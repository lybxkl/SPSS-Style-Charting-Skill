# -*- coding: utf-8 -*-
"""Source units: page/region/table/segment-level view of the original material.

`audit_corpus.py` answers "which files exist and can we read them"; this module
answers "which *units* inside each file did we actually read, where exactly, and
what is still unrecovered".  A unit is a page, a region, a table, a sheet, a
paragraph, a container member, an image, or a timed media segment; each one
carries a locator that resolves back into the original file, the representation
we produced, and the engine/parameters that produced it.

Three counts are kept apart on purpose:

* ``physical_files``   - files in the material tree (a zip counts once)
* ``logical_units``    - units after container expansion and structure splitting
* ``observations``     - units that carry independent empirical content; an
  extracted container member or a byte-identical copy is a logical unit but
  not a new observation.

CLI::

    python source_units.py --root . build --materials materials
    python source_units.py --root . list --type page
    python source_units.py --root . summary
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C


def member_suffix(name):
    suffix = Path(name).suffix
    return suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,16}", suffix) else ".bin"

TEXT_EXT = {".txt", ".md", ".rst", ".log", ".srt", ".vtt", ".tex", ".py", ".r"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
MEDIA_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4", ".mov", ".mkv",
             ".avi", ".webm", ".wmv"}
TABLE_EXT = {".csv", ".tsv", ".xlsx", ".xlsm", ".xls"}
STRUCT_EXT = {".json", ".jsonl", ".ndjson", ".yaml", ".yml", ".xml"}
OFFICE_EXT = {".docx", ".pptx"}
ARCHIVE_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"}
PDF_EXT = {".pdf"}

CONTAINER_KINDS = {"zip": "zip", "pdf_attachment": "pdf_attachment",
                   "office_embedded": "office_embedded"}

FAILURE_CLASSES = (
    "engine_missing",        # no reader/OCR/ASR installed
    "language_unsupported",  # engine has no model for the language
    "encrypted",             # needs a password we do not have
    "corrupt",               # bytes are damaged
    "empty",                 # zero bytes / no content
    "unsupported_format",    # no adapter at all
    "out_of_scope",          # user excluded it
    "other",
    "permission",
)


def failure_class(exc):
    if isinstance(exc,(UnicodeError,LookupError)):return "language_unsupported"
    if isinstance(exc,ImportError):return "engine_missing"
    if isinstance(exc,PermissionError):return "permission"
    if type(exc).__name__ in ("BadZipFile","FileDataError","JSONDecodeError","VerificationError","ParseError","InvalidFileException"):
        return "corrupt"
    return "other"


def source_digest(path):
    try:return C.file_sha256(path)
    except OSError:return ""


def _producer(**kw) -> dict:
    return C.producer_for("source_units", version="2.0", module_file=__file__,
                          **kw)


def classify(path: str | os.PathLike) -> str:
    ext = Path(path).suffix.lower()
    if ext in PDF_EXT:
        return "pdf"
    if ext in TEXT_EXT:
        return "text"
    if ext in OFFICE_EXT:
        return "office"
    if ext in (".doc",".xls",".ppt"):
        return "legacy_office"
    if ext in TABLE_EXT:
        return "table"
    if ext in STRUCT_EXT:
        return "structured"
    if ext in IMAGE_EXT:
        return "image"
    if ext in MEDIA_EXT:
        return "media"
    if ext in ARCHIVE_EXT:
        return "archive"
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("text/"):
        return "text"
    return "unsupported"


def unit_id(source_rel: str, unit_type: str, locator: Mapping) -> str:
    raw = C.canonical_json({"source": source_rel, "type": unit_type,
                            "locator": locator})
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


class SourceUnits:
    """Builds and reads the unit ledger for one project."""

    def __init__(self, project: C.Project, *, root: str | os.PathLike | None = None,
                 preview_dpi: int = 150, preview_all_pages: bool = False, encodings=None):
        self.project = project
        self.root = Path(root) if root else project.root
        self.rep_dir = project.path("units", "rep")
        self.preview_dir = project.path("units", "previews")
        self.container_dir = project.path("containers")
        self.rep_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self.container_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dpi = preview_dpi
        self.preview_all_pages = preview_all_pages
        self.encodings = dict(encodings or {})
        manifest = project.path("units", "materials.json")
        if manifest.is_file():
            self.materials_root = Path(json.loads(manifest.read_text(encoding="utf-8"))["root"])
        self._existing: dict[str, dict] | None = None

    # -- ledger helpers ----------------------------------------------------
    def _load(self) -> None:
        if self._existing is None:
            self._existing = {}
            for rec in self.project.read("source_unit"):
                self._existing[rec["id"]] = rec
        return None

    def upsert(self, payload: dict, *, status: str = "recovered") -> tuple[dict, bool]:
        """Insert or bump a unit.  Returns (record, changed)."""
        self._load()
        uid = unit_id(payload["source"], payload["unit_type"], payload["locator"])
        prev = self._existing.get(uid)
        if prev is None:
            rec = C.make_record("source_unit", uid, payload, producer=_producer(),
                                status=status)
            self.project.append("source_unit", rec)
            self._existing[uid] = rec
            return rec, True
        same = C.canonical_hash(prev["data"]) == C.canonical_hash(payload)
        if same and prev["status"] == status and prev["producer"].get("code_sha256")==C.file_sha256(__file__):
            return prev, False
        rec = C.make_record("source_unit", uid, payload, producer=_producer(),
                            status=status, revision=prev["revision"] + 1,
                            supersedes=f"source_unit:{uid}@r{prev['revision']}")
        self.project.append("source_unit", rec)
        self._existing[uid] = rec
        return rec, True

    def units(self, unit_type: str | None = None, source: str | None = None) -> list[dict]:
        rows = self.project.read("source_unit")
        latest: dict[str, dict] = {}
        for rec in rows:
            if rec["id"] not in latest or rec["revision"] > latest[rec["id"]]["revision"]:
                latest[rec["id"]] = rec
        out = list(latest.values())
        manifest = self.project.path("units", "materials.json")
        if manifest.is_file():
            material = json.loads(manifest.read_text(encoding="utf-8"))
            base = Path(material["root"])
            current = {}
            for r in out:
                rel = r["data"]["source"]
                if rel not in current:
                    path = (base / rel).resolve()
                    current[rel] = source_digest(path) if path.is_file() and base.resolve() in path.parents else None
            out = [r for r in out if current[r["data"]["source"]] == r["data"]["source_sha256"]]
            if "active_ids" in material:
                from verify_dataset import parse_time
                ids=set(material["active_ids"])
                out=[r for r in out if r["id"] in ids or parse_time(r["created_at"])>parse_time(material["completed_at"])]
        if unit_type:
            out = [r for r in out if r["data"]["unit_type"] == unit_type]
        if source:
            out = [r for r in out if r["data"]["source"] == source]
        return sorted(out, key=lambda r: (r["data"]["source"],
                                          r["data"].get("page") or 0,
                                          r["id"]))

    # -- representation ----------------------------------------------------
    def representation_path(self,unit):
        data=unit["data"];name=data["representation"]
        path=(self.project.root/name).resolve()
        if not path.is_file() and name==data["source"]:
            path=(getattr(self,"materials_root",self.root)/name).resolve()
        if not path.is_file() or C.file_sha256(path)!=data["representation_sha256"]:
            raise C.IntegrityError(f"source representation is missing or changed: {unit['id']}")
        return path

    def review_scope(self,ident,*,report,reviewer,note,remaining):
        """Bind an actual whole-unit recovery review, including remaining gaps.

        The report is authored AFTER opening the original and must explain
        coverage, recovered children and irrelevant regions. It is evidence of
        a stated review, not a machine proof that the reviewer read correctly.
        """
        if not reviewer.strip() or not note.strip() or not isinstance(remaining,list) or any(not isinstance(x,str) or not x.strip() for x in remaining):
            raise ValueError("scope review needs identity, concrete note and an explicit list of remaining gaps")
        unit=next((r for r in self.units() if r["id"]==ident),None)
        if unit is None:raise ValueError("source unit is missing or belongs to old source bytes")
        report=Path(report);report=(report if report.is_absolute() else self.project.root/report).resolve()
        if not report.is_file() or not report.stat().st_size:raise ValueError("write the actual whole-unit review report first")
        source=(getattr(self,"materials_root",self.root)/unit["data"]["source"]).resolve()
        if source_digest(source)!=unit["data"]["source_sha256"] or report==source:
            raise ValueError("review report must be separate from the current original source")
        data=dict(unit["data"]);scope=dict(data["recovered_scope"])
        scope["whole_unit_review"]={"report":self._loc(report),"report_sha256":C.file_sha256(report),
            "reviewer":reviewer,"note":note,"checked_at":C._now(),"previous_unit_signature":C.signature(unit)}
        data.update(recovered_scope=scope,unrecovered=list(remaining))
        self._existing=None  # OCR/ASR reviewers may have appended through another object.
        rec,_=self.upsert(data,status="partial" if remaining else "recovered")
        return rec

    def write_rep(self, uid: str, data: bytes | str, suffix: str = ".txt") -> tuple[str, str]:
        raw = data.encode("utf-8") if isinstance(data, str) else data
        digest=hashlib.sha256(raw).hexdigest()
        path = C.protect_output(self.project,self.rep_dir / f"{uid}-{digest}{suffix}")
        if not path.is_file() or C.file_sha256(path)!=digest:
            import txn
            txn._write_atomic(path,raw)
        return path.relative_to(self.project.root).as_posix(),digest

    def _loc(self, path: Path) -> str:
        """Project-relative when inside the project, absolute otherwise.

        Material roots may live outside the project directory; a preview path
        that only works from one working directory would be a latent bug.
        """
        try:
            return path.resolve().relative_to(self.project.root).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def _upsert_container(self, payload: dict) -> dict:
        cid = hashlib.sha1(
            f"{payload['source']}|{payload['container_type']}".encode()
        ).hexdigest()[:20]
        prev = self.project.latest("container", cid)
        if prev is not None and C.canonical_hash(prev["data"]) == \
                C.canonical_hash(payload):
            return prev
        rec = C.make_record("container", cid, payload, producer=_producer(),
                            status="enumerated") if prev is None else \
            C.make_record("container", cid, payload, producer=_producer(),
                          status="enumerated", revision=prev["revision"] + 1)
        self.project.append("container", rec, enforce_transition=False)
        return rec

    def receipt(self, source: str, source_sha: str, attempts: list[dict],
                outcome: str, *, failure_class: str | None = None,
                notes: str | None = None) -> dict:
        rid = hashlib.sha1(f"{source}|{outcome}".encode()).hexdigest()[:20]
        payload = {"source": source, "source_sha256": source_sha,
                   "attempts": attempts, "outcome": outcome}
        if failure_class:
            if failure_class not in FAILURE_CLASSES:
                raise ValueError(f"unknown failure class {failure_class!r}")
            payload["failure_class"] = failure_class
        if notes:
            payload["notes"] = notes
        return C.make_record("recovery_receipt", rid, payload, producer=_producer())

    # -- dispatch ----------------------------------------------------------
    def build(self, materials_root: str | os.PathLike) -> dict:
        root = Path(materials_root)
        if not root.is_dir():
            raise SystemExit(f"materials root not found: {root}")
        #: remembered so consumers (index, discovery) can resolve the relative
        #: ``source`` paths the units carry
        self.materials_root = root.resolve()
        if self.project.dir == root.resolve() or root.resolve() in self.project.dir.parents:
            raise ValueError("materials and generated output must be separate; refusing to ingest this project's output as source")
        physical = sorted(p for p in root.rglob("*") if p.is_file())
        built: list[str] = []
        receipts: list[dict] = []
        for path in physical:
            rel = _rel(root, path)
            kind = classify(path)
            try:
                units, recs = self.build_one(path, rel)
                built.extend(u["id"] for u in units)
                receipts.extend(recs)
            except Exception as exc:                       # noqa: BLE001
                receipts.append(self.receipt(
                    rel, source_digest(path),
                    [{"step": "dispatch", "engine": kind,
                      "outcome": f"{type(exc).__name__}: {exc}"}],
                    "failed", failure_class=failure_class(exc),
                    notes="adapter raised; recorded as a real failure, not empty"))
        for rec in receipts:
            previous = self.project.latest("recovery_receipt", rec["id"])
            if previous and previous["data"] == rec["data"] and previous["producer"] == rec["producer"]:
                continue
            if previous:
                rec = C.make_record("recovery_receipt", rec["id"], rec["data"], producer=rec["producer"], status=rec["status"], revision=previous["revision"]+1)
            self.project.append("recovery_receipt", rec, enforce_transition=False)
        payload={"root":str(root.resolve()), "inventory":{_rel(root,p):source_digest(p) for p in physical},
                 "active_ids":sorted(set(built)),"producer_sha256":C.file_sha256(__file__)}
        manifest=self.project.path("units","materials.json")
        previous=json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else None
        if not previous or {k:v for k,v in previous.items() if k!="completed_at"}!=payload:
            self.project.write_snapshot("units/materials.json", {**payload,"completed_at":C._now()})
        summary = self.summary(physical=len(physical))
        self.project.write_snapshot("units/index.json", summary)
        return summary

    def build_one(self, path: Path, rel: str) -> tuple[list[dict], list[dict]]:
        kind = classify(path)
        sha = C.file_sha256(path)
        if kind == "pdf":
            return self._pdf(path, rel, sha)
        if kind == "text":
            return self._text(path, rel, sha)
        if kind == "office":
            return self._office(path, rel, sha)
        if kind == "table":
            return self._table(path, rel, sha)
        if kind == "structured":
            return self._structured(path, rel, sha)
        if kind == "image":
            return self._image(path, rel, sha)
        if kind == "media":
            return self._media(path, rel, sha)
        if kind == "archive":
            return self._archive(path, rel, sha)
        if kind == "legacy_office":
            rec = self.receipt(rel, sha, [{
                "step": "convert", "engine": "none",
                "outcome": ".doc/.xls/.ppt need a manual re-save as docx/xlsx/pptx"}],
                "failed", failure_class="unsupported_format",
                notes="conversion is a user step; the file stays in the inventory")
            return [], [rec]
        rec = self.receipt(rel, sha, [{"step": "dispatch", "engine": "none",
                                       "outcome": "no adapter for this format"}],
                           "failed", failure_class="unsupported_format")
        return [], [rec]

    # -- per-format adapters ----------------------------------------------
    def _decode(self, path, rel):
        raw = path.read_bytes()
        encoding = self.encodings.get(rel)
        if encoding is None:
            encoding = "utf-32" if raw.startswith((b"\xff\xfe\x00\x00",b"\x00\x00\xfe\xff")) else "utf-16" if raw.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8-sig"
        return raw.decode(encoding, errors="strict"), encoding

    def _text(self, path: Path, rel: str, sha: str) -> tuple[list[dict], list[dict]]:
        text, encoding = self._decode(path,rel)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        uid = unit_id(rel, "document", {"type": "text", "start": 0, "end": len(text)})
        rep_rel, rep_sha = self.write_rep(uid, text)
        payload = {
            "source": rel, "source_sha256": sha, "unit_type": "document",
            "parent_source": rel,
            "locator": {"type": "text", "start": 0, "end": len(text), "encoding":encoding},
            "representation": rep_rel, "representation_sha256": rep_sha,
            "engine": {"name": "strict-decode", "version": "1", "params": {"encoding":encoding}},
            "recovered_scope": {"chars": len(text), "encoding": encoding},
            "unrecovered": [] if "\ufffd" not in text else
                           ["literal replacement characters in decoded source; verify the original context"],
        }
        rec, _ = self.upsert(payload)
        return [rec], []

    def _pdf(self, path: Path, rel: str, sha: str) -> tuple[list[dict], list[dict]]:
        import fitz
        if not fitz:
            raise RuntimeError("PyMuPDF unavailable")
        units: list[dict] = []
        receipts: list[dict] = []
        try:
            doc = fitz.open(path)
        except Exception as exc:                            # noqa: BLE001
            receipts.append(self.receipt(
                rel, sha, [{"step": "open", "engine": "pymupdf",
                            "outcome": f"{type(exc).__name__}: {exc}"}],
                "failed", failure_class=failure_class(exc)))
            return [], receipts
        if doc.needs_pass:
            doc.close()
            receipts.append(self.receipt(
                rel, sha, [{"step": "open", "engine": "pymupdf",
                            "outcome": "password protected"}],
                "failed", failure_class="encrypted"))
            return [], receipts
        page_count = doc.page_count
        attachments = list(doc.embfile_names())
        for pno in range(page_count):
            page = doc.load_page(pno)
            text = page.get_text("text")
            rect = page.rect
            infos = page.get_image_info()
            image_area = 0.0
            for info in infos:
                bbox = fitz.Rect(info["bbox"])
                image_area += max(0.0, bbox.get_area())
            page_area = max(1.0, rect.get_area())
            scan_fraction = min(1.0, image_area / page_area)
            has_text = bool(text.strip())
            if has_text and scan_fraction < 0.35:
                page_kind = "text"
            elif has_text:
                page_kind = "mixed"
            elif scan_fraction > 0:
                page_kind = "scan"
            else:
                page_kind = "blank"
            uid = unit_id(rel, "page", {"type": "pdf_page", "page": pno + 1})
            rep_rel, rep_sha = self.write_rep(uid, text)
            preview = None
            if self.preview_all_pages or page_kind in ("scan", "mixed") or \
                    page.rotation % 360:
                preview = self._render_pdf_page(doc, pno, uid)
            unrecovered: list[str] = []
            if page_kind == "scan":
                unrecovered = ["no text layer: OCR required before the page "
                               "counts as read"]
            elif page_kind == "mixed":
                unrecovered = [f"image area covers {scan_fraction:.0%} of the "
                               f"page: embedded/scanned regions need OCR"]
            elif page_kind == "blank":
                unrecovered = ["no text and no image content"]
            payload = {
                "source": rel, "source_sha256": sha, "unit_type": "page",
                "parent_source": rel,
                "locator": {"type": "pdf_page", "page": pno + 1},
                "page": pno + 1,
                "representation": rep_rel, "representation_sha256": rep_sha,
                "engine": {"name": "pymupdf", "version": fitz.__doc__.split()[1]
                           if fitz.__doc__ else "?",
                           "params": {"text_mode": "text"}},
                "recovered_scope": {"chars": len(text), "page_kind": page_kind,
                                    "image_area_fraction": round(scan_fraction, 4),
                                    "page_size_pt": [round(rect.width, 2),
                                                     round(rect.height, 2)],
                                    "media_size_pt": [
                                        round(page.mediabox.width, 2),
                                        round(page.mediabox.height, 2)],
                                    "has_text_layer": has_text},
                "unrecovered": unrecovered,
                "bbox": [0, 0, round(rect.width, 2), round(rect.height, 2)],
                "coord_unit": "pt",
                "rotation": float(page.rotation),
            }
            if preview:
                payload["preview"] = preview
            rec, _ = self.upsert(payload, status="recovered" if not unrecovered
                                 else "partial")
            units.append(rec)
        if attachments:
            recs = self._pdf_attachments(doc, path, rel, sha, attachments)
            units.extend(recs[0])
            receipts.extend(recs[1])
        doc.close()
        return units, receipts

    def _render_pdf_page(self, doc, pno: int, uid: str) -> str:
        import fitz
        page = doc.load_page(pno)
        zoom = self.preview_dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        raw=pix.tobytes("png")
        out = self.preview_dir / f"{uid}-{hashlib.sha256(raw).hexdigest()}.png"
        import txn
        txn._write_atomic(out,raw)
        return out.relative_to(self.project.root).as_posix()

    def _pdf_attachments(self, doc, path: Path, rel: str, sha: str,
                         names: list[str]) -> tuple[list[dict], list[dict]]:
        units: list[dict] = []
        receipts: list[dict] = []
        dest = self.container_dir / sha[:16] / "pdf_attachments"
        dest.mkdir(parents=True, exist_ok=True)
        members = []
        for member_index, name in enumerate(names):
            try:
                data = doc.embfile_get(name)
            except Exception as exc:                        # noqa: BLE001
                receipts.append(self.receipt(
                    rel, sha, [{"step": "pdf_attachment", "member": name,
                                "outcome": f"{type(exc).__name__}: {exc}"}],
                    "failed", failure_class="corrupt"))
                continue
            target = dest / f"{member_index:08d}-{hashlib.sha256(name.encode()).hexdigest()}{member_suffix(name)}"
            target.write_bytes(data)
            member_sha = hashlib.sha256(data).hexdigest()
            members.append({"path": name, "sha256": member_sha,
                            "bytes": len(data),
                            "extracted": target.relative_to(
                                self.project.root).as_posix()})
            uid = unit_id(rel, "attachment", {"type": "pdf_attachment",
                                               "name": name})
            payload = {
                "source": rel, "source_sha256": sha, "unit_type": "attachment",
                "parent_source": rel,
                "locator": {"type": "pdf_attachment", "name": name},
                "container_path": name,
                "representation": target.relative_to(
                    self.project.root).as_posix(),
                "representation_sha256": member_sha,
                "engine": {"name": "pymupdf.embfile_get", "version": "1",
                           "params": {}},
                "recovered_scope": {"bytes": len(data)},
                "unrecovered": [],
            }
            rec, _ = self.upsert(payload)
            units.append(rec)
        cid = hashlib.sha1(f"{rel}|pdf_attachment".encode()).hexdigest()[:20]
        self._upsert_container({"source": rel, "source_sha256": sha,
                                "container_type": "pdf_attachment",
                                "members": members,
                                "counts": {"members": len(members)}})
        return units, receipts

    def _office(self, path: Path, rel: str, sha: str) -> tuple[list[dict], list[dict]]:
        if path.suffix.lower()==".pptx":
            return self._presentation(path,rel,sha)
        from docx import Document
        units: list[dict] = []
        receipts: list[dict] = []
        try:
            doc = Document(str(path))
        except Exception as exc:                            # noqa: BLE001
            receipts.append(self.receipt(
                rel, sha, [{"step": "open", "engine": "python-docx",
                            "outcome": f"{type(exc).__name__}: {exc}"}],
                "failed", failure_class=failure_class(exc)))
            return [], receipts
        full = "\n".join(p.text for p in doc.paragraphs)
        for i, para in enumerate(doc.paragraphs):
            if not para.text.strip():
                continue
            uid = unit_id(rel, "paragraph", {"type": "docx_paragraph",
                                             "index": i})
            rep_rel, rep_sha = self.write_rep(uid, para.text)
            payload = {
                "source": rel, "source_sha256": sha, "unit_type": "paragraph",
                "parent_source": rel,
                "locator": {"type": "docx_paragraph", "index": i},
                "representation": rep_rel, "representation_sha256": rep_sha,
                "engine": {"name": "python-docx", "version": "1", "params": {}},
                "recovered_scope": {"chars": len(para.text),
                                    "style": para.style.name if para.style else ""},
                "unrecovered": [],
            }
            rec, _ = self.upsert(payload)
            units.append(rec)
        for ti, table in enumerate(doc.tables):
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            uid = unit_id(rel, "table", {"type": "docx_table", "index": ti})
            rep_rel, rep_sha = self.write_rep(
                uid, json.dumps(rows, ensure_ascii=False))
            payload = {
                "source": rel, "source_sha256": sha, "unit_type": "table",
                "parent_source": rel,
                "locator": {"type": "docx_table", "index": ti},
                "representation": rep_rel, "representation_sha256": rep_sha,
                "engine": {"name": "python-docx", "version": "1",
                           "params": {"shape": [len(rows),
                                                len(rows[0]) if rows else 0]}},
                "recovered_scope": {"rows": len(rows),
                                    "cols": len(rows[0]) if rows else 0},
                "unrecovered": [],
            }
            rec, _ = self.upsert(payload)
            units.append(rec)
        # embedded objects live in the OOXML package, not in the API
        units.extend(self._office_notes(path, rel, sha))
        units.extend(self._office_embedded(path, rel, sha, receipts))
        if not units:
            receipts.append(self.receipt(rel, sha, [{
                "step": "extract", "engine": "python-docx",
                "outcome": "no paragraph and no table"}], "failed",
                failure_class="empty"))
        return units, receipts

    def _presentation(self,path,rel,sha):
        """Preserve native slide/notes paragraphs, tables, media and objects.

        Parts and XML are retained as locations. Shapes/chart drawings without
        recoverable text remain explicit visual gaps rather than empty success.
        """
        import xml.etree.ElementTree as ET
        A="{http://schemas.openxmlformats.org/drawingml/2006/main}"
        units=[];receipts=[]
        with zipfile.ZipFile(path) as package:
            parts=[name for name in package.namelist() if re.fullmatch(r"ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml",name)]
            if not parts:raise ValueError("presentation contains no slide or notes XML parts")
            for part in sorted(parts):
                root=ET.fromstring(package.read(part))
                tables=list(root.iter(A+"tbl"));table_paragraphs={id(p) for table in tables for p in table.iter(A+"p")}
                fragments=[("paragraph",index,p) for index,p in enumerate(root.iter(A+"p")) if id(p) not in table_paragraphs]
                fragments.extend(("table",index,table) for index,table in enumerate(tables))
                for kind,index,fragment in fragments:
                    if kind=="table":
                        content=json.dumps([["\n".join("".join(t.text or "" for t in p.iter(A+"t")) for p in cell.iter(A+"p")) for cell in row.findall(A+"tc")] for row in fragment.findall(A+"tr")],ensure_ascii=False)
                    else:
                        content="".join(t.text or "" for t in fragment.iter(A+"t"))
                        if not content.strip():continue
                    locator={"type":"pptx_xml","part":part,"element":kind,"index":index}
                    uid=unit_id(rel,kind,locator);rep,rep_sha=self.write_rep(uid,content)
                    rec,_=self.upsert({"source":rel,"source_sha256":sha,"unit_type":kind,"parent_source":rel,"locator":locator,
                        "representation":rep,"representation_sha256":rep_sha,"engine":{"name":"ooxml-native-xml","version":"1","params":{}},
                        "recovered_scope":{"part":part,"native_xml":ET.tostring(fragment,encoding="unicode")},"unrecovered":[]})
                    units.append(rec)
                if part.startswith("ppt/slides/"):
                    locator={"type":"pptx_xml","part":part,"element":"slide"};uid=unit_id(rel,"page",locator)
                    rep,rep_sha=self.write_rep(uid,package.read(part).decode("utf-8"))
                    rec,_=self.upsert({"source":rel,"source_sha256":sha,"unit_type":"page","parent_source":rel,"locator":locator,
                        "representation":rep,"representation_sha256":rep_sha,"engine":{"name":"ooxml-native-xml","version":"1","params":{}},
                        "recovered_scope":{"part":part,"native_xml":True},"unrecovered":["Slide appearance, charts, SmartArt and shape relations require visual/native review; text extraction is not a complete slide interpretation."]})
                    units.append(rec)
        units.extend(self._office_embedded(path,rel,sha,receipts))
        return units,receipts

    def _office_notes(self, path, rel, sha):
        """Recover footnotes/endnotes/comments/headers/footers with native IDs."""
        import xml.etree.ElementTree as ET
        W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        units = []
        with zipfile.ZipFile(path) as package:
            parts = [name for name in package.namelist() if re.fullmatch(r"word/(footnotes|endnotes|comments|header\d+|footer\d+)\.xml", name)]
            for part in parts:
                root = ET.fromstring(package.read(part))
                fragments = list(root) if part in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml") else [root]
                for index, fragment in enumerate(fragments):
                    if fragment.get(W+"type") in ("separator", "continuationSeparator"):
                        continue
                    text = "".join(node.text or "" for node in fragment.iter() if node.tag.endswith("}t"))
                    if not text.strip():
                        continue
                    locator = {"type": "ooxml", "part": part, "index": index,
                               "element_id": fragment.get(W+"id"), "element": fragment.tag}
                    uid = unit_id(rel, "paragraph", locator)
                    rep, rep_sha = self.write_rep(uid, text)
                    rec, _ = self.upsert({"source": rel, "source_sha256": sha, "unit_type": "paragraph", "parent_source": rel,
                        "locator": locator, "representation": rep, "representation_sha256": rep_sha,
                        "engine": {"name": "ooxml-native-xml", "version": "1", "params": {}},
                        "recovered_scope": {"part": part, "chars": len(text), "native_xml": ET.tostring(fragment, encoding="unicode")}, "unrecovered": []})
                    units.append(rec)
        return units

    def _office_embedded(self, path: Path, rel: str, sha: str,
                         receipts: list[dict]) -> list[dict]:
        out: list[dict] = []
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            return out
        members = []
        dest = self.container_dir / sha[:16] / "office_embedded"
        dest.mkdir(parents=True, exist_ok=True)
        with zf:
            embedded = [(i, info.filename, zf.read(info)) for i, info in enumerate(zf.infolist())
                        if "/embeddings/" in info.filename or "/media/" in info.filename]
        if not embedded:
            return out
        for member_index, name, data in embedded:
            target = dest / f"{member_index:08d}-{hashlib.sha256(name.encode()).hexdigest()}{member_suffix(name)}"
            target.write_bytes(data)
            member_sha = hashlib.sha256(data).hexdigest()
            members.append({"path": name, "sha256": member_sha,
                            "bytes": len(data),
                            "extracted": target.relative_to(
                                self.project.root).as_posix()})
            uid = unit_id(rel, "embedded", {"type": "office_embedded",
                                            "name": name, "index": member_index})
            kind = "object" if "/embeddings/" in name else "image"
            payload = {
                "source": rel, "source_sha256": sha, "unit_type": kind,
                "parent_source": rel,
                "locator": {"type": "office_embedded", "name": name, "index": member_index},
                "container_path": name,
                "representation": target.relative_to(
                    self.project.root).as_posix(),
                "representation_sha256": member_sha,
                "engine": {"name": "zipfile", "version": "1", "params": {}},
                "recovered_scope": {"bytes": len(data)},
                "unrecovered": [],
            }
            rec, _ = self.upsert(payload)
            out.append(rec)
        self._upsert_container({"source": rel, "source_sha256": sha,
                                "container_type": "office_embedded",
                                "members": members,
                                "counts": {"members": len(members)}})
        return out

    def _table(self, path: Path, rel: str, sha: str) -> tuple[list[dict], list[dict]]:
        ext = path.suffix.lower()
        units: list[dict] = []
        receipts: list[dict] = []
        if ext in (".csv", ".tsv"):
            text, encoding = self._decode(path,rel)
            lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            import csv
            rows = [row for row in csv.reader(io.StringIO(text), delimiter="\t" if ext == ".tsv" else ",") if row]
            uid = unit_id(rel, "table", {"type": "delimited", "delimiter":
                                          "\t" if ext == ".tsv" else ","})
            rep_rel, rep_sha = self.write_rep(uid, text)
            payload = {
                "source": rel, "source_sha256": sha, "unit_type": "table",
                "parent_source": rel,
                "locator": {"type": "delimited", "rows": len(rows), "delimiter": "\t" if ext == ".tsv" else ",", "encoding":encoding},
                "representation": rep_rel, "representation_sha256": rep_sha,
                "engine": {"name": "csv-text", "version": "1",
                           "params": {"encoding": encoding}},
                "recovered_scope": {"logical_records": max(0, len(rows) - 1),
                                    "header": rows[0] if rows else ""},
                "unrecovered": [],
            }
            rec, _ = self.upsert(payload)
            return [rec], receipts
        import openpyxl
        try:
            wb = openpyxl.load_workbook(path, data_only=False)
            wb_cache = openpyxl.load_workbook(path, data_only=True)
        except Exception as exc:                            # noqa: BLE001
            receipts.append(self.receipt(
                rel, sha, [{"step": "open", "engine": "openpyxl",
                            "outcome": f"{type(exc).__name__}: {exc}"}],
                "failed", failure_class="corrupt"))
            return [], receipts
        for ws in wb.worksheets:
            cache_ws = wb_cache[ws.title]
            uid = unit_id(rel, "sheet", {"type": "xlsx_sheet",
                                          "sheet": ws.title})
            cells = []
            formulas = 0
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue
                    entry = {"cell": cell.coordinate, "value": cell.value,
                             "data_type": cell.data_type,
                             "number_format": cell.number_format}
                    if cell.data_type == "f":
                        formulas += 1
                        cached = cache_ws[cell.coordinate].value
                        entry["cached"] = cached
                        entry["cache_present"] = cached is not None
                    cells.append(entry)
            rep_rel, rep_sha = self.write_rep(
                uid, json.dumps({"sheet": ws.title, "cells": cells},
                                ensure_ascii=False, default=str))
            epoch = getattr(wb, "epoch", None)
            epoch_text = epoch.date().isoformat() if hasattr(epoch, "date") \
                else str(epoch or "1899-12-30")
            payload = {
                "source": rel, "source_sha256": sha, "unit_type": "sheet",
                "parent_source": rel,
                "locator": {"type": "xlsx_sheet", "sheet": ws.title},
                "representation": rep_rel, "representation_sha256": rep_sha,
                "engine": {"name": "openpyxl", "version": "1",
                           "params": {"data_only": False,
                                      "cache_compared": True}},
                "recovered_scope": {"cells": len(cells),
                                    "formulas": formulas,
                                    "dimensions": ws.dimensions,
                                    "epoch": epoch_text},
                "unrecovered": ["formula cells keep their formula; the cached "
                                "value is never used as a checked fact"
                                ] if formulas else [],
            }
            rec, _ = self.upsert(payload, status="partial" if formulas
                                 else "recovered")
            units.append(rec)
        return units, receipts

    def _structured(self, path: Path, rel: str, sha: str) -> tuple[list[dict], list[dict]]:
        raw, encoding = self._decode(path,rel)
        import verify_dataset as VD
        def strict_json(text):
            return json.loads(text, object_pairs_hook=VD._pairs, parse_float=__import__("decimal").Decimal,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"nonfinite JSON: {value}")))
        ext = path.suffix.lower()
        if ext in (".jsonl", ".ndjson"):
            rows = [ln for ln in raw.splitlines() if ln.strip()]
            for i, line in enumerate(rows, 1):
                strict_json(line)
            locator = {"type": "jsonl", "records": len(rows)}
            shape = {"records": len(rows)}
        elif ext == ".json":
            strict_json(raw)
            locator = {"type": "json", "pointer": ""}
            shape = {"bytes":path.stat().st_size,"chars":len(raw)}
        else:
            locator = {"type": "raw", "format": ext.lstrip(".")}
            shape = {"bytes":path.stat().st_size,"chars":len(raw)}
        locator["encoding"]=encoding
        uid = unit_id(rel, "document", locator)
        rep_rel, rep_sha = self.write_rep(uid, raw)
        payload = {
            "source": rel, "source_sha256": sha, "unit_type": "document",
            "parent_source": rel, "locator": locator,
            "representation": rep_rel, "representation_sha256": rep_sha,
            "engine": {"name": "stdlib-json", "version": "1", "params": {"encoding":encoding}},
            "recovered_scope": shape, "unrecovered": [],
        }
        rec, _ = self.upsert(payload)
        return [rec], []

    def _image(self, path: Path, rel: str, sha: str) -> tuple[list[dict], list[dict]]:
        from PIL import Image
        with Image.open(path) as img:
            size = img.size
            mode = img.mode
        uid = unit_id(rel, "image", {"type": "image", "page": 1})
        payload = {
            "source": rel, "source_sha256": sha, "unit_type": "image",
            "parent_source": rel,
            "locator": {"type": "image", "bbox": [0, 0, size[0], size[1]]},
            "representation": rel, "representation_sha256": sha,
            "engine": {"name": "pillow", "version": "1", "params": {}},
            "recovered_scope": {"px": list(size), "mode": mode},
            "unrecovered": ["pixels only: text/values need OCR and then an "
                            "original-image re-read"],
            "bbox": [0, 0, size[0], size[1]], "coord_unit": "px",
            "preview": self._loc(path),
        }
        rec, _ = self.upsert(payload, status="partial")
        return [rec], []

    def _media(self, path: Path, rel: str, sha: str) -> tuple[list[dict], list[dict]]:
        uid = unit_id(rel, "media", {"type": "media", "start": 0})
        payload = {
            "source": rel, "source_sha256": sha, "unit_type": "media",
            "parent_source": rel,
            "locator": {"type": "media", "start": 0, "end": None},
            "representation": rel, "representation_sha256": sha,
            "engine": {"name": "none", "version": "0", "params": {}},
            "recovered_scope": {"bytes": path.stat().st_size},
            "unrecovered": ["no transcript yet: ASR must run before any "
                            "spoken content counts as read"],
        }
        rec, _ = self.upsert(payload, status="pending")
        return [rec], []

    def _archive(self, path: Path, rel: str, sha: str) -> tuple[list[dict], list[dict]]:
        if path.suffix.lower() != ".zip":
            return [], [self.receipt(
                rel, sha, [{"step": "open", "engine": "none",
                            "outcome": "only .zip is enumerated automatically"}],
                "failed", failure_class="unsupported_format")]
        units: list[dict] = []
        receipts: list[dict] = []
        members = []
        dest = self.container_dir / sha[:16]
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            return [], [self.receipt(
                rel, sha, [{"step": "open", "engine": "zipfile",
                            "outcome": str(exc)}], "failed",
                failure_class="corrupt")]
        with zf:
            for member_index, info in enumerate(zf.infolist()):
                if info.is_dir():
                    continue
                try:
                    data = zf.read(info)
                except RuntimeError as exc:
                    receipts.append(self.receipt(
                        rel, sha, [{"step": "member", "member": info.filename,
                                    "outcome": str(exc)}], "failed",
                        failure_class="encrypted"))
                    continue
                # Member names are metadata, never filesystem authority.
                # Index preserves duplicate names instead of overwriting them.
                target = dest / f"{member_index:08d}-{hashlib.sha256(info.filename.encode()).hexdigest()}{member_suffix(info.filename)}"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                member_sha = hashlib.sha256(data).hexdigest()
                members.append({"path": info.filename, "sha256": member_sha,
                                "bytes": len(data),
                                "extracted": target.relative_to(
                                    self.project.root).as_posix()})
                uid = unit_id(rel, "member", {"type": "zip_member",
                                              "name": info.filename, "index": member_index})
                payload = {
                    "source": rel, "source_sha256": sha, "unit_type": "member",
                    "parent_source": rel,
                    "locator": {"type": "zip_member", "name": info.filename, "index": member_index},
                    "container_path": info.filename,
                    "representation": target.relative_to(
                        self.project.root).as_posix(),
                    "representation_sha256": member_sha,
                    "engine": {"name": "zipfile", "version": "1", "params": {}},
                    "recovered_scope": {"bytes": len(data)},
                    "unrecovered": [],
                }
                rec, _ = self.upsert(payload)
                units.append(rec)
        cid = hashlib.sha1(f"{rel}|zip".encode()).hexdigest()[:20]
        self._upsert_container({"source": rel, "source_sha256": sha,
                                "container_type": "zip", "members": members,
                                "counts": {"members": len(members)}})
        return units, receipts

    # -- summary -----------------------------------------------------------
    def summary(self, *, physical: int | None = None) -> dict:
        units = self.units()
        containers = self.project.read("container")
        receipts = self.project.read("recovery_receipt")
        by_type: dict[str, int] = {}
        seen_rep: dict[str, str] = {}
        observations = 0
        copies: list[str] = []
        for u in units:
            d = u["data"]
            by_type[d["unit_type"]] = by_type.get(d["unit_type"], 0) + 1
            key = f"{d['representation_sha256']}|{d['unit_type']}"
            if key in seen_rep:
                copies.append(u["id"])
                continue
            seen_rep[key] = u["id"]
            observations += 1
        failed = [r for r in receipts if r["data"]["outcome"] == "failed"]
        return {
            "physical_files": physical if physical is not None else
            len({u["data"]["source"] for u in units}),
            "logical_units": len(units),
            "observations": observations,
            "observations_semantics": "legacy unique-representation count; never statistical N",
            "unique_representations": observations,
            "independent_observations": None,
            "duplicate_representation_units": len(copies),
            "by_unit_type": dict(sorted(by_type.items())),
            "recovery_receipts": len(receipts),
            "recovery_receipts_semantics":"historical attempts; current recovery must be judged from active units, unrecovered scopes and the source-generation manifest",
            "failed_recoveries": len(failed),
            "failure_classes": sorted({r["data"].get("failure_class")
                                       for r in failed
                                       if r["data"].get("failure_class")}),
            "containers": len(containers),
            "container_members": sum(len(c["data"]["members"])
                                     for c in containers),
            "unrecovered_units": sum(1 for u in units if u["data"]["unrecovered"]),
        }

    # -- preview / crop ----------------------------------------------------
    def crop_page(self, unit: Mapping, bbox_px: list[float], *,
                  scale: float = 1.0, origin: tuple[float, float] = (0.0, 0.0),
                  rotation: float = 0.0, out_name: str | None = None) -> dict:
        """Crop a page preview and map the crop back to page coordinates.

        ``bbox_px`` is in the *rendered* image's pixel frame.  The returned
        record carries the affine transform used, so the crop can be located
        in the original page again (A05).
        """
        from PIL import Image
        preview_rel = unit["data"].get("preview")
        if not preview_rel:
            raise SystemExit(f"unit {unit['id']} has no preview to crop")
        src = self.project.root / preview_rel
        with Image.open(src) as img:
            img = img.convert("RGB")
            x0, y0, x1, y1 = bbox_px
            x0 = max(0, min(img.width - 1, x0))
            x1 = max(x0 + 1, min(img.width, x1))
            y0 = max(0, min(img.height - 1, y0))
            y1 = max(y0 + 1, min(img.height, y1))
            crop = img.crop((x0, y0, x1, y1))
            out_name = out_name or f"{unit['id']}_crop_{int(x0)}_{int(y0)}.png"
            path = self.preview_dir / out_name
            crop.save(path)
        page_bbox = [round(origin[0] + x0 / scale, 3),
                     round(origin[1] + y0 / scale, 3),
                     round(origin[0] + x1 / scale, 3),
                     round(origin[1] + y1 / scale, 3)]
        return {
            "unit": unit["id"], "preview": preview_rel,
            "crop": path.relative_to(self.project.root).as_posix(),
            "crop_px": [x0, y0, x1, y1], "page_bbox": page_bbox,
            "scale": scale, "origin": list(origin), "rotation": rotation,
            "coord_unit": unit["data"].get("coord_unit", "pt"),
        }

    def map_to_page(self, unit: Mapping, bbox_page: list[float], *,
                    scale: float, origin: tuple[float, float] = (0.0, 0.0),
                    page_size: tuple[float, float] | None = None) -> list[float]:
        """Inverse of :meth:`crop_page`: page points -> preview pixels."""
        if page_size:
            w, h = page_size
            if not (0 <= bbox_page[0] < bbox_page[2] <= w + 1e-6 and
                    0 <= bbox_page[1] < bbox_page[3] <= h + 1e-6):
                raise ValueError(f"bbox {bbox_page} outside page {page_size}")
        return [round((bbox_page[0] - origin[0]) * scale, 3),
                round((bbox_page[1] - origin[1]) * scale, 3),
                round((bbox_page[2] - origin[0]) * scale, 3),
                round((bbox_page[3] - origin[1]) * scale, 3)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="source unit recovery")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser("build")
    p_build.add_argument("--materials", required=True)
    p_build.add_argument("--encodings",help="JSON mapping of material-relative names to explicitly selected encodings")
    p_build.add_argument("--preview-dpi", type=int, default=150)
    p_build.add_argument("--preview-all-pages", action="store_true")
    p_list = sub.add_parser("list")
    p_list.add_argument("--type")
    p_list.add_argument("--source")
    sub.add_parser("summary")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    su = SourceUnits(proj, root=Path(args.root) / "materials",
                     encodings=json.loads(Path(args.encodings).read_text(encoding="utf-8")) if getattr(args,"encodings",None) else None,
                     preview_dpi=getattr(args, "preview_dpi", 150),
                     preview_all_pages=getattr(args, "preview_all_pages", False))
    if args.cmd == "build":
        summary = su.build(args.materials)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "list":
        for rec in su.units(args.type, args.source):
            d = rec["data"]
            print(f"{rec['id']} {rec['status']:9s} {d['source']} "
                  f"{d['unit_type']} {json.dumps(d['locator'], ensure_ascii=False)}")
        return 0
    if args.cmd == "summary":
        print(json.dumps(su.summary(), ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
