#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-walk the corpus and reconcile against the audit ledger (freshness, zero trust).

An audit ledger is a statement about the directory at audit time; it cannot
prove the directory is still that directory. This re-audits into a scratch dir
with the SAME sampling frame (reusing audit_corpus, so the method is identical)
and compares the corpus fingerprint plus the per-file rel_path/bytes/md5 set.
New, vanished or content-changed files are errors -- the audit must be redone.

Usage:
    python scripts/rescan_corpus.py --root "资料目录" --audit-out output/audit \
        --scratch output/qa/rescan_scratch --out output/qa/rescan.json

Exit 0 = corpus unchanged since audit; exit 2 = drift detected.
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
    ap.add_argument("--root", required=True)
    ap.add_argument("--audit-out", default="output/audit")
    ap.add_argument("--scratch", default="output/qa/rescan_scratch")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exit-zero", action="store_true", help="DEBUG ONLY")
    args = ap.parse_args(argv)
    result = AP.rescan_corpus(args.root, AP.resolve(args.audit_out, "."),
                              AP.resolve(args.scratch, "."))
    out = args.out or AP.resolve("output/qa/rescan.json", ".")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items()
                      if k in ("ok", "fingerprint_match", "errors")},
                     ensure_ascii=False, indent=2))
    if not result["ok"] and not args.exit_zero:
        print(f"RESCAN FAILED: corpus drifted since audit", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())