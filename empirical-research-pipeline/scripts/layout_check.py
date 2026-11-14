#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check figures and page layout at the size they are *actually placed*.

A figure that is fine as a PNG can still be unusable in the thesis: a 15 cm
figure squeezed into an 8.5 cm two-column slot scales 8.5 pt labels down to
4.8 pt even though its effective raster DPI increases. Pixel counts and the DPI
stored in the file therefore prove nothing about the printed page.  This module
measures the final artefacts instead:

* ``inspect_docx``  - every inline/anchor placement: displayed width/height in
  cm, pixel size of the embedded blob, image content hash, the neighbouring
  paragraphs (caption candidates) and the section text width.
* ``inspect_pdf``   - every placed image per page: bbox in pt -> cm, the pixel
  size of the extracted stream, content hash, and the smallest text span that
  actually falls *inside* that image box (the figure's own type).
* ``match_images``  - map DOCX placements to PDF placements by decoded image
  content, never by file name or order.
* ``check_placement`` - per figure: present in DOCX, effective dpi at placed
  width, same physical size in the PDF (2% tolerance), caption adjacent to the
  image, and placed font size.
* ``check_structure`` - table header repeat / row split, caption ``keepNext``,
  ``图N``/``表N`` cross references, ``w:rFonts`` completeness, blank PDF pages.
* ``record_check``  - persist the result as a v2 ``layout_check`` record.

Two honesty rules drive the design:

1. **Content, not bytes.**  Word and PyMuPDF both re-encode an embedded PNG, so
   the stored byte streams of the very same figure differ between DOCX and PDF.
   Matching on those bytes would report every figure as missing.  ``sha256`` in
   this module is therefore the hash of the *decoded pixels* (canonicalised to
   RGB with the pixel size in the prefix); ``blob_sha256`` keeps the stored-byte
   hash for reporting.  Transparent images may be composited differently by the
   PDF writer; when that happens the figure is honestly reported as unmatched
   instead of being waved through.  A *resampled* copy is unmatched too: Word's
   "save as PDF" re-encodes embedded figures at ~200 dpi, and it is precisely
   that copy ``export_pdf_hires.py`` replaces with the original image.  Until it
   does, the PDF's figure cannot be tied to the source, so the check fails with
   that instruction rather than guessing a pairing.
2. **Unmeasurable is not passed.** A bitmap has no text spans. Font measurement
   then needs a current live-artist record that reproduced the exact delivered
   PNG pixels and all rendered text, plus the matched final placement sizes.
   A source PDF alone is insufficient. Without either proof the check remains
   ``unassessed`` with ``no_text_layer``. ``record_check`` refuses a record whose
   ``pages_reviewed`` was not produced by an actual page read.

CLI::

    python layout_check.py --root . inspect --docx out/thesis.docx --pdf out/thesis.pdf
    python layout_check.py --root . check --docx out/thesis.docx --pdf out/thesis.pdf \\
        --figure out/fig/figure1.png=fig1 --figure-caption "fig1=图 1  描述（N=120）" \\
        --min-dpi 600 --min-fontsize 7.2 --record

Exit codes: ``0`` all declared checks passed, ``2`` any failed/unassessed check
or an input error (never a silent pass).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
import math

import contract_v2 as C

VERSION = "1.0.0"

DEFAULT_MIN_DPI = 600.0
DEFAULT_MIN_FONTSIZE = 7.2
#: DOCX placement vs PDF placement may differ this much (relative).
SIZE_TOLERANCE = 0.02
#: qa_outputs uses the same 0.5% grace: 15 cm at 600 dpi needs 3543.3 px, so a
#: perfectly exported 3543 px figure measures 599.9 dpi.
DPI_TOLERANCE = 0.005

EMU_PER_CM = 360000.0
CM_PER_INCH = 2.54
PT_PER_INCH = 72.0

try:                                                    # pragma: no cover
    from docx import Document
    from docx.oxml.ns import qn
except ImportError:                                     # pragma: no cover
    Document = None
    qn = None

try:                                                    # pragma: no cover
    import fitz
except ImportError:                                     # pragma: no cover
    fitz = None

try:                                                    # pragma: no cover
    from PIL import Image
except ImportError:                                     # pragma: no cover
    Image = None

#: ``图 1 …`` / ``表 2 …`` at the start of a paragraph (an object definition).
CAPTION_RE = re.compile(r"^\s*(图|表)\s*([0-9]+)")
#: ``图1`` / ``表 2`` anywhere in body text (a cross reference).  The trailing
#: ``(?![0-9])`` makes ``图1`` fail to match inside ``图10``.
LABEL_RE = re.compile(r"(图|表)\s*([0-9]+)(?![0-9])")


class LayoutError(ValueError):
    """Raised when the artefacts cannot even be opened/read."""


# ---------------------------------------------------------------------------
# geometry and image identity
# ---------------------------------------------------------------------------
def effective_dpi(px_width: float, width_cm: float) -> float:
    """Resolution a printer sees: pixel width / placed width in inches.

    This is the number that matters - not the DPI tag in the PNG metadata and not
    the pixel count.  A 1200 px figure placed at 8.5 cm has
    ``1200 / (8.5 / 2.54) = 358.6 dpi`` however it was exported.
    """
    if px_width is None or width_cm is None:
        raise LayoutError("effective_dpi needs both a pixel width and a placed width")
    if float(px_width) <= 0:
        raise LayoutError(f"pixel width must be > 0, got {px_width!r}")
    if float(width_cm) <= 0:
        raise LayoutError(f"placed width must be > 0 cm, got {width_cm!r}")
    return float(px_width) / (float(width_cm) / CM_PER_INCH)


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def image_content_sha256(blob: bytes) -> tuple[str, tuple[int, int] | None]:
    """Hash decoded pixels (canonical RGB) plus the pixel size.

    Two encoders writing the same picture (Word's image part, PyMuPDF's
    re-encoded stream) produce different bytes but identical pixels, so this is
    the only honest cross-format identity.  Returns ``(hash, (w, h))``.
    """
    if Image is None:                                   # pragma: no cover
        return _sha256_bytes(blob), None
    try:
        with Image.open(io.BytesIO(blob)) as im:
            rgb = im.convert("RGB")
            digest = hashlib.sha256()
            digest.update(f"{rgb.width}x{rgb.height}:RGB:".encode("ascii"))
            digest.update(rgb.tobytes())
            return digest.hexdigest(), (rgb.width, rgb.height)
    except Exception:
        # EMF/WMF or an exotic codec Pillow cannot decode: keep the byte hash
        # and no pixel size.  The image then cannot be tied to a raster source,
        # which is reported rather than guessed.
        return _sha256_bytes(blob), None


def _cm_from_pt(value: float) -> float:
    return float(value) / PT_PER_INCH * CM_PER_INCH


def _norm_text(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _caption_matches(caption: str, candidate: str | None) -> bool:
    """True when ``candidate`` is the caption (or the caption plus a note line)."""
    want, got = _norm_text(caption), _norm_text(candidate)
    if not want or not got:
        return False
    if got == want or got.startswith(want):
        return True
    prefix = r"^(?:图|表|Figure|Fig\.?|Table)\d+[.、:：]?"
    if not re.match(prefix, want, re.I):
        body = re.sub(prefix,"",got,count=1,flags=re.I)
        return body == want or body.startswith(want)
    return False


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (str, int, float)):
        return value
    return str(value)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
def _docx_paragraph_text(p_el) -> str:
    return "".join(node.text or "" for node in p_el.xpath(".//w:t"))


def _docx_neighbour_text(p_el, step: int) -> str:
    """Text of the nearest non-empty sibling paragraph in one direction."""
    node = p_el.getprevious() if step < 0 else p_el.getnext()
    while node is not None:
        if node.tag == qn("w:p"):
            text = _docx_paragraph_text(node).strip()
            if text:
                return text
        node = node.getprevious() if step < 0 else node.getnext()
    return ""


def _caption_candidate(prev_text: str, next_text: str) -> str:
    """Prefer the paragraph that looks like a caption, then the one below."""
    for text in (next_text, prev_text):
        if text and CAPTION_RE.match(text):
            return text
    return next_text or prev_text


def _docx_page_count(path: str) -> tuple[int | None, str | None]:
    """Word stores the last rendered page count in ``docProps/app.xml``."""
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("docProps/app.xml").decode("utf-8", "replace")
        match = re.search(r"<Pages>\s*([0-9]+)\s*</Pages>", xml)
        if match:
            return int(match.group(1)), "docProps/app.xml"
    except (KeyError, OSError, zipfile.BadZipFile):
        pass
    return None, None


def inspect_docx(path: str | os.PathLike) -> dict:
    """Read every inline/anchor placement in a DOCX.

    Sizes come from ``wp:extent`` (EMU -> cm), i.e. what Word lays out, not the
    PNG's nominal size.  Caption candidates are the image's own paragraph plus
    its nearest non-empty neighbours, because a caption is a separate paragraph
    in a Word manuscript.  Adjacency is paragraph-based: for an anchored
    (floating) image the entry is flagged ``floating`` because the paragraph it
    sits in is not necessarily the one printed next to it.
    """
    path = str(path)
    if not os.path.isfile(path):
        raise LayoutError(f"DOCX not found: {path}")
    if Document is None:                                # pragma: no cover
        raise LayoutError("python-docx is not installed; cannot read the DOCX")
    try:
        doc = Document(path)
    except Exception as exc:                            # pragma: no cover
        raise LayoutError(f"cannot open DOCX: {type(exc).__name__}: {exc}") from exc

    section_widths = []
    for section in doc.sections:
        try:
            width = (section.page_width - section.left_margin
                     - section.right_margin) / EMU_PER_CM
        except TypeError:
            width = None
        section_widths.append(round(float(width), 3) if width else None)
    section_width_cm = next((w for w in section_widths if w), None)

    images = []
    for shape in doc.element.body.xpath(".//wp:inline | .//wp:anchor"):
        refs = shape.xpath(".//a:blip/@r:embed")
        extents = shape.xpath("./wp:extent")
        if not refs or not extents:
            continue
        try:
            width_cm = float(extents[0].get("cx")) / EMU_PER_CM
            height_cm = float(extents[0].get("cy")) / EMU_PER_CM
        except (TypeError, ValueError):
            continue
        para = shape.getparent()
        while para is not None and para.tag != qn("w:p"):
            para = para.getparent()
        if para is None:                                # pragma: no cover
            continue
        paragraph_text = _docx_paragraph_text(para).strip()
        prev_text = _docx_neighbour_text(para, -1)
        next_text = _docx_neighbour_text(para, +1)
        try:
            paragraph_index = len(para.xpath("preceding-sibling::w:p"))
        except Exception:                               # pragma: no cover
            paragraph_index = None
        for ref in refs:
            part = doc.part.related_parts.get(ref)
            if part is None:                            # pragma: no cover
                continue
            blob = part.blob
            content_sha, px = image_content_sha256(blob)
            images.append({
                "index": len(images),
                "sha256": content_sha,
                "blob_sha256": _sha256_bytes(blob),
                "bytes": len(blob),
                "px": [px[0], px[1]] if px else None,
                "width_cm": round(width_cm, 4),
                "height_cm": round(height_cm, 4),
                "effective_dpi": (round(effective_dpi(px[0], width_cm), 2)
                                  if px and width_cm > 0 else None),
                "paragraph_index": paragraph_index,
                "floating": shape.tag.endswith("}anchor"),
                "paragraph_text": paragraph_text[:200],
                "prev_text": prev_text[:200],
                "next_text": next_text[:200],
                "caption_candidate": _caption_candidate(prev_text,
                                                        next_text)[:200],
                "section_width_cm": section_width_cm,
            })

    pages, pages_source = _docx_page_count(path)
    return {
        "docx": path,
        "sha256": C.file_sha256(path),
        "images": images,
        "pages": pages,
        "pages_source": pages_source,
        "section_width_cm": section_width_cm,
        "section_widths_cm": section_widths,
        "sections": len(doc.sections),
        "paragraphs": len(doc.paragraphs),
        "tables": len(doc.tables),
        "notes": ("pages is Word's last saved page count (docProps/app.xml); "
                  "it is not a re-render and is null when absent"),
    }


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def inspect_pdf(path: str | os.PathLike) -> dict:
    """Read every placed image and text span per PDF page.

    ``width_cm``/``height_cm`` come from the image bbox (pt -> cm), so a figure
    that Word resampled to 200 dpi but placed at 15 cm is measured at 15 cm.
    ``fontsize_min`` is the smallest span whose centre falls inside that image
    box - i.e. the figure's own labels, not the body text.
    """
    path = str(path)
    if not os.path.isfile(path):
        raise LayoutError(f"PDF not found: {path}")
    if fitz is None:                                    # pragma: no cover
        raise LayoutError("PyMuPDF (fitz) is not installed; cannot read the PDF")
    try:
        doc = fitz.open(path)
    except Exception as exc:                            # pragma: no cover
        raise LayoutError(f"cannot open PDF: {type(exc).__name__}: {exc}") from exc

    pages = []
    try:
        for number, page in enumerate(doc, start=1):
            spans = []
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
                        spans.append({"size": round(size, 2),
                                      "bbox": [round(float(v), 2) for v in bbox],
                                      "text": str(span.get("text", ""))[:40]})
            page_images = []
            for im in page.get_images(full=True):
                xref = im[0]
                try:
                    rect = page.get_image_bbox(im)
                except Exception:                       # pragma: no cover
                    continue
                if rect.width <= 1 or rect.height <= 1:
                    continue
                try:
                    info = doc.extract_image(xref)
                except Exception:                       # pragma: no cover
                    continue
                blob = info.get("image") or b""
                content_sha, px = image_content_sha256(blob)
                if px is None:                          # pragma: no cover
                    px = (int(info.get("width") or 0),
                          int(info.get("height") or 0))
                width_cm = _cm_from_pt(rect.width)
                height_cm = _cm_from_pt(rect.height)
                inside = [s for s in spans
                          if rect.x0 <= (s["bbox"][0] + s["bbox"][2]) / 2.0 <= rect.x1
                          and rect.y0 <= (s["bbox"][1] + s["bbox"][3]) / 2.0 <= rect.y1]
                page_images.append({
                    "xref": xref,
                    "page": number,
                    "sha256": content_sha,
                    "blob_sha256": _sha256_bytes(blob),
                    "bytes": len(blob),
                    "px": [px[0], px[1]],
                    "bbox_pt": [round(float(v), 2) for v in
                                (rect.x0, rect.y0, rect.x1, rect.y1)],
                    "width_cm": round(width_cm, 4),
                    "height_cm": round(height_cm, 4),
                    "effective_dpi": (round(effective_dpi(px[0], width_cm), 2)
                                      if px[0] and width_cm > 0 else None),
                    "text_spans_inside": len(inside),
                    "fontsize_min": (min(s["size"] for s in inside)
                                     if inside else None),
                })
            text = page.get_text().strip()
            pages.append({
                "page": number,
                "width_cm": round(_cm_from_pt(page.rect.width), 4),
                "height_cm": round(_cm_from_pt(page.rect.height), 4),
                "text_chars": len(text),
                "text_spans": len(spans),
                "min_fontsize": (min(s["size"] for s in spans) if spans else None),
                "images": page_images,
            })
    finally:
        doc.close()

    sizes = [p["min_fontsize"] for p in pages if p["min_fontsize"] is not None]
    return {
        "pdf": path,
        "sha256": C.file_sha256(path),
        "pages": pages,
        "page_count": len(pages),
        "min_fontsize": min(sizes) if sizes else None,
        "notes": ("fontsize_min on an image is measured only from spans inside "
                  "its bbox; null means the placed figure has no text layer"),
    }


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------
def _group_by_sha(entries) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(entry["sha256"], []).append(entry)
    return grouped


def _pdf_images(pdf_info: dict) -> list[dict]:
    return [image for page in pdf_info.get("pages", [])
            for image in page.get("images", [])]


def _compact(entry: dict, side: str) -> dict:
    out = {"sha256": entry["sha256"], "blob_sha256": entry.get("blob_sha256"),
           "px": entry.get("px"), "width_cm": entry.get("width_cm"),
           "height_cm": entry.get("height_cm")}
    if side == "docx":
        out["paragraph_index"] = entry.get("paragraph_index")
        out["caption_candidate"] = entry.get("caption_candidate")
    else:
        out["page"] = entry.get("page")
        out["xref"] = entry.get("xref")
        out["fontsize_min"] = entry.get("fontsize_min")
    return out


def _size_delta(docx_entry: dict, pdf_entry: dict) -> tuple[float, float]:
    dw = (abs(pdf_entry["width_cm"] - docx_entry["width_cm"])
          / docx_entry["width_cm"]) if docx_entry.get("width_cm") else 1.0
    dh = (abs(pdf_entry["height_cm"] - docx_entry["height_cm"])
          / docx_entry["height_cm"]) if docx_entry.get("height_cm") else 1.0
    return dw, dh


def match_images(docx_info: dict, pdf_info: dict,
                 *, tolerance: float = SIZE_TOLERANCE) -> dict:
    """Pair DOCX placements with PDF placements by decoded image content.

    File names and insertion order are deliberately ignored: both change between
    the DOCX and the exported PDF, and order says nothing about identity.  A
    matched image whose *placed size* differs by more than ``tolerance`` is still
    reported (and makes ``ok`` false) - that is how "the figure is there but the
    layout shrank it" surfaces.
    """
    docx_entries = list(docx_info.get("images", []))
    pdf_entries = _pdf_images(pdf_info)
    docx_by = _group_by_sha(docx_entries)
    pdf_by = _group_by_sha(pdf_entries)

    matched, docx_only, pdf_only = [], [], []
    for sha in sorted(set(docx_by) & set(pdf_by)):
        docx_group, pdf_group = docx_by[sha], pdf_by[sha]
        pairs = []
        for de in docx_group:
            best = None
            for pe in pdf_group:
                dw, dh = _size_delta(de, pe)
                delta = max(dw, dh)
                if best is None or delta < best[0]:
                    best = (delta, dw, dh, pe)
            delta, dw, dh, pe = best
            pairs.append({
                "docx_paragraph_index": de.get("paragraph_index"),
                "pdf_page": pe.get("page"),
                "docx_width_cm": de.get("width_cm"),
                "pdf_width_cm": pe.get("width_cm"),
                "docx_height_cm": de.get("height_cm"),
                "pdf_height_cm": pe.get("height_cm"),
                "width_delta": round(dw, 4),
                "height_delta": round(dh, 4),
                "ok": delta <= tolerance,
            })
        matched.append({
            "sha256": sha,
            "docx": [_compact(e, "docx") for e in docx_group],
            "pdf": [_compact(e, "pdf") for e in pdf_group],
            "pairs": pairs,
            "placement_consistent": all(p["ok"] for p in pairs),
            "byte_identical": any(d.get("blob_sha256") == p.get("blob_sha256")
                                  for d in docx_group for p in pdf_group),
        })
    for sha, group in docx_by.items():
        if sha not in pdf_by:
            docx_only.extend(_compact(e, "docx") for e in group)
    for sha, group in pdf_by.items():
        if sha not in docx_by:
            pdf_only.extend(_compact(e, "pdf") for e in group)

    placement_ok = all(m["placement_consistent"] for m in matched)
    return {
        "ok": not docx_only and not pdf_only and placement_ok,
        "match_basis": ("sha256 of decoded pixels (stored bytes legitimately "
                        "differ after Word/PyMuPDF re-encode the image)"),
        "tolerance": tolerance,
        "counts": {"docx": len(docx_entries), "pdf": len(pdf_entries),
                   "matched": len(matched)},
        "matched": matched,
        "docx_only": docx_only,
        "pdf_only": pdf_only,
    }


# ---------------------------------------------------------------------------
# per-figure placement checks
# ---------------------------------------------------------------------------
def _check(name: str, ok: bool, *, status: str | None = None,
           severity: str = "error", **detail) -> dict:
    item = {"check": name, "ok": bool(ok),
            "status": status or ("passed" if ok else "failed"),
            "severity": severity}
    item.update(_jsonable(detail))
    return item


def _pages_reviewed(pdf_info: dict | None) -> list[dict]:
    if not pdf_info:
        return []
    return [{"page": page["page"], "text_chars": page["text_chars"],
             "text_spans": page["text_spans"], "images": len(page["images"])}
            for page in pdf_info.get("pages", [])]


def _source_pdf_fontsize(path: str, placed_width_cm: float) -> dict | None:
    """Diagnostic only: scale the *source* figure PDF's type by placement.

    This is qa_outputs' "字号按版面折算" arithmetic.  It is reported next to an
    unassessed ``min_fontsize`` check so the reader has a number to act on, but
    it is never a pass: the final PDF's own text layer could not be measured.
    """
    try:
        info = inspect_pdf(path)
    except LayoutError:
        return None
    sizes = [page["min_fontsize"] for page in info["pages"]
             if page["min_fontsize"] is not None]
    # The design width of a figure PDF is the figure box it carries; a pure
    # vector export has no image box, so its page *is* the figure.
    widths = [image["width_cm"] for page in info["pages"]
              for image in page["images"] if image.get("width_cm")]
    if not widths:
        widths = [page["width_cm"] for page in info["pages"]
                  if page.get("width_cm")]
    if not sizes or not widths:
        return None
    source_width_cm = max(widths)
    scale = placed_width_cm / source_width_cm if source_width_cm else None
    return {"source_pdf": str(path),
            "source_min_fontsize_pt": min(sizes),
            "source_width_cm": source_width_cm,
            "placement_scale": round(scale, 4) if scale else None,
            "estimated_placed_fontsize_pt": (round(min(sizes) * scale, 2)
                                             if scale else None),
            "basis": ("estimate from the source figure PDF's own width, not "
                      "measured in the final PDF")}


def bound_raster_fontsize(figure, docx_hits, pdf_hits):
    """Measure an exact reproduced raster via its live-artist rendering proof.

    A source PDF alone is still not proof about a PNG. This path requires a
    current figure record that reproduced the exact PNG pixels, plus the actual
    matched image widths in both printed artifacts. Without it use unassessed.
    """
    record = figure.get("figure_record")
    if not record or not docx_hits or not pdf_hits:
        return None
    try:
        C.validate_record(record)
        data = record["data"]
        if (record["kind"] != "figure_spec" or record["status"] != "checked"
                or record["producer"].get("code_sha256") != C.file_sha256(Path(__file__).with_name("figsemantics.py"))
                or data.get("png_sha256") != C.file_sha256(figure["png"])
                or not any(c["check"] == "saved_png_matches_live_figure" and c.get("ok") is True for c in data["checks"])):
            return None
        observed = data["elements_observed"]
        if any(axis.get("images") for axis in observed["axes"]):
            return None
        texts = observed.get("rendered_text") or []
        if not texts:
            return None
        original_width = float(observed["canvas"]["size_cm"][0])
        if original_width <= 0:
            return None
        placed_width = min(float(h["width_cm"]) for h in [*docx_hits,*pdf_hits])
        sizes = [float(t["fontsize"])*placed_width/original_width for t in texts]
        if not sizes or any(not math.isfinite(s) or s <= 0 for s in sizes):
            return None
        return {"observed": min(sizes), "method":"exact_saved_png_live_artist_fonts_at_actual_placement",
                "figure_signature":C.signature(record), "rendered_text_count":len(texts),
                "source_width_cm":original_width, "placed_width_cm":placed_width}
    except (C.ContractError,ValueError,KeyError,OSError,TypeError):
        return None


def check_placement(docx_path: str | os.PathLike, pdf_path: str | os.PathLike, *,
                    figures, min_dpi: float = DEFAULT_MIN_DPI,
                    min_fontsize: float = DEFAULT_MIN_FONTSIZE) -> dict:
    """Check each declared figure at its final DOCX/PDF placement size.

    ``figures`` entries: ``{"figure_id", "png", "pdf"?, "caption"}``.  The PNG's
    decoded content is the link to the DOCX image; nothing is matched by name or
    position.
    """
    checks: list[dict] = []
    unverifiable: list[dict] = []
    images_out: list[dict] = []
    figures = list(figures or [])

    try:
        docx_info = inspect_docx(docx_path)
    except LayoutError as exc:
        return {"ok": False, "status": "failed", "docx": str(docx_path),
                "pdf": str(pdf_path), "min_dpi": min_dpi,
                "min_fontsize": min_fontsize, "images": [],
                "checks": [_check("docx_file", False, path=str(docx_path),
                                  detail=str(exc))],
                "unverifiable": [], "pages_reviewed": []}

    pdf_info = None
    if pdf_path and os.path.isfile(str(pdf_path)):
        try:
            pdf_info = inspect_pdf(pdf_path)
        except LayoutError as exc:
            checks.append(_check("pdf_file", False, path=str(pdf_path),
                                 detail=str(exc)))
    else:
        checks.append(_check("pdf_file", False, path=str(pdf_path),
                             detail="PDF not found; placement cannot be "
                                    "compared across the two artefacts"))

    docx_by_sha = _group_by_sha(docx_info["images"])
    pdf_by_sha = _group_by_sha(_pdf_images(pdf_info) if pdf_info else [])
    dpi_limit = (float(min_dpi) * (1.0 - DPI_TOLERANCE)) if min_dpi else 0.0

    if not figures:
        checks.append(_check(
            "figures_declared", False, status="unassessed",
            detail="no figure was declared, so no placement was checked"))
        unverifiable.append({"figure_id": None, "check": "figures_declared",
                             "reason": "no figure declared (--figure png=ID)"})

    for figure in figures:
        png = figure.get("png")
        fid = str(figure.get("figure_id") or "")
        if not fid:
            fid = os.path.splitext(os.path.basename(str(png or "figure")))[0]
        caption = str(figure.get("caption") or "").strip()
        entry = {"figure_id": fid, "png": str(png) if png else None,
                 "sha256": None, "px": None, "docx": [], "pdf": []}

        if not png or not os.path.isfile(str(png)):
            checks.append(_check("figure_source", False, figure_id=fid,
                                 path=str(png),
                                 detail="source PNG not found; the figure "
                                        "cannot be tied to the DOCX placement"))
            images_out.append(entry)
            continue

        with open(png, "rb") as fh:
            blob = fh.read()
        content_sha, px = image_content_sha256(blob)
        entry.update({"sha256": content_sha,
                      "blob_sha256": _sha256_bytes(blob),
                      "px": [px[0], px[1]] if px else None})

        # 1. is the declared figure actually in the DOCX?
        docx_hits = docx_by_sha.get(content_sha, [])
        if not docx_hits:
            detail = (f"no DOCX image has this pixel content (sha256 "
                      f"{content_sha[:12]}, {px[0] if px else '?'}x"
                      f"{px[1] if px else '?'} px); the declared PNG was not "
                      f"placed, or the document holds a re-exported copy")
            checks.append(_check("figure_in_docx", False, figure_id=fid,
                                 sha256=content_sha, detail=detail))
            for name, why in (
                    ("placed_dpi", "the figure is not in the DOCX"),
                    ("caption", "the figure is not in the DOCX"),
                    ("docx_pdf_size_match", "the figure is not in the DOCX"),
                    ("min_fontsize", "the figure is not in the DOCX")):
                checks.append(_check(name, False, status="unassessed",
                                     figure_id=fid,
                                     detail=f"{why}, so this cannot be measured"))
                unverifiable.append({"figure_id": fid, "check": name,
                                     "reason": why})
            images_out.append(entry)
            continue
        checks.append(_check("figure_in_docx", True, figure_id=fid,
                             sha256=content_sha,
                             source_blob_sha256=_sha256_bytes(blob),
                             docx_blob_identical=any(
                                 hit.get("blob_sha256") == _sha256_bytes(blob)
                                 for hit in docx_hits),
                             occurrences=len(docx_hits),
                             detail=f"found in {len(docx_hits)} DOCX placement(s)"))
        entry["docx"] = [{
            "paragraph_index": hit["paragraph_index"],
            "width_cm": hit["width_cm"],
            "height_cm": hit["height_cm"],
            "effective_dpi": hit["effective_dpi"],
            "caption_candidate": hit["caption_candidate"],
        } for hit in docx_hits]

        # 2. effective dpi at the width Word actually uses
        measurable = [hit for hit in docx_hits if hit.get("effective_dpi")]
        if not measurable:
            checks.append(_check("placed_dpi", False, status="unassessed",
                                 figure_id=fid,
                                 detail="the DOCX placement has no readable "
                                        "pixel size, so dpi cannot be measured"))
            unverifiable.append({"figure_id": fid, "check": "placed_dpi",
                                 "reason": "no readable pixel size in the DOCX"})
        else:
            worst = min(hit["effective_dpi"] for hit in measurable)
            ok = (not min_dpi) or worst >= dpi_limit - 1e-9
            checks.append(_check(
                "placed_dpi", ok, figure_id=fid,
                min_dpi=float(min_dpi), limit_used=round(dpi_limit, 2),
                effective_dpi=round(worst, 2),
                occurrences=[{"width_cm": hit["width_cm"],
                              "height_cm": hit["height_cm"],
                              "px": hit["px"],
                              "effective_dpi": hit["effective_dpi"]}
                             for hit in measurable],
                detail=(f"{px[0]} px placed at "
                        f"{measurable[0]['width_cm']:g} cm = "
                        f"{worst:.0f} dpi (needs >= {min_dpi:g})")))

        # 3. caption must be adjacent to the image and match the text
        if not caption:
            checks.append(_check(
                "caption", False, status="unassessed", figure_id=fid,
                detail="no caption text was supplied, so the neighbour "
                       "paragraph cannot verify itself"))
            unverifiable.append({"figure_id": fid, "check": "caption",
                                 "reason": "no caption text supplied"})
        else:
            candidates = []
            for hit in docx_hits:
                for text in (hit["paragraph_text"], hit["next_text"],
                             hit["prev_text"]):
                    if text and text not in candidates:
                        candidates.append(text)
            hits = [c for c in candidates if _caption_matches(caption, c)]
            checks.append(_check(
                "caption", bool(hits), figure_id=fid, caption=caption[:200],
                candidates=candidates[:6], matches=hits[:2],
                floating=any(hit.get("floating") for hit in docx_hits),
                detail=("caption is adjacent to the image"
                        if hits else
                        "no paragraph immediately before/after the image "
                        "matches the declared caption")))

        # 4. the same figure must be the same physical size in the PDF
        pdf_hits = pdf_by_sha.get(content_sha, []) if pdf_info else []
        if not pdf_info:
            checks.append(_check(
                "figure_in_pdf", False, figure_id=fid,
                detail="no PDF was read, so the exported placement is unknown"))
            checks.append(_check(
                "docx_pdf_size_match", False, status="unassessed",
                figure_id=fid,
                detail="the PDF is missing, so the two placements cannot be "
                       "compared"))
            unverifiable.append({"figure_id": fid,
                                 "check": "docx_pdf_size_match",
                                 "reason": "no PDF was read"})
        elif not pdf_hits:
            checks.append(_check(
                "figure_in_pdf", False, figure_id=fid, sha256=content_sha,
                detail=("the figure's pixel content is absent from the PDF. "
                        "Word exports embedded figures at roughly 200 dpi, so a "
                        "raw 'save as PDF' holds a resampled copy: run "
                        "export_pdf_hires.py to put the original image back, "
                        "then re-check")))
            checks.append(_check(
                "docx_pdf_size_match", False, status="unassessed",
                figure_id=fid,
                detail="the figure is not in the PDF, so the two placements "
                       "cannot be compared"))
            unverifiable.append({"figure_id": fid, "check": "docx_pdf_size_match",
                                 "reason": "the figure is not in the PDF"})
        else:
            checks.append(_check("figure_in_pdf", True, figure_id=fid,
                                 occurrences=len(pdf_hits),
                                 pages=sorted({h["page"] for h in pdf_hits}),
                                 detail=f"found on page(s) "
                                        f"{sorted({h['page'] for h in pdf_hits})}"))
            pairs = []
            for hit in docx_hits:
                best = None
                for placed in pdf_hits:
                    dw, dh = _size_delta(hit, placed)
                    delta = max(dw, dh)
                    if best is None or delta < best[0]:
                        best = (delta, dw, dh, placed)
                delta, dw, dh, placed = best
                pairs.append({
                    "docx_width_cm": hit["width_cm"],
                    "pdf_width_cm": placed["width_cm"],
                    "docx_height_cm": hit["height_cm"],
                    "pdf_height_cm": placed["height_cm"],
                    "width_delta": round(dw, 4),
                    "height_delta": round(dh, 4),
                    "pdf_page": placed["page"],
                    "ok": delta <= SIZE_TOLERANCE,
                })
            ok = all(pair["ok"] for pair in pairs)
            checks.append(_check(
                "docx_pdf_size_match", ok, figure_id=fid,
                tolerance=SIZE_TOLERANCE, pairs=pairs,
                detail=("placed size matches the DOCX" if ok else
                        "placed size differs from the DOCX beyond "
                        f"{SIZE_TOLERANCE:.0%}")))

        # 5. font size measured on the final PDF's own text layer
        if not min_fontsize:
            checks.append(_check(
                "min_fontsize", True, status="not_applicable", severity="info",
                figure_id=fid,
                detail="min_fontsize=0 disables the type gate; the placed font "
                       "size was not judged"))
        elif not pdf_hits:
            reason = ("the figure is not in the PDF, so its type cannot be "
                      "measured" if pdf_info else "no PDF was read")
            checks.append(_check("min_fontsize", False, status="unassessed",
                                 figure_id=fid,
                                 min_fontsize=float(min_fontsize),
                                 detail=reason))
            unverifiable.append({"figure_id": fid, "check": "min_fontsize",
                                 "reason": reason})
        else:
            sizes = [placed["fontsize_min"] for placed in pdf_hits
                     if placed.get("fontsize_min") is not None]
            raster_proof = bound_raster_fontsize(figure,docx_hits,pdf_hits) if not sizes else None
            if raster_proof:
                sizes = [raster_proof["observed"]]
                entry["raster_font_proof"] = raster_proof
            if not sizes:
                reason = ("no_text_layer: the placed figure is a bitmap in the "
                          "PDF, so its labels have no text spans and the font "
                          "size cannot be measured; this is not a pass")
                detail = {"figure_id": fid, "min_fontsize": float(min_fontsize),
                          "pages": sorted({h["page"] for h in pdf_hits}),
                          "detail": reason}
                source_pdf = figure.get("pdf")
                if source_pdf and os.path.isfile(str(source_pdf)) and docx_hits:
                    estimate = _source_pdf_fontsize(
                        str(source_pdf), docx_hits[0]["width_cm"])
                    if estimate:
                        detail["source_pdf_diagnostic"] = estimate
                checks.append(_check("min_fontsize", False,
                                     status="unassessed", **detail))
                unverifiable.append({"figure_id": fid, "check": "min_fontsize",
                                     "reason": reason})
            else:
                smallest = min(sizes)
                ok = smallest + 1e-6 >= float(min_fontsize)
                checks.append(_check(
                    "min_fontsize", ok, figure_id=fid,
                    min_fontsize=float(min_fontsize), observed=smallest,
                    pages=sorted({h["page"] for h in pdf_hits}),
                    detail=(f"smallest span inside the placed figure is "
                            f"{smallest:g} pt (needs >= {min_fontsize:g}); "
                            + (raster_proof["method"] if raster_proof else "actual PDF text spans"))))

        entry["pdf"] = [{
            "page": hit["page"], "xref": hit["xref"],
            "width_cm": hit["width_cm"], "height_cm": hit["height_cm"],
            "effective_dpi": hit["effective_dpi"],
            "fontsize_min": hit["fontsize_min"],
        } for hit in pdf_hits]
        images_out.append(entry)

    failed = [c for c in checks
              if c["status"] == "failed" and c["severity"] == "error"]
    unassessed = [c for c in checks if c["status"] == "unassessed"]
    ok = not failed and not unassessed
    status = "failed" if failed else ("unassessed" if unassessed else "passed")
    return {
        "ok": ok,
        "status": status,
        "docx": str(docx_path),
        "pdf": str(pdf_path),
        "min_dpi": float(min_dpi),
        "min_fontsize": float(min_fontsize),
        "docx_section_width_cm": docx_info.get("section_width_cm"),
        "checks": checks,
        "images": images_out,
        "unverifiable": unverifiable,
        "pages_reviewed": _pages_reviewed(pdf_info),
    }


# ---------------------------------------------------------------------------
# structural checks
# ---------------------------------------------------------------------------
def _runs_with_text(doc) -> list:
    runs = []
    for run in doc.element.body.xpath(".//w:r"):
        text = "".join(node.text or "" for node in run.xpath("./w:t"))
        if text.strip():
            runs.append((run, text.strip()))
    return runs


def check_structure(docx_path: str | os.PathLike,
                    pdf_path: str | os.PathLike) -> dict:
    """Structural manuscript checks; anything unjudgeable says so.

    Judged: table header repeat (``tblHeader``), row split (``cantSplit``),
    caption ``keepNext``, ``图N``/``表N`` cross references, ``w:rFonts``
    completeness (a run without ``eastAsia`` falls back to the theme font, so it
    is reported as a warning) and blank PDF pages.  Elements the document does
    not contain are ``not_applicable``, not ``passed``.
    """
    path = str(docx_path)
    if not os.path.isfile(path):
        raise LayoutError(f"DOCX not found: {path}")
    if Document is None:                                # pragma: no cover
        raise LayoutError("python-docx is not installed; cannot read the DOCX")
    doc = Document(path)

    checks: list[dict] = []
    warnings: list[str] = []
    not_applicable: list[str] = []

    # -- tables ------------------------------------------------------------
    if not doc.tables:
        for name in ("table_header_repeat", "table_cantSplit"):
            checks.append(_check(name, True, status="not_applicable",
                                 severity="info",
                                 detail="no table in the document"))
            not_applicable.append(name)
        table_report = []
    else:
        table_report = []
        for index, table in enumerate(doc.tables):
            rows = list(table.rows)
            header = bool(rows and rows[0]._tr.xpath("./w:trPr/w:tblHeader"))
            missing_split = [i for i, row in enumerate(rows)
                             if not row._tr.xpath("./w:trPr/w:cantSplit")]
            table_report.append({
                "table": index, "rows": len(rows),
                "header_repeat": header,
                "rows_missing_cantSplit": missing_split,
                "ok": header and not missing_split,
            })
        header_ok = all(t["header_repeat"] for t in table_report)
        split_ok = all(not t["rows_missing_cantSplit"] for t in table_report)
        checks.append(_check(
            "table_header_repeat", header_ok, tables=table_report,
            detail=("first row of every table repeats as a header"
                    if header_ok else
                    "table(s) without w:tblHeader on the first row: " +
                    str([t["table"] for t in table_report
                         if not t["header_repeat"]]))))
        checks.append(_check(
            "table_cantSplit", split_ok, tables=table_report,
            detail=("every row forbids splitting" if split_ok else
                    "row(s) may split across pages: " +
                    str([(t["table"], t["rows_missing_cantSplit"])
                         for t in table_report
                         if t["rows_missing_cantSplit"]]))))

    # -- figure captions keepNext -----------------------------------------
    caption_paragraphs = []
    for index, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text.strip()
        if CAPTION_RE.match(text):
            caption_paragraphs.append({
                "index": index, "text": text[:120],
                "instruction": "图" if text.lstrip().startswith("图") else "表",
                "keep_next": bool(paragraph._p.xpath("./w:pPr/w:keepNext")),
            })
    figure_captions = [c for c in caption_paragraphs if c["instruction"] == "图"]
    images = doc.element.body.xpath(".//wp:inline | .//wp:anchor")
    if not figure_captions:
        if images:
            checks.append(_check(
                "caption_keepNext", False, status="failed",
                detail=f"{len(images)} image(s) but no 图N caption paragraph; "
                       "the figure/caption pairing cannot be judged"))
        else:
            checks.append(_check("caption_keepNext", True,
                                 status="not_applicable", severity="info",
                                 detail="no image and no figure caption"))
            not_applicable.append("caption_keepNext")
    else:
        missing = [c for c in figure_captions if not c["keep_next"]]
        checks.append(_check(
            "caption_keepNext", not missing, captions=len(figure_captions),
            detail=("every figure caption is kept with its figure"
                    if not missing else
                    f"{len(missing)} figure caption(s) lack w:keepNext: " +
                    str([c["index"] for c in missing][:10]))))

    # -- cross references --------------------------------------------------
    objects = {"图": set(), "表": set()}
    for caption in caption_paragraphs:
        match = CAPTION_RE.match(caption["text"])
        if match:
            objects[match.group(1)].add(int(match.group(2)))
    references = {"图": set(), "表": set()}
    for paragraph in doc.paragraphs:
        text = paragraph.text
        if CAPTION_RE.match(text.strip()):
            continue                      # the caption defines, it does not cite
        for match in LABEL_RE.finditer(text):
            references[match.group(1)].add(int(match.group(2)))
    missing_refs = {kind: sorted(value - objects[kind])
                    for kind, value in references.items()}
    dangling = {k: v for k, v in missing_refs.items() if v}
    if not any(references.values()) and not any(objects.values()):
        checks.append(_check("cross_references", True, status="not_applicable",
                             severity="info",
                             detail="no 图N/表N label and no caption in the "
                                    "document"))
        not_applicable.append("cross_references")
    else:
        checks.append(_check(
            "cross_references", not dangling,
            references={k: sorted(v) for k, v in references.items()},
            objects={k: sorted(v) for k, v in objects.items()},
            missing=missing_refs,
            detail=("every 图N/表N reference has a matching caption"
                    if not dangling else
                    "reference(s) without an object: " + json.dumps(
                        dangling, ensure_ascii=False))))

    # -- run fonts ---------------------------------------------------------
    runs = _runs_with_text(doc)
    font_report = {"runs_with_text": len(runs), "with_rFonts": 0,
                   "missing_ascii": 0, "missing_hAnsi": 0, "missing_eastAsia": 0,
                   "examples": []}
    for run, text in runs:
        fonts = run.xpath("./w:rPr/w:rFonts")
        attributes = fonts[0].attrib if fonts else {}
        if fonts:
            font_report["with_rFonts"] += 1
        absent = [key for key in ("ascii", "hAnsi", "eastAsia")
                  if not attributes.get(qn(f"w:{key}"))]
        for key in absent:
            font_report[f"missing_{key}"] += 1
        if absent and len(font_report["examples"]) < 5:
            font_report["examples"].append({"text": text[:40],
                                            "missing": absent})
    if not runs:
        checks.append(_check("run_fonts", True, status="not_applicable",
                             severity="info", detail="no text run in the document"))
        not_applicable.append("run_fonts")
    else:
        complete = all(font_report[f"missing_{key}"] == 0
                       for key in ("ascii", "hAnsi", "eastAsia"))
        checks.append(_check(
            "run_fonts", complete, severity="warning", font_report=font_report,
            detail=("every run declares ascii/hAnsi/eastAsia"
                    if complete else
                    "run(s) do not declare ascii/hAnsi/eastAsia; a run "
                    "without eastAsia falls back to the theme font for Chinese "
                    "(warning, not a rendering failure)")))
        if not complete:
            warnings.append(
                f"{font_report['missing_eastAsia']}/{len(runs)} run(s) lack "
                f"w:rFonts/@w:eastAsia; Chinese text will fall back to the "
                f"theme font")

    # -- PDF pages ---------------------------------------------------------
    pages_reviewed: list[dict] = []
    pdf_info = None
    if not pdf_path or not os.path.isfile(str(pdf_path)):
        checks.append(_check("pdf_pages", False, path=str(pdf_path),
                             detail="PDF not found; page count and blank pages "
                                    "cannot be judged"))
    else:
        try:
            pdf_info = inspect_pdf(pdf_path)
        except LayoutError as exc:                      # pragma: no cover
            checks.append(_check("pdf_pages", False, path=str(pdf_path),
                                 detail=str(exc)))
            pdf_info = None
        if pdf_info is not None:
            pages_reviewed = _pages_reviewed(pdf_info)
            blank = [page["page"] for page in pdf_info["pages"]
                     if page["text_chars"] == 0 and not page["images"]]
            ok = pdf_info["page_count"] > 0 and not blank
            checks.append(_check(
                "pdf_pages", ok, page_count=pdf_info["page_count"],
                blank_pages=blank,
                detail=(f"{pdf_info['page_count']} page(s), no blank page"
                        if ok else
                        (f"blank page(s): {blank}" if blank else
                         "the PDF has no page"))))

    failed = [c for c in checks
              if c["status"] == "failed" and c["severity"] == "error"]
    unassessed_checks = [c for c in checks if c["status"] == "unassessed"]
    unassessed = [{"check": c["check"], "reason": c.get("detail", "")}
                  for c in unassessed_checks]
    ok = not failed and not unassessed_checks
    status = "failed" if failed else (
        "unassessed" if unassessed_checks else "passed")
    return {
        "ok": ok,
        "status": status,
        "docx": path,
        "pdf": str(pdf_path),
        "checks": checks,
        "warnings": warnings,
        "unassessed": unassessed,
        "not_applicable": not_applicable,
        "font_report": font_report,
        "tables": table_report,
        "caption_paragraphs": len(caption_paragraphs),
        "pages_reviewed": pages_reviewed,
    }


# ---------------------------------------------------------------------------
# v2 record
# ---------------------------------------------------------------------------
def _producer() -> dict:
    return C.producer_for("layout_check", version=VERSION, module_file=__file__)


def _input_ref(project, kind: str, rel: str) -> dict:
    """Input reference bound to the artefact's bytes, not just its name."""
    ref = {"kind": kind, "id": str(rel)}
    path = Path(str(rel))
    if not path.is_absolute():
        path = project.root / path
    try:
        if path.is_file():
            ref["sha256"] = C.file_sha256(path)
    except OSError:                                     # pragma: no cover
        pass
    return ref


def record_check(project, result: dict, *, docx_rel: str,
                 pdf_rel: str, notes: str | None = None) -> dict:
    """Write the result as a v2 ``layout_check`` record.

    ``status`` follows ``result['ok']`` (passed / failed).  An unmeasurable
    check already forced ``ok`` false in :func:`check_placement`, so it lands as
    a failed record with the reason in ``checks``/``notes`` - never a pass.

    ``pages_reviewed`` must come from an actual PDF read; a placeholder is
    refused rather than written, because a record whose pages were never looked
    at is worse than no record.
    """
    if not isinstance(project, C.Project):
        project = C.Project(project)
    pages = result.get("pages_reviewed") or []
    if not pages:
        raise LayoutError(
            "pages_reviewed is empty: the record must carry the pages that were "
            "actually read (text volume / image count), not a placeholder. "
            "Read the PDF first (inspect_pdf) and pass its pages through.")
    images = _jsonable(result.get("images") or [])
    checks = _jsonable(result.get("checks") or [])
    ok = bool(result.get("ok"))
    status = "passed" if ok else "failed"
    unverifiable = _jsonable(result.get("unverifiable") or [])

    note_parts = []
    if notes:
        note_parts.append(str(notes))
    if unverifiable:
        note_parts.append("unverifiable: " + json.dumps(unverifiable,
                                                        ensure_ascii=False))
    payload = {
        "docx": str(docx_rel),
        "pdf": str(pdf_rel),
        "images": images,
        "checks": checks,
        "pages_reviewed": _jsonable(pages),
        "notes": "; ".join(note_parts)[:4000],
    }
    if result.get("font_report"):
        payload["font_report"] = _jsonable(result["font_report"])

    identity = {"docx": str(docx_rel), "pdf": str(pdf_rel),
                "images": sorted((image.get("sha256") or "")
                                 for image in images)}
    rid = "layout-" + C.canonical_hash(identity)[:16]
    previous = project.latest("layout_check", rid)
    revision = 1
    if previous is not None:
        C.check_transition("layout_check", previous["status"], status)
        revision = int(previous["revision"]) + 1

    record = C.make_record(
        "layout_check", rid, payload,
        producer=_producer(), status=status, revision=revision,
        input_refs=[_input_ref(project, "docx", docx_rel),
                    _input_ref(project, "pdf", pdf_rel)])
    project.append("layout_check", record, enforce_transition=False)
    return record


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _rel_to(root: str | os.PathLike, path: str | os.PathLike) -> str:
    root_path = Path(root).resolve()
    target = Path(path).resolve()
    try:
        return target.relative_to(root_path).as_posix()
    except ValueError:
        return target.as_posix()


def _parse_pairs(items, flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in str(item):
            raise LayoutError(f"{flag} expects KEY=VALUE, got {item!r}")
        key, value = str(item).split("=", 1)
        out[key.strip()] = value
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check figures/layout at their final DOCX/PDF placement size")
    parser.add_argument("--root", default=".",
                        help="project root; records go to <root>/output/v2")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="dump DOCX/PDF placement data")
    p_inspect.add_argument("--docx", required=True)
    p_inspect.add_argument("--pdf", default=None)
    p_inspect.add_argument("--pretty", action="store_true")

    p_check = sub.add_parser("check", help="check declared figures end to end")
    p_check.add_argument("--docx", required=True)
    p_check.add_argument("--pdf", required=True)
    p_check.add_argument("--figure", action="append", default=[],
                         metavar="PNG=FIGURE_ID",
                         help="declare a figure; repeat for each figure")
    p_check.add_argument("--figure-caption", action="append", default=[],
                         metavar="FIGURE_ID=TEXT",
                         help="caption text of a declared figure")
    p_check.add_argument("--min-dpi", type=float, default=DEFAULT_MIN_DPI)
    p_check.add_argument("--min-fontsize", type=float, default=DEFAULT_MIN_FONTSIZE)
    p_check.add_argument("--record", action="store_true",
                         help="write a v2 layout_check record")
    p_check.add_argument("--pretty", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            payload = {"docx": inspect_docx(args.docx)}
            if args.pdf:
                pdf_info = inspect_pdf(args.pdf)
                payload["pdf"] = pdf_info
                payload["match"] = match_images(payload["docx"], pdf_info)
            print(json.dumps(payload, ensure_ascii=False,
                             indent=2 if args.pretty else None,
                             default=str))
            return 0

        captions = _parse_pairs(args.figure_caption, "--figure-caption")
        figures = []
        for item in args.figure:
            if "=" not in str(item):
                raise LayoutError(f"--figure expects PNG=FIGURE_ID, got {item!r}")
            png, figure_id = str(item).split("=", 1)
            figures.append({"figure_id": figure_id.strip(), "png": png,
                            "caption": captions.get(figure_id.strip(), ""),
                            "figure_record": C.Project(args.root).latest("figure_spec",figure_id.strip())})
        result = check_placement(args.docx, args.pdf, figures=figures,
                                 min_dpi=args.min_dpi,
                                 min_fontsize=args.min_fontsize)
        if args.record:
            project = C.Project(args.root)
            record = record_check(project, result,
                                  docx_rel=_rel_to(args.root, args.docx),
                                  pdf_rel=_rel_to(args.root, args.pdf))
            result["record"] = {"id": record["id"],
                                "status": record["status"],
                                "revision": record["revision"],
                                "ledger": str(project.ledger_path("layout_check"))}
        print(json.dumps(result, ensure_ascii=False,
                         indent=2 if args.pretty else None, default=str))
        return 0 if result.get("ok") else 2
    except LayoutError as exc:
        print(json.dumps({"ok": False,
                          "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
