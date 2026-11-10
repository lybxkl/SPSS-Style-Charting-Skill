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

# Stamped into the export report. An artefact on disk has to say which script
# produced it: "the picture looked old" is otherwise undebuggable a week later.
SCRIPT_VERSION = "2.0.0"

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
            elif isinstance(value, dict):
                out.append({"tag": tag, "title": value.get("title", ""),
                            "image": value.get("image", "")})
            else:
                out.append({"tag": str(tag), "title": "", "image": ""})
        return out
    if not isinstance(data, list):
        raise ValueError("figure map must be a JSON list or object")
    return [item for item in data if isinstance(item, dict)]


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


def caption_rect(page, tag: str, title: str):
    """Return the caption rectangle so the nearest image can be selected."""
    tag_n = norm(tag)
    title_n = norm(title)
    if not tag_n:
        return None
    pattern = re.compile(re.escape(tag_n) + r"(?!\d)")
    for block in page.get_text("blocks"):
        block_text = norm(block[4] if len(block) > 4 else "")
        if pattern.search(block_text) and (not title_n or title_n in block_text):
            return fitz.Rect(block[:4])
    for rect in page.search_for(tag):
        return rect
    return None


def find_figure_page(pdf, tag: str, title: str):
    """Return the page and image closest to the caption.

    Two figures can share a page; picking the page's largest image would
    backfill the wrong figure or overwrite the first one twice.
    """
    best = None
    for page in pdf:
        text = page.get_text("text")
        any_hit, line_hit = tag_hit(text, tag, title)
        if not any_hit:
            continue
        cap = caption_rect(page, tag, title)
        best_score = None
        best_xref = None
        for im in page.get_images(full=True):
            try:
                rect = page.get_image_bbox(im)
            except Exception:
                continue
            if rect.width <= 1 or rect.height <= 1:
                continue
            area = abs(rect.width * rect.height)
            if cap is None:
                score = (0, 0.0, -area)
            else:
                if rect.y1 <= cap.y0:
                    gap = cap.y0 - rect.y1
                elif rect.y0 >= cap.y1:
                    gap = rect.y0 - cap.y1
                else:
                    gap = 0.0
                overlap = max(0.0, min(rect.x1, cap.x1) - max(rect.x0, cap.x0))
                score = (0 if overlap > 0 else 1, gap, -area)
            if best_score is None or score < best_score:
                best_score, best_xref = score, im[0]
        if best_xref is None:
            continue
        page_score = (0 if line_hit else 1, best_score[1], best_score[2])
        if best is None or page_score < best[0]:
            best = (page_score, page, best_xref)
    return (best[1], best[2]) if best else None


def image_widths(pdf) -> list[dict]:
    """Only count placed figure images; report the effective resolution too.

    ``width`` alone cannot tell 600 dpi from 200 dpi: a 15 cm figure at 200 dpi is
    1180 px, and Word's PDF export caps bitmaps near 220 dpi no matter what the
    DOCX contains.  ``dpi`` is computed from the placement rectangle, which is the
    number that actually matters for print.
    """
    out = []
    for i, page in enumerate(pdf):
        for im in page.get_images(full=True):
            try:
                rect = page.get_image_bbox(im)
                if rect.width <= 1 or rect.height <= 1:
                    continue
                info = pdf.extract_image(im[0])
            except Exception:
                continue
            # A 1 cm rule or a logo is not a figure; require a real placement box.
            small = rect.width < 56.7 and rect.height < 56.7   # ~2 cm x 2 cm
            if small and info["width"] * info["height"] < 200_000:
                continue
            dpi = info["width"] / (rect.width / 72.0)
            out.append({"page": i + 1, "xref": im[0],
                        "width": info["width"], "height": info["height"],
                        "rect_w_pt": round(rect.width, 1), "dpi": round(dpi, 1)})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Word→PDF with 600 dpi figure backfill.")
    parser.add_argument("--docx", required=True)
    parser.add_argument("--out-pdf", required=True)
    parser.add_argument("--figure-map", default=None)
    parser.add_argument("--raw-pdf", default=None, help="keep the Word-exported PDF here")
    parser.add_argument("--min-width", type=int, default=3000,
                        help="fail if an embedded image is narrower than this (0 disables)")
    parser.add_argument("--min-dpi", type=int, default=600,
                        help="fail if an embedded figure resolves below this at its placed size")
    parser.add_argument("--allow-low", action="store_true",
                        help="only warn about low-resolution figures instead of failing")
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
    if args.figure_map and not os.path.isfile(args.figure_map):
        print(f"ERROR: figure map not found: {args.figure_map}", file=sys.stderr)
        return 2
    try:
        figures = load_map(args.figure_map)
    except Exception as exc:
        print(f"ERROR: cannot read figure map: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

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
                # replace_image only swaps the stream; the old bitmap stays in
                # /Resources until the page content is rewritten.  Without this
                # the file keeps both copies (9.8 MB -> 5.3 MB in our test).
                page.clean_contents(sanitize=True)
                replaced.append({"tag": tag, "page": page.number + 1, "image": image})
        # garbage=4 also drops the now-unreferenced image objects.
        pdf.save(out_pdf, garbage=4, deflate=True)
        widths = image_widths(pdf)
        pdf.close()
        low = [w for w in widths if args.min_width and w["width"] < args.min_width]
        low_dpi = [w for w in widths if args.min_dpi and w["dpi"] < args.min_dpi]
        report = {
            "docx": docx,
            "pdf": out_pdf,
            "figures_replaced": replaced,
            "images": widths,
            "low_resolution": low,
            "low_dpi": low_dpi,
            "min_width": args.min_width,
            "min_dpi": args.min_dpi,
            "script_version": SCRIPT_VERSION,
        }
        report_path = os.path.splitext(out_pdf)[0] + "_export_report.json"
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        check = fitz.open(out_pdf)
        pages = check.page_count
        check.close()
        print(f"pages: {pages}")
        print(f"figures replaced: {len(replaced)}")
        print(f"embedded figures: {len(widths)}; "
              f"below {args.min_width}px: {len(low)}; below {args.min_dpi} dpi: {len(low_dpi)}")
        for w in low_dpi:
            print(f"  LOW-DPI p{w['page']}: {w['width']}x{w['height']} "
                  f"@ {w['dpi']:.0f} dpi (placed {w['rect_w_pt']} pt wide)")
        for w in low:
            print(f"  LOW-WIDTH p{w['page']}: {w['width']}x{w['height']}")
        print(f"report: {report_path}")
        if (low or low_dpi) and not args.allow_low:
            print("ERROR: figure resolution below target; fix the source images "
                  "or pass --allow-low to downgrade this to a warning.", file=sys.stderr)
            return 2
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
