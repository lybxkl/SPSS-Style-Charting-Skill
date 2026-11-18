# -*- coding: utf-8 -*-
"""Release gate and release snapshot: four states, no green-washing.

The gate reads the contract ledgers (output/v2) and the main-chain
research-registry evidence and decides

* ``complete``   - every declared scope item is covered and every hard truth gate
                   passed;
* ``limited``    - a *narrowed* scope is fully covered (the narrowing is written
                   into the snapshot, not implied);
* ``not_ready``  - a hard gate is unassessed, missing, or a required item has no
                   evidence;
* ``failed``     - a hard gate actively failed (contradicting, tampered,
                   untraceable number, stale review).

``partial`` never bypasses a hard gate: a limited release still needs full-cell
review and traceable numbers for the cells it claims, it simply claims fewer
cells/sections.  Every check records the evidence path it looked at.

Scope keys: ``datasets``/``models``/``claims``/``figures`` are identity lists;
a manuscript release additionally declares ``sections`` plus the actual
print artifacts ``docx`` and ``pdf`` (project-relative), the printed-number
map ``numbers`` with its evidence ``trace``, and the caption/table specs the
print check reads (``figure_specs``/``table_specs``).  Omitting
``numbers``/``trace`` verifies zero numbers and cannot upgrade a missing
trace report.

CLI::

    python release.py --root . evaluate --scope scope.json
    python release.py --root . build --scope scope.json [--allow-limited]
    python release.py --root . show
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
import gaps as G
import lifecycle as L
import models as M
import validation as V
import evidence as E


def _producer(**kw) -> dict:
    return C.producer_for("release", version="2.0", module_file=__file__, **kw)


HARD_GATES = ("datasets_reviewed", "models_terminal", "results_validated",
              "claims_supported", "numbers_traceable", "gaps_closed",
              "artifacts_present")


def _latest_by_id(project: C.Project, kind: str) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for rec in project.read(kind):
        if rec["id"] not in latest or rec["revision"] > latest[rec["id"]]["revision"]:
            latest[rec["id"]] = rec
    return latest


def _check(name: str, errors: list, warnings: list, ok: bool, detail: str,
           evidence: Iterable[str] = (), hard: bool = True) -> dict:
    item = {"check": name, "ok": bool(ok) and not [e for e in errors
                                                   if e.get("check") == name],
            "detail": detail, "evidence": list(evidence), "hard": hard}
    if not item["ok"]:
        (errors if hard else warnings).append(
            {"check": name, "detail": detail, "evidence": list(evidence)})
    return item


def evaluate(project: C.Project, scope: Mapping) -> dict:
    try:
        before=_evidence_snapshot(project,scope)
        result=_evaluate(project, scope)
        if before != _evidence_snapshot(project,scope):
            result["errors"].append({"check":"evidence_changed_during_evaluation","detail":"inputs, code, records or runtime changed during the release check"})
            result["status"]="failed"
            result["hard_failed"].append("evidence_changed_during_evaluation")
        result["bindings"]=before
        return result
    except (C.ContractError, ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        return {"status": "failed" if isinstance(exc, C.IntegrityError) else "not_ready",
                "checks": [{"check": "current_evidence", "ok": False, "hard": True, "detail": str(exc), "evidence": []}],
                "errors": [{"check": "current_evidence", "detail": str(exc)}], "warnings": [],
                "scope": dict(scope), "hard_failed": ["current_evidence"], "uncovered": []}


def _evidence_snapshot(project,scope):
    """Seal actual dependencies before and after checking, excluding our own publication record."""
    files={}
    def add(value):
        if not isinstance(value,(str,Path)) or not str(value) or "\n" in str(value):return
        path=Path(value);path=path if path.is_absolute() else project.root/path
        try:
            path=path.resolve()
            if path.is_file() and str(path) not in files:files[str(path)]=C.file_sha256(path)
        except (OSError,ValueError):pass
    def walk(value):
        if isinstance(value,dict):
            for item in value.values():walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
        elif isinstance(value,str):add(value)
    registry=project.root/"research_registry.json";add(registry)
    if registry.is_file():
        data=json.loads(registry.read_text(encoding="utf-8"));walk(data)
        material=project.root/data.get("source_root","materials")
        if material.is_dir():
            for path in material.rglob("*"):
                if path.is_file():add(path)
    for kind in C.KINDS:
        if kind=="release_snapshot":continue
        path=project.ledger_path(kind)
        if path.is_file():add(path);walk(project.read(kind))
    for path in Path(__file__).parent.glob("*.py"):add(path)
    for path in project.path("models","specs").glob("*.json"):add(path)
    for name in ("output/dataset/dataset_verification.json","output/data_verification/dataset_verification.json","output/dataset_verification.json","output/v2/manuscript/verification.json","output/v2/units/materials.json"):
        path=project.root/name;add(path)
        if path.is_file():walk(json.loads(path.read_text(encoding="utf-8")))
    walk(dict(scope))
    import execution
    return {"files":files,"runtime":execution.environment(("matplotlib","python-docx","PyMuPDF","openpyxl"))}


def _evaluate(project: C.Project, scope: Mapping) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    checks: list[dict] = []
    scope = dict(scope)
    datasets = list(scope.get("datasets") or [])
    sections = list(scope.get("sections") or [])
    figures = list(scope.get("figures") or [])
    # scope.figures is the historical identity list (figure_spec ids); the print
    # check specs live under figure_specs/table_specs. Validate both shapes up
    # front so a wrong form folds into not_ready instead of a raw traceback.
    bad = [f for f in figures if not isinstance(f, str)]
    if bad:
        raise ValueError(f"scope.figures must be figure id strings, got: {bad[:3]}")
    for key in ("figure_specs", "table_specs"):
        items = list(scope.get(key) or [])
        bad = [i for i in items if not isinstance(i, dict)]
        if bad:
            raise ValueError(f"scope.{key} must be a list of spec objects, got: {bad[:3]}")
    trace_decl = scope.get("trace") or {}
    if not isinstance(trace_decl, dict):
        raise ValueError("scope.trace must be an object mapping placeholder keys to trace entries")
    bad = [v for v in trace_decl.values() if not isinstance(v, dict)]
    if bad:
        raise ValueError(f"scope.trace entries must be objects, got: {bad[:3]}")
    specs = _latest_by_id(project, "model_spec")
    model_ids = list(scope.get("models") or []) if "models" in scope else sorted(specs)
    claims = _latest_by_id(project,"claim")
    claim_ids=list(scope.get("claims") or []) if "claims" in scope else sorted(claims)
    registry_path = project.root / "research_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
    registered_paths = {(project.root / d["path"]).resolve(): d["id"] for d in registry.get("datasets", []) if d.get("path")}
    if sections:
        blocks=_latest_by_id(project,"manuscript_block")
        sections=list(dict.fromkeys([*sections,*[b["data"]["section"] for b in blocks.values()]]))
        for block in blocks.values():
            claim_ids.extend(cid for cid in block["data"].get("claims",[]) if cid not in claim_ids)
        claim_ids.extend(cid for cid,claim in claims.items() if claim["data"]["block_id"] in blocks and cid not in claim_ids)
        # the scope declares what the printed manuscript carries (figure specs
        # and the number trace); the compose.json sidecar is gone with the dual builder
        for item in scope.get("figure_specs") or []:
            fid = item.get("figure_id")
            if fid and fid not in figures:figures.append(fid)
        for item in (scope.get("trace") or {}).values():
            rid=item.get("result") or item.get("model")
            if rid:
                rec=project.latest("model_result",rid)
                mid=rec["data"]["model"] if rec else rid
                if mid not in model_ids:model_ids.append(mid)
            if item.get("dataset") and item["dataset"] not in datasets:datasets.append(item["dataset"])
    for cid in claim_ids:
        for item in (claims.get(cid) or {}).get("data",{}).get("support",[]):
            if item.get("kind") in ("result","model_result"):
                rec=project.latest("model_result",item["id"])
                if rec and rec["data"]["model"] not in model_ids:model_ids.append(rec["data"]["model"])
    for fid in figures:
        rec=project.latest("figure_spec",fid)
        for item in (rec or {}).get("data",{}).get("inputs",[]):
            if item.get("kind")=="dataset":
                ident=registered_paths.get((project.root/item["id"]).resolve())
                if ident and ident not in datasets:datasets.append(ident)
    for mid in model_ids:
        for item in (specs.get(mid) or {}).get("data", {}).get("inputs", []):
            ident = registered_paths.get((project.root / item["dataset"]).resolve())
            if ident and ident not in datasets:
                datasets.append(ident)
    verifier = None

    # -- datasets: main-chain verification report, if the project uses one ----
    verification_rel = scope.get("verification") or \
        "output/dataset/dataset_verification.json"
    verification_path = project.root / verification_rel
    if datasets:
        if not verification_path.is_file():
            checks.append(_check("datasets_reviewed", errors, warnings, False,
                                 f"{verification_rel} is missing", [verification_rel]))
        else:
            try:
                verifier, report = E.final_review(project, verification_rel, scope.get("adapters", ()))
            except Exception as exc:
                checks.append(_check("datasets_reviewed", errors, warnings, False, str(exc), [verification_rel]))
                report = {}
            status = str(report.get("status", ""))
            errors_in_report = int(report.get("error_count",
                                              len(report.get("issues", []))))
            by_dataset = {}
            raw = report.get("datasets", {})
            items = raw.items() if isinstance(raw, dict) else ((e.get("id"), e) for e in raw)
            for ident, entry in items:
                by_dataset[ident] = entry if isinstance(entry, dict) else {}
            missing = [d for d in datasets if d not in by_dataset]
            unreviewed = [d for d, e in by_dataset.items()
                          if d in datasets and
                          str(e.get("status", status)) != "verified"]
            ok = (verifier is not None and status == "verified" and errors_in_report == 0 and
                  not missing and not unreviewed)
            checks.append(_check(
                "datasets_reviewed", errors, warnings, ok,
                f"status={status} errors={errors_in_report} missing={missing} "
                f"unreviewed={unreviewed}", [verification_rel]))
    else:
        checks.append(_check("datasets_reviewed", errors, warnings, True,
                             "no dataset claimed in this scope", [], hard=True))
    if datasets or model_ids:
        try:
            verifier = verifier or E.final_review(project, verification_rel, scope.get("adapters", ()))[0]
            coverage = E.source_coverage(project, verifier)
            checks.append(_check("source_coverage", errors, warnings, True, f"{coverage['sources']} original sources accounted for"))
        except Exception as exc:
            checks.append(_check("source_coverage", errors, warnings, False, str(exc)))

    # -- models ------------------------------------------------------------
    results = _latest_by_id(project, "model_result")
    validations = project.read("validation_result")
    val_latest: dict[str, dict] = {}
    for rec in validations:
        if rec["id"] not in val_latest or rec["revision"] > val_latest[rec["id"]]["revision"]:
            val_latest[rec["id"]] = rec
    model_errors = []
    for mid in model_ids:
        spec = specs.get(mid)
        if spec is None:
            model_errors.append({"check": "models_terminal", "model": mid,
                                 "detail": "spec is not registered"})
            continue
        if spec["status"] not in ("completed", "insufficient_data",
                                  "not_applicable", "unsupported"):
            model_errors.append({"check": "models_terminal", "model": mid,
                                 "detail": f"status is {spec['status']}"})
            continue
        if spec["status"] != "completed":
            assessment = spec["data"].get("assessment") or {}
            if not assessment:
                model_errors.append({
                    "check": "models_terminal", "model": mid,
                    "detail": f"{spec['status']} without an assessment/gaps "
                              f"note"})
        last = results.get(mid)
        if spec["status"] == "completed" and last is None:
            model_errors.append({"check": "models_terminal", "model": mid,
                                 "detail": "completed without a result record"})
        if spec["status"] == "completed" and last:
            try:
                E.model_inputs(project, M.load_spec(project, mid)["data"], verification=verification_rel, adapters=scope.get("adapters", ()))
            except Exception as exc:
                model_errors.append({"check": "models_terminal", "model": mid, "detail": f"unreviewed model input: {exc}"})
            assessment = spec["data"].get("method_assessment") or {}
            method_record = project.latest("validation_result", assessment.get("record", ""))
            if (assessment.get("status") != "assessed" or method_record is None or method_record["status"] != "passed"
                    or method_record["producer"].get("code_sha256") != C.file_sha256(Path(__file__).with_name("designcheck.py"))
                    or method_record["data"]["target"].get("result_signature") != C.signature(last)):
                model_errors.append({"check": "models_terminal", "model": mid, "detail": "current method/design assessment missing or failed"})
    checks.append({"check": "models_terminal", "ok": not model_errors,
                   "detail": f"{len(model_ids)} model(s) in scope",
                   "evidence": [], "hard": True})
    errors.extend(model_errors)

    # -- results validated --------------------------------------------------
    val_errors = []
    for mid in model_ids:
        spec = specs.get(mid)
        if spec is None or spec["status"] != "completed":
            continue
        val = val_latest.get(f"val:{mid}:{spec['data'].get('target_parameter')}")
        if val is None or not V.is_current(project, mid, results.get(mid)):
            val_errors.append({
                "check": "results_validated", "model": mid,
                "detail": "no passed independent numeric validation"})
        last = results.get(mid)
        if last is not None and last["status"] not in ("validated", "produced"):
            val_errors.append({"check": "results_validated", "model": mid,
                               "detail": f"result status {last['status']}"})
    checks.append({"check": "results_validated", "ok": not val_errors,
                   "detail": "independent numeric validation per reported model",
                   "evidence": [], "hard": True})
    errors.extend(val_errors)

    # -- claims -------------------------------------------------------------
    claim_errors = []
    for cid in claim_ids:
        rec = claims.get(cid)
        if rec is None:
            claim_errors.append({"check": "claims_supported", "claim": cid,
                                 "detail": "claim is not registered"})
            continue
        if rec["status"] not in ("supported",):
            claim_errors.append({"check": "claims_supported", "claim": cid,
                                 "detail": f"status {rec['status']}"})
        else:
            import claims as CL
            verdict = CL.check_claim(project, rec, numbers=scope.get("numbers"), persist=False)
            if verdict["status"] != "supported":
                claim_errors.append({"check": "claims_supported", "claim": cid, "detail": verdict})
            import support_review
            if not support_review.is_current(project, rec):
                claim_errors.append({"check": "claims_supported", "claim": cid, "detail": "contextual source support review is missing or stale"})
            import refs
            for support in rec["data"].get("support", []):
                if support.get("kind") in ("reference", "ref"):
                    reference = refs.check_reference(project, support["id"], formal=True)
                    if not reference["ok"]:
                        claim_errors.append({"check": "claims_supported", "claim": cid, "detail": reference})
    checks.append({"check": "claims_supported", "ok": not claim_errors,
                   "detail": f"{len(claim_ids)} claim(s)",
                   "evidence": [], "hard": True})
    errors.extend(claim_errors)

    # -- numbers traceable (main-chain verify report) -----------------------
    trace_rel = scope.get("number_trace") or "output/verify/number_issues.csv"
    trace_path = project.root / trace_rel
    if trace_path.is_file():
        import csv
        rows = list(csv.DictReader(open(trace_path, encoding="utf-8-sig")))
        bad = [r for r in rows if str(r.get("severity", "")).lower() == "error"]
        checks.append(_check("numbers_traceable", errors, warnings, not bad,
                             f"{len(bad)} error(s) in {trace_rel}", [trace_rel]))
    else:
        checks.append(_check("numbers_traceable", errors, warnings,
                             not sections,
                             f"{trace_rel} not found; claimed sections need "
                             f"traceable numbers", [trace_rel]))
    if sections:
        import manuscript as MS
        docx_rel = scope.get("docx")
        try:
            if not docx_rel:
                raise ValueError("a manuscript release needs the DOCX assembled by assemble_manuscript (scope.docx)")
            docx_path = project.root / docx_rel
            if not docx_path.is_file():
                raise ValueError(f"{docx_rel} is missing; the actual manuscript DOCX is required")
            if not scope.get("pdf"):
                raise ValueError("a manuscript release needs its actual exported PDF as well as DOCX")
            actual_sections = {b["data"]["section"] for b in MS.latest_blocks(project).values()}
            if not set(sections).issubset(actual_sections):
                raise ValueError("claimed sections have no registered manuscript blocks")
            verified_text = MS.verify_printed(project, docx_path=docx_path,
                                              pdf_path=project.root / scope["pdf"],
                                              numbers=scope.get("numbers") or {},
                                              trace=trace_decl,
                                              figures=scope.get("figure_specs") or (),
                                              tables=scope.get("table_specs") or (), persist=False)
            if not verified_text["ok"]:
                raise ValueError(f"printed manuscript failed: {verified_text}")
            if not trace_path.is_file():
                # Upgrade numbers_traceable only when this run actually bound
                # numbers to evidence; an empty trace verifies nothing and must
                # not launder a missing trace file into "verified". A declared
                # trace with zero resolved numbers is still zero bindings.
                bound = bool(verified_text.get("numbers_used"))
                if bound:
                    errors[:] = [e for e in errors if e.get("check") != "numbers_traceable"]
                    for check in checks:
                        if check["check"] == "numbers_traceable":
                            check.update(ok=True, detail=f"{len(verified_text.get('numbers_used') or [])} number(s) bound to current evidence via the printed DOCX/PDF", evidence=[str(docx_path)])
                else:
                    warnings.append({"check": "numbers_traceable",
                                     "detail": "no numbers were bound to evidence (scope.numbers/trace empty); "
                                               "a manuscript release without traceable numbers is not complete",
                                     "evidence": [str(docx_path)]})
            checks.append(_check("manuscript_verified", errors, warnings, True, "actual blocks/numbers/support match the printed document"))
        except Exception as exc:
            checks.append(_check("manuscript_verified", errors, warnings, False, str(exc)))

    # -- gaps ---------------------------------------------------------------
    gap_state = G.completeness(project)
    checks.append({"check": "gaps_closed", "ok": not gap_state["errors"],
                   "detail": f"{gap_state['gaps']} gap(s), "
                             f"{len(gap_state['open'])} open",
                   "evidence": [], "hard": True})
    errors.extend(gap_state["errors"])

    # -- figures & layout ---------------------------------------------------
    figure_specs = _latest_by_id(project, "figure_spec")
    layout_checks = _latest_by_id(project, "layout_check")
    fig_errors = []
    for fid in figures:
        rec = figure_specs.get(fid)
        if rec is None:
            fig_errors.append({"check": "figures_present", "figure": fid,
                               "detail": "figure is not registered"})
            continue
        if rec["status"] != "checked":
            fig_errors.append({"check": "figures_present", "figure": fid,
                               "detail": f"status {rec['status']}"})
        figure = rec["data"]
        try:
            if rec["producer"].get("code_sha256") != C.file_sha256(Path(__file__).with_name("figsemantics.py")):
                raise ValueError("figure check implementation changed; recheck the actual figure")
            inputs=[{"dataset":i["id"],"sha256":i["sha256"]} for i in figure["inputs"] if i["kind"]=="dataset"]
            if not inputs:raise ValueError("figure has no independently reviewed data inputs")
            E.model_inputs(project,{"inputs":inputs},verification=verification_rel,adapters=scope.get("adapters",()))
        except Exception as exc:
            fig_errors.append({"check":"figures_present","figure":fid,"detail":f"current figure input review failed: {exc}"})
        for kind in ("png", "pdf"):
            if figure.get(kind):
                path = project.root / figure[kind]
                if not path.is_file() or figure.get(kind + "_sha256") != C.file_sha256(path):
                    fig_errors.append({"check": "figures_present", "figure": fid, "detail": f"{kind} is missing, unbound or changed"})
        current_layouts = []
        for layout in layout_checks.values():
            refs = layout["input_refs"]
            if (layout["status"] == "passed" and layout["producer"].get("code_sha256") == C.file_sha256(Path(__file__).with_name("layout_check.py")) and refs and all(
                    ref.get("sha256") and (project.root / ref["id"]).is_file()
                    and C.file_sha256(project.root / ref["id"]) == ref["sha256"] for ref in refs)
                    and any(image.get("figure_id") == fid and image.get("blob_sha256") == figure.get("png_sha256")
                            and image.get("docx") and image.get("pdf") for image in layout["data"]["images"])):
                current_layouts.append(layout)
        if not current_layouts:
            fig_errors.append({"check": "figures_present", "figure": fid, "detail": "no current layout check bound to this exact figure and its DOCX/PDF placement"})
    if figures:
        layout_ok = any(r["status"] == "passed" and all(
            ref.get("sha256") and (project.root / ref["id"]).is_file() and C.file_sha256(project.root / ref["id"]) == ref["sha256"]
            for ref in r["input_refs"] if ref["kind"] in ("docx", "pdf"))
                        and any(ref["kind"] == "docx" for ref in r["input_refs"])
                        for r in layout_checks.values())
        if not layout_ok:
            fig_errors.append({"check": "figures_present",
                               "detail": "no passed layout_check for the "
                                         "final placement"})
    errors.extend(fig_errors)

    # -- artifacts ----------------------------------------------------------
    missing_artifacts = []
    for rel in scope.get("artifacts") or []:
        if not (project.root / rel).is_file():
            missing_artifacts.append(rel)
    checks.append({"check": "artifacts_present", "ok": not missing_artifacts,
                   "detail": f"{len(missing_artifacts)} missing",
                   "evidence": missing_artifacts, "hard": True})
    if missing_artifacts:
        errors.append({"check": "artifacts_present",
                       "detail": missing_artifacts})

    hard_failed = [e for e in errors if e.get("check") in HARD_GATES or
                   e.get("check", "").startswith(HARD_GATES)]
    substantive = bool(datasets or model_ids or claim_ids or figures or sections)
    if not substantive:
        errors.append({"check": "empty_scope",
                       "detail": "the scope claims no dataset, model, claim, "
                                 "figure or section; a vacuous release is not "
                                 "a complete one"})
    # a release that silently leaves registered items out is not complete
    uncovered = []
    registry_path = project.root / "research_registry.json"
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registered = {d["id"] for d in registry.get("datasets", [])}
        uncovered += [d for d in sorted(registered) if d not in datasets]
    uncovered += [m for m in sorted(specs) if m not in model_ids]
    uncovered += [c for c in sorted(claims) if c not in claim_ids]
    uncovered += [f"figure:{f}" for f in sorted(figure_specs) if f not in figures]
    block_sections = {r["data"]["section"] for r in _latest_by_id(project, "manuscript_block").values()}
    uncovered += [f"section:{s}" for s in sorted(block_sections) if s not in sections]
    if uncovered:
        checks.append({"check": "scope_covers_registered", "ok": False,
                       "detail": f"{len(uncovered)} registered item(s) outside "
                                 f"the declared scope: {uncovered[:10]}",
                       "evidence": [], "hard": False})
    else:
        checks.append({"check": "scope_covers_registered", "ok": True,
                       "detail": "every registered item is inside the scope",
                       "evidence": [], "hard": False})
    if not errors:
        if uncovered and scope.get("allow_limited"):
            status = "limited"
        elif uncovered:
            status = "not_ready"
        else:
            status = "complete"
    elif any("tamper" in str(e) or "contradict" in str(e)
             for e in errors):
        status = "failed"
    else:
        status = "not_ready"
    hard_failed=sorted({e.get("check","unknown") for e in errors} | {c["check"] for c in checks if c.get("hard") and not c["ok"]})
    scope.update(datasets=datasets,models=model_ids,claims=claim_ids,figures=figures,sections=sections)
    scope.setdefault("deliverable_type","manuscript" if sections else "figures" if figures else "models" if model_ids else "datasets")
    if scope["deliverable_type"]=="full_research":
        path=project.root/scope.get("analysis_report","")
        if not sections or not path.is_file():
            errors.append({"check":"full_research_deliverables","detail":"full research needs reviewed manuscript sections, actual DOCX/PDF, and an actual analysis_report"})
            status="not_ready"
        hard_failed=sorted({e.get("check","unknown") for e in errors} | {c["check"] for c in checks if c.get("hard") and not c["ok"]})
    return {"status": status, "checks": checks, "errors": errors,
            "project_ready":status=="complete" and bool(sections) and scope.get("deliverable_type")=="full_research",
            "warnings": warnings, "scope": scope,
            "hard_failed": hard_failed, "uncovered": uncovered}


def build(project: C.Project, scope: Mapping, *, label: str = "release") -> dict:
    evaluation = evaluate(project, scope)
    artifacts = []
    for rel in scope.get("artifacts") or []:
        path = project.root / rel
        if path.is_file():
            artifacts.append({"path": rel, "sha256": C.file_sha256(path)})
    unfinished = [e for e in evaluation["errors"]]
    payload = {
        "scope": evaluation["scope"],
        "coverage": {"checks": len(evaluation["checks"]),
                     "passed": sum(1 for c in evaluation["checks"] if c["ok"]),
                     "errors": len(evaluation["errors"]),
                     "warnings": len(evaluation["warnings"])},
        "checks": evaluation["checks"],
        "unfinished": unfinished,
        "status_detail": evaluation["status"],
        "artifacts": artifacts,
        "gate": evaluation,
        "notes": "status reflects the declared scope only; a limited release "
                 "still requires full-cell review and traceable numbers inside "
                 "that scope",
    }
    rid = f"release:{label}"
    prev = project.latest("release_snapshot", rid)
    rec = C.make_record("release_snapshot", rid, payload,
                        producer=_producer(), status=evaluation["status"],
                        revision=(prev["revision"] + 1) if prev else 1)
    if evaluation.get("bindings") != _evidence_snapshot(project,scope):
        raise ValueError("evidence changed after evaluation; release publication refused")
    project.append("release_snapshot", rec, enforce_transition=False)
    manifest = project.path("release", "manifest.json")
    C.atomic_write_json(manifest, {"release": rec["id"],
                                   "revision":rec["revision"],
                                   "status": evaluation["status"],
                                   "artifacts": artifacts,
                                   "scope": payload["scope"],
                                   "unfinished": unfinished,
                                   "generated_at": C._now()})
    return {"release": rec["id"], "status": evaluation["status"],
            "scope_type":evaluation["scope"].get("deliverable_type"),"project_ready":evaluation.get("project_ready",False),
            "errors": evaluation["errors"],
            "manifest": manifest.relative_to(project.root).as_posix(),
            "artifacts": len(artifacts)}


def current(project: C.Project):
    """Read the published manifest and recheck readiness; historical complete is not current proof."""
    manifest=project.path("release","manifest.json")
    if not manifest.is_file():return {"status":"not_ready","published":False,"reason":"no published release manifest"}
    try:
        data=json.loads(manifest.read_text(encoding="utf-8"))
        records=project.revisions("release_snapshot",data["release"])
        record=next((r for r in records if r["revision"]==data.get("revision")),None)
        if record is None:return {"status":"not_ready","published":False,"reason":"published revision is missing or legacy; rebuild the release"}
        state=evaluate(project,record["data"]["scope"])
        if record["data"].get("gate",{}).get("bindings")!=state.get("bindings"):
            return {"status":"not_ready","published":True,"historical_status":record["status"],"reason":"published evidence changed; rebuild the release snapshot","evaluation":state,"project_ready":False}
        return {"status":state["status"],"published":True,"historical_status":record["status"],"revision":record["revision"],"release":record["id"],"evaluation":state}
    except (C.ContractError,ValueError,KeyError,OSError) as exc:
        return {"status":"failed","published":False,"reason":str(exc)}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="release gate")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("evaluate", "build"):
        p = sub.add_parser(name)
        p.add_argument("--scope", required=True)
        p.add_argument("--label", default="release")
    sub.add_parser("show")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "show":
        state=current(proj)
        print(json.dumps(state, ensure_ascii=False, indent=1))
        return 0 if state["status"]=="complete" else 2
    scope = json.loads(Path(args.scope).read_text(encoding="utf-8"))
    if args.cmd == "evaluate":
        res = evaluate(proj, scope)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["status"] == "complete" else 2
    res = build(proj, scope, label=args.label)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["status"] == "complete" else 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
