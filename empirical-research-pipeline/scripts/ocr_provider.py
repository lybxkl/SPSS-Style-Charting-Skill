# -*- coding: utf-8 -*-
"""OCR providers and visual evidence.

The contract this module enforces:

* **No OCR text is a fact.**  A transcription is stored as a ``source_unit`` of
  type ``region``/``page`` with ``status='partial'`` and an explicit
  ``unrecovered`` note.  `verify_dataset` will not accept an OCR transcript as
  proof that the original image contains that value; a human/agent re-read of
  the original page is required (``adjudicate``).
* **Coordinates resolve.**  Every OCR block keeps pixel bbox in the rendered
  preview *and* the transform (scale / origin / page rotation) needed to map it
  back into original page points, so a crop can be located again (A05).
* **Providers are replaceable and honest.**  ``RapidOCR`` (onnxruntime, no
  external binary) and ``Tesseract`` (external binary) are real adapters; when
  neither is installed the provider reports ``available() == False`` and the
  caller records a real ``engine_missing`` receipt instead of an empty success.

CLI::

    python ocr_provider.py --root . providers
    python ocr_provider.py --root . page --unit <unit_id> [--provider rapidocr]
    python ocr_provider.py --root . adjudicate --unit <unit_id> \\
        --text "1,284.50" --reviewer agent:me --note "re-read page 1"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C
import source_units as SU


def _producer(**kw) -> dict:
    return C.producer_for("ocr_provider", version="2.0", module_file=__file__,
                          **kw)


class OcrUnavailable(RuntimeError):
    pass


class OcrProvider:
    name = "base"
    version = "0"

    def available(self) -> bool:
        raise NotImplementedError

    def reason(self) -> str:
        return "not available"

    def recognize(self, image_path: str, *, lang: str | None = None) -> list[dict]:
        """Return ``[{text, bbox_px:[x0,y0,x1,y1], conf}]``."""
        raise NotImplementedError


class RapidOcrProvider(OcrProvider):
    """RapidOCR (PP-OCR models on onnxruntime) - offline, no system binary."""

    name = "rapidocr"

    def __init__(self, *, use_det: bool = True, use_cls: bool = True,
                 use_rec: bool = True):
        self.version = "?"
        self._engine = None
        self._params = {"use_det": use_det, "use_cls": use_cls,
                        "use_rec": use_rec}

    def available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except Exception:
            return False

    def reason(self) -> str:
        return ("rapidocr_onnxruntime is not installed (pip install "
                "rapidocr_onnxruntime)") if not self.available() else "ok"

    def _get(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            import rapidocr_onnxruntime as rr
            self.version = getattr(rr, "__version__", "?")
            self._engine = RapidOCR()
        return self._engine

    def recognize(self, image_path: str, *, lang: str | None = None) -> list[dict]:
        import numpy as np
        from PIL import Image
        engine = self._get()
        with Image.open(image_path) as img:
            arr = np.array(img.convert("RGB"))
        result, _elapse = engine(arr)
        blocks = []
        for item in result or []:
            box, text, conf = item[0], item[1], item[2]
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            blocks.append({"text": text,
                           "bbox_px": [min(xs), min(ys), max(xs), max(ys)],
                           "conf": float(conf)})
        return blocks


class TesseractProvider(OcrProvider):
    name = "tesseract"
    version = "5"

    def available(self) -> bool:
        import shutil
        return shutil.which("tesseract") is not None

    def reason(self) -> str:
        return "tesseract binary not on PATH" if not self.available() else "ok"

    def recognize(self, image_path: str, *, lang: str | None = None) -> list[dict]:
        import shutil
        import subprocess
        exe = shutil.which("tesseract")
        if not exe:
            raise OcrUnavailable(self.reason())
        cmd = [exe, image_path, "stdout", "tsv", "-l", lang or "eng"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if out.returncode != 0:
            raise OcrUnavailable(f"tesseract failed: {out.stderr[:400]}")
        rows = [ln.split("\t") for ln in out.stdout.splitlines()[1:] if ln.strip()]
        lines: dict[tuple, dict] = {}
        for row in rows:
            if len(row) < 12 or row[0] != "5":
                continue
            key = (row[1], row[2], row[3], row[4])
            text = row[11]
            conf = float(row[10]) / 100.0
            x, y, w, h = (int(row[6]), int(row[7]), int(row[8]), int(row[9]))
            entry = lines.setdefault(key, {"text": "", "bbox_px": [x, y, x, y],
                                           "conf": 0.0})
            entry["text"] += text
            entry["bbox_px"] = [min(entry["bbox_px"][0], x),
                                min(entry["bbox_px"][1], y),
                                max(entry["bbox_px"][2], x + w),
                                max(entry["bbox_px"][3], y + h)]
            entry["conf"] = max(entry["conf"], conf)
        return list(lines.values())


class UnavailableProvider(OcrProvider):
    name = "unavailable"
    version = "0"

    def __init__(self, why: str):
        self._why = why

    def available(self) -> bool:
        return False

    def reason(self) -> str:
        return self._why

    def recognize(self, image_path: str, *, lang: str | None = None):
        raise OcrUnavailable(self._why)


def providers() -> dict[str, OcrProvider]:
    return {"rapidocr": RapidOcrProvider(), "tesseract": TesseractProvider()}


def get_provider(name: str | None = None) -> OcrProvider:
    table = providers()
    if name:
        prov = table.get(name)
        if prov is None:
            raise SystemExit(f"unknown OCR provider {name!r}; known: "
                             f"{sorted(table)}")
        if not prov.available():
            raise OcrUnavailable(f"{name}: {prov.reason()}")
        return prov
    for prov in table.values():
        if prov.available():
            return prov
    why = "; ".join(f"{p.name}: {p.reason()}" for p in table.values())
    raise OcrUnavailable(f"no OCR provider available ({why})")


# ---------------------------------------------------------------------------
# transforms
# ---------------------------------------------------------------------------
def page_transform(unit: Mapping, *, dpi: int) -> dict:
    """Transform between the rendered preview and original page coordinates.

    ``page_size_pt`` is the *displayed* (rotation-applied) frame; the mapping
    back to the original page uses the unrotated ``media_size_pt`` recorded on
    the unit, which is why both are kept.
    """
    data = unit["data"]
    scope = data["recovered_scope"]
    media = scope.get("media_size_pt") or scope.get("page_size_pt") or [595, 842]
    display = scope.get("page_size_pt") or media
    rotation = float(data.get("rotation") or 0.0)
    scale = dpi / 72.0
    dw, dh = display
    return {"scale": scale, "origin": [0.0, 0.0], "rotation": rotation,
            "page_size_pt": [media[0], media[1]],
            "display_size_pt": [dw, dh],
            "preview_px": [round(dw * scale, 2), round(dh * scale, 2)],
            "coord_unit": "pt"}


def px_to_page(bbox_px: Iterable[float], transform: Mapping) -> list[float]:
    """Map preview pixel bbox → original (unrotated) page points."""
    s = transform["scale"]
    ox, oy = transform["origin"]
    w, h = transform["page_size_pt"]
    rot = int(round(transform["rotation"])) % 360
    x0, y0, x1, y1 = (float(v) for v in bbox_px)
    # back to the *displayed* page frame
    dx0, dy0, dx1, dy1 = (x0 / s + ox, y0 / s + oy, x1 / s + ox, y1 / s + oy)
    if rot == 0:
        return [round(dx0, 3), round(dy0, 3), round(dx1, 3), round(dy1, 3)]
    if rot == 90:      # displayed is the page rotated 90° clockwise
        return [round(dy0, 3), round(h - dx1, 3), round(dy1, 3),
                round(h - dx0, 3)]
    if rot == 180:
        return [round(w - dx1, 3), round(h - dy1, 3), round(w - dx0, 3),
                round(h - dy0, 3)]
    if rot == 270:
        return [round(w - dy1, 3), round(dx0, 3), round(w - dy0, 3),
                round(dx1, 3)]
    raise ValueError(f"unsupported rotation {rot}")


def page_to_px(bbox_page: Iterable[float], transform: Mapping) -> list[float]:
    s = transform["scale"]
    w, h = transform["page_size_pt"]
    rot = int(round(transform["rotation"])) % 360
    x0, y0, x1, y1 = (float(v) for v in bbox_page)
    if rot == 0:
        d = [x0, y0, x1, y1]
    elif rot == 90:
        d = [y0, h - x1, y1, h - x0]
    elif rot == 180:
        d = [w - x1, h - y1, w - x0, h - y0]
    elif rot == 270:
        d = [w - y1, x0, w - y0, x1]
    else:
        raise ValueError(f"unsupported rotation {rot}")
    return [round(v * s, 3) for v in d]


def iou(a: Iterable[float], b: Iterable[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return 0.0 if union <= 0 else inter / union


# ---------------------------------------------------------------------------
# running OCR on a page unit
# ---------------------------------------------------------------------------
def ocr_page(project: C.Project, units: SU.SourceUnits, unit: Mapping, *,
             provider: OcrProvider | None = None, dpi: int | None = None,
             lang: str | None = None) -> dict:
    """OCR one page/image unit; store region units + a receipt.

    Returns ``{"provider", "blocks", "transform", "regions", "status"}``.
    When the provider is unavailable the page keeps its ``partial`` status and
    the receipt records ``engine_missing`` - never an empty success.
    """
    data = unit["data"]
    preview = data.get("preview")
    if not preview:
        su_any = units
        if unit["data"]["unit_type"] == "image":
            preview = su_any._loc(project.root / unit["data"]["source"]) \
                if not Path(unit["data"]["source"]).is_absolute() \
                else unit["data"]["source"]
        else:
            raise ValueError(f"unit {unit['id']} has no rendered preview; "
                             f"render the page first")
    preview_path = project.root / preview
    if not preview_path.is_file():
        preview_path = Path(preview)
    try:
        prov = provider or get_provider()
    except OcrUnavailable as exc:
        receipt = units.receipt(data["source"], data["source_sha256"], [{
            "step": "ocr", "engine": "none", "outcome": str(exc)}],
            "failed", failure_class="engine_missing",
            notes="page remains partial; transcription is not a fact")
        project.append("recovery_receipt", receipt, enforce_transition=False)
        return {"provider": None, "blocks": [], "regions": [], "status": "failed",
                "reason": str(exc), "receipt": receipt["id"]}
    dpi = dpi or units.preview_dpi
    transform = page_transform(unit, dpi=dpi)
    try:
        blocks = prov.recognize(str(preview_path), lang=lang)
    except OcrUnavailable as exc:
        receipt = units.receipt(data["source"], data["source_sha256"], [{
            "step": "ocr", "engine": prov.name,
            "outcome": str(exc)}], "failed", failure_class="engine_missing")
        project.append("recovery_receipt", receipt, enforce_transition=False)
        return {"provider": prov.name, "blocks": [], "regions": [],
                "status": "failed", "reason": str(exc),
                "receipt": receipt["id"]}
    except Exception as exc:                            # noqa: BLE001
        receipt = units.receipt(data["source"], data["source_sha256"], [{
            "step": "ocr", "engine": prov.name,
            "outcome": f"{type(exc).__name__}: {exc}"}], "failed",
            failure_class="other")
        project.append("recovery_receipt", receipt, enforce_transition=False)
        return {"provider": prov.name, "blocks": [], "regions": [],
                "status": "failed", "reason": str(exc),
                "receipt": receipt["id"]}
    regions: list[dict] = []
    for i, block in enumerate(blocks):
        bbox_page = px_to_page(block["bbox_px"], transform)
        locator = {"type": "page_region",
                   "page": data.get("page", 1),
                   "bbox": bbox_page,
                   "bbox_px": [round(v, 2) for v in block["bbox_px"]],
                   "ocr_block": i}
        payload = {
            "source": data["source"], "source_sha256": data["source_sha256"],
            "unit_type": "region", "parent_source": data["source"],
            "locator": locator, "page": data.get("page", 1),
            "bbox": bbox_page, "coord_unit": "pt",
            "rotation": transform["rotation"], "scale": transform["scale"],
            "representation": data["representation"],
            "representation_sha256": data["representation_sha256"],
            "engine": {"name": prov.name, "version": getattr(prov, "version", "?"),
                       "params": {"lang": lang, "dpi": dpi,
                                  "transform": transform}},
            "recovered_scope": {"transcript": block["text"],
                                "confidence": round(block["conf"], 4),
                                "preview_px": [round(v, 2)
                                               for v in block["bbox_px"]]},
            "unrecovered": ["OCR transcription is not a verified reading of the "
                            "image; the original page must be re-read before a "
                            "value is used as a fact"],
            "preview": preview,
            "notes": "ocr",
        }
        rec, _ = units.upsert(payload, status="partial")
        regions.append({"unit": rec["id"], "text": block["text"],
                        "bbox_page": bbox_page, "conf": block["conf"]})
    receipt = units.receipt(
        data["source"], data["source_sha256"],
        [{"step": "ocr", "engine": prov.name,
          "version": getattr(prov, "version", "?"), "blocks": len(blocks),
          "dpi": dpi, "transform": transform}], "recovered",
        notes=f"{len(blocks)} region(s) transcribed; still requires an original-"
              f"image re-read")
    project.append("recovery_receipt", receipt, enforce_transition=False)
    return {"provider": prov.name, "blocks": blocks, "transform": transform,
            "regions": regions, "status": "partial", "receipt": receipt["id"]}


def adjudicate(project: C.Project, units: SU.SourceUnits, region_unit: Mapping,
               corrected_text: str, *, reviewer: str, note: str,
               supports: bool = True) -> dict:
    """Record a human/agent re-read of the *original* page.

    The OCR transcript is kept in ``extensions.ocr_transcript`` for the audit
    trail; the unit's ``recovered_scope.transcript`` becomes the re-read value
    and the engine block names the human method.  A dependent cell must be
    re-prepared: the old review is invalidated by the new revision.
    """
    if not reviewer or not note:
        raise ValueError("a re-read needs an actual reviewer and a note")
    data = dict(region_unit["data"])
    scope = dict(data["recovered_scope"])
    old = scope.get("transcript")
    scope["ocr_transcript"] = old
    scope["transcript"] = corrected_text
    scope["reread_by"] = reviewer
    scope["reread_note"] = note
    scope["reread_supports_original"] = bool(supports)
    data["recovered_scope"] = scope
    data["engine"] = {"name": "human-reread", "version": "1",
                      "params": {"reviewer": reviewer}}
    data["unrecovered"] = [] if supports else [
        "re-read contradicts the extracted value"]
    rec = C.make_record("source_unit", region_unit["id"], data,
                        producer=_producer(), status="recovered",
                        revision=region_unit["revision"] + 1)
    project.append("source_unit", rec)
    event = C.make_record("review_event",
                          f"ocr-reread:{region_unit['id']}:r{rec['revision']}",
                          {"dataset": "<source-unit>", "key": [region_unit["id"]],
                           "target_type": "source_unit", "source_sha256": data["source_sha256"],
                           "unit_revision": rec["revision"], "unit_signature": C.signature(rec),
                           "column": "transcript", "value_under_review": str(old),
                           "record_sha256": C.signature(region_unit),
                           "method": "source_reread", "reviewer": reviewer,
                           "independence": "independent_of_ocr",
                           "reread_scope": {"source": data["source"],
                                            "locator": data["locator"]},
                           "second_pass": {"transcript": corrected_text,
                                           "supports_original": bool(supports)},
                           "outcome": "corrected" if old != corrected_text
                           else "confirmed",
                           "checked_at": C._now(), "reason": note},
                          producer=_producer(), status="recorded")
    project.append("review_event", event, enforce_transition=False)
    return {"unit": rec["id"], "revision": rec["revision"],
            "old": old, "new": corrected_text, "event": event["id"]}


def visual_evidence_check(unit: Mapping, preview_path: str) -> dict:
    """Machine-checkable part of visual evidence: files, hashes, geometry."""
    checks = []
    data = unit["data"]
    checks.append({"check": "representation_hash",
                   "ok": C.file_sha256(preview_path) == data.get(
                       "representation_sha256", "")})
    bbox = data.get("bbox")
    if bbox:
        w, h = (data.get("recovered_scope", {}).get("page_size_pt") or [None, None])
        if w and h:
            inside = (0 <= bbox[0] < bbox[2] <= w + 0.5 and
                      0 <= bbox[1] < bbox[3] <= h + 0.5)
            checks.append({"check": "bbox_inside_page", "ok": inside})
    checks.append({"check": "transcript_is_not_a_fact", "ok": True,
                   "note": "machine can verify geometry/version only; the "
                           "original image still needs a re-read"})
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "semantic_verification": "not_possible_by_machine"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="OCR providers and visual evidence")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("providers")
    p_page = sub.add_parser("page")
    p_page.add_argument("--unit", required=True)
    p_page.add_argument("--provider")
    p_page.add_argument("--dpi", type=int, default=150)
    p_page.add_argument("--lang")
    p_adj = sub.add_parser("adjudicate")
    p_adj.add_argument("--unit", required=True)
    p_adj.add_argument("--text", required=True)
    p_adj.add_argument("--reviewer", required=True)
    p_adj.add_argument("--note", required=True)
    p_adj.add_argument("--contradicts", action="store_true")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    units = SU.SourceUnits(proj, root=Path(args.root))
    if args.cmd == "providers":
        for name, prov in providers().items():
            print(f"{name:10s} available={prov.available()} {prov.reason()}")
        return 0
    unit = proj.latest("source_unit", args.unit)
    if unit is None:
        print(f"unknown unit {args.unit}", file=sys.stderr)
        return 2
    if args.cmd == "page":
        res = ocr_page(proj, units, unit, dpi=args.dpi, lang=args.lang,
                       provider=get_provider(args.provider)
                       if args.provider else None)
        print(json.dumps({k: v for k, v in res.items() if k != "blocks"},
                         ensure_ascii=False, indent=1))
        for region in res["regions"]:
            print(f"  {region['text']!r} conf={region['conf']:.3f} "
                  f"bbox={region['bbox_page']}")
        return 0 if res["status"] != "failed" else 2
    if args.cmd == "adjudicate":
        res = adjudicate(proj, units, unit, args.text, reviewer=args.reviewer,
                         note=args.note, supports=not args.contradicts)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
