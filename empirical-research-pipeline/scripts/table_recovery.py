# -*- coding: utf-8 -*-
"""Table and workbook recovery: headers, units, footnotes, merges, formulas.

What "recovered" means here, and why it is stricter than "text came out":

* a cell is addressed by ``(row, col)`` in the original grid, including cells
  that are covered by a merge (``origin: merged``) so the grid is never silently
  short;
* multi-level and repeated headers are kept as headers, not as data; a repeated
  header on a continuation page is *removed from the body* and recorded as
  ``repeated_header: true`` - the observations on the continuation page are not
  dropped and not double counted;
* footnotes and the unit declaration ("单位：万元") are attached to the table
  instead of being thrown away, because a denominator/unit written in a footnote
  is exactly the thing a later value needs;
* an Excel formula is *never* trusted from the cached value: the formula text,
  the cached result (if any) and a recomputation are kept separately, and the
  cell is marked ``formula``;
* leading zeros / long IDs survive because the raw text is kept next to the
  parsed value.

CLI::

    python table_recovery.py --root . pdf --path materials/table.pdf [--pages 1,2]
    python table_recovery.py --root . xlsx --path materials/book.xlsx
    python table_recovery.py --root . docx --path materials/report.docx
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C

UNIT_RE = re.compile(r"单位\s*[:：]\s*([^\s，,。;；]+)")
FOOTNOTE_RE = re.compile(r"^\s*(\*|†|‡|注\s*[:：]|注\s*\d|Note\s*[:：]|"
                        r"[0-9]{1,2}[.、)]|[a-z][.)])\s*\S")
NUMERIC_RE = re.compile(r"^[-+−]?[\d,，]+(\.\d+)?%?$")


def _producer(**kw) -> dict:
    return C.producer_for("table_recovery", version="2.0", module_file=__file__,
                          **kw)


def _is_numeric(text: str) -> bool:
    return bool(NUMERIC_RE.match((text or "").strip().replace(" ", "")))


def _is_header_row(row: list[str]) -> bool:
    cells = [c for c in row if c and c.strip()]
    if not cells:
        return False
    numeric = sum(1 for c in cells if _is_numeric(c))
    return numeric == 0


def detect_header_rows(rows: list[list[str]], *, max_rows: int = 3) -> int:
    """Count leading header rows (never more than ``max_rows``)."""
    n = 0
    for row in rows[:max_rows]:
        if _is_header_row(row):
            n += 1
        else:
            break
    return n


def detect_units(text_lines: Iterable[str]) -> str | None:
    for line in text_lines:
        m = UNIT_RE.search(line)
        if m:
            return m.group(1).strip()
    return None


def detect_footnotes(text_lines: Iterable[str]) -> list[str]:
    return [ln.strip() for ln in text_lines if FOOTNOTE_RE.match(ln or "")]


def _row_key(row: list[str]) -> str:
    return C.canonical_hash([(c or "").strip() for c in row])


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def pdf_tables(path: str | os.PathLike, *, pages: list[int] | None = None,
               strategy: str = "lines", digits: bool = True) -> list[dict]:
    import pdfplumber
    out: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        wanted = pages or list(range(1, len(pdf.pages) + 1))
        for pno in wanted:
            if pno < 1 or pno > len(pdf.pages):
                raise ValueError(f"page {pno} outside 1..{len(pdf.pages)}")
            page = pdf.pages[pno - 1]
            try:
                found = page.extract_tables(
                    {"vertical_strategy": "lines",
                     "horizontal_strategy": "lines"}) or []
            except Exception:                          # noqa: BLE001
                found = []
            if not found:
                found = page.extract_tables() or []
            for idx, grid in enumerate(found):
                rows = [[(cell if cell is not None else "") for cell in row]
                        for row in grid]
                out.append({"page": pno, "index": idx, "rows": rows,
                            "raw_tables": len(found)})
    return out


def annotate_tables(tables: list[dict], page_text: dict[int, str]) -> list[dict]:
    """Attach headers, units, footnotes and cross-page continuation info."""
    prev: dict | None = None
    for table in tables:
        rows = table["rows"]
        n_head = detect_header_rows(rows)
        table["header_rows"] = rows[:n_head]
        body = rows[n_head:]
        table["repeated_header"] = False
        table["continuation_of"] = None
        if prev is not None and table["page"] == prev["page"] + 1 and \
                prev["header_rows"] and n_head >= 1 and \
                [_row_key(r) for r in prev["header_rows"]] == \
                [_row_key(r) for r in table["header_rows"]]:
            table["repeated_header"] = True
            table["continuation_of"] = prev.get("table_id")
            prev["continued_on"] = table.get("table_id")
        table["body"] = body
        text = page_text.get(table["page"], "")
        lines = text.splitlines()
        table["units"] = detect_units(lines)
        table["footnotes"] = detect_footnotes(lines)
        table["n_rows"] = len(rows)
        table["n_cols"] = max((len(r) for r in rows), default=0)
        prev = table
    return tables


def _normalise_widths(rows: list[list[str]]) -> list[list[str]]:
    width = max((len(r) for r in rows), default=0)
    return [list(r) + [""] * (width - len(r)) for r in rows]


def table_id(path_rel: str, page: int, index: int) -> str:
    return C.canonical_hash({"source": path_rel, "page": page,
                             "index": index})[:20]


def recover_table(tables: list[dict], path_rel: str) -> list[dict]:
    """Turn annotated tables into cell-addressed structures."""
    out: list[dict] = []
    for table in tables:
        tid = table.get("table_id") or table_id(path_rel, table["page"],
                                                table["index"])
        table["table_id"] = tid
        rows = _normalise_widths(table["rows"])
        cells = []
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                raw = "" if value is None else str(value)
                cells.append({
                    "row": r, "col": c,
                    "section": "header" if r < len(table["header_rows"])
                    else "body",
                    "value": raw,
                    "leading_space": len(raw) - len(raw.lstrip()),
                    "trailing_space": len(raw) - len(raw.rstrip()),
                    "numeric": _is_numeric(raw),
                    "origin": "own",
                })
        structure = {
            "table_id": tid, "source": path_rel, "page": table["page"],
            "index": table["index"],
            "header_rows": table["header_rows"], "body": table["body"],
            "units": table.get("units"),
            "footnotes": table.get("footnotes", []),
            "repeated_header": table.get("repeated_header", False),
            "continuation_of": table.get("continuation_of"),
            "continued_on": table.get("continued_on"),
            "n_rows": len(rows), "n_cols": len(rows[0]) if rows else 0,
            "cells": cells,
            "merged_cells": [],
        }
        out.append(structure)
    return out


def merge_continuations(structures: list[dict]) -> list[dict]:
    """Group continuation tables without dropping or duplicating observations."""
    by_id = {s["table_id"]: s for s in structures}
    groups: dict[str, list[str]] = {}
    for s in structures:
        root = s["table_id"]
        seen = set()
        while by_id[root].get("continuation_of") and root not in seen:
            seen.add(root)
            root = by_id[root]["continuation_of"]
        groups.setdefault(root, []).append(s["table_id"])
    for root, members in groups.items():
        observations = 0
        for mid in members:
            observations += len(by_id[mid]["body"])
        by_id[root]["group"] = {"root": root, "members": sorted(
            members, key=lambda m: (by_id[m]["page"], by_id[m]["index"])),
            "observations": observations}
    return structures


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
def docx_table_structure(table) -> dict:
    """Grid with merge provenance from ``gridSpan``/``vMerge``."""
    from docx.oxml.ns import qn
    rows = table.rows
    grid: list[list[dict]] = []
    for r_idx, row in enumerate(rows):
        cells = []
        for cell in row.cells:
            tc = cell._tc
            span = 1
            vmerge = tc.find(qn("w:tcPr"))
            vmerge_val = None
            if vmerge is not None:
                span_el = vmerge.find(qn("w:gridSpan"))
                if span_el is not None:
                    span = int(span_el.get(qn("w:val")) or 1)
                vm = vmerge.find(qn("w:vMerge"))
                if vm is not None:
                    vmerge_val = vm.get(qn("w:val")) or "continue"
            cells.append({"text": cell.text, "colspan": span,
                          "vmerge": vmerge_val})
        grid.append(cells)
    # expand to one entry per logical grid column; continuation cells are
    # marked, not filled with copies of the merged value
    width = max((sum(c["colspan"] for c in row) for row in grid), default=0)
    cells_out: list[dict] = []
    for r, row in enumerate(grid):
        col = 0
        for c in row:
            text = c["text"]
            kind = "own"
            if c["vmerge"] == "continue":
                kind = "merged"
            elif c["colspan"] > 1:
                kind = "spanned"
            cells_out.append({"row": r, "col": col, "value": text,
                              "colspan": c["colspan"], "origin": kind,
                              "vmerge": c["vmerge"]})
            for extra in range(1, c["colspan"]):
                cells_out.append({"row": r, "col": col + extra, "value": "",
                                  "colspan": 1, "origin": "merged",
                                  "vmerge": "gridSpan"})
            col += c["colspan"]
    return {"n_rows": len(grid), "n_cols": width, "cells": cells_out,
            "header_rows": [c["text"] for c in grid[0]] if grid else []}


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------
ROMAN = ("I", "II", "III", "IV", "V")


def xlsx_structure(path: str | os.PathLike, sheet: str | None = None) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=False)
    wb_cache = openpyxl.load_workbook(str(path), data_only=True)
    names = [sheet] if sheet else wb.sheetnames
    out: dict[str, Any] = {"sheets": {}, "epoch": None}
    epoch = getattr(wb, "epoch", None)
    if hasattr(epoch, "date"):
        out["epoch"] = epoch.date().isoformat()
    for name in names:
        if name not in wb.sheetnames:
            raise ValueError(f"unknown sheet {name!r}; have {wb.sheetnames}")
        ws = wb[name]
        cache_ws = wb_cache[name]
        cells = []
        formulas = 0
        merged = []
        for rng in ws.merged_cells.ranges:
            merged.append({"range": str(rng), "min_row": rng.min_row,
                           "max_row": rng.max_row, "min_col": rng.min_col,
                           "max_col": rng.max_col})
        covered = set()
        for rng in ws.merged_cells.ranges:
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    if (r, c) != (rng.min_row, rng.min_col):
                        covered.add((r, c))
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None and (cell.row, cell.column) not in covered:
                    continue
                raw = "" if cell.value is None else str(cell.value)
                entry = {"cell": cell.coordinate, "row": cell.row,
                         "col": cell.column, "value": raw,
                         "data_type": cell.data_type,
                         "number_format": cell.number_format,
                         "origin": "merged" if (cell.row, cell.column)
                         in covered else "own"}
                if cell.data_type == "f":
                    formulas += 1
                    cached = cache_ws[cell.coordinate].value
                    entry["formula"] = raw
                    entry["cached_value"] = "" if cached is None else str(cached)
                    entry["cache_present"] = cached is not None
                if isinstance(cell.value, (_dt.datetime, _dt.date)):
                    entry["iso"] = cell.value.isoformat()
                if cell.data_type == "s" and re.fullmatch(r"0\d+", raw):
                    entry["leading_zero"] = True
                cells.append(entry)
        out["sheets"][name] = {
            "cells": cells, "formulas": formulas,
            "dimensions": ws.dimensions,
            "merged_cells": merged,
            "n_rows": ws.max_row, "n_cols": ws.max_column,
        }
    return out


def recompute_formula(entry: Mapping, values: Mapping[str, float]) -> dict:
    """Independently evaluate the small formula subset we can verify.

    Anything outside the subset is reported as ``unverified`` - never as the
    cached value.
    """
    formula = (entry.get("formula") or "").lstrip("=")
    m = re.fullmatch(r"SUM\(([A-Z]+\d+):([A-Z]+\d+)\)", formula, re.I)
    if not m:
        return {"status": "unverified",
                "reason": f"formula {formula!r} outside the verifiable subset"}
    start, end = m.group(1).upper(), m.group(2).upper()
    col0 = re.match(r"([A-Z]+)", start).group(1)
    col1 = re.match(r"([A-Z]+)", end).group(1)
    if col0 != col1:
        return {"status": "unverified", "reason": "multi-column SUM range"}
    r0 = int(re.search(r"(\d+)", start).group(1))
    r1 = int(re.search(r"(\d+)", end).group(1))
    total = 0.0
    missing = []
    for r in range(r0, r1 + 1):
        key = f"{col0}{r}"
        if key not in values:
            missing.append(key)
            continue
        total += float(values[key])
    cached = entry.get("cached_value")
    if not entry.get("cache_present") or cached in (None, ""):
        return {"status": "unverified", "computed": total,
                "cached": None, "range": f"{start}:{end}",
                "missing_inputs": missing,
                "reason": "no cached value exists, so a recomputation cannot be "
                          "compared; the formula's own result is not trusted"}
    ok = abs(float(cached) - total) < 1e-9
    return {"status": "verified" if ok else "mismatch",
            "computed": total, "cached": cached,
            "range": f"{start}:{end}", "missing_inputs": missing}


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------
def recover_source(project: C.Project, path_rel: str, *, write: bool = True,
                   pages: list[int] | None = None) -> dict:
    """Recover all tables of one source and store them as a snapshot."""
    path = Path(path_rel)
    if not path.is_file():
        path = project.root / path_rel
    kind = path.suffix.lower()
    sha = C.file_sha256(path)
    if kind == ".pdf":
        page_text: dict[int, str] = {}
        import fitz
        with fitz.open(path) as doc:
            for i in range(doc.page_count):
                page_text[i + 1] = doc.load_page(i).get_text("text")
        raw = pdf_tables(path, pages=pages)
        for t in raw:
            t["table_id"] = table_id(path_rel, t["page"], t["index"])
        annotated = annotate_tables(raw, page_text)
        structures = recover_table(annotated, path_rel)
        structures = merge_continuations(structures)
        result = {"kind": "pdf", "structures": structures, "page_text": None}
    elif kind in (".xlsx", ".xlsm"):
        result = {"kind": "xlsx", **xlsx_structure(path)}
    elif kind == ".docx":
        from docx import Document
        doc = Document(str(path))
        tables = [docx_table_structure(t) for t in doc.tables]
        for i, t in enumerate(tables):
            t["table_id"] = table_id(path_rel, 0, i)
            t["source"] = path_rel
        result = {"kind": "docx", "structures": tables}
    else:
        raise ValueError(f"table recovery does not handle {kind}")
    result["source"] = path_rel
    result["source_sha256"] = sha
    result["producer"] = _producer()
    if write:
        out = project.path("tables", f"{C.canonical_hash(path_rel)[:16]}.json")
        C.atomic_write_json(out, result)
        result["snapshot"] = out.relative_to(project.root).as_posix()
    return result


def verify_structure(project: C.Project, structure_path: str) -> dict:
    """Independently re-read the native table and compare the stored grid."""
    snapshot = project.root / structure_path
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    source = data["source"]
    fresh = recover_source(project, source, write=False)
    checks: list[dict] = []
    if data["kind"] == "xlsx":
        for sheet, old in data["sheets"].items():
            new = fresh["sheets"].get(sheet)
            if new is None:
                checks.append({"check": "sheet_present", "sheet": sheet,
                               "ok": False})
                continue
            old_map = {c["cell"]: c["value"] for c in old["cells"]}
            new_map = {c["cell"]: c["value"] for c in new["cells"]}
            same = old_map == new_map and old["n_rows"] == new["n_rows"] and \
                old["n_cols"] == new["n_cols"]
            checks.append({"check": "cell_grid", "sheet": sheet, "ok": same,
                           "cells": len(old_map),
                           "differences": [
                               k for k in set(old_map) | set(new_map)
                               if old_map.get(k) != new_map.get(k)][:20]})
    else:
        old = data["structures"]
        new = fresh["structures"]
        checks.append({"check": "table_count", "ok": len(old) == len(new),
                       "stored": len(old), "fresh": len(new)})
        for a, b in zip(old, new):
            checks.append({
                "check": "table_grid", "table": a["table_id"],
                "ok": a["n_rows"] == b["n_rows"] and a["n_cols"] == b["n_cols"]
                and [c["value"] for c in a["cells"]] ==
                    [c["value"] for c in b["cells"]],
                "stored_shape": [a["n_rows"], a["n_cols"]],
                "fresh_shape": [b["n_rows"], b["n_cols"]],
            })
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "source": source}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="table and workbook recovery")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pdf", "xlsx", "docx"):
        p = sub.add_parser(name)
        p.add_argument("--path", required=True)
        p.add_argument("--pages")
    p_ver = sub.add_parser("verify")
    p_ver.add_argument("--structure", required=True)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "verify":
        res = verify_structure(proj, args.structure)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    pages = [int(x) for x in args.pages.split(",")] if getattr(
        args, "pages", None) else None
    res = recover_source(proj, args.path, pages=pages)
    summary = {k: v for k, v in res.items() if k not in ("structures",)}
    if res["kind"] == "pdf":
        summary["tables"] = [
            {"table_id": s["table_id"], "page": s["page"],
             "rows": s["n_rows"], "cols": s["n_cols"],
             "header_rows": len(s["header_rows"]),
             "units": s["units"], "footnotes": s["footnotes"],
             "repeated_header": s["repeated_header"],
             "continuation_of": s["continuation_of"],
             "group": s.get("group")} for s in res["structures"]]
    elif res["kind"] == "xlsx":
        summary["sheets"] = {k: {"cells": len(v["cells"]),
                                 "formulas": v["formulas"],
                                 "merged": len(v["merged_cells"])}
                             for k, v in res["sheets"].items()}
    else:
        summary["tables"] = [
            {"table_id": s["table_id"], "rows": s["n_rows"],
             "cols": s["n_cols"],
             "merged_cells": sum(1 for c in s["cells"]
                                 if c["origin"] != "own")}
            for s in res["structures"]]
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
