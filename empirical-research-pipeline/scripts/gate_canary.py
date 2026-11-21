#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Meta-audit: prove the gates have teeth (audit the auditors).

A gate that always returns 0 is indistinguishable from no gate. This builds
minimal synthetic fixtures, runs each real gate on a CLEAN copy (must exit 0)
and on a copy with a KNOWN planted error (must exit 2). A gate that misses its
planted error, or false-positives on the clean copy, is reported as broken.

This is the zero-trust principle applied one level up: do not trust that a
checker checks -- make it demonstrate catching a real defect. Run it after
installing/upgrading the skill, or in CI, to confirm the installed gates bite.

Usage:
    python scripts/gate_canary.py --out output/qa/gate_canary.json

Exit 0 = every gate caught its mutation and passed clean; exit 2 = a gate is
broken (missed mutation or false positive). No discipline vocabulary.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable.replace("\\", "/")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _json(path, obj):
    _write(path, json.dumps(obj, ensure_ascii=False))


def run_gate(script, args, cwd):
    proc = subprocess.run([sys.executable, os.path.join(_HERE, script)] + args,
                          cwd=cwd, capture_output=True, text=True, timeout=300)
    return proc.returncode


def canary_scope(root):
    data = os.path.join(root, "analysis.csv")
    scope = os.path.join(root, "scope.json")
    _write(data, "cat\nA\nB\n")
    _json(scope, {"columns": {"cat": {"include": ["A", "B"]}}})
    clean = run_gate("scope_conformance.py", ["--data", data, "--scope", scope,
                                              "--out", os.path.join(root, "s.csv")], root)
    _write(data, "cat\nA\nB\nOUT\n")
    mutated = run_gate("scope_conformance.py", ["--data", data, "--scope", scope,
                                                "--out", os.path.join(root, "s2.csv")], root)
    return clean, mutated


def canary_decisions(root):
    _write(os.path.join(root, "a.txt"), "年龄67岁。")
    text = "年龄67岁。"
    s, e = text.index("67岁"), text.index("67岁") + 3
    review = os.path.join(root, "review.csv")
    _write(review, "rel_path,field,value,alternatives,flags,needs_review\n"
                   "a.txt,age,67,67|71,,false\n")
    dec = os.path.join(root, "decisions.jsonl")
    base = {"id": "D1", "stage": "extract", "target": "a.txt#age", "decision": "value",
            "value": 67, "reason": "原文写明", "evidence": [f"a.txt@{s}-{e}"],
            "quote": "67岁", "confidence": 0.9, "needs_human": False}
    _write(dec, json.dumps(base, ensure_ascii=False) + "\n")
    args = ["--decisions", dec, "--root", root, "--review", review,
            "--out", os.path.join(root, "issues.csv")]
    clean = run_gate("check_decisions.py", args, root)
    base["value"] = 99  # never a candidate
    _write(dec, json.dumps(base, ensure_ascii=False) + "\n")
    mutated = run_gate("check_decisions.py", args, root)
    return clean, mutated


def canary_relation(root):
    _write(os.path.join(root, "person.csv"), "person_id,name\nP1,a\nP2,b\n")
    _write(os.path.join(root, "wave.csv"), "person_id,wave\nP1,1\nP1,2\nP2,1\n")
    reg = os.path.join(root, "registry.json")
    base = {"datasets": [
        {"id": "person", "path": "person.csv", "key": "person_id", "unit": "人"},
        {"id": "wave", "path": "wave.csv", "key": ["person_id", "wave"], "unit": "人-轮"}],
        "joins": [{"left": "person", "right": "wave", "on": "person_id",
                   "how": "left", "expect": "1:N", "result_n": 3}]}
    _json(reg, base)
    args = ["--registry", reg, "--root", root, "--out", os.path.join(root, "r.json")]
    clean = run_gate("relation_conformance.py", args, root)
    base["joins"][0]["expect"] = "1:1"  # fan-out lies about cardinality
    _json(reg, base)
    mutated = run_gate("relation_conformance.py", args, root)
    return clean, mutated


def canary_cleaning(root):
    data = os.path.join(root, "dataset.csv")
    recipe = os.path.join(root, "cleaning.json")
    _write(data, "id,x\n1,a\n2,\n3,b\n")
    base = {"recipe_version": 1, "id_columns": ["id"], "max_drop_fraction": 0.5,
            "na_values": [""], "steps": [{"op": "drop_rows_if_missing",
                                          "columns": ["x"], "mode": "any", "reason": "m"}]}
    _json(recipe, base)
    args = ["--dataset", data, "--recipe", recipe, "--out", os.path.join(root, "c")]
    clean = run_gate("clean_data.py", args, root)
    base["max_drop_fraction"] = 0.0  # guard must trip on the declared drop
    _json(recipe, base)
    mutated = run_gate("clean_data.py", args, root)
    return clean, mutated


def canary_evidence(root):
    _write(os.path.join(root, "materials", "a.txt"), "alpha beta gamma")
    ev = os.path.join(root, "evidence.jsonl")
    _write(ev, json.dumps({"rel_path": "materials/a.txt",
                           "evidence": ["x=alpha beta@0-10"]}, ensure_ascii=False) + "\n")
    args = ["--evidence", ev, "--root", root, "--out", os.path.join(root, "e.json")]
    clean = run_gate("evidence_replay.py", args, root)
    _write(ev, json.dumps({"rel_path": "materials/a.txt",
                           "evidence": ["x=alpha@100-105"]}, ensure_ascii=False) + "\n")
    mutated = run_gate("evidence_replay.py", args, root)
    return clean, mutated


def canary_stage_audit(root):
    import hashlib
    scripts = _HERE.replace("\\", "/")
    data = os.path.join(root, "data.csv")
    _write(data, "cat\nA\n")
    _write(os.path.join(root, "scope.json"), '{"columns":{"cat":{"include":["A"]}}}')
    _write(os.path.join(root, "materials", "a.txt"), "alpha beta")
    sha = hashlib.sha256(open(data, "rb").read()).hexdigest()
    led = os.path.join(root, "stage_audit.jsonl")
    cmd = f'"{PY}" "{scripts}/scope_conformance.py" --data data.csv --scope scope.json --out s.csv'
    p1 = {"stage": "dataset", "angle": "machine", "method": "recompute",
          "artifacts": {"data.csv": sha},
          "evidence": {"commands": [{"cmd": cmd, "exit": 0}]}, "findings": []}
    p2 = {"stage": "dataset", "angle": "independent", "method": "reread",
          "artifacts": {"data.csv": sha},
          "evidence": {"samples": [{"rel_path": "materials/a.txt", "span": [0, 5],
                                    "quote": "alpha"}]}, "findings": []}
    _write(led, json.dumps(p1) + "\n" + json.dumps(p2) + "\n")
    args = ["--ledger", led, "--require", "dataset", "--root", root, "--no-recompute"]
    clean = run_gate("stage_audit.py", args, root)
    # plant an out-of-scope category: the real checker now exits 2, claim stays 0
    _write(data, "cat\nOUT\n")
    mutated = run_gate("stage_audit.py", args, root)
    return clean, mutated


def canary_rescan(root):
    corpus = os.path.join(root, "materials")
    _write(os.path.join(corpus, "a.txt"), "hello research material text")
    audit_out = os.path.join(root, "output", "audit")
    run_gate("audit_corpus.py", ["--root", corpus, "--out-dir", audit_out, "--min-chars", "1"], root)
    args = ["--root", corpus, "--audit-out", audit_out,
            "--scratch", os.path.join(root, "scratch"), "--out", os.path.join(root, "r.json")]
    clean = run_gate("rescan_corpus.py", args, root)
    _write(os.path.join(corpus, "b.txt"), "a newly added material file")
    mutated = run_gate("rescan_corpus.py", args, root)
    return clean, mutated


def canary_cleaning_replay(root):
    data = os.path.join(root, "dataset.csv")
    recipe = os.path.join(root, "cleaning.json")
    audited = os.path.join(root, "cleaned")
    _write(data, "id,x\n1,a\n2,\n3,b\n")
    _json(recipe, {"recipe_version": 1, "id_columns": ["id"], "max_drop_fraction": 0.5,
                   "na_values": [""], "steps": [{"op": "drop_rows_if_missing",
                                                 "columns": ["x"], "mode": "any", "reason": "m"}]})
    run_gate("clean_data.py", ["--dataset", data, "--recipe", recipe, "--out", audited], root)
    args = ["--dataset", data, "--recipe", recipe, "--audited-out", audited,
            "--scratch", os.path.join(root, "scratch"), "--out", os.path.join(root, "cr.json")]
    clean = run_gate("cleaning_replay.py", args, root)
    with io.open(os.path.join(audited, "clean_dataset.csv"), "a", encoding="utf-8") as fh:
        fh.write("9,z\n")
    mutated = run_gate("cleaning_replay.py", args, root)
    return clean, mutated


def canary_temporal(root):
    data = os.path.join(root, "data.csv")
    scope = os.path.join(root, "scope.json")
    _write(data, "cat,date\nA,2021-06-01\n")
    _json(scope, {"columns": {"cat": {"include": ["A"]}},
                  "temporal": [{"col": "date", "min": "2021-01", "max": "2021-12"}]})
    args = ["--data", data, "--scope", scope, "--out", os.path.join(root, "s.csv")]
    clean = run_gate("scope_conformance.py", args, root)
    _write(data, "cat,date\nA,2025-01-01\n")
    mutated = run_gate("scope_conformance.py", args, root)
    return clean, mutated


CANARIES = {"scope_conformance": canary_scope, "check_decisions": canary_decisions,
            "relation_conformance": canary_relation, "clean_data": canary_cleaning,
            "evidence_replay": canary_evidence, "stage_audit": canary_stage_audit,
            "rescan_corpus": canary_rescan, "cleaning_replay": canary_cleaning_replay,
            "temporal": canary_temporal}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--out", default="output/qa/gate_canary.json")
    ap.add_argument("--only", default=None, help="comma-separated subset of canaries")
    args = ap.parse_args(argv)
    selected = [s.strip() for s in args.only.split(",")] if args.only else list(CANARIES)
    results = {}
    broken = []
    for name in selected:
        fn = CANARIES.get(name)
        if not fn:
            broken.append(f"{name}: unknown canary")
            continue
        with tempfile.TemporaryDirectory() as root:
            try:
                clean, mutated = fn(root)
            except Exception as exc:                          # noqa: BLE001
                results[name] = {"error": str(exc)}
                broken.append(f"{name}: fixture failed: {exc}")
                continue
        caught = (clean == 0 and mutated == 2)
        results[name] = {"clean_exit": clean, "mutated_exit": mutated, "caught": caught}
        if not caught:
            broken.append(f"{name}: clean={clean} mutated={mutated} (expected 0/2)")
    report = {"ok": not broken, "broken": broken, "gates": results}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if broken:
        print(f"GATE CANARY FAILED: {len(broken)} gate(s) broken", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())