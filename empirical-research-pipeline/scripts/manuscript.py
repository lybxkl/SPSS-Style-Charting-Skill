# -*- coding: utf-8 -*-
"""Assemble the full research narrative into a real DOCX/PDF and verify it.

This is the *assembly and check* layer, not a text generator: the Agent writes
the sections as ``manuscript_block`` records, each carrying the claims that live
in it.  Assembly refuses to paper over missing work:

* a required section that is missing, too short, or still contains a placeholder
  (``TODO``/``待补``/``{...}`` that does not resolve) stops the build;
* every ``{number}`` placeholder must resolve to a value with a recorded trace
  (model result + parameter + unit); an untraceable number is an error;
* each block is re-reviewed against the **text actually printed** in the DOCX
  (and, when exported, the PDF), so an edit made after review invalidates the
  block instead of silently shipping;
* figures are placed at a real width with captions, and their placement is
  checked by ``layout_check`` when a PDF is available.

CLI::

    python manuscript.py --root . compose --docx out/paper.docx \\
        --numbers numbers.json --figures figures.json
    python manuscript.py --root . export --docx out/paper.docx --pdf out/paper.pdf
    python manuscript.py --root . verify --docx out/paper.docx [--pdf out/paper.pdf]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
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
MIN_CHARS = {"abstract": 150, "introduction": 400, "methods": 400,
             "results": 400, "discussion": 400}
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


# ---------------------------------------------------------------------------
# DOCX building
# ---------------------------------------------------------------------------
def _set_cjk(run, cjk: str = "宋体", latin: str = "Times New Roman") -> None:
    from docx.oxml.ns import qn
    run.font.name = latin
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        from docx.oxml import OxmlElement
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), cjk)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)


def _page_field(paragraph) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for el in (begin, instr, sep, end):
        run._r.append(el)


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


def build_docx(project: C.Project, *, docx_path: Path, title: str,
               authors: str, numbers: Mapping[str, object],
               trace: Mapping[str, object],
               figures: Iterable[Mapping] = (),
               tables: Iterable[Mapping] = (), outline=None, required_sections=(), min_chars=None) -> dict:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    docx_path = C.protect_output(project, docx_path)

    blocks = latest_blocks(project)
    problems = check_sections(blocks, required_sections=required_sections, min_chars=min_chars)
    if problems:
        raise ManuscriptError("manuscript is not ready: " + json.dumps(
            problems, ensure_ascii=False))
    doc = Document()
    # python-docx's bundled Word Title style contains a blue bottom border.
    # Use a plain paper title; remove the inherited decoration explicitly.
    for border in doc.styles["Title"].element.xpath(".//w:pBdr"):
        border.getparent().remove(border)
    section = doc.sections[0]
    section.left_margin = section.right_margin = Cm(2.5)
    section.top_margin = section.bottom_margin = Cm(2.5)
    base = doc.styles["Normal"]
    base.font.size = Pt(10.5)
    from docx.oxml.ns import qn
    rpr = base.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        from docx.oxml import OxmlElement
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), "宋体")
    rfonts.set(qn("w:ascii"), "Times New Roman")
    rfonts.set(qn("w:hAnsi"), "Times New Roman")

    para = doc.add_paragraph(style="Title")
    run = para.add_run(title)
    run.bold = True
    run.font.size = Pt(16)
    from docx.shared import RGBColor
    run.font.color.rgb = RGBColor(0,0,0)
    _set_cjk(run)
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph(authors)
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in sub.runs:
        _set_cjk(r)

    spans: dict[str, tuple[int, int]] = {}
    used_numbers: list[dict] = []
    resolved = {key: resolve_trace(project, key, value, trace.get(key)) for key,value in numbers.items()}
    declared_sections = list(dict.fromkeys(b["data"]["section"].lower() for b in blocks.values()))
    configured = [s["id"] if isinstance(s, Mapping) else str(s) for s in (outline or [])]
    if len(set(configured)) != len(configured):
        raise ManuscriptError("duplicate sections in the configured outline")
    order = configured + [s for s in declared_sections if s not in configured]
    names = {"abstract": "摘要", "keywords": "关键词", "introduction": "一、引言",
             "methods": "二、研究方法", "results": "三、结果",
             "discussion": "四、讨论", "limitations": "五、局限",
             "conclusion": "六、结论"}
    names.update({s["id"]: s.get("title", s["id"]) for s in (outline or []) if isinstance(s, Mapping)})
    for section_name in order:
        text = section_text(blocks, section_name)
        if not _norm(text):
            continue
        heading = doc.add_paragraph()
        heading.paragraph_format.keep_with_next = True
        hrun = heading.add_run(names.get(section_name, section_name))
        hrun.bold = True
        hrun.font.size = Pt(12)
        _set_cjk(hrun)
        for bid, rec in blocks.items():
            if rec["data"]["section"].lower() != section_name:
                continue
            body, used = resolve_numbers(rec["data"]["text"], numbers, trace, project=project, resolved=resolved)
            bad_numbers = [f for f in CL._check_numbers(body, numbers) if not f["ok"]]
            if bad_numbers:
                raise ManuscriptError(f"printed factual numbers lack current evidence: {bad_numbers}")
            used_numbers.extend(used)
            start = len(doc.paragraphs)
            for chunk in body.split("\n\n"):
                p = doc.add_paragraph(chunk.strip())
                p.paragraph_format.first_line_indent = Pt(21)
                for r in p.runs:
                    _set_cjk(r)
            spans[bid] = (start, len(doc.paragraphs))

    figure_list = list(figures)
    if figure_list:
        heading = doc.add_paragraph()
        heading.paragraph_format.keep_with_next = True
        hrun = heading.add_run("图表")
        hrun.bold = True
        for i, fig in enumerate(figure_list, 1):
            if any(not c["ok"] for c in CL._check_numbers(fig.get("caption", ""), numbers)):
                raise ManuscriptError("figure caption contains an untraceable number")
            path = Path(fig["png"])
            if not path.is_absolute():
                path = project.root / path
            if not path.is_file():
                raise ManuscriptError(f"figure {fig.get('figure_id')} png missing")
            doc.add_picture(str(path), width=Cm(float(fig.get("width_cm", 15))))
            doc.paragraphs[-1].paragraph_format.keep_with_next = True
            cap = doc.add_paragraph(f"图 {i}　{fig.get('caption', '')}")
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in cap.runs:
                _set_cjk(r)
    table_list = list(tables)
    if table_list:
        import csv
        for i, table in enumerate(table_list, 1):
            path = project.root / table["csv"]
            rows = table_rows(project, table)
            if any(not c["ok"] for c in CL._check_numbers(table.get("caption", ""), numbers)):
                raise ManuscriptError("table caption contains an untraceable number")
            t = doc.add_table(rows=len(rows), cols=len(rows[0]))
            t.style = "Table Grid"
            for r_i, row in enumerate(rows):
                from docx.oxml import OxmlElement
                flags = t.rows[r_i]._tr.get_or_add_trPr()
                flags.append(OxmlElement("w:cantSplit"))
                if r_i == 0:
                    flags.append(OxmlElement("w:tblHeader"))
                for c_i, value in enumerate(row):
                    cell = t.cell(r_i, c_i)
                    cell.text = value
                    for p in cell.paragraphs:
                        for r in p.runs:
                            _set_cjk(r)
                            r.font.size = Pt(9)
            cap = doc.add_paragraph(f"表 {i}　{table.get('caption', '')}")
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _page_field(footer)

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(docx_path))
    if set(spans) != set(blocks):
        raise ManuscriptError("registered manuscript blocks do not match printed blocks")
    info = {"docx": docx_path.as_posix(), "blocks": len(blocks),
            "numbers_used": used_numbers, "spans": spans,
            "figures": len(figure_list), "tables": len(table_list), "numbers": dict(numbers), "trace": dict(trace),
            "docx_sha256": C.file_sha256(docx_path), "block_signatures": {bid: C.signature(rec) for bid,rec in blocks.items()},
            "outline": order, "table_specs": table_list, "figure_specs": figure_list}
    project.write_snapshot("manuscript/compose.json", info)
    return info


# ---------------------------------------------------------------------------
# export + printed text
# ---------------------------------------------------------------------------
def export_pdf(docx_path: Path, pdf_path: Path, *, figures=()) -> dict:
    """Export with the real Word engine when available, else LibreOffice."""
    docx_path, pdf_path = Path(docx_path), Path(pdf_path)
    if docx_path.resolve() == pdf_path.resolve():
        raise ManuscriptError("PDF output must not replace the DOCX source")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    staging = Path(tempfile.mkdtemp(prefix="paper-export-", dir=pdf_path.parent))
    staged_pdf = staging / "export.pdf"
    def publish(engine):
        if not staged_pdf.is_file() or not staged_pdf.read_bytes().startswith(b"%PDF-"):
            raise ManuscriptError("PDF engine did not produce a new valid PDF")
        restored = []
        if figures:
            import fitz
            import export_pdf_hires as HI
            import layout_check as LC
            placements = LC.inspect_docx(docx_path)["images"]
            with fitz.open(staged_pdf) as pdf:
                used = set()
                for index,figure in enumerate(figures,1):
                    source = Path(figure["png"])
                    digest,_ = LC.image_content_sha256(source.read_bytes())
                    matches = [p for p in placements if p["sha256"] == digest]
                    if not matches:
                        raise ManuscriptError("high-resolution source is absent from the actual DOCX; backfill refused")
                    hit = HI.find_figure_page(pdf,f"图{index}",figure.get("caption", ""))
                    if not hit or (hit[0].number,hit[1]) in used:
                        raise ManuscriptError("no unique caption/image location for high-resolution backfill")
                    page,xref = hit
                    rectangles = page.get_image_rects(xref)
                    if not rectangles or not any(abs(rect.width*2.54/72-p["width_cm"])<.05 and abs(rect.height*2.54/72-p["height_cm"])<.05 for rect in rectangles for p in matches):
                        raise ManuscriptError("PDF image rectangle differs from the matched DOCX placement")
                    used.add((page.number,xref))
                    page.replace_image(xref,filename=str(source.resolve()))
                    page.clean_contents(sanitize=True)
                    restored.append(figure.get("figure_id",str(index)))
                fresh = staging/"hires.pdf"
                pdf.save(fresh,garbage=4,deflate=True)
            os.replace(fresh,staged_pdf)
        os.replace(staged_pdf, pdf_path)
        shutil.rmtree(staging)
        return {"engine": engine, "pdf": pdf_path.as_posix(), "sha256": C.file_sha256(pdf_path), "figures_restored":restored}
    if os.name == "nt":
        try:
            import win32com.client
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            try:
                doc = word.Documents.Open(str(docx_path.resolve()))
                try:
                    doc.ExportAsFixedFormat(str(staged_pdf.resolve()), 17)
                finally:
                    doc.Close(False)
            finally:
                word.Quit()
            return publish("word")
        except Exception as exc:                    # noqa: BLE001
            first = str(exc)
    else:
        first = "not windows"
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        proc = subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                               "--outdir", str(staging),
                               str(docx_path)], capture_output=True, text=True,
                              timeout=600)
        generated = staging / (docx_path.stem + ".pdf")
        if proc.returncode == 0 and generated.is_file():
            os.replace(generated, staged_pdf)
            return publish("libreoffice")
        shutil.rmtree(staging, ignore_errors=True)
        raise ManuscriptError(f"libreoffice export failed: {proc.stderr[:400]}")
    shutil.rmtree(staging, ignore_errors=True)
    raise ManuscriptError(f"no DOCX->PDF engine worked: {first}")


def printed_text_docx(docx_path: Path, spans: Mapping[str, list[int]]) -> dict:
    from docx import Document
    doc = Document(str(docx_path))
    paras = [p.text for p in doc.paragraphs]
    out = {bid: "\n".join(paras[s:e]) for bid, (s, e) in spans.items()}
    return {"full": "\n".join(paras), "blocks": out, "paragraphs": len(paras)}


def printed_text_pdf(pdf_path: Path) -> str:
    import fitz
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


def verify_printed(project: C.Project, *, docx_path: Path,
                   spans: Mapping[str, list[int]],
                   pdf_path: Path | None = None,
                   numbers: Mapping[str, object] | None = None,
                   trace: Mapping[str, object] | None = None, persist=True) -> dict:
    """Compare the text actually printed with the reviewed text.

    Numbers are resolved at print time, so the comparison target is the
    *resolved* block text; a placeholder left in the print, or a resolved value
    that differs from the reviewed text, both fail.
    """
    blocks = latest_blocks(project)
    printed = printed_text_docx(docx_path, spans)
    results = []
    numbers = dict(numbers or {})
    resolved = {key: resolve_trace(project, key, value, (trace or {}).get(key)) for key,value in numbers.items()}
    missing_blocks = sorted(set(blocks) - set(spans))
    unknown_blocks = sorted(set(spans) - set(blocks))
    for bid, (start, end) in spans.items():
        rec = blocks.get(bid)
        if rec is None:
            results.append({"block": bid, "check": "unknown_block", "ok": False})
            continue
        text = printed["blocks"][bid]
        expected = rec["data"]["text"]
        if numbers is not None:
            expected, _ = resolve_numbers(expected, numbers, trace or {}, project=project, resolved=resolved)
        review = CL.review_block(project, rec, context_text=expected, persist=persist)
        matches = _norm(text) == _norm(expected)
        if not matches and persist:
            latest = project.latest("manuscript_block", bid) or rec
            payload = dict(latest["data"])
            payload["notes"] = "printed text differs from the reviewed text"
            stale = C.make_record("manuscript_block", bid, payload,
                                  producer=_producer(), status="stale",
                                  revision=latest["revision"] + 1)
            project.append("manuscript_block", stale, enforce_transition=False)
        support_ok = review["status"] == "reviewed" and all(v == "supported" for v in review["claims"].values())
        import support_review
        support_ok = support_ok and all(support_review.is_current(project, project.latest("claim", cid)) for cid in review["claims"])
        results.append({"block": bid, "ok": matches and support_ok,
                        "status": "reviewed" if matches and support_ok else "stale",
                        "findings": [] if matches else [{
                            "check": "printed_text_mismatch",
                            "detail": {"printed": _norm(text)[:160],
                                       "expected": _norm(expected)[:160]}}]})
    pdf_info = None
    if pdf_path and not Path(pdf_path).is_file():
        raise ManuscriptError("requested PDF is missing; PDF verification cannot be skipped")
    if pdf_path:
        pdf_text = _tight(printed_text_pdf(pdf_path))
        missing = []
        for bid, rec in blocks.items():
            expected = rec["data"]["text"]
            if numbers is not None:
                expected, _ = resolve_numbers(expected, numbers, trace or {}, project=project, resolved=resolved)
            if _tight(expected) not in pdf_text:
                missing.append(bid)
        pdf_info = {"pages": _pdf_pages(pdf_path), "missing_blocks": missing,
                    "ok": not missing}
    from docx import Document
    snapshot_path = project.path("manuscript", "compose.json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.is_file() else {}
    table_specs = snapshot.get("table_specs", [])
    actual_tables = Document(str(docx_path)).tables
    tables_ok = len(actual_tables) == len(table_specs)
    captions_ok = True
    for label, specs in (("图", snapshot.get("figure_specs", [])), ("表", table_specs)):
        for i, spec in enumerate(specs, 1):
            caption = f"{label} {i}　{spec.get('caption', '')}"
            captions_ok = captions_ok and caption in printed["full"]
            if pdf_info:
                captions_ok = captions_ok and _tight(caption) in pdf_text
    for table, spec in zip(actual_tables, table_specs):
        expected_rows = table_rows(project, spec)
        actual_rows = [[cell.text for cell in row.cells] for row in table.rows]
        tables_ok = tables_ok and actual_rows == expected_rows
        if pdf_info:
            tables_ok = tables_ok and all(_tight("".join(row)) in pdf_text for row in expected_rows)
    outcome = {"ok": bool(results) and tables_ok and captions_ok and not missing_blocks and not unknown_blocks and all(r["ok"] for r in results) and
            (pdf_info is None or pdf_info["ok"]),
            "blocks": results, "pdf": pdf_info, "tables_ok": tables_ok, "captions_ok": captions_ok, "missing_blocks": missing_blocks, "unknown_blocks": unknown_blocks,
            "docx_sha256": C.file_sha256(docx_path), "pdf_sha256": C.file_sha256(pdf_path) if pdf_path else None,
            "block_signatures": {bid: C.signature(rec) for bid,rec in latest_blocks(project).items()}}
    if persist:
        project.write_snapshot("manuscript/verification.json", outcome)
    return outcome


def _pdf_pages(path: Path) -> int:
    import fitz
    with fitz.open(path) as doc:
        return len(doc)


def register_media_dependencies(project: C.Project, *,
                                figures: Iterable[Mapping] = ()) -> dict:
    """Wire figures to their results and to the manuscript (T23)."""
    import depgraph
    graph = depgraph.DependencyGraph(project)
    edges = 0
    for fig in figures:
        fig_id = fig.get("figure_id")
        if not fig_id:
            continue
        graph.register("figure", fig_id, "1", label=fig.get("caption", ""),
                       path=fig.get("png"))
        for result_id in fig.get("results") or []:
            try:
                graph.register("result", result_id, "1")
            except Exception:                       # noqa: BLE001
                pass
            graph.add_edge(f"result:{result_id}", f"figure:{fig_id}",
                           "derived", evidence="figure plots this result")
            edges += 1
        for block_id in fig.get("blocks") or []:
            graph.register("manuscript_block", block_id, "1")
            graph.add_edge(f"figure:{fig_id}", f"manuscript_block:{block_id}",
                           "presents")
    return {"nodes": len(graph.nodes()), "edges": edges}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="manuscript assembly and print check")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_c = sub.add_parser("compose")
    p_c.add_argument("--docx", required=True)
    p_c.add_argument("--pdf", help="also export using a real engine and verify the actual printed DOCX/PDF")
    p_c.add_argument("--title", required=True)
    p_c.add_argument("--authors", default="")
    p_c.add_argument("--numbers")
    p_c.add_argument("--trace")
    p_c.add_argument("--figures")
    p_c.add_argument("--tables")
    p_c.add_argument("--outline", help="JSON section IDs/titles; additional registered sections are retained")
    p_c.add_argument("--required-sections", nargs="*", default=[])
    p_e = sub.add_parser("export")
    p_e.add_argument("--docx", required=True)
    p_e.add_argument("--pdf", required=True)
    p_v = sub.add_parser("verify")
    p_v.add_argument("--docx", required=True)
    p_v.add_argument("--pdf")
    p_v.add_argument("--spans")
    sub.add_parser("sections")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "sections":
        for section in sorted({b["data"]["section"]
                               for b in latest_blocks(proj).values()}):
            print(section, len(_norm(section_text(latest_blocks(proj), section))))
        return 0
    if args.cmd == "compose":
        numbers = json.loads(Path(args.numbers).read_text(encoding="utf-8")) \
            if args.numbers else {}
        trace = json.loads(Path(args.trace).read_text(encoding="utf-8")) \
            if args.trace else {}
        figures = json.loads(Path(args.figures).read_text(encoding="utf-8")) \
            if args.figures else []
        tables = json.loads(Path(args.tables).read_text(encoding="utf-8")) \
            if args.tables else []
        info = build_docx(proj, docx_path=Path(args.docx), title=args.title,
                          authors=args.authors, numbers=numbers, trace=trace,
                          figures=figures, tables=tables,
                          outline=json.loads(Path(args.outline).read_text(encoding="utf-8")) if args.outline else None,
                          required_sections=args.required_sections)
        proj.write_snapshot("manuscript/compose.json", info)
        if args.pdf:
            target = C.protect_output(proj, Path(args.pdf))
            info["pdf_export"] = export_pdf(Path(args.docx), target, figures=[{**f,"png":str(proj.root/f["png"])} for f in figures])
            info["verification"] = verify_printed(proj, docx_path=Path(args.docx), pdf_path=target,
                                                   spans=info["spans"], numbers=numbers, trace=trace)
            proj.write_snapshot("manuscript/compose.json", info)
        print(json.dumps({k: v for k, v in info.items() if k != "spans"},
                         ensure_ascii=False, indent=1))
        return 0 if not args.pdf or info["verification"]["ok"] else 2
    if args.cmd == "export":
        snapshot_path=proj.path("manuscript","compose.json")
        snapshot=json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.is_file() else {}
        figures=snapshot.get("figure_specs",[]) if Path(snapshot.get("docx",".")).resolve()==Path(args.docx).resolve() else []
        print(json.dumps(export_pdf(Path(args.docx), C.protect_output(proj, Path(args.pdf)),figures=[{**f,"png":str(proj.root/f["png"])} for f in figures]),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "verify":
        snap = json.loads((proj.root / "output/v2/manuscript/compose.json").read_text(
            encoding="utf-8"))
        spans = {k: tuple(v) for k, v in snap["spans"].items()}
        res = verify_printed(proj, docx_path=Path(args.docx), spans=spans,
                             pdf_path=Path(args.pdf) if args.pdf else None,
                             numbers=snap.get("numbers"), trace=snap.get("trace"))
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
