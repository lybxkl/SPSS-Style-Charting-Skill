# -*- coding: utf-8 -*-
"""Two-path discovery: material-first and question-first, with open candidates.

The point of this module is that nothing is silently dropped.  Every structure
(a page, a table, a sheet, a paragraph block) gets a ``structure_coverage`` row
saying what happened to it; every candidate (field, dataset, entity, measure,
time point, relation) gets a ``discovery_candidate`` row with an origin, the
source units that support it, and a disposition.  Candidates are *not* limited to
a built-in catalog: the heuristics below propose, the Agent decides, and the
ledger records the decision.

Two paths, deliberately redundant:

* **material-first** - walk the units and mine what is actually there: table
  headers, ``key: value`` patterns, units of measure, dates, explicit counts.
* **question-first** - start from the research questions and the requirements of
  the models we intend to fit, then look for the variables/contrasts/pairing
  those need.  This is what turns "we read the files" into "we looked for what
  the analysis needs".

CLI::

    python discovery.py --root . run --questions questions.json
    python discovery.py --root . report
    python discovery.py --root . candidates --disposition candidate
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

import contract_v2 as C
import source_units as SU

KEY_VALUE = re.compile(
    r"^\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 _/（）()\-]{0,20})"
    r"\s*[:：]\s*([^\n]{1,80})$")
DATE = re.compile(r"(19|20)\d{2}[-/年.](\d{1,2})[-/月.](\d{1,2})日?")
MEASURE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(%|岁|人|例|元|万元|年|月|天|小时|分|秒|km|kg|cm|mmHg|"
    r"次|个|份|件|篇|户|家|所|points?|years?|persons?|cases?)")
COUNT_CLAIM = re.compile(r"(共计|合计|共有|total of|n\s*=\s*)\s*(\d[\d,]*)", re.I)
ID_LIKE = re.compile(r"^(?:[A-Z]{1,4}[-_]?\d{1,8}|\d{4,})$")

#: Field-name synonyms used when the research question names a concept but the
#: material uses a different word.  This is a starting dictionary, not a limit:
#: the agent adds pairs as it learns the corpus.
SYNONYMS = {
    "age": ["年龄", "岁数", "age"],
    "sex": ["性别", "gender", "sex"],
    "income": ["收入", "月收入", "年收入", "income"],
    "education": ["学历", "受教育年限", "education"],
    "treatment": ["处理", "干预", "实验组", "treatment", "intervention"],
    "control": ["对照", "控制组", "control", "comparison"],
    "outcome": ["结果", "结局", "得分", "outcome", "score"],
    "time": ["时间", "年份", "日期", "时点", "year", "date", "wave"],
    "group": ["组别", "分组", "group", "arm"],
    "count": ["人数", "例数", "样本量", "n", "count"],
}


def _producer(**kw) -> dict:
    return C.producer_for("discovery", version="2.0", module_file=__file__,
                          **kw)


def _cid(*parts) -> str:
    return C.canonical_hash(list(parts))[:20]


def _source_identity(sources):
    return sorted(C.canonical_hash({k:s.get(k) for k in ("unit","source","locator","quote")}) for s in sources)


class Discovery:
    def __init__(self, project: C.Project, units: SU.SourceUnits):
        self.project = project
        self.units = units

    # -- helpers -----------------------------------------------------------
    def _text_of(self, unit: Mapping) -> str:
        rep = unit["data"].get("representation")
        if not rep:
            return ""
        path = self.units.representation_path(unit)
        if path.suffix.lower() in (".json", ".jsonl", ".txt", ".csv", ".tsv",
                                   ".md", ".xml", ".html", ""):
            return path.read_text(encoding="utf-8-sig")
        return ""

    def _candidate(self, *, origin: str, kind: str, name: str, sources: list,
                   disposition: str = "candidate", **extra) -> dict:
        sources=[dict(source) for source in sources]
        for source in sources:
            unit=self.project.latest("source_unit",source.get("unit")) if source.get("unit") else None
            if unit:source["source_sha256"]=unit["data"]["source_sha256"]
        payload = {"origin": origin, "kind": kind, "name": name,
                   "sources": sources, "disposition": disposition}
        payload.update({k: v for k, v in extra.items() if v is not None})
        cid = (_cid(origin,kind,name,_source_identity(sources))
               if origin=="source_first" else _cid(origin,kind,name))
        prev = self.project.latest("discovery_candidate", cid)
        if prev is not None and prev["producer"].get("code_sha256")==C.file_sha256(__file__) and all(
                prev["data"].get(key)==value for key,value in payload.items() if key not in ("disposition","reason","dataset")):
            return prev
        if prev is None:
            rec = C.make_record("discovery_candidate", cid, payload,
                                producer=_producer(), status=disposition)
        else:
            rec = C.make_record("discovery_candidate", cid, payload,
                                producer=_producer(), status=disposition,
                                revision=prev["revision"] + 1)
        self.project.append("discovery_candidate", rec, enforce_transition=False)
        return rec

    def _coverage(self, unit: Mapping, structure: str, disposition: str,
                  reason: str | None = None) -> dict:
        payload = {"source": unit["data"]["source"],
                   "source_sha256": unit["data"]["source_sha256"],
                   "structure": structure, "disposition": disposition,
                   "enumeration_method": "source_units.build"}
        if reason:
            payload["reason"] = reason
        cid = _cid("coverage", unit["id"], structure)
        prev = self.project.latest("structure_coverage", cid)
        if prev is not None and prev["producer"].get("code_sha256")==C.file_sha256(__file__) and C.canonical_hash(prev["data"]) == \
                C.canonical_hash(payload):
            return prev
        rec = C.make_record("structure_coverage", cid, payload,
                            producer=_producer(), status=disposition,
                            revision=(prev["revision"] + 1) if prev else 1)
        self.project.append("structure_coverage", rec, enforce_transition=False)
        return rec

    # -- material-first ----------------------------------------------------
    def from_materials(self) -> dict:
        created = 0
        tables = 0
        scanned = []
        for unit in self.units.units():
            data = unit["data"]
            kind = data["unit_type"]
            if data["unrecovered"]:
                scanned.append(unit["id"])
            if kind == "table":
                created += self._from_table(unit)
                tables += 1
                self._coverage(unit, "table", "covered",
                               "headers and body entered discovery")
            elif kind in ("document", "paragraph", "page"):
                created += self._from_text(unit)
                self._coverage(unit, kind, "covered" if not data["unrecovered"]
                               else "unrecovered", "; ".join(data["unrecovered"]))
            elif kind in ("sheet",):
                created += self._from_sheet(unit)
                self._coverage(unit, "sheet", "covered")
            elif kind in ("region", "segment"):
                created += self._from_region(unit)
                self._coverage(unit, kind, "covered")
            elif kind in ("media", "image"):
                self._coverage(unit, kind, "unrecovered",
                               "; ".join(data["unrecovered"]))
            elif kind in ("member", "attachment", "object"):
                self._coverage(unit, kind, "not_used",
                               "container member: keeps identity, is not counted "
                               "as an independent observation until read")
        return {"candidates": created, "tables": tables,
                "unrecovered_structures": len(scanned)}

    def _from_table(self, unit: Mapping) -> int:
        rep = unit["data"].get("representation")
        header: list[str] = []
        if rep:
            text = self.units.representation_path(unit).read_text(encoding="utf-8-sig")
            first = next((ln for ln in text.splitlines() if ln.strip()), "")
            try:
                data = json.loads(text) if first.strip().startswith(("[", "{")) else None
            except json.JSONDecodeError:
                data = None
            if data is not None:
                header = data[0] if isinstance(data, list) else data.get(
                    "header", [])
            elif first:
                import csv as _csv
                import io
                delim = unit["data"]["locator"].get("delimiter", "\t" if "\t" in first else ",")
                header = next(_csv.reader(io.StringIO(text), delimiter=delim))
        n = 0
        for col in header:
            if not str(col).strip():
                continue
            self._candidate(origin="source_first", kind="field",
                            name=str(col).strip(),
                            sources=[{"unit": unit["id"],
                                      "source": unit["data"]["source"],
                                      "locator": unit["data"]["locator"],
                                      "quote": str(col)}],
                            unit="table column",
                            suggested_shape="one column in a table dataset")
            n += 1
        return n

    def _from_text(self, unit: Mapping) -> int:
        text = self._text_of(unit)
        n = 0
        for line in text.splitlines():
            m = KEY_VALUE.match(line)
            if m and len(m.group(1).strip()) <= 20:
                self._candidate(
                    origin="source_first", kind="field",
                    name=m.group(1).strip(),
                    sources=[{"unit": unit["id"],
                              "source": unit["data"]["source"],
                              "locator": unit["data"]["locator"],
                              "quote": line.strip()}],
                    quote=line.strip()[:200],
                    suggested_shape="key/value field")
                n += 1
            for dm in DATE.finditer(line):
                self._candidate(
                    origin="source_first", kind="time_point",
                    name=dm.group(0),
                    sources=[{"unit": unit["id"],
                              "source": unit["data"]["source"],
                              "locator": unit["data"]["locator"],
                              "quote": line.strip()[:160]}])
                n += 1
            for cm in COUNT_CLAIM.finditer(line):
                self._candidate(
                    origin="source_first", kind="measure",
                    name=f"count={cm.group(2)}",
                    sources=[{"unit": unit["id"],
                              "source": unit["data"]["source"],
                              "locator": unit["data"]["locator"],
                              "quote": line.strip()[:160]}],
                    unit="count")
                n += 1
            for mm in MEASURE.finditer(line):
                self._candidate(
                    origin="source_first", kind="measure",
                    name=f"{mm.group(1)}{mm.group(2)}",
                    sources=[{"unit": unit["id"],
                              "source": unit["data"]["source"],
                              "locator": unit["data"]["locator"],
                              "quote": line.strip()[:160]}],
                    unit=mm.group(2))
                n += 1
        return n

    def _from_sheet(self, unit: Mapping) -> int:
        rep = unit["data"].get("representation")
        if not rep:
            return 0
        path = self.units.representation_path(unit)
        payload = json.loads(path.read_text(encoding="utf-8"))
        n = 0
        for cell in payload.get("cells", []):
            value = str(cell.get("value", ""))
            coord = cell.get("cell", "")
            if DATE.match(value):
                self._candidate(origin="source_first", kind="time_point",
                                name=value,
                                sources=[{"unit": unit["id"],
                                          "source": unit["data"]["source"],
                                          "locator": {"type": "xlsx",
                                                      "sheet": payload.get("sheet"),
                                                      "cell": coord},
                                          "quote": value}])
                n += 1
            if ID_LIKE.match(value) and len(value) <= 12:
                self._candidate(origin="source_first", kind="field",
                                name=f"id-like column at {coord}",
                                sources=[{"unit": unit["id"],
                                          "source": unit["data"]["source"],
                                          "locator": {"type": "xlsx",
                                                      "sheet": payload.get("sheet"),
                                                      "cell": coord},
                                          "quote": value}],
                                ambiguity="value looks like an identifier; the "
                                          "column meaning is not inferred")
                n += 1
        return n

    def _from_region(self, unit: Mapping) -> int:
        scope = unit["data"].get("recovered_scope", {})
        text = scope.get("transcript")
        if not text:
            return 0
        n = 0
        for mm in MEASURE.finditer(text):
            self._candidate(origin="source_first", kind="measure",
                            name=f"{mm.group(1)}{mm.group(2)}",
                            sources=[{"unit": unit["id"],
                                      "source": unit["data"]["source"],
                                      "locator": unit["data"]["locator"],
                                      "quote": text[:160]}],
                            unit=mm.group(2),
                            ambiguity="value comes from OCR/ASR; it must be "
                                      "re-read at the original before use")
            n += 1
        return n

    # -- question-first ----------------------------------------------------
    def from_questions(self, questions: Iterable[Mapping]) -> dict:
        created = 0
        material_text = []
        for unit in self.units.units():
            if unit["data"]["unit_type"] in ("document", "paragraph", "page",
                                             "region", "segment", "table",
                                             "sheet"):
                material_text.append((unit, self._text_of(unit).lower()))
        for q in questions:
            qid = q.get("id") or _cid("question", q.get("question", ""))[:12]
            need_fields = q.get("needs") or []
            for term in need_fields:
                synonyms = SYNONYMS.get(term.lower(), [term])
                found = []
                for unit, text in material_text:
                    for syn in synonyms:
                        if syn.lower() in text:
                            found.append({"unit": unit["id"],
                                          "source": unit["data"]["source"],
                                          "locator": unit["data"]["locator"],
                                          "quote": syn})
                            break
                disposition = "candidate" if found else "unresolved"
                self._candidate(
                    origin="question_first", kind="dataset",
                    name=f"{qid}:{term}", sources=found,
                    disposition=disposition,
                    research_use=q.get("question"),
                    reason=None if found else
                    f"no material text matched {synonyms}; this is a real gap, "
                    f"not proof the field is absent",
                    data_gap=None if found else f"gap:{qid}:{term}")
                created += 1
        return {"candidates": created, "questions": len(list(questions))}

    # -- dispositions ------------------------------------------------------
    def dispose(self, candidate_id: str, disposition: str, *,
                reason: str, dataset: str | None = None) -> dict:
        rec = self.project.latest("discovery_candidate", candidate_id)
        if rec is None:
            raise SystemExit(f"unknown candidate {candidate_id}")
        payload = dict(rec["data"])
        payload["disposition"] = disposition
        payload["reason"] = reason
        if dataset:
            payload["dataset"] = dataset
        new = C.make_record("discovery_candidate", rec["id"], payload,
                            producer=_producer(), status=disposition,
                            revision=rec["revision"] + 1)
        self.project.append("discovery_candidate", new)
        return new

    # -- report ------------------------------------------------------------
    def _active_candidates(self):
        active={r["id"]:r["data"]["source_sha256"] for r in self.units.units()}
        latest={r["id"]:r for r in self.project.read("discovery_candidate")}
        return {key:r for key,r in latest.items() if
                (r["data"]["origin"]!="source_first" or key==_cid("source_first",r["data"]["kind"],r["data"]["name"],_source_identity(r["data"]["sources"])))
                and (not r["data"]["sources"] or any(not s.get("unit") or s["unit"] in active and s.get("source_sha256")==active[s["unit"]] for s in r["data"]["sources"]))}

    def report(self) -> dict:
        cands = self.project.read("discovery_candidate")
        latest = {}
        for rec in cands:
            if rec["id"] not in latest or rec["revision"] > latest[rec["id"]]["revision"]:
                latest[rec["id"]] = rec
        historical=len(latest)
        latest=self._active_candidates()
        by_kind: dict[str, int] = {}
        by_disp: dict[str, int] = {}
        for rec in latest.values():
            by_kind[rec["data"]["kind"]] = by_kind.get(rec["data"]["kind"], 0) + 1
            by_disp[rec["data"]["disposition"]] = by_disp.get(
                rec["data"]["disposition"], 0) + 1
        active_units=self.units.units()
        latest_coverage={r["id"]:r for r in self.project.read("structure_coverage")}
        cov=[latest_coverage[key] for unit in active_units
             if (key:=_cid("coverage",unit["id"],unit["data"]["unit_type"])) in latest_coverage
             and latest_coverage[key]["data"]["source_sha256"]==unit["data"]["source_sha256"]
             and latest_coverage[key]["producer"].get("code_sha256")==C.file_sha256(__file__)]
        cv: dict[str, int] = {}
        for rec in cov:
            cv[rec["data"]["disposition"]] = cv.get(
                rec["data"]["disposition"], 0) + 1
        return {"candidates": len(latest), "by_kind": by_kind,"producer_sha256":C.file_sha256(__file__),
                "by_disposition": by_disp, "structures": len(cov),
                "structure_dispositions": cv,
                "historical_inactive_candidates":historical-len(latest), "unresolved_candidates": [
                    r["id"] for r in latest.values()
                    if r["data"]["disposition"] in ("candidate", "unresolved", "blocked")]}

    def coverage_errors(self) -> list[dict]:
        """Any structure with no disposition, or candidate with no reason."""
        errors = []
        covered = {r["id"]:r for r in self.project.read("structure_coverage")}
        for unit in self.units.units():
            key = _cid("coverage", unit["id"], unit["data"]["unit_type"])
            if key not in covered or covered[key]["data"]["source_sha256"] != unit["data"]["source_sha256"] or covered[key]["producer"].get("code_sha256")!=C.file_sha256(__file__):
                errors.append({"check": "structure_unaccounted",
                               "unit": unit["id"], "source": unit["data"]["source"],
                               "structure": unit["data"]["unit_type"]})
        latest = {}
        for rec in self.project.read("discovery_candidate"):
            if rec["id"] not in latest or rec["revision"] > latest[rec["id"]]["revision"]:
                latest[rec["id"]] = rec
        for rec in latest.values():
            if rec["data"]["disposition"] in ("excluded", "unresolved") and \
                    not rec["data"].get("reason"):
                errors.append({"check": "candidate_without_reason",
                               "candidate": rec["id"]})
        return errors


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="two-path discovery")
    ap.add_argument("--root", default=".")
    ap.add_argument("--materials", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--questions")
    p_disp = sub.add_parser("dispose")
    p_disp.add_argument("--candidate", required=True)
    p_disp.add_argument("--disposition", required=True,
                        choices=["adopted", "excluded", "unresolved", "blocked"])
    p_disp.add_argument("--reason", required=True)
    p_disp.add_argument("--dataset")
    p_c = sub.add_parser("candidates")
    p_c.add_argument("--disposition")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    units = SU.SourceUnits(proj, root=args.materials or Path(args.root))
    disc = Discovery(proj, units)
    if args.cmd == "run":
        res = disc.from_materials()
        questions = []
        if args.questions:
            questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
        if questions:
            res.update(disc.from_questions(questions))
        report = disc.report()
        proj.write_snapshot("discovery/report.json", report)
        print(json.dumps({**res, "report": report}, ensure_ascii=False, indent=1))
        errors = disc.coverage_errors()
        if errors:
            print(json.dumps({"coverage_errors": errors}, ensure_ascii=False,
                             indent=1), file=sys.stderr)
            return 2
        return 0
    if args.cmd == "dispose":
        print(json.dumps(disc.dispose(args.candidate, args.disposition,
                                      reason=args.reason,
                                      dataset=args.dataset),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "candidates":
        for rec in proj.read("discovery_candidate"):
            if args.disposition and rec["data"]["disposition"] != args.disposition:
                continue
            print(f"{rec['id']} {rec['data']['kind']:12s} "
                  f"{rec['data']['disposition']:10s} {rec['data']['name']}")
        return 0
    if args.cmd == "report":
        print(json.dumps(disc.report(), ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
