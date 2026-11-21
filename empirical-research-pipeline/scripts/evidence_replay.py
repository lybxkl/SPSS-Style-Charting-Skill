#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-verify EVERY evidence line against the re-read source (zero trust).

references/09 makes ``verify_evidence`` the single implementation of the
span/snippet invariant, but that invariant was only exercised on fixtures at
test time. This turns it into a delivery gate: it walks the whole
``evidence.jsonl``, re-reads each document the way the extractor anchored
offsets (binary via text_extract, CRLF-normalised), and checks every emitted
evidence line. Nothing is trusted from the extraction run's own report.

The receipt binds the re-verification to the extractor bytes (extract_lib.py +
text_extract.py sha256) and the profile sha256, so a later run with a different
parser cannot silently inherit a "verified" stamp.

Usage:
    python scripts/evidence_replay.py --evidence output/coding/evidence.jsonl \
        --root "资料目录" [--dataset output/coding/dataset.csv] \
        [--profile draft/fields.json] --out output/qa/evidence_replay.json

Exit 0 = every line verified; exit 2 = any failure / missing source / empty input.
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
import extract_lib as EL


def replay(evidence_path: str, root: str, dataset_path: str | None) -> dict:
    rows = []
    with io.open(evidence_path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    errors: list[str] = []
    if not rows:
        return {"ok": False, "errors": ["evidence.jsonl has no records"],
                "documents": 0, "lines_checked": 0, "lines_failed": 0}

    data_index = {}
    if dataset_path and os.path.isfile(dataset_path):
        for r in AP.read_table(dataset_path):
            rel = r.get("rel_path") or r.get("relpath") or ""
            if rel:
                data_index[rel.replace("\\", "/")] = r

    checked = failed = documents = 0
    failures: list[dict] = []
    for rec in rows:
        rel = rec.get("rel_path") or ""
        documents += 1
        full = AP.resolve(rel, root)
        if not os.path.isfile(full):
            errors.append(f"source missing: {rel}")
            failures.append({"rel_path": rel, "error": "source missing"})
            continue
        try:
            text = AP.read_source_text(full)
        except Exception as exc:                              # noqa: BLE001
            errors.append(f"cannot re-read {rel}: {exc}")
            failures.append({"rel_path": rel, "error": str(exc)})
            continue
        for ev in rec.get("evidence") or []:
            checked += 1
            if not EL.verify_evidence(text, ev):
                failed += 1
                field = ev.split("=", 1)[0]
                errors.append(f"{rel}: evidence line failed re-verification: {ev[:80]}")
                failures.append({"rel_path": rel, "field": field, "line": ev})
        # cross-check dataset values against the re-read span where a span exists
        if rel.replace("\\", "/") in data_index:
            drow = data_index[rel.replace("\\", "/")]
            for name, f in (rec.get("fields") or {}).items():
                span = f.get("span")
                if not span or f.get("value") is None:
                    continue
                # span must be valid in the re-read text; raw is extractor
                # output already anchored by the verified evidence line, so do
                # not require raw⊆span (kv_block raw can carry the label line).
                ok, reason = AP.verify_span_quote(text, span, None)
                if not ok:
                    failed += 1
                    errors.append(f"{rel}#{name}: field span failed: {reason}")
                    failures.append({"rel_path": rel, "field": name, "error": reason})
                cell = drow.get(name)
                if cell not in (None, "") and not _same(cell, f.get("value")):
                    errors.append(f"{rel}#{name}: dataset cell {cell!r} != evidence value {f.get('value')!r}")
                    failures.append({"rel_path": rel, "field": name, "error": "value mismatch"})
    if data_index:
        ev_rels = {str(rec.get("rel_path") or "").replace("\\", "/") for rec in rows}
        uncovered = sorted(set(data_index) - ev_rels)
        if uncovered:
            errors.append(f"{len(uncovered)} dataset row(s) have no evidence record "
                          f"(coverage gap): {uncovered[:10]}")
    return {"ok": not errors, "errors": errors, "documents": documents,
            "lines_checked": checked, "lines_failed": failed, "failures": failures[:200]}


def _same(a, b) -> bool:
    try:
        return float(str(a).strip()) == float(str(b).strip())
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if not os.path.isfile(args.evidence):
        print(f"ERROR: evidence file not found: {args.evidence}", file=sys.stderr)
        return 2
    result = replay(args.evidence, args.root, args.dataset)
    result["extractor_sha256"] = {
        "extract_lib.py": AP.sha256_file(os.path.join(_HERE, "extract_lib.py")),
        "text_extract.py": AP.sha256_file(os.path.join(_HERE, "text_extract.py")),
    }
    if args.profile and os.path.isfile(args.profile):
        result["profile_sha256"] = AP.sha256_file(args.profile)
    out = args.out or os.path.join(os.path.dirname(args.evidence), "evidence_replay.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"evidence: {result['documents']} docs, {result['lines_checked']} lines, "
          f"{result['lines_failed']} failed -> {out}")
    if not result["ok"]:
        for e in result["errors"][:8]:
            print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())