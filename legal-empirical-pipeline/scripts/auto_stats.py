#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automatic descriptive and bivariate screening for an analysis CSV.

This is a first-pass screening pack, not the final paper model. It produces:
  - descriptives.csv / .md
  - group_tests.csv        (chi-square / Fisher / Mann-Whitney / Kruskal)
  - binary_rates.csv       (rates with Wilson CI by category)
  - correlations.csv       (Pearson/Spearman with p)
  - univariate_models.csv  (univariate logistic OR or OLS coefficient, including
                            dummy-coded multi-level categorical predictors)
  - analysis_pack.md       (human-readable summary)

Final, pre-specified models still belong in SPSS or a dedicated model script.

Usage:
    python auto_stats.py --data data/analysis.csv --config assets/chart_config.example.json --out output/analysis_pack
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis_utils import (  # noqa: E402
    apply_filter, encode_binary, is_constant, is_id_like, outcome_kind,
    same_values, fmt, fmt_p,
)

try:
    import statsmodels.api as sm
except ImportError:  # pragma: no cover
    sm = None


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, center - half), min(1.0, center + half))


def is_binary(s: pd.Series) -> bool:
    v = pd.to_numeric(s, errors="coerce").dropna()
    return not v.empty and set(np.unique(v)).issubset({0, 1})


def infer_columns(df: pd.DataFrame, cfg: dict, max_categories: int = 12):
    drop = set(cfg.get("drop", []))
    time_col = cfg.get("time") or next((c for c in df.columns if re.search(r"year|年份|时间", c, re.I)), None)
    group_col = cfg.get("group") or next((c for c in df.columns if re.search(r"category|crime|group|类别|案由", c, re.I)), None)
    treatment_col = cfg.get("treatment") or next((c for c in df.columns if re.search(r"stage|treatment|处理|阶段", c, re.I)), None)
    outcome_col = cfg.get("outcome") or next((c for c in df.columns if re.search(r"outcome_binary|outcome|target|结果|支持", c, re.I)), None)

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
    return time_col, group_col, treatment_col, outcome_col, numeric, categorical, binaries


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
            "min": s.min(), "max": s.max(), "levels": "",
        })
    for c in categorical:
        s = df[c].dropna().astype(str)
        vc = s.value_counts()
        rows.append({
            "variable": c, "type": "categorical", "n": len(s),
            "missing": len(df) - len(s), "mean": np.nan, "sd": np.nan,
            "median": np.nan, "p25": np.nan, "p75": np.nan,
            "min": np.nan, "max": np.nan,
            "levels": "; ".join(f"{k}:{v}" for k, v in vc.head(8).items()),
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
                numeric: list[str], kind: str) -> pd.DataFrame:
    rows = []
    for c in categorical:
        sub = df[[c, outcome]].dropna()
        if sub[c].nunique() < 2 or len(sub) < 10:
            continue
        if kind in {"binary", "categorical"}:
            tab = pd.crosstab(sub[c], sub[outcome])
            if tab.shape[0] < 2 or tab.shape[1] < 2:
                continue
            try:
                chi2, p, dof, expected = stats.chi2_contingency(tab, correction=False)
                test = "chi-square"
                if tab.shape == (2, 2) and (expected < 5).any():
                    _, p = stats.fisher_exact(tab)
                    test = "Fisher exact"
                effect = cramers_v(tab)
            except Exception:
                chi2, p, effect, test = np.nan, np.nan, np.nan, "failed"
            note = "Cramér's V"
            if kind == "categorical":
                note += "; multiclass outcome"
            rows.append({"outcome": outcome, "predictor": c, "test": test,
                         "statistic": chi2, "p": p, "effect": effect,
                         "n": len(sub), "note": note if test != "failed" else ""})
        else:
            groups = [pd.to_numeric(g[outcome], errors="coerce").dropna().values
                      for _, g in sub.groupby(c)]
            groups = [g for g in groups if len(g) >= 5]
            if len(groups) >= 2:
                try:
                    stat, p = stats.kruskal(*groups)
                    rows.append({"outcome": outcome, "predictor": c, "test": "Kruskal-Wallis",
                                 "statistic": stat, "p": p, "effect": np.nan,
                                 "n": len(sub), "note": "continuous outcome"})
                except Exception:
                    pass
    for c in numeric:
        sub = df[[c, outcome]].dropna()
        sub[c] = pd.to_numeric(sub[c], errors="coerce")
        sub = sub.dropna()
        if len(sub) < 10 or sub[c].nunique() < 2:
            continue
        if kind == "binary":
            groups = [sub.loc[sub[outcome] == v, c].values for v in [0, 1]]
            groups = [g for g in groups if len(g) > 0]
            if len(groups) == 2:
                try:
                    stat, p = stats.mannwhitneyu(groups[0], groups[1], alternative="two-sided")
                    rows.append({"outcome": outcome, "predictor": c, "test": "Mann-Whitney",
                                 "statistic": stat, "p": p, "effect": np.nan,
                                 "n": len(sub), "note": "binary outcome; nonparametric"})
                except Exception:
                    pass
        elif kind == "categorical":
            groups = [pd.to_numeric(g[c], errors="coerce").dropna().values
                      for _, g in sub.groupby(outcome)]
            groups = [g for g in groups if len(g) >= 5]
            if len(groups) >= 2:
                try:
                    stat, p = stats.kruskal(*groups)
                    rows.append({"outcome": outcome, "predictor": c, "test": "Kruskal-Wallis",
                                 "statistic": stat, "p": p, "effect": np.nan,
                                 "n": len(sub), "note": "multiclass outcome"})
                except Exception:
                    pass
        else:
            try:
                r, p = stats.pearsonr(sub[c], pd.to_numeric(sub[outcome], errors="coerce"))
                rows.append({"outcome": outcome, "predictor": c, "test": "Pearson r",
                             "statistic": r, "p": p, "effect": r,
                             "n": len(sub), "note": "continuous outcome"})
            except Exception:
                pass
    return pd.DataFrame(rows).sort_values("p", na_position="last") if rows else pd.DataFrame()


def correlations(df: pd.DataFrame, numeric: list[str], binaries: list[str]) -> pd.DataFrame:
    cols = [c for c in numeric + binaries if c in df.columns]
    cols = [c for c in cols if not is_constant(df[c])][:14]
    rows = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            sub = df[[a, b]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(sub) < 10 or sub[a].nunique() < 2 or sub[b].nunique() < 2:
                continue
            try:
                r, p = stats.pearsonr(sub[a], sub[b])
                if np.isfinite(r):
                    rows.append({"var1": a, "var2": b, "method": "Pearson",
                                 "r": r, "p": p, "n": len(sub)})
            except Exception:
                continue
    return pd.DataFrame(rows).sort_values("p", na_position="last") if rows else pd.DataFrame()


def univariate_models(df: pd.DataFrame, outcome: str, numeric: list[str],
                      binaries: list[str], kind: str,
                      categorical: list[str] | None = None):
    """Return (models, skipped_models). Perfect separation is skipped, not reported as an OR."""
    skipped = []
    if sm is None:
        return pd.DataFrame(), pd.DataFrame()
    if kind == "categorical":
        return pd.DataFrame(), pd.DataFrame([{
            "outcome": outcome, "predictor": "(all)",
            "reason": "multiclass outcome; use multinomial logit or collapse categories",
        }])
    out = pd.to_numeric(df[outcome], errors="coerce")
    rows = []
    predictors = [c for c in numeric + binaries
                  if c != outcome and c in df.columns and not is_constant(df[c])][:20]
    for c in predictors:
        sub = pd.DataFrame({outcome: out, c: pd.to_numeric(df[c], errors="coerce")}).dropna()
        if len(sub) < 20 or sub[c].nunique() < 2 or sub[outcome].nunique() < 2:
            continue
        if kind == "binary":
            tab = pd.crosstab(sub[c], sub[outcome])
            if tab.shape == (2, 2) and (tab.values == 0).any():
                skipped.append({"outcome": outcome, "predictor": c,
                                "reason": "perfect separation (empty 2x2 cell)"})
                continue
        try:
            X = sm.add_constant(sub[[c]].astype(float))
            y = sub[outcome].astype(float)
            if kind == "binary":
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = sm.Logit(y, X).fit(disp=0)
                coef = model.params[c]
                lo, hi = model.conf_int().loc[c]
                if abs(coef) > 10 or (hi - lo) > 20:
                    skipped.append({"outcome": outcome, "predictor": c,
                                    "reason": "unstable estimate; possible separation"})
                    continue
                rows.append({"outcome": outcome, "predictor": c, "model": "logit",
                             "effect": math.exp(coef), "ci_low": math.exp(lo),
                             "ci_high": math.exp(hi), "p": model.pvalues[c],
                             "n": len(sub), "metric": "OR"})
            else:
                model = sm.OLS(y, X).fit()
                coef = model.params[c]
                lo, hi = model.conf_int().loc[c]
                rows.append({"outcome": outcome, "predictor": c, "model": "ols",
                             "effect": coef, "ci_low": lo, "ci_high": hi,
                             "p": model.pvalues[c], "n": len(sub), "metric": "beta"})
        except Exception as exc:
            skipped.append({"outcome": outcome, "predictor": c,
                            "reason": f"{type(exc).__name__}: {exc}"[:200]})
            continue
    # Multi-level categorical predictors: dummy-code them so they are not
    # silently absent from the univariate screening table.
    for c in (categorical or []):
        if c == outcome or c in predictors or c not in df.columns or is_constant(df[c]):
            continue
        levels = df[c].dropna().astype(str).unique()
        if len(levels) < 2:
            continue
        if len(levels) > 12:
            skipped.append({"outcome": outcome, "predictor": c,
                            "reason": f"too many levels ({len(levels)}); recode before modeling"})
            continue
        sub = pd.DataFrame({"y": out, "g": df[c].astype(str)}).dropna()
        if len(sub) < 20 or sub["y"].nunique() < 2:
            continue
        try:
            dummies = pd.get_dummies(sub["g"], prefix=c, drop_first=True, dtype=float)
            X = sm.add_constant(dummies)
            y = sub["y"].astype(float)
            if kind == "binary":
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = sm.Logit(y, X).fit(disp=0)
                for term in dummies.columns:
                    coef = model.params[term]
                    lo, hi = model.conf_int().loc[term]
                    if abs(coef) > 10 or (hi - lo) > 20:
                        skipped.append({"outcome": outcome, "predictor": term,
                                        "reason": "unstable estimate; possible separation"})
                        continue
                    rows.append({"outcome": outcome, "predictor": term, "model": "logit (dummy)",
                                 "effect": math.exp(coef), "ci_low": math.exp(lo),
                                 "ci_high": math.exp(hi), "p": model.pvalues[term],
                                 "n": len(sub), "metric": "OR"})
            else:
                model = sm.OLS(y, X).fit()
                for term in dummies.columns:
                    coef = model.params[term]
                    lo, hi = model.conf_int().loc[term]
                    rows.append({"outcome": outcome, "predictor": term, "model": "ols (dummy)",
                                 "effect": coef, "ci_low": lo, "ci_high": hi,
                                 "p": model.pvalues[term], "n": len(sub), "metric": "beta"})
        except Exception as exc:
            skipped.append({"outcome": outcome, "predictor": c,
                            "reason": f"dummy model: {type(exc).__name__}: {exc}"[:200]})
    models = pd.DataFrame(rows).sort_values("p", na_position="last") if rows else pd.DataFrame()
    skipped_df = pd.DataFrame(skipped) if skipped else pd.DataFrame()
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
        return pd.DataFrame([{
            "variable": outcome, "type": "outcome (binary)", "n": n, "missing": missing,
            "mean": k / len(y) if len(y) else np.nan, "sd": np.nan,
            "median": np.nan, "p25": np.nan, "p75": np.nan,
            "min": 0, "max": 1, "levels": levels,
            "rate_ci": f"{k}/{n} = {k / n * 100:.1f}% ({lo * 100:.1f}–{hi * 100:.1f}%)" if n else "",
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
        "levels": "; ".join(f"{k}:{v}" for k, v in vc.head(10).items()), "rate_ci": "",
    }])


def write_md(path: str, desc: pd.DataFrame, tests: pd.DataFrame,
             rates: pd.DataFrame, corr: pd.DataFrame, uni: pd.DataFrame,
             uni_skipped: pd.DataFrame, meta: dict):
    lines = ["# 自动统计筛查包", "",
             f"- 数据：`{meta['data']}`",
             f"- 筛选：`{meta['filter']}`",
             f"- 分析样本：{meta['n']:,}",
             f"- 结果变量：`{meta['outcome']}`（{meta.get('outcome_kind', '')}）"]
    if meta.get("outcome_map"):
        lines.append(f"- 二元编码：`{meta['outcome_map']}`")
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
    outcome_rows = desc[desc["type"].str.startswith("outcome")]
    if not outcome_rows.empty and outcome_rows.iloc[0].get("rate_ci"):
        lines.append(f"\n结果变量发生率：{outcome_rows.iloc[0]['rate_ci']}（95% Wilson CI）。")

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
        lines += ["| 结果 | 预测变量 | 检验 | p | 效应量 | N | 备注 |", "|---|---|---|---:|---:|---:|---|"]
        for _, r in tests.head(15).iterrows():
            lines.append(f"| {r['outcome']} | {r['predictor']} | {r['test']} | {fmt_p(r['p'])} | "
                         f"{fmt(r['effect'], 3)} | {r['n']} | {r.get('note', '')} |")
    lines += ["", "## 4. 单变量模型（按 p 排序，前 15）", ""]
    if uni.empty:
        lines.append("无可估计的单变量模型。")
    else:
        lines += ["| 结果 | 预测变量 | 模型 | 效应 | 95%CI | p | N |", "|---|---|---|---:|---|---:|---:|"]
        for _, r in uni.head(15).iterrows():
            lines.append(f"| {r['outcome']} | {r['predictor']} | {r['model']} | {fmt(r['effect'], 3)} | "
                         f"{fmt(r['ci_low'], 3)}–{fmt(r['ci_high'], 3)} | {fmt_p(r['p'])} | {r['n']} |")
    if uni_skipped is not None and not uni_skipped.empty:
        lines += ["", "以下变量未估计（通常因为完全分离、估计不稳定或为多元结果）：", ""]
        for _, r in uni_skipped.head(15).iterrows():
            lines.append(f"- {r['predictor']}：{r['reason']}")
    lines += ["", "## 5. 相关（按 p 排序，前 15）", ""]
    if corr.empty:
        lines.append("无可用相关。")
    else:
        lines += ["| 变量 1 | 变量 2 | 方法 | r | p | N |", "|---|---|---|---:|---:|---:|"]
        for _, r in corr.head(15).iterrows():
            lines.append(f"| {r['var1']} | {r['var2']} | {r['method']} | {fmt(r['r'], 3)} | "
                         f"{fmt_p(r['p'])} | {r['n']} |")
    lines += ["", "## 6. 下一步", "",
              "1. 把有实质意义的变量纳入预设定多变量模型；不要按 p 值筛变量。",
              "2. 对分类变量做哑变量/参照组；报告每个模型 N。",
              "3. 用 `auto_chart_pack.py` 生成对应图，再用 SPSS 复核最终模型。",
              "4. 把所有做/不做的分析写入 `analysis_manifest.md`。"]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Automatic descriptive/bivariate screening.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--out", default="output/analysis_pack")
    parser.add_argument("--max-categories", type=int, default=12)
    args = parser.parse_args()

    if not os.path.isfile(args.data):
        print(f"ERROR: data not found: {args.data}", file=sys.stderr)
        return 2
    df = pd.read_csv(args.data, encoding="utf-8-sig", low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]
    cfg = {}
    if args.config:
        if not os.path.isfile(args.config):
            print(f"ERROR: config not found: {args.config}", file=sys.stderr)
            return 2
        with open(args.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
    try:
        df, filter_desc = apply_filter(df, cfg)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if df.empty:
        print("ERROR: filter returned 0 rows; check filter_query/filter", file=sys.stderr)
        return 2

    outcome_col = cfg.get("outcome")
    if outcome_col and outcome_col not in df.columns:
        print(f"ERROR: outcome column not found: {outcome_col}", file=sys.stderr)
        return 2
    if not outcome_col:
        regex_hits = [c for c in df.columns
                      if re.search(r"outcome_binary|outcome|target|结果|支持", c, re.I)
                      and not is_id_like(c, df[c])]
        if len(regex_hits) > 1:
            print(f"ERROR: multiple outcome-like columns: {regex_hits}; pass config.outcome",
                  file=sys.stderr)
            return 2
        if regex_hits:
            outcome_col = regex_hits[0]
        else:
            candidates = [c for c in df.columns
                          if is_binary(df[c]) and 0.05 < float(pd.to_numeric(df[c], errors="coerce").mean()) < 0.95
                          and not is_id_like(c, df[c])]
            if len(candidates) == 1:
                outcome_col = candidates[0]
            elif len(candidates) > 1:
                print("ERROR: cannot infer outcome; candidates: "
                      f"{candidates}. Pass config.outcome", file=sys.stderr)
                return 2
            else:
                print("ERROR: no outcome column found; pass config.outcome", file=sys.stderr)
                return 2
    cfg = dict(cfg)
    cfg["outcome"] = outcome_col

    kind, encoded, outcome_map, kind_msg = outcome_kind(
        df[outcome_col], args.max_categories, cfg.get("outcome_map"))
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

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    desc = describe(df, numeric, categorical)
    outcome_desc = describe_outcome(df, outcome_col, kind)
    desc = pd.concat([outcome_desc, desc], ignore_index=True)
    test_cats = list(dict.fromkeys(
        [c for c in categorical if df[c].nunique(dropna=True) <= max(args.max_categories, 2)]
        + binary_predictors
    ))
    rates = binary_rates(df, outcome_col, test_cats) if kind == "binary" else pd.DataFrame()
    if kind == "binary":
        y = pd.to_numeric(df[outcome_col], errors="coerce").dropna()
        k, n = int(y.sum()), len(y)
        lo, hi = wilson_ci(k, n)
        overall = pd.DataFrame([{"predictor": "(overall)", "level": "", "n": n,
                                 "events": k, "rate": k / n, "ci_low": lo, "ci_high": hi}])
        rates = pd.concat([overall, rates], ignore_index=True) if not rates.empty else overall
    tests = group_tests(df, outcome_col, test_cats, numeric, kind)
    corr_binaries = binary_predictors + ([outcome_col] if kind in {"binary", "continuous"} else [])
    corr = correlations(df, numeric, corr_binaries)
    uni, uni_skipped = univariate_models(
        df, outcome_col, numeric, binary_predictors, kind, categorical)

    tables = [("descriptives", desc), ("group_tests", tests),
              ("binary_rates", rates), ("correlations", corr),
              ("univariate_models", uni), ("univariate_skipped", uni_skipped)]
    for name, table in tables:
        if table is not None and not table.empty:
            table.to_csv(os.path.join(out_dir, f"{name}.csv"), index=False, encoding="utf-8-sig")
    meta = {"data": os.path.abspath(args.data), "n": len(df),
            "filter": filter_desc,
            "outcome": outcome_col, "outcome_kind": kind,
            "outcome_map": outcome_map,
            "group": group_col, "treatment": treatment_col,
            "numeric": numeric, "categorical": categorical, "binary": binary_predictors,
            "dropped_duplicates": dropped_duplicates,
            "warnings": warnings_list}
    with open(os.path.join(out_dir, "analysis_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    write_md(os.path.join(out_dir, "analysis_pack.md"), desc, tests, rates, corr,
             uni, uni_skipped, meta)
    print(f"n: {len(df)}  outcome: {outcome_col} ({kind})  "
          f"descriptives: {len(desc)}  tests: {len(tests)}  "
          f"correlations: {len(corr)}  univariate: {len(uni)}")
    if uni_skipped is not None and not uni_skipped.empty:
        print(f"univariate skipped: {len(uni_skipped)} -> univariate_skipped.csv")
    for w in warnings_list:
        print(f"WARN: {w}")
    print(f"output: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
