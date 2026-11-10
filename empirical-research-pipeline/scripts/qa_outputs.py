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
import math
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

# Colour QA.  A 7-class figure whose colours all sit at the same lightness is
# unreadable in print (black-and-white) even when it looks fine on screen, and
# two hues that survive as "blue vs blue" under deuteranopia are the same
# problem in colour.  Thresholds are the usual editorial minima.
MIN_DELTA_L = 10.0      # CIE L* difference for two colours to be separable in gray
MIN_DELTA_E = 8.0       # CIE76 difference after simulated colour-vision deficiency
MIN_DELTA_CHROMA = 6.0  # ... and the (Δa*, Δb*) part alone, i.e. hue survival
DEFAULT_CYCLE = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                 "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf")
# Machado, Oliveira & Fernandes (2009) severity 1.0, applied in LINEAR RGB.
CVD_MATRICES = {
    "protanopia": ((0.152286, 1.052583, -0.204868),
                   (0.114503, 0.786281, 0.099216),
                   (-0.003882, -0.048116, 1.051998)),
    "deuteranopia": ((0.367322, 0.860646, -0.227968),
                     (0.280085, 0.672501, 0.047413),
                     (-0.011820, 0.042940, 0.968881)),
}
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


# --------------------------------------------------------------------- colour

def hex_to_rgb(color: str) -> tuple[float, float, float] | None:
    """``#2F5C8A`` -> (0.18, 0.36, 0.54) in sRGB [0, 1]; ``None`` if unparseable."""
    text = str(color or "").strip()
    match = _HEX_RE.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return tuple(int(digits[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    try:  # matplotlib colour names ("tab:blue", "green", ...)
        from matplotlib.colors import to_rgb
        return tuple(float(v) for v in to_rgb(text))
    except Exception:
        return None


def _srgb_to_linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel: float) -> float:
    channel = min(max(channel, 0.0), 1.0)
    return channel * 12.92 if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055


def rgb_to_lab(rgb) -> tuple[float, float, float]:
    """sRGB (0-1) -> CIE Lab (D65).  Hand-rolled: no colour-science dependency."""
    r, g, b = (_srgb_to_linear(float(v)) for v in rgb)
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def lightness(color: str) -> float | None:
    rgb = hex_to_rgb(color)
    return None if rgb is None else rgb_to_lab(rgb)[0]


def delta_e76(first, second) -> float:
    lab_a, lab_b = rgb_to_lab(first), rgb_to_lab(second)
    return float(sum((a - b) ** 2 for a, b in zip(lab_a, lab_b)) ** 0.5)


def simulate_cvd(rgb, kind: str = "deuteranopia"):
    """Apply a Machado 2009 matrix in linear RGB and return sRGB (0-1)."""
    linear = [_srgb_to_linear(float(v)) for v in rgb]
    matrix = CVD_MATRICES[kind]
    out = [sum(matrix[row][col] * linear[col] for col in range(3)) for row in range(3)]
    return tuple(_linear_to_srgb(v) for v in out)


def parse_palette(cell) -> list[str]:
    """``"#1C4E7B;#E18560"`` -> colour list (separators: ; , whitespace |)."""
    if not cell:
        return []
    return [part for part in re.split(r"[;,|\s]+", str(cell).strip()) if part]


def check_palette(colors: list[str], colorblind: bool = False,
                  min_delta_l: float = MIN_DELTA_L,
                  min_delta_e: float = MIN_DELTA_E) -> dict:
    """Grayscale and colour-vision separability of one palette.

    Every pair must differ by at least ``min_delta_l`` in CIE L* to survive
    printing, and (when ``colorblind``) by ``min_delta_e`` after simulating
    deuteranopia/protanopia.
    """
    result = {"colors": list(colors), "errors": [], "warnings": []}
    usable = [(c, hex_to_rgb(c)) for c in colors]
    usable = [(c, rgb) for c, rgb in usable if rgb is not None]
    result["unparsed"] = [c for c in colors if hex_to_rgb(c) is None]
    if len(usable) < 2:
        return result
    gray_pairs = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            (name_a, rgb_a), (name_b, rgb_b) = usable[i], usable[j]
            dl = abs(rgb_to_lab(rgb_a)[0] - rgb_to_lab(rgb_b)[0])
            gray_pairs.append({"a": name_a, "b": name_b, "delta_l": round(dl, 2)})
            if dl < min_delta_l:
                result["errors"].append(
                    f"grayscale: {name_a} vs {name_b} ΔL*={dl:.1f} < {min_delta_l:g}")
    result["gray_pairs"] = gray_pairs
    result["min_delta_l"] = round(min((p["delta_l"] for p in gray_pairs), default=0.0), 2)
    if colorblind:
        cv_pairs = []
        for i in range(len(usable)):
            for j in range(i + 1, len(usable)):
                (name_a, rgb_a), (name_b, rgb_b) = usable[i], usable[j]
                worst = 0.0
                worst_kind = ""
                chroma = 0.0
                for kind in CVD_MATRICES:
                    lab_a = rgb_to_lab(simulate_cvd(rgb_a, kind))
                    lab_b = rgb_to_lab(simulate_cvd(rgb_b, kind))
                    de = float(sum((x - y) ** 2 for x, y in zip(lab_a, lab_b)) ** 0.5)
                    if worst_kind == "" or de < worst:
                        worst, worst_kind = de, kind
                        # ΔE76 is dominated by ΔL*, which the grayscale gate has
                        # already forced to >=10; only the (Δa*, Δb*) part tells us
                        # whether the two hues survive the simulation.
                        chroma = math.hypot(lab_a[1] - lab_b[1], lab_a[2] - lab_b[2])
                cv_pairs.append({"a": name_a, "b": name_b,
                                 "delta_e": round(worst, 2), "sim": worst_kind,
                                 "delta_chroma": round(chroma, 2)})
                if chroma < MIN_DELTA_CHROMA:
                    result["warnings"].append(
                        f"colour blind ({worst_kind}): {name_a} vs {name_b} "
                        f"chromatic distance={chroma:.1f} < {MIN_DELTA_CHROMA:g} "
                        f"(ΔE={worst:.1f}): the two "
                        f"series look alike to colour-blind readers")
        result["cvd_pairs"] = cv_pairs
        result["min_delta_e"] = round(min((p["delta_e"] for p in cv_pairs), default=0.0), 2)
    return result



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


def check_pdf(path: str, min_width: int = 0, min_dpi: int = 600,
              min_fontsize: float | None = None,
              target_width_cm: float | None = None,
              allow_raster_text: bool = False,
              raster_expected: bool = False) -> dict:
    """Check PDF pagination, captions, figure resolution and *placed* font size.

    Pixel width alone is not resolution: a 15 cm figure needs 3 543 px for 600 dpi,
    so ``--min-width 3000`` accepts a 508 dpi image.  dpi is pixel width divided by
    the placed width in inches, which is what a printer sees.

    Fonts are judged after placement, not as exported: a figure designed 15 cm
    wide and printed at 13.2 cm scales every glyph by 0.88, so an 8.5 pt label
    arrives at 7.48 pt and a 7.2 pt tick at 6.34 pt.  The ratio is taken against
    the **placed width of the figure**, not the page: a 15 cm figure on an A4
    page is scaled 1.0, not 0.71.  Text outside any figure box (body, captions)
    is judged at its nominal size, so page-width arithmetic cannot fabricate
    hundreds of "too small" spans.  Pass ``target_width_cm=0`` to disable.

    A figure that is a pure bitmap has no text layer, so its type can never be
    verified here.  Whether that is a defect depends on the object being checked:
    in a **manuscript** (``raster_expected=True``) embedded PNGs are the normal
    Word -> PDF shape, so a bitmap at a sufficient effective dpi is a *warning*
    telling the reader to check type in the source figure PDF; a flattened
    **figure** PDF handed in directly (``raster_expected=False``) is an error,
    because vector art that lost its text layer is a delivery defect.
    ``allow_raster_text`` silences the difference and downgrades both.
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
        fonts = []
        raster_figures = []
        single_page = doc.page_count == 1
        for i, page in enumerate(doc):
            text = page.get_text()
            for m in CAPTION_RE.finditer(text):
                captions[f"{m.group(1)}{m.group(2)}"] += 1
            for m in N_RE.finditer(text):
                n_values.add(m.group(1).strip())
            # Where the figures actually sit on this page, and how much each one
            # is scaled relative to its design width.
            placements = []
            page_images = []
            for im in page.get_images(full=True):
                try:
                    rect = page.get_image_bbox(im)
                    if rect.width <= 1 or rect.height <= 1:
                        continue
                    info = doc.extract_image(im[0])
                except Exception:
                    continue
                page_images.append((im, rect, info))
                if target_width_cm and rect.width > 0:
                    placed_cm = float(rect.width) / 72.0 * 2.54
                    placements.append((rect, float(target_width_cm) / placed_cm))
            # No image box on a ONE-page PDF: the PDF *is* the figure (vector
            # export) and its page width is the design width.  In a multi-page
            # manuscript a page without a measurable figure box gives us nothing
            # to divide by, so text keeps its nominal size instead of being
            # scaled by the page and reported as "too small".
            page_cm = float(page.rect.width) / 72.0 * 2.54 if page.rect.width else 0.0
            page_scale = (float(target_width_cm) / page_cm
                          if (not placements and single_page and target_width_cm
                              and page_cm > 0)
                          else 1.0)

            def placed_scale(bbox):
                if not placements:
                    return page_scale
                cx = (bbox[0] + bbox[2]) / 2.0
                cy = (bbox[1] + bbox[3]) / 2.0
                for rect, value in placements:
                    if (rect.x0 - 1.0 <= cx <= rect.x1 + 1.0
                            and rect.y0 - 1.0 <= cy <= rect.y1 + 1.0):
                        return value
                return 1.0

            page_fonts = []
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        try:
                            size = float(span.get("size") or 0.0)
                        except (TypeError, ValueError):
                            continue
                        if size <= 0:
                            continue
                        bbox = span.get("bbox") or (0.0, 0.0, 0.0, 0.0)
                        scale = placed_scale(bbox)
                        entry = {
                            "page": i + 1,
                            "size": round(size, 2),
                            "effective": round(size * scale, 2),
                            "text": str(span.get("text", "")).strip()[:40],
                        }
                        fonts.append(entry)
                        page_fonts.append((entry, bbox))
            for im, rect, info in page_images:
                dpi = info["width"] / (rect.width / 72.0)
                widths.append({"page": i + 1, "width": info["width"],
                               "height": info["height"],
                               "rect_w_pt": round(rect.width, 1),
                               "dpi": round(dpi, 1)})
                if not raster_expected:
                    # A figure PDF is judged per page, not per image: an imshow
                    # panel (heatmap, matrix) is a legitimate raster element and
                    # its axis labels are vector text.  Only a page that carries
                    # essentially no text at all is a rasterised export.
                    continue
                inside = 0
                for _entry, bbox in page_fonts:
                    cx = (bbox[0] + bbox[2]) / 2.0
                    cy = (bbox[1] + bbox[3]) / 2.0
                    if (rect.x0 - 1.0 <= cx <= rect.x1 + 1.0
                            and rect.y0 - 1.0 <= cy <= rect.y1 + 1.0):
                        inside += 1
                if not inside and rect.width >= 56.7 and rect.height >= 56.7:
                    # A figure-sized box with no text inside is a bitmap: its
                    # labels cannot be measured, so the type gate would pass
                    # vacuously.  Thin boxes (colour bars, rules) are skipped.
                    raster_figures.append({
                        "page": i + 1,
                        "width": info["width"],
                        "height": info["height"],
                        "rect_w_pt": round(rect.width, 1),
                        "dpi": round(info["width"] / (rect.width / 72.0), 1),
                    })
            if not raster_expected and page_images and len(page_fonts) < 3:
                info = page_images[0][2]
                raster_figures.append({
                    "page": i + 1,
                    "width": info["width"],
                    "height": info["height"],
                    "rect_w_pt": round(page_images[0][1].width, 1),
                    "dpi": round(info["width"] / (page_images[0][1].width / 72.0), 1),
                })
    finally:
        doc.close()
    # Ignore logos, rules, equation fragments, and unused replacement xrefs:
    # a real figure occupies a box of at least ~2 cm on a side (or is large).
    def is_figure(w: dict) -> bool:
        return (w.get("rect_w_pt", 0) >= 56.7 or w["width"] * w["height"] >= 200_000)
    figure_images = [w for w in widths if is_figure(w)]
    # Say how many bitmaps were skipped as non-figures: silently dropping 40
    # xrefs made "0 figures" look like a clean PDF.
    result["images_checked"] = len(figure_images)
    result["images_skipped"] = len(widths) - len(figure_images)
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
    result["font_sizes"] = sorted({f["size"] for f in fonts})
    result["font_spans"] = len(fonts)
    result["min_fontsize"] = min((f["size"] for f in fonts), default=None)
    result["min_fontsize_effective"] = min((f["effective"] for f in fonts), default=None)
    if raster_figures:
        result["raster_figures"] = raster_figures
    def _raster_verdict():
        """(kind, message) for the bitmap figures found on the pages."""
        pages = [r["page"] for r in raster_figures][:6]
        least_dpi = min((r.get("dpi") or 0.0) for r in raster_figures)
        enough_resolution = (not min_dpi) or least_dpi >= dpi_limit
        if allow_raster_text or not min_fontsize or (raster_expected and enough_resolution):
            # A manuscript's embedded PNGs are its normal shape.  Say what could
            # not be measured and where to measure it instead.
            return ("warnings",
                    f"no_text_layer: {len(raster_figures)} figure(s) are bitmaps "
                    f"(pages {pages}, {least_dpi:g} dpi) -- the pixel resolution is "
                    f"fine, but their type cannot be read from a bitmap; check font "
                    f"size in the source figure PDF (qa_outputs --pdf FigureN.pdf)")
        if raster_expected:
            return ("errors",
                    f"no_text_layer: {len(raster_figures)} bitmap figure(s) "
                    f"(pages {pages}) are below {min_dpi:g} dpi ({least_dpi:g} dpi) and "
                    f"carry no text layer, so neither resolution nor type can be "
                    f"justified")
        return ("errors",
                f"no_text_layer: {len(raster_figures)} figure(s) in this PDF are "
                f"bitmaps (pages {pages}), so their type could not be measured; "
                f"export vector art, or confirm the type before running "
                f"export_pdf_hires")

    if raster_figures and (min_fontsize or not fonts):
        kind, message = _raster_verdict()
        result[kind].append(message)
    elif not fonts:
        message = ("no_text_layer: the PDF has no text spans at all, so font size "
                   "cannot be verified (rasterized export); check the source "
                   "PDF/PNG instead")
        if allow_raster_text or not min_fontsize:
            result["warnings"].append(message)
        else:
            result["errors"].append(message)
    low_font = []
    if min_fontsize:
        low_font = [f for f in fonts if f["effective"] < float(min_fontsize) - 1e-6]
        result["min_fontsize_limit"] = float(min_fontsize)
        result["low_font"] = low_font[:20]
        result["low_font_count"] = len(low_font)
        if low_font:
            smallest = min(f["effective"] for f in low_font)
            result["errors"].append(
                f"{len(low_font)} text span(s) below {float(min_fontsize):g} pt after "
                f"placement (smallest {smallest:g} pt): {low_font[:5]}")
    else:
        result["low_font"] = []
        result["low_font_count"] = 0
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


def check_manifest(path: str, data_rows: int | None = None,
                   graycheck: bool = True, colorblind: bool = False,
                   min_delta_l: float = MIN_DELTA_L,
                   min_delta_e: float = MIN_DELTA_E) -> dict:
    """Check chart_manifest.csv: required columns, N, captions, files, palettes."""
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
    n_unknown: list[str] = []
    palette_rows: list[dict] = []
    for r in rows:
        cid = r.get("id", "?")
        raw_n = (r.get("n") or "").strip()
        # "NA" is a producer saying "I do not know the sample size".  It must not
        # be silently replaced by a row count, and it is a warning, not an error:
        # the figure itself can still be correct.
        unknown_n = raw_n.upper() in {"", "NA", "N/A", "N.A.", "-", "—", "?", "NONE"}
        n, is_range = parse_n(raw_n)
        if unknown_n:
            n_unknown.append(cid)
        elif n is None or n <= 0:
            n_bad.append(cid)
        if not unknown_n and n is not None and n > 0:
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
        # Grayscale / colour-vision separability.  A declared ``palette`` is
        # authoritative and a bad one is an ERROR.  A row may instead state
        # ``n_series``, in which case the default matplotlib cycle it most likely
        # used is checked and reported as a warning only.  Without either, the
        # real colours are unknown -- guessing them from tick labels produced
        # nothing but false alarms -- so the row is counted as unchecked.
        declared = parse_palette(r.get("palette"))
        colors = list(declared)
        if not colors and graycheck and (r.get("n_series") or "").strip():
            try:
                count = int(float(r["n_series"]))
            except (TypeError, ValueError):
                count = 0
            if count >= 2:
                colors = list(DEFAULT_CYCLE[:min(len(DEFAULT_CYCLE), count)])
        if declared:
            distinct = len(dict.fromkeys(declared))
            series = 0
            raw_series = (r.get("n_series") or "").strip()
            if raw_series:
                try:
                    series = int(float(raw_series))
                except (TypeError, ValueError):
                    series = 0
            if len(declared) > distinct or (series and series > distinct):
                result["warnings"].append(
                    f"{cid}: palette declares {distinct} distinct colour(s) for "
                    f"{max(len(declared), series)} series; at least two series "
                    f"share a colour")
        if graycheck and len(colors) >= 2:
            palette_report = check_palette(colors, colorblind=colorblind,
                                           min_delta_l=min_delta_l,
                                           min_delta_e=min_delta_e)
            palette_rows.append({
                "id": cid,
                "declared": bool(declared),
                "colors": colors,
                "min_delta_l": palette_report.get("min_delta_l"),
                "min_delta_e": palette_report.get("min_delta_e"),
            })
            for message in palette_report["errors"]:
                if declared:
                    result["errors"].append(f"{cid}: {message}")
                else:
                    result["warnings"].append(f"{cid} (default cycle): {message}")
            for message in palette_report["warnings"]:
                result["warnings"].append(f"{cid}: {message}")
    if n_bad:
        result["errors"].append(f"{len(n_bad)} chart N invalid: {n_bad[:8]}")
    result["graycheck"] = bool(graycheck)
    result["colorblind"] = bool(colorblind)
    result["palettes"] = palette_rows
    if graycheck and rows:
        unchecked = len(rows) - sum(1 for p in palette_rows if p["declared"])
        # A missing palette is not a defect: it is simply out of scope for the
        # grayscale check.  Record it as a note instead of a warning so that a
        # clean manifest keeps reporting an empty warning list.
        result["palette_unchecked"] = int(unchecked)
        result["palette_note"] = (
            f"{unchecked}/{len(rows)} manifest row(s) record no palette of two or "
            f"more colours; grayscale separability only applies where two series "
            f"can be confused") if unchecked else ""
    result["n_na_count"] = len(n_unknown)
    result["n_total"] = len(rows)
    if n_unknown:
        if len(n_unknown) == len(rows):
            # Every row is silent about N, so the caption check verifies nothing
            # at all: a gate that cannot measure must not report success.
            result["errors"].append(
                f"所有 {len(rows)} 张图都没有声明样本量（n=NA），图注里的 N= 无法校验；"
                f"请在 paper_figures/chart_pack 里写 n 或 n_scope")
        else:
            for cid in n_unknown:
                result["warnings"].append(
                    f"{cid}: n=NA (sample size unknown); the caption's N= "
                    f"cannot be checked")
    if caption_bad:
        result["warnings"].append(f"{len(caption_bad)} caption(s) missing matching N=: {caption_bad[:8]}")
    if file_bad:
        result["errors"].append(f"{len(file_bad)} manifest file path(s) missing: {file_bad[:8]}")
    if scope_bad:
        result["warnings"].append(f"{len(scope_bad)} chart(s) with unknown n_scope: {scope_bad[:8]}")
    if range_notes:
        result["range_n"] = range_notes[:12]
    return result


def check_figures(path: str, min_dpi: int = 600, width_cm: float = 15.0,
                  min_fontsize: float | None = None,
                  allow_raster_text: bool = False) -> dict:
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
    # Type size lives in the vector, not in a PNG: the PDFs beside the rasters are
    # the only place it can be measured. Rasters are reported as "not checkable"
    # rather than silently passing.
    pdf_rows, low_font_spans = [], []
    min_effective = None
    if min_fontsize:
        for name in sorted(os.listdir(path)):
            if not name.lower().endswith(".pdf"):
                continue
            pdf_info = check_pdf(os.path.join(path, name), 0, 0, min_fontsize,
                                 width_cm, allow_raster_text,
                                 raster_expected=False)
            pdf_rows.append({
                "file": name,
                "pages": pdf_info.get("pages"),
                "min_fontsize": pdf_info.get("min_fontsize"),
                "min_fontsize_effective": pdf_info.get("min_fontsize_effective"),
                "low_font_count": pdf_info.get("low_font_count", 0),
            })
            for span in pdf_info.get("low_font", []):
                low_font_spans.append({"file": name, **span})
            effective = pdf_info.get("min_fontsize_effective")
            if effective is not None:
                min_effective = effective if min_effective is None \
                    else min(min_effective, effective)
            for message in pdf_info.get("errors", []):
                if "pt after placement" in message or "no_text_layer" in message:
                    result["errors"].append(f"{name}: {message}")
            for message in pdf_info.get("warnings", []):
                if "no_text_layer" in message:
                    result["warnings"].append(f"{name}: {message}")
        result["pdfs"] = pdf_rows
        result["min_fontsize"] = min_effective
        result["min_fontsize_limit"] = float(min_fontsize)
        result["low_font"] = low_font_spans[:20]
        result["low_font_count"] = len(low_font_spans)
        if not pdf_rows:
            result["font_size_check"] = (
                f"skipped: no PDF in the directory, so {float(min_fontsize):g} pt "
                f"cannot be verified from the rasters; pass --pdf")
            # A PNG/TIFF has no text layer by definition, so this is not a
            # no_text_layer defect -- but it is not a pass either: say it once.
            if result["files"]:
                result["warnings"].append(
                    f"{len(result['files'])} raster file(s): pixel images have no "
                    f"text layer, so the {float(min_fontsize):g} pt minimum was not "
                    f"verified; check the source figure PDF (qa_outputs --pdf)")
    if not result["files"] and not result.get("pdfs"):
        # "0 figures checked" is not a pass: it is the usual symptom of pointing
        # --figures at the chart-pack folder instead of chart-pack/figures, and a
        # silent pass hides that the whole resolution gate was skipped.
        result["errors"].append(
            f"no image or PDF files found under {result['dir']}; point --figures at the "
            f"folder that holds the figures (e.g. chart_pack/figures), or drop the flag")
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
    parser.add_argument("--min-fontsize", type=float, default=None,
                        help="minimum text size in pt after placement (default 7.2; "
                             "giving it explicitly also turns bitmap/no_text_layer "
                             "figures into errors, 0 disables)")
    parser.add_argument("--target-width-cm", type=float, default=None,
                        help="width the PDF is placed at when computing effective pt "
                             "(default: --figure-width-cm; 0 disables scaling)")
    parser.add_argument("--graycheck", dest="graycheck", action="store_true",
                        default=True,
                        help="check grayscale separability of manifest palettes (default on)")
    parser.add_argument("--no-graycheck", dest="graycheck", action="store_false",
                        help="skip the grayscale check")
    parser.add_argument("--colorblind", action="store_true",
                        help="also simulate deuteranopia/protanopia (warnings)")
    parser.add_argument("--allow-raster-text", action="store_true",
                        help="downgrade no_text_layer (bitmap figures whose type "
                             "cannot be measured) from error to warning")
    parser.add_argument("--out", default=None, help="write JSON report here")
    parser.add_argument("--strict", action="store_true", help="(kept for compatibility; errors already exit 2)")
    parser.add_argument("--exit-zero", action="store_true",
                        help="always exit 0 even when errors are found (do not use in CI)")
    args = parser.parse_args()

    report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "checks": {}}
    target_cm = args.target_width_cm
    if target_cm is None:
        target_cm = args.figure_width_cm
    if target_cm is not None and target_cm <= 0:
        target_cm = None  # explicit opt-out of the placement scaling
    # Font size is always *measured* and reported, but it is only enforced when the
    # caller asks for it: a resolution-only run must not fail on type it was not
    # asked about.
    strict_type = bool(args.min_fontsize and args.min_fontsize > 0)
    min_fontsize = float(args.min_fontsize) if strict_type else None
    raster_is_error = strict_type and not args.allow_raster_text
    if args.min_width:
        # Documented as retired: pixel width ignores the printed width, so a
        # 3543 px figure is fine at 15 cm and wrong at 5 cm.  Keep parsing the
        # flag so old commands run, but do not let it veto figures.
        print("warning: --min-width is retired (use --min-dpi / "
              "--target-width-cm); the value is ignored", file=sys.stderr)
    if args.pdf:
        report["checks"]["pdf"] = check_pdf(args.pdf, 0, args.min_dpi,
                                            min_fontsize, target_cm,
                                            not raster_is_error,
                                            raster_expected=True)
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
        report["checks"]["manifest"] = check_manifest(
            args.manifest, data_rows, args.graycheck, args.colorblind)
    if args.figures:
        report["checks"]["figures"] = check_figures(
            args.figures, args.min_dpi, args.figure_width_cm, min_fontsize,
            not raster_is_error)

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
