# -*- coding: utf-8 -*-
"""Study-design features -> required diagnostics, and role/leakage accounting.

A model can be numerically fine and still be wrong for the design: clustered
rows treated as independent, repeated measures counted as new people, weighted
survey data reported unweighted, matched samples analysed as two independent
groups, or a test split leaking into training.  This module makes those
linkages explicit instead of leaving them to prose.

Two independent jobs:

* **design -> diagnostics**: infer the design features that the data actually
  shows (cluster/repeated/weighted/matched/stratified/panel/small-n/missing),
  state which diagnostics the analysis must therefore report, and check the
  fitted result for them.
* **roles -> N and leakage**: account N by role and observation unit (never by
  summing table rows), and reject splits that put the same unit on both sides.

Results are stored as ``validation_result`` records with
``target.kind = "design_linkage"`` so the release gate can see them.

CLI::

    python designcheck.py --root . infer --dataset person --keys id
    python designcheck.py --root . link --spec M1
    python designcheck.py --root . roles --spec M1
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C

#: design feature -> diagnostics that must be reported, with the reason.
LINKAGE = {
    "clustered": [
        ("cluster_count", "report how many clusters and their sizes; rows in a "
                          "cluster are not independent observations"),
        ("cluster_robust_or_mixed", "use cluster-robust SEs or a multilevel "
                                    "model; otherwise the SE is too small"),
    ],
    "repeated": [
        ("unit_count", "N is the number of units, not the number of rows"),
        ("within_unit_structure", "report the within-unit correlation or the "
                                  "random-effects structure"),
    ],
    "weighted": [
        ("weight_variable", "name the weight variable and its source"),
        ("weighted_vs_unweighted_n", "report both the weighted and the "
                                     "unweighted N"),
    ],
    "matched": [
        ("matched_pairs", "report the number of matched sets/pairs"),
        ("balance", "report covariate balance after matching"),
    ],
    "stratified": [
        ("strata_counts", "report the strata and their counts"),
    ],
    "panel": [
        ("periods", "report the number of periods and the panel balance"),
        ("within_between", "say whether the estimate is within or between "
                           "units"),
    ],
    "small_n": [
        ("epv_or_power", "report events per variable or a power statement; a "
                         "small sample limits what can be concluded"),
    ],
    "missing": [
        ("missing_counts", "report n_dropna and the missingness pattern"),
    ],
    "multiple_outcomes": [
        ("multiplicity", "report whether and how multiple comparisons were "
                         "handled"),
    ],
}


def _producer(**kw) -> dict:
    return C.producer_for("designcheck", version="2.0", module_file=__file__,
                          **kw)


class DesignError(Exception):
    pass


def _load_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh,delimiter="\t" if path.suffix.lower()==".tsv" else ",")
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


def infer_design(dataset_path: str | os.PathLike, *, keys: Iterable[str],
                 columns: Iterable[str] | None = None,
                 weight_column: str | None = None,
                 strata_column: str | None = None,
                 treat_column: str | None = None,
                 time_column: str | None = None,
                 cluster_column: str | None = None) -> dict:
    path = Path(dataset_path)
    header, rows = _load_csv(path)
    keys = list(keys)
    values = {}
    for key in keys:
        if key not in header:
            raise DesignError(f"key column {key!r} is not in {path.name}")
        values[key] = [r[key] for r in rows]
    units = list(zip(*[values[k] for k in keys])) if keys else []
    unique_units = len(set(units))
    features: dict[str, object] = {
        "rows": len(rows), "unique_units": unique_units,
        "unit_column": keys[0] if len(keys) == 1 else keys,
    }
    repeated = unique_units and len(rows) > unique_units
    features["repeated"] = bool(repeated)
    if repeated:
        counts: dict[tuple, int] = {}
        for unit in units:
            counts[unit] = counts.get(unit, 0) + 1
        features["max_rows_per_unit"] = max(counts.values())
    if cluster_column:
        if cluster_column not in header:
            raise DesignError(f"cluster column {cluster_column!r} is missing")
        clusters = {r[cluster_column] for r in rows if not _is_blank(r[cluster_column])}
        features["clustered"] = len(clusters) > 1 and len(clusters) < len(rows)
        features["cluster_count"] = len(clusters)
    if weight_column:
        if weight_column not in header:
            raise DesignError(f"weight column {weight_column!r} is missing")
        weights = [r[weight_column] for r in rows if not _is_blank(r[weight_column])]
        features["weighted"] = bool(weights)
        features["weight_min"] = min((float(w) for w in weights), default=None)
        features["weight_max"] = max((float(w) for w in weights), default=None)
        if weights:
            try:
                features["weights_all_one"] = all(float(w) == 1.0 for w in weights)
            except ValueError:
                features["weights_all_one"] = None
    if strata_column:
        if strata_column not in header:
            raise DesignError(f"strata column {strata_column!r} is missing")
        strata = [r[strata_column] for r in rows]
        features["stratified"] = len(set(strata)) > 1
        features["strata_count"] = len(set(strata))
    if time_column:
        if time_column not in header:
            raise DesignError(f"time column {time_column!r} is missing")
        periods = {r[time_column] for r in rows if not _is_blank(r[time_column])}
        features["panel"] = len(periods) > 1 and bool(repeated)
        features["periods"] = len(periods)
    if treat_column and treat_column in header:
        features["groups"] = len({r[treat_column] for r in rows})
        # Matching is a declared design, not inferable from repeated IDs alone.
        features["matched"] = False
        features["matching_assessment"] = "declare matched sets and assignment basis if applicable"
    else:
        features["matched"] = False
    cols = list(columns or header)
    missing = {c: sum(1 for r in rows if _is_blank(r.get(c))) for c in cols}
    features["missing"] = {c: n for c, n in missing.items() if n}
    features["n_with_any_missing"] = sum(
        1 for r in rows if any(_is_blank(r.get(c)) for c in cols))
    features["small_n"] = len(rows) < 30 or unique_units < 30
    outcomes = [c for c in cols if c not in keys]
    features["multiple_outcomes"] = len(outcomes) > 1
    return features


def required_diagnostics(features: Mapping) -> list[dict]:
    if not isinstance(features, Mapping):
        raise DesignError("features must be a mapping")
    out = []
    for name, checks in LINKAGE.items():
        if not features.get(name):
            continue
        for check, why in checks:
            out.append({"check": check, "why": why, "feature": name})
    return out


def linkage(spec: Mapping, result: Mapping | None = None) -> dict:
    """Does the fitted result report what the design demands?"""
    features = spec.get("design_features") or {}
    if not features:
        raise DesignError("the model spec has no design_features; run infer and "
                          "attach them before linking diagnostics")
    required = required_diagnostics(features)
    result = dict(result or {})
    payload = result.get("payload") or result
    reported = dict(payload.get("diagnostics") or {})
    sample = (result or {}).get("sample_scope") or {}
    findings = []
    for item in required:
        name = item["check"]
        value = reported.get(name)
        present = value not in (None, "", [], {}) and value is not False
        if name == "cluster_robust_or_mixed":
            present = value is True or (isinstance(value, Mapping) and value.get("status") == "passed" and bool(value.get("method")))
        if name in ("cluster_count", "matched_pairs", "periods"):
            present = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        if isinstance(value, Mapping) and value.get("status") in ("failed", "not_run", "unassessed", "unsupported"):
            present = False
        if name == "unit_count":
            present = isinstance(sample.get("n_unit", payload.get("n_unit")), (int, float))
        if name == "missing_counts":
            count = reported.get("n_dropna", sample.get("n_dropna", payload.get("n_dropna")))
            present = isinstance(count, int) and not isinstance(count, bool) and count >= 0
        findings.append({"check": name, "ok": bool(present),
                         "feature": item["feature"], "why": item["why"],
                         "severity": "error" if not present else "info"})
    errors = [f for f in findings if not f["ok"]]
    return {"ok": not errors, "features": features,
            "required": [r["check"] for r in required],
            "findings": findings,
            "missing": [f["check"] for f in errors]}


def role_accounting(spec: Mapping, *, root=None) -> dict:
    """N by role and unit; reject summed table rows and leaking splits."""
    inputs = spec.get("inputs") or []
    if not inputs:
        raise DesignError("model spec has no inputs")
    by_role: dict[str, list[dict]] = {}
    for inp in inputs:
        role = inp.get("role")
        if not role:
            raise DesignError(f"input {inp.get('dataset')!r} has no role")
        by_role.setdefault(role, []).append(inp)
    problems = []
    per_role: dict[str, dict] = {}
    seen_units: dict[str, dict] = {}
    for role, items in by_role.items():
        units: set[tuple] = set()
        rows = 0
        raw_keys: dict[str, list[str]] = {}
        for item in items:
            path = Path(item["dataset"])
            if not path.is_absolute():
                base = root or spec.get("project_root")
                if base is None:
                    raise DesignError("relative model inputs need their project_root")
                path = Path(base) / path
            if C.file_sha256(path) != item.get("sha256"):
                problems.append({"check": "input_changed", "role": role,
                                 "dataset": item.get("dataset")})
            if (spec.get("n_semantics") or {}).get("kind") == "none" or item.get("role") in ("parameters", "constraints", "initial", "boundary") or item.get("tabular") is False:
                per_role[role] = {"datasets": len(items), "rows": None, "units": None, "raw_keys": {}, "sample_semantics": "none",
                                  "dimensions": spec.get("dimensions"), "input_bytes": sum((Path(root or spec.get("project_root") or ".") / i["dataset"]).stat().st_size for i in items)}
                continue
            header, data = _load_csv(path)
            keys = item.get("keys") or [header[0]]
            unit_keys = item.get("unit_keys") or (spec.get("n_semantics") or {}).get("unit_keys") or keys
            rows += len(data)
            for row in data:
                if any(k not in row or _is_blank(row[k]) for k in unit_keys):
                    problems.append({"check": "missing_unit_key", "role": role})
                else:
                    units.add(tuple(str(row[k]) for k in unit_keys))
            raw_keys[item.get("dataset", "")] = list(keys)
        if role in per_role and per_role[role].get("sample_semantics") == "none":
            continue
        per_role[role] = {"datasets": len(items), "rows": rows,
                          "units": len(units), "raw_keys": raw_keys}
        seen_units[role] = units
    for role, units in seen_units.items():
        if role in ("fit", "train"):
            continue
        for other in ("test", "validate", "calibrate"):
            if other == role or other not in seen_units:
                continue
            overlap = units & seen_units[other]
            if overlap:
                problems.append({"check": "split_leakage", "roles": [role, other],
                                 "overlap_units": len(overlap),
                                 "example": sorted(overlap)[:3]})
    train_units: set[tuple] = set()
    for role in ("fit", "train"):
        train_units |= seen_units.get(role, set())
    held_out: set[tuple] = set()
    for role in ("test", "validate", "calibrate"):
        held_out |= seen_units.get(role, set())
    if train_units and held_out:
        overlap = train_units & held_out
        if overlap:
            problems.append({"check": "split_leakage", "roles": ["fit", "test"],
                             "overlap_units": len(overlap),
                             "example": sorted(overlap)[:3]})
            problems.append({"check": "train_test_overlap",
                             "overlap_units": len(overlap)})
    if spec.get("n_semantics", {}).get("kind") == "observation":
        declared = spec.get("n_semantics", {}).get("unit")
        for role in ("fit", "train"):
            if role in per_role and not declared:
                problems.append({"check": "role_without_unit", "role": role})
    repeated = []
    for role, info in per_role.items():
        if info["rows"] != info["units"]:
            repeated.append({"role": role, "rows": info["rows"],
                             "units": info["units"]})
    return {"ok": not problems, "by_role": per_role,
            "n_by_role_not_summed": {r: v["units"] for r, v in per_role.items()},
            "repeated_roles": repeated, "problems": problems,
            "note": "N is reported per role and per observation unit; table rows "
                    "are never added across inputs to make an independent N"}


def record_linkage(project: C.Project, spec: Mapping, *,
                   result: Mapping | None = None) -> dict:
    import models as M
    spec_id = spec.get("id")
    if not spec_id:
        raise DesignError("spec needs an id")
    roles = role_accounting(spec, root=project.root)
    if result is None:
        result_rec = project.latest("model_result", spec_id)
        result = result_rec["data"] if result_rec else None
    else:
        result_rec = project.latest("model_result", spec_id)
    if not M.statistical(spec):
        payload_result = (result or {}).get("payload", result or {})
        quality = payload_result.get("solve_quality")
        ok = quality in ("feasible", "local_optimum", "certified_global") and bool(payload_result.get("certificate") or payload_result.get("diagnostics"))
        link = {"ok": ok, "features": {"mathematical": True}, "required": ["feasibility_and_quality"],
                "missing": [] if ok else ["feasibility_and_quality"]}
    else:
        spec = dict(spec)
        if not spec.get("design_features"):
            fit = next(i for i in spec["inputs"] if i["role"] in ("fit", "train"))
            variables = spec.get("variables") or {}
            unit_keys = fit.get("unit_keys") or (spec.get("n_semantics") or {}).get("unit_keys") or fit["keys"]
            features = infer_design(project.root / fit["dataset"], keys=unit_keys,
                                    columns=[variables["y"], *variables.get("x", []), *variables.get("controls", [])],
                                    cluster_column=spec.get("cluster") or spec.get("groups"), time_column=spec.get("time"),
                                    weight_column=spec.get("weights"), strata_column=spec.get("strata"))
            features["multiple_outcomes"] = len(spec.get("outcomes") or [variables["y"]]) > 1
            spec["design_features"] = features
        link = linkage(spec, result)
        diagnostics = ((result or {}).get("payload") or result or {}).get("diagnostics") or {}
        if diagnostics.get("converged") is None:
            link["missing"].append("convergence_assessment")
        if diagnostics.get("converged") is False:
            link["missing"].append("convergence")
        if diagnostics.get("separation_warning"):
            link["missing"].append("separation_assessment")
        if diagnostics.get("design_rank", float("inf")) < diagnostics.get("parameter_count", 0):
            link["missing"].append("identifiability")
        link["ok"] = link["ok"] and not link["missing"]
    payload = {
        "target": {"kind": "design_linkage", "spec": spec_id,
                   "model": spec_id},
        "method": "design_to_diagnostics",
        "independent": {"estimate": None,
                        "note": "linkage is a decision, not an independent "
                                "recomputation"},
        "tolerance": {"kind": "exact", "value": 0},
        "observed": {"features": link["features"], "required": link["required"],
                     "missing": link["missing"], "roles": roles,
                     "outcome": "pass" if link["ok"] and roles["ok"] else "fail"},
        "layers": ["method"],
        "status": "passed" if link["ok"] and roles["ok"] else "failed",
        "reason": ("design and diagnostics linked" if link["ok"] and roles["ok"]
                   else f"missing diagnostics {link['missing']}; role problems "
                        f"{[p['check'] for p in roles['problems']]}"),
    }
    payload["target"]["result_signature"] = C.signature(result_rec) if result_rec else None
    rid = f"design:{spec_id}"
    prev = project.latest("validation_result", rid)
    rec = C.make_record("validation_result", rid, payload, producer=_producer(),
                        status=payload["status"],
                        revision=(prev["revision"] + 1) if prev else 1)
    project.append("validation_result", rec, enforce_transition=False)
    if project.latest("model_spec", spec_id) is not None:
        status = "assessed" if rec["status"] == "passed" else "failed"
        M._update_spec(project, spec_id, status=project.latest("model_spec", spec_id)["status"],
                       patch={"method_assessment": {"status": status, "record": rid,
                                                    "result_signature": payload["target"]["result_signature"]}})
    return {"record": rec["id"], "status": rec["status"],
            "missing": link["missing"], "problems": roles["problems"]}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="design/diagnostic linkage")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_i = sub.add_parser("infer")
    p_i.add_argument("--dataset", required=True)
    p_i.add_argument("--keys", nargs="+", required=True)
    p_i.add_argument("--columns", nargs="*")
    p_i.add_argument("--weight")
    p_i.add_argument("--strata")
    p_i.add_argument("--treat")
    p_i.add_argument("--time")
    p_i.add_argument("--cluster")
    p_l = sub.add_parser("link")
    p_l.add_argument("--spec", required=True)
    p_r = sub.add_parser("roles")
    p_r.add_argument("--spec", required=True)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "infer":
        path = Path(args.dataset)
        if not path.is_absolute():
            path = proj.root / path
        features = infer_design(path, keys=args.keys, columns=args.columns,
                                weight_column=args.weight,
                                strata_column=args.strata,
                                treat_column=args.treat,
                                time_column=args.time,
                                cluster_column=args.cluster)
        print(json.dumps({"features": features,
                          "required": required_diagnostics(features)},
                         ensure_ascii=False, indent=1))
        return 0
    import models as M
    try:
        spec = M.load_spec(proj, args.spec)["data"]
    except M.ModelError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.cmd == "link":
        result = None
        result_rec = proj.latest("model_result", args.spec)
        if result_rec is not None:
            result = result_rec["data"]
        res = record_linkage(proj, spec, result=result)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["status"] == "passed" else 2
    if args.cmd == "roles":
        res = role_accounting(spec, root=proj.root)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
