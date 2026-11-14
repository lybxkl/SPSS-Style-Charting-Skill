# -*- coding: utf-8 -*-
"""Independent numeric validation and specification stability.

Two different jobs, deliberately ordered: **validate the number, then vary the
specification**.  Extending the spec grid before the arithmetic is independently
checked multiplies unverified numbers.

Independence is layered.  A second computation that re-uses the same extraction,
the same transform, or the same model call is *not* independent even if it calls
a different library.  Each validation records which layers it covers and whether
the preprocessing was shared; a shared wrong transform that produces two
agreeing numbers is reported as ``agrees_but_not_independent`` rather than as
proof.

CLI::

    python validation.py --root . ols --spec M1
    python validation.py --root . logit --spec M2
    python validation.py --root . stability --spec M1 \\
        --variant "no_controls=..." --variant "winsor=..."
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C
import models as M


def _producer(**kw) -> dict:
    return C.producer_for("validation", version="2.0", module_file=__file__,
                          **kw)


LAYERS = ("extraction", "transform", "numeric", "method")
TOLERANCE = 1e-6


def _load(spec: Mapping, project: C.Project):
    import pandas as pd
    fit = next(i for i in spec["inputs"] if i["role"] in ("fit", "train"))
    if C.file_sha256(project.root / fit["dataset"]) != fit["sha256"]:
        raise ValueError("validation input changed after model registration")
    frame = pd.read_csv(project.root / fit["dataset"], sep="\t" if Path(fit["dataset"]).suffix.lower()==".tsv" else ",", dtype=str, keep_default_na=False).replace("", float("nan"))
    variables = spec["variables"]
    cols = [variables["y"]] + list(variables.get("x") or []) + \
           list(variables.get("controls") or [])
    data = frame[cols].astype(float).dropna()
    y = data[variables["y"]].to_numpy()
    X = data[[c for c in cols if c != variables["y"]]].to_numpy()
    X = __import__("numpy").column_stack([__import__("numpy").ones(len(X)), X])
    return y, X, fit


def independent_ols(project: C.Project, spec_id: str, *,
                    shared_preprocessing: bool = False) -> dict:
    """Solve least squares with numpy only (no statsmodels)."""
    import numpy as np
    spec_rec = M.load_spec(project, spec_id)
    spec = spec_rec["data"]
    if spec["family"] != "ols" or spec.get("weights") is not None or spec.get("offset") is not None:
        raise ValueError("independent_ols checks unweighted OLS only; select an independent adapter for this model")
    y, X, fit = _load(spec, project)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    target = spec["result"]["target_parameter"]
    names = ["const"] + list(spec["variables"].get("x") or []) + \
            list(spec["variables"].get("controls") or [])
    independent = {name: float(b) for name, b in zip(names, beta)}
    return _compare_and_record(project, spec, spec_rec, target,
                               independent, fit,
                               shared_preprocessing=shared_preprocessing,
                               expected_n=len(y),
                               method="normal equations via numpy.linalg.lstsq",
                               numeric_library="numpy")


def independent_logit(project: C.Project, spec_id: str, *,
                      shared_preprocessing: bool = False) -> dict:
    """IRLS implemented here, compared with the registered statsmodels fit."""
    import numpy as np
    spec_rec = M.load_spec(project, spec_id)
    spec = spec_rec["data"]
    if spec["family"] != "logit" or spec.get("weights") is not None or spec.get("offset") is not None:
        raise ValueError("independent_logit checks unweighted logit only; select an independent adapter for this model")
    y, X, fit = _load(spec, project)
    beta = np.zeros(X.shape[1])
    converged = False
    for _ in range(100):
        eta = X @ beta
        p = 1.0 / (1.0 + np.exp(-eta))
        w = np.clip(p * (1 - p), 1e-10, None)
        z = eta + (y - p) / w
        xtw = X.T * w
        new, *_ = np.linalg.lstsq(xtw @ X, xtw @ z, rcond=None)
        if np.max(np.abs(new - beta)) < 1e-10:
            beta = new
            converged = True
            break
        beta = new
    if not converged or not np.isfinite(beta).all():
        raise ValueError("independent IRLS did not converge; no passed validation may be recorded")
    names = ["const"] + list(spec["variables"].get("x") or []) + \
            list(spec["variables"].get("controls") or [])
    independent = {name: float(b) for name, b in zip(names, beta)}
    target = spec["result"]["target_parameter"]
    return _compare_and_record(project, spec, spec_rec, target, independent, fit,
                               expected_n=len(y),
                               shared_preprocessing=shared_preprocessing,
                               method="IRLS implemented in validation.py",
                               numeric_library="numpy (own IRLS)")


def _compare_and_record(project: C.Project, spec: Mapping, spec_rec: Mapping,
                        target: str, independent: Mapping, fit_input: Mapping,
                        *, shared_preprocessing: bool, method: str,
                        numeric_library: str, expected_n=None) -> dict:
    model = project.latest("model_result", str(spec["id"]))
    if model is None:
        raise SystemExit("fit the model before validating it")
    if not M.current_result(project, model):
        raise ValueError("result is not current and execution-bound; refit before numeric validation")
    res = model["data"]["payload"]
    if not res:
        raise SystemExit("the model result is empty; nothing to validate")
    coefs = res.get("coefficients") or {}
    mine = independent.get(target)
    theirs = (coefs.get(target) or {}).get("estimate")
    differences = {}
    worst = 0.0
    import math
    absent=set(independent)-set(coefs)
    for name, mine_b in independent.items():
        if name not in coefs:
            continue
        import math
        diff = abs(mine_b - coefs[name]["estimate"])
        if not math.isfinite(diff):
            worst = float("inf")
            differences[name] = "nonfinite"
            continue
        scale = max(1.0, abs(coefs[name]["estimate"]))
        differences[name] = round(diff / scale, 12)
        worst = max(worst, diff / scale)
    within = (not absent and (expected_n is None or res.get("n")==expected_n) and mine is not None and theirs is not None and math.isfinite(float(mine))
              and math.isfinite(float(theirs)) and worst <= TOLERANCE)
    worst_output = worst if math.isfinite(worst) else "nonfinite"
    shared = bool(shared_preprocessing) or \
        fit_input.get("preprocessing_ref") == spec.get("preprocessing_ref") and \
        spec.get("preprocessing_ref") is not None
    if shared:
        status = "agrees_but_not_independent" if within else "failed"
        independence = {"layers": ["numeric"],
                        "shared": ["extraction", "transform"],
                        "note": "both numbers came from the same preprocessing; "
                                "this checks arithmetic only, not the data"}
    else:
        status = "passed" if within else "failed"
        independence = {"layers": ["numeric"],
                        "shared": [],
                        "note": "independent arithmetic on the same audited dataset; source extraction and method suitability are checked separately"}
    payload = {
        "target": {"model": model["id"], "parameter": target,
                   "spec": spec["id"], "result_revision": model["revision"],
                   "result_signature": C.signature(model)},
        "method": method,
        "independent": {"estimate": mine, "coefficients": independent,
                        "library": numeric_library,
                        "layers": independence["layers"],
                        "shared": independence["shared"],
                        "note": independence["note"]},
        "tolerance": {"kind": "relative", "value": TOLERANCE},
        "observed": {"reference": theirs, "coefficients": coefs,
                     "max_relative_difference": worst_output,
                     "differences": differences, "outcome": status,
                     "data_sha256": fit_input["sha256"]},
        "layers": independence["layers"],
        "reason": "" if status == "passed" else independence["note"],
    }
    payload["observed"]["validated_fields"]=["estimate",*[C.field_pointer("coefficients",name,"estimate") for name in independent]]+(["n"] if expected_n is not None else [])
    payload["observed"]["expected_n"]=expected_n
    payload["observed"]["missing_coefficients"]=sorted(absent)
    rid = f"val:{spec['id']}:{target}"
    prev = project.latest("validation_result", rid)
    rec = C.make_record("validation_result", rid, payload, producer=_producer(),
                        status=("passed" if status == "passed" else "failed"),
                        revision=(prev["revision"] + 1) if prev else 1,
                        input_refs=[{"kind": "model_result",
                                     "id": model["id"]}])
    project.append("validation_result", rec, enforce_transition=False)
    return {"validation": rec["id"], "status": status,
            "independent": mine, "reference": theirs,
            "max_relative_difference": worst_output,
            "independence": independence}


def is_current(project, spec_id, result=None, *, field=None):
    result = result or project.latest("model_result", spec_id)
    if not M.current_result(project, result):
        return False
    target = result["data"]["target_parameter"]
    validation = project.latest("validation_result", f"val:{spec_id}:{target}")
    covered=(validation or {}).get("data",{}).get("observed",{}).get("validated_fields",[])
    payload=result["data"]["payload"]
    needed=[field] if field else (["estimate"] if payload.get("estimate") is not None else ["solution"] if payload.get("solution") is not None else [])
    if not field and M.statistical(M.load_spec(project,spec_id)["data"]):needed.append("n")
    if any(not any(C.field_parts(name)[:len(C.field_parts(item))]==C.field_parts(item) for item in covered) for name in needed):return False
    if validation and validation["data"]["independent"].get("bindings"):
        import execution as EX
        if not EX.current(project, M.load_spec(project, spec_id)["data"], validation["data"]["independent"]["bindings"]):
            return False
    return bool(validation and validation["status"] == "passed"
                and validation["data"]["target"].get("result_signature") == C.signature(result)
                and validation["producer"].get("code_sha256") == C.file_sha256(__file__))


def compare_results(project, left_id, right_id):
    """Describe comparability; never subtract unlike estimands or silently convert units."""
    left = project.latest("model_result", left_id)
    right = project.latest("model_result", right_id)
    if not left or not right or not M.current_result(project, left) or not M.current_result(project, right):
        raise ValueError("comparison requires two current execution-bound results")
    a, b = left["data"]["payload"], right["data"]["payload"]
    dimensions = ("target_parameter", "unit", "scale", "native_parameter_scale", "denominator", "group", "time_scope", "sample_unit")
    differences = {k: {"left": a.get(k), "right": b.get(k)} for k in dimensions if a.get(k) != b.get(k)}
    unknown = [k for k in ("target_parameter", "unit", "scale") if not a.get(k) or not b.get(k)]
    return {"comparable": not differences and not unknown, "differences": differences, "unassessed": unknown,
            "left_signature": C.signature(left), "right_signature": C.signature(right),
            "note": "Matching labels establish numerical comparability only; design and substantive interpretation require separate review."}


def adjust_pvalues(values, *, method="holm"):
    """Bonferroni/Holm/BH with original order preserved, no filtering by significance."""
    import math
    p = [float(v) for v in values]
    if not p or any(not math.isfinite(v) or not 0 <= v <= 1 for v in p):
        raise ValueError("a declared test family needs finite p values in [0,1]")
    n = len(p)
    order = sorted(range(n), key=p.__getitem__)
    adjusted = [0.0] * n
    if method == "bonferroni":
        return [min(1.0, v*n) for v in p]
    if method == "holm":
        previous = 0.0
        for rank, i in enumerate(order):
            previous = max(previous, min(1.0, (n-rank)*p[i]))
            adjusted[i] = previous
    elif method in ("bh", "fdr_bh"):
        previous = 1.0
        for rank in range(n-1, -1, -1):
            i = order[rank]
            previous = min(previous, n*p[i]/(rank+1))
            adjusted[i] = min(1.0, previous)
    else:
        raise ValueError("use a built-in correction or an explicitly bound custom implementation")
    return adjusted


def multiple_comparisons(project, family_id, *, tests, rationale, method="holm", alpha=0.05):
    if not rationale.strip() or not 0 < alpha < 1:
        raise ValueError("declare the test-family rationale and alpha before correction")
    rows, signatures, seen = [], {}, set()
    for test in tests:
        key = (test["model"], test["parameter"])
        if key in seen:
            raise ValueError("a test cannot appear twice in one family")
        seen.add(key)
        rec = project.latest("model_result", key[0])
        row = {"model": key[0], "parameter": key[1], "p_raw": None, "p_adjusted": None, "status": "unassessed"}
        if rec and is_current(project, key[0], rec,field=C.field_pointer("coefficients",key[1],"p")):
            coefficient = rec["data"]["payload"].get("coefficients", {}).get(key[1], {})
            row["p_raw"] = coefficient.get("p")
            signatures[key[0]] = C.signature(rec)
            if row["p_raw"] is not None:
                row["status"] = "computed"
        rows.append(row)
    complete = bool(rows) and all(r["status"] == "computed" for r in rows)
    # Do not silently omit failed or unavailable tests and shrink the family.
    if complete:
        for row, adjusted in zip(rows, adjust_pvalues([r["p_raw"] for r in rows], method=method)):
            row.update(p_adjusted=adjusted, reject=adjusted <= alpha)
    payload = {"target": {"kind": "test_family", "id": family_id, "results": signatures},
               "method": method, "independent": {"tests": rows}, "tolerance": {"alpha": alpha,"decision_rule":"p_adjusted <= alpha"},
               "observed": {"family_size": len(rows), "complete": complete}, "reason": rationale, "layers": ["method"]}
    rid = f"multiplicity:{family_id}"
    prev = project.latest("validation_result", rid)
    record = C.make_record("validation_result", rid, payload, producer=_producer(), status="passed" if complete else "unassessed",
                           revision=prev["revision"] + 1 if prev else 1)
    project.append("validation_result", record, enforce_transition=False)
    return {"record": rid, "status": record["status"], "tests": rows}


def _ordered_time(values, time_format=None):
    """Order numeric time or explicitly interpretable dates, never guess an ambiguous locale."""
    from decimal import Decimal,InvalidOperation
    from datetime import datetime
    raw=list(values)
    if any(not str(value).strip() for value in raw):raise ValueError("time ordering has missing time values")
    try:
        keys=[Decimal(str(value)) for value in raw]
        if not all(k.is_finite() for k in keys):raise ValueError("time values must be finite")
        return keys,"numeric"
    except InvalidOperation:pass
    try:
        keys=[datetime.strptime(str(value),time_format) if time_format else datetime.fromisoformat(str(value).replace("Z","+00:00")) for value in raw]
        if len({k.tzinfo is None for k in keys})>1:raise ValueError("mixed known/unknown timezones")
        sorted(keys)
        return keys,"declared format" if time_format else "ISO-8601"
    except (ValueError,TypeError) as exc:
        raise ValueError("declare an unambiguous time format/timezone or a custom validator") from exc


def prediction_validation(project, spec_id, *, target, predictors, split, group=None, time_column=None,
                          test_fraction=0.2, seed=7, ridge=0.0):
    """Independent linear prediction with explicit random/group/time splitting.

    This is a reusable linear baseline. Other estimators use the open validator
    adapter. Means/scales are learned on training rows only; held-out rows and
    omitted cases are retained in the receipt.
    """
    import numpy as np
    import pandas as pd
    import execution as EX
    spec = M.load_spec(project, spec_id)["data"]
    if not 0 < test_fraction < 1 or ridge < 0 or not predictors or target in predictors:
        raise ValueError("declare predictors, a valid split fraction and nonnegative ridge")
    fit = next(i for i in spec["inputs"] if i["role"] in ("fit", "train"))
    with EX.protected(project, spec) as bindings:
        frame = pd.read_csv(project.root / fit["dataset"], sep="\t" if Path(fit["dataset"]).suffix.lower()==".tsv" else ",",dtype=str,keep_default_na=False)
        for column in [target,*predictors]:frame[column]=frame[column].replace("",np.nan).astype(float)
        required = [target, *predictors, *fit["keys"]] + ([group] if group else []) + ([time_column] if time_column else [])
        complete=frame.dropna(subset=list(dict.fromkeys(required)))
        identity=[*fit["keys"],*([group] if group else []),*([time_column] if time_column else [])]
        valid=complete.loc[(complete[identity]!="").all(axis=1)]
        if valid.empty:
            raise ValueError("no complete prediction observations")
        if not np.isfinite(valid[[target,*predictors]].to_numpy(dtype=float)).all():raise ValueError("prediction inputs contain nonfinite numbers")
        rng = np.random.default_rng(seed)
        if split == "time":
            if not time_column:
                raise ValueError("time split needs a time column")
            keys,ordering=_ordered_time(valid[time_column],spec.get("time_format"))
            times=sorted(set(keys));rank={k:i for i,k in enumerate(times)}
            positions=__import__("pandas").Series([rank[k] for k in keys],index=valid.index)
            cut = max(1, int(len(times)*(1-test_fraction)))
            train = valid[positions<cut]
            test = valid[positions>=cut]
            basis = {"time": time_column,"ordering":ordering, "train_max": str(times[cut-1]), "test_min": str(times[cut]) if cut<len(times) else None}
        elif split == "group":
            if not group:
                raise ValueError("group split needs a group/individual identifier")
            groups = valid[group].unique().copy()
            rng.shuffle(groups)
            cut = max(1, int(len(groups)*(1-test_fraction)))
            train = valid[valid[group].isin(groups[:cut])]
            test = valid[valid[group].isin(groups[cut:])]
            basis = {"group": group, "overlap": sorted(set(train[group]) & set(test[group]))}
        elif split == "random":
            unit_keys = (spec.get("n_semantics") or {}).get("unit_keys") or fit["keys"]
            if valid.duplicated(unit_keys).any():
                raise ValueError("repeated units require group or time splitting")
            order = rng.permutation(len(valid))
            cut = max(1, int(len(valid)*(1-test_fraction)))
            train, test = valid.iloc[order[:cut]], valid.iloc[order[cut:]]
            basis = {"seed": seed}
        else:
            raise ValueError("choose random/group/time or use a custom validation adapter")
        if train.empty or test.empty:
            raise ValueError("the declared split produced an empty training or held-out set")
        if split=="group":
            unit_keys=(spec.get("n_semantics") or {}).get("unit_keys") or fit["keys"]
            if set(map(tuple,train[unit_keys].values)) & set(map(tuple,test[unit_keys].values)):
                raise ValueError("independent observational units leak across the chosen group split")
        train_x, test_x = train[predictors].astype(float).to_numpy(), test[predictors].astype(float).to_numpy()
        means, scales = train_x.mean(axis=0), train_x.std(axis=0)
        scales[scales == 0] = 1
        X = np.column_stack([np.ones(len(train)), (train_x-means)/scales])
        Xtest = np.column_stack([np.ones(len(test)), (test_x-means)/scales])
        y = train[target].to_numpy(dtype=float)
        if ridge:
            penalty = np.diag([0, *([ridge]*len(predictors))])
            beta = np.linalg.solve(X.T @ X + penalty, X.T @ y)
        else:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        train_predictions, predictions = X @ beta, Xtest @ beta
        truth = test[target].to_numpy(dtype=float)
        metrics = {"train_rmse": float(np.sqrt(np.mean((train_predictions-y)**2))),
                   "test_rmse": float(np.sqrt(np.mean((predictions-truth)**2))),
                   "test_mae": float(np.mean(np.abs(predictions-truth)))}
        payload = {"target": {"kind": "prediction", "model": spec_id}, "method": "held-out linear baseline",
                   "independent": {"bindings": bindings, "coefficients": beta.tolist()}, "tolerance": {},
                   "observed": {"split": split, "basis": basis, "train_keys": train[fit["keys"]].astype(str).values.tolist(),
                                "test_keys": test[fit["keys"]].astype(str).values.tolist(),
                                "dropped_keys": frame.loc[~frame.index.isin(valid.index), fit["keys"]].astype(str).values.tolist(),
                                "training_means": means.tolist(), "training_scales": scales.tolist(),
                                "test_observed": truth.tolist(), "test_predictions": predictions.tolist(), **metrics},
                   "layers": ["method"], "reason": "evaluation performance, not a causal or population-validity certificate"}
    rid = f"prediction:{spec_id}"
    prev = project.latest("validation_result", rid)
    record = C.make_record("validation_result", rid, payload, producer=_producer(), status="passed", revision=prev["revision"] + 1 if prev else 1)
    project.append("validation_result", record, enforce_transition=False)
    return {"record": rid, "status": record["status"], **metrics}


def independent_check(project, spec_id, *, validator, fields, tolerance=None, shared_layers=()):
    """Run a bound independent implementation for any declared result shape.

    validator(project, spec) returns recomputed fields, never the reference
    result. Fields and tolerances are fixed before execution and retained.
    """
    import numpy as np
    import execution as EX
    spec = M.load_spec(project, spec_id)["data"]
    result = project.latest("model_result", spec_id)
    if not M.current_result(project, result):
        raise ValueError("independent validation requires a current executed result")
    if isinstance(validator, str):
        path, function = validator.rsplit(":", 1)
        path = Path(path)
        validator = M._load_callable(str(path if path.is_absolute() else project.root / path) + ":" + function, "validator")
    fields = list(fields)
    if not fields:
        raise ValueError("declare the exact result fields to validate")
    tolerance = dict(tolerance or {"atol": 1e-8, "rtol": 1e-6})
    if set(tolerance) != {"atol", "rtol"} or any(not np.isfinite(v) or v < 0 for v in tolerance.values()):
        raise ValueError("declare finite nonnegative atol/rtol before validation")
    with EX.protected(project, spec, validator) as bindings:
        recomputed = validator(project, spec)
    reference = result["data"]["payload"]
    checks = []
    from decimal import Decimal, InvalidOperation, localcontext
    for field in fields:
        actual, expected = reference, recomputed
        try:
            actual,expected=C.field_value(actual,field),C.field_value(expected,field)
            a, b = np.asarray(actual, dtype=object), np.asarray(expected, dtype=object)
            if a.shape != b.shape or not a.size:
                raise ValueError("numeric validation requires nonempty arrays with identical shapes")
            pairs=[(Decimal(str(x)),Decimal(str(y))) for x,y in zip(a.flat,b.flat)]
            with localcontext() as context:
                context.prec=max(50,max(len(x.as_tuple().digits)+len(y.as_tuple().digits)+abs(x.adjusted()-y.adjusted())+8 for x,y in pairs if x.is_finite() and y.is_finite()) if all(x.is_finite() and y.is_finite() for x,y in pairs) else 50)
                ok=all(x.is_finite() and y.is_finite() and abs(x-y)<=Decimal(str(tolerance["atol"]))+Decimal(str(tolerance["rtol"]))*abs(y) for x,y in pairs)
                difference=str(max(abs(x-y) for x,y in pairs)) if all(x.is_finite() and y.is_finite() for x,y in pairs) else "nonfinite"
        except (KeyError, TypeError, ValueError, InvalidOperation):
            ok, difference = False, None
        checks.append({"field": field, "ok": bool(ok), "max_absolute_difference": difference})
    passed = bool(checks) and all(c["ok"] for c in checks) and not shared_layers
    payload = {"target": {"model": spec_id, "parameter": spec["result"]["target_parameter"],
                           "result_signature": C.signature(result), "result_revision": result["revision"]},
               "method": "independent declared adapter", "independent": {"values": recomputed, "bindings": bindings,
                                                                          "shared": list(shared_layers)},
               "tolerance": tolerance, "observed": {"checks": checks, "validated_fields":fields, "outcome": "passed" if passed else "failed"},
               "layers": ["numeric"], "reason": "shared layers do not establish independence" if shared_layers else ""}
    rid = f"val:{spec_id}:{spec['result']['target_parameter']}"
    prev = project.latest("validation_result", rid)
    record = C.make_record("validation_result", rid, payload, producer=_producer(),
                           status="passed" if passed else "failed", revision=prev["revision"] + 1 if prev else 1,
                           input_refs=[{"kind": "model_result", "id": result["id"], "signature": C.signature(result)}])
    project.append("validation_result", record, enforce_transition=False)
    return {"validation": rid, "status": record["status"], "checks": checks}


# ---------------------------------------------------------------------------
# specification stability (T21) - gated on a passed validation (T22)
# ---------------------------------------------------------------------------
VARIANTS = ("drop_control", "alt_link", "subsample", "winsorize",
            "cluster", "lag")


def _variant_specs(spec: Mapping, variants: Iterable[str]) -> list[dict]:
    out = []
    for variant in variants:
        clone = json.loads(json.dumps(spec))
        if isinstance(variant, Mapping):
            name = variant["name"]
            clone.update(variant.get("patch") or {})
        else:
            name = str(variant)
        clone["id"] = f"{spec['id']}::{name}"
        clone["variation_of"] = spec["id"]
        clone["variation"] = name
        if isinstance(variant, Mapping):
            out.append(clone)
            continue
        if name == "drop_control":
            controls = clone["variables"].get("controls") or []
            if controls:
                clone["variables"]["controls"] = controls[:-1]
            else:
                clone["variant_disposition"] = {"status": "not_applicable", "reason": "the registered specification contains no controls"}
        elif name == "alt_link":
            if clone["family"] == "logit":
                clone["family"] = "probit"
            elif clone["family"] == "probit":
                clone["family"] = "logit"
            else:
                clone["variant_disposition"] = {"status": "not_applicable", "reason": "the built-in link comparison applies to logit/probit; supply a custom variant for other estimators"}
        elif name == "subsample":
            clone["subsample"] = {"fraction": 0.8, "seed": 7}
        elif name == "winsorize":
            clone["winsorize"] = {"column": clone["variables"]["y"],
                                  "limits": [0.01, 0.99]}
        elif name == "cluster":
            if clone.get("cluster"):
                clone["cov_type"] = "cluster"
            else:
                clone["variant_disposition"] = {"status": "needs_data", "reason": "cluster identifiers and design justification are required"}
        elif name == "lag":
            if clone.get("time") and clone.get("lag_columns"):
                clone["lag_transform"] = {"time": clone["time"], "columns": clone["lag_columns"],
                                          "groups": clone.get("lag_groups", []), "periods": clone.get("lag_periods", 1)}
            else:
                clone["variant_disposition"] = {"status": "needs_data", "reason": "time, lag columns and within-unit ordering are required"}
        else:
            clone["variant_disposition"] = {"status": "unsupported", "reason": "declare a custom patch/runner for this requested variation"}
        out.append(clone)
    return out


def _prepare_variant(project: C.Project, spec: Mapping) -> dict:
    """Apply a variation to the data and return a re-bound spec."""
    import pandas as pd
    import numpy as np
    spec = json.loads(json.dumps(spec))
    fit = next(i for i in spec["inputs"] if i["role"] in ("fit", "train"))
    original_fit = fit
    frame = pd.read_csv(project.root / fit["dataset"],sep="\t" if Path(fit["dataset"]).suffix.lower()==".tsv" else ",",dtype=str,keep_default_na=False)
    if spec.get("subsample"):
        part = spec["subsample"]
        frame = frame.sample(frac=part["fraction"],
                             random_state=part["seed"]).sort_index()
    if spec.get("winsorize"):
        w = spec["winsorize"]
        col = w["column"]
        frame[col]=frame[col].replace("",np.nan).astype(float)
        lo, hi = np.nanquantile(frame[col], w["limits"])
        frame[col] = frame[col].clip(lo, hi)
    if spec.get("lag_transform"):
        lag = spec["lag_transform"]
        order = list(lag["groups"]) + [lag["time"]]
        keys,_=_ordered_time(frame[lag["time"]],spec.get("time_format"))
        time_key="__erp_time_order__"
        while time_key in frame.columns:time_key+="_"
        frame[time_key]=keys
        normalized_order=[*lag["groups"],time_key]
        if frame.duplicated(normalized_order).any():
            raise ValueError("lag ordering is ambiguous: duplicate unit/time keys")
        frame = frame.sort_values(normalized_order, kind="stable")
        for column in lag["columns"]:
            frame[column] = (frame.groupby(lag["groups"], sort=False)[column].shift(lag["periods"])
                             if lag["groups"] else frame[column].shift(lag["periods"]))
        frame=frame.drop(columns=[time_key])
    rel = f"output/v2/variants/{C.canonical_hash(spec['id'])}.csv"
    path = C.protect_output(project,rel)
    import txn
    txn._write_atomic(path,frame.to_csv(index=False).encode("utf-8"))
    fit = dict(fit)
    fit["dataset"] = rel
    fit["sha256"] = C.file_sha256(path)
    fit["variation"] = spec.get("variation")
    spec["inputs"] = [fit if i is original_fit else i
                      for i in spec["inputs"]]
    return spec


def summarise_stability(rows: list[Mapping], base_estimate) -> dict:
    """Pure summary of a variation table (used by :func:`stability`)."""
    estimates = [r["estimate"] for r in rows
                 if isinstance(r.get("estimate"), (int, float)) and r.get("status","estimated")=="estimated"]
    signs = {1 if e > 0 else (-1 if e < 0 else 0) for e in estimates}
    sign_flip = len(signs) > 1
    ci_cross = []
    for r in rows:
        ci = r.get("ci") or {}
        if ci.get("ci_low") is not None and ci["ci_low"] <= 0 <= ci["ci_high"]:
            ci_cross.append(r["variant"])
    return {"base_estimate": base_estimate, "estimates": estimates,
            "range": [min(estimates), max(estimates)] if estimates else None,
            "sign_flip": sign_flip, "ci_crosses_zero": ci_cross,
            "fragile": bool(sign_flip or (ci_cross and
                                          len(ci_cross) == len(rows))),
            "n_variants": len(rows)}


def stability(project: C.Project, spec_id: str,
              variants: Iterable[str] = VARIANTS) -> dict:
    spec_rec = M.load_spec(project, spec_id)
    spec = spec_rec["data"]
    val = project.latest("validation_result", f"val:{spec_id}:"
                         f"{spec['result']['target_parameter']}")
    if not is_current(project, spec_id):
        raise SystemExit("specification stability requires a passed "
                         "independent numeric validation first (T22 before T21)")
    base = project.latest("model_result", str(spec["id"]))
    base_est = ((base or {}).get("data", {}).get("payload") or {}).get("estimate")
    rows = []
    for variant in variants:
        for clone in _variant_specs(spec, [variant]):
            disposition = clone.get("variant_disposition")
            if disposition:
                rows.append({"variant": clone["variation"], **disposition})
                if disposition["status"] == "needs_data":
                    import gaps
                    gaps.open_gap(project, target=f"model:{spec_id}", requirement=f"{clone['variation']}: {disposition['reason']}",
                                  status_detail="search original materials before deciding this variant is unavailable")
                continue
            try:
                clone = _prepare_variant(project, clone)
                M.register(project, clone)
                out = M.fit(project, clone["id"])
                validation = (independent_ols(project, clone["id"]) if clone["family"] == "ols" else
                              independent_logit(project, clone["id"]) if clone["family"] == "logit" else
                              {"status": "unassessed", "reason": "supply a model-appropriate independent validator"})
            except (M.ModelError, ValueError, OSError) as exc:
                rows.append({"variant": variant, "status": "failed",
                             "error": str(exc)})
                continue
            rec = project.latest("model_result", out["result"])
            result = (rec["data"]["payload"] if rec else None) or None
            comparison=compare_results(project,base["id"],rec["id"]) if rec and M.current_result(project,rec) else {"comparable":False,"reason":"no current result"}
            rows.append({"variant": variant,
                         "status": out["status"] if comparison["comparable"] else "incomparable",
                         "comparability":comparison,
                         "numeric_validation": validation,
                         "estimate": (result or {}).get("estimate"),
                         "ci": ((result or {}).get("coefficients") or {}).get(
                             spec["result"]["target_parameter"], {}),
                         "n": (result or {}).get("n")})
    summary = summarise_stability(rows, base_est)
    payload = {
        "target": {"kind": "stability", "spec": spec_id,
                   "parameter": spec["result"]["target_parameter"]},
        "method": "specification variation",
        "independent": {"variants": rows},
        "tolerance": {"kind": "none",
                      "reason": "stability is a range, not a numeric identity"},
        "observed": summary,
        "layers": ["method"],
        "reason": "",
    }
    fragile = summary["fragile"]
    assessed = any(r.get("status") == "estimated" for r in rows) and all(
        r.get("status") == "not_applicable" or r.get("status")=="estimated" and r.get("numeric_validation", {}).get("status") == "passed" for r in rows)
    rec = C.make_record("validation_result", f"stability:{spec_id}", payload,
                        producer=_producer(),
                        status="passed" if assessed and not fragile else "unassessed")
    prev = project.latest("validation_result", rec["id"])
    if prev is not None:
        rec = C.make_record("validation_result", rec["id"], payload,
                            producer=_producer(), status=rec["status"],
                            revision=prev["revision"] + 1)
    project.append("validation_result", rec, enforce_transition=False)
    return {"record": rec["id"], "range": summary["range"],
            "sign_flip": summary["sign_flip"], "fragile": fragile,
            "n_variants": len(rows), "status": rec["status"]}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="independent validation")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ols", "logit"):
        p = sub.add_parser(name)
        p.add_argument("--spec", required=True)
        p.add_argument("--shared-preprocessing", action="store_true")
    p_s = sub.add_parser("stability")
    p_s.add_argument("--spec", required=True)
    p_s.add_argument("--variant", action="append")
    p_s.add_argument("--variants-json", help="custom named spec patches; not a closed family list")
    p_check = sub.add_parser("check")
    p_check.add_argument("--spec", required=True)
    p_check.add_argument("--validator", required=True)
    p_check.add_argument("--field", action="append", required=True)
    p_check.add_argument("--atol", type=float, default=1e-8)
    p_check.add_argument("--rtol", type=float, default=1e-6)
    p_multi = sub.add_parser("multiplicity")
    p_multi.add_argument("--family", required=True)
    p_multi.add_argument("--tests", required=True)
    p_multi.add_argument("--rationale", required=True)
    p_multi.add_argument("--method", default="holm")
    p_pred = sub.add_parser("prediction")
    p_pred.add_argument("--spec", required=True)
    p_pred.add_argument("--target", required=True)
    p_pred.add_argument("--predictor", action="append", required=True)
    p_pred.add_argument("--split", required=True, choices=["random", "group", "time"])
    p_pred.add_argument("--group")
    p_pred.add_argument("--time-column")
    p_pred.add_argument("--test-fraction", type=float, default=0.2)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd in ("ols", "logit"):
        func = independent_ols if args.cmd == "ols" else independent_logit
        res = func(proj, args.spec,
                   shared_preprocessing=args.shared_preprocessing)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["status"] == "passed" else 2
    if args.cmd == "stability":
        variants = json.loads(Path(args.variants_json).read_text(encoding="utf-8")) if args.variants_json else args.variant or VARIANTS
        res = stability(proj, args.spec, variants)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["status"] == "passed" else 2
    if args.cmd == "check":
        res = independent_check(proj, args.spec, validator=args.validator, fields=args.field,
                                tolerance={"atol": args.atol, "rtol": args.rtol})
    elif args.cmd == "multiplicity":
        res = multiple_comparisons(proj, args.family, tests=json.loads(Path(args.tests).read_text(encoding="utf-8")),
                                   rationale=args.rationale, method=args.method)
    elif args.cmd == "prediction":
        res = prediction_validation(proj, args.spec, target=args.target, predictors=args.predictor, split=args.split,
                                    group=args.group, time_column=args.time_column, test_fraction=args.test_fraction)
    else:
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["status"] == "passed" else 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
