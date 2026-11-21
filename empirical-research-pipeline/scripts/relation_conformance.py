#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Submission-tier relation/unit conformance (zero trust, registry-driven).

A cross-dataset relation is a CLAIM, not a foreign key the engine invents. The
registry declares each dataset's unit + key and each join's expected
cardinality; this recomputes key uniqueness, orphan keys, fan-out and the
resulting row accounting from the tables themselves, so a fabricated key or a
granularity-shifting join (person-period merged into person, many-to-many
fan-out inflating N) cannot pass silently. Complements the archive-tier
entities.py join ledger with a lightweight check usable before statistics.

Registry shape (extends research_registry.json)::

    {"datasets":[{"id":"person","path":"data/person.csv","key":"person_id","unit":"一个人"}],
     "joins":[{"left":"person","right":"wave","on":"person_id","how":"left",
               "expect":"1:N","result_n":120,"unit":"一个人的一次测量"}]}

Usage:
    python scripts/relation_conformance.py --registry research_registry.json \
        --root . --out output/qa/relation_conformance.json

Exit 0 = conformant; exit 2 = any error. No discipline vocabulary.
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
    ap.add_argument("--registry", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exit-zero", action="store_true", help="DEBUG ONLY")
    args = ap.parse_args(argv)
    path = AP.resolve(args.registry, args.root)
    if not os.path.isfile(path):
        print(f"ERROR: registry not found: {path}", file=sys.stderr)
        return 2
    registry = json.loads(open(path, encoding="utf-8").read())
    result = AP.check_relations(registry, args.root)
    out = args.out or AP.resolve("output/qa/relation_conformance.json", args.root)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"] and not args.exit_zero:
        print(f"RELATION FAILED: {len(result['errors'])} error(s)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())