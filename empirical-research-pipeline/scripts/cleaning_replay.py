#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replay a cleaning recipe and reconcile the fingerprint chain (zero trust).

"Review by replay" was possible by construction but had no packaged command.
This re-runs clean_data on the same dataset + recipe into a scratch dir,
compares clean_dataset.csv bytes and the cleaning_log.jsonl sha_in/sha_out
chain against the audited output, and enumerates EVERY dropped id (input ids
minus output ids) -- not the 20-row sample the log keeps -- so the full discard
set is visible without trusting the log.

Usage:
    python scripts/cleaning_replay.py --dataset output/coding/dataset.csv \
        --recipe draft/cleaning.json --audited-out output/cleaning \
        --scratch output/qa/cleaning_scratch --out output/qa/cleaning_replay.json

Exit 0 = replay matches; exit 2 = divergence.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import audit_probe as AP


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--audited-out", default="output/cleaning")
    ap.add_argument("--scratch", default="output/qa/cleaning_scratch")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exit-zero", action="store_true", help="DEBUG ONLY")
    args = ap.parse_args(argv)
    result = AP.replay_cleaning(args.dataset, args.recipe,
                                AP.resolve(args.audited_out, "."),
                                AP.resolve(args.scratch, "."))
    out = args.out or AP.resolve("output/qa/cleaning_replay.json", ".")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"cleaning replay: ok={result['ok']} dropped={result.get('n_dropped', 0)} -> {out}")
    if not result["ok"] and not args.exit_zero:
        for e in result["errors"]:
            print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())