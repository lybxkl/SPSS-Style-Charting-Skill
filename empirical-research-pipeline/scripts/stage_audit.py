#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zero-trust two-pass stage-audit verifier.

The pipeline requires >=2 audits from different angles after EVERY stage. This
script does not trust the audited step's account of itself. A ledger pass is a
set of CLAIMS; the verifier tests each claim mechanically:

* **artifact binding** -- every pass declares the sha256 of the artifacts it
  audited; the verifier re-hashes them now. If the bytes changed since the
  audit, the pass no longer describes the current outputs and is rejected.
* **command re-execution** -- every ``evidence.commands`` entry is RE-RUN by the
  verifier (parsed with shlex, executed without a shell); the real exit code is
  compared to the claimed one. A self-reported "exit 0" is not evidence.
* **source re-read** -- every ``evidence.samples`` entry must be structured
  ``{rel_path, span, quote?, field?, value?}``; the verifier re-reads the raw
  source itself (binary via text_extract), checks the span, and requires the
  quote to sit INSIDE the span (a wider quote could wrap a real core in
  fabricated text). If field+value are given, the cell in --data is compared.
* **independence** -- >=2 distinct angles AND >=2 distinct methods, and at least
  one pass must re-read raw sources (a sample whose rel_path is not under
  output/). Re-running the same checker twice is not two angles.
* **re-derivation** -- the verifier recomputes funnel monotonicity, scope/temporal
  conformance and declared relation cardinality from the tables themselves,
  rather than trusting a QA report the audited step wrote about its own outputs.
* **resolution evidence** -- a finding marked resolved must carry resolution
  evidence (a re-run command or a changed-artifact hash); "resolved": true alone
  is not accepted.

Ledger (JSONL, one record per pass)::

    {"stage":"dataset","angle":"machine","method":"recompute",
     "artifacts":{"output/dataset/analysis.csv":"<sha256>"},
     "evidence":{"commands":[{"cmd":"python scripts/scope_conformance.py --data ... --scope ...","exit":0}],
                 "samples":[{"rel_path":"materials/a.pdf","span":[10,24],"quote":"...","field":"x","value":"v"}]},
     "findings":[{"detail":"...","resolved":true,"resolution":{"cmd":"...","exit":0}}],"at":"..."}

Missing required stage, <2 passes, single angle/method, unbound artifacts,
claim mismatch, fabricated quote, no raw-source re-read, or unresolved finding
=> exit 2. ``--no-rerun`` / ``--no-recompute`` / ``--exit-zero`` are DEBUG ONLY
and forbidden at delivery (they downgrade the verifier to structural checks).
No discipline-specific vocabulary lives here.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import audit_probe as AP

METHODS = {"recompute", "rerun", "rescan", "replay", "reextract", "reread", "mutation"}
KEY_ALIASES = ("rel_path", "relpath", "file", "path", "doc_id", "id")


def read_ledger(path: str) -> list[dict]:
    records = []
    with io.open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            records.append(json.loads(line))
    return records


def _same_value(left, right) -> bool:
    try:
        a, b = float(str(left).strip()), float(str(right).strip())
        return a == b
    except (TypeError, ValueError):
        return str(left).strip() == str(right).strip()


def _is_raw_source(rel_path: str) -> bool:
    norm = str(rel_path).replace("\\", "/").lstrip("./")
    return not (norm.startswith("output/") or norm.startswith("data/"))


def _index_data(data_path: str) -> dict:
    rows = AP.read_table(data_path)
    index = {}
    for row in rows:
        for alias in KEY_ALIASES:
            if row.get(alias):
                index[str(row[alias]).replace("\\", "/")] = row
                break
    return index


def _verify_pass(stage: str, idx: int, rec: dict, root: str, opts: dict,
                 data_index: dict | None) -> tuple[list[str], list[str], dict]:
    errors: list[str] = []
    warnings: list[str] = []
    tag = f"{stage} pass#{idx}"
    info: dict = {}

    angle = str(rec.get("angle") or "").strip()
    method = str(rec.get("method") or "").strip().lower()
    if not angle:
        errors.append(f"{tag}: missing angle")
    if method not in METHODS:
        errors.append(f"{tag}: method {method!r} not in {sorted(METHODS)}")
    info["method"] = method

    # artifact binding
    art_errors, verified = AP.verify_artifacts(rec.get("artifacts") or {}, root)
    errors.extend(f"{tag}: {e}" for e in art_errors)
    info["verified_artifacts"] = verified

    ev = rec.get("evidence") or {}
    if not isinstance(ev, dict):
        errors.append(f"{tag}: evidence must be an object")
        ev = {}

    # commands: re-run and compare real exit
    cmds = ev.get("commands") or []
    if not isinstance(cmds, list):
        errors.append(f"{tag}: evidence.commands must be a list")
        cmds = []
    for c in cmds:
        if not isinstance(c, dict) or not str(c.get("cmd") or "").strip() \
                or not isinstance(c.get("exit"), int):
            errors.append(f"{tag}: command entry needs cmd + integer exit")
            continue
        if opts.get("no_rerun"):
            warnings.append(f"{tag}: command not re-run (--no-rerun debug): {c['cmd']}")
            continue
        actual = AP.rerun_command(c["cmd"], root, opts.get("rerun_timeout", 600))
        if actual["timed_out"] or actual["exit"] is None:
            errors.append(f"{tag}: command failed to run: {c['cmd']} ({actual['stderr_tail']})")
        elif actual["exit"] != c["exit"]:
            errors.append(f"{tag}: claimed exit {c['exit']} but re-run gave "
                          f"{actual['exit']}: {c['cmd']}")
        info.setdefault("rerun", []).append({"cmd": c["cmd"], "claimed": c["exit"],
                                             "actual": actual["exit"]})

    # samples: structured, re-read raw source, quote inside span
    samples = ev.get("samples") or []
    if not isinstance(samples, list):
        errors.append(f"{tag}: evidence.samples must be a list")
        samples = []
    raw_reread = False
    for s in samples:
        if not isinstance(s, dict) or not s.get("rel_path") or "span" not in s:
            errors.append(f"{tag}: sample must be structured {{rel_path, span, ...}}; "
                          "free-text samples are not evidence")
            continue
        rel = str(s["rel_path"])
        full = AP.resolve(rel, root)
        if not os.path.isfile(full):
            errors.append(f"{tag}: sample source missing: {rel}")
            continue
        try:
            text = AP.read_source_text(full)
        except Exception as exc:                              # noqa: BLE001
            errors.append(f"{tag}: cannot re-read sample {rel}: {exc}")
            continue
        ok, reason = AP.verify_span_quote(text, s.get("span"), s.get("quote"))
        if not ok:
            errors.append(f"{tag}: sample {rel} failed re-read: {reason}")
            continue
        if _is_raw_source(rel):
            raw_reread = True
        if s.get("field") is not None and s.get("value") is not None:
            if data_index is None:
                warnings.append(f"{tag}: sample value not checked (no --data)")
            else:
                row = data_index.get(rel.replace("\\", "/"))
                if row is None:
                    errors.append(f"{tag}: sample {rel} not found in --data")
                elif not _same_value(s["value"], row.get(s["field"], "")):
                    errors.append(f"{tag}: sample {rel}#{s['field']} value {s['value']!r} "
                                  f"!= dataset cell {row.get(s['field'])!r}")
    info["raw_reread"] = raw_reread

    # findings: unresolved blocks; resolved needs resolution evidence
    for f in rec.get("findings") or []:
        if not isinstance(f, dict):
            errors.append(f"{tag}: finding must be an object")
            continue
        if not f.get("resolved", False):
            errors.append(f"{tag}: unresolved finding: {f.get('detail') or '(no detail)'}")
            continue
        resolution = f.get("resolution")
        if not isinstance(resolution, dict) or not (
                resolution.get("cmd") or resolution.get("artifacts")):
            errors.append(f"{tag}: finding marked resolved without resolution evidence "
                          f"(cmd or artifacts): {f.get('detail')}")
        elif resolution.get("cmd") and not opts.get("no_rerun"):
            actual = AP.rerun_command(resolution["cmd"], root, opts.get("rerun_timeout", 600))
            claimed = resolution.get("exit", 0)
            if actual["exit"] != claimed:
                errors.append(f"{tag}: resolution command claimed exit {claimed} "
                              f"but re-run gave {actual['exit']}")

    if not cmds and not samples:
        errors.append(f"{tag}: no verifiable evidence (commands or structured samples)")
    if method in ("reread", "reextract") and not samples:
        errors.append(f"{tag}: method {method} requires structured samples (raw-source re-read); "
                      "a command-only pass cannot claim this method")
    return errors, warnings, info


def _recompute_battery(root: str, opts: dict) -> tuple[list[str], dict]:
    """Re-derive project facts from raw inputs; never trust audited QA reports."""
    errors: list[str] = []
    detail: dict = {}
    if opts.get("no_recompute"):
        return errors, {"skipped": True}

    flow = opts.get("flow")
    if not flow:
        for cand in ("output/coding/sample_flow.csv", "output/audit/sample_flow.csv"):
            if os.path.isfile(AP.resolve(cand, root)):
                flow = cand
                break
    if flow and os.path.isfile(AP.resolve(flow, root)):
        ferr = AP.funnel_recompute(AP.resolve(flow, root))
        errors.extend(f"funnel: {e}" for e in ferr)
        detail["funnel"] = {"path": flow, "errors": ferr}

    data = opts.get("data")
    scope = opts.get("scope")
    registry = opts.get("registry")
    # Auto-detect standard project files so the default `--root .` invocation
    # actually re-derives scope/relations instead of silently skipping them.
    if not registry and os.path.isfile(AP.resolve("research_registry.json", root)):
        registry = "research_registry.json"
    if not scope and os.path.isfile(AP.resolve("scope.json", root)):
        scope = "scope.json"
    if not data and os.path.isfile(AP.resolve("output/dataset/analysis.csv", root)):
        data = "output/dataset/analysis.csv"
    if data and scope and os.path.isfile(AP.resolve(data, root)) \
            and os.path.isfile(AP.resolve(scope, root)):
        import scope_conformance as SC
        spec = json.loads(open(AP.resolve(scope, root), encoding="utf-8").read())
        cc = opts.get("cell_cols")
        if isinstance(cc, str):
            cc = [c.strip() for c in cc.split(",") if c.strip()] or None
        res = SC.check(AP.resolve(data, root), AP.resolve(scope, root), cc, None)
        errors.extend(f"scope: {e}" for e in res["errors"])
        detail["scope"] = {"error_count": res["error_count"]}
        tres = AP.check_temporal(spec, AP.resolve(data, root))
        errors.extend(f"temporal: {e}" for e in tres["errors"])
        detail["temporal"] = tres

    if registry and os.path.isfile(AP.resolve(registry, root)):
        reg = json.loads(open(AP.resolve(registry, root), encoding="utf-8").read())
        rres = AP.check_relations(reg, root)
        errors.extend(f"relation: {e}" for e in rres["errors"])
        detail["relations"] = rres
    return errors, detail


def check(records: list[dict], required: list[str] | None, root: str = ".",
        opts: dict | None = None) -> dict:
    opts = opts or {}
    by_stage = defaultdict(list)
    for rec in records:
        stage = str(rec.get("stage") or "").strip()
        if stage:
            by_stage[stage].append(rec)

    data = opts.get("data")
    if not data and os.path.isfile(AP.resolve("output/dataset/analysis.csv", root)):
        data = "output/dataset/analysis.csv"
    data_index = None
    if data and os.path.isfile(AP.resolve(data, root)):
        data_index = _index_data(AP.resolve(data, root))

    result: dict = {"errors": [], "warnings": [], "stages": {}}
    targets = required if required else sorted(by_stage)
    for stage in targets:
        passes = by_stage.get(stage, [])
        angles = sorted({str(p.get("angle") or "").strip().lower()
                         for p in passes if str(p.get("angle") or "").strip()})
        methods = sorted({str(p.get("method") or "").strip().lower()
                          for p in passes if str(p.get("method") or "").strip()})
        info = {"passes": len(passes), "angles": angles, "methods": methods}
        result["stages"][stage] = info
        if len(passes) < 2:
            result["errors"].append(f"{stage}: only {len(passes)} audit pass(es); >=2 required")
            continue
        if len(angles) < 2:
            result["errors"].append(f"{stage}: single angle {angles}; >=2 distinct angles required")
        if len(methods) < 2:
            result["errors"].append(f"{stage}: single method {methods}; >=2 distinct methods required "
                                    "(re-running one checker twice is not independence)")
        stage_raw = False
        for i, p in enumerate(passes, start=1):
            errs, warns, pinfo = _verify_pass(stage, i, p, root, opts, data_index)
            result["errors"].extend(errs)
            result["warnings"].extend(warns)
            info.setdefault("pass_detail", []).append(pinfo)
            stage_raw = stage_raw or pinfo.get("raw_reread", False)
        if not stage_raw:
            result["errors"].append(f"{stage}: no pass re-read a raw source "
                                    "(need >=1 structured sample whose rel_path is outside output/ and data/)")

    battery_errors, detail = _recompute_battery(root, opts)
    result["errors"].extend(battery_errors)
    result["recompute"] = detail
    result["error_count"] = len(result["errors"])
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--ledger", required=True, help="stage_audit.jsonl (one record per pass)")
    ap.add_argument("--require", default=None,
                    help="comma-separated stages that must each have >=2 clean passes")
    ap.add_argument("--root", default=".", help="project root for re-run/re-read/re-hash")
    ap.add_argument("--data", default=None, help="analysis table for sample value + scope checks")
    ap.add_argument("--scope", default=None, help="scope.json for scope/temporal re-derivation")
    ap.add_argument("--registry", default=None, help="research_registry.json for relation checks")
    ap.add_argument("--flow", default=None, help="sample_flow.csv (auto-detected if omitted)")
    ap.add_argument("--cell-cols", default=None, help="comma-separated small-cell columns")
    ap.add_argument("--rerun-timeout", type=int, default=600)
    ap.add_argument("--no-rerun", action="store_true", help="DEBUG ONLY: skip command re-execution")
    ap.add_argument("--no-recompute", action="store_true", help="DEBUG ONLY: skip re-derivation battery")
    ap.add_argument("--exit-zero", action="store_true", help="DEBUG ONLY: always exit 0")
    args = ap.parse_args(argv)
    required = [s.strip() for s in args.require.split(",") if s.strip()] if args.require else None
    opts = {"data": args.data, "scope": args.scope, "registry": args.registry,
            "flow": args.flow, "cell_cols": args.cell_cols,
            "rerun_timeout": args.rerun_timeout,
            "no_rerun": args.no_rerun, "no_recompute": args.no_recompute}
    try:
        records = read_ledger(args.ledger)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    result = check(records, required, args.root, opts)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["error_count"] and not args.exit_zero:
        print(f"STAGE AUDIT FAILED: {result['error_count']} error(s)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())