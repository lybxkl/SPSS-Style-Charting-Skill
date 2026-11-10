#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lightweight QA for the final dataset / figures / manuscript.

Checks the things that are cheap to verify and expensive to miss:
- PDF embedded image widths (Word export downsampling)
- PDF page count and caption inventory
- DOCX inline image count and figure/table captions
- CSV duplicate keys and missing analysis flag
- corpus audit duplicate counts

It cannot judge whether the argument is correct. Use the checklist in
references/06-qa-checklist.md for that.

Usage:
    python qa_outputs.py --docx "成稿.docx" --pdf "成稿.pdf" \
        --figures "figures" --data "data/analysis.csv" \
        --audit "output/audit/corpus_audit.csv"
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

try:
    from docx import Document
except ImportError:  # pragma: no cover
    Document = None

CAPTION_RE = re.compile(
    r"^\s*(附图|图|表|Figure|Fig\.?|Table)\s*(\d+)(?=\s|[：:、.．]|$)",
    re.MULTILINE | re.IGNORECASE,
)
# N may carry thousand separators (",", full-width comma, thin/plain spaces),
# a leading "N=" and a range ("3111→2713").  Keep digits and separators only.
N_RE = re.compile(r"[ＮNn]\s*[=＝]\s*([\d,，\s]+)")
CSV_ENCODINGS = ("utf-8-sig", "gb18030", "big5")

# One column name cannot be assumed: audit writes rel_path (and relpath), older
# datasets use file, others doc_id/id.  Consumers must accept all of them.
KEY_ALIASES = ("rel_path", "relpath", "file", "path", "doc_id", "id")
N_SCOPES = ("sample", "subgroup", "corpus")
N_RANGE_SPLIT = re.compile(r"[→\-–—~～至]")


def resolve_key(header: list[str], wanted: str | None) -> tuple[str | None, list[str]]:
    """Return (column, candidates) for the unique-key column.

    ``wanted`` wins when present.  Otherwise the first alias found in the header
    is used, so an explicit --key that no longer matches the file cannot silently
    pass as a warning.
    """
    if wanted and wanted not in ("auto", "") and wanted in header:
        return wanted, [wanted]
    candidates = [c for c in KEY_ALIASES if c in header]
    if wanted and wanted not in ("auto", "") and wanted not in header:
        return (candidates[0] if candidates else None), candidates
    return (candidates[0] if candidates else None), candidates


def parse_n(value) -> tuple[int | None, bool]:
    """Parse a manifest ``n`` cell.  Returns (n, is_range).

    Accepts ``2713``, ``2 713``, ``N=2713``, ``3 111→2 713`` (first number wins).
    """
    text = str(value or "").replace("＝", "=").replace("，", ",").strip()
    text = re.sub(r"^[ＮNn]\s*=", "", text)
    is_range = bool(N_RANGE_SPLIT.search(text))
    first = N_RANGE_SPLIT.split(text)[0] if is_range else text
    digits = re.sub(r"[^\d]", "", first)
    if not digits:
        return None, is_range
    try:
        return int(digits), is_range
    except ValueError:
        return None, is_range



def read_rows(path: str) -> list[dict]:
    last_error = None
    for encoding in CSV_ENCODINGS:
        try:
            with open(path, encoding=encoding, newline="") as fh:
                return list(csv.DictReader(fh))
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def check_pdf(path: str, min_width: int = 0, min_dpi: int = 600) -> dict:
    """Check PDF pagination, captions and the *effective* resolution of figures.

    Pixel width alone is not resolution: a 15 cm figure needs 3 543 px for 600 dpi,
    so ``--min-width 3000`` accepts a 508 dpi image.  dpi is pixel width divided by
    the placed width in inches, which is what a printer sees.
    """
    result = {"path": path, "exists": os.path.isfile(path), "errors": [], "warnings": []}
    if not result["exists"]:
        result["errors"].append("PDF not found")
        return result
    if fitz is None:
        result["errors"].append("PyMuPDF not installed")
        return result
    try:
        doc = fitz.open(path)
    except Exception as exc:
        result["errors"].append(f"cannot open PDF: {type(exc).__name__}: {exc}"[:300])
        return result
    try:
        result["pages"] = doc.page_count
        widths = []
        captions = Counter()
        n_values = set()
        for i, page in enumerate(doc):
            text = page.get_text()
            for m in CAPTION_RE.finditer(text):
                captions[f"{m.group(1)}{m.group(2)}"] += 1
            for m in N_RE.finditer(text):
                n_values.add(m.group(1).strip())
            for im in page.get_images(full=True):
                try:
                    rect = page.get_image_bbox(im)
                    if rect.width <= 1 or rect.height <= 1:
                        continue
                    info = doc.extract_image(im[0])
                    dpi = info["width"] / (rect.width / 72.0)
                    widths.append({"page": i + 1, "width": info["width"],
                                   "height": info["height"],
                                   "rect_w_pt": round(rect.width, 1),
                                   "dpi": round(dpi, 1)})
                except Exception:
                    continue
    finally:
        doc.close()
    # Ignore logos, rules, equation fragments, and unused replacement xrefs:
    # a real figure occupies a box of at least ~2 cm on a side (or is large).
    def is_figure(w: dict) -> bool:
        return (w.get("rect_w_pt", 0) >= 56.7 or w["width"] * w["height"] >= 200_000)
    figure_images = [w for w in widths if is_figure(w)]
    low = [w for w in figure_images if min_width and w["width"] < min_width]
    # 15 cm at 600 dpi is 3543.3 px, so an exact 3543 px figure measures 599.9.
    # Judge with a 0.5% tolerance instead of failing perfect output on rounding.
    dpi_limit = min_dpi * 0.995 if min_dpi else 0
    low_dpi = [w for w in figure_images if dpi_limit and w["dpi"] < dpi_limit]
    result["images"] = len(widths)
    result["figure_images"] = len(figure_images)
    result["low_resolution"] = low
    result["low_dpi"] = low_dpi
    result["dpi_min"] = min((w["dpi"] for w in figure_images), default=None)
    result["captions"] = dict(sorted(captions.items()))
    result["n_values"] = sorted(n_values)
    if low_dpi:
        result["errors"].append(
            f"{len(low_dpi)} figure image(s) below {min_dpi} dpi at placed size "
            f"(min {result['dpi_min']:.0f} dpi); re-export with export_pdf_hires.py")
    if low:
        result["errors"].append(f"{len(low)} figure image(s) below {min_width}px")
    if not figure_images:
        result["warnings"].append("no figure-sized embedded images found")
    return result



def check_docx(path: str) -> dict:
    result = {"path": path, "exists": os.path.isfile(path), "errors": [], "warnings": []}
    if not result["exists"]:
        result["errors"].append("DOCX not found")
        return result
    if Document is None:
        result["errors"].append("python-docx not installed")
        return result
    try:
        doc = Document(path)
    except Exception as exc:
        result["errors"].append(f"cannot open DOCX: {type(exc).__name__}: {exc}"[:300])
        return result
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    captions = []
    for text in paragraphs:
        m = CAPTION_RE.match(text)
        if m:
            captions.append(text[:80])
    n_values = set()
    for text in paragraphs:
        for m in N_RE.finditer(text):
            n_values.add(m.group(1))
    result["paragraphs"] = len(paragraphs)
    result["inline_images"] = len(doc.inline_shapes)
    image_parts = sum(1 for rel in doc.part.rels.values()
                      if "image" in getattr(rel, "reltype", ""))
    result["image_parts"] = image_parts
    result["captions"] = captions
    result["n_values"] = sorted(n_values)
    result["tables"] = len(doc.tables)
    if (doc.inline_shapes or image_parts) and not captions:
        result["warnings"].append("images but no figure captions detected")
    return result


def check_data(path: str, key: str, flag: str | None) -> dict:
    result = {"path": path, "exists": os.path.isfile(path), "errors": [], "warnings": []}
    if not result["exists"]:
        result["errors"].append("CSV not found")
        return result
    try:
        rows = read_rows(path)
    except Exception as exc:
        result["errors"].append(f"cannot read CSV: {type(exc).__name__}: {exc}"[:300])
        return result
    result["rows"] = len(rows)
    result["columns"] = len(rows[0]) if rows else 0
    if not rows:
        result["errors"].append("CSV has no data rows")
        return result
    header = list(rows[0].keys()) if rows else []
    column, candidates = resolve_key(header, key)
    result["key"] = column
    result["key_candidates"] = candidates
    if column:
        keys = [r.get(column, "") for r in rows]
        counts = Counter(keys)
        dup = {k: v for k, v in counts.items() if v > 1 and k}
        empty = sum(1 for k in keys if not str(k).strip())
        result["duplicate_keys"] = len(dup)
        result["duplicate_key_examples"] = list(dup.items())[:5]
        result["empty_keys"] = empty
        if dup:
            result["errors"].append(f"{len(dup)} duplicate {column} value(s)")
        if empty:
            result["errors"].append(f"{empty} empty {column} value(s)")
    else:
        # A missing key column silently disabled duplicate detection in the past.
        want = f"--key {key}" if key and key != "auto" else "any of " + "/".join(KEY_ALIASES)
        result["errors"].append(
            f"key column not found ({want}); columns are {header[:12]}")
    if flag and rows and flag in rows[0]:
        result["flag_counts"] = dict(Counter(r.get(flag, "") for r in rows))
    return result


def check_audit(path: str) -> dict:
    result = {"path": path, "exists": os.path.isfile(path), "errors": [], "warnings": []}
    if not result["exists"]:
        result["errors"].append("audit CSV not found")
        return result
    try:
        rows = read_rows(path)
    except Exception as exc:
        result["errors"].append(f"cannot read audit CSV: {type(exc).__name__}: {exc}"[:300])
        return result
    result["files"] = len(rows)
    if not rows:
        result["errors"].append("audit CSV has no rows")
    result["status"] = dict(Counter(r.get("status", "") for r in rows))
    result["duplicate_groups"] = len({r.get("dup_group") for r in rows if r.get("dup_group")})
    result["duplicate_files"] = sum(1 for r in rows if r.get("dup_role") == "duplicate")
    if result["duplicate_files"]:
        result["warnings"].append(f"{result['duplicate_files']} duplicate copies still present in audit")
    return result


def check_manifest(path: str, data_rows: int | None = None) -> dict:
    """Check chart_manifest.csv: required columns, N, captions, and files."""
    result = {"path": path, "exists": os.path.isfile(path), "errors": [], "warnings": []}
    if not result["exists"]:
        result["errors"].append("manifest not found")
        return result
    try:
        rows = read_rows(path)
    except Exception as exc:
        result["errors"].append(f"cannot read manifest: {type(exc).__name__}: {exc}"[:300])
        return result
    result["charts"] = len(rows)
    if not rows:
        result["errors"].append("manifest has no chart rows")
    required = {"id", "question", "chart_type", "variables", "n", "png", "pdf", "caption"}
    if rows:
        missing = required - set(rows[0].keys())
        if missing:
            result["errors"].append(f"manifest missing columns: {sorted(missing)}")
    ids = [r.get("id", "") for r in rows]
    dups = {k: v for k, v in Counter(ids).items() if k and v > 1}
    if dups:
        result["errors"].append(f"{len(dups)} duplicate chart id(s)")
    n_bad, caption_bad, file_bad, scope_bad, range_notes = [], [], [], [], []
    for r in rows:
        cid = r.get("id", "?")
        n, is_range = parse_n(r.get("n", ""))
        if n is None or n <= 0:
            n_bad.append(cid)
            continue
        scope = (r.get("n_scope") or "sample").strip().lower() or "sample"
        if scope not in N_SCOPES:
            scope_bad.append(f"{cid}:{scope}")
            scope = "sample"
        if is_range:
            range_notes.append(f"{cid}={r.get('n')}")
        if data_rows is not None and n > data_rows:
            if scope == "corpus":
                result["warnings"].append(
                    f"{cid}: corpus-scope N={n} > data rows {data_rows} (expected for funnel charts)")
            else:
                n_bad.append(f"{cid}(N>{data_rows},{scope})")
        cap = (r.get("caption", "") or "").replace("，", ",")
        cap = re.sub(r"[\s\u00a0]+", "", cap).replace("＝", "=").upper()
        if f"N={n:,}".upper() not in cap and f"N={n}".upper() not in cap:
            caption_bad.append(cid)
        for col in ("png", "pdf"):
            val = (r.get(col) or "").strip()
            if val and not os.path.isfile(val):
                beside_manifest = os.path.join(os.path.dirname(os.path.abspath(path)), val)
                if not os.path.isfile(beside_manifest):
                    file_bad.append(f"{cid}:{col}")
        # Optional manifest v2 columns: validate when present.
        for col in ("dpi", "px_width"):
            raw = (r.get(col) or "").strip()
            if raw:
                try:
                    if float(raw) <= 0:
                        raise ValueError(raw)
                except ValueError:
                    result["warnings"].append(f"{cid}: invalid {col}={raw!r}")
    if n_bad:
        result["errors"].append(f"{len(n_bad)} chart N invalid: {n_bad[:8]}")
    if caption_bad:
        result["warnings"].append(f"{len(caption_bad)} caption(s) missing matching N=: {caption_bad[:8]}")
    if file_bad:
        result["errors"].append(f"{len(file_bad)} manifest file path(s) missing: {file_bad[:8]}")
    if scope_bad:
        result["warnings"].append(f"{len(scope_bad)} chart(s) with unknown n_scope: {scope_bad[:8]}")
    if range_notes:
        result["range_n"] = range_notes[:12]
    return result


def check_figures(path: str, min_dpi: int = 600, width_cm: float = 15.0) -> dict:
    """Check the raster figures in a directory for real resolution.

    Counting files is not QA: a 72 dpi PNG passed the old check.  For each image
    report its pixel size, the dpi recorded in the file, and the dpi it would have
    if printed at ``width_cm`` — the last one is the number the journal cares about.
    """
    result = {"dir": os.path.abspath(path), "exists": os.path.isdir(path),
              "errors": [], "warnings": [], "files": []}
    if not result["exists"]:
        result["errors"].append("figures directory not found")
        return result
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        Image = None
    low, no_meta = [], []
    # Same 0.5% tolerance as check_pdf: 15 cm at 600 dpi is 3543.3 px, and a
    # 3543 px file lands on 599.9 -- a rounding artefact, not a low-res export.
    dpi_limit = min_dpi * 0.995 if min_dpi else 0
    for name in sorted(os.listdir(path)):
        if not name.lower().endswith((".png", ".tif", ".tiff", ".jpg", ".jpeg")):
            continue
        full = os.path.join(path, name)
        info = {"file": name, "bytes": os.path.getsize(full)}
        if Image is not None:
            try:
                with Image.open(full) as im:
                    w, h = im.size
                    meta = im.info.get("dpi")
                info.update({"px_width": w, "px_height": h,
                             "dpi_meta": round(float(meta[0]), 1) if meta else None,
                             "dpi_at_width": round(w / (width_cm / 2.54), 1)})
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {exc}"[:120]
        result["files"].append(info)
        if info.get("dpi_at_width") is None:
            continue
        if dpi_limit and info["dpi_at_width"] < dpi_limit:
            low.append(f"{name}({info['dpi_at_width']:.0f}dpi)")
        elif not info.get("dpi_meta"):
            no_meta.append(name)
    result["count"] = len(result["files"])
    result["min_dpi"] = min_dpi
    result["width_cm"] = width_cm
    if not result["files"]:
        result["warnings"].append("no image files found")
    if low:
        result["errors"].append(
            f"{len(low)} figure(s) below {min_dpi} dpi at {width_cm} cm wide: {low[:8]}")
    if no_meta:
        result["warnings"].append(
            f"{len(no_meta)} figure(s) carry no dpi metadata (pixel size is still checked)")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="QA the final outputs.")
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--docx", default=None)
    parser.add_argument("--figures", default=None)
    parser.add_argument("--data", default=None)
    parser.add_argument("--key", default="auto",
                        help="unique key column (default auto: " + "/".join(KEY_ALIASES) + ")")
    parser.add_argument("--flag", default="in_analysis", help="analysis flag column")
    parser.add_argument("--audit", default=None)
    parser.add_argument("--manifest", default=None, help="chart_manifest.csv")
    parser.add_argument("--min-dpi", type=int, default=600,
                        help="required effective resolution of figures (0 disables)")
    parser.add_argument("--min-width", type=int, default=0,
                        help="legacy pixel-width check (0 disables)")
    parser.add_argument("--figure-width-cm", type=float, default=15.0,
                        help="printed width used to compute figure dpi")
    parser.add_argument("--out", default=None, help="write JSON report here")
    parser.add_argument("--strict", action="store_true", help="(kept for compatibility; errors already exit 2)")
    parser.add_argument("--exit-zero", action="store_true",
                        help="always exit 0 even when errors are found (do not use in CI)")
    args = parser.parse_args()

    report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "checks": {}}
    if args.pdf:
        report["checks"]["pdf"] = check_pdf(args.pdf, args.min_width, args.min_dpi)
    if args.docx:
        report["checks"]["docx"] = check_docx(args.docx)
    if args.data:
        report["checks"]["data"] = check_data(args.data, args.key, args.flag)
    if args.audit:
        report["checks"]["audit"] = check_audit(args.audit)
    if args.manifest:
        data_rows = None
        if args.data:
            data_report = report["checks"].get("data") or {}
            data_rows = data_report.get("rows")
        report["checks"]["manifest"] = check_manifest(args.manifest, data_rows)
    if args.figures:
        report["checks"]["figures"] = check_figures(
            args.figures, args.min_dpi, args.figure_width_cm)

    if not report["checks"]:
        print("ERROR: no check targets supplied", file=sys.stderr)
        return 2

    errors = sum(len(v.get("errors", [])) for v in report["checks"].values())
    warnings = sum(len(v.get("warnings", [])) for v in report["checks"].values())
    report["error_count"] = errors
    report["warning_count"] = warnings

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors and not args.exit_zero:
        print(f"QA FAILED: {errors} error(s), {warnings} warning(s)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
