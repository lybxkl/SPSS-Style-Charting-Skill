#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic two-pass stage-audit ledger validator.

The pipeline requires that after EVERY stage completes, the agent runs at least
two audits from DIFFERENT angles (e.g. a machine/numbers pass and an independent
source-re-read / drift pass) and records them before moving on.  This script
checks the ledger of those audits; it does not perform the audits itself and it
embeds no discipline-specific logic -- angles, samples and checks are whatever
the project declares.

Ledger: JSONL, one record per audit pass (append after each pass)::

    {"stage":"dataset","angle":"machine","evidence":{"commands":[{"cmd":"...","exit":0}]},
     "findings":[{"detail":"...","resolved":true}],"at":"..."}
    {"stage":"dataset","angle":"independent","evidence":{"samples":["rel/path"],"checks":["scope-drift"]},
     "findings":[],"at":"..."}

A stage passes only if it has >=2 records, >=2 distinct angles, every record
carries real evidence (commands with exit codes, or samples, or checks), and no
finding is left unresolved.  Missing required stage, <2 passes, single angle,
empty evidence, or unresolved finding => exit 2.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict


def read_ledger(path: str) -> list[dict]:
    records = []
    with io.open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            records.append(json.loads(line))
    return records


def has_evidence(rec: dict) -> bool:
    ev = rec.get("evidence") or {}
    if not isinstance(ev, dict):
        return False
    cmds = ev.get("commands")
    if isinstance(cmds, list) and cmds:
        return all(isinstance(c, dict) and str(c.get("cmd") or "").strip()
                   and isinstance(c.get("exit"), int) for c in cmds)
    for key in ("samples", "checks"):
        val = ev.get(key)
        if isinstance(val, list) and any(str(v).strip() for v in val):
            return True
    return False


def unresolved(rec: dict) -> list:
    out = []
    for f in rec.get("findings") or []:
        if isinstance(f, dict) and not f.get("resolved", False):
            out.append(f.get("detail") or "(no detail)")
    return out


def check(records: list[dict], required: list[str] | None) -> dict:
    by_stage = defaultdict(list)
    for rec in records:
        stage = str(rec.get("stage") or "").strip()
        if stage:
            by_stage[stage].append(rec)
    result = {"errors": [], "warnings": [], "stages": {}}
    targets = required if required else sorted(by_stage)
    for stage in targets:
        passes = by_stage.get(stage, [])
        info = {"passes": len(passes), "angles": sorted({str(p.get("angle") or "").strip().lower() for p in passes if str(p.get("angle") or "").strip()})}
        result["stages"][stage] = info
        if len(passes) < 2:
            result["errors"].append(f"{stage}: only {len(passes)} audit pass(es); >=2 required")
            continue
        if len(info["angles"]) < 2:
            result["errors"].append(f"{stage}: passes share a single angle {info['angles']}; >=2 distinct angles required")
        for i, p in enumerate(passes):
            if not str(p.get("angle") or "").strip():
                result["errors"].append(f"{stage} pass#{i+1}: missing angle")
            if not has_evidence(p):
                result["errors"].append(f"{stage} pass#{i+1}: no real evidence (commands+exit, samples, or checks)")
            bad = unresolved(p)
            if bad:
                result["errors"].append(f"{stage} pass#{i+1}: unresolved finding(s): {bad[:3]}")
    result["error_count"] = len(result["errors"])
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--ledger", required=True, help="stage_audit.jsonl (one record per pass)")
    ap.add_argument("--require", default=None,
                    help="comma-separated stages that must each have >=2 clean passes (default: all stages in ledger)")
    ap.add_argument("--exit-zero", action="store_true", help="always exit 0 (do not use in CI)")
    args = ap.parse_args(argv)
    required = [s.strip() for s in args.require.split(",") if s.strip()] if args.require else None
    try:
        records = read_ledger(args.ledger)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    result = check(records, required)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["error_count"] and not args.exit_zero:
        print(f"STAGE AUDIT FAILED: {result['error_count']} error(s)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())