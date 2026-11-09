#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export a Word document to PDF and restore full-resolution figures.

Word's PDF exporter downsamples embedded images to roughly 200 dpi. The docx
still contains the original images, so after exporting we locate each figure by
its caption ("图1" + title) and replace the compressed image with the source at
the same display rectangle.

Requires Windows + Microsoft Word (win32com) + PyMuPDF.

Usage:
    python export_pdf_hires.py --docx "成稿.docx" --out-pdf "成稿.pdf" \\
        --figure-map "figure_map.json"

figure_map.json:
    [
      {"tag": "图1", "title": "样本类别结构", "image": "figures/fig1.png"},
      {"tag": "图2", "title": "处理阶段与结果发生率", "image": "figures/fig2.png"}
    ]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def tag_hit(text: str, tag: str, title: str) -> tuple[bool, bool]:
    """Return (any_boundary_hit, caption_line_hit) for a caption tag."""
    tag_n = norm(tag)
    title_n = norm(title)
    if not tag_n:
        return False, False
    pattern = re.compile(re.escape(tag_n) + r"(?!\d)")
    any_hit = False
    line_hit = False
    for line in (text or "").splitlines():
        line_n = norm(line)
        if not pattern.search(line_n):
            continue
        any_hit = True
        if title_n and title_n not in line_n:
            continue
        if line_n.startswith(tag_n):
            line_hit = True
            break
    if not any_hit:
        whole = norm(text)
        any_hit = bool(pattern.search(whole)) and (not title_n or title_n in whole)
    return any_hit, line_hit


def load_map(path: str | None) -> list[dict]:
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        out = []
        for tag, value in data.items():
            if isinstance(value, str):
                out.append({"tag": tag, "title": "", "image": value})
            else:
                out.append({"tag": tag, "title": value.get("title", ""),
                            "image": value.get("image", "")})
        return out
    return data


def word_export(docx: str, raw_pdf: str) -> None:
    try:
        import win32com.client
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("win32com is unavailable; install pywin32 and Microsoft Word") from exc
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = None
    try:
        doc = word.Documents.Open(os.path.abspath(docx), ReadOnly=True)
        doc.SaveAs(os.path.abspath(raw_pdf), FileFormat=17)
    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()


def find_figure_page(pdf, tag: str, title: str):
    """Return the page with the largest image area that contains the caption."""
    best = None
    for page in pdf:
        text = page.get_text("text")
        any_hit, line_hit = tag_hit(text, tag, title)
        if not any_hit:
            continue
        best_area = 0
        best_xref = None
        for im in page.get_images(full=True):
            try:
                rect = page.get_image_bbox(im)
                area = abs(rect.width * rect.height)
            except Exception:
                continue
            if area > best_area:
                best_area, best_xref = area, im[0]
        if best_xref is None:
            continue
        score = (line_hit, best_area)
        if best is None or score > best[0]:
            best = (score, page, best_xref)
    return (best[1], best[2]) if best else None


def image_widths(pdf) -> list[dict]:
    out = []
    for i, page in enumerate(pdf):
        for im in page.get_images(full=True):
            try:
                info = pdf.extract_image(im[0])
                out.append({"page": i + 1, "xref": im[0],
                            "width": info["width"], "height": info["height"]})
            except Exception:
                continue
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Word→PDF with 600 dpi figure backfill.")
    parser.add_argument("--docx", required=True)
    parser.add_argument("--out-pdf", required=True)
    parser.add_argument("--figure-map", default=None)
    parser.add_argument("--raw-pdf", default=None, help="keep the Word-exported PDF here")
    parser.add_argument("--min-width", type=int, default=3000,
                        help="warn if an embedded image is narrower than this")
    parser.add_argument("--no-backfill", action="store_true")
    args = parser.parse_args()

    if fitz is None:
        print("ERROR: PyMuPDF not installed. Run: pip install pymupdf", file=sys.stderr)
        return 2
    docx = os.path.abspath(args.docx)
    out_pdf = os.path.abspath(args.out_pdf)
    if not os.path.isfile(docx):
        print(f"ERROR: docx not found: {docx}", file=sys.stderr)
        return 2
    if args.raw_pdf and os.path.abspath(args.raw_pdf) == out_pdf:
        print("ERROR: --raw-pdf must differ from --out-pdf", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    figures = load_map(args.figure_map)

    tmp = None
    if args.raw_pdf:
        raw = os.path.abspath(args.raw_pdf)
    else:
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(out_pdf))
        os.close(fd)
        raw = tmp

    try:
        try:
            word_export(docx, raw)
        except Exception as exc:
            print(f"ERROR: Word export failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        pdf = fitz.open(raw)
        replaced = []
        if not args.no_backfill:
            for item in figures:
                tag, title, image = item.get("tag", ""), item.get("title", ""), item.get("image", "")
                if not image or not os.path.isfile(image):
                    print(f"WARN: image missing for {tag}: {image}", file=sys.stderr)
                    continue
                hit = find_figure_page(pdf, tag, title)
                if not hit:
                    print(f"WARN: caption not found: {tag} {title}", file=sys.stderr)
                    continue
                page, xref = hit
                page.replace_image(xref, filename=os.path.abspath(image))
                replaced.append({"tag": tag, "page": page.number + 1, "image": image})
        pdf.save(out_pdf, garbage=3, deflate=True)
        widths = image_widths(pdf)
        pdf.close()
        low = [w for w in widths if w["width"] < args.min_width]
        report = {
            "docx": docx,
            "pdf": out_pdf,
            "figures_replaced": replaced,
            "images": widths,
            "low_resolution": low,
            "min_width": args.min_width,
        }
        report_path = os.path.splitext(out_pdf)[0] + "_export_report.json"
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        check = fitz.open(out_pdf)
        pages = check.page_count
        check.close()
        print(f"pages: {pages}")
        print(f"figures replaced: {len(replaced)}")
        print(f"embedded images: {len(widths)}; below {args.min_width}px: {len(low)}")
        for w in low:
            print(f"  LOW p{w['page']}: {w['width']}x{w['height']}")
        print(f"report: {report_path}")
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
