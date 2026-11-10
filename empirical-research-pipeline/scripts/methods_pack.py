#!/usr/bin/env python3
"""Run the sixteen analysis methods, with their preconditions stated out loud.

The catalogue below is the one a reader of the source material would expect:

    1 描述性统计        2 主成分分析       3 相关性分析      4 方差分析
    5 卡方检验          6 结构方程模型     7 判别分析        8 时间序列分析
    9 因子分析         10 聚类分析        11 回归分析       12 T 检验
   13 中介效应         14 卡诺模型        15 信度分析       16 效度分析

plus the non-parametric family the same notes introduce as the fallback for
T/ANOVA (Mann-Whitney, Wilcoxon, Kruskal-Wallis).

What this script will not do is pretend. Every method:

* reads named slots from a config (it never guesses which column is the
  outcome from a substring);
* checks its preconditions first (two groups for a t test, a 0/1 outcome for
  logistic, n > parameters, expected counts for chi-square, KMO for EFA) and
  reports ``skipped: <reason>`` with the alternative to use instead;
* reports an effect size next to every p value;
* refuses SEM outright, because no engine is installed and a fabricated
  structural model is worse than an honest "not available".

Usage
-----
    python scripts/methods_pack.py --data data.csv --config methods.json \\
        --out output/methods --methods all
    python scripts/methods_pack.py --list
    python scripts/methods_pack.py --data d.csv --config c.json --out o \\
        --only m04 --force

Config (every slot optional; a method whose slots are missing is skipped):

    {
      "outcome":      {"col": "restore_any", "type": "binary", "positive": 1},
      "continuous":   {"col": "restore_amount"},
      "predictors":   ["gongyi", "charge_group", "trial_level"],
      "group":        "charge_group",
      "paired":       ["before_col", "after_col"],
      "time":         {"col": "year", "value": "restore_amount"},
      "items":        {"scale": ["q1", "q2", "q3", "q4"]},
      "path":         {"x": "x_col", "m": "m_col", "y": "y_col"},
      "cluster_vars": ["v1", "v2", "v3"],
      "discriminant": {"group": "g", "vars": ["v1", "v2"]},
      "kano":         {"feature_a": ["functional_col", "dysfunctional_col"]},
      "n_factors":    2,
      "cluster_k":    3
    }
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import traceback
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import methods_lib as ML  # noqa: E402
import pubfig as PF  # noqa: E402

SCRIPT_VERSION = "1.0.0"
WIDTH_CM = 15.0

#: id, number, names, the config slots it needs, and what it falls back to.
CATALOG = [
    {"id": "m01", "nr": 1, "cn": "描述性统计", "en": "Descriptive statistics",
     "family": "describe", "slots": [], "fallback": "",
     "when": "任何数据集的第一步；连续变量看均值/中位数与离散度，分类变量看频数与构成比"},
    {"id": "m12", "nr": 12, "cn": "T 检验", "en": "t test",
     "family": "compare", "slots": ["group", "continuous"], "fallback": "m17 非参数检验",
     "when": "两组均值比较；独立样本看 Levene，配对样本先看配对相关"},
    {"id": "m04", "nr": 4, "cn": "方差分析", "en": "ANOVA",
     "family": "compare", "slots": ["group", "continuous"], "fallback": "m17 非参数检验",
     "when": "三组及以上均值比较；显著后再做事后比较（Bonferroni/Tukey）"},
    {"id": "m05", "nr": 5, "cn": "卡方检验", "en": "Chi-square test",
     "family": "assoc", "slots": ["group"], "fallback": "Fisher 精确检验（脚本自动）",
     "when": "两个分类变量的列联表；期望频数<5 时要看精确检验"},
    {"id": "m03", "nr": 3, "cn": "相关性分析", "en": "Correlation",
     "family": "assoc", "slots": [], "fallback": "Spearman（脚本按正态性自动切换）",
     "when": "两变量关联强度；|r|≥0.7 才算强，且相关不等于因果"},
    {"id": "m11", "nr": 11, "cn": "回归分析", "en": "Linear regression",
     "family": "model", "slots": ["continuous", "predictors"], "fallback": "",
     "when": "连续因变量与一个或多个自变量的关系；必须看 VIF 与残差"},
    {"id": "m10", "nr": 10, "cn": "聚类分析", "en": "Cluster analysis",
     "family": "reduce", "slots": ["cluster_vars"], "fallback": "判别分析（m07）",
     "when": "按相似性把观测分组；先标准化，再用轮廓系数选 K，聚类结果不是既定分类"},
    {"id": "m06", "nr": 6, "cn": "结构方程模型", "en": "SEM",
     "family": "model", "slots": [], "fallback": "路径回归 + 中介检验，或安装 semopy",
     "when": "潜变量与多条因果路径；需要专门引擎，本脚本不代算"},
    {"id": "m02", "nr": 2, "cn": "主成分分析", "en": "PCA",
     "family": "reduce", "slots": ["cluster_vars"], "fallback": "因子分析（m09）",
     "when": "变量多且相关强，用少数成分概括；看特征值与累计方差"},
    {"id": "m09", "nr": 9, "cn": "因子分析", "en": "Factor analysis",
     "family": "reduce", "slots": ["items"], "fallback": "主成分（m02）",
     "when": "寻找潜在结构；先看 KMO 与 Bartlett，再看载荷与共同度"},
    {"id": "m15", "nr": 15, "cn": "信度分析", "en": "Reliability",
     "family": "measure", "slots": ["items"], "fallback": "",
     "when": "同一构念的多个题项是否一致；α≥0.7 可接受，>0.95 反而可能冗余"},
    {"id": "m16", "nr": 16, "cn": "效度分析", "en": "Validity",
     "family": "measure", "slots": ["items"], "fallback": "内容效度靠专家评审（脚本不替代）",
     "when": "题项是否测到了想测的东西；结构效度用 EFA，内容/效标效度需外部证据"},
    {"id": "m14", "nr": 14, "cn": "卡诺模型", "en": "Kano model",
     "family": "classify", "slots": ["kano"], "fallback": "",
     "when": "功能/反功能配对评分，把需求分成魅力/期望/必备/无差异"},
    {"id": "m07", "nr": 7, "cn": "判别分析", "en": "Discriminant analysis",
     "family": "classify", "slots": ["discriminant"], "fallback": "Logistic 回归（m18）",
     "when": "用一组连续变量区分已知类别；回代准确率不是泛化精度"},
    {"id": "m08", "nr": 8, "cn": "时间序列分析", "en": "Time series",
     "family": "classify", "slots": ["time"], "fallback": "",
     "when": "按时间顺序记录的数据；ARIMA 后用 Ljung-Box 查残差"},
    {"id": "m13", "nr": 13, "cn": "中介效应", "en": "Mediation",
     "family": "model", "slots": ["path"], "fallback": "",
     "when": "X 通过 M 影响 Y；报告 bootstrap CI，且不要用横断面数据讲因果"},
    {"id": "m17", "nr": 17, "cn": "非参数检验", "en": "Non-parametric tests",
     "family": "compare", "slots": ["group"], "fallback": "",
     "when": "T/ANOVA 的替代：Mann-Whitney、Wilcoxon、Kruskal-Wallis"},
    {"id": "m18", "nr": 18, "cn": "二元 Logistic 回归", "en": "Binary logistic",
     "family": "model", "slots": ["outcome", "predictors"], "fallback": "",
     "when": "0/1 因变量的回归（教材单列一节，故编号放在 16 之后）；报告 OR 与 95%CI"},
]

BY_ID = {m["id"]: m for m in CATALOG}


class Skip(Exception):
    """Raised when a method cannot run on this data; carries the reason."""


@dataclass
class Run:
    spec: dict
    result: ML.Result | None = None
    status: str = "ok"
    reason: str = ""
    figure: str = ""
    table_files: list | None = None


def _get(cfg: dict, *keys):
    for k in keys:
        if k in cfg and cfg[k] not in (None, "", [], {}):
            return cfg[k]
    return None


def _col(cfg: dict, slot: str, col_key: str = "col"):
    raw = cfg.get(slot)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict) and raw.get(col_key):
        return raw[col_key]
    return None


def _need(cond: bool, reason: str, alt: str = "") -> None:
    if not cond:
        raise Skip(reason + (f"；建议改用 {alt}" if alt else ""))


def _need_cols(df, *cols) -> None:
    """A config slot naming a column the data does not have is a skip, not a crash."""
    missing = [c for c in cols if c and c not in df.columns]
    _need(not missing, f"配置里指定的列不在数据中：{missing}",
          f"可用列示例：{list(df.columns)[:8]}")


def _items(cfg: dict):
    """config.items is either a list or {"scale": [...]}; accept both."""
    val = cfg.get("items")
    if isinstance(val, dict):
        val = next(iter(val.values()), None)
    return [c for c in (val or []) if isinstance(c, str)]


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------


class FigureBook:
    def __init__(self, out_dir: str, formats, dpi: int = 600):
        self.dir = out_dir
        self.formats = formats
        self.dpi = dpi
        self.made = []

    def save(self, fig, name: str, caption: str) -> str:
        os.makedirs(self.dir, exist_ok=True)
        paths = PF.save_fig(fig, self.dir, name, formats=self.formats, dpi=self.dpi)
        self.made.append({"name": name, "caption": caption, "png": paths[0] if paths else ""})
        return paths[0] if paths else ""


def _fig(w_cm: float = WIDTH_CM, h_in: float = 3.4, nrows: int = 1, ncols: int = 1):
    fig, axes = plt.subplots(nrows, ncols, figsize=(w_cm / 2.54, h_in), squeeze=False)
    return fig, axes


# ---------------------------------------------------------------------------
# runners
# ---------------------------------------------------------------------------


def run_m01(ctx: dict) -> ML.Result:
    df = ctx["df"]
    cols = ctx["cfg"].get("describe")
    return ML.describe(df, cols)


def run_m12(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    val = _col(cfg, "continuous")
    grp = cfg.get("group")
    paired = cfg.get("paired")
    if paired and len(paired) == 2:
        _need(all(c in df.columns for c in paired), f"配对列不存在：{paired}")
        return ML.t_test_paired(df, paired[0], paired[1])
    _need(bool(val), "config.continuous 未指定", "m17")
    _need(bool(grp), "config.group 未指定", "m17")
    levels = df[grp].dropna().nunique()
    if levels > 2:
        _need(False, f"{grp} 有 {levels} 组，t 检验只接受 2 组", "m04 方差分析")
    return ML.t_test_independent(df, val, grp)


def run_m04(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    val, grp = _col(cfg, "continuous"), cfg.get("group")
    _need(bool(val) and bool(grp), "config.continuous 与 config.group 都必须给出", "m17")
    res = ML.anova(df, val, grp)
    if res.stats.get("p", 1) < ctx["alpha"]:
        try:
            extra = ML.posthoc(df, val, grp, alpha=ctx["alpha"])
            res.tables.extend(extra.tables)
            res.verdict = res.verdict + extra.verdict
        except ML.MethodError as exc:
            res.notes.append(f"事后比较未执行：{exc}")
    return res


def run_m17_nonparametric(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    grp = cfg.get("group")
    _need(bool(grp), "config.group 未指定", "")
    val = _col(cfg, "continuous")
    if val:
        levels = df[grp].dropna().nunique()
        if levels == 2:
            return ML.mannwhitney(df, val, grp)
        return ML.kruskal(df, val, grp)
    paired = cfg.get("paired")
    if paired and len(paired) == 2:
        return ML.wilcoxon(df, paired[0], paired[1])
    raise Skip("非参数检验需要 config.continuous+group 或 config.paired")


def run_m05(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    row = _get(cfg, "row", "group")
    col = _get(cfg, "column")
    _need(bool(row) and bool(col), "config.row 与 config.column 都需要（分类×分类）", "m01")
    res = ML.chi_square(df, row, col, alpha=ctx["alpha"])
    if df[row].nunique() > 2 and ctx["cfg"].get("pairwise", True):
        try:
            extra = ML.chi_square_pairs(df, row, col, alpha=ctx["alpha"])
            res.tables.extend(extra.tables)
            res.verdict = res.verdict + extra.verdict
        except ML.MethodError as exc:
            res.notes.append(f"两两比较未执行：{exc}")
    return res


def run_m03(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    cols = cfg.get("correlate") or ([_col(cfg, "continuous")] if _col(cfg, "continuous") else [])
    cols = [c for c in cols if c] + list(cfg.get("predictors") or [])
    cols = list(dict.fromkeys([c for c in cols if c in df.columns]))
    _need(len(cols) >= 2, "相关分析需要至少两个数值列（config.correlate / predictors）", "m01")
    return ML.correlation(df, cols, method=cfg.get("corr_method", "auto"), alpha=ctx["alpha"])


def run_m11(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    y = _col(cfg, "continuous")
    xs = cfg.get("predictors") or []
    _need(bool(y) and bool(xs), "config.continuous（因变量）与 config.predictors 都需要", "m18")
    res = ML.linear_regression(df, y, xs, alpha=ctx["alpha"])
    try:
        coef = res.tables[0][1]
        sub = coef[coef["term"] != "const"].copy()
        sub["low"] = sub["beta"] - 1.96 * sub["se"]
        sub["high"] = sub["beta"] + 1.96 * sub["se"]
        ctx["beta_frame"] = sub
    except Exception:
        pass
    return res


def run_m10_clustering(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    cols = cfg.get("cluster_vars")
    _need(bool(cols) and len(cols) >= 2, "聚类需要 config.cluster_vars 中的至少两个数值变量", "m02")
    _need_cols(df, *cols)
    k = int(cfg.get("cluster_k", 3))
    res = ML.kmeans_analysis(df, cols, k=k, seed=ctx["seed"])
    ctx["cluster_frame"] = res.tables[1][1].copy()
    return res


def run_m18_logistic(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    y = _col(cfg, "outcome")
    xs = cfg.get("predictors") or []
    _need(bool(y) and bool(xs), "config.outcome（0/1）与 config.predictors 都需要", "")
    info = cfg.get("outcome") or {}
    if isinstance(info, dict) and info.get("positive") not in (None, 1):
        df = df.copy()
        pos = info["positive"]
        df[y] = pd.to_numeric(df[y], errors="coerce").map(
            {pos: 1, **{k: 0 for k in df[y].dropna().unique() if k != pos}})
    res = ML.logistic(df, y, xs, alpha=ctx["alpha"])
    try:
        coef = res.tables[0][1]
        sub = coef[coef["term"] != "const"].copy()
        ctx["or_frame"] = sub
    except Exception:
        pass
    return res


def run_m02(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    cols = cfg.get("cluster_vars") or cfg.get("items")
    _need(bool(cols) and len(cols) >= 3, "主成分分析需要至少三个数值变量（config.cluster_vars）", "m09")
    k = int(cfg.get("components", 2))
    return ML.pca(df, cols, n_components=k)


def run_m09_factor_analysis(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    cols = _items(cfg)
    _need(len(cols) >= 3, "因子分析需要 config.items 中的至少三个题项", "m02")
    _need_cols(df, *cols)
    return ML.efa(df, cols, n_factors=cfg.get("n_factors"), alpha=ctx["alpha"])


def run_m15(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    items = _items(cfg)
    _need(len(items) >= 2, "信度分析需要 config.items（同一构念的题项列表）", "")
    _need_cols(df, *items)
    return ML.cronbach(df, items, alpha=ctx["alpha"])


def run_m16(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    items = _items(cfg)
    _need(len(items) >= 3, "效度（结构效度）需要至少三个题项", "m15")
    _need_cols(df, *items)
    return ML.validity(df, items, n_factors=cfg.get("n_factors"), alpha=ctx["alpha"])


def run_m14(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    pairs = cfg.get("kano")
    _need(bool(pairs), "卡诺模型需要 config.kano = {需求名: [功能列, 反功能列]}", "")
    clean = {k: tuple(v) for k, v in pairs.items()
             if isinstance(v, (list, tuple)) and len(v) == 2 and all(c in df.columns for c in v)}
    _need(bool(clean), "config.kano 里的列在数据中找不到", "")
    return ML.kano(df, clean)


def run_m07(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    spec = cfg.get("discriminant") or {}
    grp, cols = spec.get("group"), spec.get("vars")
    _need(bool(grp) and bool(cols), "判别分析需要 config.discriminant = {group, vars}", "m18")
    _need_cols(df, grp, *cols)
    res = ML.lda(df, grp, cols)
    ctx["lda_frame"] = res.tables[0][1].copy()
    return res


def run_m08(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    t = cfg.get("time") or {}
    _need(isinstance(t, dict) and t.get("col") and t.get("value"),
          "时间序列需要 config.time = {col, value}", "")
    _need_cols(df, t["col"], t["value"])
    return ML.time_series(df, t["col"], t["value"], alpha=ctx["alpha"])


def run_m13(ctx: dict) -> ML.Result:
    df, cfg = ctx["df"], ctx["cfg"]
    p = cfg.get("path") or {}
    _need(all(p.get(k) for k in ("x", "m", "y")), "中介效应需要 config.path = {x, m, y}", "")
    return ML.mediation(df, p["x"], p["m"], p["y"], n_boot=int(cfg.get("boot", 2000)),
                        seed=ctx["seed"], alpha=ctx["alpha"])


def run_m06(ctx: dict) -> ML.Result:
    return ML.sem()


# One runner per catalogue number, and the number means exactly one thing:
# m09 is factor analysis, m17 is the non-parametric family it is often swapped
# for. They share code, not numbering.
RUNNERS = {
    "m01": run_m01, "m02": run_m02, "m03": run_m03, "m04": run_m04,
    "m05": run_m05, "m06": run_m06, "m07": run_m07, "m08": run_m08,
    "m09": run_m09_factor_analysis, "m10": run_m10_clustering, "m11": run_m11,
    "m12": run_m12, "m13": run_m13, "m14": run_m14, "m15": run_m15,
    "m16": run_m16, "m17": run_m17_nonparametric, "m18": run_m18_logistic,
}


def dispatch(mid: str, ctx: dict) -> ML.Result:
    """Route one catalogue id to its runner."""
    return RUNNERS[mid](ctx)


# ---------------------------------------------------------------------------
# figures per method
# ---------------------------------------------------------------------------


def draw(mid: str, run: Run, ctx: dict) -> None:
    """Draw the figure a reader of this method expects, or say why not."""
    res, book = run.result, ctx["book"]
    try:
        if mid == "m01":
            num = [t for t in res.tables[0][1].itertuples() if t.type == "连续"]
            if not num:
                return
            var = num[0].variable
            fig, axes = _fig(h_in=2.9, nrows=1, ncols=2,
                             )
            PF.plot_distribution(axes[0][0], axes[0][1], ctx["df"][var].dropna(),
                                 xlabel=var)
            fig.subplots_adjust(bottom=0.16)
            run.figure = book.save(fig, "m01_descriptive", f"{var} 的分布")
        elif mid == "m12":
            tab = res.tables[0][1]
            fig, axes = _fig(h_in=2.8)
            ax = axes[0][0]
            est = tab["mean"].tolist()
            half = [1.96 * s / math.sqrt(n) for s, n in zip(tab["sd"], tab["n"])]
            PF.bar_with_ci(ax, tab["group"].astype(str).tolist(), est,
                           [e - h for e, h in zip(est, half)],
                           [e + h for e, h in zip(est, half)])
            ax.set_ylabel(_col(ctx["cfg"], "continuous") or "")
            PF.style_axis(ax)
            fig.subplots_adjust(bottom=0.18)
            run.figure = book.save(fig, "m12_ttest", "两组的均值与 95%CI")
        elif mid == "m04":
            tab = res.tables[0][1]
            fig, axes = _fig(h_in=2.8)
            ax = axes[0][0]
            est = tab["mean"].tolist()
            half = [1.96 * s / math.sqrt(n) for s, n in zip(tab["sd"], tab["n"])]
            PF.bar_with_ci(ax, tab["group"].astype(str).tolist(), est,
                           [e - h for e, h in zip(est, half)],
                           [e + h for e, h in zip(est, half)])
            ax.set_ylabel(_col(ctx["cfg"], "continuous") or "")
            PF.style_axis(ax)
            fig.subplots_adjust(bottom=0.2)
            run.figure = book.save(fig, "m04_anova", "各组均值与 95%CI")
        elif mid == "m05":
            tab = res.tables[2][1]
            fig, axes = _fig(h_in=3.0)
            ax = axes[0][0]
            PF.heatmap(ax, tab.values, [str(i) for i in tab.index],
                       [str(c) for c in tab.columns], annotate=True, fmt=".1f")
            ax.set_xlabel("列变量"); ax.set_ylabel("行变量")
            fig.subplots_adjust(left=0.28, bottom=0.3)
            run.figure = book.save(fig, "m05_chisq", "行百分比")
        elif mid == "m03":
            tab = res.tables[0][1]
            vars_ = sorted(set(tab["var1"]) | set(tab["var2"]))
            mat = pd.DataFrame(np.eye(len(vars_)), index=vars_, columns=vars_)
            for r in tab.itertuples():
                if r.r is not None:
                    mat.loc[r.var1, r.var2] = r.r
                    mat.loc[r.var2, r.var1] = r.r
            fig, axes = _fig(h_in=3.2)
            PF.corr_heatmap(axes[0][0], mat, method="pearson", annotate=True)
            fig.subplots_adjust(left=0.26, bottom=0.26)
            run.figure = book.save(fig, "m03_corr", "相关系数矩阵")
        elif mid == "m11" and ctx.get("beta_frame") is not None:
            sub = ctx["beta_frame"]
            fig, axes = _fig(h_in=max(2.4, 0.32 * len(sub) + 1.2))
            PF.forest_plot(axes[0][0], [PF.short_label(t) for t in sub["term"]],
                           sub["beta"].tolist(), sub["low"].tolist(),
                           sub["high"].tolist(),
                           ref=0.0, log_scale=False, xlabel="β（95%CI）")
            fig.subplots_adjust(left=0.42, bottom=0.16)
            run.figure = book.save(fig, "m11_ols_coef", "回归系数与 95%CI")
        elif mid == "m10" and res.tables:
            prof = res.tables[0][1]
            fig, axes = _fig(h_in=2.8)
            PF.bar_counts(axes[0][0], prof["cluster"].astype(str).tolist(),
                          prof["n"].tolist(), fmt="{:,.0f}", xlabel="聚类",
                          ylabel="观测数")
            fig.subplots_adjust(bottom=0.2)
            run.figure = book.save(fig, "m10_cluster_sizes", "各聚类规模")
        elif mid == "m18" and ctx.get("or_frame") is not None:
            sub = ctx["or_frame"]
            fig, axes = _fig(h_in=max(2.4, 0.32 * len(sub) + 1.2))
            PF.forest_plot(axes[0][0], [PF.short_label(t) for t in sub["term"]],
                           sub["OR"].tolist(), sub["OR_ci_low"].tolist(),
                           sub["OR_ci_high"].tolist(), ref=1.0, log_scale=True)
            fig.subplots_adjust(left=0.42, bottom=0.16)
            run.figure = book.save(fig, "m18_logit_or", "OR 与 95%CI")
        elif mid == "m02":
            var = res.tables[1][1]
            fig, axes = _fig(h_in=2.9)
            PF.scree_plot(axes[0][0], var["eigenvalue"].tolist())
            fig.subplots_adjust(bottom=0.18)
            run.figure = book.save(fig, "m02_pca_scree", "主成分特征值（碎石图）")
        elif mid == "m09":
            var = res.tables[1][1]
            fig, axes = _fig(h_in=2.9)
            PF.scree_plot(axes[0][0], var["eigenvalue"].tolist())
            fig.subplots_adjust(bottom=0.18)
            run.figure = book.save(fig, "m09_efa_scree", "因子特征值（碎石图）")
        elif mid == "m15" and res.tables:
            tab = res.tables[0][1]
            fig, axes = _fig(h_in=2.8)
            PF.bar_counts(axes[0][0], tab["item"].astype(str).tolist(),
                          tab["item_total_r"].tolist(), horizontal=True,
                          fmt="{:.2f}", xlabel="项目-总体相关")
            fig.subplots_adjust(left=0.3, bottom=0.18)
            run.figure = book.save(fig, "m15_items", "项目-总体相关")
        elif mid == "m16" and res.tables:
            load = res.tables[0][1]
            mat = load.set_index(load.columns[0])
            # communality lives on a 0..1 scale, not the -1..1 loading scale, so
            # it stays in the table and out of the colour bar.
            keep = [c for c in mat.columns if str(c).lower() not in ("communality", "共同度")]
            mat = mat[keep]
            fig, axes = _fig(h_in=3.2)
            PF.heatmap(axes[0][0], mat.values, [str(i) for i in mat.index],
                       [str(c) for c in mat.columns], annotate=True, fmt=".2f",
                       cmap="RdBu_r", vmin=-1, vmax=1)
            axes[0][0].set_xlabel("因子"); axes[0][0].set_ylabel("题项")
            fig.subplots_adjust(left=0.24, bottom=0.26)
            run.figure = book.save(fig, "m16_loadings", "因子载荷")
        elif mid == "m14":
            tab = res.tables[0][1]
            fig, axes = _fig(h_in=3.0)
            ax = axes[0][0]
            ax.axhline(0, color="gray", lw=0.8)
            ax.axvline(0.5, color="gray", lw=0.8, ls=":")
            for r in tab.itertuples():
                ax.scatter(r.better, r.worse, s=22, color=PF.BLUE)
                ax.annotate(r.feature, (r.better, r.worse), fontsize=7,
                            xytext=(4, 3), textcoords="offset points")
            ax.set_xlabel("better（满足时的满意度提升）")
            ax.set_ylabel("worse（不满足时的不满意）")
            PF.style_axis(ax, grid_axis="both")
            fig.subplots_adjust(left=0.16, bottom=0.18)
            run.figure = book.save(fig, "m14_kano", "Kano 四象限")
        elif mid == "m07" and ctx.get("lda_frame") is not None:
            coef = ctx["lda_frame"].copy().sort_values("standardised")
            fig, axes = _fig(h_in=max(2.2, 0.3 * len(coef) + 1.3))
            ax = axes[0][0]
            ax.barh(coef["variable"].astype(str).tolist(),
                    coef["standardised"].tolist(),
                    color=[PF.BLUE if v >= 0 else PF.ORANGE for v in coef["standardised"]],
                    height=0.62)
            ax.axvline(0, color="black", lw=0.8)
            ax.set_xlabel("标准化判别系数（LD1）")
            PF.style_axis(ax, grid_axis="x")
            fig.subplots_adjust(left=0.3, bottom=0.2)
            run.figure = book.save(fig, "m07_lda_coef", "判别函数系数")
        elif mid == "m08":
            fitted = res.tables[1][1].dropna(subset=["fitted"])
            # Repeated timestamps are common in survey data; connecting raw
            # observations would draw a zig-zag through all of them, so the
            # line joins the per-time means (identical to the series when each
            # time point appears once).
            agg = fitted.groupby("time", as_index=False).mean(numeric_only=True)
            fig, axes = _fig(h_in=3.0)
            ax = axes[0][0]
            ax.plot(agg["time"], agg["observed"], marker="o", ms=4,
                    lw=1.2, color=PF.BLUE, label="观测值（按时间均值）")
            ax.plot(agg["time"], agg["fitted"], lw=1.5, ls="--",
                    color=PF.ORANGE, label="ARIMA 拟合值")
            ax.set_xlabel(str((ctx["cfg"].get("time") or {}).get("col", "时间")))
            ax.set_ylabel(str((ctx["cfg"].get("time") or {}).get("value", "")))
            ax.legend(frameon=False, fontsize=8)
            PF.style_axis(ax)
            fig.subplots_adjust(bottom=0.18)
            run.figure = book.save(fig, "m08_series", "观测值与拟合值")
        elif mid == "m17" and res.tables:
            tab = res.tables[0][1]
            fig, axes = _fig(h_in=2.9)
            PF.bar_with_ci(axes[0][0], tab["group"].astype(str).tolist(),
                           tab["median"].tolist(), tab["p25"].tolist(),
                           tab["p75"].tolist())
            axes[0][0].set_ylabel("中位数（P25–P75）")
            PF.style_axis(axes[0][0])
            fig.subplots_adjust(bottom=0.2)
            run.figure = book.save(fig, "m17_medians", "各组中位数与四分位距")
        elif mid == "m13":
            fig, axes = _fig(h_in=1.9)
            ax = axes[0][0]
            eff = res.tables[1][1].iloc[0]
            PF.forest_plot(ax, ["间接效应 a×b"], [eff["indirect"]],
                           [eff["boot_lo"]], [eff["boot_hi"]],
                           ref=0.0, log_scale=False, xlabel="间接效应（bootstrap 95%CI）")
            fig.subplots_adjust(left=0.3, bottom=0.22)
            run.figure = book.save(fig, "m13_mediation", "间接效应")
    except Exception as exc:  # a figure must never kill the battery
        run.reason = (run.reason + f"；图未生成：{type(exc).__name__}: {exc}").strip("；")
        print(f"warning: {mid} 图未生成：{type(exc).__name__}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def write_report(path: str, runs: list, ctx: dict) -> None:
    lines = ["# 十六种分析方法运行报告（另含非参数检验族）", "",
             f"- 数据：`{ctx['data_path']}`（n={len(ctx['df'])} 行，{ctx['df'].shape[1]} 列）",
             f"- 配置：`{ctx['config_path']}`",
             f"- 生成者：methods_pack.py {SCRIPT_VERSION}",
             f"- 显著性水平：α={ctx['alpha']}；随机种子：{ctx['seed']}", "",
             "本报告只陈述能由这份数据支持的结论。被跳过的办法不是失败，"
             "而是**这份数据不支持它**，原因逐条写在下面。", ""]
    ok = [r for r in runs if r.status == "ok"]
    skipped = [r for r in runs if r.status != "ok"]
    lines += [f"## 总览（{len(ok)} 个完成 / {len(skipped)} 个跳过）", "",
              "| 编号 | 方法 | 状态 | 关键结果 | 图 |", "|---|---|---|---|---|"]
    for r in runs:
        key = ""
        if r.result:
            s = r.result.stats
            bits = []
            for k in ("p", "r2", "adj_r2", "alpha", "kmo", "chi2", "F", "H", "t",
                      "silhouette", "mcfadden_r2", "wilks", "indirect", "aic",
                      "pc1_pct", "n_factors", "k", "features", "accuracy", "n"):
                if k in s and isinstance(s[k], (int, float)) and not isinstance(s[k], bool):
                    bits.append(f"{k}={s[k]:.4g}")
            key = "，".join(bits[:3])
        lines.append(f"| {BY_ID[r.spec['id']]['nr']} | {BY_ID[r.spec['id']]['cn']} | "
                     f"{'完成' if r.status == 'ok' else '跳过'} | {key} | "
                     f"{'有' if r.figure else '—'} |")
    lines.append("")
    for r in runs:
        spec = BY_ID[r.spec["id"]]
        lines += [f"## {spec['nr']}. {spec['cn']}（{spec['en']}）", "",
                  f"**适用**：{spec['when']}", ""]
        if r.status != "ok":
            lines += [f"**本次跳过**：{r.reason}", ""]
            if spec["fallback"]:
                lines += [f"**可改用**：{spec['fallback']}", ""]
            continue
        mlr = r.result
        for name, table in mlr.tables:
            if table is None or (hasattr(table, "empty") and table.empty):
                continue
            lines += [f"**{name}**", "", _md_table(table.head(30)), ""]
            if hasattr(table, "__len__") and len(table) > 30:
                lines += [f"（表共 {len(table)} 行，完整内容见 `{r.spec['id']}_{name}.csv`）", ""]
        if mlr.verdict:
            lines += ["**判定**", ""] + [f"- {v}" for v in mlr.verdict] + [""]
        if mlr.notes:
            lines += ["**注意**", ""] + [f"- {n}" for n in mlr.notes] + [""]
        if r.figure:
            lines += [f"![{spec['cn']}]({os.path.basename(r.figure)})", ""]
    lines += ["## 报告句式（可直接改写进正文）", "",
              "| 方法 | 句式 |", "|---|---|",
              "| 描述性 | “连续变量以 M±SD 或 M（P25，P75）描述，分类变量以 n（%）描述。” |",
              "| t 检验 | “t(df)=…，p=…，Cohen's d=…。” |",
              "| 方差分析 | “F(df1,df2)=…，p=…，η²=…；事后比较采用 Bonferroni 校正。” |",
              "| 卡方 | “χ²(df)=…，p=…，Cramér's V=…。” |",
              "| 相关 | “r=…，p=…（Pearson/Spearman）。” |",
              "| 线性回归 | “R²=…，F(…)=…，p=…；β=…，95%CI […]。” |",
              "| Logistic | “OR=…，95%CI […]，p=…；McFadden R²=…。” |",
              "| 信度 | “Cronbach's α=…。” |",
              "| 因子分析 | “KMO=…，Bartlett χ²(…)=…，p<.001；提取 k 个因子，累计解释 …%。” |",
              "| 聚类 | “K=…，轮廓系数=…。” |",
              "| 中介 | “间接效应=…，bootstrap 95%CI […]；占总效应 …%。” |", ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _md_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        cells = []
        for v in row:
            if v is None or (isinstance(v, float) and math.isnan(v)):
                cells.append("—")
            elif isinstance(v, float):
                cells.append(f"{v:.4g}")
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data")
    ap.add_argument("--config")
    ap.add_argument("--out", default="output/methods")
    ap.add_argument("--methods", default="all",
                    help="all | comma list (m01,m04) | family name (model)")
    ap.add_argument("--only", default="", help="同 --methods，便于与其它脚本对齐")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--formats", default="png,pdf")
    ap.add_argument("--feedback-png-only", action="store_true", help="只出 png（调试）")
    args = ap.parse_args(argv)

    if args.list:
        print(f"{'#':>3}  {'id':4}  {'方法':<16}{'需要':<28}替代")
        for m in sorted(CATALOG, key=lambda x: x["nr"]):
            slots = ",".join(m["slots"]) or "—"
            print(f"{m['nr']:>3}  {m['id']:4}  {m['cn']:<16}{slots:<28}{m['fallback'] or '—'}")
        return 0

    if not args.data:
        print("ERROR: --data is required (or use --list)", file=sys.stderr)
        return 2
    if not os.path.isfile(args.data):
        print(f"ERROR: data not found: {args.data}", file=sys.stderr)
        return 2
    df = pd.read_csv(args.data, encoding="utf-8-sig", low_memory=False)
    if df.empty:
        print("ERROR: data has no rows", file=sys.stderr)
        return 2
    cfg = {}
    if args.config:
        if not os.path.isfile(args.config):
            print(f"ERROR: config not found: {args.config}", file=sys.stderr)
            return 2
        with open(args.config, encoding="utf-8-sig") as fh:
            cfg = json.load(fh) or {}
    os.makedirs(args.out, exist_ok=True)

    wanted = (args.only or args.methods or "all").strip()
    if wanted == "all":
        ids = [m["id"] for m in CATALOG]
    elif wanted in {m["family"] for m in CATALOG}:
        ids = [m["id"] for m in CATALOG if m["family"] == wanted]
    else:
        ids = [w.strip() for w in wanted.split(",") if w.strip()]
        unknown = [i for i in ids if i not in BY_ID]
        if unknown:
            print(f"ERROR: 未知方法 {unknown}；用 --list 查编号", file=sys.stderr)
            return 2

    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    if args.feedback_png_only:
        formats = ("png",)
    # Without this every CJK glyph falls back to DejaVu Sans and the figure is
    # full of empty boxes while the script still reports success.
    PF.set_style(width_cm=WIDTH_CM, dpi=600)
    ctx = {"df": df, "cfg": cfg, "alpha": args.alpha, "seed": args.seed,
           "data_path": args.data, "config_path": args.config or "",
           "book": FigureBook(os.path.join(args.out, "figures"), formats)}

    runs = []
    for mid in ids:
        spec = BY_ID[mid]
        run = Run(spec=spec)
        try:
            res = dispatch(mid, ctx)
            run.result = res
            run.status = res.status
            # The manifest's reason column is for "why skipped/failed"; for a
            # successful run a short warning is enough, full notes live in the
            # report. 300 chars keeps the CSV readable.
            text = "；".join(n for n in res.notes if n)
            run.reason = text if len(text) <= 300 else text[:299] + "…"
        except Skip as exc:
            run.status = "skipped"
            run.reason = str(exc)
        except ML.MethodError as exc:
            run.status = "skipped"
            run.reason = str(exc)
        except Exception as exc:
            run.status = "error"
            run.reason = f"{type(exc).__name__}: {exc}"
            print(f"warning: {mid} 出错：{exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        # tables always land on disk; the report only shows the head
        if run.result:
            for name, table in run.result.tables:
                if table is None or not hasattr(table, "to_csv"):
                    continue
                path = os.path.join(args.out, f"{mid}_{name}.csv")
                table.to_csv(path, index=False, encoding="utf-8-sig")
                run.table_files = (run.table_files or []) + [path]
            if not args.no_figures:
                draw(mid, run, ctx)
        runs.append(run)
        mark = {"ok": "完成", "skipped": "跳过", "error": "出错"}[run.status]
        print(f"{mid} {spec['cn']}: {mark}"
              + (f" — {run.reason}" if run.reason and run.status != "ok" else ""))

    report = os.path.join(args.out, "methods_report.md")
    write_report(report, runs, ctx)
    manifest = os.path.join(args.out, "methods_manifest.csv")
    with open(manifest, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "nr", "method", "family", "status", "n", "key_stats",
                    "figure", "tables", "reason"])
        for r in runs:
            s = (r.result.stats if r.result else {}) or {}
            keys = ",".join(f"{k}={s[k]:.4g}" for k in sorted(s)
                            if isinstance(s[k], (int, float)) and not isinstance(s[k], bool))
            w.writerow([r.spec["id"], r.spec["nr"], r.spec["cn"], r.spec["family"],
                        r.status, len(ctx["df"]), keys, os.path.basename(r.figure or ""),
                        ";".join(os.path.basename(p) for p in (r.table_files or [])),
                        r.reason])
    n_ok = sum(1 for r in runs if r.status == "ok")
    n_skip = sum(1 for r in runs if r.status == "skipped")
    n_err = sum(1 for r in runs if r.status == "error")
    print(f"methods: {len(runs)}  ok: {n_ok}  skipped: {n_skip}  errors: {n_err}")
    print(f"report: {report}")
    print(f"manifest: {manifest}")
    if n_err:
        return 2
    if n_ok == 0:
        print("ERROR: 没有任何方法跑通——检查 --config 的槽位是否对得上数据列", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())