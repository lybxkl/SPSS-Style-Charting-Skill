#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a comprehensive, question-driven chart pack from an analysis CSV.

The default pack covers:
  A. data quality: missingness, sample composition, outcome prevalence
  B. univariate: numeric distributions, categorical distributions, Q-Q, donut
  C. bivariate: group × outcome, treatment × outcome, cross-tabs, correlations
  D. multivariate: violin/box, scatter matrix, PCA biplot/loadings, dendrogram, MDS
  E. time: sample trend, outcome trend, 3-sigma control chart, composition
  F. model diagnostics: forest, ROC, calibration, confusion, PR, lift
     (when --coef/--pred supplied); Kaplan-Meier when survival columns exist
  G. appendix: correspondence analysis, Pareto

It is intentionally generous: more charts are better than making the user ask
again. Every chart gets a manifest row with its question, N, variables, caption
and file paths.

Usage:
    python auto_chart_pack.py --data data/analysis.csv --out output/chart_pack
    python auto_chart_pack.py --data ... --config chart_config.json --tiff
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubfig import (  # noqa: E402
    set_style, save_fig, wilson_ci, style_axis,
    bar_counts, plot_distribution, plot_violin, stacked_bar, line_ci,
    heatmap, corr_heatmap, scatter_fit, roc_curve, calibration_plot,
    pareto, scree_plot, forest_plot, dumbbell,
    stacked_area, bubble,
    pie_chart, qq_plot, control_chart, dendrogram_plot, classical_mds,
    mds_plot, pr_curve, lift_chart, confusion_heatmap, kaplan_meier,
    BLUE, ORANGE, GRAY, LGRAY, INK,
)
from analysis_utils import (  # noqa: E402
    apply_filter, encode_binary, is_constant, is_id_like, outcome_kind,
    read_csv_auto, same_values,
)

FIG_W = 15 / 2.54  # 15 cm text width, A4 with standard margins

SHORT_CATEGORY = {
    "其他": "其他",
}


def short_label(value, col: str = "") -> str:
    s = str(value)
    if col in {"category", "crime"} and s in SHORT_CATEGORY:
        return SHORT_CATEGORY[s]
    if re.fullmatch(r"[A-Za-z0-9_ ]+", s):
        return s if len(s) <= 22 else s[:20] + "…"
    s = s.replace("罪", "")
    return s if len(s) <= 9 else s[:8] + "…"


def top_counts(series: pd.Series, n: int) -> tuple[list[str], np.ndarray]:
    vc = series.dropna().astype(str).value_counts()
    top = vc.head(n)
    rest = vc.iloc[n:].sum()
    labels = list(top.index)
    values = list(top.values)
    if rest > 0:
        rest_label = "其余类别" if "其他" in labels else "其他"
        labels.append(rest_label)
        values.append(rest)
    return labels, np.asarray(values, dtype=float)


def is_binary(series: pd.Series) -> bool:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return False
    return set(np.unique(s)).issubset({0, 1}) and s.nunique() >= 1


def role_columns(df: pd.DataFrame, cfg: dict, max_categories: int):
    drop = set(cfg.get("drop", []))
    id_col = cfg.get("id") or next((c for c in ["id", "file", "path"] if c in df.columns), None)
    time_col = cfg.get("time")
    if not time_col:
        time_col = next((c for c in df.columns if re.search(r"year|年份|时间|date", c, re.I)), None)
    group_col = cfg.get("group")
    if not group_col:
        group_col = next((c for c in df.columns if re.search(r"category|crime|group|类别|案由", c, re.I)), None)
    treatment_col = cfg.get("treatment")
    if not treatment_col:
        treatment_col = next((c for c in df.columns if re.search(r"stage|treatment|处理|阶段", c, re.I)), None)
    outcome_col = cfg.get("outcome")
    if not outcome_col:
        outcome_col = next((c for c in df.columns if re.search(r"outcome_binary|outcome|target|结果|支持", c, re.I)), None)

    binaries = [c for c in df.columns if c not in drop and c != id_col
                and is_binary(df[c]) and not is_constant(df[c]) and not is_id_like(c, df[c])]
    if not outcome_col:
        outcome_col = next((c for c in binaries if 0.05 < df[c].mean() < 0.95), None)
    categorical = []
    for c in df.columns:
        if c in drop or c == id_col or is_constant(df[c]) or is_id_like(c, df[c]):
            continue
        n = df[c].nunique(dropna=True)
        if 2 <= n <= max_categories and (df[c].dtype == object or c in binaries or n <= 12):
            categorical.append(c)
    numeric = []
    for c in df.columns:
        if c in drop or c == id_col or c in binaries or is_constant(df[c]) or is_id_like(c, df[c]):
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() >= 10 and s.nunique() > max_categories:
            numeric.append(c)
    if time_col in numeric:
        numeric.remove(time_col)

    cfg_num = cfg.get("numeric")
    cfg_cat = cfg.get("categorical")
    cfg_bin = cfg.get("binary")
    if cfg_num:
        numeric = [c for c in cfg_num if c in df.columns]
    if cfg_cat:
        categorical = [c for c in cfg_cat if c in df.columns]
    if cfg_bin:
        binaries = [c for c in cfg_bin if c in df.columns]
    return id_col, time_col, group_col, treatment_col, outcome_col, numeric, categorical, binaries


class ChartPack:
    def __init__(self, df: pd.DataFrame, out_dir: str, cfg: dict, formats: list[str],
                 top_n: int, min_n: int):
        self.df = df
        self.out_dir = out_dir
        self.fig_dir = os.path.join(out_dir, "figures")
        os.makedirs(self.fig_dir, exist_ok=True)
        self.cfg = cfg
        self.formats = formats
        self.top_n = top_n
        self.min_n = min_n
        self.manifest = []
        self.skipped = []
        self.vlabels = cfg.get("variable_labels", {}) if cfg else {}
        self.glabels = cfg.get("value_labels", {}) if cfg else {}
        self.binary_outcome = False
        self.outcome_kind = "unknown"
        self.outcome = None
        self.outcome_labels = {}
        self.rate_label = "比例（0–1）"
        self.rate_pct_label = "比例（%）"
        self.mean_label = "均值"

    def set_outcome(self, outcome: str | None, kind: str, outcome_map: dict | None = None):
        self.outcome = outcome
        self.outcome_kind = kind
        self.binary_outcome = kind == "binary"
        self.outcome_labels = {int(v): str(k) for k, v in (outcome_map or {}).items()
                               if str(v).lstrip("-").isdigit()}
        label = self.vlabel(outcome) if outcome else "结果"
        self.rate_label = f"{label}比例（0–1）"
        self.rate_pct_label = f"{label}比例（%）"
        self.mean_label = f"{label}均值"

    def vlabel(self, col: str) -> str:
        return self.vlabels.get(col, short_label(col))

    def glabel(self, value, col: str = "") -> str:
        if col == self.outcome and self.outcome_labels:
            try:
                key = int(float(value))
                if key in self.outcome_labels:
                    return self.outcome_labels[key]
            except (TypeError, ValueError):
                pass
        mapping = self.glabels.get(col, {})
        return mapping.get(str(value), short_label(value, col))

    def numeric_display(self, s: pd.Series):
        """Return (values, note) where note is '', 'log', or 'clip'."""
        skew = float(s.skew()) if len(s) > 2 else 0.0
        if s.min() > 0 and skew > 2:
            return np.log10(s.values), "log"
        if skew > 2:
            cap = float(s.quantile(0.99))
            return s[s <= cap].values, "clip"
        return s.values, ""

    def save(self, fig, slug: str, section: str, question: str, chart_type: str,
             variables: list[str], n: int, caption: str, note: str = ""):
        if int(n) <= 0:
            self.skip(section, question, "no valid observations (N=0)")
            plt.close(fig)
            return
        idx = len(self.manifest) + 1
        name = f"fig{idx:02d}_{slug}"
        caption = re.sub(r"N=[\d,]+", f"N={int(n):,}", caption, count=1)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fig.tight_layout(pad=0.4)
        except Exception:
            pass
        paths = save_fig(fig, self.fig_dir, name, formats=self.formats)
        by_ext = {os.path.splitext(p)[1].lower().lstrip("."): p for p in paths}
        self.manifest.append({
            "id": f"F{idx:02d}", "section": section, "question": question,
            "chart_type": chart_type, "variables": "; ".join(variables),
            "n": n, "png": by_ext.get("png", ""), "pdf": by_ext.get("pdf", ""),
            "tiff": by_ext.get("tiff", ""), "caption": caption, "note": note,
            "status": "ok",
        })

    def skip(self, section: str, question: str, reason: str):
        self.skipped.append({"section": section, "question": question, "reason": reason})

    def caption(self, extra: str = "") -> str:
        parts = [f"N={len(self.df):,}"]
        if extra:
            parts.append(extra)
        parts.append("数据来源：分析数据集")
        return "注：" + "；".join(parts) + "。"

    # ------------------------------------------------------------------
    # A. Data quality / sample structure
    # ------------------------------------------------------------------
    def data_quality(self, group, time, region):
        miss = self.df.isna().mean().sort_values(ascending=False)
        miss = miss[miss > 0].head(25)
        if len(miss):
            fig, ax = plt.subplots(figsize=(FIG_W, max(2.6, 0.24 * len(miss) + 1.2)))
            labels = [self.vlabel(c) for c in miss.index]
            bar_counts(ax, labels, miss.values * 100, horizontal=True,
                       fmt="{:.1f}%", xlabel="缺失率（%）")
            ax.set_xlim(0, max(10, miss.max() * 100 * 1.2))
            self.save(fig, "missingness", "A 数据质量",
                      "哪些变量缺失最严重？", "horizontal bar",
                      list(miss.index), len(self.df),
                      self.caption("缺失率按变量统计"))
        else:
            self.skip("A 数据质量", "哪些变量缺失最严重？", "无缺失值")

        if group:
            labels, vals = top_counts(self.df[group], self.top_n)
            fig, ax = plt.subplots(figsize=(FIG_W, 3.6))
            bar_counts(ax, [self.glabel(x, group) for x in labels], vals,
                       xlabel="文书数（件）")
            self.save(fig, "sample_by_group", "A 数据质量",
                      "样本在主要类别上如何分布？", "bar", [group], int(vals.sum()),
                      self.caption(f"按 {self.vlabel(group)} 统计，仅列前 {self.top_n} 类"))
        if time:
            vc = self.df[time].value_counts().sort_index()
            fig, ax = plt.subplots(figsize=(FIG_W, 3.2))
            bar_counts(ax, [str(x) for x in vc.index], vc.values, xlabel=str(time),
                       ylabel="文书数（件）")
            self.save(fig, "sample_by_time", "A 数据质量",
                      "样本随年份如何变化？", "bar", [time], int(vc.sum()),
                      self.caption(f"按 {self.vlabel(time)} 统计"))
        if region:
            labels, vals = top_counts(self.df[region], self.top_n)
            fig, ax = plt.subplots(figsize=(FIG_W, 3.2))
            bar_counts(ax, labels, vals, xlabel="文书数（件）")
            self.save(fig, "sample_by_region", "A 数据质量",
                      "样本在地区上如何分布？", "bar", [region], int(vals.sum()),
                      self.caption(f"按 {self.vlabel(region)} 统计，仅列前 {self.top_n} 类"))

    def binary_prevalence(self, outcome, binaries):
        cols = []
        for c in binaries:
            if c not in self.df.columns:
                continue
            s = pd.to_numeric(self.df[c], errors="coerce").dropna()
            if len(s) >= self.min_n and 0 < s.mean() < 1:
                cols.append(c)
        if not cols:
            self.skip("A 数据质量", "关键二元变量的发生率是多少？", "没有可用的二元变量")
            return
        cols = cols[:10]
        est, lo, hi, sizes = [], [], [], []
        for c in cols:
            s = pd.to_numeric(self.df[c], errors="coerce").dropna()
            k, n = int(s.sum()), len(s)
            a, b = wilson_ci(k, n)
            est.append(k / n)
            lo.append(a)
            hi.append(b)
            sizes.append(n)
        fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
        bar_counts(ax, [f"{self.vlabel(c)}（n={n}）" for c, n in zip(cols, sizes)],
                   np.array(est) * 100, ylabel="发生率（%）", annotate=False)
        ax.errorbar(np.arange(len(cols)), np.array(est) * 100,
                    yerr=[(np.array(est) - np.array(lo)) * 100,
                          (np.array(hi) - np.array(est)) * 100],
                    fmt="none", ecolor=INK, elinewidth=0.8, capsize=2.2, zorder=3)
        for i, v in enumerate(est):
            ax.text(i, hi[i] * 100 + 2.0, f"{v * 100:.1f}%", ha="center",
                    va="bottom", fontsize=7.8)
        ax.set_ylim(0, 105)
        self.save(fig, "binary_prevalence", "A 数据质量",
                  "关键二元变量的发生率是多少？", "bar + 95%CI",
                  cols, min(sizes),
                  self.caption("横轴标注各变量有效 N；误差线为 95% Wilson CI"))

    def outcome_distribution(self, outcome):
        if not outcome:
            self.skip("B 单变量", "结果变量的分布如何？", "未指定结果变量")
            return
        if self.outcome_kind == "binary":
            y = pd.to_numeric(self.df[outcome], errors="coerce").dropna()
            if y.empty:
                return
            counts = [int((y == 0).sum()), int((y == 1).sum())]
            fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
            bar_counts(ax, [self.glabel(0, outcome), self.glabel(1, outcome)],
                       counts, ylabel="文书数（件）")
            self.save(fig, "outcome_distribution", "B 单变量",
                      "结果变量的两类各有多少？", "bar",
                      [outcome], len(y),
                      self.caption(f"事件率 {counts[1]}/{len(y)} = {counts[1] / len(y) * 100:.1f}%"))
        elif self.outcome_kind == "continuous":
            s = pd.to_numeric(self.df[outcome], errors="coerce").dropna()
            if len(s) < self.min_n:
                self.skip("B 单变量", "结果变量的分布如何？", f"有效 N<{self.min_n}")
                return
            plot_vals, note = self.numeric_display(s)
            fig = plt.figure(figsize=(FIG_W, 3.2))
            gs = fig.add_gridspec(1, 2, width_ratios=[4, 1], wspace=0.08)
            ax = fig.add_subplot(gs[0, 0])
            axb = fig.add_subplot(gs[0, 1], sharey=ax)
            plot_distribution(ax, axb, plot_vals,
                              xlabel=self.vlabel(outcome) + ("（log10）" if note == "log" else ""))
            self.save(fig, "outcome_distribution", "B 单变量",
                      "结果变量的分布是否偏态/多峰/有异常值？", "histogram + box",
                      [outcome], len(s),
                      self.caption("结果变量分布" +
                                   ("；已用 log10 变换" if note == "log" else
                                    "；横轴截断至 P99" if note == "clip" else "")))
            fig, ax = plt.subplots(figsize=(4.8, 3.8))
            r = qq_plot(ax, s)
            self.save(fig, "outcome_qq", "B 单变量",
                      "结果变量是否接近正态分布？", "normal Q-Q",
                      [outcome], len(s),
                      self.caption(f"理论正态分位数 vs 样本分位数；相关系数 r={r:.3f}"))
        else:
            labels, vals = top_counts(self.df[outcome], min(self.top_n, 10))
            if len(labels) < 2:
                return
            fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
            bar_counts(ax, [self.glabel(x, outcome) for x in labels], vals,
                       ylabel="文书数（件）")
            self.save(fig, "outcome_distribution", "B 单变量",
                      "结果变量的各类别如何分布？", "bar",
                      [outcome], int(vals.sum()),
                      self.caption("多分类结果变量的构成"))

    def continuous_outcome_by(self, outcome, group, slug: str, question: str,
                              preserve_order: bool = False):
        if not outcome or not group:
            return
        sub = self.df[[group, outcome]].dropna()
        rows = []
        for level, part in sub.groupby(group):
            y = pd.to_numeric(part[outcome], errors="coerce").dropna()
            if len(y) < self.min_n or len(y) < 2:
                continue
            mean = float(y.mean())
            se = float(y.std(ddof=1) / np.sqrt(len(y)))
            half = float(stats.t.ppf(0.975, len(y) - 1) * se)
            rows.append((str(level), mean, mean - half, mean + half, len(y)))
        if preserve_order:
            try:
                rows.sort(key=lambda x: (float(x[0]), x[0]))
            except ValueError:
                rows.sort(key=lambda x: x[0])
        else:
            rows.sort(key=lambda x: -x[1])
        rows = rows[:self.top_n]
        if len(rows) < 2:
            self.skip("C 双变量", question, f"分组后每组 N≥{self.min_n} 的组不足 2 个")
            return
        means = np.array([x[1] for x in rows])
        lows = np.array([x[2] for x in rows])
        highs = np.array([x[3] for x in rows])
        fig, ax = plt.subplots(figsize=(FIG_W, 3.6))
        bar_counts(ax, [self.glabel(x[0], group) for x in rows],
                   means, ylabel=self.mean_label, annotate=False)
        ax.errorbar(np.arange(len(rows)), means, yerr=[means - lows, highs - means],
                    fmt="none", ecolor=INK, elinewidth=0.8, capsize=2.2, zorder=3)
        # Starting at zero hides small but meaningful group differences; pad
        # around the observed CI range instead.
        pad = max(float(np.max(highs) - np.min(lows)) * 0.12, 0.1)
        ax.set_ylim(max(0, float(np.min(lows)) - pad), float(np.max(highs)) + pad)
        for i, r in enumerate(rows):
            ax.text(i, highs[i] + pad * 0.25, f"{means[i]:.1f}", ha="center",
                    va="bottom", fontsize=7.6)
        self.save(fig, slug, "C 双变量", question, "bar + 95%CI",
                  [group, outcome], int(sum(x[4] for x in rows)),
                  self.caption("柱为均值，误差线为 95% t 区间；"
                               "纵轴按 CI 范围截断而非从 0 开始；"
                               "组间差异参考 Kruskal–Wallis 检验；"
                               f"仅列 n≥{self.min_n} 的组"))

    def categorical_outcome_by(self, outcome, group, slug: str, question: str):
        if not outcome or not group:
            return
        tab = pd.crosstab(self.df[group], self.df[outcome])
        tab = tab.loc[tab.sum(axis=1).sort_values(ascending=False).head(self.top_n).index]
        tab = tab.loc[tab.sum(axis=1) >= self.min_n]
        tab = tab.loc[:, tab.sum(axis=0) > 0]
        if len(tab) < 2 or tab.shape[1] < 2:
            self.skip("C 双变量", question, f"分组后每组 N≥{self.min_n} 的组不足 2 个")
            return
        fig, ax = plt.subplots(figsize=(FIG_W, max(3.4, 0.42 * len(tab) + 1.2)))
        stacked_bar(ax, [self.glabel(x, group) for x in tab.index],
                    [tab[c].values for c in tab.columns],
                    [self.glabel(c, outcome) for c in tab.columns], normalize=True)
        self.save(fig, slug, "C 双变量", question, "100% stacked bar",
                  [group, outcome], int(tab.values.sum()),
                  self.caption(f"堆叠为组内结果类别百分比；仅列 n≥{self.min_n} 的组"))

    # ------------------------------------------------------------------
    # B. Univariate
    # ------------------------------------------------------------------
    def univariate(self, numeric, categorical, treatment):
        if treatment:
            vc = self.df[treatment].dropna().value_counts().sort_index()
            if len(vc):
                fig, ax = plt.subplots(figsize=(FIG_W, 3.2))
                bar_counts(ax, [self.glabel(x, treatment) for x in vc.index], vc.values,
                           xlabel="文书数（件）")
                self.save(fig, "treatment_distribution", "B 单变量",
                          "处理阶段/核心分组的构成如何？", "bar",
                          [treatment], int(vc.sum()),
                          self.caption(f"按 {self.vlabel(treatment)} 统计"))
                if 2 <= len(vc) <= 6:
                    fig, ax = plt.subplots(figsize=(4.8, 3.8))
                    pie_chart(ax, [self.glabel(x, treatment) for x in vc.index],
                              vc.values, sort=False)
                    self.save(fig, "treatment_donut", "B 单变量",
                              "处理阶段/核心分组的占比如何？", "donut",
                              [treatment], int(vc.sum()),
                              self.caption(f"按 {self.vlabel(treatment)} 统计；环形中心为 N"))
        for c in numeric[:6]:
            s = pd.to_numeric(self.df[c], errors="coerce").dropna()
            if len(s) < self.min_n:
                continue
            plot_vals, note = self.numeric_display(s)
            fig = plt.figure(figsize=(FIG_W, 3.2))
            gs = fig.add_gridspec(1, 2, width_ratios=[4, 1], wspace=0.08)
            ax = fig.add_subplot(gs[0, 0])
            axb = fig.add_subplot(gs[0, 1], sharey=ax)
            xlabel = self.vlabel(c) + ("（log10）" if note == "log" else "")
            plot_distribution(ax, axb, plot_vals, xlabel=xlabel)
            self.save(fig, f"dist_{re.sub(r'[^A-Za-z0-9]+', '_', c)}", "B 单变量",
                      f"{self.vlabel(c)} 的分布是否偏态/多峰/有异常值？", "histogram + box",
                      [c], len(s), self.caption(f"{self.vlabel(c)} 的分布；箱线图显示中位数与异常值" +
                                                ("；已用 log10 变换" if note == "log" else
                                                 "；横轴截断至 P99" if note == "clip" else "")))
        for c in categorical[:6]:
            if c == treatment:
                continue
            labels, vals = top_counts(self.df[c], min(self.top_n, 8))
            if len(labels) < 2:
                continue
            fig, ax = plt.subplots(figsize=(FIG_W, 3.2))
            bar_counts(ax, [self.glabel(x, c) for x in labels], vals,
                       xlabel="文书数（件）")
            self.save(fig, f"cat_{re.sub(r'[^A-Za-z0-9]+', '_', c)}", "B 单变量",
                      f"{self.vlabel(c)} 的类别构成如何？", "bar", [c], int(vals.sum()),
                      self.caption(f"{self.vlabel(c)} 的类别构成，仅列前 {min(self.top_n, 8)} 类"))

    # ------------------------------------------------------------------
    # C. Bivariate
    # ------------------------------------------------------------------
    def bivariate(self, group, treatment, outcome, region, trial):
        if outcome and self.outcome_kind == "continuous":
            self.continuous_outcome_by(outcome, group, "outcome_mean_by_group",
                                       "不同类别的结果均值是否不同？")
            self.continuous_outcome_by(outcome, treatment, "outcome_mean_by_treatment",
                                       "不同处理阶段的结果均值如何变化？",
                                       preserve_order=True)
            self.continuous_outcome_by(outcome, region, "outcome_mean_by_region",
                                       "不同地区的结果均值是否不同？")
            self.continuous_outcome_by(outcome, trial, "outcome_mean_by_trial",
                                       "不同审级的结果均值是否不同？")
            outcome = None
        elif outcome and self.outcome_kind == "categorical":
            self.categorical_outcome_by(outcome, group, "outcome_composition_by_group",
                                        "不同类别内部的结果类别构成是否不同？")
            self.categorical_outcome_by(outcome, treatment, "outcome_composition_by_treatment",
                                        "不同处理阶段内部的结果类别构成是否不同？")
            self.categorical_outcome_by(outcome, region, "outcome_composition_by_region",
                                        "不同地区内部的结果类别构成是否不同？")
            self.categorical_outcome_by(outcome, trial, "outcome_composition_by_trial",
                                        "不同审级内部的结果类别构成是否不同？")
            outcome = None
        if outcome and group:
            sub = self.df[[group, outcome]].dropna()
            rows = []
            for g, s in sub.groupby(group):
                y = pd.to_numeric(s[outcome], errors="coerce").dropna()
                if len(y) < self.min_n:
                    continue
                k, n = int(y.sum()), len(y)
                a, b = wilson_ci(k, n)
                rows.append((str(g), k / n, a, b, n))
            rows.sort(key=lambda x: -x[1])
            rows = rows[:self.top_n]
            if rows:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.6))
                bar_counts(ax, [self.glabel(x[0], group) for x in rows],
                           np.array([x[1] for x in rows]) * 100,
                           ylabel=self.rate_pct_label, annotate=False)
                ax.errorbar(np.arange(len(rows)),
                            np.array([x[1] for x in rows]) * 100,
                            yerr=[(np.array([x[1] for x in rows]) - np.array([x[2] for x in rows])) * 100,
                                  (np.array([x[3] for x in rows]) - np.array([x[1] for x in rows])) * 100],
                            fmt="none", ecolor=INK, elinewidth=0.8, capsize=2.2, zorder=3)
                for i, r in enumerate(rows):
                    ax.text(i, r[3] * 100 + 2.0, f"{r[1] * 100:.1f}%", ha="center",
                            va="bottom", fontsize=7.6)
                ax.set_ylim(0, 105)
                self.save(fig, "outcome_by_group", "C 双变量",
                          "不同类别的结果率是否趋同？", "bar + 95%CI",
                          [group, outcome], int(sum(x[4] for x in rows)),
                          self.caption(f"按 {self.vlabel(group)} 分组，仅列前 {self.top_n} 类；误差线为 95% Wilson CI"))
        if outcome and group:
            sub = self.df[[group, outcome]].dropna()
            rows = []
            for g, s in sub.groupby(group):
                y = pd.to_numeric(s[outcome], errors="coerce").dropna()
                if len(y) < self.min_n:
                    continue
                k, n = int(y.sum()), len(y)
                rows.append((str(g), k / n * 100, n))
            if len(rows) >= 2:
                rows.sort(key=lambda x: -x[1])
                fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
                bubble(ax, [r[1] for r in rows], [r[2] for r in rows], [r[2] for r in rows],
                       [self.glabel(r[0], group) for r in rows],
                       xlabel=self.rate_pct_label, ylabel="文书数（件）")
                self.save(fig, "group_rate_bubble", "C 双变量",
                          "类别结果率与样本量之间是什么关系？", "bubble",
                          [group, outcome], int(sum(r[2] for r in rows)),
                          self.caption("横轴为结果率，纵轴为样本量，气泡大小=样本量"))
        if outcome and treatment:
            sub = self.df[[treatment, outcome]].dropna()
            rows = []
            for t, s in sub.groupby(treatment):
                y = pd.to_numeric(s[outcome], errors="coerce").dropna()
                if len(y) < self.min_n:
                    continue
                k, n = int(y.sum()), len(y)
                a, b = wilson_ci(k, n)
                rows.append((t, k / n, a, b, n))
            rows.sort(key=lambda x: x[0])
            if rows:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
                bar_counts(ax, [self.glabel(x[0], treatment) for x in rows],
                           np.array([x[1] for x in rows]) * 100,
                           ylabel=self.rate_pct_label, annotate=False)
                ax.errorbar(np.arange(len(rows)),
                            np.array([x[1] for x in rows]) * 100,
                            yerr=[(np.array([x[1] for x in rows]) - np.array([x[2] for x in rows])) * 100,
                                  (np.array([x[3] for x in rows]) - np.array([x[1] for x in rows])) * 100],
                            fmt="none", ecolor=INK, elinewidth=0.8, capsize=2.2, zorder=3)
                for i, r in enumerate(rows):
                    ax.text(i, r[3] * 100 + 2.0, f"{r[1] * 100:.1f}%", ha="center",
                            va="bottom", fontsize=7.6)
                ax.set_ylim(0, 105)
                self.save(fig, "outcome_by_treatment", "C 双变量",
                          "不同处理阶段的结果率如何变化？", "bar + 95%CI",
                          [treatment, outcome], int(sum(x[4] for x in rows)),
                          self.caption(f"按 {self.vlabel(treatment)} 分组；误差线为 95% Wilson CI"))

        if group and treatment:
            cell = self.df[[group, treatment]].dropna()
            keep_g = cell[group].value_counts()
            keep_g = keep_g[keep_g >= self.min_n].head(self.top_n).index
            keep_t = cell[treatment].value_counts()
            keep_t = keep_t[keep_t >= self.min_n].index
            tab = pd.crosstab(cell[group], cell[treatment])
            tab = tab.loc[tab.index.intersection(keep_g), tab.columns.intersection(keep_t)]
            if len(tab) >= 2 and tab.shape[1] >= 2:
                rowpct = tab.div(tab.sum(axis=1), axis=0) * 100
                fig, ax = plt.subplots(figsize=(FIG_W, max(3.2, 0.42 * len(tab) + 1.2)))
                heatmap(ax, rowpct.values, [self.glabel(x, group) for x in rowpct.index],
                        [self.glabel(x, treatment) for x in rowpct.columns], fmt=".1f")
                ax.set_xlabel(self.vlabel(treatment))
                self.save(fig, "group_treatment_heatmap", "C 双变量",
                          "各类别内部的处理阶段构成是否不同？", "heatmap（行百分比）",
                          [group, treatment], int(tab.values.sum()),
                          self.caption(f"单元格为行内百分比；仅列前 {self.top_n} 类"))
                fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
                stacked_bar(ax, [self.glabel(x, group) for x in tab.index],
                            [tab[c].values for c in tab.columns],
                            [self.glabel(c, treatment) for c in tab.columns], normalize=True)
                self.save(fig, "group_treatment_stacked", "C 双变量",
                          "各类别内部的处理阶段构成是否不同？", "100% stacked bar",
                          [group, treatment], int(tab.values.sum()),
                          self.caption("堆叠为行内百分比"))
                if outcome:
                    piv = self.df.pivot_table(index=group, columns=treatment,
                                              values=outcome, aggfunc="mean")
                    cnt = self.df.pivot_table(index=group, columns=treatment,
                                              values=outcome, aggfunc="count")
                    piv = piv.loc[tab.index.intersection(piv.index)]
                    cnt = cnt.loc[piv.index]
                    piv = piv.where(cnt >= self.min_n)
                    if piv.notna().sum().sum() >= 4:
                        fig, ax = plt.subplots(figsize=(FIG_W, max(3.2, 0.42 * len(piv) + 1.2)))
                        heatmap(ax, piv.values * 100,
                                [self.glabel(x, group) for x in piv.index],
                                [self.glabel(x, treatment) for x in piv.columns], fmt=".1f")
                        ax.set_xlabel(self.vlabel(treatment))
                        self.save(fig, "outcome_group_treatment_heatmap", "C 双变量",
                                  "类别×阶段的结果率是否存在结构差异？", "heatmap",
                                  [group, treatment, outcome], int(cnt.values.sum()),
                                  self.caption(f"单元格为{self.vlabel(outcome)}比例（%）；n<{self.min_n} 的格子留空"))

        if outcome and region:
            sub = self.df[[region, outcome]].dropna()
            rows = []
            for g, s in sub.groupby(region):
                y = pd.to_numeric(s[outcome], errors="coerce").dropna()
                if len(y) < self.min_n:
                    continue
                k, n = int(y.sum()), len(y)
                a, b = wilson_ci(k, n)
                rows.append((str(g), k / n, a, b, n))
            rows.sort(key=lambda x: -x[1])
            if len(rows) >= 2:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.2))
                bar_counts(ax, [self.glabel(x[0], region) for x in rows],
                           np.array([x[1] for x in rows]) * 100,
                           ylabel=self.rate_pct_label, annotate=False)
                ax.errorbar(np.arange(len(rows)), np.array([x[1] for x in rows]) * 100,
                            yerr=[(np.array([x[1] for x in rows]) - np.array([x[2] for x in rows])) * 100,
                                  (np.array([x[3] for x in rows]) - np.array([x[1] for x in rows])) * 100],
                            fmt="none", ecolor=INK, elinewidth=0.8, capsize=2.2, zorder=3)
                for i, r in enumerate(rows):
                    ax.text(i, r[3] * 100 + 2.0, f"{r[1] * 100:.1f}%", ha="center",
                            va="bottom", fontsize=7.6)
                ax.set_ylim(0, 105)
                self.save(fig, "outcome_by_region", "C 双变量",
                          "不同地区的结果率是否不同？", "bar + 95%CI",
                          [region, outcome], int(sum(x[4] for x in rows)),
                          self.caption("误差线为 95% Wilson CI"))
        if outcome and trial:
            sub = self.df[[trial, outcome]].dropna()
            rows = []
            for g, s in sub.groupby(trial):
                y = pd.to_numeric(s[outcome], errors="coerce").dropna()
                if len(y) < self.min_n:
                    continue
                k, n = int(y.sum()), len(y)
                a, b = wilson_ci(k, n)
                rows.append((str(g), k / n, a, b, n))
            rows.sort(key=lambda x: x[0])
            if len(rows) >= 2:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.2))
                bar_counts(ax, [self.glabel(x[0], trial) for x in rows],
                           np.array([x[1] for x in rows]) * 100,
                           ylabel=self.rate_pct_label, annotate=False)
                ax.errorbar(np.arange(len(rows)), np.array([x[1] for x in rows]) * 100,
                            yerr=[(np.array([x[1] for x in rows]) - np.array([x[2] for x in rows])) * 100,
                                  (np.array([x[3] for x in rows]) - np.array([x[1] for x in rows])) * 100],
                            fmt="none", ecolor=INK, elinewidth=0.8, capsize=2.2, zorder=3)
                for i, r in enumerate(rows):
                    ax.text(i, r[3] * 100 + 2.0, f"{r[1] * 100:.1f}%", ha="center",
                            va="bottom", fontsize=7.6)
                ax.set_ylim(0, 105)
                self.save(fig, "outcome_by_trial", "C 双变量",
                          "不同审级的结果率是否不同？", "bar + 95%CI",
                          [trial, outcome], int(sum(x[4] for x in rows)),
                          self.caption("误差线为 95% Wilson CI"))

    def correlations(self, numeric, binaries):
        cols = [c for c in numeric if c in self.df.columns]
        cols += [c for c in binaries if c in self.df.columns and c not in cols]
        cols = cols[:14]
        if len(cols) < 2:
            self.skip("C 双变量", "变量之间是否存在明显相关？", "可用数值变量不足")
            return
        dat = self.df[cols].apply(pd.to_numeric, errors="coerce")
        dat = dat.dropna(axis=1, how="all")
        dat = dat.loc[:, dat.std() > 0]
        if dat.shape[1] < 2 or len(dat) < self.min_n:
            self.skip("C 双变量", "变量之间是否存在明显相关？",
                      f"有效数值列不足或 N<{self.min_n}")
            return
        heat = dat.copy()
        heat.columns = [self.vlabel(c) for c in heat.columns]
        n_complete = int(dat.dropna().shape[0])
        fig, ax = plt.subplots(figsize=(FIG_W, 6.2))
        corr_heatmap(ax, heat)
        self.save(fig, "correlation_heatmap", "C 双变量",
                  "变量之间是否存在明显相关/共线？", "correlation heatmap",
                  list(dat.columns), n_complete,
                  self.caption(f"Pearson 相关（成对删除，完整案例 N={n_complete}）；"
                               "用于筛查共线性与探索性关联"))
        # scatter fits for the most correlated numeric pairs
        num = dat[[c for c in numeric if c in dat.columns]].dropna()
        if len(num.columns) >= 2 and len(num) >= self.min_n:
            corr = num.corr().abs()
            pairs = []
            for i, a in enumerate(num.columns):
                for b in num.columns[i + 1:]:
                    value = corr.loc[a, b]
                    if np.isfinite(value):
                        pairs.append((value, a, b))
            pairs.sort(reverse=True)
            for _, a, b in pairs[:3]:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
                r = scatter_fit(ax, num[a].values, num[b].values,
                                xlabel=self.vlabel(a), ylabel=self.vlabel(b))
                self.save(fig, f"scatter_{re.sub(r'[^A-Za-z0-9]+', '_', a)}_{re.sub(r'[^A-Za-z0-9]+', '_', b)}",
                          "C 双变量", f"{a} 与 {b} 是否相关？", "scatter + OLS",
                          [a, b], len(num), self.caption(f"Pearson r={r:.2f}"))
        # violin by group is done in multivariate()

    # ------------------------------------------------------------------
    # D. Multivariate
    # ------------------------------------------------------------------
    def multivariate(self, numeric, group, treatment):
        if group and numeric:
            for c in numeric[:2]:
                s = pd.to_numeric(self.df[c], errors="coerce")
                sub = pd.DataFrame({group: self.df[group], c: s}).dropna()
                counts = sub[group].value_counts()
                top = counts[counts >= self.min_n].head(5).index
                groups = [sub.loc[sub[group] == g, c].values for g in top]
                if len(groups) < 2:
                    continue
                plot_vals, note = self.numeric_display(sub[c])
                if note == "log":
                    groups = [np.log10(g) for g in groups]
                    ylabel = self.vlabel(c) + "（log10）"
                elif note == "clip":
                    cap = float(sub[c].quantile(0.99))
                    groups = [g[g <= cap] for g in groups]
                    ylabel = self.vlabel(c) + "（截断 P99）"
                else:
                    ylabel = self.vlabel(c)
                fig, ax = plt.subplots(figsize=(FIG_W, 3.6))
                plot_violin(ax, groups, [self.glabel(g, group) for g in top],
                            ylabel=ylabel, rotate=20)
                self.save(fig, f"violin_{re.sub(r'[^A-Za-z0-9]+', '_', c)}", "D 多变量",
                          f"{self.vlabel(c)} 在不同类别间是否不同？", "violin + box + points",
                          [group, c], len(sub),
                          self.caption("小提琴为分布密度，箱线为中位数/IQR，点为抽样散点" +
                                       ("；已用 log10 变换" if note == "log" else
                                        "；已截断至 P99" if note == "clip" else "")))
        if len(numeric) >= 2:
            cols = [c for c in numeric if c in self.df.columns][:4]
            raw = self.df[cols].apply(pd.to_numeric, errors="coerce")
            raw = raw.loc[:, raw.std() > 0].dropna()
            if len(raw) >= self.min_n and len(raw.columns) >= 2:
                cols = list(raw.columns)
                plot = pd.DataFrame(index=raw.index)
                notes = {}
                for c in cols:
                    _, note = self.numeric_display(raw[c])
                    if note == "log":
                        plot[c] = np.log10(raw[c])
                    elif note == "clip":
                        plot[c] = raw[c].clip(upper=float(raw[c].quantile(0.99)))
                    else:
                        plot[c] = raw[c]
                    notes[c] = note
                k = len(cols)
                fig, axes = plt.subplots(k, k, figsize=(FIG_W, 7.0))
                for i, a in enumerate(cols):
                    for j, b in enumerate(cols):
                        ax = axes[i, j]
                        if i == j:
                            ax.hist(plot[a].values, bins=24, color=BLUE, alpha=0.8)
                        else:
                            ax.scatter(plot[b].values, plot[a].values, s=4,
                                       color=BLUE, alpha=0.22, linewidths=0)
                        if i == k - 1:
                            ax.set_xlabel(self.vlabel(b) + ("（log10）" if notes[b] == "log" else
                                                            "（≤P99）" if notes[b] == "clip" else ""),
                                          fontsize=7)
                        if j == 0:
                            ax.set_ylabel(self.vlabel(a) + ("（log10）" if notes[a] == "log" else
                                                            "（≤P99）" if notes[a] == "clip" else ""),
                                          fontsize=7)
                        ax.tick_params(labelsize=6)
                        ax.ticklabel_format(style="plain", axis="both")
                        style_axis(ax, "both")
                self.save(fig, "scatter_matrix", "D 多变量",
                          "数值变量两两之间是否存在非线性/离群结构？", "scatter matrix",
                          cols, len(plot), self.caption("对角线为分布，非对角线为散点；偏态变量做 log10 或 P99 截断"))
        # two binary proportions gap by group (config-driven)
        dumbbell_cols = self.cfg.get("dumbbell") or []
        if (group and isinstance(dumbbell_cols, (list, tuple)) and len(dumbbell_cols) == 2
                and all(c in self.df.columns for c in dumbbell_cols)):
            left_col, right_col = dumbbell_cols
            g = self.df.groupby(group)[[left_col, right_col]].mean()
            g["n"] = self.df.groupby(group).size()
            g = g[g["n"] >= self.min_n].sort_values(left_col, ascending=False).head(self.top_n)
            if len(g) >= 2:
                fig, ax = plt.subplots(figsize=(FIG_W, max(3.2, 0.4 * len(g) + 1.2)))
                dumbbell(ax, [self.glabel(x, group) for x in g.index],
                         g[left_col].values * 100, g[right_col].values * 100,
                         left_label=self.vlabel(left_col), right_label=self.vlabel(right_col))
                ax.set_xlabel("比例（%）")
                self.save(fig, "two_rate_gap_dumbbell", "D 多变量",
                          f"各类别的{self.vlabel(left_col)}与{self.vlabel(right_col)}比例差距多大？", "dumbbell",
                          [group, left_col, right_col], int(g["n"].sum()),
                          self.caption(f"两端分别为{self.vlabel(left_col)}与{self.vlabel(right_col)}比例"))

    def pca(self, numeric, group):
        cols = [c for c in numeric if c in self.df.columns][:10]
        if len(cols) < 3:
            self.skip("D 多变量", "数值变量是否存在潜在结构？", "数值变量不足 3 个")
            return
        dat = self.df[cols].apply(pd.to_numeric, errors="coerce")
        dat = dat.dropna(axis=1, how="all")
        dat = dat.loc[:, dat.std() > 0]
        if len(dat) < self.min_n or dat.shape[1] < 3:
            self.skip("D 多变量", "数值变量是否存在潜在结构？",
                      f"有效数值变量不足或 N<{self.min_n}")
            return
        dat = dat.fillna(dat.median()).astype(float)
        dat = dat.clip(lower=dat.quantile(0.01), upper=dat.quantile(0.99), axis=1)
        dat = dat.loc[:, dat.std() > 0]
        if dat.shape[1] < 3:
            self.skip("D 多变量", "数值变量是否存在潜在结构？", "有效数值变量不足")
            return
        z = (dat - dat.mean()) / dat.std()
        u, s, vt = np.linalg.svd(z.values, full_matrices=False)
        ev = s ** 2 / np.sum(s ** 2) * 100
        fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
        scree_plot(ax, ev[:min(10, len(ev))])
        self.save(fig, "pca_scree", "D 多变量",
                  "前几个主成分解释了多少方差？", "scree + cumulative",
                  cols, len(dat), self.caption("对数值变量标准化后做 PCA"))
        scores = u[:, :2] * s[:2]
        loadings = vt[:2].T
        fig, ax = plt.subplots(figsize=(FIG_W, 4.8))
        if group:
            groups = (self.df.loc[dat.index, group].astype(str)
                      .replace({"nan": "未记载", "None": "未记载", "<NA>": "未记载"}).values)
            for g in pd.Series(groups).value_counts().head(5).index:
                m = groups == g
                ax.scatter(scores[m, 0], scores[m, 1], s=7, alpha=0.28,
                           linewidths=0, label=self.glabel(g, group))
            ax.legend(frameon=False, fontsize=6.8, loc="best")
        else:
            ax.scatter(scores[:, 0], scores[:, 1], s=7, alpha=0.28,
                       color=BLUE, linewidths=0)
        xlo, xhi = np.quantile(scores[:, 0], [0.01, 0.99])
        ylo, yhi = np.quantile(scores[:, 1], [0.01, 0.99])
        xpad = max((xhi - xlo) * 0.18, 0.2)
        ypad = max((yhi - ylo) * 0.18, 0.2)
        ax.set_xlim(xlo - xpad, xhi + xpad)
        ax.set_ylim(ylo - ypad, yhi + ypad)
        scale = 0.9 * min(xhi - xlo, yhi - ylo) / max(float(np.abs(loadings).max()), 1e-9)
        for i, c in enumerate(dat.columns):
            ax.arrow(0, 0, loadings[i, 0] * scale, loadings[i, 1] * scale,
                     color=ORANGE, width=0.002, head_width=0.03,
                     length_includes_head=True, alpha=0.9)
            ax.text(loadings[i, 0] * scale * 1.06, loadings[i, 1] * scale * 1.06,
                    self.vlabel(c), fontsize=6.6, color=INK)
        ax.axhline(0, color=LGRAY, linewidth=0.5)
        ax.axvline(0, color=LGRAY, linewidth=0.5)
        ax.set_xlabel(f"PC1（{ev[0]:.1f}%）")
        ax.set_ylabel(f"PC2（{ev[1]:.1f}%）")
        style_axis(ax, "both")
        self.save(fig, "pca_biplot", "D 多变量",
                  "样本在主轴平面上是否形成类别结构？", "PCA biplot",
                  cols + ([group] if group else []), len(dat),
                  self.caption("点为样本得分，箭头为变量载荷；缺失值中位数填补；仅作探索性展示"))
        k = min(3, vt.shape[0])
        load = vt[:k, :].T
        fig, ax = plt.subplots(figsize=(FIG_W, max(3.0, 0.32 * len(dat.columns) + 1.2)))
        vmax = max(float(np.abs(load).max()), 1e-9)
        heatmap(ax, load, [self.vlabel(c) for c in dat.columns],
                [f"PC{i + 1}" for i in range(k)], fmt=".2f", cmap="RdBu_r",
                vmin=-vmax, vmax=vmax)
        self.save(fig, "pca_loadings", "D 多变量",
                  "哪些变量在主轴上的载荷最高？", "PCA loadings heatmap",
                  list(dat.columns), len(dat),
                  self.caption("单元格为变量在前三个主成分上的载荷；仅作探索性展示"))

    def clustering(self, numeric, group):
        cols = [c for c in numeric if c in self.df.columns][:8]
        if len(cols) < 2:
            self.skip("D 多变量", "样本是否形成自然聚类？", "数值变量不足 2 个")
            return
        dat = self.df[cols + ([group] if group else [])].copy()
        for c in cols:
            dat[c] = pd.to_numeric(dat[c], errors="coerce")
        dat = dat.dropna(subset=cols)
        cols = [c for c in cols if dat[c].std() > 0]
        dat = dat[cols + ([group] if group else [])]
        if len(dat) < self.min_n or len(cols) < 2:
            self.skip("D 多变量", "样本是否形成自然聚类？",
                      f"有效样本不足或数值变量不足（N<{self.min_n}）")
            return
        if len(dat) > 300:
            dat = dat.sample(300, random_state=42)
        z = dat[cols].astype(float)
        z = (z - z.mean()) / z.std(ddof=0).replace(0, 1)
        labs = (dat[group].astype(str)
                .replace({"nan": "未记载", "None": "未记载", "<NA>": "未记载"}).tolist()
                if group else None)
        fig, ax = plt.subplots(figsize=(FIG_W, 4.6))
        dendrogram_plot(ax, z.values, labels=None)
        self.save(fig, "cluster_dendrogram", "D 多变量",
                  "样本/变量是否形成自然聚类？", "dendrogram",
                  cols + ([group] if group else []), len(dat),
                  self.caption("对标准化数值变量做 Ward 层次聚类；最多抽样 300 行；仅作探索性展示"))
        if float(z.duplicated().mean()) > 0.25:
            self.skip("D 多变量", "样本在低维相似性空间中是否分离？",
                      "重复/零值行过多，MDS 坐标会堆叠，信息量低")
            return
        diffs = z.values[:, None, :] - z.values[None, :, :]
        dist = np.sqrt((diffs ** 2).sum(axis=2))
        coords, explained = classical_mds(dist)
        fig, ax = plt.subplots(figsize=(FIG_W, 4.4))
        mds_plot(ax, coords, groups=labs, explained=explained)
        self.save(fig, "cluster_mds", "D 多变量",
                  "样本在低维相似性空间中是否分离？", "classical MDS",
                  cols + ([group] if group else []), len(dat),
                  self.caption("经典 MDS（欧氏距离）；颜色为分组变量；仅作探索性展示"))

    def correspondence(self, group, treatment):
        if not group or not treatment:
            self.skip("G 附录", "类别与处理阶段是否存在对应结构？", "缺少分组或处理变量")
            return
        cell = self.df[[group, treatment]].dropna()
        keep_g = cell[group].value_counts()
        keep_g = keep_g[keep_g >= self.min_n].head(self.top_n).index
        keep_t = cell[treatment].value_counts()
        keep_t = keep_t[keep_t >= self.min_n].index
        tab = pd.crosstab(cell[group], cell[treatment])
        tab = tab.loc[tab.index.intersection(keep_g), tab.columns.intersection(keep_t)]
        if tab.values.sum() < self.min_n or tab.shape[0] < 2 or tab.shape[1] < 2:
            self.skip("G 附录", "类别与处理阶段是否存在对应结构？",
                      f"有效样本不足或组数不足（N<{self.min_n}）")
            return
        p = tab.values / tab.values.sum()
        r = p.sum(axis=1)
        c = p.sum(axis=0)
        s = (p - np.outer(r, c)) / np.sqrt(np.outer(r, c))
        u, sv, vt = np.linalg.svd(s, full_matrices=False)
        row = (u[:, :2] * sv[:2]) / np.sqrt(r)[:, None]
        col = (vt[:2].T * sv[:2]) / np.sqrt(c)[:, None]
        fig, ax = plt.subplots(figsize=(FIG_W, 5.2))
        ax.scatter(row[:, 0], row[:, 1], s=28, color=BLUE, label="类别", zorder=3)
        ax.scatter(col[:, 0], col[:, 1], s=28, color=ORANGE, marker="s", label="阶段", zorder=3)
        for i, lab in enumerate(tab.index):
            ax.text(row[i, 0] + 0.02, row[i, 1] + 0.02, self.glabel(lab, group),
                    fontsize=7, color=BLUE)
        for i, lab in enumerate(tab.columns):
            ax.text(col[i, 0] + 0.02, col[i, 1] + 0.02, self.glabel(lab, treatment),
                    fontsize=7, color=ORANGE)
        ax.axhline(0, color=LGRAY, linewidth=0.5)
        ax.axvline(0, color=LGRAY, linewidth=0.5)
        total_inertia = float(np.sum(sv ** 2))
        ax.set_xlabel(f"维度 1（{sv[0]**2/total_inertia*100:.1f}%）")
        ax.set_ylabel(f"维度 2（{sv[1]**2/total_inertia*100:.1f}%）")
        ax.legend(frameon=False, fontsize=7)
        style_axis(ax, "both")
        self.save(fig, "correspondence_biplot", "G 附录",
                  "类别与处理阶段是否存在对应结构？", "correspondence analysis biplot",
                  [group, treatment], int(tab.values.sum()),
                  self.caption("对称归一化对应分析；仅作探索性展示"))

    def time_trends(self, time, outcome, treatment):
        if not time:
            self.skip("E 时间", "结果如何随年份变化？", "没有时间变量")
            return
        vc = self.df[time].dropna().value_counts().sort_index()
        if len(vc):
            fig, ax = plt.subplots(figsize=(FIG_W, 3.2))
            bar_counts(ax, [str(x) for x in vc.index], vc.values,
                       xlabel=str(time), ylabel="文书数（件）")
            self.save(fig, "sample_trend", "E 时间",
                      "各年份样本量如何变化？", "bar", [time], int(vc.sum()),
                      self.caption("按时间变量统计"))

        if outcome and self.outcome_kind == "binary":
            sub = self.df[[time, outcome]].dropna()
            rows = []
            for y, s in sub.groupby(time):
                v = pd.to_numeric(s[outcome], errors="coerce").dropna()
                if len(v) < self.min_n:
                    continue
                k, n = int(v.sum()), len(v)
                a, b = wilson_ci(k, n)
                rows.append((y, k / n, a, b, n))
            rows.sort()
            if len(rows) >= 2:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
                line_ci(ax, [r[0] for r in rows], [r[1] for r in rows],
                        [r[2] for r in rows], [r[3] for r in rows],
                        xlabel=str(time), ylabel=self.rate_label)
                ax.set_ylim(0, 1)
                self.save(fig, "outcome_trend", "E 时间",
                          f"{self.vlabel(outcome)}比例随年份如何变化？", "line + 95%CI",
                          [time, outcome], int(sum(r[4] for r in rows)),
                          self.caption(f"仅列 n≥{self.min_n} 的年份；误差线为 95% Wilson CI"))
                if len(rows) >= 3:
                    fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
                    control_chart(ax, [r[0] for r in rows], [r[1] for r in rows],
                                  n=[r[4] for r in rows],
                                  center=sum(r[1] * r[4] for r in rows) / sum(r[4] for r in rows),
                                  ylabel=self.rate_label)
                    self.save(fig, "outcome_control", "E 时间",
                              "结果比例是否出现超出 3σ 的异常年份？", "p control chart",
                              [time, outcome], int(sum(r[4] for r in rows)),
                              self.caption("中心线为加权平均比例，控制限为 ±3σ；"
                                           "越界点需结合政策/样本变化解释"))
        elif outcome and self.outcome_kind == "continuous":
            sub = self.df[[time, outcome]].dropna()
            rows = []
            for y, s in sub.groupby(time):
                v = pd.to_numeric(s[outcome], errors="coerce").dropna()
                if len(v) < self.min_n or len(v) < 2:
                    continue
                mean = float(v.mean())
                half = float(stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / np.sqrt(len(v)))
                rows.append((y, mean, mean - half, mean + half, len(v)))
            rows.sort()
            if len(rows) >= 2:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
                line_ci(ax, [r[0] for r in rows], [r[1] for r in rows],
                        [r[2] for r in rows], [r[3] for r in rows],
                        xlabel=str(time), ylabel=self.mean_label)
                self.save(fig, "outcome_trend_mean", "E 时间",
                          f"{self.vlabel(outcome)}均值随年份如何变化？", "line + 95%CI",
                          [time, outcome], int(sum(r[4] for r in rows)),
                          self.caption(f"仅列 n≥{self.min_n} 的年份；误差线为 95% t 区间"))
                if len(rows) >= 3:
                    means = [r[1] for r in rows]
                    fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
                    control_chart(ax, [r[0] for r in rows], means,
                                  center=float(np.mean(means)),
                                  sigma=float(np.std(means, ddof=1)) or 1e-9,
                                  ylabel=self.mean_label)
                    self.save(fig, "outcome_control_mean", "E 时间",
                              "结果均值是否出现超出 3σ 的异常年份？", "X-bar control chart",
                              [time, outcome], int(sum(r[4] for r in rows)),
                              self.caption("中心线为年份均值，控制限为 ±3σ；"
                                           "越界点需结合样本变化解释"))
        elif outcome and self.outcome_kind == "categorical":
            tab = pd.crosstab(self.df[time], self.df[outcome])
            tab = tab.loc[tab.sum(axis=1) >= self.min_n]
            tab = tab.loc[:, tab.sum(axis=0) > 0]
            if len(tab) >= 2 and tab.shape[1] >= 2:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
                stacked_bar(ax, [str(x) for x in tab.index],
                            [tab[c].values for c in tab.columns],
                            [self.glabel(c, outcome) for c in tab.columns], normalize=True)
                ax.set_xlabel(str(time))
                self.save(fig, "outcome_composition_trend", "E 时间",
                          "结果类别构成随年份如何变化？", "100% stacked bar",
                          [time, outcome], int(tab.values.sum()),
                          self.caption(f"堆叠为行内百分比；仅列 n≥{self.min_n} 的年份"))

        if treatment:
            tab = pd.crosstab(self.df[time], self.df[treatment])
            tab = tab.loc[tab.sum(axis=1) >= self.min_n]
            if len(tab) >= 2 and tab.shape[1] >= 2:
                fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
                stacked_bar(ax, [str(x) for x in tab.index],
                            [tab[c].values for c in tab.columns],
                            [self.glabel(c, treatment) for c in tab.columns], normalize=True)
                self.save(fig, "treatment_composition_trend", "E 时间",
                          "处理阶段构成随年份如何变化？", "100% stacked bar",
                          [time, treatment], int(tab.values.sum()),
                          self.caption("堆叠为行内百分比；仅列 n≥%d 的年份" % self.min_n))
                fig, ax = plt.subplots(figsize=(FIG_W, 3.6))
                stacked_area(ax, list(tab.index),
                             [tab[c].values for c in tab.columns],
                             [self.glabel(c, treatment) for c in tab.columns])
                ax.set_xlabel(str(time))
                ax.set_ylabel("构成比例")
                self.save(fig, "treatment_composition_area", "E 时间",
                          "处理阶段构成随年份如何变化？", "100% stacked area",
                          [time, treatment], int(tab.values.sum()),
                          self.caption("面积为行内百分比；仅列 n≥%d 的年份" % self.min_n))

    # ------------------------------------------------------------------
    # F. Model diagnostics
    # ------------------------------------------------------------------
    def model_charts(self, coef_path, pred_path):
        if not coef_path and not pred_path:
            self.skip("F 模型诊断", "模型系数与预测表现如何？",
                      "未提供 --coef 或 --pred；可补充 CSV 后重跑")
            return
        if coef_path:
            try:
                c = read_csv_auto(coef_path)
            except Exception as exc:
                self.skip("F 模型诊断", "模型系数图",
                          f"coef CSV 无法读取: {type(exc).__name__}: {exc}"[:200])
                c = None
        if coef_path and c is not None:
            rename = {x.lower(): x for x in c.columns}
            term = rename.get("term") or rename.get("variable")
            est = rename.get("or") or rename.get("estimate")
            lo = rename.get("ci_low") or rename.get("low")
            hi = rename.get("ci_high") or rename.get("high")
            model = rename.get("model")
            metric_col = rename.get("metric")
            n_col = rename.get("n")
            if term and est and lo and hi:
                c = c.copy()
                for col in (est, lo, hi):
                    c[col] = pd.to_numeric(c[col], errors="coerce")
                c = c[c[[term, est, lo, hi]].notna().all(axis=1)]
                if c.empty:
                    self.skip("F 模型诊断", "模型系数图",
                              "coef CSV 的 estimate/CI 列没有可用数值")
                    groups = []
                else:
                    groups = c.groupby(model) if model else [("model", c)]
                for m, sub in groups:
                    try:
                        metric = str(sub[metric_col].iloc[0]).upper() if metric_col else "OR"
                        log_scale = metric in {"OR", "HR", "RR"}
                        ref = 1.0 if log_scale else 0.0
                        n_model = len(self.df)
                        if n_col and sub[n_col].notna().any():
                            try:
                                n_model = int(float(sub[n_col].iloc[0]))
                            except (TypeError, ValueError):
                                pass
                        term_labels = self.cfg.get("term_labels", {})
                        fig, ax = plt.subplots(figsize=(FIG_W, max(3.2, 0.4 * len(sub) + 1.2)))
                        forest_plot(ax, [term_labels.get(str(x), short_label(x)) for x in sub[term]],
                                    sub[est].values, sub[lo].values, sub[hi].values,
                                    ref=ref, log_scale=log_scale,
                                    xlabel=f"{metric}（95%CI）")
                        self.save(fig, f"forest_{re.sub(r'[^A-Za-z0-9]+', '_', str(m))}",
                                  "F 模型诊断", f"{m} 的系数方向与不确定性如何？",
                                  "forest plot", [term, est, lo, hi], n_model,
                                  f"注：N={n_model:,}；模型 {m}；点为 {metric}，线为 95%CI；"
                                  f"参考线 {metric}={ref:g}；数据来源：分析数据集。")
                    except Exception as exc:
                        self.skip("F 模型诊断", f"{m} 的系数图",
                                  f"无法绘制: {type(exc).__name__}: {exc}"[:200])
            else:
                self.skip("F 模型诊断", "模型系数图", "coef CSV 缺少 term/estimate/ci_low/ci_high")
        if pred_path:
            try:
                p = read_csv_auto(pred_path)
            except Exception as exc:
                self.skip("F 模型诊断", "ROC/校准图",
                          f"pred CSV 无法读取: {type(exc).__name__}: {exc}"[:200])
                p = None
        if pred_path and p is not None:
            ycol = next((c for c in p.columns if c.lower() in {"y_true", "y", "outcome", "label"}), None)
            scol = next((c for c in p.columns if c.lower() in {"y_prob", "prob", "pred", "prediction"}), None)
            if not (ycol and scol):
                self.skip("F 模型诊断", "ROC/校准图", "pred CSV 缺少 y_true/y_prob")
                return
            encoded, label_map = encode_binary(p[ycol])
            if encoded is None:
                self.skip("F 模型诊断", "ROC/校准图",
                          "y_true 不是可识别的二分类标签；请编码为 0/1 或在 CSV 中使用是/否")
                return
            data = pd.DataFrame({"y": encoded, "p": pd.to_numeric(p[scol], errors="coerce")}).dropna()
            if data.empty:
                self.skip("F 模型诊断", "ROC/校准图", "没有有效的 y_true/y_prob 行")
                return
            n_pred = len(data)
            y = data["y"].values
            s = data["p"].values
            if len(np.unique(y)) < 2:
                self.skip("F 模型诊断", "ROC/校准图", "y_true 只有一个类别")
                return
            if float(np.nanmax(s) - np.nanmin(s)) == 0:
                self.skip("F 模型诊断", "ROC/校准图", "预测概率为常数，无法计算 ROC/校准")
                return
            fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
            auc = roc_curve(ax, y, s)
            if np.isfinite(auc):
                self.save(fig, "model_roc", "F 模型诊断",
                          "模型的区分度如何？", "ROC",
                          [ycol, scol], n_pred, self.caption(f"AUC={auc:.3f}"))
            else:
                plt.close(fig)
            fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
            calibration_plot(ax, y, s)
            self.save(fig, "model_calibration", "F 模型诊断",
                      "模型预测概率是否校准？", "calibration curve",
                      [ycol, scol], n_pred,
                      self.caption("按预测概率分箱；对角线为完美校准"))
            fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
            labels = {v: k for k, v in label_map.items()}
            for v, col in [(0, GRAY), (1, BLUE)]:
                vals = s[y == v]
                if len(vals):
                    ax.hist(vals, bins=30, alpha=0.55, color=col,
                            label=f"y={labels.get(v, v)}")
            ax.set_xlabel("预测概率")
            ax.set_ylabel("频数")
            ax.legend(frameon=False)
            style_axis(ax, "y")
            self.save(fig, "model_pred_distribution", "F 模型诊断",
                      "预测概率在两类之间是否分离？", "histogram",
                      [ycol, scol], n_pred, self.caption("按真实类别分组的预测概率分布"))
            fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
            confusion_heatmap(ax, y, s)
            self.save(fig, "model_confusion", "F 模型诊断",
                      "阈值 0.5 下的分类错误主要在哪里？", "confusion matrix",
                      [ycol, scol], n_pred,
                      self.caption("预测概率≥0.5 判为正类；单元格为文书数"))
            fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
            ap = pr_curve(ax, y, s)
            if np.isfinite(ap):
                self.save(fig, "model_pr", "F 模型诊断",
                          "在正类较少时精确率-召回率表现如何？", "precision-recall",
                          [ycol, scol], n_pred, self.caption(f"AP={ap:.3f}；虚线为正类基线"))
            else:
                plt.close(fig)
            fig, ax = plt.subplots(figsize=(FIG_W, 3.4))
            tab = lift_chart(ax, y, s)
            if not tab.empty:
                self.save(fig, "model_lift", "F 模型诊断",
                          "高预测概率组的提升倍数有多大？", "decile lift",
                          [ycol, scol], n_pred,
                          self.caption("按预测概率十分位（D1 最高）；虚线为随机基线"))
            else:
                plt.close(fig)

    def survival(self, cfg: dict):
        tcol = cfg.get("survival_time")
        ecol = cfg.get("survival_event")
        if not tcol or not ecol:
            self.skip("F 模型诊断", "生存/随访时间如何变化？",
                      "未配置 survival_time/survival_event；有随访数据时再启用")
            return
        if tcol not in self.df.columns or ecol not in self.df.columns:
            self.skip("F 模型诊断", "生存/随访时间如何变化？",
                      f"列不存在：{tcol}/{ecol}")
            return
        t = pd.to_numeric(self.df[tcol], errors="coerce")
        e, _ = encode_binary(self.df[ecol])
        if e is None:
            self.skip("F 模型诊断", "生存/随访时间如何变化？",
                      "survival_event 不是可识别的 0/1 或 是/否 标签")
            return
        sub = pd.DataFrame({"t": t, "e": e}).dropna()
        if len(sub) < self.min_n:
            self.skip("F 模型诊断", "生存/随访时间如何变化？", f"有效 N<{self.min_n}")
            return
        group = self.cfg.get("survival_group") or self.cfg.get("group")
        g = (self.df.loc[sub.index, group].astype(str)
             .replace({"nan": "未记载", "None": "未记载", "<NA>": "未记载"})
             if group in self.df.columns else None)
        fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
        kaplan_meier(ax, sub["t"], sub["e"], group=g)
        self.save(fig, "survival_km", "F 模型诊断",
                  "不同组的生存/未再犯概率如何变化？", "Kaplan-Meier",
                  [tcol, ecol] + ([group] if g is not None else []), len(sub),
                  self.caption("阶梯线为 Kaplan–Meier 估计；短竖线为删失点"))

    # ------------------------------------------------------------------
    # G. Appendix
    # ------------------------------------------------------------------
    def appendix(self, group):
        if group:
            labels, vals = top_counts(self.df[group], self.top_n)
            fig, ax = plt.subplots(figsize=(FIG_W, max(3.2, 0.36 * len(labels) + 1.2)))
            pareto(ax, [self.glabel(x, group) for x in labels], vals)
            self.save(fig, "pareto_group", "G 附录",
                      "类别分布是否高度集中？", "Pareto",
                      [group], int(vals.sum()),
                      self.caption("柱为频数，线为累计百分比"))

    def write(self, meta: dict):
        mpath = os.path.join(self.out_dir, "chart_manifest.csv")
        pd.DataFrame(self.manifest).to_csv(mpath, index=False, encoding="utf-8-sig")
        with open(os.path.join(self.out_dir, "chart_pack.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": meta, "charts": self.manifest, "skipped": self.skipped},
                      fh, ensure_ascii=False, indent=2)
        lines = ["# 图表包", "",
                 f"- 数据：`{meta['data']}`",
                 f"- 分析样本：{meta['n']:,}",
                 f"- 图表数：{len(self.manifest)}",
                 f"- 跳过：{len(self.skipped)}",
                 "", "## 图表清单", ""]
        for m in self.manifest:
            lines += [f"### {m['id']} {m['question']}", "",
                      f"- 类型：{m['chart_type']}",
                      f"- 变量：{m['variables']}",
                      f"- N：{m['n']:,}",
                      f"- 文件：`{os.path.basename(m['png'])}` / `{os.path.basename(m['pdf'])}`",
                      f"- 图注：{m['caption']}", ""]
        if self.skipped:
            lines += ["## 跳过项", ""]
            for s in self.skipped:
                lines.append(f"- {s['section']}｜{s['question']}：{s['reason']}")
        with open(os.path.join(self.out_dir, "chart_pack.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return mpath


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a comprehensive chart pack.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", default="output/chart_pack")
    parser.add_argument("--config", default=None)
    parser.add_argument("--coef", default=None, help="CSV: model,term,estimate/or,ci_low,ci_high,p")
    parser.add_argument("--pred", default=None, help="CSV: y_true,y_prob")
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--min-n", type=int, default=10)
    parser.add_argument("--max-categories", type=int, default=12)
    parser.add_argument("--survival-time", default=None, help="follow-up time column for Kaplan-Meier")
    parser.add_argument("--survival-event", default=None, help="event/censor column (1=event, 0=censor)")
    parser.add_argument("--survival-group", default=None, help="group column for Kaplan-Meier")
    parser.add_argument("--tiff", action="store_true", help="also write LZW TIFF")
    args = parser.parse_args()

    if not os.path.isfile(args.data):
        print(f"ERROR: data not found: {args.data}", file=sys.stderr)
        return 2
    if args.config and not os.path.isfile(args.config):
        print(f"ERROR: config not found: {args.config}", file=sys.stderr)
        return 2
    if args.coef and not os.path.isfile(args.coef):
        print(f"ERROR: coef CSV not found: {args.coef}", file=sys.stderr)
        return 2
    if args.pred and not os.path.isfile(args.pred):
        print(f"ERROR: pred CSV not found: {args.pred}", file=sys.stderr)
        return 2
    if args.top_n < 1 or args.min_n < 1:
        print("ERROR: --top-n and --min-n must be at least 1", file=sys.stderr)
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
        try:
            with open(args.config, encoding="utf-8") as fh:
                cfg = json.load(fh)
            if not isinstance(cfg, dict):
                raise ValueError("config must be a JSON object")
        except Exception as exc:
            print(f"ERROR: cannot read config: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    if args.survival_time:
        cfg["survival_time"] = args.survival_time
    if args.survival_event:
        cfg["survival_event"] = args.survival_event
    if args.survival_group:
        cfg["survival_group"] = args.survival_group
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
                          if is_binary(df[c])
                          and 0.05 < float(pd.to_numeric(df[c], errors="coerce").mean()) < 0.95
                          and not is_id_like(c, df[c])]
            if len(candidates) == 1:
                outcome_col = candidates[0]
            elif len(candidates) > 1:
                print("ERROR: cannot infer outcome; candidates: "
                      f"{candidates}. Pass config.outcome", file=sys.stderr)
                return 2
            else:
                print("WARN: no outcome column found; generating descriptive charts only",
                      file=sys.stderr)
                outcome_col = None

    kind = "unknown"
    outcome_map = {}
    if outcome_col:
        kind, encoded, outcome_map, kind_msg = outcome_kind(
            df[outcome_col], args.max_categories, cfg.get("outcome_map"))
        if kind == "unsupported":
            print(f"ERROR: {kind_msg}", file=sys.stderr)
            return 2
        if encoded is not None:
            df[outcome_col] = encoded
        if df[outcome_col].notna().sum() == 0:
            print(f"ERROR: outcome column has no non-missing values: {outcome_col}",
                  file=sys.stderr)
            return 2
        if df[outcome_col].nunique(dropna=True) < 2:
            print(f"ERROR: outcome has fewer than 2 levels: {outcome_col}", file=sys.stderr)
            return 2
        cfg = dict(cfg)
        cfg["outcome"] = outcome_col

    id_col, time_col, group_col, treatment_col, _, numeric, categorical, binaries = \
        role_columns(df, cfg, args.max_categories)
    numeric = [c for c in numeric if c != outcome_col and not is_constant(df[c])]
    categorical = [c for c in categorical if c != outcome_col and not is_constant(df[c])]
    binary_predictors = [c for c in binaries if c != outcome_col
                         and not is_constant(df[c])
                         and not same_values(df[c], df[outcome_col])] if outcome_col else binaries
    if not group_col:
        group_candidates = [c for c in categorical
                            if c != outcome_col and c not in binary_predictors
                            and 2 <= df[c].nunique(dropna=True) <= args.max_categories]
        group_col = next((c for c in group_candidates if df[c].nunique(dropna=True) > 2),
                         group_candidates[0] if group_candidates else None)
    region_col = cfg.get("region") or next((c for c in ["region", "地区"] if c in df.columns), None)
    trial_col = cfg.get("trial") or next((c for c in ["instance_level", "审级"] if c in df.columns), None)

    out_dir = os.path.abspath(args.out)
    formats = ["png", "pdf"] + (["tiff"] if args.tiff else [])
    set_style()
    pack = ChartPack(df, out_dir, cfg, formats, args.top_n, args.min_n)
    pack.set_outcome(outcome_col, kind, outcome_map)

    prevalence_binaries = binary_predictors[:]
    if outcome_col and kind == "binary":
        prevalence_binaries = [outcome_col] + prevalence_binaries

    pack.data_quality(group_col, time_col, region_col)
    pack.binary_prevalence(outcome_col, prevalence_binaries)
    pack.outcome_distribution(outcome_col)
    pack.univariate(numeric, categorical, treatment_col)
    pack.bivariate(group_col, treatment_col, outcome_col, region_col, trial_col)
    corr_numeric = numeric + ([outcome_col] if outcome_col and kind == "continuous"
                              and outcome_col not in numeric else [])
    corr_binaries = binary_predictors + ([outcome_col] if outcome_col and kind in {"binary", "continuous"}
                                         and outcome_col not in binary_predictors else [])
    pack.correlations(corr_numeric, corr_binaries)
    multivariate_numeric = (([outcome_col] if outcome_col and kind == "continuous"
                             and outcome_col not in numeric else []) + numeric)
    pack.multivariate(multivariate_numeric, group_col, treatment_col)
    pack.pca(numeric, group_col)
    pack.clustering(numeric, group_col)
    pack.time_trends(time_col, outcome_col, treatment_col)
    pack.model_charts(args.coef, args.pred)
    pack.survival(cfg)
    pack.correspondence(group_col, treatment_col)
    pack.appendix(group_col)
    if not pack.manifest:
        print("ERROR: no charts could be generated; check data columns and filter",
              file=sys.stderr)
        return 3

    meta = {
        "data": os.path.abspath(args.data), "n": len(df),
        "filter": filter_desc,
        "id": id_col, "time": time_col, "group": group_col,
        "treatment": treatment_col, "outcome": outcome_col,
        "outcome_kind": kind, "outcome_map": outcome_map,
        "numeric": numeric, "categorical": categorical, "binary": binary_predictors,
        "survival_time": cfg.get("survival_time"),
        "survival_event": cfg.get("survival_event"),
        "survival_group": cfg.get("survival_group"),
    }
    mpath = pack.write(meta)
    print(f"charts: {len(pack.manifest)}  skipped: {len(pack.skipped)}")
    print(f"manifest: {mpath}")
    print(f"figures: {pack.fig_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
