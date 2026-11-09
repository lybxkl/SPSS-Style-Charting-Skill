#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create (and optionally apply) a duplicate-file plan from corpus_audit.csv.

The audit script marks every byte-identical file as keeper or duplicate. This
script turns that into a reviewable plan, then moves duplicates into
`<root>/_duplicates/` without deleting them.

Usage:
    python dedupe_corpus.py --audit output/audit/corpus_audit.csv --root "语料目录" --out-dir output/audit
    python dedupe_corpus.py ... --apply
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime


def read_audit(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def unique_destination(dest: str) -> str:
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(dest)
    i = 2
    while os.path.exists(f"{base}__dup{i}{ext}"):
        i += 1
    return f"{base}__dup{i}{ext}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or apply byte-level deduplication.")
    parser.add_argument("--audit", required=True, help="corpus_audit.csv from audit_corpus.py")
    parser.add_argument("--root", required=True, help="corpus root folder")
    parser.add_argument("--out-dir", default=None, help="output folder; default: audit folder")
    parser.add_argument("--apply", action="store_true", help="move duplicates (default: dry run)")
    parser.add_argument("--copy", action="store_true", help="copy instead of move")
    parser.add_argument("--dest-name", default="_duplicates", help="quarantine folder name")
    args = parser.parse_args()

    audit_path = os.path.abspath(args.audit)
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 2
    out_dir = os.path.abspath(args.out_dir or os.path.dirname(audit_path))
    os.makedirs(out_dir, exist_ok=True)
    rows = read_audit(audit_path)
    if not rows:
        print("ERROR: empty audit file", file=sys.stderr)
        return 2

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        group = (row.get("dup_group") or "").strip()
        if group:
            groups[group].append(row)

    plan = []
    for group, items in sorted(groups.items()):
        keep = [r for r in items if r.get("dup_role") == "keeper"]
        if len(keep) != 1:
            # Defensive: if the audit has no keeper, pick the first and warn.
            keep = [items[0]]
            for r in items:
                r["dup_role"] = "keeper" if r is items[0] else "duplicate"
        keeper = keep[0]
        for row in items:
            role = row.get("dup_role")
            if role == "keeper":
                plan.append({
                    "group": group, "action": "keep", "role": role,
                    "file": row["name"], "relpath": row["relpath"],
                    "destination": "", "reason": "keeper by audit rule",
                    "bytes": row.get("bytes", ""), "pages": row.get("pages", ""),
                    "chars": row.get("chars", ""),
                })
                continue
            dest = os.path.join(args.dest_name, row["relpath"])
            plan.append({
                "group": group, "action": "copy" if args.copy else "move",
                "role": "duplicate", "file": row["name"], "relpath": row["relpath"],
                "destination": dest, "reason": f"same MD5 as {keeper['name']}",
                "bytes": row.get("bytes", ""), "pages": row.get("pages", ""),
                "chars": row.get("chars", ""),
            })

    plan_csv = os.path.join(out_dir, "dedupe_plan.csv")
    write_csv(plan_csv, plan, ["group", "action", "role", "file", "relpath",
                               "destination", "reason", "bytes", "pages", "chars"])

    actions = Counter(p["action"] for p in plan)
    print(f"groups: {len(groups)}  actions: {dict(actions)}")
    print(f"plan: {plan_csv}")

    if not args.apply:
        print("dry run; re-run with --apply to move/copy duplicates")
        return 0

    moved = 0
    planned = sum(1 for p in plan if p["action"] in {"move", "copy"})
    for item in plan:
        if item["action"] not in {"move", "copy"}:
            continue
        rel = item["relpath"]
        if os.path.isabs(rel) or ".." in rel.split(os.sep):
            print(f"WARN: unsafe relpath skipped: {rel}", file=sys.stderr)
            continue
        src = os.path.join(root, rel)
        dest = os.path.join(root, item["destination"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        dest = unique_destination(dest)
        try:
            if item["action"] == "copy":
                shutil.copy2(src, dest)
            else:
                shutil.move(src, dest)
            moved += 1
        except Exception as exc:
            print(f"WARN: {rel}: {exc}", file=sys.stderr)
    print(f"applied: {moved} files -> {os.path.join(root, args.dest_name)}")
    if moved < planned:
        print(f"WARN: {planned - moved} planned action(s) were not applied "
              "(already moved, missing, or unsafe)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
