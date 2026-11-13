#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run an explicitly chosen analysis command and bind its inputs/code/outputs.

The agent chooses the engine, script, specification and environment. This
runner does not select methods or execute instructions read from source data.
Commands are argument arrays (shell=False), never interpolated shell strings.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from verify_dataset import load_json, sha256, validate_final_report, write_json
from source_guard import SourceGuard


def now():
    return datetime.now(timezone.utc).isoformat()


def file_records(paths, root):
    records = []
    for name in paths:
        path = Path(name)
        full = path.resolve() if path.is_absolute() else (root / path).resolve()
        if not full.is_file():
            raise ValueError(f"file missing: {full}")
        records.append({"path": str(full), "sha256": sha256(full), "bytes": full.stat().st_size})
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--verification", required=True, help="current final dataset_verification.json; revalidated before execution")
    parser.add_argument("--adapter", action="append", default=[])
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--code", action="append", required=True,
                        help="entry script plus imported project helpers/configuration; repeatable")
    parser.add_argument("--output", action="append", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--timeout", type=float, default=0, help="seconds; 0 means no time limit")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    receipt = Path(args.receipt).resolve()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    record = {"schema_version": 1, "id": args.id, "started_at": now(),
              "cwd": str(root), "command": command, "status": "error",
              "environment": {"platform": platform.platform(), "python": sys.version},
              "inputs": [], "code": [], "outputs": []}
    protected = {str((root / p).resolve()) for p in [*args.input, *args.code, args.registry, args.verification]}
    source_root = None
    guard = None
    try:
        config = load_json((root / args.registry).resolve())
        if config.get("source_root"):
            source_root = (root / config["source_root"]).resolve()
        if source_root and receipt.is_relative_to(source_root):
            raise ValueError("receipt/logs must stay outside the frozen source directory")
        if not command or args.timeout < 0:
            raise ValueError("supply an explicit command after -- and a nonnegative timeout")
        verifier, verified = validate_final_report(args.registry, str(root), args.verification, args.adapter)
        if source_root is None:
            raise ValueError("registry needs source_root to protect all original files")
        guard = SourceGuard(source_root, root)
        guard.freeze()
        declared = {str((root / p).resolve()) for p in args.input}
        if not declared & {str(verifier.path(v["spec"]["path"])) for v in verifier.datasets.values()}:
            raise ValueError("declare at least one verified registry dataset as --input")
        extra = [*verifier.bindings, *[r['path'] for r in guard.records], args.registry, args.verification,
                 verified["snapshot_path"], *verified["review_bindings"]]
        record["inputs"] = file_records(list(dict.fromkeys([*args.input, *extra])), root)
        record["code"] = file_records(list(dict.fromkeys([*args.code, str(Path(__file__).resolve()),
                                                         str(Path(__file__).with_name("verify_dataset.py").resolve()),
                                                         str(Path(__file__).with_name("source_guard.py").resolve())])), root)
        record["verification"] = {"fingerprint": verified["fingerprint"], "verified_before_execution": True}
        protected |= {r["path"] for r in record["inputs"] + record["code"]}
        outputs = [str((root / p).resolve()) for p in args.output]
        log_paths = {str(receipt), str(receipt) + ".stdout.log", str(receipt) + ".stderr.log"}
        if any(guard.forbidden(p) for p in [*outputs, *log_paths]):
            raise ValueError("outputs, receipt and logs must stay outside frozen sources and source backups")
        if len(set(outputs)) != len(outputs) or protected & (set(outputs) | log_paths) or set(outputs) & log_paths:
            raise ValueError("inputs/code, outputs, receipt and logs must use separate paths")
        before = {p: (Path(p).stat().st_mtime_ns, Path(p).stat().st_ctime_ns,
                      Path(p).stat().st_size, sha256(p)) for p in outputs if Path(p).is_file()}
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with open(str(receipt) + ".stdout.log", "w", encoding="utf-8") as out, \
                open(str(receipt) + ".stderr.log", "w", encoding="utf-8") as err:
            result = subprocess.run(command, cwd=root, shell=False, stdout=out, stderr=err,
                                    timeout=args.timeout or None)
        record["returncode"] = result.returncode
        if result.returncode:
            raise ValueError(f"analysis command returned {result.returncode}; inspect stderr log")
        for item in record["inputs"] + record["code"]:
            if sha256(item["path"]) != item["sha256"]:
                raise ValueError(f"analysis changed a declared input/code file: {item['path']}")
        record["outputs"] = file_records(args.output, root)
        if any(r["bytes"] == 0 for r in record["outputs"]):
            raise ValueError("an output is empty; do not label a zero-output run completed")
        for item in record["outputs"]:
            path = Path(item["path"])
            stat = path.stat()
            if before.get(str(path)) == (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, item["sha256"]):
                raise ValueError(f"output was not regenerated by this run: {path}")
        record["status"] = "completed"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if guard is not None:
            protection = guard.finish()
            record["source_protection"] = protection
            if any(protection.values()):
                record["status"] = "error"
                record["error"] = "frozen source changes detected; originals restored where possible; inspect source_protection"
    record["finished_at"] = now()
    # An accidental receipt/input overlap is diagnosed without overwriting it.
    if (str(receipt) in (protected | {str((root / p).resolve()) for p in args.output})
            or (source_root and receipt.is_relative_to(source_root)) or (guard and guard.forbidden(receipt))):
        print(record.get("error", "receipt overlaps an input"), file=sys.stderr)
        return 2
    receipt.parent.mkdir(parents=True, exist_ok=True)
    write_json(receipt, record)
    print(json.dumps({"id": args.id, "status": record["status"], "receipt": str(receipt),
                      "error": record.get("error", "")}, ensure_ascii=False))
    return 0 if record["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
