"""Validate this planning snapshot, not research capabilities or runtime tests.

Run from any directory: python <this file> --self-test
The snapshot intentionally requires all implementation tasks/cards to be planned.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent
ROOT = DOCS.parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def validate(tasks, cards, audit, text):
    items = tasks["tasks"]
    by_id = {t["id"]: t for t in items}
    require(len(items) == len(by_id), "duplicate task")
    require(set(by_id) == {f"T{i:02d}" for i in range(1, 41)}, "task coverage")
    reqs = {r["id"] for r in tasks["requirements"]}
    require(len(reqs) == len(tasks["requirements"]) == 9, "requirement coverage")
    require(reqs == {f"R{i:02d}" for i in range(1, 10)}, "requirement ids")
    require(all(r["status"] == "planned" and r["required_for_completion"] for r in tasks["requirements"]), "planning requirements state")
    require(tasks["counts"] == {"requirements": 9, "tasks": 40, "phases": 8, "acceptance_scenarios": 60}, "declared counts")
    phases = {p["id"]: i for i, p in enumerate(tasks["phases"])}
    require(len(phases) == len(tasks["phases"]) == 8, "phase coverage")
    require(set(phases) == {f"M{i}" for i in range(8)}, "phase ids")
    all_cases = {f"A{i:02d}" for i in range(1, 61)}
    require(set(tasks["acceptance_case_ids"]) == all_cases and len(tasks["acceptance_case_ids"]) == 60, "case ids")
    owned = {case: set() for case in all_cases}
    covered = set()
    for task in items:
        require(task["status"] == "planned" and not task["implementation_evidence"], "planning task has implementation evidence")
        require(task["planned_deliverables"] and task["done_when"].strip(), "task lacks deliverables")
        require(task["requirements"] and set(task["requirements"]) <= reqs | {"foundation"}, "unknown requirement")
        require(task["phase"] in phases, "unknown phase")
        covered.update(set(task["requirements"]) - {"foundation"})
        for field in ("depends_on", "integration_dependencies"):
            deps = task[field]
            require(len(deps) == len(set(deps)), "duplicate dependency")
            require(set(deps) <= set(by_id), "unknown dependency")
            require(task["id"] not in deps, "self dependency")
            require(all(phases[by_id[d]["phase"]] <= phases[task["phase"]] for d in deps), "future phase dependency")
        require(task["acceptance_cases"] and len(task["acceptance_cases"]) == len(set(task["acceptance_cases"])), "task case duplication")
        require(set(task["acceptance_cases"]) <= all_cases, "unknown task case")
        for case in task["acceptance_cases"]:
            owned[case].add(task["id"])
    require(covered == reqs and all(owned.values()), "uncovered requirement or case")
    visiting, visited = set(), set()

    def visit(ident):
        require(ident not in visiting, "dependency cycle")
        if ident in visited:
            return
        visiting.add(ident)
        for dep in by_id[ident]["depends_on"] + by_id[ident]["integration_dependencies"]:
            visit(dep)
        visiting.remove(ident)
        visited.add(ident)

    for ident in by_id:
        visit(ident)
    order = tasks["suggested_acceptance_order"]
    require(set(order) == set(by_id) and len(order) == 40, "acceptance order coverage")
    positions = {ident: i for i, ident in enumerate(order)}
    require(all(positions[d] < positions[t["id"]] for t in items for d in t["depends_on"] + t["integration_dependencies"]), "acceptance order violates dependency")
    require(positions["T22"] < positions["T21"], "numerical check must precede specification expansion")
    definitions = {c["id"]: c for c in cards["cases"]}
    require(len(definitions) == len(cards["cases"]) == 60 and set(definitions) == all_cases, "acceptance card coverage")
    scenario_rows = re.findall(r"^\| (A\d{2}) \| (.*?) \|$", text, re.M)
    scenarios = dict(scenario_rows)
    require(len(scenario_rows) == len(scenarios), "duplicate plan case")
    require(len(scenarios) == 60 and set(scenarios) == all_cases, "plan case table coverage")
    headings = re.findall(r"^### (R\d{2})：", text, re.M)
    require(len(headings) == 9 and set(headings) == reqs, "plan requirement headings")
    for ident, card in definitions.items():
        require(card["scenario"] == scenarios[ident], "case description differs from plan")
        require(card["primary_acceptance_task"] in owned[ident], "primary acceptance task must own case " + ident)
        require(set(card["linked_tasks"]) == owned[ident], "case task backlinks")
        require(card["status"] == "planned" and not card["actual_evidence"], "planning card has execution evidence")
        require(all(card[k] for k in ("fixture_and_procedure_spec", "independent_expected_observation", "negative_control", "environment_profiles", "required_evidence", "oracle_requirement", "skip_policy")), "incomplete acceptance card")
    for field, ids in (
        ("requirement_reviews", reqs),
        ("original_task_reviews", {f"T{i:02d}" for i in range(1, 37)}),
        ("original_case_reviews", {f"A{i:02d}" for i in range(1, 43)}),
        ("added_task_reviews", {f"T{i:02d}" for i in range(37, 41)}),
        ("added_case_reviews", {f"A{i:02d}" for i in range(43, 61)}),
        ("user_requirement_reviews", {f"U{i:02d}" for i in range(1, 10)}),
        ("regression_reviews", {f"C{i:02d}" for i in range(1, 19)}),
    ):
        records = audit[field]
        require(len(records) == len(ids) and {r["id"] for r in records} == ids, "audit item coverage: " + field)
        require(all(r["assessment"].strip() for r in records), "empty audit assessment")
    require(len(audit["section_reviews"]) == 11 and {s["section"] for s in audit["section_reviews"]} == {str(i) for i in range(1, 12)}, "audit section coverage")
    findings = audit["findings"]
    finding_ids = {f["id"] for f in findings}
    require(len(findings) == 20 and finding_ids == {f"P{i:02d}" for i in range(1, 21)}, "finding coverage")
    require(all(f["status"] == "revised_in_plan" and f["runtime_implemented"] is False and set(f["acceptance_cases"]) <= all_cases for f in findings), "finding incorrectly claims implementation")
    require(all(set(r.get("finding_refs", [])) <= finding_ids for field in ("requirement_reviews", "original_task_reviews") for r in audit[field]), "unknown finding reference")
    return {"requirements": 9, "tasks": 40, "acceptance_scenarios": 60,
            "original_objects_reviewed": 87, "findings_revised_in_plan": 20,
            "dependency_graph": "acyclic", "acceptance_runs": 0}


def self_test(tasks, cards, audit, text):
    mutations = [
        ("duplicate task", lambda t, c, a: t["tasks"].append(copy.deepcopy(t["tasks"][0]))),
        ("unknown dependency", lambda t, c, a: t["tasks"][0]["depends_on"].append("T99")),
        ("dependency cycle", lambda t, c, a: t["tasks"][0]["depends_on"].append("T37")),
        ("unknown requirement", lambda t, c, a: t["tasks"][0]["requirements"].append("R99")),
        ("primary acceptance task", lambda t, c, a: c["cases"][9].update(primary_acceptance_task="T36")),
        ("planning card has execution evidence", lambda t, c, a: c["cases"][0]["actual_evidence"].append("pretend")),
        ("incomplete acceptance card", lambda t, c, a: c["cases"][0].update(independent_expected_observation="")),
        ("audit item coverage", lambda t, c, a: a["original_case_reviews"].pop()),
        ("finding incorrectly claims implementation", lambda t, c, a: a["findings"][0].update(runtime_implemented=True)),
    ]
    for expected, mutate in mutations:
        t, c, a = copy.deepcopy((tasks, cards, audit))
        mutate(t, c, a)
        try:
            validate(t, c, a, text)
        except ValueError as exc:
            require(expected in str(exc), f"self-test {expected}: wrong rejection {exc}")
        else:
            raise ValueError("self-test failed to reject " + expected)
    duplicate_row = next(line for line in text.splitlines() if line.startswith("| A01 |"))
    try:
        validate(tasks, cards, audit, text + "\n" + duplicate_row + "\n")
    except ValueError as exc:
        require("duplicate plan case" in str(exc), "wrong duplicate-plan rejection")
    else:
        raise ValueError("self-test failed to reject duplicate plan case")
    return len(mutations) + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    task_path = DOCS / "research-pipeline-enhancement-2026-11-14.json"
    card_path = HERE / "acceptance_cards.json"
    audit_path = HERE / "item_audit.json"
    plan_path = DOCS / "RESEARCH-PIPELINE-ENHANCEMENT-PLAN-2026-11-14.md"
    tasks, cards, audit = read(task_path), read(card_path), read(audit_path)
    result = validate(tasks, cards, audit, plan_path.read_text(encoding="utf-8"))
    result["validator_negative_controls"] = self_test(tasks, cards, audit, plan_path.read_text(encoding="utf-8")) if args.self_test else 0
    baseline = read(HERE / "baseline.json")
    for name, item in baseline["files"].items():
        require(sha(HERE / name) == item["sha256"], "original snapshot changed")
    for file in (plan_path, DOCS / "AUDIT-RESEARCH-PLAN-2026-11-14.md", ROOT / "README.md"):
        for link in re.findall(r"\]\(([^)]+)\)", file.read_text(encoding="utf-8")):
            if not link.startswith(("http:", "https:", "#", "mailto:")):
                target = (file.parent / link.split("#")[0]).resolve()
                # The linked validation record is created by this successful run.
                require(target.exists() or target == HERE / "validation.json", "missing local link: " + link)
    runtime = read(DOCS / "audit-2026-11-14-palette/validation.json")
    require(all(sha(ROOT / name) == digest for name, digest in runtime["skill_source_sha256"].items()), "runtime source changed")
    require(sha(ROOT / runtime["package"]["file"]) == runtime["package"]["sha256"], "runtime package changed")
    paths = [plan_path, task_path, card_path, audit_path, HERE / "baseline.json", HERE / "before-plan.md", HERE / "before-backlog.json", HERE / "build_acceptance_cards.py", HERE / "validate_plan.py", DOCS / "AUDIT-RESEARCH-PLAN-2026-11-14.md", ROOT / "README.md"]
    result.update({"recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                   "scope": "Planning/document consistency audit only. No new research capability was executed or implemented.",
                   "runtime_source_and_package": "unchanged",
                   "artifact_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}})
    (HERE / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "artifact_sha256"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
