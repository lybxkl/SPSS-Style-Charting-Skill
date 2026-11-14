# -*- coding: utf-8 -*-
"""Open model registry: specs, multi-input roles, conditions, typed results.

The registry organises work; it is not a ceiling.  A spec names:

* the **family** and estimator (statsmodels or a callable you supply);
* **inputs by role** - fit / train / validate / test / calibrate / parameters /
  constraints / initial / boundary - each bound to a dataset *version* and the
  keys actually used.  A second file is a second role, not a second column in
  the same table;
* the **result form** (coefficient, marginal effect, prediction, optimum,
  trajectory...) with its target parameter, unit, scale, denominator, time
  scope and group, so nothing is forced into a coefficient table;
* the **N semantics**: for statistical models N comes from the observed unit of
  the fit input (never the sum of rows across tables); a mathematical model with
  no sampling notion records dimensions and constraints instead of inventing N.

Execution success, numeric validation and allowed conclusions are three
different flags and are stored separately.

CLI::

    python models.py --root . register --spec specs/m1.json
    python models.py --root . fit --spec M1
    python models.py --root . conditions --spec M1
    python models.py --root . solve --spec OPT1
    python models.py --root . show --spec M1
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C
import execution as EX

_ACTIVE_EXECUTION = ContextVar("model_execution", default=None)


def statistical(spec):
    return spec.get("family") in STAT_FAMILIES or (spec.get("n_semantics") or {}).get("kind") == "observation" or ("family" not in spec and bool(spec.get("design_features")))

ROLES = ("fit", "train", "validate", "test", "calibrate", "parameters",
         "constraints", "initial", "boundary", "weights", "offset")

STAT_FAMILIES = {
    "ols": "statsmodels.OLS",
    "logit": "statsmodels.Logit",
    "probit": "statsmodels.Probit",
    "poisson": "statsmodels.Poisson",
    "negbin": "statsmodels.NegativeBinomial",
    "quantile": "statsmodels.QuantReg",
    "mixedlm": "statsmodels.MixedLM",
    "gee": "statsmodels.GEE",
}

MATH_FAMILIES = ("lp", "milp", "nonlinear", "ode", "simulation", "custom")

SOLVE_QUALITIES = ("infeasible", "unbounded", "timeout", "feasible",
                   "local_optimum", "certified_global", "not_run", "error")


def _producer(**kw) -> dict:
    return C.producer_for("models", version="2.0", module_file=__file__, **kw)


class ModelError(Exception):
    pass


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
def validate_spec(spec: Mapping) -> dict:
    """Reject specs that cannot produce an honest result."""
    spec = dict(spec)
    for key in ("id", "family", "purpose"):
        if not spec.get(key):
            raise ModelError(f"spec needs {key}")
    family = spec["family"]
    if not isinstance(family, str) or not family.strip():
        raise ModelError("family must name the selected mathematical/statistical implementation")
    inputs = spec.get("inputs") or []
    if not isinstance(inputs, list) or not inputs:
        raise ModelError("spec.inputs must be a non-empty list of roles")
    inputs = [dict(item) for item in inputs]
    seen_fit = False
    for item in inputs:
        if not isinstance(item.get("role"), str) or not item["role"].strip():
            raise ModelError("each input needs an explicit role")
        for key in ("dataset", "sha256"):
            if not item.get(key):
                raise ModelError(f"input {item.get('role')} needs {key}")
        if statistical(spec) and item["role"] in ("fit", "train", "validate", "test") and not item.get("keys"):
            raise ModelError("statistical observation inputs need their actual keys")
        item.setdefault("keys", [])
        if item["role"] in ("fit", "train"):
            seen_fit = True
    if statistical(spec):
        if not seen_fit:
            raise ModelError("a statistical spec needs a fit or train input")
        n_sem = spec.get("n_semantics") or {}
        if n_sem.get("kind") != "observation":
            raise ModelError("statistical models need n_semantics.kind=observation")
        if not n_sem.get("unit"):
            raise ModelError("n_semantics.unit is required (the unit of "
                             "observation, e.g. one firm)")
        if not spec.get("result"):
            raise ModelError("statistical models need a result description")
        res = spec["result"]
        for key in ("type", "target_parameter", "unit", "scale"):
            if not res.get(key):
                raise ModelError(f"result needs {key}")
    else:
        n_sem = spec.get("n_semantics") or {"kind": "none"}
        if n_sem.get("kind") != "none":
            raise ModelError("a mathematical model must declare "
                             "n_semantics.kind=none; it has no sampling N")
        for key in ("dimensions", "constraints"):
            if key not in spec or spec[key] is None:
                raise ModelError(f"mathematical models need {key}")
        spec["n_semantics"] = n_sem
    spec["inputs"] = [dict(i) for i in inputs]
    spec.setdefault("result", {"type": "native_result", "target_parameter": "objective",
                                "unit": "declared_in_native_result", "scale": "declared_in_native_result"})
    return spec


def _spec_path(project: C.Project, spec_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_"
                   for ch in spec_id)
    return project.path("models", "specs", f"{safe[:80]}-{C.canonical_hash(spec_id)[:16]}.json")


def register(project: C.Project, spec: Mapping) -> dict:
    spec = validate_spec(spec)
    spec["project_root"] = str(project.root)
    rid = str(spec["id"])
    C.atomic_write_json(_spec_path(project, rid), spec)
    command=(spec.get("executor") or {}).get("command") or []
    engine=spec.get("engine") or (Path(command[0]).name if command else "Python adapter" if spec.get("runner") else
                                 "statsmodels" if spec["family"] in STAT_FAMILIES else "scipy" if spec["family"] in MATH_FAMILIES else "unselected adapter")
    payload = {
        "family": spec["family"],
        "engine": {"name": engine, "version": spec.get("engine_version") or EX.environment()["packages"].get(engine) or "unreported",
                   "adapter": spec.get("runner")},
        "question": spec.get("purpose") or spec.get("question") or "",
        "inputs": spec["inputs"],
        "requirements": {"variables": spec.get("variables", {}),
                         "n_semantics": spec.get("n_semantics"),
                         "assumptions": spec.get("assumptions", []),
                         "conditions_checked": False},
        "execution": {"status": "not_run"},
        "numerical_validation": {"status": "not_run"},
        "method_assessment": {"status": "not_assessed",
                              "assumptions": spec.get("assumptions", [])},
        "claim_scope": {"allowed": spec.get("claim_scope", {}),
                        "forbidden": spec.get("forbidden_claims", [])},
        "target_parameter": str((spec.get("result") or {}).get(
            "target_parameter") or ""),
        "unit": str((spec.get("result") or {}).get("unit") or ""),
        "scale": str((spec.get("result") or {}).get("scale") or ""),
        "sample_accounting": spec.get("n_semantics"),
        "diagnostics_expected": spec.get("diagnostics_expected", []),
        "gaps": spec.get("gaps", []),
        "spec_sha256": C.canonical_hash(spec),
    }
    prev = project.latest("model_spec", rid)
    rec = C.make_record("model_spec", rid, payload, producer=_producer(),
                        status="ready",
                        revision=(prev["revision"] + 1) if prev else 1)
    project.append("model_spec", rec, enforce_transition=False)
    return rec


def load_spec(project: C.Project, spec_id: str) -> dict:
    rec = project.latest("model_spec", spec_id)
    if rec is None:
        raise ModelError(f"unknown spec {spec_id}")
    path = _spec_path(project, spec_id)
    if not path.is_file():
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in spec_id)
        path = project.path("models", "specs", f"{safe}.json")
    if not path.is_file():
        raise ModelError("the registered full specification is missing; restore it or re-register, never reconstruct an incomplete model")
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("id") != spec_id or rec["data"].get("spec_sha256") != C.canonical_hash(spec):
        raise ModelError("specification file changed without re-registration")
    return {"id": rec["id"], "revision": rec["revision"], "data": spec,
            "record": rec}


def _update_spec(project: C.Project, spec_id: str, *,
                 patch: Mapping, status: str) -> dict:
    rec = project.latest("model_spec", spec_id)
    payload = dict(rec["data"])
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    new = C.make_record("model_spec", spec_id, payload, producer=_producer(),
                        status=status, revision=rec["revision"] + 1)
    project.append("model_spec", new)
    return new


# ---------------------------------------------------------------------------
# conditions
# ---------------------------------------------------------------------------
def _read_dataset(project: C.Project, rel: str) -> "Any":
    import pandas as pd
    path = project.root / rel
    if not path.is_file():
        raise ModelError(f"dataset missing: {rel}")
    # Identifiers, codes and categories retain exact lexical identity. Numeric
    # conversion happens only for the explicitly selected model variables.
    return pd.read_csv(path, sep="\t" if path.suffix.lower()==".tsv" else ",", dtype=str, keep_default_na=False)


def conditions(project: C.Project, spec_id: str) -> dict:
    spec = load_spec(project, spec_id)["data"]
    findings = []

    def add(check: str, ok: bool, detail: str, severity: str = "error"):
        findings.append({"check": check, "ok": bool(ok), "detail": detail,
                         "severity": severity})

    for item in spec["inputs"]:
        rel = item["dataset"]
        try:
            path = project.root / rel
            actual = C.file_sha256(path) if path.is_file() else None
        except OSError:
            actual = None
        add(f"input_exists[{item['role']}]", actual is not None,
            f"{rel} not found")
        if actual is not None:
            add(f"input_version[{item['role']}]", actual == item["sha256"],
                f"{rel} sha {actual[:12]} vs bound {item['sha256'][:12]}; "
                f"re-bind before fitting")
            if item["role"] in ("fit", "train", "validate", "test",
                                 "calibrate", "weights"):
                try:
                    if spec.get("conditions_runner"):
                        continue
                    frame = _read_dataset(project, rel)
                    missing = [k for k in item["keys"]
                               if k not in frame.columns]
                    add(f"keys[{item['role']}]", not missing,
                        f"missing keys {missing}")
                except (ModelError,ValueError,OSError,UnicodeError) as exc:
                    add(f"readable[{item['role']}]", False, str(exc))
            else:
                add(f"role_is_not_data[{item['role']}]", True,
                    "parameters/constraints/initial/boundary inputs are not "
                    "parsed as tables")
    fit_input = next((i for i in spec["inputs"]
                      if i["role"] in ("fit", "train")), None)
    if spec.get("conditions_runner"):
        target=spec["conditions_runner"];filename,name=target.rsplit(":",1)
        path=Path(filename);path=path if path.is_absolute() else project.root/path
        checker=_load_callable(str(path)+":"+name,"conditions")
        with EX.protected(project,spec,checker):
            report=checker(project,spec)
        checks=report.get("checks",[]) if isinstance(report,dict) else []
        if not checks or any(type(check.get("ok")) is not bool or not check.get("check") for check in checks):
            raise ModelError("conditions adapter must report actual named boolean checks, not a self-declared ready status")
        for check in checks:add("adapter:"+check["check"],check["ok"],str(check.get("detail","")))
    if fit_input and spec["family"] in STAT_FAMILIES and not spec.get("conditions_runner"):
        try:
            frame = _read_dataset(project, fit_input["dataset"])
        except ModelError as exc:
            return {"spec": spec_id, "ok": False,
                    "findings": findings + [{"check": "fit_input", "ok": False,
                                             "detail": str(exc),
                                             "severity": "error"}]}
        need = spec.get("variables") or {}
        for name, column in need.items():
            columns = column if isinstance(column, list) else [column]
            missing_cols = [c for c in columns if c not in frame.columns]
            add(f"variable[{name}]", not missing_cols,
                f"columns missing: {missing_cols}")
        keys = fit_input["keys"]
        if all(k in frame.columns for k in keys):
            dup = int(frame.duplicated(subset=keys).sum())
            add("unique_observed_unit", dup == 0,
                f"{dup} duplicated key rows; N must count independent units")
            n = int(frame.drop_duplicates(subset=keys).shape[0])
            params = 1 + sum(len(v) if isinstance(v, list) else 1
                             for k, v in need.items() if k != "y")
            add("n_above_parameters", n > params,
                f"N={n}, parameters={params}; a saturated model has no "
                f"residual degrees of freedom", severity="warning")
            add("positive_n", n > 0, f"N={n}")
        if need:
            outcome = need.get("y")
            if outcome and outcome in frame.columns:
                values = frame[outcome]
                add("outcome_variation", values.nunique(dropna=True) > 1,
                    "outcome has no variation")
                add("outcome_parsable", True, "checked at fit time")
        missing_rates = {c: round(float((frame[c].isna() | frame[c].eq("")).mean()), 4)
                         for c in frame.columns}
        add("missing_declared", True,
            json.dumps(missing_rates, ensure_ascii=False), severity="info")
    ok = all(f["ok"] for f in findings if f["severity"] == "error")
    return {"spec": spec_id, "ok": ok, "findings": findings}


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------
def _design(frame, variables: Mapping):
    import numpy as np
    y_col = variables.get("y")
    x_cols = variables.get("x") or []
    controls = variables.get("controls") or []
    import statsmodels.api as sm
    data = frame[[y_col] + list(x_cols) + list(controls)].copy()
    data = data.replace("", np.nan).astype(float)
    dropped = int(data.isna().any(axis=1).sum())
    data = data.dropna()
    X = sm.add_constant(data[list(x_cols) + list(controls)], has_constant="add")
    return data[y_col].to_numpy(), X, data, dropped


def _execute_bound(project, spec_id, operation, *, runner=None, tag="", budget_seconds=None):
    spec_rec = load_spec(project, spec_id)
    spec = spec_rec["data"]
    token = None
    try:
        with EX.protected(project, spec, runner) as before:
            token = _ACTIVE_EXECUTION.set({**before, "status": "running"})
            if runner is not None or spec.get("runner") or spec.get("executor"):
                out = _fit_external(project, spec_rec, runner=runner, tag=tag)
            elif operation == "solve":
                out = _solve_impl(project, spec_id, tag=tag, budget_seconds=budget_seconds)
            else:
                out = _fit_impl(project, spec_id, tag=tag)
        rec = project.latest("model_result", out["result"])
        payload = dict(rec["data"])
        payload["computation"] = {**before, "status": "checked", "finished_at": C._now()}
        sealed = C.make_record("model_result", rec["id"], payload, producer=_producer(),
                               status=rec["status"], revision=rec["revision"] + 1,
                               input_refs=rec["input_refs"])
        project.append("model_result", sealed)
        return out
    except Exception as exc:
        rec = _write_result(project, spec, spec_rec,
                            {"execution": {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, "result": None},
                            status="failed", tag=tag)
        _update_spec(project, spec_id, status="failed", patch={"execution": {"status": "failed", "error": str(exc)}})
        return {"result": rec["id"], "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if token is not None:
            _ACTIVE_EXECUTION.reset(token)


def fit(project: C.Project, spec_id: str, *, runner: Callable | None = None, tag: str = "") -> dict:
    spec = load_spec(project, spec_id)["data"]
    if not statistical(spec):
        return solve(project, spec_id, runner=runner, tag=tag)
    return _execute_bound(project, spec_id, "fit", runner=runner, tag=tag)


def _fit_external(project, spec_rec, *, runner, tag):
    spec = spec_rec["data"]
    cond = conditions(project, spec["id"])
    if not cond["ok"]:
        raise ModelError(f"adapter conditions failed: {cond['findings']}")
    result, receipt = EX.run_adapter(project, spec, runner)
    if not isinstance(result, dict):
        raise ModelError("adapter must return a structured result mapping")
    for key in ("type", "target_parameter", "unit", "scale"):
        if not result.get(key):
            raise ModelError(f"adapter result needs {key}")
    if any(result.get(k) != spec["result"].get(k) for k in ("target_parameter", "unit", "scale")):
        raise ModelError("adapter output semantics do not match the registered result")
    if statistical(spec) and (isinstance(result.get("n"),bool) or not isinstance(result.get("n"), int) or result["n"] <= 0):
        raise ModelError("statistical adapter must report actual estimation N")
    if statistical(spec):
        tabular=[i for i in spec["inputs"] if i["role"] in ("fit","train") and Path(i["dataset"]).suffix.lower() in (".csv",".tsv")]
        if len(tabular)==len([i for i in spec["inputs"] if i["role"] in ("fit","train")]) and result["n"]>sum(len(_read_dataset(project,i["dataset"])) for i in tabular):
            raise ModelError("reported N exceeds all actual fitting rows")
    if not statistical(spec) and result.get("n") is not None:
        raise ModelError("mathematical adapter must not invent sampling N")
    if result.get("native_path"):
        native = C.protect_output(project, result["native_path"])
        if not native.is_file() or native in {Path(project.root / i["dataset"]).resolve() for i in spec["inputs"]}:
            raise ModelError("native output is absent or aliases an input")
        result["native_path"] = str(native)
        result["native_sha256"] = C.file_sha256(native)
    rec = _write_result(project, spec, spec_rec,
                        {"execution": {"status": "success", "receipt": receipt}, "result": result}, status="produced", tag=tag)
    _update_spec(project, spec["id"], status="completed", patch={"execution": {"status": "success"}, "result_id": rec["id"]})
    return {"result": rec["id"], "status": "estimated" if statistical(spec) else result.get("solve_quality", "produced"), "estimate": result.get("estimate")}


def _fit_impl(project: C.Project, spec_id: str, *, runner: Callable | None = None,
              tag: str = "") -> dict:
    spec_rec = load_spec(project, spec_id)
    spec = spec_rec["data"]
    cond = conditions(project, spec_id)
    if not cond["ok"]:
        rec = _write_result(project, spec, spec_rec, {
            "execution": {"status": "blocked", "detail": "conditions not met",
                          "conditions": cond},
            "result": None}, status="unvalidated")
        _update_spec(project, str(spec["id"]), status="insufficient_data",
                     patch={"execution": {"status": "blocked",
                                          "reason": "conditions not met"},
                            "assessment": {"conditions": cond["findings"]}})
        return {"result": rec["id"], "status": "blocked", "conditions": cond}
    if spec["family"] in MATH_FAMILIES:
        return solve(project, spec_id, runner=runner, tag=tag)
    fit_input = next(i for i in spec["inputs"] if i["role"] in ("fit", "train"))
    frame = _read_dataset(project, fit_input["dataset"])
    variables = spec["variables"]
    y, X, used, dropped = _design(frame, variables)
    import statsmodels.api as sm
    family = spec["family"]
    attempts = []
    params = {}
    try:
        if spec["result"].get("type") != "coefficient_table" or spec["result"].get("parameterization","raw") != "raw":
            raise ModelError("builtin fitting returns raw coefficients; select a runner for another output/parameterization")
        if str(spec["result"].get("scale","")).lower() in ("or","odds_ratio","odds ratio","irr","incidence_rate_ratio","marginal_effect","standardized_beta"):
            raise ModelError("a transformed result needs an actual transformation adapter, not a relabelled raw coefficient")
        active = [i for i in spec["inputs"] if i["role"] in ("fit", "train")]
        if len(active) != 1:
            raise ModelError("the builtin estimator needs one fit input; declare a runner/executor to combine multiple fit inputs explicitly")
        if any(i["role"] in ("weights", "offset") for i in spec["inputs"]) or any(spec.get(k) is not None for k in ("weights", "offset")):
            raise ModelError("weights/offset require an explicitly selected runner/executor; builtin fitting must not silently ignore them")
        if family == "ols":
            model = sm.OLS(y, X)
        elif family == "logit":
            model = sm.Logit(y, X)
        elif family == "probit":
            model = sm.Probit(y, X)
        elif family == "poisson":
            model = sm.Poisson(y, X)
        elif family == "negbin":
            model = sm.NegativeBinomial(y, X)
        elif family == "quantile":
            model = sm.QuantReg(y, X)
            params["q"] = float(spec.get("quantile", 0.5))
        elif family in ("mixedlm", "gee"):
            group_column = spec.get("groups")
            if not group_column or group_column not in frame.columns:
                raise ModelError(f"{family} requires a declared groups column")
            groups = frame.loc[used.index, group_column]
            if groups.isna().any():
                raise ModelError("group identity missing in fitted observations")
            if family == "mixedlm":
                model = sm.MixedLM(y, X, groups=groups)
            else:
                family_name = spec.get("distribution", "Gaussian")
                covariance = spec.get("cov_struct", "Exchangeable")
                if not hasattr(sm.families, family_name) or not hasattr(sm.cov_struct, covariance):
                    raise ModelError("declare an available GEE distribution and covariance structure")
                model = sm.GEE(y, X, groups=groups, family=getattr(sm.families, family_name)(),
                               cov_struct=getattr(sm.cov_struct, covariance)())
        else:
            raise ModelError(f"family {family} needs a custom runner")
        started = time.time()
        if family == "gee":
            res = model.fit(maxiter=200)
        elif family == "mixedlm":
            res = model.fit(reml=spec.get("reml", True), disp=False)
        elif family == "quantile":
            res = model.fit(q=params["q"])
        elif family == "negbin":
            res = model.fit(disp=0, maxiter=200)
        else:
            fit_kwargs = {"disp": 0, "maxiter": 200}
            if spec.get("cov_type"):
                fit_kwargs["cov_type"] = spec["cov_type"]
                if spec["cov_type"] == "cluster":
                    cluster = spec.get("cluster")
                    if not cluster or cluster not in frame.columns:
                        raise ModelError("cluster covariance needs a declared cluster column")
                    fit_kwargs["cov_kwds"] = {"groups": frame.loc[used.index, cluster]}
            res = model.fit(**fit_kwargs)
        elapsed = round(time.time() - started, 3)
        ci = res.conf_int()
        coefs = {name: {"estimate": float(res.params[name]),
                        "se": float(res.bse[name]),
                        "ci_low": float(ci.loc[name, 0]),
                        "ci_high": float(ci.loc[name, 1]),
                        "p": float(res.pvalues[name])}
                 for name in res.params.index}
        result = {
            "type": "coefficient_table",
            "native_parameter_scale":"log_odds" if family=="logit" else "latent_probit" if family=="probit" else "log_rate" if family in ("poisson","negbin") else "outcome_units",
            "target_parameter": spec["result"]["target_parameter"],
            "unit": spec["result"]["unit"],
            "scale": spec["result"]["scale"],
            "estimate": coefs.get(str(spec["result"]["target_parameter"]),
                                  {}).get("estimate"),
            "coefficients": coefs,
            "n": int(res.nobs),
            "n_dropna": int(dropped),
            "sample_unit": spec["n_semantics"]["unit"],
            "time_scope": spec["result"].get("time_scope"),
            "group": spec["result"].get("group"),
            "denominator": spec["result"].get("denominator"),
            "interval": {"level": 0.95, "kind": "confidence"},
            "fit_statistics": {"llf": float(getattr(res, "llf", float("nan"))),
                               "aic": float(getattr(res, "aic", float("nan"))),
                               "r2": float(getattr(res, "rsquared",
                                                   float("nan")))},
            "diagnostics": _diagnostics(res, family),
            "elapsed_s": elapsed,
            "engine": {"name": "statsmodels", "version": sm.__version__,
                       "family": STAT_FAMILIES[family]},
        }
        import numpy as np
        diagnostics = result["diagnostics"]
        diagnostics.update(design_rank=int(np.linalg.matrix_rank(X.to_numpy())),
                           parameter_count=int(X.shape[1]), missing_counts={c: int((frame[c].isna() | frame[c].eq("")).sum()) for c in used.columns},
                           n_dropna=int(dropped), estimation_rows=len(used),
                           residual_summary={"mean": float(np.mean(np.asarray(getattr(res, "resid", y - res.predict())))),
                                             "n": len(used)},
                           epv_or_power={"status": "reported", "method": "observed sample and parameter accounting; no post-hoc power proof",
                                         "observations": len(used), "parameters": X.shape[1]},
                           missing_strategy={"method": "complete_case", "dropped": dropped})
        unit_keys = (spec.get("n_semantics") or {}).get("unit_keys") or fit_input["keys"]
        result["n_unit"] = len(frame.loc[used.index].drop_duplicates(subset=unit_keys))
        result["used_keys"] = frame.loc[used.index, fit_input["keys"]].astype(str).values.tolist()
        if spec.get("cluster"):
            diagnostics["cluster_count"] = int(frame.loc[used.index, spec["cluster"]].nunique())
            diagnostics["cluster_robust_or_mixed"] = spec.get("cov_type") == "cluster" or family in ("mixedlm", "gee")
        if family in ("mixedlm", "gee"):
            diagnostics["within_unit_structure"] = {"method": family, "groups": spec["groups"],
                                                     "covariance": spec.get("cov_struct", "random_intercept" if family == "mixedlm" else "Exchangeable")}
            diagnostics["unit_count"] = int(frame.loc[used.index, spec["groups"]].nunique())
            diagnostics["cluster_count"] = diagnostics["unit_count"]
            diagnostics["cluster_robust_or_mixed"] = True
        diagnostics["converged"] = bool(getattr(res, "converged", diagnostics.get("converged", True)))
        if not all(np.isfinite(c["estimate"]) for c in coefs.values()):
            raise ModelError("estimator produced a nonfinite coefficient")
        attempts.append({"op": "fit", "ok": True, "elapsed_s": elapsed})
    except Exception as exc:                    # noqa: BLE001
        result = None
        attempts.append({"op": "fit", "ok": False,
                         "error": f"{type(exc).__name__}: {exc}"})
    payload = {"execution": {"status": "success" if result else "failed",
                             "attempts": attempts,
                             "conditions_ok": True},
               "result": result,
               "spec_snapshot": {k: spec[k] for k in
                                 ("id", "family", "variables", "result")}}
    status = "produced" if result else "failed"
    rec = _write_result(project, spec, spec_rec, payload, status=status,
                        tag=tag)
    _update_spec(project, str(spec["id"]),
                 status="completed" if result else "failed",
                 patch={"execution": payload["execution"],
                        "result_id": rec["id"]})
    return {"result": rec["id"], "status": "estimated" if result else "failed",
            "estimate": (result or {}).get("estimate"), "attempts": attempts}


def _diagnostics(res, family: str) -> dict:
    out = {"converged": bool(getattr(res, "mle_retvals", {}).get("converged",
                                                                 True))
           if hasattr(res, "mle_retvals") else True}
    try:
        out["condition_number"] = float(res.condition_number)
    except Exception:                            # noqa: BLE001
        pass
    if family == "logit":
        try:
            pred = res.predict()
            out["separation_warning"] = bool(((pred < 1e-8) | (pred >
                                                               1 - 1e-8)).any())
        except Exception:                        # noqa: BLE001
            pass
    return out


def _write_result(project: C.Project, spec: Mapping, spec_rec: Mapping,
                  payload: Mapping, *, status: str, tag: str = "") -> dict:
    unavailable = []
    def finite_or_missing(value, path=""):
        if isinstance(value, float) and not math.isfinite(value):
            unavailable.append(path)
            return None
        if isinstance(value, dict):
            return {k: finite_or_missing(v, f"{path}.{k}") for k,v in value.items()}
        if isinstance(value, (list, tuple)):
            return [finite_or_missing(v, f"{path}[{i}]") for i,v in enumerate(value)]
        return value
    result = finite_or_missing(payload.get("result") or {})
    if unavailable:
        result["unassessed_fields"] = unavailable
    spec_result = spec.get("result") or {}
    estimate = result.get("estimate")
    conformant = {
        "model": str(spec["id"]),
        "result_type": result.get("type") or "none",
        "payload": {**result, "execution": payload.get("execution")},
        "computation": _ACTIVE_EXECUTION.get() or {"status": "unbound"},
        "scale": str(result.get("scale") or spec_result.get("scale") or ""),
        "target_parameter": str(result.get("target_parameter")
                                or spec_result.get("target_parameter") or ""),
        "unit": str(result.get("unit") or spec_result.get("unit") or ""),
        "sample_scope": {
            "kind": "observation" if result.get("n") is not None else "none",
            "n": result.get("n"),
            "unit": result.get("sample_unit") or spec_result.get("sample_unit"),
            "n_dropna": result.get("n_dropna"),
            "n_unit": result.get("n_unit"), "used_keys": result.get("used_keys"),
            "note": "n is the estimated sample; n_dropna is only the rows "
                    "removed for missing data (V-05)",
        },
    }
    if estimate is not None:
        conformant["estimate"] = repr(estimate) if not isinstance(estimate, str) \
            else estimate
    for key in ("interval", "denominator", "time_scope", "group"):
        if result.get(key) is not None:
            conformant[key] = result[key]
    if result.get("native_path"):
        conformant["native_path"] = result["native_path"]
        conformant["native_sha256"] = result.get("native_sha256")
    rid = f"{spec['id']}:{tag}" if tag else str(spec["id"])
    prev = project.latest("model_result", rid)
    rec = C.make_record("model_result", rid, conformant, producer=_producer(),
                        status=status,
                        revision=(prev["revision"] + 1) if prev else 1,
                        input_refs=[{"kind": "model_spec",
                                     "id": spec_rec["id"]}])
    project.append("model_result", rec, enforce_transition=False)
    return rec


def current_result(project, result):
    if result is None or result["status"] not in ("produced", "validated"):
        return False
    try:
        spec = load_spec(project, result["data"]["model"])["data"]
        computation = result["data"].get("computation") or {}
        native = result["data"].get("native_path")
        native_ok = not native or (Path(native).is_file() and C.file_sha256(native) == result["data"].get("native_sha256"))
        return native_ok and computation.get("status") == "checked" and EX.current(project, spec, computation)
    except (ModelError, C.ContractError):
        return False


# ---------------------------------------------------------------------------
# mathematical models
# ---------------------------------------------------------------------------
def _solve_core(payload: dict) -> dict:
    """Run one solve and return a JSON-serialisable state dict."""
    try:
        import numpy as np
        from scipy import optimize
        kind = payload["kind"]
        tol = float(payload.get("feasibility_tolerance", 1e-7))
        if not math.isfinite(tol) or tol <= 0:
            raise ModelError("feasibility tolerance must be finite and positive")
        if tol > 1e-7 and not payload.get("feasibility_tolerance_reason"):
            raise ModelError("a relaxed problem-specific tolerance needs a predeclared unit/scale justification")
        if kind == "ode":
            from scipy.integrate import solve_ivp
            rhs = _load_callable(payload["rhs"], "rhs")
            solution = solve_ivp(rhs, payload["t_span"], payload["y0"],
                                 t_eval=payload.get("t_eval"), rtol=payload.get("rtol", 1e-8),
                                 atol=payload.get("atol", 1e-10), method=payload.get("method", "RK45"))
            if not solution.success or not np.all(np.isfinite(solution.y)):
                return {"quality": "error", "message": solution.message}
            # A trajectory is a solution approximation, never an optimum.
            return {"quality": "feasible", "x": solution.y[:, -1].tolist(), "objective": None,
                    "trajectory": {"time": solution.t.tolist(), "values": solution.y.tolist()},
                    "diagnostics": {"nfev": solution.nfev, "rtol": payload.get("rtol", 1e-8),
                                    "atol": payload.get("atol", 1e-10)}, "message": solution.message}
        if kind in ("lp", "milp"):
            c = np.asarray(payload["c"], dtype=float)
            n = len(c)
            raw_bounds = payload.get("bounds") or [(0, None)] * n
            if len(raw_bounds) == 2 and all(v is None or isinstance(v, (int, float)) for v in raw_bounds):
                raw_bounds = [raw_bounds] * n
            lower = np.array([-np.inf if b[0] is None else b[0] for b in raw_bounds], dtype=float)
            upper = np.array([np.inf if b[1] is None else b[1] for b in raw_bounds], dtype=float)
            integrality = np.zeros(n, dtype=int)
            if kind == "milp":
                if "integrality" not in payload:
                    raise ModelError("MILP needs an explicit integrality vector (0 continuous, 1 integer, 2/3 semi-domain)")
                integrality = np.broadcast_to(np.asarray(payload["integrality"], dtype=int), (n,))
                if not np.isin(integrality, [0, 1, 2, 3]).all():
                    raise ModelError("invalid integrality domain")
                constraints = []
                for A, b, equal in ((payload.get("A_ub"), payload.get("b_ub"), False),
                                    (payload.get("A_eq"), payload.get("b_eq"), True)):
                    if A is not None:
                        constraints.append(optimize.LinearConstraint(A, b if equal else -np.inf, b))
                res = optimize.milp(c, integrality=integrality, bounds=optimize.Bounds(lower, upper),
                                    constraints=constraints, options={"mip_rel_gap": payload.get("mip_rel_gap", 0.0)})
            else:
                res = optimize.linprog(c, A_ub=payload.get("A_ub"), b_ub=payload.get("b_ub"),
                                        A_eq=payload.get("A_eq"), b_eq=payload.get("b_eq"),
                                        bounds=list(zip(lower, upper)), method="highs")
            quality = {2: "infeasible", 3: "unbounded", 1: "timeout"}.get(res.status, "error")
            certificate = {"solver_status": int(res.status), "primal_residual": None}
            if res.x is not None:
                x = np.asarray(res.x)
                semi_zero = np.isin(integrality, [2, 3]) & (np.abs(x) <= tol)
                violations = [0.0, *np.maximum(lower[~semi_zero] - x[~semi_zero], 0), *np.maximum(x - upper, 0)]
                if payload.get("A_ub") is not None:
                    violations.extend(np.maximum(np.asarray(payload["A_ub"]) @ x - payload["b_ub"], 0))
                if payload.get("A_eq") is not None:
                    violations.extend(np.abs(np.asarray(payload["A_eq"]) @ x - payload["b_eq"]))
                ints = np.isin(integrality, [1, 3])
                integer_error = float(np.max(np.abs(x[ints] - np.round(x[ints])), initial=0))
                residual = float(max(violations))
                feasible = bool(np.isfinite(x).all() and residual <= tol and integer_error <= tol)
                certificate.update(primal_residual=residual, integrality_error=integer_error)
                if feasible:
                    quality = "feasible"
                    if kind == "milp":
                        bound = getattr(res, "mip_dual_bound", None)
                        gap = getattr(res, "mip_gap", None)
                        certificate.update(dual_bound=bound, mip_gap=gap)
                        if res.status == 0 and bound is not None and abs(float(res.fun) - bound) <= tol * max(1, abs(res.fun)):
                            quality = "certified_global"
                    elif res.status == 0:
                        dual = 0.0
                        for rhs, marg in ((payload.get("b_ub", []), res.ineqlin.marginals),
                                          (payload.get("b_eq", []), res.eqlin.marginals),
                                          (lower, res.lower.marginals), (upper, res.upper.marginals)):
                            a = np.asarray(rhs, dtype=float)
                            finite = np.isfinite(a)
                            dual += float(a[finite] @ np.asarray(marg)[finite])
                        certificate.update(dual_objective=dual, duality_gap=abs(float(res.fun) - dual))
                        if certificate["duality_gap"] <= tol * max(1, abs(res.fun)):
                            quality = "certified_global"
                else:
                    quality = "error"
            return {"quality": quality, "x": res.x.tolist() if res.x is not None else None,
                    "objective": float(res.fun) if res.fun is not None else None,
                    "message": res.message, "status": int(res.status), "certificate": certificate}
        func = _load_callable(payload["objective"], "objective")
        x0 = payload.get("x0") or [0.0] * int(payload["dimensions"])
        constraints = []
        for item in payload.get("constraints", []):
            if item.get("type") not in ("eq", "ineq"):
                raise ModelError("nonlinear constraints need type=eq/ineq and an explicit fun")
            constraints.append({"type": item["type"], "fun": _load_callable(item["fun"], "constraint")})
        for A, b, kind_ in ((payload.get("A_ub"), payload.get("b_ub"), "ineq"),
                            (payload.get("A_eq"), payload.get("b_eq"), "eq")):
            if A is not None:
                constraints.append({"type": kind_, "fun": lambda x, A=np.asarray(A), b=np.asarray(b): b - A @ x})
        method = payload.get("method") or ("SLSQP" if constraints else "L-BFGS-B" if payload.get("bounds") else "BFGS")
        if constraints and method not in ("SLSQP", "trust-constr", "COBYLA", "COBYQA"):
            raise ModelError(f"{method} cannot honor these constraints")
        if payload.get("bounds") and method not in ("L-BFGS-B", "TNC", "SLSQP", "trust-constr", "Powell", "Nelder-Mead", "COBYLA", "COBYQA"):
            raise ModelError(f"{method} cannot honor bounds")
        res = optimize.minimize(func, x0, method=method, constraints=constraints,
                                bounds=payload.get("bounds"),
                                options={"maxiter": payload.get("maxiter", 1000)})
        violations = [0.0]
        for value, (lo, hi) in zip(res.x, payload.get("bounds") or [(None, None)] * len(res.x)):
            violations.extend([max(0, lo - value) if lo is not None else 0, max(0, value - hi) if hi is not None else 0])
        for item in constraints:
            values = np.atleast_1d(item["fun"](res.x))
            violations.extend(np.abs(values) if item["type"] == "eq" else np.maximum(-values, 0))
        feasible = bool(np.all(np.isfinite(res.x)) and max(violations) <= tol)
        quality = "local_optimum" if res.success and feasible else "feasible" if feasible else "error"
        return {"quality": quality, "x": list(res.x),
                "objective": float(res.fun), "message": res.message,
                "certificate": None,
                "diagnostics": {"primal_residual": float(max(violations)), "method": method, "success": bool(res.success)},
                "note": "first-order optimum only; no global certificate"}
    except BaseException as exc:                 # noqa: BLE001
        return {"quality": "error",
                "message": f"{type(exc).__name__}: {exc}"}


def _solve_timeout(payload: dict, budget: float) -> dict:
    """Run :func:`_solve_core` in a child process, enforcing a wall clock.

    A real OS process is used so a solver that hangs inside a C extension can
    still be stopped; the parent never shares state with it.
    """
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(payload, fh)
        payload_path = fh.name
    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "_worker", payload_path],
            capture_output=True, text=True, timeout=budget)
        if proc.returncode != 0:
            return {"quality": "error",
                    "message": (proc.stderr or proc.stdout or
                                f"worker exit {proc.returncode}")[-2000:]}
        for line in reversed(proc.stdout.strip().splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return {"quality": "error", "message": "worker printed no JSON result"}
    except subprocess.TimeoutExpired:
        return {"quality": "timeout", "message": f"exceeded {budget}s budget"}
    finally:
        try:
            os.unlink(payload_path)
        except OSError:
            pass


def _load_callable(target: str, name: str) -> Callable:
    if ":" not in target:
        raise ModelError(f"{name} must be 'path/to/file.py:function'")
    # rsplit, because a Windows path itself contains a colon (C:\...)
    path, func_name = target.rsplit(":", 1)
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise ModelError(f"{name} file not found: {path}")
    spec = importlib.util.spec_from_file_location(f"model_{name}", path)
    if spec is None or spec.loader is None:
        raise ModelError(f"cannot load {path} as a python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, func_name, None)
    if not callable(fn):
        raise ModelError(f"{target} is not callable")
    return fn


def solve(project: C.Project, spec_id: str, *, runner: Callable | None = None,
          tag: str = "", budget_seconds: float | None = None) -> dict:
    return _execute_bound(project, spec_id, "solve", runner=runner, tag=tag, budget_seconds=budget_seconds)


def _solve_impl(project: C.Project, spec_id: str, *, tag: str = "", budget_seconds=None) -> dict:
    spec_rec = load_spec(project, spec_id)
    spec = spec_rec["data"]
    cond = conditions(project, spec_id)
    if not cond["ok"]:
        rec = _write_result(project, spec, spec_rec,
                            {"execution": {"status": "blocked",
                                           "conditions": cond},
                             "result": None}, status="unvalidated")
        _update_spec(project, str(spec["id"]), status="insufficient_data",
                     patch={"execution": {"status": "blocked",
                                          "reason": "conditions not met"},
                            "assessment": {"conditions": cond["findings"]}})
        return {"result": rec["id"], "status": "blocked", "conditions": cond}
    params = dict(spec.get("parameters") or {})
    target = spec.get("target")
    if target and not params:
        # a problem builder is a real input: call it instead of trusting prose
        builder = _load_callable(target, "target")
        problem = builder()
        if not isinstance(problem, Mapping):
            raise ModelError(f"target {target!r} must return a problem mapping")
        params = dict(problem)
    budget = float(budget_seconds or spec.get("budget_seconds") or 30.0)
    kind = spec["family"]
    if kind not in ("lp", "milp", "nonlinear", "ode"):
        raise ModelError(f"{kind} requires a declared custom runner/executor; no silent algorithm substitution")
    payload = {**params, "kind": kind}
    for key in ("objective", "rhs"):
        if isinstance(payload.get(key), str) and ":" in payload[key]:
            path, name = payload[key].rsplit(":", 1)
            path = Path(path)
            payload[key] = str(path if path.is_absolute() else project.root / path) + ":" + name
    if kind in ("lp", "milp"):
        payload.setdefault("c", params.get("objective"))
    started = time.time()
    solved = _solve_timeout(payload, budget)
    timed_out = solved.get("quality") == "timeout"
    elapsed = round(time.time() - started, 3)
    quality = solved["quality"]
    dimensions = spec["dimensions"]
    expected_dimension = dimensions if isinstance(dimensions, int) else dimensions.get("variables") if isinstance(dimensions, dict) else None
    if solved.get("x") is not None and expected_dimension is not None and len(solved["x"]) != expected_dimension:
        quality = "error"
        solved["message"] = "declared decision/state dimension differs from the actual solution"
    result = {
        "type": "trajectory" if kind == "ode" else "optimization_solution" if kind == "nonlinear" else "mixed_integer_program" if kind == "milp" else "linear_program",
        "target_parameter": spec["result"].get("target_parameter"),
        "unit": spec["result"].get("unit"),
        "scale": spec["result"].get("scale"),
        "estimate": solved.get("objective"),
        "solution": solved.get("x"),
        "solve_quality": quality,
        "certificate": solved.get("certificate"),
        "n": None,
        "n_semantics": "none",
        "dimensions": spec["dimensions"],
        "constraints": spec["constraints"],
        "message": solved.get("message"),
        "elapsed_s": elapsed,
        "budget_seconds": budget,
        "diagnostics": solved.get("diagnostics", {}), "trajectory": solved.get("trajectory"),
    }
    payload_out = {"execution": {"status": "success" if quality not in
                                 ("error",) else "failed",
                                 "attempts": [{"op": "solve", "ok": quality not in
                                               ("error",), "elapsed_s": elapsed,
                                               "timed_out": timed_out}],
                                 "conditions_ok": True},
                   "result": result,
                   "spec_snapshot": {k: spec[k] for k in ("id", "family")}}
    rec = _write_result(project, spec, spec_rec, payload_out,
                        status="produced" if quality != "error" else "failed",
                        tag=tag)
    _update_spec(project, str(spec["id"]),
                 status="completed" if quality != "error" else "failed",
                 patch={"execution": payload_out["execution"],
                        "method_assessment": {"status": "assessed",
                                              "solve_quality": quality,
                                              "message": result["message"]},
                        "result_id": rec["id"]})
    return {"result": rec["id"], "status": quality,
            "objective": result["estimate"], "elapsed_s": elapsed}


def assert_conclusion_scope(project: C.Project, result_id: str,
                            claim: Mapping) -> dict:
    """Check a claimed conclusion against what the result actually supports."""
    rec = project.latest("model_result", result_id)
    if rec is None:
        raise ModelError(f"unknown result {result_id}")
    res = rec["data"]["payload"]
    scope = rec["data"].get("sample_scope") or {}
    if not res:
        return {"ok": False, "reason": "no result was produced"}
    problems = []
    if claim.get("causal") and res.get("type") != "experimental_effect":
        problems.append("result is not a causal design; causal wording is not "
                        "supported")
    if claim.get("global_optimum") and res.get("solve_quality") != \
            "certified_global":
        problems.append(f"solve quality is {res.get('solve_quality')}; only a "
                        f"certified global optimum supports 'best'")
    if claim.get("sample") and scope.get("n") is None:
        problems.append("result has no sampling N (mathematical model)")
    for key in ("unit", "denominator", "time_scope", "group"):
        if claim.get(key) and rec["data"].get(key) and \
                claim[key] != rec["data"][key]:
            problems.append(f"{key} claim {claim[key]!r} != result "
                            f"{rec['data'][key]!r}")
    return {"ok": not problems, "problems": problems,
            "allowed_scope": {"type": res.get("type"),
                              "solve_quality": res.get("solve_quality"),
                              "n": scope.get("n"),
                              "unit": rec["data"].get("unit"),
                              "denominator": rec["data"].get("denominator")}}


def _main(argv: list[str]) -> int:
    if argv and argv[0] == "_worker":
        # internal: run one solve in a child process (see _solve_timeout)
        payload = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        print(json.dumps(_solve_core(payload), ensure_ascii=False))
        return 0
    ap = argparse.ArgumentParser(description="model registry")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_r = sub.add_parser("register")
    p_r.add_argument("--spec", required=True)
    p_f = sub.add_parser("fit")
    p_f.add_argument("--spec", required=True)
    p_f.add_argument("--tag", default="")
    p_c = sub.add_parser("conditions")
    p_c.add_argument("--spec", required=True)
    p_s = sub.add_parser("solve")
    p_s.add_argument("--spec", required=True)
    p_s.add_argument("--budget", type=float)
    p_s.add_argument("--tag", default="")
    p_v = sub.add_parser("show")
    p_v.add_argument("--spec", required=True)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "register":
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        print(json.dumps(register(proj, spec), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "conditions":
        res = conditions(proj, args.spec)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    if args.cmd == "fit":
        res = fit(proj, args.spec, tag=args.tag)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["status"] == "estimated" else 2
    if args.cmd == "solve":
        res = solve(proj, args.spec, tag=args.tag, budget_seconds=args.budget)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["status"] in ("certified_global", "local_optimum",
                                      "feasible", "infeasible",
                                      "unbounded", "timeout", "produced") else 2
    if args.cmd == "show":
        rec = load_spec(proj, args.spec)
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
