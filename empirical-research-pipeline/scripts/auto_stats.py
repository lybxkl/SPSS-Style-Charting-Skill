#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automatic descriptive and bivariate screening for an analysis CSV.

This is a first-pass screening pack, not the final paper model. It produces:
  - descriptives.csv / .md
  - group_tests.csv        (chi-square / Fisher / Mann-Whitney / Kruskal, with p_bh)
  - binary_rates.csv       (rates with Wilson CI by category)
  - correlations.csv       (Pearson/Spearman with p)
  - univariate_models.csv  (univariate logistic OR or OLS coefficient, including
                            dummy-coded multi-level categorical predictors)
  - univariate_skipped.csv (every silently skipped variable, with the stage and reason)
  - analysis_pack.md       (human-readable summary)

``--spec model_spec.json`` adds the independent multivariate layer (S-01):
  - coef_<model_id>.csv    (model,term,beta,se,ci_low,ci_high,p,or,or_low,or_high,
                            n,outcome,ref,note — directly consumable by
                            ``auto_chart_pack.py --coef``)
  - model_summary.md       (reference groups, separation actions, fit statistics)
  - separation_report.csv  (empty cells found before fitting; --separation drop|merge|error)

Final, pre-specified models still belong in SPSS or a dedicated model script; this
entry point exists so the multivariate step is reproducible from the same CSV.

Sections (``--only`` / ``--sections``): descriptives, group_tests, binary_rates,
correlations, univariate, models, vif, roc. Groups: screen = the first five,
models = models+vif+roc, all = everything.

Usage:
    python auto_stats.py --data data/analysis.csv --config assets/chart_config.example.json --out output/analysis_pack
    python auto_stats.py --data data/analysis.csv --spec model_spec.json --out output/analysis_pack
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis_utils import (  # noqa: E402
    apply_filter, encode_binary, is_constant, is_id_like, outcome_kind,
    read_csv_auto, same_values, fmt, fmt_p,
)

try:
    import statsmodels.api as sm
except ImportError:  # pragma: no cover
    sm = None


# ---------------------------------------------------------------------------
# Limits and section bookkeeping (documented in references/08-analysis-expansion.md)
# ---------------------------------------------------------------------------
DEFAULT_MAX_PREDICTORS = 0    # 0 = no count limit; positive budgets must be explicit
DEFAULT_MAX_MODELS = 0

SECTION_ORDER = ("descriptives", "group_tests", "binary_rates", "correlations",
                 "univariate", "models", "vif", "roc")
SECTION_GROUPS = {
    "all": SECTION_ORDER,
    "screen": ("descriptives", "group_tests", "binary_rates", "correlations", "univariate"),
    "models": ("models", "vif", "roc"),
}

# Tables are always written with these headers, even when empty (S-09: an empty
# univariate_skipped.csv used to disappear, so a reader could not tell "nothing
# was skipped" from "the run never got there").
TABLE_COLUMNS = {
    "descriptives": ["variable", "type", "n", "missing", "mean", "sd", "median",
                     "p25", "p75", "min", "max", "levels", "rate_ci"],
    "group_tests": ["outcome", "predictor", "test", "statistic_name", "statistic",
                    "p", "p_bh", "effect", "n", "note"],
    "binary_rates": ["predictor", "level", "n", "events", "rate", "ci_low", "ci_high"],
    "correlations": ["var1", "var2", "method", "r", "p", "n"],
    "univariate_models": ["outcome", "predictor", "model", "effect", "ci_low",
                          "ci_high", "p", "p_bh", "n", "metric", "se_type", "ref"],
    "univariate_skipped": ["stage", "outcome", "predictor", "reason", "n", "events",
                           "min_cell"],
    "separation_report": ["variable", "level", "n", "events", "action"],
    "coef": ["model", "term", "type", "beta", "se", "beta_ci_low", "beta_ci_high",
             "p", "or", "or_low", "or_high", "ci_low", "ci_high", "metric",
             "estimate", "n", "n_events", "outcome", "ref", "note", "se_type",
             "sample"],
    "coef_all": ["model", "label", "term", "type", "beta", "se", "p", "stars",
                 "or", "or_low", "or_high", "ci_low", "ci_high", "metric",
                 "estimate", "n", "n_events", "sample", "outcome", "ref", "se_type"],
    "fit": ["model", "type", "n", "k", "n_events", "loglik", "llr", "llr_df",
            "llr_p", "pseudo_r2", "aic", "bic", "se_type", "subset", "n_dropna"],
    "vif": ["model", "term", "vif", "n_predictors", "note"],
    "roc": ["model", "auc", "ci_low", "ci_high", "n", "n_events", "method", "reps",
            "note"],
}

# Forbidden in filter_query: ``@`` rebinds names to the caller's locals, ``__``
# reaches dunder attributes, and import/exec/eval/lambda are code execution.
FORBIDDEN_QUERY = re.compile(r"(@|__|\bimport\b|\bexec\b|\beval\b|\blambda\b|;)")


class SpecError(ValueError):
    """A model spec or CLI option is not usable (maps to exit code 2)."""


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Kept numerically identical to ``pubfig.wilson_ci`` (same expression order,
    same clamp to ``p``) so a rate in this pack and the same rate drawn on a
    figure cannot disagree; ``tests/test_stats_charts.py`` asserts equality.

    Parameters
    ----------
    k: number of events. ``n``: number of trials. ``z``: normal quantile.
    Returns ``(low, high)`` or ``(nan, nan)`` when ``n <= 0``.
    """
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, min(center - half, p)), min(1.0, max(center + half, p)))


def bh_adjust(pvals) -> np.ndarray:
    """Benjamini-Hochberg adjusted p values (NaN for non-finite inputs)."""
    p = np.asarray(list(pvals), dtype=float)
    out = np.full(p.shape, np.nan, dtype=float)
    ok = np.isfinite(p)
    m = int(ok.sum())
    if m == 0:
        return out
    idx = np.where(ok)[0]
    order = idx[np.argsort(p[idx])]
    ranks = np.arange(1, m + 1, dtype=float)
    adj = p[order] * m / ranks
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    out[order] = np.clip(adj, 0.0, 1.0)
    return out


def validate_filter_query(query) -> None:
    """Reject a filter_query that could execute code or reach the caller's scope.

    ``analysis_utils.apply_filter`` hands the string straight to
    ``DataFrame.query``; pandas' eval engine resolves ``@name`` against the
    caller's locals and ``__`` dunders against objects, so an untrusted query is
    an injection vector. This guard is applied before the filter runs (S-10).
    """
    if not query:
        return
    text = str(query)
    hit = FORBIDDEN_QUERY.search(text)
    if hit:
        raise ValueError(
            f"filter_query 含被禁止的记号 {hit.group(0)!r}（禁止 @ 变量注入、__ 访问、"
            f"import/exec/eval/lambda 与分号）；请改用简单比较或 filter 字典：{text[:120]}")


def parse_sections(value) -> set | None:
    """Parse ``--only/--sections`` into a set of section names."""
    if not value:
        return None
    parts = [p.strip().lower() for p in re.split(r"[,;\s]+", str(value)) if p.strip()]
    if not parts:
        return None
    chosen: list[str] = []
    for part in parts:
        if part in SECTION_GROUPS:
            chosen.extend(SECTION_GROUPS[part])
        elif part in SECTION_ORDER:
            chosen.append(part)
        else:
            raise ValueError(f"未知的 section: {part!r}；可选："
                             + ", ".join(list(SECTION_GROUPS) + list(SECTION_ORDER)))
    return set(chosen)


def write_table(path: str, table: pd.DataFrame | None, columns: list[str]) -> None:
    """Write a CSV with a fixed header even when there is no row."""
    frame = table if isinstance(table, pd.DataFrame) else pd.DataFrame()
    cols = list(columns) + [c for c in frame.columns if c not in columns]
    frame.reindex(columns=cols).to_csv(path, index=False, encoding="utf-8-sig")


def audit_skip(audit, stage: str, outcome: str, predictor: str, reason: str,
               n=None, events=None, min_cell=None) -> None:
    """Record one silently skipped variable so it shows up in univariate_skipped.csv."""
    if audit is None:
        return
    audit.append({"stage": stage, "outcome": outcome, "predictor": predictor,
                  "reason": reason, "n": n, "events": events, "min_cell": min_cell})


def is_binary(s: pd.Series) -> bool:
    v = pd.to_numeric(s, errors="coerce").dropna()
    return not v.empty and set(np.unique(v)).issubset({0, 1})


def infer_columns(df: pd.DataFrame, cfg: dict, max_categories: int = 12):
    drop = set(cfg.get("drop", []))
    time_col = cfg.get("time") or next((c for c in df.columns if re.search(r"year|年份|时间", c, re.I)), None)
    group_col = cfg.get("group") or next((c for c in df.columns if re.search(r"category|crime|group|类别|案由", c, re.I)), None)
    treatment_col = cfg.get("treatment") or next((c for c in df.columns if re.search(r"stage|treatment|处理|阶段", c, re.I)), None)
    # The outcome is resolved once in resolve_outcome() (S-12: this used to be
    # duplicated here with a different failure mode).
    outcome_col = cfg.get("outcome")

    binaries = [c for c in df.columns if c not in drop and is_binary(df[c])]
    if not outcome_col:
        outcome_col = next((c for c in binaries if 0.05 < df[c].mean() < 0.95), None)
    categorical = []
    numeric = []
    for c in df.columns:
        if c in drop or c in binaries:
            continue
        n = df[c].nunique(dropna=True)
        if is_id_like(c, df[c]):
            continue
        if df[c].dtype == object:
            if 2 <= n <= max_categories:
                categorical.append(c)
        elif 2 <= n <= max_categories:
            categorical.append(c)
        elif pd.to_numeric(df[c], errors="coerce").notna().sum() >= 10:
            numeric.append(c)
    if cfg.get("numeric"):
        numeric = [c for c in cfg["numeric"] if c in df.columns]
    if cfg.get("categorical"):
        categorical = [c for c in cfg["categorical"] if c in df.columns]
    if cfg.get("binary"):
        binaries = [c for c in cfg["binary"] if c in df.columns]
    from analysis_utils import apply_declared_roles
    numeric, categorical, binaries = apply_declared_roles(df, cfg, numeric, categorical, binaries)
    return time_col, group_col, treatment_col, outcome_col, numeric, categorical, binaries


def resolve_outcome(df: pd.DataFrame, cfg: dict):
    """Resolve config.outcome, else infer it deterministically.

    Returns ``(column, error_message, notes)`` (S-12: one code path, so the
    config path and the inference path cannot diverge). When several binary
    columns qualify, the first one in column order is used — the pre-existing
    behaviour — but the alternatives are returned as notes so the summary shows
    the choice instead of hiding it.
    """
    outcome_col = cfg.get("outcome")
    if outcome_col:
        if outcome_col not in df.columns:
            return None, f"outcome column not found: {outcome_col}", []
        return outcome_col, None, []
    # A bare `outcome` substring also matches `has_outcome` (an auxiliary flag)
    # and `outcome_len` (a count), which is how the default command ended up
    # picking a column nobody meant.  Keep the stem match, then require the
    # column to actually look like a binary outcome.
    regex_hits = [c for c in df.columns
                  if re.search(r"outcome_binary|outcome|target|结果|支持", c, re.I)
                  and not c.lower().startswith(("has_", "is_", "n_", "num_", "count_"))
                  and is_binary(df[c])
                  and not is_id_like(c, df[c])]
    if len(regex_hits) == 1:
        return regex_hits[0], None, []
    if len(regex_hits) > 1:
        return None, f"multiple outcome-like columns: {regex_hits}; pass config.outcome", []
    candidates = [c for c in df.columns
                  if is_binary(df[c])
                  and 0.05 < float(pd.to_numeric(df[c], errors="coerce").mean()) < 0.95
                  and not is_id_like(c, df[c])]
    if not candidates:
        return None, "no outcome column found; pass config.outcome", []
    notes = []
    if len(candidates) > 1:
        notes.append(f"outcome 自动选择为 `{candidates[0]}`（列序第一的 0/1 变量）；"
                     f"其他候选 {candidates[1:]}，如不对请传 config.outcome")
    return candidates[0], None, notes


def cramers_v(tab: pd.DataFrame) -> float:
    chi2 = stats.chi2_contingency(tab.values, correction=False)[0]
    n = tab.values.sum()
    r, k = tab.shape
    denom = n * (min(r - 1, k - 1))
    return float(math.sqrt(chi2 / denom)) if denom > 0 else float("nan")


def describe(df: pd.DataFrame, numeric: list[str], categorical: list[str]) -> pd.DataFrame:
    rows = []
    for c in numeric:
        s = pd.to_numeric(df[c], errors="coerce")
        s = s.dropna()
        rows.append({
            "variable": c, "type": "numeric", "n": len(s),
            "missing": len(df) - len(s), "mean": s.mean(), "sd": s.std(),
            "median": s.median(), "p25": s.quantile(.25), "p75": s.quantile(.75),
            "min": s.min(), "max": s.max(), "levels": "", "rate_ci": "",
        })
    for c in categorical:
        s = df[c].dropna().astype(str)
        vc = s.value_counts()
        rows.append({
            "variable": c, "type": "categorical", "n": len(s),
            "missing": len(df) - len(s), "mean": np.nan, "sd": np.nan,
            "median": np.nan, "p25": np.nan, "p75": np.nan,
            "min": np.nan, "max": np.nan,
            "levels": "; ".join(f"{k}:{v}" for k, v in vc.items()),
            "rate_ci": "",
        })
    return pd.DataFrame(rows)


def binary_rates(df: pd.DataFrame, outcome: str, categorical: list[str]) -> pd.DataFrame:
    rows = []
    for c in categorical:
        sub = df[[c, outcome]].dropna()
        for level, part in sub.groupby(c):
            y = pd.to_numeric(part[outcome], errors="coerce").dropna()
            if len(y) < 5:
                continue
            k, n = int(y.sum()), len(y)
            lo, hi = wilson_ci(k, n)
            rows.append({"predictor": c, "level": str(level), "n": n,
                         "events": k, "rate": k / n, "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows)


def group_tests(df: pd.DataFrame, outcome: str, categorical: list[str],
                numeric: list[str], kind: str, audit: list | None = None) -> pd.DataFrame:
    """Group comparisons; every skip is recorded in ``audit`` (S-08)."""
    rows = []
    for c in categorical:
        sub = df[[c, outcome]].dropna()
        if sub[c].nunique() < 2 or len(sub) < 10:
            audit_skip(audit, "group_tests", outcome, c,
                       "constant predictor or n<10", n=len(sub))
            continue
        if kind in {"binary", "categorical"}:
            tab = pd.crosstab(sub[c], sub[outcome])
            if tab.shape[0] < 2 or tab.shape[1] < 2:
                audit_skip(audit, "group_tests", outcome, c,
                           f"contingency table is {tab.shape[0]}x{tab.shape[1]}; no test",
                           n=len(sub))
                continue
            stat_name = "chi2"
            try:
                chi2, p, dof, expected = stats.chi2_contingency(tab, correction=False)
                test = "chi-square"
                effect = cramers_v(tab)
                # S-07: when Fisher replaces chi-square, the statistic must
                # change with it; otherwise the CSV mixes a chi2 value under a
                # "Fisher exact" label.
                small = int((expected < 5).sum())
                if tab.shape == (2, 2) and small:
                    fisher_or, p = stats.fisher_exact(tab)
                    chi2 = float(fisher_or)
                    stat_name = "Fisher OR"
                    test = "Fisher exact"
            except Exception as exc:  # pragma: no cover - defensive
                chi2, p, effect, test = np.nan, np.nan, np.nan, "failed"
                stat_name = ""
                audit_skip(audit, "group_tests", outcome, c,
                           f"test failed: {type(exc).__name__}: {exc}"[:160], n=len(sub))
            note = "Cramér's V"
            if kind == "categorical":
                note += "; multiclass outcome"
            small = int((np.asarray(tab.values, dtype=float) < 5).sum())
            if small:
                note += f"; {small} 个单元格计数<5"
            rows.append({"outcome": outcome, "predictor": c, "test": test,
                         "statistic_name": stat_name, "statistic": chi2, "p": p,
                         "effect": effect, "n": len(sub),
                         "note": note if test != "failed" else ""})
        else:
            groups = [pd.to_numeric(g[outcome], errors="coerce").dropna().values
                      for _, g in sub.groupby(c)]
            groups = [g for g in groups if len(g) >= 5]
            if len(groups) < 2:
                audit_skip(audit, "group_tests", outcome, c,
                           "fewer than 2 groups with n>=5", n=len(sub))
                continue
            try:
                stat, p = stats.kruskal(*groups)
                rows.append({"outcome": outcome, "predictor": c, "test": "Kruskal-Wallis",
                             "statistic_name": "H", "statistic": stat, "p": p,
                             "effect": np.nan, "n": len(sub), "note": "continuous outcome"})
            except Exception as exc:  # pragma: no cover - defensive
                audit_skip(audit, "group_tests", outcome, c,
                           f"test failed: {type(exc).__name__}: {exc}"[:160], n=len(sub))
    for c in numeric:
        sub = df[[c, outcome]].dropna()
        sub[c] = pd.to_numeric(sub[c], errors="coerce")
        sub = sub.dropna()
        if len(sub) < 10 or sub[c].nunique() < 2:
            audit_skip(audit, "group_tests", outcome, c,
                       "n<10 or constant predictor", n=len(sub))
            continue
        if kind == "binary":
            groups = [sub.loc[sub[outcome] == v, c].values for v in [0, 1]]
            groups = [g for g in groups if len(g) > 0]
            if len(groups) < 2:
                audit_skip(audit, "group_tests", outcome, c,
                           "one outcome group is empty", n=len(sub))
                continue
            try:
                stat, p = stats.mannwhitneyu(groups[0], groups[1], alternative="two-sided")
                rows.append({"outcome": outcome, "predictor": c, "test": "Mann-Whitney",
                             "statistic_name": "U", "statistic": stat, "p": p,
                             "effect": np.nan, "n": len(sub),
                             "note": "binary outcome; nonparametric"})
            except Exception as exc:  # pragma: no cover - defensive
                audit_skip(audit, "group_tests", outcome, c,
                           f"test failed: {type(exc).__name__}: {exc}"[:160], n=len(sub))
        elif kind == "categorical":
            groups = [pd.to_numeric(g[c], errors="coerce").dropna().values
                      for _, g in sub.groupby(outcome)]
            groups = [g for g in groups if len(g) >= 5]
            if len(groups) < 2:
                audit_skip(audit, "group_tests", outcome, c,
                           "fewer than 2 outcome groups with n>=5", n=len(sub))
                continue
            try:
                stat, p = stats.kruskal(*groups)
                rows.append({"outcome": outcome, "predictor": c, "test": "Kruskal-Wallis",
                             "statistic_name": "H", "statistic": stat, "p": p,
                             "effect": np.nan, "n": len(sub), "note": "multiclass outcome"})
            except Exception as exc:  # pragma: no cover - defensive
                audit_skip(audit, "group_tests", outcome, c,
                           f"test failed: {type(exc).__name__}: {exc}"[:160], n=len(sub))
        else:
            try:
                r, p = stats.pearsonr(sub[c], pd.to_numeric(sub[outcome], errors="coerce"))
                rows.append({"outcome": outcome, "predictor": c, "test": "Pearson r",
                             "statistic_name": "r", "statistic": r, "p": p,
                             "effect": r, "n": len(sub), "note": "continuous outcome"})
            except Exception as exc:  # pragma: no cover - defensive
                audit_skip(audit, "group_tests", outcome, c,
                           f"test failed: {type(exc).__name__}: {exc}"[:160], n=len(sub))
    if not rows:
        return pd.DataFrame()
    table = pd.DataFrame(rows)
    table["p_bh"] = bh_adjust(table["p"])
    return table.sort_values("p", na_position="last")


def correlations(df: pd.DataFrame, numeric: list[str], binaries: list[str],
                 audit: list | None = None) -> pd.DataFrame:
    """Pairwise correlations; ``method`` is Spearman when either side is skewed.

    The docstring always promised Spearman; the implementation only ever ran
    Pearson (S-13). Variables with |skew| > 2 now switch to Spearman and say so
    in the ``method`` column.
    """
    cols = [c for c in numeric + binaries if c in df.columns]
    cols = list(dict.fromkeys(c for c in cols if not is_constant(df[c])))
    rows = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            sub = df[[a, b]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(sub) < 10 or sub[a].nunique() < 2 or sub[b].nunique() < 2:
                audit_skip(audit, "correlations", "", f"{a} × {b}",
                           "n<10 or constant variable", n=len(sub))
                continue
            try:
                skew_a = float(pd.Series(sub[a]).skew())
                skew_b = float(pd.Series(sub[b]).skew())
                if (np.isfinite(skew_a) and abs(skew_a) > 2) or \
                        (np.isfinite(skew_b) and abs(skew_b) > 2):
                    r, p = stats.spearmanr(sub[a], sub[b])
                    method = "Spearman"
                else:
                    r, p = stats.pearsonr(sub[a], sub[b])
                    method = "Pearson"
                if np.isfinite(r):
                    rows.append({"var1": a, "var2": b, "method": method,
                                 "r": float(r), "p": float(p), "n": len(sub)})
            except Exception as exc:  # pragma: no cover - defensive
                audit_skip(audit, "correlations", "", f"{a} × {b}",
                           f"failed: {type(exc).__name__}: {exc}"[:160], n=len(sub))
    return pd.DataFrame(rows).sort_values("p", na_position="last") if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Univariate models
# ---------------------------------------------------------------------------
def _fit_with_warnings(build, fit_kwargs, sink=None):
    """Fit a model while recording the warnings statsmodels emits.

    Convergence failures ("Maximum Likelihood optimization failed to converge",
    perfect separation, Hessian inversion) used to be silenced with a blanket
    ``simplefilter("ignore")``: the table looked fine and the reader never knew
    the estimate was shaky.  Collect them instead and surface the texts.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = build()
        fitted = model.fit(**fit_kwargs)
    texts = [str(w.message) for w in caught
             if issubclass(w.category, (UserWarning, RuntimeWarning, Warning))]
    uniq = []
    for text in texts:
        if text not in uniq:
            uniq.append(text)
    if sink is not None and uniq:
        sink.extend(uniq)
    if uniq:
        print(f"warning: fit reported {len(uniq)}: {uniq[0][:160]}", file=sys.stderr)
    return fitted


def _fit_kwargs(cov: str | None, logit: bool) -> dict:
    kwargs = {"disp": 0} if logit else {}
    if cov:
        kwargs["cov_type"] = cov
    return kwargs


def univariate_models(df: pd.DataFrame, outcome: str, numeric: list[str],
                      binaries: list[str], kind: str,
                      categorical: list[str] | None = None,
                      audit: list | None = None,
                      reference_levels: dict | None = None,
                      cov: str | None = None,
                      max_predictors: int = DEFAULT_MAX_PREDICTORS):
    """Return (models, skipped_models).

    Parameters
    ----------
    df: analysis frame. outcome: outcome column. numeric / binaries: candidate
    continuous and 0/1 predictors. kind: ``binary``, ``continuous`` or
    ``categorical`` outcome. categorical: multi-level predictors, dummy-coded.
    audit: shared skip log (also receives this function's skips). 
    reference_levels: explicit ``{column: reference level}``; otherwise the most
    frequent level is the reference and it is written to the ``ref`` column
    (S-03: no longer the alphabetical first level).
    cov: ``HC0/HC1/HC3`` for robust SE (``--robust``); ``None`` keeps the model
    based SE. max_predictors: screening budget; omitted variables are logged
    instead of silently dropped.

    Perfect separation and empty cells are skipped, never reported as an OR.
    """
    local: list = []
    if sm is None:
        return pd.DataFrame(), pd.DataFrame()
    if kind == "categorical":
        audit_skip(local, "univariate", outcome, "(all)",
                   "multiclass outcome; use multinomial logit or collapse categories")
        if audit is not None:
            audit.extend(local)
        return pd.DataFrame(), pd.DataFrame(local)
    out = pd.to_numeric(df[outcome], errors="coerce")
    rows = []
    candidates = [c for c in numeric + binaries
                  if c != outcome and c in df.columns and not is_constant(df[c])]
    predictors = candidates[:max_predictors] if max_predictors > 0 else candidates
    for c in (candidates[max_predictors:] if max_predictors > 0 else []):
        audit_skip(local, "univariate", outcome, c,
                   f"not screened: predictor cap ({max_predictors}); raise --max-predictors")
    for c in predictors:
        sub = pd.DataFrame({outcome: out, c: pd.to_numeric(df[c], errors="coerce")}).dropna()
        if len(sub) < 20 or sub[c].nunique() < 2 or sub[outcome].nunique() < 2:
            audit_skip(local, "univariate", outcome, c,
                       "n<20, constant predictor, or single outcome level", n=len(sub))
            continue
        if kind == "binary":
            tab = pd.crosstab(sub[c], sub[outcome])
            if tab.shape == (2, 2) and (tab.values == 0).any():
                audit_skip(local, "univariate", outcome, c,
                           "perfect separation (empty 2x2 cell)", n=len(sub),
                           events=int(sub[outcome].sum()), min_cell=0)
                continue
        try:
            X = sm.add_constant(sub[[c]].astype(float))
            y = sub[outcome].astype(float)
            if kind == "binary":
                model = _fit_with_warnings(
                    lambda: sm.Logit(y, X), _fit_kwargs(cov, True))
            else:
                model = _fit_with_warnings(
                    lambda: sm.OLS(y, X), _fit_kwargs(cov, False))
            coef = model.params[c]
            lo, hi = model.conf_int().loc[c]
            se_type = cov or "nonrobust"
            if kind == "binary":
                if abs(coef) > 10 or (hi - lo) > 20 or not np.isfinite(coef):
                    audit_skip(local, "univariate", outcome, c,
                               f"unstable estimate (beta={coef:.2f}); possible separation",
                               n=len(sub), events=int(y.sum()))
                    continue
                rows.append({"outcome": outcome, "predictor": c, "model": "logit",
                             "effect": math.exp(coef), "ci_low": math.exp(lo),
                             "ci_high": math.exp(hi), "p": model.pvalues[c],
                             "n": len(sub), "metric": "OR", "se_type": se_type,
                             "ref": ""})
            else:
                rows.append({"outcome": outcome, "predictor": c, "model": "ols",
                             "effect": coef, "ci_low": lo, "ci_high": hi,
                             "p": model.pvalues[c], "n": len(sub), "metric": "beta",
                             "se_type": se_type, "ref": ""})
        except Exception as exc:
            audit_skip(local, "univariate", outcome, c,
                       f"{type(exc).__name__}: {exc}"[:200], n=len(sub))
            continue
    # Multi-level categorical predictors: dummy-code them so they are not
    # silently absent from the univariate screening table.
    reference_levels = reference_levels or {}
    for c in (categorical or []):
        if c == outcome or c in predictors or c not in df.columns or is_constant(df[c]):
            continue
        # S-04: drop missing values BEFORE astype(str); otherwise NaN becomes a
        # literal "nan" category that enters the model as a real level.
        non_null = df[c].dropna()
        levels = [str(v) for v in non_null.astype(str).value_counts().index]
        if len(levels) < 2:
            audit_skip(local, "univariate", outcome, c, "fewer than 2 levels", n=len(non_null))
            continue
        if len(levels) > 12:
            audit_skip(local, "univariate", outcome, c,
                       f"too many levels ({len(levels)}); recode before modeling",
                       n=len(non_null))
            continue
        ref = reference_levels.get(c)
        if not ref or str(ref) not in levels:
            ref = levels[0]
        sub = pd.DataFrame({"y": out, "g": non_null}).dropna()
        sub["g"] = sub["g"].astype(str)
        if len(sub) < 20 or sub["y"].nunique() < 2:
            audit_skip(local, "univariate", outcome, c,
                       "n<20 or single outcome level", n=len(sub))
            continue
        keep = [lvl for lvl in levels if lvl != ref]
        dummies = pd.DataFrame({lvl: (sub["g"] == lvl).astype(float) for lvl in keep})
        # Name the columns var[T.level] so a dummy OR is attributable in the CSV.
        dummies.columns = [f"{c}[T.{lvl}]" for lvl in keep]
        # S-02: pre-check empty cells for every dummy level before fitting.
        empty = []
        for lvl in levels:
            if lvl == ref:
                continue
            part = sub[sub["g"] == lvl]
            ev = int(part["y"].sum())
            if kind == "binary" and (ev == 0 or ev == len(part)):
                empty.append((lvl, len(part), ev))
        if empty:
            detail = "; ".join(f"{lvl}(n={n}, events={ev})" for lvl, n, ev in empty)
            audit_skip(local, "univariate", outcome, f"{c}[T.*]",
                       f"empty cell in level(s) {detail}; dummy model skipped",
                       n=len(sub), events=int(sub["y"].sum()), min_cell=0)
            continue
        try:
            X = sm.add_constant(dummies)
            y = sub["y"].astype(float)
            if kind == "binary":
                model = _fit_with_warnings(
                    lambda: sm.Logit(y, X), _fit_kwargs(cov, True))
            else:
                model = _fit_with_warnings(
                    lambda: sm.OLS(y, X), _fit_kwargs(cov, False))
            se_type = cov or "nonrobust"
            for term in dummies.columns:
                coef = model.params[term]
                lo, hi = model.conf_int().loc[term]
                if kind == "binary":
                    if abs(coef) > 10 or (hi - lo) > 20 or not np.isfinite(coef):
                        audit_skip(local, "univariate", outcome, term,
                                   f"unstable estimate (beta={coef:.2f}); possible separation",
                                   n=len(sub), events=int(y.sum()))
                        continue
                    rows.append({"outcome": outcome, "predictor": term,
                                 "model": "logit (dummy)", "effect": math.exp(coef),
                                 "ci_low": math.exp(lo), "ci_high": math.exp(hi),
                                 "p": model.pvalues[term], "n": len(sub),
                                 "metric": "OR", "se_type": se_type, "ref": ref})
                else:
                    rows.append({"outcome": outcome, "predictor": term,
                                 "model": "ols (dummy)", "effect": coef,
                                 "ci_low": lo, "ci_high": hi,
                                 "p": model.pvalues[term], "n": len(sub),
                                 "metric": "beta", "se_type": se_type, "ref": ref})
        except Exception as exc:
            audit_skip(local, "univariate", outcome, c,
                       f"dummy model: {type(exc).__name__}: {exc}"[:200], n=len(sub))
    if audit is not None:
        audit.extend(local)
    models = pd.DataFrame(rows)
    if not models.empty:
        models["p_bh"] = bh_adjust(models["p"])
        models = models.sort_values("p", na_position="last")
    skipped_df = pd.DataFrame(local) if local else pd.DataFrame()
    return models, skipped_df


def describe_outcome(df: pd.DataFrame, outcome: str, kind: str) -> pd.DataFrame:
    s = df[outcome]
    n = int(s.notna().sum())
    missing = len(df) - n
    if kind == "binary":
        y = pd.to_numeric(s, errors="coerce").dropna()
        k = int(y.sum())
        lo, hi = wilson_ci(k, len(y))
        levels = f"0:{len(y) - k}; 1:{k}"
        # S-11: spell out the CI and the denominator instead of a bare range.
        rate_ci = (f"{k}/{len(y)} = {k / len(y) * 100:.1f}%（95%CI "
                   f"{lo * 100:.1f}–{hi * 100:.1f}%，Wilson）") if len(y) else ""
        return pd.DataFrame([{
            "variable": outcome, "type": "outcome (binary)", "n": n, "missing": missing,
            "mean": k / len(y) if len(y) else np.nan, "sd": np.nan,
            "median": np.nan, "p25": np.nan, "p75": np.nan,
            "min": 0, "max": 1, "levels": levels, "rate_ci": rate_ci,
        }])
    if kind == "continuous":
        y = pd.to_numeric(s, errors="coerce").dropna()
        return pd.DataFrame([{
            "variable": outcome, "type": "outcome (continuous)", "n": n, "missing": missing,
            "mean": y.mean(), "sd": y.std(), "median": y.median(),
            "p25": y.quantile(.25), "p75": y.quantile(.75),
            "min": y.min(), "max": y.max(), "levels": "", "rate_ci": "",
        }])
    vc = s.dropna().astype(str).value_counts()
    return pd.DataFrame([{
        "variable": outcome, "type": "outcome (categorical)", "n": n, "missing": missing,
        "mean": np.nan, "sd": np.nan, "median": np.nan, "p25": np.nan, "p75": np.nan,
        "min": np.nan, "max": np.nan,
        "levels": "; ".join(f"{k}:{v}" for k, v in vc.items()), "rate_ci": "",
    }])


# ---------------------------------------------------------------------------
# Multivariate layer (--spec): logit/ols with explicit reference groups,
# clustering, robust SE, VIF and ROC.
# ---------------------------------------------------------------------------
_CAT_RE = re.compile(
    r"^C\(\s*([^,()]+?)\s*(?:,\s*Treatment\(\s*['\"]?([^'\")]+?)['\"]?\s*\)\s*)?\)$")


def parse_predictor(expr, ref_map: dict) -> dict:
    """Parse one ``predictors`` entry into ``{kind, name, ref, expr}``.

    Accepted forms: ``name`` (continuous), ``C(name)`` (categorical),
    ``C(name, Treatment('level'))`` (categorical with an explicit reference),
    and a bare ``name`` that also appears in ``ref`` (categorical with that
    reference). A categorical predictor with no declared reference is an error:
    S-03 showed that letting pandas pick ``drop_first`` made the reference the
    alphabetical first level, which for ``court_f`` was a level with zero events.
    """
    text = str(expr).strip()
    if not text:
        raise SpecError("predictors 里有空字符串")
    match = _CAT_RE.match(text)
    if match:
        name = match.group(1).strip().strip("'\"")
        ref = match.group(2)
        if ref is None:
            ref = ref_map.get(name)
        return {"kind": "cat", "name": name, "ref": ref, "expr": text}
    if text in ref_map and ref_map[text]:
        return {"kind": "cat", "name": text, "ref": ref_map[text], "expr": text}
    return {"kind": "num", "name": text, "ref": None, "expr": text}


def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        try:
            spec = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SpecError(f"spec 不是合法 JSON: {exc}") from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("models"), list):
        raise SpecError("spec 必须是 {\"models\": [...]} 结构")
    if not spec["models"]:
        raise SpecError("spec.models 为空")
    return spec


def normalize_cov(value) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).strip().upper()
    if text in {"HC0", "HC1", "HC3"}:
        return text
    if text in {"NONROBUST", "CLASSICAL", "NONE", "OLS"}:
        return None
    raise SpecError(f"不支持的 cov: {value!r}；用 HC0 / HC1 / HC3 或省略")


def encode_model_outcome(series: pd.Series, mtype: str, outcome_map=None):
    if mtype == "logit":
        encoded, used = encode_binary(series, outcome_map)
        if encoded is None:
            raise SpecError("结果变量不是可识别的二元 0/1；文本标签请在 spec 里给 outcome_map")
        return encoded.astype(float), used
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == 0:
        raise SpecError("OLS 的结果变量无法转为数值")
    return numeric.astype(float), {}


def detect_empty_cells(frame: pd.DataFrame, cats: list[str], outcome: str,
                       labels: dict) -> list[dict]:
    """Empty cells for binary outcomes: a level with 0 events or all events."""
    rows: list[dict] = []
    for c in cats:
        values = frame[c].astype(str)
        for level, part in frame.groupby(values, sort=True):
            n = len(part)
            events = int(part[outcome].sum())
            if events == 0 or events == n:
                rows.append({"variable": labels.get(c, c), "level": str(level),
                             "n": n, "events": events, "action": ""})
    return rows


def vif_rows(X: pd.DataFrame) -> list[dict]:
    """VIF per design column (regress each predictor on all the others)."""
    cols = [c for c in X.columns if X[c].notna().all() and X[c].nunique() > 1]
    rows = []
    n = len(X)
    for c in cols:
        others = [x for x in cols if x != c]
        y = X[c].to_numpy(dtype=float)
        design = [np.ones(n)] + [X[x].to_numpy(dtype=float) for x in others]
        matrix = np.column_stack(design)
        try:
            coef, *_ = np.linalg.lstsq(matrix, y, rcond=None)
            resid = y - matrix @ coef
            ss_res = float(resid @ resid)
            ss_tot = float(((y - y.mean()) ** 2).sum())
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
            vif = 1.0 / (1.0 - r2) if np.isfinite(r2) and r2 < 1 else float("inf")
        except np.linalg.LinAlgError:  # pragma: no cover - defensive
            vif = float("nan")
        rows.append({"term": c, "vif": float(vif), "n_predictors": len(cols), "note": ""})
    return rows


def _auc(y: np.ndarray, score: np.ndarray) -> float:
    pos = score[y == 1]
    neg = score[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = stats.rankdata(np.r_[pos, neg])
    r_pos = float(ranks[:len(pos)].sum())
    return (r_pos - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def auc_with_ci(y, score, reps: int = 1000, seed: int = 20240101):
    """AUC + 95% percentile bootstrap CI (deterministic seed)."""
    y = np.asarray(y, dtype=int)
    score = np.asarray(score, dtype=float)
    point = _auc(y, score)
    rng = np.random.default_rng(seed)
    n = len(y)
    draws = []
    for _ in range(int(reps)):
        idx = rng.integers(0, n, n)
        yy, ss = y[idx], score[idx]
        if len(np.unique(yy)) < 2:
            continue
        value = _auc(yy, ss)
        if np.isfinite(value):
            draws.append(value)
    if len(draws) < 50:
        return point, float("nan"), float("nan")
    low, high = np.percentile(draws, [2.5, 97.5])
    return point, float(low), float(high)


def _design_matrix(work: pd.DataFrame, predictors: list[dict], mid: str):
    """Build the design matrix with explicitly declared reference groups."""
    X = pd.DataFrame(index=work.index)
    refs: dict[str, str] = {}
    for pred in predictors:
        name = pred["name"]
        if pred["kind"] == "num":
            values = pd.to_numeric(work[name], errors="coerce").astype(float)
            if values.notna().sum() == 0:
                raise SpecError(f"模型 {mid}：预测变量 {name} 无法转为数值；"
                                "若是分类变量请用 C(name, Treatment('参照'))")
            X[name] = values
            refs[name] = ""
            continue
        raw = work[name]
        counts = raw.dropna().astype(str).value_counts()
        levels = [str(v) for v in counts.index]
        if len(levels) < 2:
            raise SpecError(f"模型 {mid}：分类变量 {name} 只有 1 个水平")
        ref = str(pred["ref"]) if pred["ref"] not in (None, "") else None
        if ref is None:
            raise SpecError(
                f"模型 {mid}：分类变量 {name} 未声明参照组；"
                f"写成 C({name}, Treatment('水平')) 或在 ref 里声明，"
                f"水平为 {levels[:8]}")
        if ref not in levels:
            raise SpecError(f"模型 {mid}：{name} 的参照组 {ref!r} 不在数据里；"
                            f"水平为 {levels[:8]}")
        for level in levels:
            if level == ref:
                continue
            term = f"{name}[T.{level}]"
            X[term] = (raw.astype(str) == level).astype(float)
            refs[term] = ref
    return X, refs


def _model_rows(mid: str, mtype: str, fit, X: pd.DataFrame, refs: dict[str, str],
                outcome: str, n_model: int, n_events, se_type: str,
                merges: dict[str, list[str]], excluded: list[str],
                sample: str = "full") -> list[dict]:
    rows = []
    conf = fit.conf_int()
    for term in X.columns:
        beta = float(fit.params[term])
        se = float(fit.bse[term])
        lo = float(conf.loc[term].iloc[0])
        hi = float(conf.loc[term].iloc[1])
        pval = float(fit.pvalues[term])
        if not np.isfinite(beta) or not np.isfinite(se):
            excluded.append(term)
            continue
        if mtype == "logit" and (abs(beta) > 12 or se > 8):
            # Backstop for separation that survived the pre-check: never write
            # an OR of 1e9 into a coefficient table.
            excluded.append(term)
            continue
        note = ""
        var = term.split("[T.")[0]
        if merges.get(var):
            note = "合并水平: " + "、".join(merges[var])
        row = {"model": mid, "term": term, "type": mtype, "beta": beta, "se": se,
               "beta_ci_low": lo, "beta_ci_high": hi, "p": pval,
               "or": np.nan, "or_low": np.nan, "or_high": np.nan,
               "ci_low": lo, "ci_high": hi, "metric": "beta", "estimate": beta,
               "n": n_model, "n_events": n_events, "outcome": outcome,
               "ref": refs.get(term, ""), "note": note, "se_type": se_type,
               "sample": sample}
        if mtype == "logit":
            row.update({"or": math.exp(beta), "or_low": math.exp(lo),
                        "or_high": math.exp(hi), "ci_low": math.exp(lo),
                        "ci_high": math.exp(hi), "metric": "OR",
                        "estimate": math.exp(beta)})
        rows.append(row)
    return rows


def _stars(p) -> str:
    """Significance stars for a p value: ``***`` < .001, ``**`` < .01, ..."""
    try:
        value = float(p)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(value):
        return ""
    if value < 0.001:
        return "***"
    if value < 0.01:
        return "**"
    if value < 0.05:
        return "*"
    if value < 0.1:
        return "."
    return ""


def _short_label(term: str) -> str:
    """Human-readable term used by ``coef_all.csv`` (delegates to pubfig)."""
    try:
        from pubfig import short_label
    except Exception:  # pragma: no cover - pubfig lives next to this script
        return str(term)
    return str(short_label(term))


def _term_order(term: str, predictors: list[str]) -> int:
    """Sort key: spec predictor order, dummies of one variable kept together."""
    if term in ("Intercept", "const"):
        return len(predictors) * 10 + 9          # constant term last
    var = str(term).split("[T.")[0]
    if var in predictors:
        return predictors.index(var) * 10
    return len(predictors) * 10 + 5              # unexpected term after the spec ones


def _coef_label(term: str, labels: dict[str, str]) -> str:
    """Readable label: spec ``labels`` > dummy form > pubfig.short_label."""
    term = str(term)
    if term in ("Intercept", "const"):
        return "常数项"
    if term in labels:
        return labels[term]
    if "[T." in term:
        var, level = term.split("[T.", 1)
        return f"{labels.get(var, var)}：{level.rstrip(']')}"
    return _short_label(term)


def _coef_all_frame(frames: list[pd.DataFrame], spec: dict,
                    models: list[dict]) -> pd.DataFrame:
    """Merge per-model coefficient frames into the paper-style comparison table."""
    labels = {str(k): str(v) for k, v in (spec.get("labels") or {}).items()}
    by_id = {str(m.get("id")): m for m in models}
    parts: list[pd.DataFrame] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        mid = str(frame["model"].iloc[0])
        model = by_id.get(mid, {})
        local_labels = dict(labels)
        local_labels.update({str(k): str(v)
                             for k, v in (model.get("labels") or {}).items()})
        order: list[str] = []
        for expr in (model.get("predictors") or []):
            try:
                order.append(parse_predictor(expr, {})["name"])
            except SpecError:            # pragma: no cover - spec already validated
                order.append(str(expr))
        part = frame.copy()
        part["label"] = [_coef_label(t, local_labels) for t in part["term"]]
        part["stars"] = [_stars(p) for p in part["p"]]
        part["_order"] = [_term_order(t, order) for t in part["term"]]
        part = part.sort_values("_order", kind="stable").drop(columns=["_order"])
        parts.append(part)
    cols = TABLE_COLUMNS["coef_all"]
    if not parts:
        return pd.DataFrame(columns=cols)
    return pd.concat(parts, ignore_index=True).reindex(columns=cols)


def load_sample_flow(path: str) -> dict[str, int]:
    """Read ``sample_flow.csv`` (``stage,n,note``) into ``{stage: n}``."""
    frame = read_csv_auto(path)
    names = {str(c).strip(): c for c in frame.columns}
    for need in ("stage", "n"):
        if need not in names:
            raise SpecError(f"sample_flow 缺少列 {need!r}；需要 stage,n,note: {path}")
    out: dict[str, int] = {}
    for _, row in frame.iterrows():
        stage = str(row[names["stage"]]).strip()
        try:
            value = int(float(row[names["n"]]))
        except (TypeError, ValueError):
            continue
        if stage:
            out[stage] = value
    if not out:
        raise SpecError(f"sample_flow 没有可用的 stage/n 行: {path}")
    return out


def _fit_row(info: dict) -> dict:
    # Contract: n is the actual fitted sample; n_dropna is the count EXCLUDED
    # for missing values before fitting. Keep the legacy column name for
    # consumers, but never interpret it as the retained N.
    """One machine-readable fitting record for ``fit.csv``."""
    return {"model": info["mid"], "type": info["mtype"], "n": info["n"],
            "k": info.get("k", np.nan), "n_events": info.get("n_events", np.nan),
            "loglik": info.get("loglik", np.nan), "llr": info.get("llr", np.nan),
            "llr_df": info.get("llr_df", np.nan), "llr_p": info.get("llr_p", np.nan),
            "pseudo_r2": info.get("pseudo_r2", np.nan),
            "aic": info.get("aic", np.nan), "bic": info.get("bic", np.nan),
            "se_type": info.get("se_type", ""), "subset": info.get("subset") or "full",
            "n_dropna": info.get("n_dropped", np.nan)}


LLR_P_FLOOR = 1e-300


def _fmt_llr_p(p) -> str:
    """Format the LLR p-value for Markdown; underflow is shown as ``<1e-300``."""
    try:
        value = float(p)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(value):
        return "—"
    if value < LLR_P_FLOOR:
        return "<1e-300"
    return fmt_p(value)


def run_models(df: pd.DataFrame, spec: dict, args, out_dir: str,
               filter_desc: str | None) -> int:
    """Fit every model in the spec and write coef_*.csv / model_summary.md."""
    if sm is None:
        print("ERROR: statsmodels 未安装，无法运行 --spec 多变量模型", file=sys.stderr)
        return 2
    models = spec["models"]
    if args.max_models > 0 and len(models) > args.max_models:
        print(f"ERROR: spec 有 {len(models)} 个模型，超过 --max-models {args.max_models}；"
              "请拆分 spec 或提高上限", file=sys.stderr)
        return 2
    flow = None
    flow_path = getattr(args, "sample_flow", None)
    if flow_path:
        try:
            flow = load_sample_flow(flow_path)
        except SpecError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    if flow is not None:
        # C2: a declared flow_stage MUST exist in the funnel; an undeclared one
        # is simply not checked (never conflated with "declared but mismatched").
        # But a funnel passed in and used by nothing is a silent no-op, so say so.
        declared = [str(m.get("flow_stage") or "").strip() for m in models]
        if not any(declared):
            print("warning: --sample-flow was given but no model declares "
                  "'flow_stage'; the funnel is never compared. Add "
                  "\"flow_stage\": \"<stage name>\" to the models you want checked",
                  file=sys.stderr)
        stages = sorted(flow)
        for index, model in enumerate(models):
            mid = str(model.get("id") or f"M{index + 1}").strip()
            stage = str(model.get("flow_stage") or "").strip()
            if stage and stage not in flow:
                print(f"ERROR: 模型 {mid}：flow_stage '{stage}' 不在 "
                      f"sample_flow.csv（现有：{', '.join(stages)}）", file=sys.stderr)
                return 2
    summary: list[str] = ["# 多变量模型摘要", "",
                          f"- 数据：`{os.path.abspath(args.data)}`",
                          f"- spec：`{os.path.abspath(args.spec)}`",
                          f"- 筛选：`{filter_desc or '(无)'}`",
                          f"- 过滤后样本：{len(df):,}",
                          f"- 分离策略：`{args.separation}`",
                          (f"- sample_flow：`{os.path.abspath(flow_path)}`"
                           if flow_path else "- sample_flow：未提供（`--sample-flow`）"),
                          *(["- flow 说明：WARN 只说明模型 N 与漏斗某行不等，"
                             "并非数据错误；模型侧已排除的缺失/分离条数见 "
                             "separation_report.csv 与 fit.csv 的 n_dropna。"]
                            if flow is not None else []),
                          "- 说明：logit 的 `ci_low/ci_high` 与 `or` 同为 OR 尺度，"
                          "`beta/se` 为对数尺度；ols 的 `ci_low/ci_high` 为 β 尺度。",
                          "- `coef_<id>.csv` 可直接传给 `auto_chart_pack.py --coef`。", ""]
    all_coef: list[pd.DataFrame] = []
    infos: list[dict] = []
    separation_rows: list[dict] = []
    vif_all: list[dict] = []
    roc_all: list[dict] = []
    failures = 0
    for index, model in enumerate(models):
        mid = str(model.get("id") or f"M{index + 1}").strip()
        try:
            rows, info, sep_rows, vif_rows_m, roc_row = _run_one_model(
                df, model, mid, args)
        except SpecError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            summary.extend([f"## {mid}（未能估计）", "", f"- 原因：{exc}", ""])
            failures += 1
            continue
        except Exception as exc:  # pragma: no cover - defensive
            print(f"ERROR: 模型 {mid}: {type(exc).__name__}: {exc}", file=sys.stderr)
            summary.extend([f"## {mid}（未能估计）", "",
                            f"- 原因：{type(exc).__name__}: {exc}", ""])
            failures += 1
            continue
        # C2: only a DECLARED flow_stage is checked (presence validated above);
        # models without one keep blank flow_n/flow_match and no summary line.
        stage = str(model.get("flow_stage") or "").strip()
        if flow is not None and stage:
            info["flow_stage"] = stage
            flow_n = int(flow[stage])
            info["flow_n"] = flow_n
            info["flow_match"] = bool(flow_n == int(info["n"]))
            if not info["flow_match"]:
                print(f"WARN: 模型 {mid} 的 N={info['n']} 与 sample_flow 的 "
                      f"{flow_n} 不一致（stage=\"{stage}\"）", file=sys.stderr)
        infos.append(info)
        separation_rows.extend(sep_rows)
        if vif_rows_m:
            vif_all.extend(vif_rows_m)
        if roc_row:
            roc_all.append(roc_row)
        frame = pd.DataFrame(rows)
        all_coef.append(frame)
        write_table(os.path.join(out_dir, f"coef_{mid}.csv"), frame,
                    TABLE_COLUMNS["coef"])
        summary.extend(_render_model_summary(frame, info, sep_rows, vif_rows_m, roc_row))
    write_table(os.path.join(out_dir, "separation_report.csv"),
                pd.DataFrame(separation_rows), TABLE_COLUMNS["separation_report"])
    if args.vif:
        write_table(os.path.join(out_dir, "vif.csv"),
                    pd.DataFrame(vif_all), TABLE_COLUMNS["vif"])
    if args.roc:
        write_table(os.path.join(out_dir, "roc.csv"),
                    pd.DataFrame(roc_all), TABLE_COLUMNS["roc"])
    if all_coef:
        combined = pd.concat(all_coef, ignore_index=True)
        combined = combined.reindex(columns=TABLE_COLUMNS["coef"])
    else:
        combined = pd.DataFrame(columns=TABLE_COLUMNS["coef"])
    # A3-2 / A3-3: the paper-facing comparison table and the machine-readable fit table.
    coef_all = _coef_all_frame(all_coef, spec, models)
    write_table(os.path.join(out_dir, "coef_all.csv"), coef_all,
                TABLE_COLUMNS["coef_all"])
    fit_cols = list(TABLE_COLUMNS["fit"])
    fit_rows = [_fit_row(info) for info in infos]
    if flow is not None:
        fit_cols += ["flow_n", "flow_match"]
        for row, info in zip(fit_rows, infos):
            row["flow_n"] = info.get("flow_n", np.nan)
            match = info.get("flow_match")
            row["flow_match"] = "" if match is None else ("TRUE" if match else "FALSE")
    write_table(os.path.join(out_dir, "fit.csv"), pd.DataFrame(fit_rows), fit_cols)
    summary.extend(["", "## 输出文件", "",
                    f"- `coef_<model_id>.csv`：{len(all_coef)} 个模型、"
                    f"{len(combined)} 行系数（含 `sample` 列）",
                    f"- `coef_all.csv`：多模型对比表（{len(coef_all)} 行，含 label/stars）",
                    f"- `fit.csv`：拟合指标（LLR χ²、McFadden R²、AIC/BIC、n_dropna"
                    + ("、flow_n/flow_match" if flow is not None else "") + "）",
                    "- `separation_report.csv`：空单元格检查结果（drop/merge/exclude）",
                    "- `vif.csv`" if args.vif else "- `vif.csv`：未运行（加 --vif）",
                    "- `roc.csv`" if args.roc else "- `roc.csv`：未运行（加 --roc）",
                    ""])
    # Fit warnings belong in the deliverable, not only in a terminal nobody reads.
    warned = [info for info in infos if info.get("fit_warnings")]
    summary.extend(["", "## 拟合告警", ""])
    if warned:
        for info in warned:
            for text in info["fit_warnings"]:
                summary.append(f"- `{info['mid']}`：{text}")
    else:
        summary.append("- 无（statsmodels 未报告收敛或奇异矩阵告警）")
    with open(os.path.join(out_dir, "model_summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(summary) + "\n")
    meta = {"data": os.path.abspath(args.data), "spec": os.path.abspath(args.spec),
            "filter": filter_desc, "n": int(len(df)),
            "separation": args.separation, "max_models": args.max_models,
            "vif": bool(args.vif), "roc": bool(args.roc),
            "models": [str(m.get("id") or f"M{i + 1}") for i, m in enumerate(models)],
            "subsets": {str(m.get("id") or f"M{i + 1}"): (m.get("subset") or None)
                        for i, m in enumerate(models)},
            "sample_flow": os.path.abspath(flow_path) if flow_path else None,
            "flow_checks": [{"model": info["mid"], "stage": info.get("flow_stage"),
                             "flow_n": info.get("flow_n"),
                             "model_n": info["n"], "match": info.get("flow_match")}
                            for info in infos if info.get("flow_stage") is not None],
            "failures": failures}
    with open(os.path.join(out_dir, "model_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    if combined.empty:
        print("ERROR: spec 未产出任何系数行（模型全部失败或全部被分离规则排除）",
              file=sys.stderr)
        return 2
    print(f"models: {len(all_coef)}  coef rows: {len(combined)}  "
          f"separation rows: {len(separation_rows)}")
    if failures:
        print(f"ERROR: {failures} 个模型未能估计，见 model_summary.md", file=sys.stderr)
        return 2
    return 0


def _run_one_model(df: pd.DataFrame, model: dict, mid: str, args):
    """Fit one spec model; returns (rows, info, separation_rows, vif_rows, roc_row)."""
    allowed = {"id", "type", "outcome", "predictors", "ref", "cluster", "cov",
               "dropna", "outcome_map", "label", "note", "subset", "flow_stage",
               "labels"}
    unknown = [k for k in model if k not in allowed and not str(k).startswith("_")]
    if unknown:
        raise SpecError(f"模型 {mid}：未知字段 {unknown}")
    mtype = str(model.get("type") or "").strip().lower()
    if mtype not in {"logit", "ols"}:
        raise SpecError(f"模型 {mid}：type 必须是 logit 或 ols")
    outcome = str(model.get("outcome") or "").strip()
    if not outcome:
        raise SpecError(f"模型 {mid}：缺少 outcome")
    if outcome not in df.columns:
        raise SpecError(f"模型 {mid}：outcome 列不存在: {outcome}")
    raw_predictors = model.get("predictors") or []
    if not isinstance(raw_predictors, list) or not raw_predictors:
        raise SpecError(f"模型 {mid}：predictors 必须是非空数组")
    ref_map = {str(k): str(v) for k, v in (model.get("ref") or {}).items()}
    predictors = [parse_predictor(x, ref_map) for x in raw_predictors]
    names = [p["name"] for p in predictors]
    if len(set(names)) != len(names):
        raise SpecError(f"模型 {mid}：predictors 有重复变量 {names}")
    for pred in predictors:
        if pred["name"] not in df.columns:
            raise SpecError(f"模型 {mid}：预测变量列不存在: {pred['name']}")
    cov = normalize_cov(model.get("cov"))
    cluster = str(model.get("cluster") or "").strip() or None
    if cluster and cluster not in df.columns:
        raise SpecError(f"模型 {mid}：cluster 列不存在: {cluster}")
    dropna = model.get("dropna", True)
    dropna = True if dropna is None else bool(dropna)

    # A3-1: models[].subset narrows the entry-filtered frame BEFORE dropna, so
    # the order is entry filter -> subset -> complete cases.
    subset = str(model.get("subset") or "").strip() or None
    sample = "full"
    n_entry = len(df)
    n_subset = n_entry
    if subset:
        try:
            validate_filter_query(subset)
        except ValueError as exc:
            raise SpecError(f"模型 {mid}：subset 含被禁止的记号：{exc}") from exc
        try:
            sub = df.query(subset)
        except Exception as exc:
            raise SpecError(f"模型 {mid}：subset 无法执行（{subset}）："
                            f"{type(exc).__name__}: {exc}") from exc
        if sub.empty:
            raise SpecError(f"模型 {mid}：subset 之后没有样本：{subset}")
        df = sub
        sample = subset
        n_subset = len(df)

    y, outcome_map = encode_model_outcome(df[outcome], mtype, model.get("outcome_map"))
    y.name = "__y__"
    work = pd.DataFrame({y.name: y}, index=df.index)
    for pred in predictors:
        if pred["kind"] == "num":
            work[pred["name"]] = pd.to_numeric(df[pred["name"]], errors="coerce")
        else:
            work[pred["name"]] = df[pred["name"]].astype("object")
    n_before = len(work)
    complete = work.notna().all(axis=1)
    n_dropped = int((~complete).sum())
    if not dropna and n_dropped:
        counts = {c: int(work[c].isna().sum()) for c in work.columns if work[c].isna().any()}
        raise SpecError(f"模型 {mid}：dropna=false 但存在缺失值 {counts}")
    work = work[complete]
    if len(work) <= len(predictors) + 2:
        raise SpecError(f"模型 {mid}：完整案例只有 {len(work)} 行，无法估计")

    cat_names = [p["name"] for p in predictors if p["kind"] == "cat"]
    labels = {p["name"]: p["expr"] for p in predictors}
    separation_rows: list[dict] = []
    merges: dict[str, list[str]] = {}
    excluded: list[str] = []
    if mtype == "logit" and cat_names:
        cells = detect_empty_cells(work, cat_names, y.name,
                                   {p["name"]: p["name"] for p in predictors})
        if cells:
            policy = args.separation
            if policy == "error":
                detail = "；".join(f"{c['variable']}={c['level']}(n={c['n']}, events={c['events']})"
                                  for c in cells)
                raise SpecError(f"模型 {mid}：检测到空单元格 {detail}；"
                                "用 --separation drop|merge 处理")
            for cell in cells:
                var_expr = cell["variable"]
                var = next((p["name"] for p in predictors if p["expr"] == var_expr), var_expr)
                level = cell["level"]
                if policy == "drop":
                    work = work[work[var].astype(str) != level]
                    cell["action"] = "dropped"
                else:  # merge
                    ref = next((p["ref"] for p in predictors if p["name"] == var), None)
                    levels = [str(v) for v in work[var].dropna().astype(str).unique()]
                    ref = ref if ref in levels else None
                    if ref is None:
                        raise SpecError(
                            f"模型 {mid}：{var} 的参照组未声明或等于被合并水平，无法 merge；"
                            "改用 --separation drop 或声明参照组")
                    work[var] = work[var].astype(str).replace({level: ref})
                    cell["action"] = "merged"
                    merges.setdefault(var, []).append(f"{level}→{ref}")
                separation_rows.append(cell)
            if len(work) <= len(predictors) + 2:
                raise SpecError(f"模型 {mid}：按分离规则剔除后样本不足（{len(work)} 行）")

    X, refs = _design_matrix(work, predictors, mid)
    constant = [c for c in X.columns if X[c].nunique() <= 1]
    if constant:
        X = X.drop(columns=constant)
        for term in constant:
            excluded.append(term)
    if X.empty or X.shape[1] == 0:
        raise SpecError(f"模型 {mid}：设计矩阵为空")

    frame = pd.concat([work[y.name], X], axis=1).dropna()
    yv = frame[y.name].astype(float)
    Xv = frame.drop(columns=[y.name])
    if mtype == "logit" and yv.nunique() < 2:
        raise SpecError(f"模型 {mid}：结果只有 1 个类别")
    design = sm.add_constant(Xv, has_constant="add")
    # Record, do not silence: a non-converged fit is still reported, but the
    # reader has to be told.  The texts go to stderr and into model_summary.md.
    fit_warnings: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if mtype == "logit":
            model_obj = sm.Logit(yv, design)
        else:
            model_obj = sm.OLS(yv, design)
        if cluster:
            groups = df.loc[frame.index, cluster]
            if groups.isna().any():
                raise SpecError(f"模型 {mid}：cluster 列 {cluster} 在建模样本里有缺失")
            n_groups = int(groups.nunique())
            if n_groups < 2:
                raise SpecError(f"模型 {mid}：cluster 列 {cluster} 只有 {n_groups} 组")
            fit = model_obj.fit(cov_type="cluster",
                                cov_kwds={"groups": groups.to_numpy()},
                                **({"disp": 0} if mtype == "logit" else {}))
            se_type = f"cluster({cluster}, {n_groups} 组)"
            if cov:
                se_type += f"; cov={cov} 被 cluster 覆盖"
        elif cov:
            fit = model_obj.fit(cov_type=cov,
                                **({"disp": 0} if mtype == "logit" else {}))
            se_type = cov
        else:
            fit = model_obj.fit(**({"disp": 0} if mtype == "logit" else {}))
            se_type = "nonrobust"

    for warn_item in caught:
        text = str(warn_item.message)
        if text not in fit_warnings:
            fit_warnings.append(text)
    if fit_warnings:
        print(f"warning: 模型 {mid} 拟合报告 {len(fit_warnings)} 条告警: "
              f"{fit_warnings[0][:160]}", file=sys.stderr)

    n_model = int(len(frame))
    n_events = int(yv.sum()) if mtype == "logit" else np.nan
    rows = _model_rows(mid, mtype, fit, Xv, refs, outcome, n_model, n_events,
                       se_type, merges, excluded, sample)
    info = {"mid": mid, "mtype": mtype, "outcome": outcome, "n": n_model,
            "n_before": n_before, "n_dropped": n_dropped,
            "n_removed_separation": int(n_before - n_dropped - n_model),
            "n_events": n_events, "se_type": se_type, "cluster": cluster,
            "cov": cov, "outcome_map": outcome_map, "refs": refs,
            "predictors": predictors, "label": model.get("label"),
            "note": model.get("note"), "n_cats": len(cat_names),
            "n_excluded": len(excluded), "excluded": excluded,
            "llf": float(getattr(fit, "llf", np.nan)),
            "llnull": float(getattr(fit, "llnull", np.nan)),
            "aic": float(getattr(fit, "aic", np.nan)),
            "rsquared": float(getattr(fit, "rsquared", np.nan)),
            "rsquared_adj": float(getattr(fit, "rsquared_adj", np.nan)),
            "f_pvalue": float(getattr(fit, "f_pvalue", np.nan)),
            "bic": float(getattr(fit, "bic", np.nan)),
            "fit_warnings": fit_warnings}
    # A3-3: likelihood-ratio statistics for the machine-readable fit table.
    k_params = int(len(fit.params))
    loglik = float(getattr(fit, "llf", np.nan))
    llr = llr_df = llr_p = np.nan
    pseudo_r2 = np.nan
    if mtype == "logit":
        llnull = float(getattr(fit, "llnull", np.nan))
        if np.isfinite(loglik) and np.isfinite(llnull):
            llr = 2.0 * (loglik - llnull)
            llr_df = max(k_params - 1, 0)
            if llr_df > 0:
                llr_p = float(stats.chi2.sf(max(llr, 0.0), llr_df))
            pseudo_r2 = 1.0 - loglik / llnull if llnull != 0 else np.nan
    else:
        pseudo_r2 = float(getattr(fit, "rsquared", np.nan))
    info.update({"k": k_params, "loglik": loglik, "llr": llr, "llr_df": llr_df,
                 "llr_p": llr_p, "pseudo_r2": pseudo_r2, "subset": subset,
                 "sample": sample, "n_entry": n_entry, "n_subset": n_subset})
    if mtype == "logit":
        p = fit.predict(design)
        info["_pred"] = p
    vif_data = vif_rows(Xv) if args.vif else []
    for row in vif_data:
        row["model"] = mid
    if args.vif and not vif_data:
        vif_data = [{"model": mid, "term": "(none)", "vif": np.nan,
                     "n_predictors": 0, "note": "无可用预测变量"}]
    roc_row = None
    if args.roc and mtype == "logit":
        prob = fit.predict(design).to_numpy(dtype=float)
        point, low, high = auc_with_ci(yv.to_numpy(dtype=int), prob)
        roc_row = {"model": mid, "auc": float(point), "ci_low": low,
                   "ci_high": high, "n": n_model, "n_events": n_events,
                   "method": "bootstrap percentile", "reps": 1000,
                   "note": "seed=20240101"}
        info["auc"] = (float(point), low, high)
    elif args.roc:
        roc_row = {"model": mid, "auc": np.nan, "ci_low": np.nan, "ci_high": np.nan,
                   "n": n_model, "n_events": np.nan, "method": "n/a", "reps": 0,
                   "note": "ROC 仅对 logit 模型计算"}
    return rows, info, separation_rows, vif_data, roc_row


def _render_model_summary(frame: pd.DataFrame, info: dict, sep_rows: list[dict],
                          vif_data: list[dict], roc_row: dict | None) -> list[str]:
    lines = [f"## {info['mid']}（{info['mtype']}）", ""]
    if info.get("label"):
        lines.append(f"- 标签：{info['label']}")
    events = info.get("n_events")
    event_txt = ""
    if events is not None and np.isfinite(events):
        rate = events / info["n"] * 100 if info["n"] else np.nan
        event_txt = f"（事件 {int(events)}/{info['n']} = {rate:.1f}%）"
    lines.append(f"- 结果：`{info['outcome']}`{event_txt}")
    lines.append(f"- 估计样本：N={info['n']:,}（dropna 排除 {info['n_dropped']} 行；"
                 f"分离规则再排除 {info['n_removed_separation']} 行）")
    if info.get("subset"):
        lines.append(f"- 子样本（`subset`）：`{info['subset']}`；入口过滤后 "
                     f"{info.get('n_entry', 0):,} 行 → 子样本 {info.get('n_subset', 0):,} 行")
    else:
        lines.append("- 子样本：全样本（`sample=full`）")
    if info.get("flow_stage") is not None:
        stage = info["flow_stage"]
        if info.get("flow_match") is True:
            lines.append(f"- **flow 校验：{info['mid']} N={info['n']:,} ✓**"
                         f"（stage=\"{stage}\"）")
        elif info.get("flow_match") is False:
            lines.append(f"- **flow 校验：{info['mid']} N={info['n']:,} ≠ sample_flow "
                         f"{int(info['flow_n']):,}**（stage=\"{stage}\"）")
        else:
            lines.append(f"- flow 校验：sample_flow 里没有 stage=\"{stage}\"，跳过")
    lines.append(f"- 标准误：{info['se_type']}")
    if info["mtype"] == "logit":
        mcf = np.nan
        if np.isfinite(info["llf"]) and np.isfinite(info["llnull"]) and info["llnull"] != 0:
            mcf = 1 - info["llf"] / info["llnull"]
        llr_txt = ""
        if np.isfinite(info.get("llr", np.nan)):
            llr_txt = (f"；LLR χ²={fmt(info['llr'], 1)}"
                       f"（df={int(info['llr_df'])}, p={_fmt_llr_p(info['llr_p'])}）")
        lines.append(f"- 拟合：对数似然 {fmt(info['llf'], 2)}；"
                     f"McFadden R²={fmt(mcf, 3)}；AIC={fmt(info['aic'], 1)}{llr_txt}")
    else:
        lines.append(f"- 拟合：R²={fmt(info['rsquared'], 3)}；"
                     f"调整 R²={fmt(info['rsquared_adj'], 3)}；"
                     f"F 检验 p={fmt_p(info['f_pvalue'])}")
    if info["outcome_map"]:
        lines.append(f"- 二元编码：`{info['outcome_map']}`")
    refs = {}
    for pred in info["predictors"]:
        if pred["kind"] == "cat":
            declared = pred["ref"]
            refs[pred["name"]] = declared if declared is not None else "(未声明)"
    if refs:
        lines.append("- 参照组（显式声明）：" +
                     "；".join(f"`{k}` = {v}" for k, v in refs.items()))
    else:
        lines.append("- 参照组：无分类预测变量")
    if sep_rows:
        detail = "；".join(
            f"`{r['variable']}`={r['level']}（n={r['n']}, events={r['events']}）→ {r['action']}"
            for r in sep_rows)
        lines.append(f"- 分离检查：{detail}")
    else:
        lines.append("- 分离检查：未发现空单元格")
    if info["excluded"]:
        lines.append("- 未写入 coef 的项（常数或估计不稳定）：" +
                     "、".join(f"`{t}`" for t in info["excluded"]))
    lines += ["", "| term | β | SE | 效应 | 95%CI | p | ref | 备注 |",
              "|---|---:|---:|---:|---|---:|---|---|"]
    for _, row in frame.iterrows():
        effect = row["or"] if row["metric"] == "OR" else row["beta"]
        ci = (f"{fmt(row['ci_low'], 3)}–{fmt(row['ci_high'], 3)}")
        lines.append(f"| {row['term']} | {fmt(row['beta'], 3)} | {fmt(row['se'], 3)} | "
                     f"{fmt(effect, 3)} | {ci} | {fmt_p(row['p'])} | "
                     f"{row['ref'] or '—'} | {row['note'] or '—'} |")
    lines.append("")
    if vif_data:
        lines.append("**VIF（多重共线性）**")
        lines.append("")
        for row in vif_data:
            if row["term"] == "(none)":
                lines.append("- 无可用预测变量")
                continue
            flag = "（>10，需处理）" if np.isfinite(row["vif"]) and row["vif"] > 10 else ""
            lines.append(f"- `{row['term']}`: {fmt(row['vif'], 2)}{flag}")
        lines.append("")
    if roc_row:
        if np.isfinite(roc_row["auc"]):
            lines.append(f"**ROC/AUC**：{roc_row['auc']:.3f}（95%CI "
                         f"{fmt(roc_row['ci_low'], 3)}–{fmt(roc_row['ci_high'], 3)}，"
                         f"bootstrap {roc_row['reps']} 次）")
        else:
            lines.append(f"**ROC/AUC**：{roc_row['note']}")
        lines.append("")
    if info.get("note"):
        lines.append(f"- 备注：{info['note']}")
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Markdown summary for the screening pack
# ---------------------------------------------------------------------------
def write_md(path: str, desc: pd.DataFrame, tests: pd.DataFrame,
             rates: pd.DataFrame, corr: pd.DataFrame, uni: pd.DataFrame,
             uni_skipped: pd.DataFrame, meta: dict):
    lines = ["# 自动统计筛查包", "",
             f"- 数据：`{meta['data']}`",
             f"- 筛选：`{meta.get('filter') or '(无)'}`",
             f"- 分析样本：{meta['n']:,}",
             f"- 结果变量：`{meta['outcome']}`（{meta.get('outcome_kind', '')}）"]
    if meta.get("outcome_map"):
        lines.append(f"- 二元编码：`{meta['outcome_map']}`")
    if meta.get("max_predictors"):
        lines.append(f"- 单变量筛查上限：{meta['max_predictors']} 个预测变量（`--max-predictors`）")
    lines += ["", "> 这是探索性筛查，不是最终论文模型。最终模型应按预注册/分析计划在 SPSS 中估计并报告。", ""]
    if meta.get("warnings"):
        lines += ["## 0. 数据警告", ""]
        lines += [f"- {w}" for w in meta["warnings"]] + [""]
    lines += ["## 1. 描述统计", "", "| 变量 | 类型 | N | 缺失 | 均值/中位数 | 水平 |", "|---|---|---:|---:|---|---|"]
    for _, r in desc.iterrows():
        center = f"{fmt(r['mean'], 2)} / {fmt(r['median'], 2)}" if r["type"] == "numeric" else ""
        if r["type"] == "outcome (binary)":
            center = f"{fmt(r['mean'] * 100, 1)}%"
        lines.append(f"| {r['variable']} | {r['type']} | {r['n']} | {r['missing']} | {center} | {r['levels']} |")
    outcome_rows = desc[desc["type"].str.startswith("outcome")] if not desc.empty else desc
    if not outcome_rows.empty and outcome_rows.iloc[0].get("rate_ci"):
        lines.append(f"\n结果变量发生率：{outcome_rows.iloc[0]['rate_ci']}。")

    lines += ["", "## 2. 结果变量的分组比例（Wilson 95%CI）", ""]
    if rates.empty:
        lines.append("无分组比例（连续或多元结果请见描述统计/组间检验）。")
    else:
        lines += ["| 预测变量 | 水平 | N | 事件数 | 比例 | 95%CI |", "|---|---|---:|---:|---:|---:|"]
        for _, r in rates.head(30).iterrows():
            lines.append(f"| {r['predictor']} | {r['level']} | {r['n']} | {r['events']} | "
                         f"{r['rate'] * 100:.1f}% | {r['ci_low'] * 100:.1f}–{r['ci_high'] * 100:.1f}% |")

    lines += ["", "## 3. 组间检验（按 p 排序，前 15）", ""]
    if tests.empty:
        lines.append("无可用检验。")
    else:
        lines += ["| 结果 | 预测变量 | 检验 | p | BH p | 效应量 | N | 备注 |",
                  "|---|---|---|---:|---:|---:|---:|---|"]
        for _, r in tests.head(15).iterrows():
            lines.append(f"| {r['outcome']} | {r['predictor']} | {r['test']} | "
                         f"{fmt_p(r['p'])} | {fmt_p(r.get('p_bh'))} | "
                         f"{fmt(r['effect'], 3)} | {r['n']} | {r.get('note', '')} |")
    lines += ["", "## 4. 单变量模型（按 p 排序，前 15）", ""]
    if uni.empty:
        lines.append("无可估计的单变量模型。")
    else:
        lines += ["| 结果 | 预测变量 | 模型 | 效应 | 95%CI | p | BH p | N | 参照组 |",
                  "|---|---|---|---:|---|---:|---:|---:|---|"]
        for _, r in uni.head(15).iterrows():
            lines.append(f"| {r['outcome']} | {r['predictor']} | {r['model']} | "
                         f"{fmt(r['effect'], 3)} | "
                         f"{fmt(r['ci_low'], 3)}–{fmt(r['ci_high'], 3)} | "
                         f"{fmt_p(r['p'])} | {fmt_p(r.get('p_bh'))} | {r['n']} | "
                         f"{r.get('ref', '') or '—'} |")
    lines += ["", "## 5. 跳过与未纳入（`univariate_skipped.csv` 全量）", ""]
    if uni_skipped is None or uni_skipped.empty:
        lines.append("无跳过项（全部候选变量都已估计）。")
    else:
        for _, r in uni_skipped.head(25).iterrows():
            stage = r.get("stage", "univariate") or "univariate"
            lines.append(f"- [{stage}] {r['predictor']}：{r['reason']}")
        if len(uni_skipped) > 25:
            lines.append(f"- …… 其余 {len(uni_skipped) - 25} 行见 CSV。")
    lines += ["", "## 6. 相关（按 p 排序，前 15）", ""]
    if corr.empty:
        lines.append("无可用相关。")
    else:
        lines += ["| 变量 1 | 变量 2 | 方法 | r | p | N |", "|---|---|---|---:|---:|---:|"]
        for _, r in corr.head(15).iterrows():
            lines.append(f"| {r['var1']} | {r['var2']} | {r['method']} | {fmt(r['r'], 3)} | "
                         f"{fmt_p(r['p'])} | {r['n']} |")
    lines += ["", "## 7. 下一步", "",
              "1. 把有实质意义的变量写进 `model_spec.json`，用 `--spec` 跑多变量模型"
              "（显式参照组、聚类/稳健标准误）。",
              "2. 不要按 p 值筛变量；`p_bh` 只是筛查期的提示。",
              "3. 用 `auto_chart_pack.py --coef output/analysis_pack/coef_M1.csv` 出系数图，再用 SPSS 复核最终模型。",
              "4. 把所有做/不做的分析写入 `analysis_manifest.md`。"]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def run_screening(df: pd.DataFrame, cfg: dict, args, out_dir: str,
                  sections: set, filter_desc: str | None) -> int:
    """The classic bivariate screening pack, restricted to ``sections``."""
    outcome_col, error, outcome_notes = resolve_outcome(df, cfg)
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    cfg = dict(cfg)
    cfg["outcome"] = outcome_col

    kind, encoded, outcome_map, kind_msg = outcome_kind(
        df[outcome_col], args.max_categories, cfg.get("outcome_map"),
        declared_type=cfg.get("outcome_type") or cfg.get("variable_types", {}).get(outcome_col))
    if kind == "unsupported":
        print(f"ERROR: {kind_msg}", file=sys.stderr)
        return 2
    if encoded is not None:
        df[outcome_col] = encoded
    n_outcome = int(df[outcome_col].notna().sum())
    if n_outcome == 0:
        print(f"ERROR: outcome column has no non-missing values: {outcome_col}", file=sys.stderr)
        return 2
    if df[outcome_col].nunique(dropna=True) < 2:
        print(f"ERROR: outcome has fewer than 2 levels: {outcome_col}", file=sys.stderr)
        return 2
    warnings_list = []
    if outcome_notes:
        warnings_list.extend(outcome_notes)
    if len(df) < 30:
        warnings_list.append(f"分析样本仅 {len(df)} 行；检验和模型只应作描述性参考。")
    if kind == "binary":
        events = int(pd.to_numeric(df[outcome_col], errors="coerce").sum())
        if events < 10 or (n_outcome - events) < 10:
            warnings_list.append(f"结果事件数偏少（{events}/{n_outcome}）；Logistic 估计可能不稳定。")
    elif kind == "categorical":
        warnings_list.append(kind_msg or "结果为多分类变量；单变量模型已跳过。")

    time_col, group_col, treatment_col, _, numeric, categorical, binaries = \
        infer_columns(df, cfg, args.max_categories)
    numeric = [c for c in numeric if c != outcome_col and not is_constant(df[c])
               and not is_id_like(c, df[c])]
    categorical = [c for c in categorical if c != outcome_col and not is_constant(df[c])
                   and not is_id_like(c, df[c])]
    dropped_duplicates = []
    binary_predictors = []
    for c in binaries:
        if c == outcome_col or is_constant(df[c]) or is_id_like(c, df[c]):
            continue
        if same_values(df[c], df[outcome_col]):
            dropped_duplicates.append(c)
            continue
        binary_predictors.append(c)
    if group_col and group_col not in categorical and group_col != outcome_col:
        categorical.append(group_col)
    if treatment_col and treatment_col not in categorical and treatment_col != outcome_col:
        categorical.append(treatment_col)

    audit: list[dict] = []
    desc = describe(df, numeric, categorical) if "descriptives" in sections else pd.DataFrame()
    if "descriptives" in sections:
        outcome_desc = describe_outcome(df, outcome_col, kind)
        desc = pd.concat([outcome_desc, desc], ignore_index=True)
    test_cats = list(dict.fromkeys(
        [c for c in categorical if df[c].nunique(dropna=True) <= max(args.max_categories, 2)]
        + binary_predictors
    ))
    rates = pd.DataFrame()
    if "binary_rates" in sections and kind == "binary":
        rates = binary_rates(df, outcome_col, test_cats)
        y = pd.to_numeric(df[outcome_col], errors="coerce").dropna()
        k, n = int(y.sum()), len(y)
        lo, hi = wilson_ci(k, n)
        overall = pd.DataFrame([{"predictor": "(overall)", "level": "", "n": n,
                                 "events": k, "rate": k / n, "ci_low": lo, "ci_high": hi}])
        rates = pd.concat([overall, rates], ignore_index=True) if not rates.empty else overall
    tests = (group_tests(df, outcome_col, test_cats, numeric, kind, audit=audit)
             if "group_tests" in sections else pd.DataFrame())
    corr = pd.DataFrame()
    if "correlations" in sections:
        corr_binaries = binary_predictors + ([outcome_col] if kind in {"binary", "continuous"} else [])
        corr = correlations(df, numeric, corr_binaries, audit=audit)
    uni, uni_skipped = pd.DataFrame(), pd.DataFrame()
    if "univariate" in sections:
        reference_levels = {str(k): str(v) for k, v in (cfg.get("reference_levels") or {}).items()}
        uni, uni_skipped = univariate_models(
            df, outcome_col, numeric, binary_predictors, kind, categorical,
            audit=audit, reference_levels=reference_levels, cov=args.robust,
            max_predictors=args.max_predictors)
    skipped = pd.DataFrame(audit) if audit else pd.DataFrame()

    if "descriptives" in sections:
        write_table(os.path.join(out_dir, "descriptives.csv"), desc, TABLE_COLUMNS["descriptives"])
    if "group_tests" in sections:
        write_table(os.path.join(out_dir, "group_tests.csv"), tests, TABLE_COLUMNS["group_tests"])
    if "binary_rates" in sections:
        write_table(os.path.join(out_dir, "binary_rates.csv"), rates, TABLE_COLUMNS["binary_rates"])
    if "correlations" in sections:
        write_table(os.path.join(out_dir, "correlations.csv"), corr, TABLE_COLUMNS["correlations"])
    if "univariate" in sections:
        write_table(os.path.join(out_dir, "univariate_models.csv"), uni,
                    TABLE_COLUMNS["univariate_models"])
        write_table(os.path.join(out_dir, "univariate_skipped.csv"), skipped,
                    TABLE_COLUMNS["univariate_skipped"])
    meta = {"data": os.path.abspath(args.data), "n": len(df),
            "filter": filter_desc,
            "outcome": outcome_col, "outcome_kind": kind,
            "outcome_map": outcome_map,
            "group": group_col, "treatment": treatment_col,
            "numeric": numeric, "categorical": categorical, "binary": binary_predictors,
            "dropped_duplicates": dropped_duplicates,
            "max_predictors": args.max_predictors,
            "robust": args.robust,
            "sections": sorted(sections),
            "warnings": warnings_list}
    # `meta` used to be dumped to analysis_meta.json, which nothing ever read
    # (an orphan artifact).  The markdown report already carries the same
    # provenance in its header, and models write model_meta.json, so the JSON
    # copy was pure clutter.
    write_md(os.path.join(out_dir, "analysis_pack.md"), desc, tests, rates, corr,
             uni, skipped, meta)
    print(f"n: {len(df)}  outcome: {outcome_col} ({kind})  "
          f"descriptives: {len(desc)}  tests: {len(tests)}  "
          f"correlations: {len(corr)}  univariate: {len(uni)}")
    if not skipped.empty:
        print(f"univariate skipped: {len(skipped)} -> univariate_skipped.csv")
    for w in warnings_list:
        print(f"WARN: {w}")
    print(f"output: {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automatic descriptive/bivariate screening.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--out", default="output/analysis_pack")
    parser.add_argument("--max-categories", type=int, default=12)
    parser.add_argument("--max-predictors", type=int, default=DEFAULT_MAX_PREDICTORS,
                        help=f"单变量筛查的预测变量上限（默认 {DEFAULT_MAX_PREDICTORS} = 不限）")
    parser.add_argument("--max-models", type=int, default=DEFAULT_MAX_MODELS,
                        help=f"spec 里的模型数上限（默认 {DEFAULT_MAX_MODELS} = 不限）")
    parser.add_argument("--only", "--sections", dest="only", default=None,
                        help="只跑指定 section：descriptives,group_tests,binary_rates,"
                             "correlations,univariate,models,vif,roc（或 screen/all/models）")
    parser.add_argument("--spec", default=None,
                        help="多变量模型 spec JSON（输出 coef_<id>.csv 与 model_summary.md）")
    parser.add_argument("--separation", choices=["drop", "merge", "error"], default="drop",
                        help="空单元格处理：drop 剔除该水平、merge 并入参照组、error 报错退出")
    parser.add_argument("--vif", action="store_true", help="计算模型 VIF（需 --spec）")
    parser.add_argument("--roc", action="store_true", help="计算 logit 模型 AUC+95%%CI（需 --spec）")
    parser.add_argument("--robust", default=None, choices=["HC0", "HC1", "HC3"],
                        help="单变量模型的稳健标准误（OLS/Logit 的 cov_type）")
    parser.add_argument("--sample-flow", default=None,
                        help="sample_flow.csv（列 stage,n,note）；只核对声明了 "
                             "models[].flow_stage 的模型：N 不等只 warning 不退出，"
                             "声明了但漏斗里没有该 stage 则报错退出（exit 2）")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if (args.vif or args.roc) and not args.spec:
        print("ERROR: --vif/--roc 需要 --spec（多变量模型）", file=sys.stderr)
        return 2
    if args.sample_flow and not args.spec:
        print("ERROR: --sample-flow 需要 --spec（多变量模型）", file=sys.stderr)
        return 2
    if args.sample_flow and not os.path.isfile(args.sample_flow):
        print(f"ERROR: sample_flow not found: {args.sample_flow}", file=sys.stderr)
        return 2
    try:
        requested = parse_sections(args.only)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.max_predictors < 0 or args.max_models < 0:
        print("ERROR: --max-predictors/--max-models 必须 >= 0（0 = 不限）", file=sys.stderr)
        return 2
    if not os.path.isfile(args.data):
        print(f"ERROR: data not found: {args.data}", file=sys.stderr)
        return 2
    try:
        df = read_csv_auto(args.data, low_memory=False)
    except pd.errors.EmptyDataError:
        print(f"ERROR: data file has no columns/rows: {args.data}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: cannot read data: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty:
        print(f"ERROR: data has no rows: {args.data}", file=sys.stderr)
        return 2
    cfg = {}
    if args.config:
        if not os.path.isfile(args.config):
            print(f"ERROR: config not found: {args.config}", file=sys.stderr)
            return 2
        try:
            with open(args.config, encoding="utf-8") as fh:
                cfg = json.load(fh)
            if not isinstance(cfg, dict):
                raise ValueError("config must be a JSON object")
        except Exception as exc:
            print(f"ERROR: cannot read config: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    query = cfg.get("filter_query")
    try:
        validate_filter_query(query)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        df, filter_desc = apply_filter(df, cfg)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if df.empty:
        print("ERROR: filter returned 0 rows; check filter_query/filter", file=sys.stderr)
        return 2

    spec = None
    if args.spec:
        if not os.path.isfile(args.spec):
            print(f"ERROR: spec not found: {args.spec}", file=sys.stderr)
            return 2
        try:
            spec = load_spec(args.spec)
        except SpecError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if requested is None:
        sections = {"models"} if spec else set(SECTION_GROUPS["all"])
    else:
        sections = set(requested)
    if spec:
        sections |= {"models"}
    if "models" in sections and spec is None:
        if requested is not None:
            print("ERROR: --only models 需要 --spec model_spec.json", file=sys.stderr)
            return 2
        sections.discard("models")
    if not sections:
        print("ERROR: 没有可运行的 section", file=sys.stderr)
        return 2

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    status = 0
    if "models" in sections:
        status = max(status, run_models(df, spec, args, out_dir, filter_desc))
    screening = sections & set(SECTION_GROUPS["screen"])
    if screening:
        status = max(status, run_screening(df, cfg, args, out_dir, screening, filter_desc))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
