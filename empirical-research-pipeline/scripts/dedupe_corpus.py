#!/usr/bin/env python3
"""Turn the audit duplicate report into a keeper/duplicate plan, then apply it.

Usage:
    python dedupe_corpus.py --audit output/audit/corpus_files.csv --root <dir>
        [--out-dir <dir>] [--dest-name _duplicates] [--copy] [--apply]
    python dedupe_corpus.py --undo output/audit/move_log.csv

Safety rules:
    * The keeper must still exist on disk, otherwise the whole group is skipped
      and nothing is moved (a missing keeper means the duplicate is the only copy).
    * Every applied move/copy is written to move_log.csv with src/dest/action/status,
      so `--undo` can move files back and remove verified copies.
    * `--apply` returns 2 when any file failed, was skipped, or a conflict
      remains, so a partial run is never reported as success.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime

# Stamped into the run output so an artefact names the code that made it.
SCRIPT_VERSION = "2.0.0"

PLAN_FIELDS = [
    "group", "action", "role", "file", "rel_path", "relpath", "destination",
    "reason", "bytes", "pages", "chars", "chars_effective", "md5", "md5_ok",
    "exists",
]
LOG_FIELDS = ["group", "src", "dest", "action", "status", "reason"]


def read_csv(path: str) -> tuple[list[dict], list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def md5_file(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relpath(rel: str, root: str) -> str | None:
    """Resolve a CSV relative path under root, rejecting traversal/absolute paths."""
    rel = (rel or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return None
    path = os.path.normpath(os.path.join(root, *rel.split("/")))
    base = os.path.realpath(root)
    real = os.path.realpath(path)
    try:
        if os.path.commonpath([real, base]) != base:
            return None
    except ValueError:
        return None
    return path


def unique_destination(dest: str) -> str:
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(dest)
    index = 2
    while os.path.exists(f"{base}__dup{index}{ext}"):
        index += 1
    return f"{base}__dup{index}{ext}"


def rel_of(row: dict) -> str:
    return (row.get("rel_path") or row.get("relpath") or "").strip()


def build_plan(groups: dict, root: str, dest_name: str, copy_mode: bool):
    """Create plan rows; a group whose keeper is missing is marked action=skip."""
    plan: list[dict] = []
    skipped_groups = 0
    for group, rows in groups.items():
        keepers = [row for row in rows if (row.get("dup_role") or "").strip() == "keeper"]
        if len(keepers) != 1:
            print(f"warning: group {group} has {len(keepers)} keepers; "
                  "using the first row as keeper", file=sys.stderr)
            keepers = [rows[0]]
        keeper = keepers[0]
        keeper_rel = rel_of(keeper)
        keeper_path = safe_relpath(keeper_rel, root) if keeper_rel else None
        keeper_ok = bool(keeper_path and os.path.isfile(keeper_path))
        if not keeper_ok:
            skipped_groups += 1
            print(f"warning: group {group} keeper missing on disk: {keeper_rel}; "
                  "skipping the whole group", file=sys.stderr)
        keeper_reason = "keeper by audit rule" if keeper_ok else "keeper missing on disk"
        plan.append({
            "group": group, "action": "keep" if keeper_ok else "skip",
            "role": "keeper", "file": keeper.get("name", ""),
            "rel_path": keeper_rel, "relpath": keeper_rel, "destination": "",
            "reason": keeper_reason, "bytes": keeper.get("bytes", ""),
            "pages": keeper.get("pages", ""), "chars": keeper.get("chars", ""),
            "chars_effective": keeper.get("chars_effective", ""),
            "md5": keeper.get("md5", ""), "md5_ok": "",
            "exists": "yes" if keeper_ok else "no",
        })
        for row in rows:
            if row is keeper:
                continue
            rel = rel_of(row)
            src = safe_relpath(rel, root) if rel else None
            exists = bool(src and os.path.isfile(src))
            md5_ok = ""
            if exists and row.get("md5"):
                try:
                    md5_ok = "yes" if md5_file(src) == row["md5"] else "no"
                except OSError:
                    md5_ok = "no"
            if not keeper_ok:
                action = "skip"
                reason = "keeper missing on disk"
            elif not exists:
                action = "skip"
                reason = "duplicate missing on disk"
            elif md5_ok == "no":
                action = "skip"
                reason = "MD5 changed since audit"
            else:
                action = "copy" if copy_mode else "move"
                reason = f"same MD5 as {keeper.get('name', '')}"
            plan.append({
                "group": group, "action": action, "role": "duplicate",
                "file": row.get("name", ""), "rel_path": rel, "relpath": rel,
                "destination": os.path.join(dest_name, rel) if action in {"copy", "move"} else "",
                "reason": reason, "bytes": row.get("bytes", ""),
                "pages": row.get("pages", ""), "chars": row.get("chars", ""),
                "chars_effective": row.get("chars_effective", ""),
                "md5": row.get("md5", ""), "md5_ok": md5_ok,
                "exists": "yes" if exists else "no",
            })
    return plan, skipped_groups


def apply_plan(plan: list[dict], root: str, dest_name: str, log_path: str) -> dict:
    """Move/copy each duplicate, logging every attempt. Re-checks the keeper."""
    keeper_ok: dict[str, bool] = {}
    for row in plan:
        if row["role"] == "keeper":
            keeper_ok[row["group"]] = row["exists"] == "yes"
    counts = Counter()
    log: list[dict] = []
    for row in plan:
        if row["action"] not in {"copy", "move"}:
            if row["action"] == "skip":
                log.append({
                    "group": row["group"], "src": row["rel_path"], "dest": "",
                    "action": "skip", "status": "skipped", "reason": row["reason"],
                })
                counts["skipped"] += 1
            continue
        group = row["group"]
        src = safe_relpath(row["rel_path"], root)
        dest = safe_relpath(row["destination"], root)
        status, reason = "", ""
        if not keeper_ok.get(group, False):
            status, reason = "skipped", "keeper missing on disk"
        elif not src or not os.path.isfile(src):
            status, reason = "failed", "source missing"
        elif not dest:
            status, reason = "failed", "unsafe destination"
        elif row.get("md5") and not row.get("md5_ok"):
            try:
                ok = md5_file(src) == row["md5"]
            except OSError as exc:
                ok = False
                reason = f"cannot hash: {type(exc).__name__}"
            if not ok:
                status = "failed"
                reason = reason or "MD5 changed since audit"
        if status:
            log.append({"group": group, "src": src or row["rel_path"], "dest": dest or "",
                        "action": row["action"], "status": status, "reason": reason})
            counts["failed" if status == "failed" else "skipped"] += 1
            continue
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            final_dest = unique_destination(dest)
            if row["action"] == "copy":
                shutil.copy2(src, final_dest)
                status = "copied"
            else:
                shutil.move(src, final_dest)
                status = "moved"
            log.append({"group": group, "src": src, "dest": final_dest,
                        "action": row["action"], "status": status, "reason": row["reason"]})
            counts[status] += 1
        except OSError as exc:
            log.append({"group": group, "src": src, "dest": dest,
                        "action": row["action"], "status": "failed",
                        "reason": f"{type(exc).__name__}: {exc}"[:200]})
            counts["failed"] += 1
    write_csv(log_path, log, LOG_FIELDS)
    counts["logged"] = len(log)
    return counts


def undo(log_path: str) -> int:
    """Reverse the applied plan: move `move` rows back, delete verified `copy` rows.

    A copy is only removed when src and dest still have the same MD5; anything
    that cannot be verified is kept and reported as a conflict.
    """
    if not os.path.isfile(log_path):
        print(f"error: --undo log not found: {log_path}", file=sys.stderr)
        return 2
    rows, fields = read_csv(log_path)
    required = {"src", "dest", "action", "status"}
    missing = required - set(fields)
    if missing:
        print(f"error: {log_path} lacks column(s): {', '.join(sorted(missing))}", file=sys.stderr)
        print(f"columns found: {', '.join(fields)}", file=sys.stderr)
        return 2
    counts = Counter()
    for row in rows:
        action = row.get("action")
        if action not in ("move", "copy"):
            continue
        if row.get("status") not in ("moved", "copied"):
            continue
        src, dest = row.get("src", ""), row.get("dest", "")
        counts["entries"] += 1
        if not os.path.isfile(dest):
            print(f"warning: applied file no longer exists: {dest}", file=sys.stderr)
            counts["skipped"] += 1
            continue
        if action == "copy":
            if not os.path.isfile(src):
                print(f"warning: cannot verify copy, source missing: {src}", file=sys.stderr)
                counts["conflict"] += 1
                continue
            try:
                same = md5_file(src) == md5_file(dest)
            except OSError as exc:
                print(f"error: cannot hash copy pair {src}: {exc}", file=sys.stderr)
                counts["failed"] += 1
                continue
            if not same:
                print(f"warning: refusing to delete changed copy: {dest}", file=sys.stderr)
                counts["conflict"] += 1
                continue
            try:
                os.remove(dest)
                counts["removed"] += 1
            except OSError as exc:
                print(f"error: cannot remove copy {dest}: {exc}", file=sys.stderr)
                counts["failed"] += 1
            continue
        # action == "move": put the original file back.
        if os.path.exists(src):
            print(f"warning: refusing to overwrite restored file: {src}", file=sys.stderr)
            counts["conflict"] += 1
            continue
        try:
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.move(dest, src)
            counts["restored"] += 1
        except OSError as exc:
            print(f"error: cannot restore {dest}: {exc}", file=sys.stderr)
            counts["failed"] += 1
    if not counts["entries"]:
        print("undo: nothing to undo (log had no move/copy entries)", file=sys.stderr)
        return 2
    print("undo: " + ", ".join(
        f"{key}={counts[key]}" for key in ("restored", "removed", "conflict", "skipped")))
    return 2 if counts["conflict"] or counts["failed"] or counts["skipped"] else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Plan and apply duplicate handling from the audit CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 ok, 2 parameter error / failed or skipped files.",
    )
    print(f"dedupe_corpus.py {SCRIPT_VERSION}", file=sys.stderr)
    ap.add_argument("--audit", help="corpus_files.csv produced by audit_corpus.py")
    ap.add_argument("--root", help="corpus root used by the audit")
    ap.add_argument("--out-dir", help="output directory (default: the audit folder)")
    ap.add_argument("--apply", action="store_true", help="execute the plan")
    ap.add_argument("--copy", action="store_true", help="copy instead of move")
    ap.add_argument("--dest-name", default="_duplicates", help="quarantine folder name")
    ap.add_argument("--undo", help="reverse move_log.csv: move files back, "
                                   "delete copies whose MD5 still matches the source")
    args = ap.parse_args(argv)

    if args.undo:
        return undo(args.undo)
    if not args.audit or not args.root:
        print("error: --audit and --root are required", file=sys.stderr)
        return 2
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"error: --root is not a directory: {args.root}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.audit):
        print(f"error: --audit not found: {args.audit}", file=sys.stderr)
        return 2
    dest_name = args.dest_name.strip().replace("\\", "/").strip("/")
    if not dest_name or dest_name.startswith("..") or "/" in dest_name:
        print("error: --dest-name must be a single folder name", file=sys.stderr)
        return 2
    out_dir = os.path.abspath(args.out_dir or os.path.dirname(os.path.abspath(args.audit)))
    os.makedirs(out_dir, exist_ok=True)

    rows, fields = read_csv(args.audit)
    if not rows:
        print("error: audit CSV has no data rows", file=sys.stderr)
        print(f"columns found: {', '.join(fields)}", file=sys.stderr)
        return 2
    missing = {"dup_group", "dup_role"} - set(fields)
    if missing:
        print(f"error: audit CSV lacks column(s): {', '.join(sorted(missing))}", file=sys.stderr)
        print(f"columns found: {', '.join(fields)}", file=sys.stderr)
        return 2
    if not any(rel_of(row) for row in rows):
        print("error: audit CSV has neither rel_path nor relpath", file=sys.stderr)
        print(f"columns found: {', '.join(fields)}", file=sys.stderr)
        return 2

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        group = (row.get("dup_group") or "").strip()
        if group:
            groups[group].append(row)
    if not groups:
        # Nothing to dedupe is a result, not a failure: a clean corpus is what we
        # want, and returning 2 made a documented step look broken on any corpus
        # without duplicates.  Still write an empty plan so downstream steps can
        # tell "ran and found nothing" from "never ran".
        plan_path = os.path.join(out_dir, "dedupe_plan.csv")
        write_csv(plan_path, [], PLAN_FIELDS)
        print("groups: 0, keeper missing: 0")
        print(f"plan: (no duplicate groups in the audit) -> {plan_path}")
        print("dedupe: nothing to do")
        return 0

    plan, skipped_groups = build_plan(groups, root, dest_name, args.copy)
    plan_path = os.path.join(out_dir, "dedupe_plan.csv")
    write_csv(plan_path, plan, PLAN_FIELDS)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    write_csv(os.path.join(out_dir, f"dedupe_plan_{stamp}.csv"), plan, PLAN_FIELDS)

    actions = Counter(row["action"] for row in plan)
    print(f"groups: {len(groups)}, keeper missing: {skipped_groups}")
    print("plan: " + ", ".join(f"{key}={value}" for key, value in sorted(actions.items())))
    print(f"plan written: {plan_path}")

    if not args.apply:
        print("dry-run: nothing moved. Re-run with --apply after checking the keeper column.")
        skips = sum(1 for row in plan if row["action"] == "skip")
        if skips:
            print(f"error: {skips} row(s) would be skipped (missing keeper/source or "
                  "changed MD5); fix the corpus or re-run the audit", file=sys.stderr)
            return 2
        return 0

    log_path = os.path.join(out_dir, "move_log.csv")
    counts = apply_plan(plan, root, dest_name, log_path)
    print("apply: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"move log: {log_path}")
    if counts["failed"] or counts["skipped"]:
        print(f"error: {counts['failed']} failed, {counts['skipped']} skipped; "
              f"fix them and re-run (or use --undo {log_path})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
