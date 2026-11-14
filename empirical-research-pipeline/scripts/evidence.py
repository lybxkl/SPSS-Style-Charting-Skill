"""Shared current-evidence checks used by manuscript and release consumers."""
from pathlib import Path
import json
import contract_v2 as C
import verify_dataset as VD


def final_review(project, verification=None, adapters=()):
    if verification is None:
        paths = ["output/dataset/dataset_verification.json", "output/data_verification/dataset_verification.json",
                 "output/dataset_verification.json"]
        verification = next((p for p in paths if (project.root / p).is_file()), paths[0])
    return VD.validate_final_report("research_registry.json", project.root, verification, adapters)


def model_inputs(project, spec, *, verification=None, adapters=()):
    verifier, report = final_review(project, verification, adapters)
    registered = {verifier.path(info["spec"]["path"]): ident for ident, info in verifier.datasets.items()}
    used, errors = set(), []
    for item in spec["inputs"]:
        path = verifier.path(item["dataset"])
        if not path.is_file() or C.file_sha256(path) != item["sha256"]:
            errors.append(f"changed input: {path}")
            continue
        ident = registered.get(path)
        if ident:
            used.add(ident)
            continue
        # Native structured data may be fitted directly, but its registered
        # audit view still has to pass independent structural reconciliation.
        views = [r for r in project.read("audit_view") if verifier.path(r["data"]["native_path"]) == path]
        latest = max(views, key=lambda r: (r["revision"], r["created_at"])) if views else None
        if latest and verifier.path(latest["data"]["view_path"]) in registered:
            import audit_view
            checked = audit_view.verify_view(project, latest["data"]["view_path"], record=False)
            if checked["ok"]:
                used.add(registered[verifier.path(latest["data"]["view_path"])])
                continue
        errors.append(f"input has no currently reviewed dataset/audit view: {path}")
    if errors:
        raise ValueError("; ".join(errors))
    return used, verifier, report


def source_coverage(project, verifier):
    """Reuse the maintained v1 original-file coverage rules, not its model-N rule."""
    from research_gate import ResearchGate
    gate = ResearchGate("research_registry.json", project.root)
    gate.source_coverage()
    if gate.issues:
        raise ValueError(f"original material coverage is incomplete: {gate.issues[:5]}")
    if project.ledger_path("source_unit").is_file() or project.path("units","materials.json").is_file():
        import discovery as D
        import source_units as SU
        units = SU.SourceUnits(project, root=project.root)
        manifest=project.path("units","materials.json")
        if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("producer_sha256") != C.file_sha256(SU.__file__):
            raise ValueError("source recovery generation is missing/stale; rebuild source units with the current implementation")
        discovery = D.Discovery(project, units)
        errors = discovery.coverage_errors()
        if errors or discovery.report()["unresolved_candidates"]:
            raise ValueError(f"discovery candidates/structures remain unassessed: {errors}, {discovery.report()['unresolved_candidates']}")
        coverage=VD.load_jsonl(verifier.path(verifier.registry["source_coverage"]))
        included={r["source"] for r in coverage if r.get("status")=="included"}
        current_units=units.units()
        missing=included-{unit["data"]["source"] for unit in current_units}
        if missing:raise ValueError(f"included materials have no recovered current source units: {sorted(missing)}")
        for unit in current_units:
            units.representation_path(unit)
            source = verifier.path(verifier.registry["source_root"]) / unit["data"]["source"]
            if not source.is_file() or C.file_sha256(source) != unit["data"]["source_sha256"]:
                raise ValueError("source units belong to old material versions; repeat discovery")
            if unit["data"]["source"] in included and unit["data"].get("unrecovered"):
                raise ValueError(f"included material contains unresolved recovery scope: {unit['id']}: {unit['data']['unrecovered']}")
            review=unit["data"].get("recovered_scope",{}).get("whole_unit_review")
            if review:
                report=verifier.path(review["report"])
                if not report.is_file() or C.file_sha256(report)!=review.get("report_sha256"):
                    raise ValueError("whole-unit recovery review report is missing or changed; repeat the actual scope review")
    return {"sources": len(gate.sources), "bindings": gate.bindings}
