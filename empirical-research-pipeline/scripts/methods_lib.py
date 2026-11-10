#!/usr/bin/env python3
"""Statistical cores for the sixteen analysis methods.

Everything here is plain functions over DataFrames: no CLI, no plotting, no
files. `methods_pack.py` owns the catalogue, the preconditions, the figures and
the report; this module owns the arithmetic.

Design rules, learned the hard way in this repository:

* A function never returns a number it cannot defend. If the design does not
  support the test (three groups for a t test, a continuous outcome for a
  binary model, fewer observations than parameters), it raises `MethodError`
  with the reason and what to run instead.
* Effect sizes travel with p values. "p < .05" alone is not a finding.
* Every approximation says so in its docstring (for example the K-S test here
  uses estimated parameters, SPSS uses the Lilliefors correction).

Domain: none. Nothing in this file knows what the variables mean.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# errors and small helpers
# ---------------------------------------------------------------------------


class MethodError(ValueError):
    """Raised when the data cannot support the requested method."""


@dataclass
class Result:
    """What every method returns: tables, key statistics, and a verdict."""

    method: str
    tables: list = field(default_factory=list)          # [(name, DataFrame)]
    stats: dict = field(default_factory=dict)
    verdict: list = field(default_factory=list)         # plain sentences
    notes: list = field(default_factory=list)           # caveats
    status: str = "ok"                                  # ok | skipped


def _clean(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").dropna()


def _fmt_p(p: float) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "p=NA"
    if p < 0.001:
        return "p<.001"
    return f"p={p:.3f}"


def _stars(p: float) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return ""
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    if p < 0.10:
        return "."
    return ""


def _num(col: str, df: pd.DataFrame) -> pd.Series:
    if col not in df.columns:
        raise MethodError(f"列不存在：{col}")
    out = pd.to_numeric(df[col], errors="coerce")
    return out


def _require_n(n: int, k: int, what: str) -> None:
    if n <= k:
        raise MethodError(f"样本量不足：{what} 需要 n>{k}，实际 n={n}")


# ---------------------------------------------------------------------------
# 1. descriptive statistics
# ---------------------------------------------------------------------------


def describe(df: pd.DataFrame, columns: list | None = None,
             alpha: float = 0.05) -> Result:
    """Describe continuous and categorical columns, and say which centre to use.

    SPSS note: for a normally distributed variable the mean is meaningful; for a
    skewed one the median and quartiles are (the note in the source material
    says exactly this, and it is the single most common reporting error).
    """
    cols = columns or [c for c in df.columns if c != "rel_path"]
    rows, notes, skewed = [], [], []
    for col in cols:
        s = df[col]
        numeric = pd.to_numeric(s, errors="coerce")
        n_obs = int(s.notna().sum())
        if numeric.notna().sum() >= max(3, int(0.8 * n_obs)) \
                and numeric.nunique() > 10:
            x = numeric.dropna()
            row = {"variable": col, "type": "连续", "n": int(x.size),
                   "missing": int(s.isna().sum()),
                   "mean": round(float(x.mean()), 4),
                   "sd": round(float(x.std(ddof=1)), 4),
                   "median": round(float(x.median()), 4),
                   "p25": round(float(x.quantile(0.25)), 4),
                   "p75": round(float(x.quantile(0.75)), 4),
                   "min": round(float(x.min()), 4),
                   "max": round(float(x.max()), 4),
                   "skew": round(float(stats.skew(x, bias=False)), 3),
                   "kurtosis": round(float(stats.kurtosis(x, bias=False)), 3)}
            try:
                row["normality_p"] = round(float(stats.shapiro(x).pvalue), 4) \
                    if 3 <= x.size <= 5000 else None
            except Exception:
                row["normality_p"] = None
            normal = row["normality_p"] is None or row["normality_p"] >= alpha
            row["report"] = ("均值±标准差" if normal else "中位数（P25，P75）")
            if not normal:
                skewed.append(col)
            rows.append(row)
        else:
            vc = s.astype("string").value_counts(dropna=True)
            if vc.empty:
                continue
            top = vc.index[0]
            row = {"variable": col, "type": "分类", "n": int(vc.sum()),
                   "missing": int(s.isna().sum()),
                   "levels": int(vc.size), "mode": str(top),
                   "mode_pct": round(float(vc.iloc[0] / vc.sum() * 100), 1),
                   "report": "频数（构成比%）"}
            rows.append(row)
    table = pd.DataFrame(rows)
    if skewed:
        head = "、".join(skewed[:6]) + ("…" if len(skewed) > 6 else "")
        notes.append(f"{len(skewed)}/{len(rows)} 个连续变量偏离正态（Shapiro p<{alpha}）："
                     f"{head}；这些变量按中位数（P25，P75）报告，不报均值。")
    return Result("descriptive", [("descriptive", table)],
                  {"n": int(len(df))}, notes=notes)


# ---------------------------------------------------------------------------
# 2. normality
# ---------------------------------------------------------------------------


def normality(df: pd.DataFrame, column: str, alpha: float = 0.05) -> Result:
    """Shapiro-Wilk (n<=5000) or K-S with estimated parameters (n>5000)."""
    x = _clean(df[column])
    if x.size < 3:
        raise MethodError(f"{column} 的有效值只有 {x.size} 个，无法检验正态性")
    if x.size <= 5000:
        stat, p = stats.shapiro(x)
        test = "Shapiro-Wilk"
    else:
        # SPSS reports K-S with a Lilliefors correction; scipy's kstest with
        # estimated parameters is close but anti-conservative. Say so.
        z = (x - x.mean()) / x.std(ddof=1)
        stat, p = stats.kstest(z, "norm")
        test = "K-S（参数由样本估计，未做 Lilliefors 校正，p 偏小）"
    normal = p >= alpha
    verdict = [
        f"{column}：{test} 统计量={stat:.3f}，{_fmt_p(p)}，"
        f"{'未拒绝正态' if normal else '拒绝正态'}（α={alpha}）。",
        ("可用参数检验（t/ANOVA/线性回归）。" if normal
         else "改用非参数检验（Mann-Whitney / Wilcoxon / Kruskal-Wallis）或检查离群值。"),
    ]
    tab = pd.DataFrame([{"variable": column, "test": test, "statistic": round(float(stat), 4),
                         "p": round(float(p), 6), "n": int(x.size),
                         "normal": bool(normal)}])
    return Result("normality", [("normality", tab)],
                  {"p": float(p), "normal": bool(normal)}, verdict)


# ---------------------------------------------------------------------------
# 3. chi-square
# ---------------------------------------------------------------------------


def chi_square(df: pd.DataFrame, row: str, col: str,
               alpha: float = 0.05) -> Result:
    """Pearson chi-square on a contingency table, with the checks that matter."""
    sub = df[[row, col]].dropna()
    if sub.empty:
        raise MethodError("两列都没有有效值")
    tab = pd.crosstab(sub[row], sub[col])
    if tab.shape[0] < 2 or tab.shape[1] < 2:
        raise MethodError(f"列联表只有 {tab.shape[0]}×{tab.shape[1]}，至少需要 2×2")
    chi2, p, dof, expected = stats.chi2_contingency(tab, correction=False)
    n = int(tab.values.sum())
    cramers = math.sqrt(chi2 / (n * (min(tab.shape) - 1))) if n else float("nan")
    min_exp = float(expected.min())
    low_cells = int((expected < 5).sum())
    # Odds ratio for 2x2, Fisher when cells are sparse (SPSS's exact test).
    extra = {}
    if tab.shape == (2, 2):
        a, b = tab.values[0]
        c, d = tab.values[1]
        orv = (a * d) / (b * c) if b * c else float("inf")
        extra = {"odds_ratio": round(float(orv), 4)}
        if min_exp < 5:
            _, p_fisher = stats.fisher_exact(tab.values)
            extra["fisher_p"] = round(float(p_fisher), 6)
    verdict = [
        f"{row} 与 {col}：χ²({dof})={chi2:.3f}，{_fmt_p(p)}"
        f"{'，差异显著' if p < alpha else '，差异不显著'}。",
        f"关联强度 Cramér's V={cramers:.3f}"
        f"（{'弱' if cramers < 0.2 else '中等' if cramers < 0.4 else '较强'}）。",
    ]
    notes = []
    if low_cells:
        notes.append(f"{low_cells}/{expected.size} 个单元格期望频数<5"
                     f"（最小 {min_exp:.2f}）；SPSS 会提示，"
                     f"{'已给出 Fisher 精确检验' if 'fisher_p' in extra else '结论需谨慎'}。")
    if tab.shape == (2, 2) and "fisher_p" in extra:
        verdict.append(f"Fisher 精确检验 {_fmt_p(extra['fisher_p'])}。")
    pct = pd.DataFrame(tab)
    return Result("chi_square", [("contingency", pct), ("expected", pd.DataFrame(expected)),
                                 ("row_percent", (tab.div(tab.sum(axis=1), axis=0) * 100).round(1))],
                  {"chi2": float(chi2), "dof": int(dof), "p": float(p),
                   "cramers_v": float(cramers), **extra}, verdict, notes)


def chi_square_pairs(df: pd.DataFrame, row: str, col: str,
                     adjust: str = "bonferroni", alpha: float = 0.05) -> Result:
    """Pairwise 2x2 tests when a level has more than two categories."""
    sub = df[[row, col]].dropna()
    levels = list(pd.crosstab(sub[row], sub[col]).index)
    rows = []
    for a, b in itertools.combinations(levels, 2):
        part = sub[sub[row].isin([a, b])]
        tab = pd.crosstab(part[row], part[col])
        if tab.shape != (2, 2):
            continue
        _, p, _, exp = stats.chi2_contingency(tab, correction=False)
        rows.append({"pair": f"{a} vs {b}", "n": int(tab.values.sum()),
                     "p_raw": round(float(p), 6),
                     "min_expected": round(float(exp.min()), 2)})
    if not rows:
        raise MethodError("没有可比较的 2×2 子表")
    out = pd.DataFrame(rows)
    m = len(out)
    out["p_adj"] = (out["p_raw"] * m).clip(upper=1).round(6) if adjust == "bonferroni" \
        else out["p_raw"]
    out["significant"] = out["p_adj"] < alpha
    sig = out[out["significant"]]["pair"].tolist()
    verdict = [f"两两比较（{adjust} 校正，共 {m} 次）："
               + ("；".join(sig) + " 差异显著。" if sig else "没有任意一对差异显著。")]
    return Result("chi_square_pairs", [("pairwise", out)], {"pairs": m}, verdict)


# ---------------------------------------------------------------------------
# 4. t tests
# ---------------------------------------------------------------------------


def t_test_independent(df: pd.DataFrame, value: str, group: str,
                       alpha: float = 0.05) -> Result:
    """Independent-samples t test with Levene, Cohen's d and a Welch fallback."""
    sub = df[[value, group]].dropna()
    sub[value] = pd.to_numeric(sub[value], errors="coerce")
    sub = sub.dropna()
    levels = list(pd.unique(sub[group]))
    if len(levels) != 2:
        raise MethodError(f"{group} 有 {len(levels)} 个取值，独立样本 t 检验只接受 2 组；"
                          f"三组及以上请用方差分析或 Kruskal-Wallis")
    a = sub.loc[sub[group] == levels[0], value].astype(float)
    b = sub.loc[sub[group] == levels[1], value].astype(float)
    _require_n(len(a) + len(b), 2, "独立样本 t 检验")
    lev_stat, lev_p = stats.levene(a, b)
    equal_var = lev_p >= alpha
    t, p = stats.ttest_ind(a, b, equal_var=equal_var)
    n1, n2 = len(a), len(b)
    s1, s2 = a.std(ddof=1), b.std(ddof=1)
    pooled = math.sqrt(((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2) / max(1, n1 + n2 - 2))
    d = (a.mean() - b.mean()) / pooled if pooled else float("nan")
    diff_ci = None
    try:
        se = math.sqrt(s1 ** 2 / n1 + s2 ** 2 / n2) if not equal_var else \
            pooled * math.sqrt(1 / n1 + 1 / n2)
        dof = (n1 + n2 - 2) if equal_var else None
        q = stats.t.ppf(1 - alpha / 2, dof or min(n1, n2) - 1)
        diff_ci = (round(float(a.mean() - b.mean() - q * se), 4),
                   round(float(a.mean() - b.mean() + q * se), 4))
    except Exception:
        pass
    verdict = [
        f"Levene 方差齐性 {_fmt_p(lev_p)} → {'方差相等' if equal_var else '方差不相等'}，"
        f"采用{'合并方差' if equal_var else 'Welch 校正'}的 t 值。",
        f"{value} 在 {levels[0]}(n={n1}, M={a.mean():.3f}) 与 {levels[1]}(n={n2}, M={b.mean():.3f})："
        f"t={t:.3f}，{_fmt_p(p)}，Cohen's d={d:.3f}。",
    ]
    tab = pd.DataFrame([{"group": levels[0], "n": n1, "mean": round(float(a.mean()), 4),
                         "sd": round(float(s1), 4)},
                        {"group": levels[1], "n": n2, "mean": round(float(b.mean()), 4),
                         "sd": round(float(s2), 4)}])
    test = pd.DataFrame([{"levene_stat": round(float(lev_stat), 4),
                          "levene_p": round(float(lev_p), 6), "equal_var": bool(equal_var),
                          "t": round(float(t), 4), "dof": (n1 + n2 - 2) if equal_var else None,
                          "p": round(float(p), 6), "cohens_d": round(float(d), 4),
                          "mean_diff_ci_low": diff_ci[0] if diff_ci else None,
                          "mean_diff_ci_high": diff_ci[1] if diff_ci else None}])
    return Result("t_test_independent", [("groups", tab), ("test", test)],
                  {"t": float(t), "p": float(p), "d": float(d), "equal_var": bool(equal_var)},
                  verdict)


def t_test_paired(df: pd.DataFrame, before: str, after: str,
                  alpha: float = 0.05) -> Result:
    """Paired t test; correlation of the pair is reported first, as SPSS does."""
    a = pd.to_numeric(df[before], errors="coerce")
    b = pd.to_numeric(df[after], errors="coerce")
    both = pd.concat([a, b], axis=1).dropna()
    if both.shape[0] < 3:
        raise MethodError("配对样本少于 3 对，无法检验")
    diff = both.iloc[:, 0] - both.iloc[:, 1]
    r, r_p = stats.pearsonr(both.iloc[:, 0], both.iloc[:, 1])
    t, p = stats.ttest_rel(both.iloc[:, 0], both.iloc[:, 1])
    dz = float(diff.mean() / diff.std(ddof=1)) if diff.std(ddof=1) else float("nan")
    verdict = [
        f"配对相关 r={r:.3f}（{_fmt_p(r_p)}）"
        f"{'，可用配对 t 检验' if r_p < alpha else '，配对关系弱，配对检验的收益有限'}。",
        f"前后差值 M={diff.mean():.3f}（SD={diff.std(ddof=1):.3f}），"
        f"t({len(both) - 1})={t:.3f}，{_fmt_p(p)}，dz={dz:.3f}。",
    ]
    tab = pd.DataFrame([{"pair": f"{before} - {after}", "n": int(len(both)),
                         "mean_before": round(float(both.iloc[:, 0].mean()), 4),
                         "mean_after": round(float(both.iloc[:, 1].mean()), 4),
                         "mean_diff": round(float(diff.mean()), 4),
                         "correlation": round(float(r), 4), "corr_p": round(float(r_p), 6),
                         "t": round(float(t), 4), "p": round(float(p), 6),
                         "cohens_dz": round(float(dz), 4)}])
    return Result("t_test_paired", [("paired", tab)], {"t": float(t), "p": float(p)}, verdict)


# ---------------------------------------------------------------------------
# 5. ANOVA (+ post hoc)
# ---------------------------------------------------------------------------


def anova(df: pd.DataFrame, value: str, group: str, alpha: float = 0.05) -> Result:
    """One-way ANOVA, Welch correction when variances differ, eta squared."""
    sub = df[[value, group]].dropna()
    sub[value] = pd.to_numeric(sub[value], errors="coerce")
    sub = sub.dropna()
    levels = [lv for lv in pd.unique(sub[group]) if pd.notna(lv)]
    if len(levels) < 2:
        raise MethodError(f"{group} 只有 {len(levels)} 个组")
    if len(levels) == 2:
        raise MethodError("只有两组时请用独立样本 t 检验（两者的 p 相同，但 t 更易读）")
    groups = [sub.loc[sub[group] == lv, value].astype(float) for lv in levels]
    for lv, g in zip(levels, groups):
        if len(g) < 2:
            raise MethodError(f"组 {lv} 只有 {len(g)} 个观测")
    f, p = stats.f_oneway(*groups)
    lev_stat, lev_p = stats.levene(*groups)
    grand = sub[value].astype(float).mean()
    ss_between = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)
    ss_total = float(((sub[value].astype(float) - grand) ** 2).sum())
    eta2 = ss_between / ss_total if ss_total else float("nan")
    welch = None
    try:
        from statsmodels.stats.oneway import anova_oneway
        res = anova_oneway(sub[value].astype(float), sub[group],
                           use_var="unequal", welch_correction=True)
        welch = (float(res.statistic), float(res.pvalue))
    except Exception:
        pass
    verdict = [
        f"Levene {_fmt_p(lev_p)} → {'方差齐' if lev_p >= alpha else '方差不齐'}。",
        f"单因素方差分析 F({len(levels) - 1},{len(sub) - len(levels)})={f:.3f}，"
        f"{_fmt_p(p)}，η²={eta2:.3f}。",
        (f"方差不齐，Welch 校正 F={welch[0]:.3f}，{_fmt_p(welch[1])}。" if welch and lev_p < alpha else
         ("方差齐，无需 Welch 校正。" if welch else "")),
    ]
    desc = pd.DataFrame([{"group": lv, "n": len(g), "mean": round(float(g.mean()), 4),
                          "sd": round(float(g.std(ddof=1)), 4)}
                         for lv, g in zip(levels, groups)])
    test = pd.DataFrame([{"F": round(float(f), 4), "p": round(float(p), 6),
                          "eta2": round(float(eta2), 4),
                          "levene_p": round(float(lev_p), 6),
                          "welch_F": round(welch[0], 4) if welch else None,
                          "welch_p": round(welch[1], 6) if welch else None}])
    return Result("anova", [("groups", desc), ("anova", test)],
                  {"F": float(f), "p": float(p), "eta2": float(eta2)}, verdict)


def posthoc(df: pd.DataFrame, value: str, group: str, adjust: str = "bonferroni",
            alpha: float = 0.05) -> Result:
    """Pairwise comparisons after a significant omnibus test."""
    sub = df[[value, group]].dropna()
    sub[value] = pd.to_numeric(sub[value], errors="coerce")
    sub = sub.dropna()
    levels = [lv for lv in pd.unique(sub[group]) if pd.notna(lv)]
    if len(levels) < 3:
        raise MethodError("事后比较需要三组及以上")
    groups = [sub.loc[sub[group] == lv, value].astype(float) for lv in levels]
    n_total = len(sub)
    k = len(levels)
    mse = sum((len(g) - 1) * g.var(ddof=1) for g in groups) / max(1, n_total - k)
    rows = []
    for (i, a), (j, b) in itertools.combinations(list(enumerate(levels)), 2):
        ga, gb = groups[i], groups[j]
        se = math.sqrt(mse * (1 / len(ga) + 1 / len(gb)))
        t = (ga.mean() - gb.mean()) / se if se else float("nan")
        p = 2 * (1 - stats.t.cdf(abs(t), n_total - k))
        rows.append({"pair": f"{a} vs {b}", "mean_diff": round(float(ga.mean() - gb.mean()), 4),
                     "se": round(float(se), 4), "t": round(float(t), 4),
                     "p_raw": round(float(p), 6)})
    out = pd.DataFrame(rows)
    m = len(out)
    out["p_adj"] = (out["p_raw"] * m).clip(upper=1).round(6) if adjust == "bonferroni" \
        else out["p_raw"]
    out["stars"] = out["p_adj"].map(_stars)
    sig = out.loc[out["p_adj"] < alpha, "pair"].tolist()
    verdict = [f"事后比较（{adjust}，共 {m} 对）："
               + ("；".join(sig) if sig else "没有任意一对差异显著")]
    if out["p_raw"].min() < alpha <= out["p_adj"].min():
        verdict.append("有配对在未校正时显著、校正后不显著——这是多重比较的典型现象，"
                       "不要按未校正的 p 报告。")
    return Result("posthoc", [("posthoc", out)], {"pairs": m}, verdict)


def kruskal(df: pd.DataFrame, value: str, group: str, alpha: float = 0.05) -> Result:
    """Kruskal-Wallis: the non-parametric stand-in for one-way ANOVA."""
    sub = df[[value, group]].dropna()
    sub[value] = pd.to_numeric(sub[value], errors="coerce")
    sub = sub.dropna()
    levels = [lv for lv in pd.unique(sub[group]) if pd.notna(lv)]
    if len(levels) < 2:
        raise MethodError("分组变量至少需要 2 个水平")
    groups = [sub.loc[sub[group] == lv, value].astype(float) for lv in levels]
    h, p = stats.kruskal(*groups)
    n = len(sub)
    eps2 = (h - len(levels) + 1) / (n - len(levels)) if n > len(levels) else float("nan")
    verdict = [f"Kruskal-Wallis H({len(levels) - 1})={h:.3f}，{_fmt_p(p)}，"
               f"ε²={eps2:.3f}（非参数效应量）。"]
    desc = pd.DataFrame([{"group": lv, "n": len(g), "median": round(float(g.median()), 4),
                          "p25": round(float(g.quantile(0.25)), 4),
                          "p75": round(float(g.quantile(0.75)), 4)}
                         for lv, g in zip(levels, groups)])
    return Result("kruskal", [("groups", desc),
                              ("kruskal", pd.DataFrame([{"H": round(float(h), 4),
                                                         "p": round(float(p), 6),
                                                         "epsilon2": round(float(eps2), 4)}]))],
                  {"H": float(h), "p": float(p)}, verdict)


def mannwhitney(df: pd.DataFrame, value: str, group: str, alpha: float = 0.05) -> Result:
    """Mann-Whitney U: two-group non-parametric comparison."""
    sub = df[[value, group]].dropna()
    sub[value] = pd.to_numeric(sub[value], errors="coerce")
    sub = sub.dropna()
    levels = list(pd.unique(sub[group]))
    if len(levels) != 2:
        raise MethodError(f"{group} 有 {len(levels)} 个取值，Mann-Whitney 只接受 2 组")
    a = sub.loc[sub[group] == levels[0], value].astype(float)
    b = sub.loc[sub[group] == levels[1], value].astype(float)
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    n1, n2 = len(a), len(b)
    rb = 1 - (2 * u) / (n1 * n2)  # rank-biserial correlation
    verdict = [f"Mann-Whitney U={u:.1f}，{_fmt_p(p)}；秩相关 r={rb:.3f}。",
               f"报告写成中位数（四分位）：{levels[0]} {a.median():.2f}"
               f"（{a.quantile(0.25):.2f}–{a.quantile(0.75):.2f}），"
               f"{levels[1]} {b.median():.2f}"
               f"（{b.quantile(0.25):.2f}–{b.quantile(0.75):.2f}）。"]
    return Result("mannwhitney", [("test", pd.DataFrame([{"U": float(u), "p": float(p),
                                                          "rank_biserial": round(float(rb), 4)}]))],
                  {"U": float(u), "p": float(p)}, verdict)


def wilcoxon(df: pd.DataFrame, before: str, after: str, alpha: float = 0.05) -> Result:
    """Wilcoxon signed-rank: paired non-parametric comparison."""
    a = pd.to_numeric(df[before], errors="coerce")
    b = pd.to_numeric(df[after], errors="coerce")
    both = pd.concat([a, b], axis=1).dropna()
    if both.shape[0] < 5:
        raise MethodError("配对样本少于 5 对，Wilcoxon 检验没有意义")
    stat, p = stats.wilcoxon(both.iloc[:, 0], both.iloc[:, 1])
    diff = both.iloc[:, 0] - both.iloc[:, 1]
    verdict = [f"Wilcoxon 符号秩 W={stat:.1f}，{_fmt_p(p)}；差值中位数={diff.median():.3f}。"]
    return Result("wilcoxon", [("test", pd.DataFrame([{"W": float(stat), "p": float(p),
                                                       "median_diff": round(float(diff.median()), 4)}]))],
                  {"W": float(stat), "p": float(p)}, verdict)


# ---------------------------------------------------------------------------
# 6. correlation
# ---------------------------------------------------------------------------


def correlation(df: pd.DataFrame, columns: list, method: str = "auto",
                alpha: float = 0.05) -> Result:
    """Pearson for normal pairs, Spearman otherwise (or when forced)."""
    cols = [c for c in columns if c in df.columns]
    if len(cols) < 2:
        raise MethodError("相关分析至少需要两个变量")
    data = df[cols].apply(pd.to_numeric, errors="coerce")
    used = method
    if method == "auto":
        nonnormal = 0
        for c in cols:
            x = data[c].dropna()
            if x.size >= 3:
                try:
                    if stats.shapiro(x).pvalue < alpha:
                        nonnormal += 1
                except Exception:
                    pass
        used = "spearman" if nonnormal else "pearson"
    rows, matrix = [], []
    for a, b in itertools.combinations(cols, 2):
        pair = data[[a, b]].dropna()
        if pair.shape[0] < 3:
            rows.append({"var1": a, "var2": b, "n": int(pair.shape[0]),
                         "r": None, "p": None, "strength": "样本不足"})
            continue
        if used == "pearson":
            r, p = stats.pearsonr(pair[a], pair[b])
        else:
            r, p = stats.spearmanr(pair[a], pair[b])
        strength = ("强" if abs(r) >= 0.7 else "中" if abs(r) >= 0.4 else "弱")
        rows.append({"var1": a, "var2": b, "n": int(pair.shape[0]),
                     "r": round(float(r), 4), "p": round(float(p), 6),
                     "stars": _stars(p),
                     "direction": "正" if r > 0 else "负",
                     "strength": f"{strength}{'正' if r > 0 else '负'}相关"})
    out = pd.DataFrame(rows)
    sig = out[(out["p"].notna()) & (out["p"] < alpha)]
    verdict = [f"采用 {'Pearson' if used == 'pearson' else 'Spearman'} 相关"
               f"（{'全部变量近似正态' if used == 'pearson' else '存在偏离正态的变量'}）。",
               (f"{len(sig)}/{len(out)} 对显著（α={alpha}）；"
                + "；".join(f"{r.var1}–{r.var2} r={r.r:.3f}" for r in sig.itertuples())
                if len(sig) else f"没有任意一对在 α={alpha} 下显著。")]
    stats_out = {"method": used,
                 "n_pairs": int(len(out)),
                 "max_abs_r": round(float(out["r"].abs().max()), 4)}
    return Result("correlation", [("correlations", out)], stats_out, verdict)


# ---------------------------------------------------------------------------
# 7. linear regression
# ---------------------------------------------------------------------------


def _design(df: pd.DataFrame, xs: list) -> tuple[pd.DataFrame, list]:
    """Build a design matrix; categoricals become dummies with a named base."""
    frames, names = [], []
    for x in xs:
        s = df[x]
        numeric = pd.to_numeric(s, errors="coerce")
        if numeric.notna().sum() >= 0.9 * s.notna().sum() and numeric.nunique() > 10:
            frames.append(numeric.rename(x))
            names.append(x)
        else:
            d = pd.get_dummies(s.astype("string"), prefix=x, drop_first=True, dtype=float)
            frames.append(d)
            names.extend(list(d.columns))
    X = pd.concat(frames, axis=1)
    return X, names


def linear_regression(df: pd.DataFrame, y: str, xs: list,
                      robust: str | None = "HC1", alpha: float = 0.05) -> Result:
    """OLS with standardised betas, VIF and residual diagnostics."""
    yv = pd.to_numeric(df[y], errors="coerce")
    X, names = _design(df, xs)
    data = pd.concat([yv.rename(y), X], axis=1).dropna()
    if data.shape[0] <= len(names) + 1:
        raise MethodError(f"样本 {data.shape[0]} 行不足以估计 {len(names) + 1} 个参数")
    import statsmodels.api as sm
    Y = data[y].astype(float)
    Xm = sm.add_constant(data[names].astype(float))
    model = sm.OLS(Y, Xm)
    fit = model.fit(cov_type=robust) if robust else model.fit()
    resid = fit.resid
    sw_p = float(stats.shapiro(resid).pvalue) if 3 <= resid.size <= 5000 else None
    bp = None
    try:
        from statsmodels.stats.diagnostic import het_breuschpagan
        bp = het_breuschpagan(resid, Xm)[1]
    except Exception:
        pass
    vif = {}
    try:
        from statsmodels.stats.outliers_influence import variance_inflation_factor
        for i, name in enumerate(Xm.columns):
            if name == "const":
                continue
            vif[name] = round(float(variance_inflation_factor(Xm.values, i)), 3)
    except Exception:
        pass
    params = pd.DataFrame({
        "term": fit.params.index,
        "beta": fit.params.values.round(4),
        "se": fit.bse.values.round(4),
        "t": fit.tvalues.values.round(3),
        "p": fit.pvalues.values.round(6),
    })
    params["stars"] = params["p"].map(_stars)
    try:
        rows = [cat for cat in df[xs].select_dtypes(exclude="number").columns]
    except Exception:
        rows = []
    sd_y = float(Y.std(ddof=1))
    betas = []
    for term in params["term"]:
        if term == "const":
            betas.append(None)
        elif term in data.columns and sd_y:
            betas.append(round(float(fit.params[term] * data[term].std(ddof=1) / sd_y), 4))
        else:
            betas.append(None)
    params["std_beta"] = betas
    params["vif"] = params["term"].map(lambda t: vif.get(t))
    fit_row = pd.DataFrame([{
        "n": int(fit.nobs), "r2": round(float(fit.rsquared), 4),
        "adj_r2": round(float(fit.rsquared_adj), 4),
        "F": round(float(fit.fvalue), 3), "F_p": float(fit.f_pvalue),
        "rmse": round(float(math.sqrt(fit.mse_resid)), 4),
        "durbin_watson": round(float(sm.stats.durbin_watson(resid)), 3),
        "breusch_pagan_p": round(float(bp), 6) if bp is not None else None,
        "resid_normality_p": round(sw_p, 6) if sw_p is not None else None,
    }])
    max_vif = max([v for v in vif.values()] or [0])
    verdict = [
        f"回归方程 R²={fit.rsquared:.3f}（调整后 {fit.rsquared_adj:.3f}），"
        f"F={fit.fvalue:.3f}，{_fmt_p(fit.f_pvalue)}；"
        f"{'模型可解释约 ' + format(fit.rsquared * 100, '.0f') + '% 的方差' if fit.rsquared_adj > 0.2 else '解释力偏弱（调整 R²<0.2），结论要谨慎'}。",
        f"共线性：最大 VIF={max_vif:.2f}"
        f"（{'<5，可接受' if max_vif < 5 else '≥5，存在共线性，见下方提示'}）。",
        (f"残差诊断：Shapiro {_fmt_p(sw_p)}；Breusch-Pagan {_fmt_p(bp)}。"
         if sw_p is not None else "残差诊断：样本量不足未做。"),
    ]
    notes = []
    if max_vif >= 5:
        notes.append("VIF≥5 的变量彼此高度重叠；删掉其中解释力较弱的一个，或改用主成分/因子得分。")
    if sw_p is not None and sw_p < alpha:
        notes.append("残差偏离正态：大样本下系数仍近似无偏，但 p 值需谨慎；可用 bootstrap。")
    return Result("linear_regression",
                  [("coefficients", params), ("model", fit_row)],
                  {"r2": float(fit.rsquared), "adj_r2": float(fit.rsquared_adj),
                   "F": float(fit.fvalue), "p": float(fit.f_pvalue),
                   "max_vif": float(max_vif)}, verdict, notes)


# ---------------------------------------------------------------------------
# 8. binary logistic regression
# ---------------------------------------------------------------------------


def logistic(df: pd.DataFrame, y: str, xs: list, alpha: float = 0.05) -> Result:
    """Binary logit with odds ratios, CI, McFadden R² and Hosmer-Lemeshow."""
    yv = pd.to_numeric(df[y], errors="coerce")
    levels = sorted(pd.unique(yv.dropna()))
    if len(levels) != 2:
        raise MethodError(f"{y} 有 {len(levels)} 个取值，二元 Logistic 需要二分类结果")
    if set(levels) - {0, 1}:
        raise MethodError(f"{y} 的取值是 {levels}，请先编码成 0/1（0=参照）")
    X, names = _design(df, xs)
    data = pd.concat([yv.rename(y), X], axis=1).dropna()
    if data.shape[0] <= len(names) + 1:
        raise MethodError(f"样本 {data.shape[0]} 行不足以估计 {len(names) + 1} 个参数")
    import statsmodels.api as sm
    Xm = sm.add_constant(data[names].astype(float))
    Y = data[y].astype(int)
    if Y.nunique() < 2:
        raise MethodError("结果变量只有一个类别，无法拟合")
    try:
        fit = sm.Logit(Y, Xm).fit(disp=False, maxiter=200)
    except Exception as exc:
        raise MethodError(f"Logit 拟合失败（可能是完全分离）：{exc}") from exc
    ci = fit.conf_int()
    with np.errstate(over="ignore", invalid="ignore"):
        or_v, or_lo, or_hi = (np.exp(fit.params.values), np.exp(ci[0].values),
                              np.exp(ci[1].values))
    out = pd.DataFrame({
        "term": fit.params.index,
        "B": fit.params.values.round(4),
        "se": fit.bse.values.round(4),
        "wald": (fit.params.values / fit.bse.values).round(3),
        "p": fit.pvalues.values.round(6),
        "OR": or_v.round(4),
        "OR_ci_low": or_lo.round(4),
        "OR_ci_high": or_hi.round(4),
    })
    out["stars"] = out["p"].map(_stars)
    ll0 = sm.Logit(Y, np.ones((len(Y), 1))).fit(disp=False).llf
    lr = 2 * (fit.llf - ll0)
    from scipy.stats import chi2 as chi2_dist
    lr_p = float(chi2_dist.sf(lr, len(names)))
    # Hosmer-Lemeshow on deciles of predicted probability
    pred = fit.predict(Xm)
    hl_p = None
    try:
        dfh = pd.DataFrame({"y": Y.values, "p": pred.values})
        dfh["bin"] = pd.qcut(dfh["p"], 10, duplicates="drop")
        grouped = dfh.groupby("bin", observed=True).agg(obs=("y", "sum"), n=("y", "size"),
                                                        exp=("p", "sum"))
        hl = float((((grouped["obs"] - grouped["exp"]) ** 2) /
                    (grouped["exp"] * (1 - grouped["exp"] / grouped["n"]))).sum())
        hl_p = float(chi2_dist.sf(hl, max(1, len(grouped) - 2)))
    except Exception:
        pass
    pseudo = 1 - fit.llf / ll0 if ll0 else float("nan")
    fit_row = pd.DataFrame([{"n": int(fit.nobs), "events": int(Y.sum()),
                             "mcfadden_r2": round(float(pseudo), 4),
                             "llr_chi2": round(float(lr), 3), "llr_dof": len(names),
                             "llr_p": round(float(lr_p), 6),
                             "hosmer_lemeshow_p": round(hl_p, 6) if hl_p is not None else None,
                             "aic": round(float(fit.aic), 3)}])
    sig = out[(out["p"] < alpha) & (out["term"] != "const")]
    separated = bool(np.isinf(or_hi).any() or np.isinf(or_lo).any()
                     or (np.abs(fit.params.values) > 12).any())
    notes = []
    if separated:
        notes.append("存在准完全分离：至少一个系数或它的置信区间发散，" 
                     "OR 与 CI 的数值不可解释（inf 表示 MLE 不存在）；" 
                     "应合并稀疏类别或用 Firth 惩罚似然，而不是引用这个 OR。")
    verdict = [
        f"模型 χ²({len(names)})={lr:.3f}，{_fmt_p(lr_p)}；McFadden R²={pseudo:.3f}，"
        f"AIC={fit.aic:.1f}，n={int(fit.nobs)}（事件 {int(Y.sum())}）。",
        (f"{len(sig)} 个变量显著；OR 大于 1 表示该变量升高时发生比增加。" if len(sig)
         else "没有变量在 α 水平显著。"),
        (f"Hosmer-Lemeshow {_fmt_p(hl_p)}（p>0.05 表示校准可接受）。"
         if hl_p is not None else "Hosmer-Lemeshow 未能计算。"),
    ]
    if fit.nobs / max(1, len(names)) < 10:
        notes.append(f"每参数事件数 {Y.sum() / max(1, len(names)):.1f} < 10，"
                     f"系数可能不稳定（EPV 规则）。")
    big = out[(out["OR_ci_high"] > 50) | (out["OR"] < 0.02)]
    if not big.empty:
        notes.append("有 OR 极端（<0.02 或 CI 上界>50）：常见原因是该类别的样本极少，"
                     "或存在准完全分离；请检查交叉表。")
    return Result("logistic", [("coefficients", out), ("model", fit_row)],
                  {"mcfadden_r2": float(pseudo), "llr_p": float(lr_p),
                   "n": int(fit.nobs)}, verdict, notes)


# ---------------------------------------------------------------------------
# 9. PCA / EFA / reliability / validity
# ---------------------------------------------------------------------------


def _corr_matrix(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    data = df[cols].apply(pd.to_numeric, errors="coerce")
    return data.corr()


def kmo_bartlett(df: pd.DataFrame, cols: list) -> dict:
    """Kaiser-Meyer-Olkin and Bartlett's test of sphericity."""
    R = _corr_matrix(df, cols).values
    p = R.shape[0]
    if p < 2:
        raise MethodError("至少需要两个变量")
    det = np.linalg.det(R)
    if det <= 0:
        raise MethodError("相关矩阵奇异（变量完全共线），无法做因子分析")
    n = int(df[cols].dropna().shape[0])
    chi2 = -(n - 1 - (2 * p + 5) / 6) * math.log(det)
    dof = p * (p - 1) // 2
    bartlett_p = float(stats.chi2.sf(chi2, dof))
    Rinv = np.linalg.inv(R)
    d = np.sqrt(np.diag(Rinv))
    partial = -Rinv / np.outer(d, d)
    np.fill_diagonal(partial, 0)
    R0 = R.copy()
    np.fill_diagonal(R0, 0)
    num = float((R0 ** 2).sum())
    den = num + float((partial ** 2).sum())
    kmo = num / den if den else float("nan")
    return {"kmo": round(kmo, 4), "bartlett_chi2": round(float(chi2), 3),
            "bartlett_dof": int(dof), "bartlett_p": round(bartlett_p, 6), "n": n}


def _varimax(loadings: np.ndarray, max_iter: int = 100, tol: float = 1e-6) -> np.ndarray:
    """Kaiser's varimax rotation (the one SPSS applies by default)."""
    L = loadings.copy()
    p, k = L.shape
    if k < 2:
        return L
    h = np.sqrt((L ** 2).sum(axis=1, keepdims=True))
    L = L / np.where(h == 0, 1, h)
    R = np.eye(k)
    d = 0
    for _ in range(max_iter):
        Lam = L @ R
        u, s, vt = np.linalg.svd(L.T @ (Lam ** 3 - Lam @ np.diag((Lam ** 2).sum(axis=0)) / p))
        R = u @ vt
        d_new = s.sum()
        if d_new - d < tol:
            break
        d = d_new
    return L @ R * h


def efa(df: pd.DataFrame, cols: list, n_factors: int | None = None,
        rotate: str = "varimax", alpha: float = 0.05) -> Result:
    """Exploratory factor analysis by principal axis on the correlation matrix."""
    cols = [c for c in cols if c in df.columns]
    if len(cols) < 3:
        raise MethodError("因子分析至少需要三个变量")
    R = _corr_matrix(df, cols)
    eigval, eigvec = np.linalg.eigh(R.values)
    order = np.argsort(eigval)[::-1]
    eigval, eigvec = eigval[order], eigvec[:, order]
    kaiser = int((eigval > 1).sum())
    k = n_factors or max(1, kaiser)
    k = min(k, len(cols))
    loadings = eigvec[:, :k] * np.sqrt(np.clip(eigval[:k], 0, None))
    if rotate == "varimax":
        loadings = _varimax(loadings)
    communality = (loadings ** 2).sum(axis=1)
    L = pd.DataFrame(loadings, index=cols,
                     columns=[f"F{i + 1}" for i in range(k)]).round(3)
    L["communality"] = communality.round(3)
    var = pd.DataFrame({"factor": [f"F{i + 1}" for i in range(k)],
                        "eigenvalue": eigval[:k].round(3),
                        "variance_pct": (eigval[:k] / len(cols) * 100).round(2),
                        "cumulative_pct": (np.cumsum(eigval[:k]) / len(cols) * 100).round(2)})
    kb = kmo_bartlett(df, cols)
    verdict = [
        f"KMO={kb['kmo']:.3f}（{'可接受' if kb['kmo'] >= 0.6 else '偏低，不适合做因子分析'}）；"
        f"Bartlett χ²({kb['bartlett_dof']})={kb['bartlett_chi2']:.1f}，"
        f"{_fmt_p(kb['bartlett_p'])}。",
        f"特征值>1 的因子 {kaiser} 个，提取 {k} 个，累计解释 "
        f"{var['cumulative_pct'].iloc[-1]:.1f}% 的方差。",
    ]
    notes = []
    weak = L[(L.drop(columns=["communality"]).abs().max(axis=1) < 0.4)]
    if not weak.empty:
        notes.append("共同度或载荷偏低（最大载荷<0.4）的变量：" +
                     "、".join(weak.index.tolist()) + "；考虑删除或单独分析。")
    return Result("efa", [("loadings", L.reset_index().rename(columns={"index": "variable"})),
                          ("variance", var), ("kmo_bartlett", pd.DataFrame([kb]))],
                  {"kmo": kb["kmo"], "n_factors": k, **kb}, verdict, notes)


def pca(df: pd.DataFrame, cols: list, n_components: int = 2,
        alpha: float = 0.05) -> Result:
    """Principal components on standardised variables (SVD, no sklearn)."""
    cols = [c for c in cols if c in df.columns]
    data = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if data.shape[0] < len(cols) + 1:
        raise MethodError("样本量不足")
    Z = (data - data.mean()) / data.std(ddof=1)
    U, S, Vt = np.linalg.svd(Z.values, full_matrices=False)
    var = (S ** 2) / (data.shape[0] - 1)
    share = var / var.sum()
    k = min(n_components, len(cols))
    scores = U[:, :k] * S[:k]
    loadings = pd.DataFrame(Vt[:k].T, index=cols,
                            columns=[f"PC{i + 1}" for i in range(k)]).round(3)
    var_tab = pd.DataFrame({"component": [f"PC{i + 1}" for i in range(len(cols))],
                            "eigenvalue": var.round(3),
                            "variance_pct": (share * 100).round(2),
                            "cumulative_pct": (np.cumsum(share) * 100).round(2)})
    sc = pd.DataFrame(scores, columns=[f"PC{i + 1}" for i in range(k)])
    verdict = [f"前 {k} 个主成分解释 {share[:k].sum() * 100:.1f}% 的方差"
               f"（PC1 {share[0] * 100:.1f}%）；"
               f"特征值>1 的成分 {int((var > 1).sum())} 个。"]
    return Result("pca", [("loadings", loadings.reset_index().rename(columns={"index": "variable"})),
                          ("variance", var_tab), ("scores", sc)],
                  {"pc1_pct": float(share[0] * 100), "k": k}, verdict)


def cronbach(df: pd.DataFrame, cols: list, alpha: float = 0.05) -> Result:
    """Cronbach's alpha with corrected item-total correlations."""
    cols = [c for c in cols if c in df.columns]
    data = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    k = len(cols)
    if k < 2 or data.shape[0] < 3:
        raise MethodError("信度分析至少需要两个题项与三个样本")
    item_var = data.var(ddof=1)
    total_var = data.sum(axis=1).var(ddof=1)
    a = (k / (k - 1)) * (1 - item_var.sum() / total_var) if total_var else float("nan")
    rows = []
    total = data.sum(axis=1)
    for c in cols:
        rest = total - data[c]
        r = float(np.corrcoef(data[c], rest)[0, 1]) if data[c].std() and rest.std() else float("nan")
        rest_var = rest.var(ddof=1)
        a_del = ((k - 1) / (k - 2)) * (1 - (item_var.sum() - item_var[c]) / rest_var) \
            if k > 2 and rest_var else float("nan")
        rows.append({"item": c, "mean": round(float(data[c].mean()), 3),
                     "sd": round(float(data[c].std(ddof=1)), 3),
                     "item_total_r": round(r, 3), "alpha_if_deleted": round(a_del, 3)})
    tab = pd.DataFrame(rows)
    level = ("优秀" if a >= 0.9 else "良好" if a >= 0.8 else "可接受" if a >= 0.7
             else "偏低" if a >= 0.6 else "不可接受")
    verdict = [f"Cronbach's α={a:.3f}（{k} 个题项，n={data.shape[0]}），{level}。",
               f"若删除某题能明显提高 α，说明该题与其他题不同质（见 alpha_if_deleted 列）。"]
    notes = []
    weak = tab[tab["item_total_r"] < 0.3]
    if not weak.empty:
        notes.append("项目-总体相关<0.3 的题项：" + "、".join(weak["item"].tolist()) +
                     "；它们可能测量的是另一个构念。")
    if a > 0.95:
        notes.append("α>0.95 常见于题目高度重复（冗余），不是越好越好。")
    return Result("cronbach", [("reliability", tab),
                               ("summary", pd.DataFrame([{"k": k, "n": int(data.shape[0]),
                                                          "cronbach_alpha": round(float(a), 4)}]))],
                  {"alpha": float(a), "k": k}, verdict, notes)


def validity(df: pd.DataFrame, cols: list, n_factors: int | None = None,
             alpha: float = 0.05) -> Result:
    """Structural validity: KMO/Bartlett + EFA loadings, with the caveats named."""
    res = efa(df, cols, n_factors=n_factors, alpha=alpha)
    kb = res.stats
    res.method = "validity"
    res.verdict.insert(0, "效度分三层：内容效度靠专家判断（脚本不能替代），"
                          "结构效度看下面的因子分析，效标效度需要外部金标准。")
    res.notes.append("结构效度只说明题项按预期聚成维度，不等于测量到了你想测的东西；"
                     "内容效度请写专家评审与题项来源。")
    return res


# ---------------------------------------------------------------------------
# 10. clustering
# ---------------------------------------------------------------------------


def _kmeans(X: np.ndarray, k: int, n_init: int = 20, max_iter: int = 300,
            seed: int = 20260101) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    best = None
    n = X.shape[0]
    for _ in range(n_init):
        # k-means++ initialisation
        centers = [X[rng.integers(n)]]
        for _ in range(1, k):
            d2 = np.min(((X[:, None, :] - np.array(centers)[None, :, :]) ** 2).sum(-1), axis=1)
            probs = d2 / d2.sum() if d2.sum() else np.full(n, 1 / n)
            centers.append(X[rng.choice(n, p=probs)])
        C = np.array(centers)
        labels = np.zeros(n, dtype=int)
        for _ in range(max_iter):
            d = ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1)
            new = d.argmin(axis=1)
            if np.array_equal(new, labels):
                break
            labels = new
            for j in range(k):
                if (labels == j).any():
                    C[j] = X[labels == j].mean(axis=0)
        inertia = float(((X - C[labels]) ** 2).sum())
        if best is None or inertia < best[0]:
            best = (inertia, labels.copy(), C.copy())
    return best[1], best[2]


def _silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    n = len(labels)
    uniq = np.unique(labels)
    if len(uniq) < 2 or n > 5000:
        return float("nan")
    d = np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(-1))
    s = []
    for i in range(n):
        same = labels == labels[i]
        if same.sum() <= 1:
            s.append(0.0)
            continue
        a = d[i, same].sum() / (same.sum() - 1)
        b = min(d[i, labels == u].mean() for u in uniq if u != labels[i])
        s.append((b - a) / max(a, b) if max(a, b) else 0.0)
    return float(np.mean(s))


def kmeans_analysis(df: pd.DataFrame, cols: list, k: int = 3,
                    seed: int = 20260101) -> Result:
    """K-means with k-means++ and silhouette; no sklearn required."""
    data = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if data.shape[0] <= k:
        raise MethodError("样本量应大于聚类数")
    Z = ((data - data.mean()) / data.std(ddof=1)).values
    labels, centers = _kmeans(Z, k, seed=seed)
    sil = _silhouette(Z, labels)
    sizes = pd.Series(labels).value_counts().sort_index()
    prof = pd.DataFrame(centers, columns=cols)
    prof.insert(0, "cluster", [f"C{i + 1}" for i in range(k)])
    prof.insert(1, "n", [int(sizes.get(i, 0)) for i in range(k)])
    verdict = [f"K={k}：轮廓系数 {sil:.3f}"
               f"（{'结构清晰' if sil >= 0.5 else '结构一般' if sil >= 0.25 else '结构弱，K 可能不合适'}）。",
               "聚类结果对标准化敏感；本结果基于 z 分数。"]
    return Result("kmeans", [("profile", prof.round(3)),
                             ("summary", pd.DataFrame([{"k": k, "n": int(len(data)),
                                                        "silhouette": round(sil, 4)}]))],
                  {"k": k, "silhouette": sil}, verdict)


def hclust(df: pd.DataFrame, cols: list, k: int = 3, method: str = "ward") -> Result:
    """Agglomerative clustering (Ward) with a cophenetic correlation."""
    data = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if data.shape[0] < k + 1:
        raise MethodError("样本量不足")
    from scipy.cluster.hierarchy import linkage, fcluster, cophenet
    from scipy.spatial.distance import pdist
    Z = ((data - data.mean()) / data.std(ddof=1)).values
    lm = linkage(Z, method=method)
    coph, _ = cophenet(lm, pdist(Z))
    labels = fcluster(lm, k, criterion="maxclust")
    sizes = pd.Series(labels).value_counts().sort_index()
    verdict = [f"层次聚类（{method}）K={k}：cophenetic r={coph:.3f}"
               f"（{'合并结构可信' if coph >= 0.7 else '结构较松，谨慎解释'}）。"]
    return Result("hclust", [("sizes", pd.DataFrame({"cluster": [f"C{i}" for i in sizes.index],
                                                    "n": sizes.values}))],
                  {"k": k, "cophenetic": float(coph)}, verdict)


# ---------------------------------------------------------------------------
# 11. discriminant analysis
# ---------------------------------------------------------------------------


def lda(df: pd.DataFrame, y: str, xs: list, alpha: float = 0.05) -> Result:
    """Fisher linear discriminant analysis (two or more groups)."""
    data = pd.concat([df[[y]], df[xs].apply(pd.to_numeric, errors="coerce")], axis=1).dropna()
    levels = [lv for lv in pd.unique(data[y]) if pd.notna(lv)]
    if len(levels) < 2:
        raise MethodError("分组变量至少需要 2 个类别")
    X = data[xs].values.astype(float)
    yv = data[y].values
    overall = X.mean(axis=0)
    Sw = np.zeros((len(xs), len(xs)))
    Sb = np.zeros_like(Sw)
    for lv in levels:
        Xi = X[yv == lv]
        if len(Xi) < 2:
            raise MethodError(f"组 {lv} 只有 {len(Xi)} 个观测")
        mu = Xi.mean(axis=0)
        Sw += (Xi - mu).T @ (Xi - mu)
        Sb += len(Xi) * np.outer(mu - overall, mu - overall)
    Sw /= max(1, len(X) - len(levels))
    Sb /= max(1, len(levels) - 1)
    try:
        vals, vecs = np.linalg.eig(np.linalg.solve(Sw, Sb))
    except np.linalg.LinAlgError:
        raise MethodError("组内协方差矩阵奇异（变量共线或某组样本过少）")
    order = np.argsort(vals.real)[::-1]
    vals, vecs = vals.real[order], vecs.real[:, order]
    keep = vals > 1e-9
    vecs, vals = vecs[:, keep], vals[keep]
    if vecs.shape[1] == 0:
        raise MethodError("没有可用的判别函数（组间差异被共线性吃掉）")
    scores = X @ vecs[:, :1]
    # resubstitution accuracy as a *ceiling*, not a validation estimate
    pred = np.array([levels[np.argmin([abs(scores[i] - np.mean(scores[yv == lv]))
                                       for lv in levels])] for i in range(len(X))])
    acc = float((pred == yv).mean())
    coef = pd.DataFrame({"variable": xs, "LD1": np.round(vecs[:, 0], 3)})
    coef["standardised"] = np.round(vecs[:, 0] * X.std(axis=0), 3)
    wilks = float(np.prod(1 / (1 + vals)))
    verdict = [f"提取 {vecs.shape[1]} 个判别函数，第 1 个解释 "
               f"{vals[0] / vals.sum() * 100:.1f}% 的组间差异；Wilks' Λ={wilks:.3f}。",
               f"回代准确率 {acc * 100:.1f}%（这是上限，不是泛化精度；"
               f"正式报告请做交叉验证或留一法）。"]
    return Result("lda", [("coefficients", coef),
                          ("summary", pd.DataFrame([{"functions": int(vecs.shape[1]),
                                                     "wilks_lambda": round(wilks, 4),
                                                     "resubstitution_accuracy": round(acc, 4)}]))],
                  {"wilks": wilks, "accuracy": acc}, verdict)


# ---------------------------------------------------------------------------
# 12. time series
# ---------------------------------------------------------------------------


def time_series(df: pd.DataFrame, time: str, value: str,
                max_p: int = 2, alpha: float = 0.05) -> Result:
    """ARIMA(p,d,0) chosen by AIC, with a Ljung-Box residual check."""
    data = df[[time, value]].copy()
    data[value] = pd.to_numeric(data[value], errors="coerce")
    data = data.dropna().sort_values(time)
    if data.shape[0] < 8:
        raise MethodError("时间序列至少需要 8 个时点")
    y = data[value].astype(float).values
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.stats.diagnostic import acorr_ljungbox
    best = None
    for p in range(max_p + 1):
        for d in (0, 1):
            if len(y) <= p + d + 2:
                continue
            try:
                fit = ARIMA(y, order=(p, d, 0)).fit()
            except Exception:
                continue
            if best is None or fit.aic < best[0]:
                best = (fit.aic, p, d, fit)
    if best is None:
        raise MethodError("ARIMA 未能收敛")
    aic, p, d, fit = best
    lb = acorr_ljungbox(fit.resid, lags=[max(2, min(10, len(y) // 2))], return_df=True)
    lb_p = float(lb["lb_pvalue"].iloc[0])
    verdict = [f"按 AIC 选择 ARIMA({p},{d},0)：AIC={aic:.2f}，"
               f"残差 Ljung-Box {_fmt_p(lb_p)}"
               f"（{'残差近似白噪声' if lb_p >= alpha else '残差仍有自相关，阶数不足'}）。"]
    coef = np.asarray(fit.params, dtype=float)
    se = np.asarray(fit.bse, dtype=float)
    # ARIMA was fitted on a bare ndarray, so params carries no index; its
    # param_names still tells the reader which term is which (incl. sigma2).
    names = list(getattr(fit, "param_names", [])) or [f"term{i}" for i in range(coef.size)]
    params = pd.DataFrame({"term": names[:coef.size], "coef": np.round(coef, 4),
                           "se": np.round(se, 4)})
    # ARIMA's first d fitted values are placeholders (0 after differencing),
    # so blanking them keeps the plot from claiming a fit at the series start.
    fit_vals = np.asarray(fit.fittedvalues, dtype=float)
    if d:
        fit_vals = fit_vals.copy()
        fit_vals[:d] = np.nan
    fitted = pd.DataFrame({"time": data[time].values,
                           "observed": np.round(y, 6),
                           "fitted": np.round(fit_vals, 6)})
    return Result("time_series", [("params", params), ("fitted", fitted),
                                  ("fit", pd.DataFrame([{"p": p, "d": d, "aic": round(aic, 3),
                                                         "ljungbox_p": round(lb_p, 6)}]))],
                  {"aic": float(aic), "p": p, "d": d}, verdict)


# ---------------------------------------------------------------------------
# 13. mediation
# ---------------------------------------------------------------------------


def mediation(df: pd.DataFrame, x: str, m: str, y: str, n_boot: int = 2000,
              seed: int = 20260101, alpha: float = 0.05) -> Result:
    """Baron-Kenny paths plus Sobel and a percentile bootstrap CI."""
    data = df[[x, m, y]].apply(pd.to_numeric, errors="coerce").dropna()
    if data.shape[0] < 20:
        raise MethodError("中介效应建议 n≥20（bootstrap 需要更多）")
    import statsmodels.api as sm
    X1 = sm.add_constant(data[[x]].values)
    a = sm.OLS(data[m].values, X1).fit().params[1]
    X2 = sm.add_constant(data[[x, m]].values)
    fit_y = sm.OLS(data[y].values, X2).fit()
    b, c_prime = fit_y.params[2], fit_y.params[1]
    c = sm.OLS(data[y].values, X1).fit().params[1]
    indirect = a * b
    se_a = sm.OLS(data[m].values, X1).fit().bse[1]
    se_b = fit_y.bse[2]
    sobel_se = math.sqrt(b ** 2 * se_a ** 2 + a ** 2 * se_b ** 2)
    sobel_z = indirect / sobel_se if sobel_se else float("nan")
    sobel_p = float(2 * (1 - stats.norm.cdf(abs(sobel_z))))
    rng = np.random.default_rng(seed)
    boots = []
    n = len(data)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        d = data.iloc[idx]
        try:
            aa = sm.OLS(d[m].values, sm.add_constant(d[[x]].values)).fit().params[1]
            bb = sm.OLS(d[y].values, sm.add_constant(d[[x, m]].values)).fit().params[2]
            boots.append(aa * bb)
        except Exception:
            continue
    lo, hi = (np.percentile(boots, [2.5, 97.5]) if boots else (np.nan, np.nan))
    sig = (lo > 0) or (hi < 0)
    share = indirect / c if c else float("nan")
    rows = pd.DataFrame([
        {"path": f"{x}→{m} (a)", "coef": round(float(a), 4), "se": round(float(se_a), 4)},
        {"path": f"{m}→{y} (b)", "coef": round(float(b), 4), "se": round(float(se_b), 4)},
        {"path": f"{x}→{y} 总效应 (c)", "coef": round(float(c), 4), "se": None},
        {"path": f"{x}→{y} 直接效应 (c′)", "coef": round(float(c_prime), 4),
         "se": round(float(fit_y.bse[1]), 4)},
    ])
    verdict = [
        f"间接效应 a×b={indirect:.4f}；bootstrap 95%CI [{lo:.4f}, {hi:.4f}]"
        f"{'不含 0，中介成立' if sig else '含 0，中介不成立'}。",
        f"Sobel z={sobel_z:.3f}，{_fmt_p(sobel_p)}；中介占总效应 {share * 100:.1f}%"
        f"（{share:.3f}）。",
    ]
    notes = ["这是横断面数据的中介检验：统计上成立不等于因果上成立，"
             "需要时间顺序或实验设计支持。"]
    return Result("mediation", [("paths", rows),
                                ("effect", pd.DataFrame([{"indirect": round(float(indirect), 4),
                                                          "boot_lo": round(float(lo), 4),
                                                          "boot_hi": round(float(hi), 4),
                                                          "sobel_z": round(float(sobel_z), 3),
                                                          "sobel_p": round(sobel_p, 6),
                                                          "proportion": round(float(share), 4)}]))],
                  {"indirect": float(indirect), "boot_lo": float(lo), "boot_hi": float(hi)},
                  verdict, notes)


# ---------------------------------------------------------------------------
# 14. Kano model
# ---------------------------------------------------------------------------


KANO_RULES = {
    # (functional, dysfunctional) -> category, using the classic 5-point table
    "A": [(5, 1), (5, 2), (4, 1), (4, 2)],
    "O": [(5, 3), (5, 4), (5, 5), (4, 3), (4, 4), (4, 5), (3, 4), (3, 5)],
    "M": [(1, 5), (2, 5), (1, 4), (2, 4), (1, 3), (2, 3)],
    "I": [(3, 3), (3, 1), (3, 2), (1, 1), (1, 2), (2, 1), (2, 2)],
    "R": [(1, 1), (5, 1), (1, 5), (5, 5)],
}


def _kano_category(f: int, d: int) -> str:
    if f >= 4 and d <= 2:
        return "A"          # attractive
    if f >= 4 and d >= 4:
        return "O"          # one-dimensional
    if f <= 2 and d >= 4:
        return "M"          # must-be
    if f <= 2 and d <= 2:
        return "I"          # indifferent
    return "Q" if (f == 3 and d == 3) else "R"


def kano(df: pd.DataFrame, pairs: dict) -> Result:
    """Classify features from functional/dysfunctional ratings.

    ``pairs`` maps a feature name to ``(functional_column, dysfunctional_column)``;
    both are 1–5 Likert items. Better/worse coefficients follow Matzler & Hinterhuber.
    """
    if not pairs:
        raise MethodError("Kano 需要 {功能名: (功能列, 反功能列)} 的配对")
    rows = []
    for feature, (fc, dc) in pairs.items():
        sub = df[[fc, dc]].apply(pd.to_numeric, errors="coerce").dropna()
        if sub.empty:
            continue
        counts = {"A": 0, "O": 0, "M": 0, "I": 0, "R": 0}
        for f, d in zip(sub[fc].astype(int), sub[dc].astype(int)):
            cat = _kano_category(f, d)
            counts[cat if cat in counts else "I"] += 1
        total = sum(counts.values())
        better = (counts["A"] + counts["O"]) / total if total else float("nan")
        worse = -(counts["O"] + counts["M"]) / total if total else float("nan")
        top = max(counts, key=counts.get)
        rows.append({"feature": feature, "n": total, **counts,
                     "better": round(better, 3), "worse": round(worse, 3),
                     "category": top,
                     "label": {"A": "魅力型", "O": "期望型", "M": "必备型",
                               "I": "无差异", "R": "反向"}[top]})
    out = pd.DataFrame(rows)
    if out.empty:
        raise MethodError("没有任何可用配对")
    verdict = [f"{len(out)} 个需求的类型："
               + "；".join(f"{r.feature}={r.label}" for r in out.itertuples()) + "。",
               "better 越接近 1 表示满足该需求带来的满意度提升越大；"
               "worse 越接近 -1 表示不满足时的不满意越强。"]
    return Result("kano", [("kano", out)], {"features": len(out)}, verdict)


# ---------------------------------------------------------------------------
# 15. SEM (explicitly not implemented natively)
# ---------------------------------------------------------------------------


def sem(**_: object) -> Result:
    """Structural equation modelling is NOT implemented here.

    Fitting SEM needs a dedicated engine (semopy, lavaan, Mplus, AMOS). Producing
    a number without one would be a lie dressed as a table.
    """
    raise MethodError(
        "本技能的统计内核不实现结构方程模型（SEM）：它需要专门引擎"
        "（Python 可用 semopy，R 用 lavaan，或 Mplus/AMOS）。"
        "可选替代：① 安装 semopy 后用它的 CLI；② 用路径回归（多个 OLS/Logit）+ "
        "中介效应检验近似；③ 若只是验证测量结构，用 --method validity（EFA）。"
    )