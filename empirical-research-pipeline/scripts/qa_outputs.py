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
N_RE = re.compile(r"\b[ＮNn]\s*[=＝]\s*([\d,，]+)")


def check_pdf(path: str, min_width: int) -> dict:
    result = {"path": path, "exists": os.path.isfile(path), "errors": [], "warnings": []}
    if not result["exists"]:
        result["errors"].append("PDF not found")
        return result
    if fitz is None:
        result["errors"].append("PyMuPDF not installed")
        return result
    doc = fitz.open(path)
    result["pages"] = doc.page_count
    widths = []
    captions = Counter()
    n_values = set()
    for i, page in enumerate(doc):
        text = page.get_text()
        for m in CAPTION_RE.finditer(text):
            captions[f"{m.group(1)}{m.group(2)}"] += 1
        for m in N_RE.finditer(text):
            n_values.add(m.group(1))
        for im in page.get_images(full=True):
            try:
                info = doc.extract_image(im[0])
                widths.append({"page": i + 1, "width": info["width"],
                               "height": info["height"]})
            except Exception:
                continue
    doc.close()
    # Ignore logos, rules, and equation fragments: only check figure-sized images.
    figure_images = [w for w in widths
                     if w["width"] * w["height"] >= 200_000 or w["width"] >= 1000]
    low = [w for w in figure_images if w["width"] < min_width]
    result["images"] = len(widths)
    result["figure_images"] = len(figure_images)
    result["low_resolution"] = low
    result["captions"] = dict(sorted(captions.items()))
    result["n_values"] = sorted(n_values)
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
    doc = Document(path)
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
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    result["rows"] = len(rows)
    result["columns"] = len(rows[0]) if rows else 0
    if not rows:
        result["errors"].append("CSV has no data rows")
        return result
    if rows and key in rows[0]:
        keys = [r.get(key, "") for r in rows]
        counts = Counter(keys)
        dup = {k: v for k, v in counts.items() if v > 1 and k}
        result["duplicate_keys"] = len(dup)
        result["duplicate_key_examples"] = list(dup.items())[:5]
        if dup:
            result["errors"].append(f"{len(dup)} duplicate {key} value(s)")
    else:
        result["warnings"].append(f"key column not found: {key}")
    if flag and rows and flag in rows[0]:
        result["flag_counts"] = dict(Counter(r.get(flag, "") for r in rows))
    return result


def check_audit(path: str) -> dict:
    result = {"path": path, "exists": os.path.isfile(path), "errors": [], "warnings": []}
    if not result["exists"]:
        result["errors"].append("audit CSV not found")
        return result
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    result["files"] = len(rows)
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
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    result["charts"] = len(rows)
    required = {"id", "question", "chart_type", "variables", "n", "png", "pdf", "caption"}
    if rows:
        missing = required - set(rows[0].keys())
        if missing:
            result["errors"].append(f"manifest missing columns: {sorted(missing)}")
    ids = [r.get("id", "") for r in rows]
    dups = {k: v for k, v in Counter(ids).items() if k and v > 1}
    if dups:
        result["errors"].append(f"{len(dups)} duplicate chart id(s)")
    n_bad, caption_bad, file_bad = [], [], []
    for r in rows:
        try:
            n = int(float(str(r.get("n", "")).replace(",", "")))
        except ValueError:
            n_bad.append(r.get("id", "?"))
            continue
        if n <= 0:
            n_bad.append(r.get("id", "?"))
        if data_rows is not None and n > data_rows:
            n_bad.append(f"{r.get('id', '?')}(N>{data_rows})")
        cap = r.get("caption", "") or ""
        if f"N={n:,}" not in cap and f"N={n}" not in cap:
            caption_bad.append(r.get("id", "?"))
        for col in ("png", "pdf"):
            val = (r.get(col) or "").strip()
            if val and not os.path.isfile(val):
                file_bad.append(f"{r.get('id', '?')}:{col}")
    if n_bad:
        result["errors"].append(f"{len(n_bad)} chart N invalid: {n_bad[:8]}")
    if caption_bad:
        result["warnings"].append(f"{len(caption_bad)} caption(s) missing matching N=: {caption_bad[:8]}")
    if file_bad:
        result["errors"].append(f"{len(file_bad)} manifest file path(s) missing: {file_bad[:8]}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="QA the final outputs.")
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--docx", default=None)
    parser.add_argument("--figures", default=None)
    parser.add_argument("--data", default=None)
    parser.add_argument("--key", default="file", help="unique key column in CSV")
    parser.add_argument("--flag", default="in_analysis", help="analysis flag column")
    parser.add_argument("--audit", default=None)
    parser.add_argument("--manifest", default=None, help="chart_manifest.csv")
    parser.add_argument("--min-width", type=int, default=3000)
    parser.add_argument("--out", default=None, help="write JSON report here")
    parser.add_argument("--strict", action="store_true", help="exit 2 if any error")
    args = parser.parse_args()

    report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "checks": {}}
    if args.pdf:
        report["checks"]["pdf"] = check_pdf(args.pdf, args.min_width)
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
        fig_dir = os.path.abspath(args.figures)
        figs = []
        if os.path.isdir(fig_dir):
            for name in sorted(os.listdir(fig_dir)):
                if name.lower().endswith((".png", ".pdf", ".tiff")):
                    figs.append({"file": name, "bytes": os.path.getsize(os.path.join(fig_dir, name))})
        report["checks"]["figures"] = {"dir": fig_dir, "count": len(figs), "files": figs}

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
    if args.strict and errors:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
