#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Maintain the *implementation* ledger under ``docs/implementation/``.

The planning audit under ``docs/plan-audit-2026-11-14/`` is frozen evidence of
the design phase: its validator insists every task is still ``planned`` and that
no source file changed.  It therefore cannot be used as a completion gate for
the implementation.  This tool copies the task/acceptance *definitions* out of
the frozen plan once, then keeps real progress in a separate tree:

    docs/implementation/TASK-STATUS.json
    docs/implementation/ACCEPTANCE-RESULTS.json

Usage (from the repository root):

    python tools/impl_ledger.py init       # create the ledger from the plan
    python tools/impl_ledger.py status     # print a compact progress table
    python tools/impl_ledger.py set T02 done --note "..." \
        --evidence path/to/log.json
    python tools/impl_ledger.py accept A02 passed --note "..." \
        --evidence docs/implementation/verification/A02/run.log
    python tools/impl_ledger.py check      # exit 1 on ledger inconsistencies

``init`` never overwrites an existing ledger (use ``--force`` explicitly only
when the implementation tree really is being rebuilt).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLAN = REPO / "docs" / "research-pipeline-enhancement-2026-11-14.json"
CARDS = REPO / "docs" / "plan-audit-2026-11-14" / "acceptance_cards.json"
OUT = REPO / "docs" / "implementation"
TASKS = OUT / "TASK-STATUS.json"
ACCEPT = OUT / "ACCEPTANCE-RESULTS.json"
VERIFY = OUT / "verification"

TASK_STATES = ("planned", "in_progress", "implemented", "verified", "blocked",
               "partial", "dropped")
ACCEPT_STATES = ("unassessed", "passed", "failed", "not_applicable", "blocked",
                 "partial")


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(
        timespec="seconds")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")


def init(force: bool = False) -> int:
    plan = load(PLAN)
    cards = load(CARDS)
    if TASKS.exists() and not force:
        print(f"refusing to overwrite {TASKS.relative_to(REPO)} (use --force)")
        return 2
    tasks = {}
    for t in plan["tasks"]:
        tasks[t["id"]] = {
            "id": t["id"],
            "phase": t["phase"],
            "requirements": t["requirements"],
            "title": t["title"],
            "planned_status": t["status"],           # frozen plan value
            "depends_on": t["depends_on"],
            "integration_dependencies": t["integration_dependencies"],
            "acceptance_cases": t["acceptance_cases"],
            "planned_deliverables": t["planned_deliverables"],
            "done_when": t["done_when"],
            # ---- real implementation fields ----
            "state": "planned",
            "changes": [],          # files/modules actually touched
            "verification": [],     # commands run + evidence paths
            "gaps": [],             # honest remaining limitations
            "updated_at": None,
        }
    save(TASKS, {
        "schema_version": 1,
        "kind": "implementation_ledger_not_a_plan",
        "plan_revision": plan.get("plan_revision"),
        "baseline_commit": plan.get("baseline_commit"),
        "created_at": now(),
        "note": ("Real implementation progress. The frozen planning audit under "
                 "docs/plan-audit-2026-11-14/ keeps its own planned-state "
                 "records and is not rewritten by this ledger."),
        "tasks": tasks,
    })
    cases = {}
    for c in cards["cases"]:
        cases[c["id"]] = {
            "id": c["id"],
            "scenario": c.get("scenario", ""),
            "primary_task": c.get("primary_acceptance_task"),
            "linked_tasks": c.get("linked_tasks", []),
            "fixture_spec": c.get("fixture_and_procedure_spec"),
            "expectation": c.get("independent_expected_observation"),
            "negative_control": c.get("negative_control"),
            "environment_profiles": c.get("environment_profiles", []),
            "required_evidence": c.get("required_evidence", []),
            "skip_policy": c.get("skip_policy"),
            "design_state": c.get("status", "design"),
            # ---- real execution fields ----
            "result": "unassessed",
            "runs": [],
            "evidence": [],
            "note": None,
            "updated_at": None,
        }
    save(ACCEPT, {
        "schema_version": 1,
        "kind": "acceptance_results_not_design_cards",
        "plan_revision": cards.get("plan_revision"),
        "created_at": now(),
        "note": ("Design cards live in docs/plan-audit-2026-11-14/"
                 "acceptance_cards.json.  This file records what was actually "
                 "executed; unassessed is not a pass."),
        "cases": cases,
    })
    VERIFY.mkdir(parents=True, exist_ok=True)
    print(f"wrote {TASKS.relative_to(REPO)} ({len(tasks)} tasks)")
    print(f"wrote {ACCEPT.relative_to(REPO)} ({len(cases)} scenarios)")
    return 0


def _load_tasks() -> dict:
    if not TASKS.exists():
        raise SystemExit("run `python tools/impl_ledger.py init` first")
    return load(TASKS)


def set_task(tid: str, state: str, note: str | None, evidence: list[str],
             gap: str | None) -> int:
    if state not in TASK_STATES:
        raise SystemExit(f"unknown state {state!r}; expected {TASK_STATES}")
    doc = _load_tasks()
    t = doc["tasks"].get(tid)
    if t is None:
        raise SystemExit(f"unknown task {tid}")
    t["state"] = state
    t["updated_at"] = now()
    if note:
        t["changes"].append({"at": now(), "note": note})
    for e in evidence:
        t["verification"].append({"at": now(), "evidence": e})
    if gap:
        t["gaps"].append({"at": now(), "gap": gap})
    save(TASKS, doc)
    print(f"{tid}: {state}")
    return 0


def accept(cid: str, result: str, note: str | None, evidence: list[str],
           command: str | None, env: str | None) -> int:
    if result not in ACCEPT_STATES:
        raise SystemExit(f"unknown result {result!r}; expected {ACCEPT_STATES}")
    if not ACCEPT.exists():
        raise SystemExit("run `python tools/impl_ledger.py init` first")
    doc = load(ACCEPT)
    case = doc["cases"].get(cid)
    if case is None:
        raise SystemExit(f"unknown scenario {cid}")
    case["result"] = result
    case["updated_at"] = now()
    if note:
        case["note"] = note
    for e in evidence:
        if not (REPO / e).exists() and not Path(e).exists():
            raise SystemExit(f"evidence path does not exist: {e}")
        case["evidence"].append(e)
    if command or env:
        case["runs"].append({"at": now(), "command": command, "environment": env,
                             "result": result})
    save(ACCEPT, doc)
    print(f"{cid}: {result}")
    return 0


def status() -> int:
    doc = _load_tasks()
    acc = load(ACCEPT) if ACCEPT.exists() else {"cases": {}}
    counts: dict[str, int] = {}
    for t in doc["tasks"].values():
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    print("TASKS", dict(sorted(counts.items())))
    for tid in sorted(doc["tasks"]):
        t = doc["tasks"][tid]
        mark = {"verified": "OK ", "implemented": "IMP", "in_progress": ".. ",
                "partial": "PRT", "blocked": "BLK", "planned": "   ",
                "dropped": "DRP"}.get(t["state"], "?  ")
        gaps = f"  gaps={len(t['gaps'])}" if t["gaps"] else ""
        print(f"{mark} {tid} {t['phase']} {t['title']}{gaps}")
    acounts: dict[str, int] = {}
    for c in acc["cases"].values():
        acounts[c["result"]] = acounts.get(c["result"], 0) + 1
    print("SCENARIOS", dict(sorted(acounts.items())))
    return 0


def check() -> int:
    doc = _load_tasks()
    acc = load(ACCEPT)
    problems: list[str] = []
    for tid, t in doc["tasks"].items():
        if t["state"] in ("verified", "implemented") and not t["verification"]:
            problems.append(f"{tid}: {t['state']} without verification evidence")
        for d in t["depends_on"]:
            if doc["tasks"][d]["state"] in ("planned", "dropped") and \
                    t["state"] in ("implemented", "verified"):
                problems.append(f"{tid}: {t['state']} but depends_on {d} is "
                                f"{doc['tasks'][d]['state']}")
    for cid, c in acc["cases"].items():
        if c["result"] == "passed" and not c["evidence"]:
            problems.append(f"{cid}: passed without evidence")
    for p in problems:
        print("INCONSISTENT:", p)
    if problems:
        return 1
    print("OK: ledger is internally consistent")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init")
    p_init.add_argument("--force", action="store_true")
    sub.add_parser("status")
    sub.add_parser("check")
    p_set = sub.add_parser("set")
    p_set.add_argument("task")
    p_set.add_argument("state")
    p_set.add_argument("--note")
    p_set.add_argument("--evidence", action="append", default=[])
    p_set.add_argument("--gap")
    p_acc = sub.add_parser("accept")
    p_acc.add_argument("case")
    p_acc.add_argument("result")
    p_acc.add_argument("--note")
    p_acc.add_argument("--evidence", action="append", default=[])
    p_acc.add_argument("--command")
    p_acc.add_argument("--env")
    args = ap.parse_args(argv)

    if args.cmd == "init":
        return init(force=args.force)
    if args.cmd == "status":
        return status()
    if args.cmd == "check":
        return check()
    if args.cmd == "set":
        return set_task(args.task, args.state, args.note, args.evidence, args.gap)
    if args.cmd == "accept":
        return accept(args.case, args.result, args.note, args.evidence,
                      args.command, args.env)
    raise SystemExit(2)


if __name__ == "__main__":
    sys.exit(main())
