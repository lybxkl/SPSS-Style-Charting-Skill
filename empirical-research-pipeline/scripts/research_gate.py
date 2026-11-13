#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check source coverage, open-ended model plans and source-backfill attempts.

This is a coverage/receipt gate, not an automatic selector of valid research
designs. Arbitrary dataset forms and method family names are accepted. It can
detect omissions against registered sources/plans, not prove all useful ideas
in the world have been discovered.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from verify_dataset import load_json, load_jsonl, parse_time, read_csv, sha256, validate_final_report, write_json


TERMINAL = {"completed", "insufficient_data", "not_applicable", "unsupported", "failed"}


class ResearchGate:
    def __init__(self, registry_path, root, adapters=()):
        self.root = Path(root).resolve()
        self.registry_path = self.path(registry_path)
        self.registry = load_json(self.registry_path)
        self.issues, self.sources, self.datasets = [], {}, {}
        self.bindings = {str(self.registry_path): sha256(self.registry_path)}
        self.model_count = 0
        self.adapters = adapters

    def path(self, name):
        path = Path(name)
        return path.resolve() if path.is_absolute() else (self.root / path).resolve()

    def error(self, where, detail):
        self.issues.append({"severity": "error", "where": where, "detail": str(detail)})

    def file(self, name, expected=None, allow_empty=False):
        path = self.path(name)
        actual = self.bindings.get(str(path)) or sha256(path)
        if expected is not None and actual != expected:
            raise ValueError(f"stale hash: {name}")
        if path.stat().st_size == 0 and not allow_empty:
            raise ValueError(f"empty artifact: {name}")
        self.bindings[str(path)] = actual
        return path

    def source_coverage(self):
        inventory = self.file(self.registry["source_inventory"])
        _, rows = read_csv(inventory)
        source_root = self.path(self.registry["source_root"])
        for row in rows:
            rel = row.get("rel_path") or row.get("relpath")
            if not rel or rel in self.sources:
                raise ValueError("source inventory has missing/duplicate relative paths")
            path = (source_root / rel).resolve()
            if not path.is_relative_to(source_root):
                raise ValueError("source inventory path escapes source_root")
            self.sources[rel] = {"path": path, "status": row.get("status")}
        if not self.sources:
            raise ValueError("source inventory is empty")
        # Enumerate again so a stale audit cannot silently omit newly added files.
        disk = {p.relative_to(source_root).as_posix() for p in source_root.rglob("*") if p.is_file()}
        if disk != set(self.sources):
            self.error("source_inventory", f"inventory/disk mismatch; new={sorted(disk-set(self.sources))}, missing={sorted(set(self.sources)-disk)}")
        used = {}
        for spec in self.registry["datasets"]:
            ident = spec["id"]
            if ident in self.datasets:
                raise ValueError(f"duplicate dataset id: {ident}")
            self.datasets[ident] = spec
            self.file(spec["path"])
            records = load_jsonl(self.file(spec["provenance"]))
            used[ident] = {str(self.path(s["path"])) for r in records for s in r.get("sources", [])}
        unregistered = set().union(*used.values()) - {str(s["path"]) for s in self.sources.values()}
        if unregistered:
            self.error("source_coverage", f"cell evidence uses unaudited sources: {sorted(unregistered)}")
        coverage = load_jsonl(self.file(self.registry["source_coverage"]))
        seen = set()
        for row in coverage:
            rel = row.get("source")
            if rel not in self.sources or rel in seen:
                self.error("source_coverage", f"unknown/duplicate source: {rel}")
                continue
            seen.add(rel)
            try:
                self.file(self.sources[rel]["path"], row.get("sha256", ""), allow_empty=True)
                if not str(row.get("reason", "")).strip():
                    raise ValueError("every inclusion/exclusion needs a reason")
                status = row.get("status")
                if status == "included":
                    if self.sources[rel]["status"] != "valid":
                        raise ValueError("included source failed its audit; recover/re-audit it before use")
                    ids = row.get("datasets", [])
                    if not ids:
                        raise ValueError("included source has no dataset IDs")
                    actual_ids = {ident for ident, paths in used.items() if str(self.sources[rel]["path"]) in paths}
                    if set(ids) != actual_ids or len(set(ids)) != len(ids):
                        raise ValueError(f"source dataset links differ from actual cell evidence: {sorted(actual_ids)}")
                    for ident in ids:
                        if ident not in used or str(self.sources[rel]["path"]) not in used[ident]:
                            raise ValueError(f"included source has no cell evidence in dataset {ident}")
                elif status == "excluded":
                    if any(str(self.sources[rel]["path"]) in paths for paths in used.values()):
                        raise ValueError("excluded source still supplies dataset cells")
                elif status == "unreadable":
                    if not row.get("recovery_attempts"):
                        raise ValueError("unreadable source needs conversion/OCR/recovery attempts")
                    if any(str(self.sources[rel]["path"]) in paths for paths in used.values()):
                        raise ValueError("unreadable source still supplies cells without a registered recovered source")
                else:
                    raise ValueError("status must be included, excluded or unreadable")
            except Exception as exc:
                self.error(f"source:{rel}", exc)
        for rel in set(self.sources) - seen:
            self.error(f"source:{rel}", "source has no coverage disposition")
        self.file(self.registry["discovery_report"])

    def backfill(self, model):
        gaps = model.get("gaps", [])
        if not gaps:
            raise ValueError("an insufficient/unsupported/failed model needs explicit gaps and backfill evidence")
        for gap in gaps:
            if not gap.get("requirement") or not gap.get("conclusion"):
                raise ValueError("each gap needs requirement and a documented conclusion")
            searches = gap.get("searches", [])
            accounted = set()
            for search in searches:
                rel = search.get("source")
                if rel not in self.sources or rel in accounted:
                    raise ValueError(f"unknown/duplicate backfill source: {rel}")
                accounted.add(rel)
                self.file(self.sources[rel]["path"], search.get("sha256", ""), allow_empty=True)
                if search.get("result") not in {"found", "not_found", "unreadable", "not_relevant"} or not search.get("note"):
                    raise ValueError("each backfill search needs result and context/relevance note")
                if search.get("result") == "found" and not search.get("resolution"):
                    raise ValueError("found data needs a resolution: integrate/rebuild/review or explain why unusable")
            if accounted != set(self.sources):
                raise ValueError(f"backfill coverage incomplete: {sorted(set(self.sources)-accounted)}; unrelated files need not_relevant with a reason")

    def receipt(self, model):
        receipt = load_json(self.file(model["receipt"]))
        if receipt.get("id") != model["id"] or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError("run receipt is not a successful execution of this model")
        verification = receipt.get("verification") or {}
        if (verification.get("fingerprint") != self.verified["fingerprint"]
                or verification.get("verified_before_execution") is not True):
            raise ValueError("run receipt lacks current pre-execution data verification")
        if not receipt.get("command") or str(self.path(receipt.get("cwd", ""))) != str(self.root):
            raise ValueError("run receipt lacks its actual command/project directory")
        if parse_time(receipt["finished_at"]) < parse_time(receipt["started_at"]):
            raise ValueError("invalid run timestamps")
        expected_inputs = {*self.verifier.bindings, str(self.registry_path), str(self.path(self.verification_path)),
                           str(self.path(self.verified["snapshot_path"])), *self.verified["review_bindings"],
                           *[str(s["path"]) for s in self.sources.values()]}
        declared_inputs = {str(self.path(r["path"])) for r in receipt.get("inputs", [])}
        if not expected_inputs <= declared_inputs:
            raise ValueError("run receipt omitted mandatory source/rule/snapshot/review/input bindings")
        expected_code = {str(Path(__file__).with_name(n).resolve()) for n in
                         ("run_model.py", "verify_dataset.py", "source_guard.py")}
        if not expected_code <= {str(self.path(r["path"])) for r in receipt.get("code", [])}:
            raise ValueError("run receipt omitted runner/verifier/source-guard code bindings")
        protection = receipt.get("source_protection")
        if not isinstance(protection, dict) or any(protection.values()):
            raise ValueError("run receipt lacks successful frozen-source protection")
        for group in ("inputs", "code", "outputs"):
            records = receipt.get(group)
            if not isinstance(records, list) or not records:
                raise ValueError(f"run receipt has no {group}")
            for item in records:
                self.file(item["path"], item.get("sha256", ""), allow_empty=group == "inputs")
        data_path = str(self.path(self.datasets[model["dataset"]]["path"]))
        if data_path not in {str(self.path(x["path"])) for x in receipt["inputs"]}:
            raise ValueError("run receipt does not bind the declared dataset")
        for name in ("diagnostics", "sample"):
            full = str(self.file(model[name]))
            if full not in {str(self.path(x["path"])) for x in receipt["outputs"]}:
                raise ValueError(f"{name} is not bound to the completed run outputs")
        spec = self.datasets[model["dataset"]]
        _, data = read_csv(self.path(spec["path"]), spec.get("encoding", "utf-8-sig"), spec.get("delimiter", ","))
        keys = spec["key"] if isinstance(spec["key"], list) else [spec["key"]]
        existing = {tuple(r[k] for k in keys) for r in data}
        _, sample = read_csv(self.path(model["sample"]))
        selected = [tuple(r[k] for k in keys) for r in sample]
        if not selected or len(selected) != len(set(selected)) or not set(selected) <= existing:
            raise ValueError("sample keys must be nonempty, unique and present in the declared dataset")
        if isinstance(model.get("n"), bool) or model.get("n") != len(selected):
            raise ValueError("model N differs from its recorded input sample keys")

    def models(self):
        models = load_jsonl(self.file(self.registry["model_plan"]))
        self.model_count = len(models)
        if not models:
            raise ValueError("model plan is empty; document descriptive/exploratory candidates even when inference is unavailable")
        seen = set()
        for model in models:
            ident = model.get("id")
            try:
                if not ident or ident in seen:
                    raise ValueError(f"duplicate/empty model id: {ident}")
                seen.add(ident)
                if model.get("dataset") not in self.datasets:
                    raise ValueError("unknown dataset")
                if not all(str(model.get(k, "")).strip() for k in ("family", "question", "reason")):
                    raise ValueError("family, question and reason are required; family is open text")
                if not isinstance(model.get("requirements"), dict) or not model["requirements"]:
                    raise ValueError("model-specific data/design/identification requirements are required")
                status = model.get("status")
                if status not in TERMINAL:
                    raise ValueError(f"unfinished model status: {status}")
                if status == "completed":
                    self.receipt(model)
                    if model.get("gaps"):
                        self.backfill(model)
                elif status == "not_applicable":
                    self.file(model["assessment"])
                else:
                    self.backfill(model)
                    self.file(model["assessment"])
            except Exception as exc:
                self.error(f"model:{ident}", exc)
        for ident in set(self.datasets) - {m.get("dataset") for m in models}:
            self.error(f"dataset:{ident}", "no model/descriptive/not-applicable assessment covers this dataset")

    def run(self, verification):
        self.source_coverage()
        self.verification_path = verification
        self.verifier, self.verified = validate_final_report(str(self.registry_path), str(self.root), verification, self.adapters)
        self.models()
        # Re-run the machine portion to reject a stale "verified" JSON report.
        self.file(verification)
        _, checked = validate_final_report(str(self.registry_path), str(self.root), verification, self.adapters)
        self.file(checked["snapshot_path"], checked.get("snapshot_sha256", ""))
        for path, expected in checked["review_bindings"].items():
            self.file(path, expected)
        for path, old in list(self.bindings.items()):
            if sha256(path) != old:
                self.error(path, "input changed during research gate")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--verification", required=True, help="final dataset_verification.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--adapter", action="append", default=[], help="trusted name=path.py, same as verify_dataset")
    args = parser.parse_args(argv)
    gate = None
    try:
        gate = ResearchGate(args.registry, args.root, args.adapter)
        gate.run(args.verification)
        issues = gate.issues
    except Exception as exc:
        issues = (gate.issues if gate else []) + [{"severity": "error", "where": "input", "detail": str(exc)}]
    report = {"schema_version": 1, "status": "verified" if not issues else "error",
              "error_count": len(issues), "issues": issues,
              "source_count": len(gate.sources) if gate else 0,
              "dataset_count": len(gate.datasets) if gate else 0,
              "model_count": gate.model_count if gate else 0,
              "bindings": gate.bindings if gate else {},
              "limitations": "Checks registered coverage and receipts, not semantic correctness or completeness of all conceivable models."}
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, report)
    print(json.dumps({k: report[k] for k in ("status", "error_count", "source_count", "dataset_count", "model_count")}, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
