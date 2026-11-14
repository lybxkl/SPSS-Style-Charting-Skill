# -*- coding: utf-8 -*-
"""Native → audit-view conversion with an *independent* structural check.

A file hash proves identity, not that the conversion was lossless.  This module
therefore builds a flat audit view (one row per value) and verifies it by
re-reading the native file through a **different** mechanism:

* ``.xlsx``  builder uses openpyxl; the verifier parses ``xl/worksheets/*.xml``
  and ``xl/sharedStrings.xml`` directly, so a shared bug in one reader cannot
  make both agree.
* ``.json``/``.jsonl`` builder uses :func:`json.loads`; the verifier re-parses
  with ``parse_float=Decimal``, detects duplicate keys with an
  ``object_pairs_hook`` and compares the *raw text* of every number against the
  view, so float rounding or a dropped field is visible.
* ``.csv`` the view is a byte-preserving normalisation; the verifier re-reads it
  with the ``csv`` module and compares field counts and exact strings.

It also owns two data-semantics rules the rest of the pipeline depends on:

* legal empty tables need range evidence, and an empty table never reports
  ``0/0 = 100%`` coverage (A46);
* generated values (estimated/imputed/simulated/image-approximation) must
  declare method and uncertainty and are never written into the observed layer
  (A58).

CLI::

    python audit_view.py --root . build --path materials/book.xlsx
    python audit_view.py --root . verify --view output/v2/views/<id>.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import io
import json
import os
import re
import sys
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C

VALUE_KINDS = {
    "observed": "read directly from the material",
    "encoded": "an explicit coding/mapping of an observed value",
    "derived": "deterministically computed from checked cells",
    "structural": "an identifier/position that is not empirical data",
    "missing": "genuinely absent, with a reason and re-read context",
    "estimated": "model estimate: carries method + uncertainty",
    "imputed": "filled-in value: carries method + uncertainty",
    "simulated": "simulation output: carries method + uncertainty",
    "image_approx": "digitised from a figure: carries calibration + error",
}

OBLIGATIONS: dict[str, tuple[str, ...]] = {
    "observed": ("sources",),
    "encoded": ("sources", "rule"),
    "derived": ("inputs", "rule"),
    "structural": ("sources",),
    "missing": ("reason", "sources"),
    "estimated": ("method", "uncertainty", "inputs"),
    "imputed": ("method", "uncertainty", "sources"),
    "simulated": ("method", "uncertainty", "inputs"),
    "image_approx": ("method", "uncertainty", "sources"),
}


class AuditError(Exception):
    pass


def _producer(**kw) -> dict:
    return C.producer_for("audit_view", version="2.0", module_file=__file__,
                          **kw)


def value_kind_obligations(kind: str, record: Mapping) -> dict:
    """Check that a value carries what its provenance kind owes."""
    if kind not in VALUE_KINDS:
        raise AuditError(f"unknown value kind {kind!r}; expected "
                         f"{sorted(VALUE_KINDS)}")
    missing = [f for f in OBLIGATIONS[kind] if not record.get(f)]
    return {"ok": not missing, "kind": kind, "missing": missing,
            "observed_layer": kind in ("observed", "encoded")}


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def build_csv_view(path: Path, out: Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    out.write_text(normalised, encoding="utf-8", newline="\n")
    rows = list(csv.reader(io.StringIO(normalised)))
    widths = {len(r) for r in rows if r}
    return {"kind": "csv", "rows": len(rows), "columns": len(rows[0]) if rows
            else 0, "ragged_widths": sorted(widths), "bom": raw[:3] == b"\xef\xbb\xbf"}


def verify_csv(native: Path, view: Path) -> dict:
    raw_native = native.read_bytes().decode("utf-8-sig")
    raw_view = view.read_text(encoding="utf-8")
    a = list(csv.reader(io.StringIO(raw_native.replace("\r\n", "\n"))))
    b = list(csv.reader(io.StringIO(raw_view)))
    checks = [
        {"check": "row_count", "ok": len(a) == len(b),
         "native": len(a), "view": len(b)},
        {"check": "cell_values", "ok": a == b,
         "first_difference": _first_diff(a, b)},
    ]
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def _first_diff(a, b):
    for i, (ra, rb) in enumerate(zip(a, b)):
        if ra != rb:
            return {"row": i, "native": ra, "view": rb}
    if len(a) != len(b):
        return {"row": min(len(a), len(b)), "native": None, "view": None}
    return None


# ---------------------------------------------------------------------------
# JSON / JSONL
# ---------------------------------------------------------------------------
def flatten(obj: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from flatten(value, f"{prefix}/{_ptr_escape(str(key))}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from flatten(value, f"{prefix}/{i}")
    else:
        yield prefix or "", obj


def _ptr_escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def build_json_view(path: Path, out: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    records: list[dict] = []
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        for i, line in enumerate((ln for ln in text.splitlines() if ln.strip()), 1):
            obj = json.loads(line, parse_float=Decimal)
            for ptr, value in flatten(obj):
                records.append({"record": i, "path": ptr,
                                "type": _type_name(value),
                                "value": _scalar_text(value)})
        kind = "jsonl"
    else:
        obj = json.loads(text, parse_float=Decimal)
        for ptr, value in flatten(obj):
            records.append({"record": 1, "path": ptr,
                            "type": _type_name(value),
                            "value": _scalar_text(value)})
        kind = "json"
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=["record", "path", "type", "value"])
        writer.writeheader()
        writer.writerows(records)
    return {"kind": kind, "rows": len(records)}


def _scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _loads_detect_dupes(text: str) -> tuple[Any, list[str]]:
    dupes: list[str] = []

    def hook(pairs):
        seen = set()
        for k, _v in pairs:
            if k in seen:
                dupes.append(k)
            seen.add(k)
        return dict(pairs)

    return json.loads(text, parse_float=Decimal, object_pairs_hook=hook), dupes


def verify_json(native: Path, view: Path) -> dict:
    text = native.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(open(view, encoding="utf-8")))
    checks: list[dict] = []
    dupes: list[str] = []
    if native.suffix.lower() in (".jsonl", ".ndjson"):
        expected: list[tuple[int, str, str, str]] = []
        for i, line in enumerate((ln for ln in text.splitlines() if ln.strip()), 1):
            obj, d = _loads_detect_dupes(line)
            dupes.extend(f"record {i}: {k}" for k in d)
            for ptr, value in flatten(obj):
                expected.append((i, ptr, _type_name(value), _scalar_text(value)))
        checks.append({"check": "duplicate_keys", "ok": not dupes,
                       "duplicates": dupes})
        actual = [(int(r["record"]), r["path"], r["type"], r["value"])
                  for r in rows]
        checks.append({"check": "flattened_values", "ok": actual == expected,
                       "first_difference": _first_diff(expected, actual)})
    else:
        obj, d = _loads_detect_dupes(text)
        dupes.extend(d)
        checks.append({"check": "duplicate_keys", "ok": not dupes,
                       "duplicates": dupes})
        expected = [(1, p, _type_name(v), _scalar_text(v))
                    for p, v in flatten(obj)]
        actual = [(int(r["record"]), r["path"], r["type"], r["value"])
                  for r in rows]
        checks.append({"check": "flattened_values", "ok": actual == expected,
                       "first_difference": _first_diff(expected, actual)})
        # raw number text must survive: compare against the literal token
        raw_numbers = re.findall(r":\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
                                 text)
        view_numbers = [r["value"] for r in rows if r["type"] in ("integer",
                                                                 "decimal")]
        checks.append({"check": "number_text_preserved",
                       "ok": all(any(v == n or _num_equal(v, n)
                                     for v in view_numbers)
                                 for n in raw_numbers),
                       "raw_tokens": len(raw_numbers)})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def _num_equal(a: str, b: str) -> bool:
    try:
        return Decimal(a) == Decimal(b)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# XLSX (independent XML reader)
# ---------------------------------------------------------------------------
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def build_xlsx_view(path: Path, out: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=False)
    rows: list[dict] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                rows.append({
                    "sheet": ws.title, "cell": cell.coordinate,
                    "row": cell.row, "col": cell.column,
                    "type": cell.data_type,
                    "value": str(cell.value),
                    "number_format": cell.number_format,
                })
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=["sheet", "cell", "row", "col",
                                                "type", "value",
                                                "number_format"])
        writer.writeheader()
        writer.writerows(rows)
    return {"kind": "xlsx", "rows": len(rows),
            "sheets": [ws.title for ws in wb.worksheets]}


def _xml_cells(path: Path) -> dict[str, dict[str, dict]]:
    """Read sheet cells from raw XML (independent of openpyxl)."""
    import xml.etree.ElementTree as ET
    out: dict[str, dict[str, dict]] = {}
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{_NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.get("Id"): rel.get("Target")
                   for rel in rels}
        sheets = []
        for sheet in wb_root.find(f"{_NS}sheets"):
            rel_id = sheet.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/"
                "relationships}id")
            target = rel_map.get(rel_id, "")
            if target.startswith("/"):
                target = target.lstrip("/")
            elif not target.startswith("xl/"):
                target = "xl/" + target
            sheets.append((sheet.get("name"), target))
        for name, target in sheets:
            if target not in zf.namelist():
                continue
            root = ET.fromstring(zf.read(target))
            cells: dict[str, dict] = {}
            for c in root.iter(f"{_NS}c"):
                ref = c.get("r")
                t = c.get("t")
                v = c.find(f"{_NS}v")
                f = c.find(f"{_NS}f")
                is_el = c.find(f"{_NS}is")
                if t == "s" and v is not None:
                    value = shared[int(v.text)]
                elif t == "inlineStr" and is_el is not None:
                    value = "".join(x.text or "" for x in is_el.iter(f"{_NS}t"))
                elif v is not None:
                    value = v.text or ""
                else:
                    value = ""
                cells[ref] = {"v": value, "t": t,
                              "f": (f.text or "") if f is not None else None}
            out[name] = cells
    return out


def _serial_to_iso(serial: str) -> str | None:
    """Excel 1900 date system serial -> ISO datetime (epoch 1899-12-30)."""
    try:
        value = float(serial)
    except (TypeError, ValueError):
        return None
    base = _dt.datetime(1899, 12, 30)
    return (base + _dt.timedelta(days=value)).isoformat()


def verify_xlsx(native: Path, view: Path) -> dict:
    rows = list(csv.DictReader(open(view, encoding="utf-8")))
    raw = _xml_cells(native)
    checks: list[dict] = []
    by_sheet: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_sheet.setdefault(r["sheet"], {})[r["cell"]] = r
    for sheet, cells in raw.items():
        view_cells = by_sheet.get(sheet, {})
        if sheet not in by_sheet:
            checks.append({"check": "sheet_present", "sheet": sheet, "ok": False})
            continue
        missing = sorted(set(cells) - set(view_cells))
        extra = sorted(set(view_cells) - set(cells))
        mismatched = []
        for ref in sorted(set(cells) & set(view_cells)):
            a, b = cells[ref], view_cells[ref]
            want = a["v"]
            # a formula cell: the view must carry the formula text, not the
            # cached number (the cache is never a checked fact)
            if a["f"]:
                if b["value"] != "=" + a["f"]:
                    mismatched.append({"cell": ref, "raw": "=" + a["f"],
                                       "view": b["value"]})
                continue
            if a["t"] in ("s", "str", "inlineStr"):
                same = a["v"] == b["value"]
            else:
                same = a["v"] == b["value"]
                if not same:
                    try:
                        same = Decimal(a["v"]) == Decimal(b["value"])
                    except Exception:
                        same = False
                    if not same and b["value"] and ("T" in b["value"] or
                                                   " " in b["value"]):
                        same = _serial_to_iso(a["v"]) == \
                            b["value"].replace(" ", "T")
            if not same:
                mismatched.append({"cell": ref, "raw": a["v"],
                                   "view": b["value"]})
        checks.append({"check": "cell_set", "sheet": sheet,
                       "ok": not missing and not extra,
                       "missing": missing[:20], "extra": extra[:20]})
        checks.append({"check": "cell_values", "sheet": sheet,
                       "ok": not mismatched,
                       "mismatched": mismatched[:20]})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def build_pdf_view(path: Path, out: Path) -> dict:
    """A page/block view built with PyMuPDF."""
    import fitz
    rows = []
    with fitz.open(path) as doc:
        for pno, page in enumerate(doc, 1):
            for i, block in enumerate(page.get_text("blocks")):
                rows.append({"page": pno, "block": i,
                             "bbox": ",".join(f"{v:.2f}" for v in block[:4]),
                             "text": str(block[4]).replace("\n", " ")})
        pages = len(doc)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=["page", "block", "bbox", "text"])
        writer.writeheader()
        writer.writerows(rows)
    return {"kind": "pdf", "rows": len(rows), "pages": pages}


def verify_pdf(native: Path, view: Path) -> dict:
    """Check the PyMuPDF view with an independent extractor (pypdf)."""
    rows = list(csv.DictReader(open(view, encoding="utf-8")))
    checks = []
    try:
        from pypdf import PdfReader
    except Exception as exc:                        # noqa: BLE001
        return {"ok": False, "checks": [{"check": "independent_reader",
                                         "ok": False,
                                         "detail": f"pypdf unavailable: {exc}"}]}
    reader = PdfReader(str(native))
    pages = len(reader.pages)
    view_pages = max((int(r["page"]) for r in rows), default=0)
    checks.append({"check": "page_count", "ok": pages == view_pages,
                   "native": pages, "view": view_pages})
    by_page: dict[int, list[str]] = {}
    for row in rows:
        by_page.setdefault(int(row["page"]), []).append(_norm_space(row["text"]))
    mismatched = []
    for pno in range(1, pages + 1):
        independent = _norm_space(reader.pages[pno - 1].extract_text() or "")
        built = " ".join(by_page.get(pno, []))
        if not independent and not built:
            continue
        if _pad(independent) != _pad(built):
            mismatched.append({"page": pno, "independent": independent[:120],
                               "view": built[:120]})
    checks.append({"check": "text_per_page", "ok": not mismatched,
                   "mismatched": mismatched[:5]})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _pad(text: str) -> str:
    return text


def build_view(project: C.Project, path: str | os.PathLike, *, adapter=None, verifier=None, code=()) -> dict:
    native = Path(path)
    if not native.is_file():
        native = project.root / path
    if not native.is_file():
        raise AuditError(f"native file not found: {path}")
    rel = _rel(project.root, native)
    sha = C.file_sha256(native)
    ext = native.suffix.lower()
    vid = C.canonical_hash({"native": rel, "sha256": sha})[:16]
    out = project.path("views", f"{vid}.csv")
    custom = None
    if adapter:
        if not verifier or adapter == verifier:
            raise AuditError("a custom view needs a distinct independent verifier")
        import models
        import execution as EX
        def bound_target(target):
            filename, function = target.rsplit(":", 1)
            filename = Path(filename)
            return str(filename if filename.is_absolute() else project.root / filename) + ":" + function
        adapter, verifier = bound_target(adapter), bound_target(verifier)
        files = [adapter.rsplit(":",1)[0], verifier.rsplit(":",1)[0], *code]
        spec = {"id": "audit-view:"+vid, "inputs": [{"dataset": str(native), "sha256": sha}], "code": files}
        with EX.protected(project, spec) as binding:
            meta = models._load_callable(adapter, "view_builder")(native, out)
        if not out.is_file() or not isinstance(meta, Mapping):
            raise AuditError("custom builder must write its full view and return structure/scope metadata")
        custom = {"builder": adapter, "verifier": verifier, "bindings": binding, "spec": spec, "scope": dict(meta)}
        meta = {"kind": "custom", **meta}
    elif ext == ".csv" or ext == ".tsv":
        meta = build_csv_view(native, out)
    elif ext in (".json", ".jsonl", ".ndjson"):
        meta = build_json_view(native, out)
    elif ext in (".xlsx", ".xlsm"):
        meta = build_xlsx_view(native, out)
    elif ext == ".pdf":
        meta = build_pdf_view(native, out)
    else:
        raise AuditError(f"no audit-view builder for {ext}")
    payload = {
        "native_path": rel, "native_sha256": sha,
        "view_path": out.relative_to(project.root).as_posix(),
        "view_sha256": C.file_sha256(out),
        "checks": [], "mismatches": [],
        "adapter": {"name": f"build_{meta['kind']}_view", "version": "2.0"},
        "notes": json.dumps(meta, ensure_ascii=False, sort_keys=True),
    }
    if custom:
        payload["adapter"] = custom
    if meta.get("rows") is not None:
        payload["row_count"] = int(meta["rows"])
    if meta.get("columns") is not None:
        payload["column_count"] = int(meta["columns"])
    previous = project.latest("audit_view", vid)
    rec = C.make_record("audit_view", vid, payload, producer=_producer(),
                        status="partial", revision=previous["revision"]+1 if previous else 1)
    project.append("audit_view", rec, enforce_transition=False)
    return {"id": vid, "view": payload["view_path"], "meta": meta,
            "native_sha256": sha}


def verify_view(project: C.Project, view_rel: str, *, record: bool = True) -> dict:
    view = project.root / view_rel
    if not view.is_file():
        raise AuditError(f"view not found: {view_rel}")
    native_rel = None
    rec = None
    for candidate in project.read("audit_view"):
        if (project.root / candidate["data"]["view_path"]).resolve() == view.resolve():
            rec = candidate
            native_rel = candidate["data"]["native_path"]
    if native_rel is None:
        raise AuditError(f"{view_rel} is not a registered audit view")
    native = project.root / native_rel
    if not native.is_file():
        raise AuditError(f"native file moved or deleted: {native_rel}")
    if C.file_sha256(native) != rec["data"]["native_sha256"]:
        return {"ok": False, "status": "mismatch",
                "checks": [{"check": "native_unchanged", "ok": False,
                            "note": "the native file changed after the view was "
                                    "built; rebuild the view"}]}
    ext = native.suffix.lower()
    adapter = rec["data"].get("adapter") or {}
    if adapter.get("verifier"):
        import models
        import execution as EX
        spec = adapter["spec"]
        if not EX.current(project, spec, adapter["bindings"]):
            raise AuditError("custom view adapter/code/environment changed; rebuild and reconcile")
        with EX.protected(project, spec):
            res = models._load_callable(adapter["verifier"], "independent_view_verifier")(native, view, adapter["scope"])
        if not isinstance(res, dict) or not res.get("checks") or any("ok" not in c for c in res["checks"]):
            raise AuditError("independent verifier must return actual structural/value checks")
        res["ok"] = all(c["ok"] is True for c in res["checks"])
    elif ext in (".json", ".jsonl", ".ndjson"):
        res = verify_json(native, view)
    elif ext in (".xlsx", ".xlsm"):
        res = verify_xlsx(native, view)
    elif ext == ".pdf":
        res = verify_pdf(native, view)
    else:
        res = verify_csv(native, view)
    res["native"] = native_rel
    res["view"] = view_rel
    res["native_sha256"] = C.file_sha256(native)
    res["view_sha256"] = C.file_sha256(view)
    if record and rec is not None:
        payload = dict(rec["data"])
        payload["checks"] = res["checks"]
        payload["mismatches"] = [c for c in res["checks"] if not c["ok"]]
        new = C.transition(rec, "verified" if res["ok"] else "mismatch",
                           producer=_producer(),
                           patch=payload,
                           reason="independent structural re-read")
        project.append("audit_view", new, enforce_transition=False)
        res["record"] = new["id"]
        res["status"] = new["status"]
    return res


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


# ---------------------------------------------------------------------------
# empty tables and generated values
# ---------------------------------------------------------------------------
def empty_table_evidence(dataset: str, *, window: str, denominator: str,
                         source_rel: str, source_sha256: str,
                         reread_by: str, reread_note: str,
                         columns: Iterable[str]) -> dict:
    """Range evidence for a legitimately empty table.

    ``0/0`` coverage is *not* 100%: an empty table gets a dataset-level verdict
    and an explicit ``cell_coverage: not_applicable``.
    """
    if not window or not denominator or not source_rel or not reread_by:
        raise AuditError("an empty table needs an observation window, a "
                         "denominator, the source and an actual re-read")
    return {
        "dataset": dataset, "rows": 0, "columns": list(columns),
        "cell_coverage": "not_applicable",
        "cell_coverage_reason": "no cells exist; 0/0 must not be reported as a "
                                "percentage",
        "dataset_level_checks": ["schema_declared", "window_declared",
                                 "denominator_declared", "source_reread"],
        "window": window, "denominator": denominator,
        "source": {"path": source_rel, "sha256": source_sha256},
        "reread": {"by": reread_by, "note": reread_note},
        "claim": f"no event satisfied the condition inside {window}",
    }


def record_empty_table(project: C.Project, dataset: str, **kwargs) -> dict:
    """Persist range evidence for a legitimately empty table."""
    evidence = empty_table_evidence(dataset, **kwargs)
    evidence.update({"native_path": evidence["source"]["path"],
                     "native_sha256": evidence["source"]["sha256"],
                     "view_path": "", "view_sha256": "",
                     "checks": [{"check": "range_evidence", "ok": True,
                                 "detail": evidence["window"]}],
                     "mismatches": []})
    rid = C.canonical_hash([dataset, evidence["window"],
                            evidence["source"]["sha256"]])[:20]
    rec = C.make_record("audit_view", rid, evidence, producer=_producer(),
                        status="verified")
    project.append("audit_view", rec, enforce_transition=False)
    return rec


def generated_value_record(kind: str, value: str, *, method: str,
                           uncertainty: str, inputs: Iterable[Mapping] = (),
                           sources: Iterable[Mapping] = ()) -> dict:
    record = {"value": value, "kind": kind, "method": method,
              "uncertainty": uncertainty, "inputs": list(inputs),
              "sources": list(sources)}
    status = value_kind_obligations(kind, record)
    if not status["ok"]:
        raise AuditError(f"{kind} value is missing {status['missing']}; a "
                         f"generated value must not masquerade as observed")
    record["observed_layer"] = status["observed_layer"]
    return record


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="audit view build/verify")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_b = sub.add_parser("build")
    p_b.add_argument("--path", required=True)
    p_b.add_argument("--adapter", help="trusted module.py:builder(native, view) -> structure metadata")
    p_b.add_argument("--verifier", help="distinct module.py:verify(native, view, metadata) -> actual checks")
    p_b.add_argument("--code", action="append", default=[])
    p_v = sub.add_parser("verify")
    p_v.add_argument("--view", required=True)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "build":
        res = build_view(proj, args.path, adapter=args.adapter, verifier=args.verifier, code=args.code)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "verify":
        res = verify_view(proj, args.view)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
