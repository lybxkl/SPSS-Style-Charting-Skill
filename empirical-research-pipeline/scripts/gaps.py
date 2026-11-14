# -*- coding: utf-8 -*-
"""Data gaps, real searches and the closure loop.

A gap is not "we did not bother": it is a requirement some model or dataset has,
linked to every search that was actually executed for it, ending in one of the
real end states (found and integrated / unavailable / blocked / exhausted).  The
loop this module encodes is:

    requirement -> gap -> executed search(es) -> found a real value
      -> integrate into a dataset -> re-prepare -> re-review -> re-assess model
    or -> unavailable (with the searched range) / blocked (with the condition)

``completeness`` is what the release gate uses: every gap has at least one
executed search; a ``resolved`` gap names the dataset it entered; a
``not_found`` conclusion is only allowed when the searches covered the whole
inventory.

CLI::

    python gaps.py --root . open --target model:M1 --requirement "event count"
    python gaps.py --root . attach --gap <id> --run <search_run_id> \\
        --conclusion found --note "..."
    python gaps.py --root . resolve --gap <id> --dataset events --note "..."
    python gaps.py --root . check
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C
import search_index as SI


def _producer(**kw) -> dict:
    return C.producer_for("gaps", version="2.0", module_file=__file__, **kw)


CONCLUSIONS = ("found", "not_found", "unreadable", "not_relevant")


def _current_searches(project, searches):
    current=[];historical=[]
    for item in searches:
        try:current.append((item,SI.require_executed(project,item["run"])))
        except (ValueError,C.ContractError,OSError) as exc:historical.append({"run":item["run"],"reason":str(exc)})
    return current,historical


def _gap_id(target: str, requirement: str) -> str:
    return C.canonical_hash([target, requirement])[:20]


def open_gap(project: C.Project, *, target: str, requirement: str,
             status_detail: str, model_or_dataset: str | None = None,
             impact: str | None = None) -> dict:
    payload = {"model_or_dataset": model_or_dataset or target,
               "requirement": requirement, "status_detail": status_detail,
               "searches": []}
    if impact:
        payload["impact"] = impact
    gid = _gap_id(target, requirement)
    prev = project.latest("data_gap", gid)
    if prev is not None:
        payload["searches"] = prev["data"]["searches"]
        rec = C.make_record("data_gap", gid, payload, producer=_producer(),
                            status=prev["status"], revision=prev["revision"] + 1)
    else:
        rec = C.make_record("data_gap", gid, payload, producer=_producer(),
                            status="open")
    project.append("data_gap", rec, enforce_transition=False)
    return rec


def attach_search(project: C.Project, gap_id: str, run_id: str, *,
                  conclusion: str, note: str,
                  resolution: str | None = None) -> dict:
    if conclusion not in CONCLUSIONS:
        raise ValueError(f"conclusion must be one of {CONCLUSIONS}")
    run = SI.require_executed(project, run_id)
    if conclusion == "found" and not run["data"]["hits"]:
        raise ValueError("a zero-hit search cannot be recorded as found")
    if not note.strip():
        raise ValueError("a search conclusion needs a source/context assessment")
    gap = project.latest("data_gap", gap_id)
    if gap is None:
        raise SystemExit(f"unknown gap {gap_id}")
    searches = list(gap["data"]["searches"])
    queries = run["data"]["query"]
    sources = [{"source": s["source"], "sha256": s["sha256"]}
               for s in run["data"]["sources"]]
    entry = {"run": run_id, "conclusion": conclusion, "note": note,
             "query": queries, "index": run["data"]["index"],
             "hits": len(run["data"]["hits"]),
             "sources": sources}
    if resolution:
        entry["resolution"] = resolution
    searches.append(entry)
    payload = dict(gap["data"])
    payload["searches"] = searches
    payload["status_detail"] = (f"{len(searches)} search(es); last conclusion: "
                                f"{conclusion}")
    if conclusion == "found":
        new_status = "searching"
    elif conclusion == "not_found":
        new_status = "searching"
    elif conclusion == "unreadable":
        new_status = "blocked"
        payload["blocked_reason"] = note
    else:
        new_status = "searching"
    rec = C.make_record("data_gap", gap["id"], payload, producer=_producer(),
                        status=new_status, revision=gap["revision"] + 1)
    project.append("data_gap", rec, enforce_transition=False)
    return rec


def resolve(project: C.Project, gap_id: str, *, dataset: str,
            resolution: str, cells: Iterable[Mapping] = (),
            verification: str = "output/dataset/dataset_verification.json") -> dict:
    gap = project.latest("data_gap", gap_id)
    if gap is None:
        raise SystemExit(f"unknown gap {gap_id}")
    if not any(s["conclusion"] == "found" for s in gap["data"]["searches"]):
        raise ValueError("a gap cannot be resolved without an executed search "
                         "that found the value")
    import verify_dataset as VD
    cells = list(cells)
    if not cells or not resolution.strip():
        raise ValueError("resolution needs exact integrated cells and an assessment note")
    registry = project.root / "research_registry.json"
    try:
        verifier, report = VD.validate_final_report(registry, project.root, verification)
    except Exception as exc:
        raise ValueError(f"integration requires current full-dataset final review: {exc}") from exc
    if dataset not in verifier.datasets:
        raise ValueError(f"integrated dataset is not registered: {dataset}")
    for cell in cells:
        target = (dataset, VD.key_tuple(cell["key"]), cell["column"])
        if target not in verifier.cells or verifier.cells[target][0] != str(cell["value"]):
            raise ValueError(f"integrated cell/value does not exist: {target}")
        if verifier.records[target]["kind"] == "missing":
            raise ValueError("a still-missing cell does not resolve the gap")
    current,_ = _current_searches(project,gap["data"]["searches"])
    found_runs = [run for item,run in current if item["conclusion"]=="found"]
    if not found_runs:raise ValueError("repeat the found-value search against current materials before resolving")
    material_root = Path(verifier.registry.get("source_root") or "materials")
    material_root = material_root if material_root.is_absolute() else project.root / material_root
    found_paths = {(material_root / h["source"]).resolve() for run in found_runs for h in run["data"]["hits"]}
    for cell in cells:
        proof = verifier.records[(dataset, VD.key_tuple(cell["key"]), cell["column"])]
        source_paths = {verifier.path(s["path"]) for s in proof.get("sources", []) if s.get("path")}
        if not source_paths & found_paths:
            raise ValueError("integrated cells must link to the actually found source")
    reassessment = None
    owner = gap["data"]["model_or_dataset"]
    if owner.startswith("model:"):
        import models as M
        model_id = owner.partition(":")[2]
        model = project.latest("model_spec", model_id)
        if model is None or model["status"] not in ("completed", "insufficient_data", "not_applicable"):
            raise ValueError("the target model must be re-evaluated after integration")
        if VD.parse_time(model["created_at"]) < VD.parse_time(report["generated_at"]):
            raise ValueError("model reassessment predates the final review")
        if not M.conditions(project, model_id)["ok"]:
            raise ValueError("model reassessment is not bound to the integrated inputs")
        reassessment = {"id": model_id, "revision": model["revision"], "signature": C.signature(model)}
    payload = dict(gap["data"])
    payload["resolution"] = resolution
    payload["resolved_dataset"] = dataset
    payload["conclusion"] = "found and integrated"
    payload["integration"] = {"cells": cells, "dataset_sha256": C.file_sha256(verifier.path(verifier.datasets[dataset]["spec"]["path"])),
                              "verification": str(verification), "verification_sha256": C.file_sha256(verifier.path(verification)),
                              "reassessment": reassessment}
    rec = C.make_record("data_gap", gap["id"], payload, producer=_producer(),
                        status="resolved", revision=gap["revision"] + 1)
    project.append("data_gap", rec, enforce_transition=False)
    return rec


def close_unavailable(project: C.Project, gap_id: str, *, reason: str) -> dict:
    gap = project.latest("data_gap", gap_id)
    if gap is None:
        raise SystemExit(f"unknown gap {gap_id}")
    if not gap["data"]["searches"]:
        raise ValueError("an 'unavailable' conclusion needs at least one "
                         "executed search; otherwise it is just unexamined")
    runs = [run for _,run in _current_searches(project,gap["data"]["searches"])[0]]
    if not runs:raise ValueError("no current search; repeat after materials/index changes")
    cover = SI.searches_cover(project, [r["id"] for r in runs], runs[-1]["data"]["inventory"])
    if not cover["complete"] or not reason.strip():
        raise ValueError("unavailable requires actual complete search range and a reason")
    payload = dict(gap["data"])
    payload["conclusion"] = "unavailable"
    payload["blocked_reason"] = reason
    payload["coverage"] = cover
    rec = C.make_record("data_gap", gap["id"], payload, producer=_producer(),
                        status="unavailable", revision=gap["revision"] + 1)
    project.append("data_gap", rec, enforce_transition=False)
    return rec


def exhaust(project: C.Project, gap_id: str, *, note: str,
            inventory: Iterable[Mapping]) -> dict:
    """Declare the search range exhausted - only if it really was covered."""
    gap = project.latest("data_gap", gap_id)
    if gap is None:
        raise SystemExit(f"unknown gap {gap_id}")
    runs = [run["id"] for _,run in _current_searches(project,gap["data"]["searches"])[0]]
    if not runs or not note.strip():raise ValueError("exhaustion needs current executed searches and a contextual assessment")
    cover = SI.searches_cover(project, runs, inventory)
    if not cover["complete"]:
        raise ValueError(f"cannot declare 'exhausted': searches do not cover "
                         f"the inventory ({cover['missing'][:10]} missing, "
                         f"{cover['hash_mismatch'][:10]} with a stale hash)")
    payload = dict(gap["data"])
    payload["conclusion"] = "exhausted within the declared range"
    payload["coverage"] = cover
    payload["blocked_reason"] = note
    rec = C.make_record("data_gap", gap["id"], payload, producer=_producer(),
                        status="exhausted", revision=gap["revision"] + 1)
    project.append("data_gap", rec, enforce_transition=False)
    return rec


def completeness(project: C.Project) -> dict:
    gaps = project.read("data_gap")
    latest: dict[str, dict] = {}
    for rec in gaps:
        if rec["id"] not in latest or rec["revision"] > latest[rec["id"]]["revision"]:
            latest[rec["id"]] = rec
    errors = []
    for gid, rec in latest.items():
        data = rec["data"]
        if rec["status"] in ("open", "searching", "blocked"):
            errors.append({"check": "gap_not_terminal", "gap": gid, "status": rec["status"]})
        current,historical=_current_searches(project,data["searches"])
        if data["searches"] and not current:
            errors.append({"check":"gap_search_stale","gap":gid,"detail":historical})
        if rec["status"] in ("unavailable","exhausted") and current:
            cover=SI.searches_cover(project,[run["id"] for _,run in current],current[-1][1]["data"]["inventory"])
            if not cover["complete"]:errors.append({"check":"gap_current_range_incomplete","gap":gid,"detail":cover})
        if not data["searches"] and rec["status"] not in ("open", "searching"):
            errors.append({"check": "gap_without_search", "gap": gid,
                           "status": rec["status"]})
        if rec["status"] == "resolved" and not data.get("resolved_dataset"):
            errors.append({"check": "resolved_without_dataset", "gap": gid})
        if rec["status"] == "resolved":
            integration = data.get("integration") or {}
            try:
                import verify_dataset as VD
                if not integration.get("cells"):
                    raise ValueError("no exact integrated cell receipt")
                path = project.root / integration["verification"]
                if C.file_sha256(path) != integration["verification_sha256"]:
                    raise ValueError("final review changed after gap resolution")
                verifier, _ = VD.validate_final_report("research_registry.json", project.root, path)
                entry = verifier.datasets[data["resolved_dataset"]]["spec"]
                if C.file_sha256(verifier.path(entry["path"])) != integration["dataset_sha256"]:
                    raise ValueError("integrated dataset changed")
                assessment = integration.get("reassessment")
                if assessment and C.signature(project.latest("model_spec", assessment["id"])) != assessment["signature"]:
                    raise ValueError("target model changed after reassessment")
            except Exception as exc:
                errors.append({"check": "gap_integration_stale", "gap": gid, "detail": str(exc)})
        if rec["status"] == "exhausted" and "coverage" not in data:
            errors.append({"check": "exhausted_without_coverage", "gap": gid})
    by_status: dict[str, int] = {}
    for rec in latest.values():
        by_status[rec["status"]] = by_status.get(rec["status"], 0) + 1
    return {"gaps": len(latest), "by_status": by_status, "errors": errors,
            "open": [gid for gid, r in latest.items()
                     if r["status"] in ("open", "searching", "blocked")]}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="data gap closure")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_open = sub.add_parser("open")
    p_open.add_argument("--target", required=True)
    p_open.add_argument("--requirement", required=True)
    p_open.add_argument("--detail", default="")
    p_att = sub.add_parser("attach")
    p_att.add_argument("--gap", required=True)
    p_att.add_argument("--run", required=True)
    p_att.add_argument("--conclusion", required=True, choices=list(CONCLUSIONS))
    p_att.add_argument("--note", required=True)
    p_res = sub.add_parser("resolve")
    p_res.add_argument("--gap", required=True)
    p_res.add_argument("--dataset", required=True)
    p_res.add_argument("--note", required=True)
    p_res.add_argument("--cells", required=True, help="JSON array of exact key/column/value cells")
    p_res.add_argument("--verification", default="output/dataset/dataset_verification.json")
    p_un = sub.add_parser("unavailable")
    p_un.add_argument("--gap", required=True)
    p_un.add_argument("--reason", required=True)
    sub.add_parser("check")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "open":
        print(json.dumps(open_gap(proj, target=args.target,
                                  requirement=args.requirement,
                                  status_detail=args.detail),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "attach":
        print(json.dumps(attach_search(proj, args.gap, args.run,
                                       conclusion=args.conclusion,
                                       note=args.note),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "resolve":
        print(json.dumps(resolve(proj, args.gap, dataset=args.dataset,
                                 resolution=args.note, cells=json.loads(Path(args.cells).read_text(encoding="utf-8")),
                                 verification=args.verification),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "unavailable":
        print(json.dumps(close_unavailable(proj, args.gap,
                                           reason=args.reason),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "check":
        res = completeness(proj)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if not res["errors"] else 2
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
