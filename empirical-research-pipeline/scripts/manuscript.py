# -*- coding: utf-8 -*-
"""Print-time evidence binding for the numbers a manuscript actually prints.

This module is the *check* layer of the single manuscript chain.  The DOCX is
built by ``assemble_manuscript.py`` from the project spec; this module owns
what that builder cannot check:

* every ``{number}`` placeholder in a reviewed ``manuscript_block`` must
  resolve to a value with a recorded trace (validated model result, reviewed
  dataset cell or aggregate, checked reference); an untraceable number is an
  error;
* the text actually printed in the DOCX (and, when exported, the PDF) must
  still contain the reviewed text of every block, so an edit made after
  review invalidates the block instead of silently shipping;
* printed tables must match their data sources row for row - no cell may be
  dropped or invented.

There is deliberately no DOCX builder and no PDF exporter here:
``assemble_manuscript.py`` is the only builder, ``export_pdf_hires.py`` the
only exporter.  Two builders would mean two versions of the manuscript.

CLI::

    python manuscript.py --root . sections [--required s1 s2 ...]
    python manuscript.py --root . verify --docx out/paper.docx [--pdf out/paper.pdf] \\
        [--numbers numbers.json] [--trace trace.json] [--figures figures.json] \\
        [--tables tables.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import claims as CL
import contract_v2 as C

REQUIRED_SECTIONS = ("abstract", "introduction", "methods", "results",
                     "discussion")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w.\-]*)\}")
BAD_MARKERS = ("todo", "tbd", "待补", "占位", "xxxx", "[insert")


class ManuscriptError(Exception):
    pass


def _producer(**kw) -> dict:
    return C.producer_for("manuscript", version="2.0", module_file=__file__,
                          **kw)


def _norm(text: str) -> str:
    return CL.normalize_text(text)


def _tight(text: str) -> str:
    """Whitespace-insensitive form: PDF extraction inserts line breaks in CJK."""
    return re.sub(r"\s+", "", _norm(text))


def latest_blocks(project: C.Project) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for rec in project.read("manuscript_block"):
        bid = rec["data"]["block_id"]
        if bid not in out or rec["revision"] > out[bid]["revision"]:
            out[bid] = rec
    return out


def section_text(blocks: Mapping[str, Mapping], section: str) -> str:
    parts = [b["data"]["text"] for b in blocks.values()
             if b["data"]["section"].lower() == section]
    return "\n\n".join(parts)


def check_sections(blocks: Mapping[str, Mapping], *, required_sections=(), min_chars=None) -> list[dict]:
    problems = []
    if not blocks:
        problems.append({"check": "manuscript_empty"})
    sections = list(dict.fromkeys([*required_sections, *(b["data"]["section"].lower() for b in blocks.values())]))
    for section in sections:
        text = section_text(blocks, section)
        if not _norm(text):
            problems.append({"check": "section_missing", "section": section})
            continue
        minimum = (min_chars or {}).get(section, 0)
        if len(_norm(text)) < minimum:
            problems.append({"check": "section_too_short", "section": section,
                             "chars": len(_norm(text)),
                             "min": minimum})
        low = text.lower()
        for marker in BAD_MARKERS:
            if marker in low:
                problems.append({"check": "placeholder_text", "section": section,
                                 "marker": marker})
    for bid, rec in blocks.items():
        if rec["status"] == "stale":
            problems.append({"check": "block_stale", "block": bid})
    return problems


def resolve_trace(project, key, value, entry):
    if not entry:
        raise ManuscriptError(f"number {{{key}}} has no trace")
    if project is None or not isinstance(entry, Mapping):
        raise ManuscriptError(f"number {{{key}}} needs a current project evidence target")
    import math
    import validation as V
    import evidence
    if entry.get("model") or entry.get("result"):
        result_id = entry.get("result") or entry["model"]
        result = project.latest("model_result", result_id)
        if result is None or not V.is_current(project, result["data"]["model"], result):
            raise ManuscriptError(f"number {{{key}}} refers to a missing/stale/unvalidated model result")
        spec = __import__("models").load_spec(project, result["data"]["model"])["data"]
        evidence.model_inputs(project, spec, verification=entry.get("verification"))
        payload = result["data"]["payload"]
        parameter = entry.get("parameter") or result["data"]["target_parameter"]
        field = entry.get("field")
        if field:
            actual=C.field_value(payload,field)
        elif parameter in (payload.get("coefficients") or {}):
            actual = payload["coefficients"][parameter]["estimate"]
        elif parameter == result["data"]["target_parameter"]:
            actual = payload.get("estimate")
        else:
            raise ManuscriptError(f"number {{{key}}} parameter is absent from result")
        checked_field=field
        if not checked_field:
            checked_field=C.field_pointer("coefficients",parameter,"estimate") if parameter in (payload.get("coefficients") or {}) else "estimate"
        if not V.is_current(project,result["data"]["model"],result,field=checked_field):
            raise ManuscriptError(f"number {{{key}}} field {checked_field} has not been independently validated")
        if entry.get("unit") and entry["unit"] != result["data"]["unit"]:
            raise ManuscriptError(f"number {{{key}}} has a different unit from its result")
        binding = {"kind": "model_result", "id": result["id"], "revision": result["revision"], "signature": C.signature(result),
                   "parameter": parameter, "field": field, "unit": result["data"]["unit"], "scale": result["data"].get("scale")}
    elif entry.get("dataset"):
        verifier, report = evidence.final_review(project, entry.get("verification"))
        ident = entry["dataset"]
        if entry.get("aggregate"):
            import csv
            from decimal import Decimal
            info = verifier.datasets[ident]
            with open(verifier.path(info["spec"]["path"]), encoding="utf-8-sig", newline="") as stream:
                rows = [row for row in csv.DictReader(stream) if all(row.get(c) == str(v) for c,v in entry.get("where", {}).items())]
            operation = entry["aggregate"]
            if operation == "row_count":
                actual = len(rows)
            else:
                values = [Decimal(row[entry["column"]]) for row in rows if row[entry["column"]] != ""]
                if len(values) != len(rows) and entry.get("missing") != "exclude":
                    raise ManuscriptError("aggregation must declare its treatment of missing values")
                if not values:
                    raise ManuscriptError("an empty aggregation is not an observed zero")
                actual = sum(values) if operation == "sum" else sum(values)/len(values) if operation == "mean" else min(values) if operation == "min" else max(values) if operation == "max" else None
                if actual is None:
                    raise ManuscriptError("declare a supported aggregate or an independently checked custom result")
            binding = {"kind": "dataset_aggregate", "dataset": ident, "operation": operation,
                       "where": entry.get("where", {}), "fingerprint": report["fingerprint"]}
        else:
            target = (ident, __import__("verify_dataset").key_tuple(entry["key"]), entry["column"])
            if target not in verifier.cells:
                raise ManuscriptError(f"number {{{key}}} has no such reviewed dataset cell")
            actual = verifier.cells[target][0]
            binding = {"kind": "dataset_cell", "target": [ident, list(target[1]), target[2]], "fingerprint": report["fingerprint"]}
    elif entry.get("reference"):
        import refs
        rec = project.latest("reference", entry["reference"])
        if rec is None or not refs.check_reference(project, rec["id"])["ok"] or not rec["data"]["access"].get("evidence"):
            raise ManuscriptError("literature facts require checked metadata/access evidence")
        actual = rec["data"][entry["field"]]
        binding = {"kind": "reference", "id": rec["id"], "signature": C.signature(rec)}
    else:
        raise ManuscriptError(f"number {{{key}}} has no supported actual evidence target")
    try:
        actual_number = float(actual)
        if entry.get("display") == "percent":
            actual_number *= 100
        rendered = format(actual_number, entry["format"]) if entry.get("format") else actual
        if not math.isfinite(actual_number) or not math.isclose(float(str(value).rstrip("%")), float(rendered), rel_tol=1e-12, abs_tol=1e-12):
            raise ManuscriptError(f"number {{{key}}} differs from current evidence: printed={value}, actual={rendered}")
    except (TypeError, ValueError) as exc:
        raise ManuscriptError(f"number {{{key}}} does not resolve to a finite scalar") from exc
    return {"key": key, "value": value, "actual": str(actual), "trace": dict(entry), "binding": binding}


def resolve_numbers(text: str, numbers: Mapping[str, object],
                    trace: Mapping[str, object], *, project=None, resolved=None) -> tuple[str, list[dict]]:
    used = []

    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in numbers:
            raise ManuscriptError(f"number placeholder {{{key}}} has no value")
        entry = trace.get(key)
        if not entry:
            raise ManuscriptError(
                f"number {{{key}}} has no trace (model/result/parameter/unit); "
                f"a printed number must be traceable")
        used.append(resolved[key] if resolved is not None else resolve_trace(project, key, numbers[key], entry))
        return str(numbers[key])

    return PLACEHOLDER.sub(repl, text), used


def table_rows(project, table):
    """Load a whole rectangular table and verify its data source, never truncate rows."""
    import csv
    import evidence
    path = project.root / table["csv"]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ManuscriptError("table must be nonempty and rectangular; no cells may be dropped")
    registry = json.loads((project.root/"research_registry.json").read_text(encoding="utf-8")) if (project.root/"research_registry.json").is_file() else {}
    dataset = next((d for d in registry.get("datasets", []) if (project.root/d["path"]).resolve() == path.resolve()), None)
    if dataset:
        verifier, _ = evidence.final_review(project, table.get("verification"))
        if dataset["id"] not in verifier.datasets:
            raise ManuscriptError("table dataset is outside the current final review")
    else:
        cell_trace = table.get("trace") or {}
        for ri,row in enumerate(rows[1:], 1):
            for ci,value in enumerate(row):
                key = f"{ri}:{ci}"
                if CL._check_numbers(value, {}):
                    resolve_trace(project, key, value, cell_trace.get(key))
    return rows


def printed_text_docx(docx_path: Path) -> dict:
    """Full paragraph text of the printed DOCX (the builder is assemble_manuscript)."""
    from docx import Document
    doc = Document(str(docx_path))
    paras = [p.text for p in doc.paragraphs]
    return {"full": "\n".join(paras), "paragraphs": len(paras)}


def printed_text_pdf(pdf_path: Path) -> str:
    import fitz
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


def verify_printed(project: C.Project, *, docx_path: Path,
                   pdf_path: Path | None = None,
                   numbers: Mapping[str, object] | None = None,
                   trace: Mapping[str, object] | None = None,
                   figures: Iterable[Mapping] = (),
                   tables: Iterable[Mapping] = (),
                   persist=True) -> dict:
    """Compare the text actually printed with the reviewed text.

    The DOCX is built by ``assemble_manuscript.py``; this check does not know
    paragraph spans, so containment replaces span equality: the reviewed text
    of every block must appear in the printed text, whitespace-insensitively.
    ``{placeholder}`` syntax is *always* resolved against ``numbers``/``trace``
    (an empty map makes any placeholder an error - a printed number must be
    traceable, and literal braces are not a supported escape).  A printed value
    that differs from the current evidence fails.  An edit after review
    invalidates the block.  Known limits, disclosed honestly: whitespace-
    insensitive containment cannot distinguish "1 2" from "12" (numeric
    precision is separately guarded by ``resolve_trace`` at 1e-12), and text
    printed *in addition* to the reviewed blocks is not detected here - the
    layout/figure checks and human review cover the printed surface.
    """
    blocks = latest_blocks(project)
    printed = printed_text_docx(docx_path)
    printed_full = _tight(printed["full"])
    numbers = dict(numbers or {})
    resolved = {key: resolve_trace(project, key, value, (trace or {}).get(key))
                for key, value in numbers.items()}

    def expected_text(rec):
        expected, _ = resolve_numbers(rec["data"]["text"], numbers, trace or {},
                                      project=project, resolved=resolved)
        return expected

    results = []
    for bid, rec in blocks.items():
        expected = expected_text(rec)
        review = CL.review_block(project, rec, context_text=expected, persist=persist)
        matches = _tight(expected) in printed_full
        if not matches and persist:
            latest = project.latest("manuscript_block", bid) or rec
            payload = dict(latest["data"])
            payload["notes"] = "printed text differs from the reviewed text"
            stale = C.make_record("manuscript_block", bid, payload,
                                  producer=_producer(), status="stale",
                                  revision=latest["revision"] + 1)
            project.append("manuscript_block", stale, enforce_transition=False)
        support_ok = review["status"] == "reviewed" and all(
            v == "supported" for v in review["claims"].values())
        import support_review
        support_ok = support_ok and all(
            support_review.is_current(project, project.latest("claim", cid))
            for cid in review["claims"])
        results.append({"block": bid, "ok": matches and support_ok,
                        "status": "reviewed" if matches and support_ok else "stale",
                        "findings": [] if matches else [{
                            "check": "printed_text_mismatch",
                            "detail": {"expected": _tight(expected)[:160]}}]})
    pdf_info = None
    pdf_text = None
    if pdf_path and not Path(pdf_path).is_file():
        raise ManuscriptError("requested PDF is missing; PDF verification cannot be skipped")
    if pdf_path:
        pdf_text = _tight(printed_text_pdf(pdf_path))
        missing = [bid for bid, rec in blocks.items()
                   if _tight(expected_text(rec)) not in pdf_text]
        pdf_info = {"pages": _pdf_pages(pdf_path), "missing_blocks": missing,
                    "ok": not missing}
    figure_specs = list(figures)
    table_specs = list(tables)
    from docx import Document
    actual_tables = Document(str(docx_path)).tables
    tables_ok = len(actual_tables) == len(table_specs)
    captions_ok = True
    for spec in [*figure_specs, *table_specs]:
        caption = str(spec.get("caption", ""))
        if not caption:
            continue
        captions_ok = captions_ok and caption in printed["full"]
        if pdf_text is not None:
            captions_ok = captions_ok and _tight(caption) in pdf_text
    for table, spec in zip(actual_tables, table_specs):
        expected_rows = table_rows(project, spec)
        actual_rows = [[cell.text for cell in row.cells] for row in table.rows]
        tables_ok = tables_ok and actual_rows == expected_rows
        if pdf_text is not None:
            tables_ok = tables_ok and all(
                _tight("".join(row)) in pdf_text for row in expected_rows)
    outcome = {"ok": bool(results) and tables_ok and captions_ok
               and all(r["ok"] for r in results)
               and (pdf_info is None or pdf_info["ok"]),
               "blocks": results, "pdf": pdf_info, "tables_ok": tables_ok,
               "captions_ok": captions_ok,
               "docx_sha256": C.file_sha256(docx_path),
               "pdf_sha256": C.file_sha256(pdf_path) if pdf_path else None,
               "block_signatures": {bid: C.signature(rec) for bid, rec
                                    in latest_blocks(project).items()},
               "numbers_used": list(resolved.values())}
    if persist:
        project.write_snapshot("manuscript/verification.json", outcome)
    return outcome


def _pdf_pages(path: Path) -> int:
    import fitz
    with fitz.open(path) as doc:
        return len(doc)


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="print-time evidence binding for the manuscript chain")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_s = sub.add_parser("sections")
    p_s.add_argument("--required", nargs="*", default=[],
                     help="sections that must exist; e.g. the REQUIRED_SECTIONS defaults")
    p_v = sub.add_parser("verify")
    p_v.add_argument("--docx", required=True)
    p_v.add_argument("--pdf")
    p_v.add_argument("--numbers", help="JSON file: printed values keyed by placeholder")
    p_v.add_argument("--trace", help="JSON file: evidence trace per placeholder")
    p_v.add_argument("--figures", help="JSON file: figure specs with captions")
    p_v.add_argument("--tables", help="JSON file: table specs with csv sources")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "sections":
        blocks = latest_blocks(proj)
        for section in sorted({b["data"]["section"] for b in blocks.values()}):
            print(section, len(_norm(section_text(blocks, section))))
        problems = check_sections(blocks, required_sections=args.required or ())
        if problems:
            print(json.dumps(problems, ensure_ascii=False))
            return 2
        return 0
    if args.cmd == "verify":
        def load(name, want):
            if not name:
                return None
            path = Path(name)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ManuscriptError(f"cannot read {name}: {exc}")
            except json.JSONDecodeError as exc:
                raise ManuscriptError(f"{name} is not valid JSON: {exc}")
            if not isinstance(data, want):
                raise ManuscriptError(f"{name} must be a JSON {want.__name__}")
            return data
        docx = Path(args.docx)
        if not docx.is_file():
            print(f"FAIL: {args.docx} is missing; pass the DOCX assembled by "
                  f"assemble_manuscript.py", file=sys.stderr)
            return 2
        try:
            res = verify_printed(proj, docx_path=docx,
                                 pdf_path=Path(args.pdf) if args.pdf else None,
                                 numbers=load(args.numbers, dict) or {},
                                 trace=load(args.trace, dict) or {},
                                 figures=load(args.figures, list) or [],
                                 tables=load(args.tables, list) or [])
        except ManuscriptError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
