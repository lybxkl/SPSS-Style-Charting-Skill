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
import hashlib
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
    short_label as _pubfig_short_label,
    BLUE, ORANGE, GRAY, LGRAY, INK, CATEGORICAL,
)
from analysis_utils import (  # noqa: E402
    apply_filter, encode_binary, is_constant, is_id_like, outcome_kind,
    read_csv_auto, same_values,
)

FIG_W = 15 / 2.54  # 15 cm text width, A4 with standard margins

# Cap on the number of figures a single run may write. The documented default pack
# is ~40-55 charts (references/07-chart-atlas.md §1/§5); --max-charts defaults to
# this ceiling and can only be lowered explicitly.
MAX_CHARTS = 60

N_SCOPES = ("sample", "corpus", "subgroup")

# Manifest columns, v2 order (docs/CONTRACTS.md §3). The first block is mandatory,
# the rest is optional and written whenever it can be measured.
MANIFEST_COLUMNS = [
    "id", "question", "chart_type", "variables", "n", "n_scope",
    "png", "pdf", "caption", "dpi", "px_width", "model_id", "data_hash",
    "tiff", "note", "section", "status", "palette",
]

# Sections as they are written into the manifest; the CLI accepts the letter.
SECTIONS = {
    "A": "A 数据质量",
    "B": "B 单变量",
    "C": "C 双变量",
    "D": "D 多变量",
    "E": "E 时间",
    "F": "F 模型诊断",
    "G": "G 附录",
}

# Chart types whose legend is anchored outside the axes: always reserve headroom.
# "top" legends are re-anchored above the axes; "side" ones (pie/donut) keep the
# position pubfig gives them and only get a right margin when they overflow.
TOP_LEGEND_CHART_TYPES = {"100% stacked bar", "100% stacked area"}
SIDE_LEGEND_CHART_TYPES = {"donut", "pie"}
FORCE_TOP_CHART_TYPES = TOP_LEGEND_CHART_TYPES | SIDE_LEGEND_CHART_TYPES

# Effect measures a coef CSV can declare in its ``metric`` column: ratios live on a
# log axis with a reference line at 1, linear terms (β) on a linear axis at 0.
LOG_METRICS = {"OR", "HR", "RR", "AOR", "ODDS", "RATIO",
               "ODDS RATIO", "HAZARD RATIO", "RISK RATIO"}
LIN_METRICS = {"B", "BETA", "COEF", "COEF.", "β", "Β", "SLOPE", "ESTIMATE", "LINEAR"}

SHORT_CATEGORY = {
    "其他": "其他",
}

# dummy pattern: C(charge_f)[T.水生资源] / charge_f[T.水生资源] / 变量[级别]
_DUMMY_TERM_RE = re.compile(r"^\s*(?P<var>.+?)\s*\[\s*(?:T\.)?\s*(?P<level>.+?)\s*\]\s*$")
_C_WRAPPER_RE = re.compile(r"^C\(\s*(?P<var>[^()]+?)\s*\)$")
_N_TOKEN_RE = re.compile(r"[Nn]\s*[=＝]\s*\d[\d,，]*(?:\s*[→\-–—~]\s*\d[\d,，]*)?")


def short_label(value, col: str = "") -> str:
    """Compact tick/axis label -- one implementation, shared with ``pubfig``.

    The pack only adds patsy's ``C(var)[T.level]`` wrapper handling: ``C()`` is
    stripped, so ``C(charge_f)[T.水生资源]`` and ``charge_f[T.水生资源]`` print the
    same ``charge_f：水生资源``.  Everything else (keeping ``var：level`` instead of
    cutting to 8 characters, never scrubbing a character out of the data, truncating
    only what is really too long) comes from :func:`pubfig.short_label`.  A second
    private copy is exactly what let the two versions drift apart.
    """
    s = str(value).strip()
    if col in {"category", "crime"} and s in SHORT_CATEGORY:
        return SHORT_CATEGORY[s]
    dummy = _DUMMY_TERM_RE.match(s)
    if dummy and dummy.group("level").strip():
        var = _C_WRAPPER_RE.sub(r"\g<var>", dummy.group("var").strip()).strip()
        if var:
            s = f"{var}[{dummy.group('level').strip()}]"
    return _pubfig_short_label(s, col)


def parse_n(value) -> tuple[int | None, str]:
    """Parse a manifest N value into ``(first integer, display text)``.

    CONTRACTS §3 allows an integer (``2713`` / ``"2,713"``), a range
    (``"3111→2713"`` or ``"3111-2713"``, the first integer wins) and an ``N=``
    prefix.  The display text keeps the range so the caption stays informative;
    the integer is what validation compares with the row count.
    """
    if value is None:
        return None, ""
    if isinstance(value, (bool, int, np.integer)):
        return int(value), f"{int(value):,}"
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return int(value), f"{int(value):,}"
    match = re.search(r"\d[\d,，]*(?:\s*[→\-–—~]\s*\d[\d,，]*)?", str(value))
    if not match:
        return None, ""
    display = re.sub(r"\s+", "", match.group(0)).replace("，", ",")
    first = re.match(r"\d[\d,]*", display)
    try:
        value = int(first.group(0).replace(",", ""))
    except (AttributeError, ValueError):
        return None, ""
    if display == first.group(0):
        display = f"{value:,}"          # plain integer / N= prefix: format it
    return value, display


def fill_caption_n(caption: str, display: str) -> str:
    """Rewrite *every* ``N=...`` token in *caption* to the resolved N.

    The old code used ``re.sub(..., count=1)``, so a caption that already carried
    an ``N=`` of its own (e.g. ``完整案例 N=118``) kept a stale value next to the
    rewritten one.
    """
    if not display:
        return caption
    if _N_TOKEN_RE.search(caption):
        return _N_TOKEN_RE.sub(f"N={display}", caption)
    body = caption.strip()
    if not body:
        return f"注：N={display}。"
    prefix = "注：" if body.startswith("注：") else ""
    body = body[len(prefix):].strip().rstrip("。")
    return f"{prefix}N={display}；{body}。" if body else f"{prefix}N={display}。"


def png_pixel_info(path: str) -> tuple[int, int]:
    """Return ``(dpi, pixel_width)`` read back from the saved PNG, ``(0, 0)`` if absent."""
    if not path or not os.path.isfile(path):
        return 0, 0
    try:
        from PIL import Image
        with Image.open(path) as im:
            width = int(im.size[0])
            dpi = im.info.get("dpi") or (0, 0)
        return (int(round(float(dpi[0]))), width) if dpi else (0, width)
    except Exception:
        return 0, 0


def data_fingerprint(df: pd.DataFrame, key_cols: list[str] | None = None) -> str:
    """8-hex md5 over column names, row count and a summary of the key columns.

    Lets a later reader check that a manifest row was produced from the same
    dataset without shipping the data itself.
    """
    digest = hashlib.md5()
    digest.update("|".join(str(c) for c in df.columns).encode("utf-8"))
    digest.update(f"|rows={len(df)}".encode("utf-8"))
    candidates = [c for c in (key_cols or []) if c in df.columns] or list(df.columns)
    for col in candidates[:12]:
        series = df[col]
        numeric = pd.to_numeric(series, errors="coerce")
        n_num = int(numeric.notna().sum())
        if n_num:
            digest.update(f"|{col}:n{n_num}:s{float(numeric.sum()):.6f}".encode("utf-8"))
        else:
            digest.update(f"|{col}:n{int(series.notna().sum())}"
                          f":u{int(series.nunique(dropna=True))}".encode("utf-8"))
    return digest.hexdigest()[:8]


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


# The chart catalogue: one row per chart type this script can emit, in output
# order. `slug` is the manifest slug ("{}" marks a variable/model suffix);
# `--list-charts` prints it and references/07-chart-atlas.md §1 is generated from
# it, so the docs cannot drift from the code.
CHART_CATALOG = [
    ("A", "missingness", "horizontal bar", "哪些变量缺失最严重？", "存在缺失列"),
    ("A", "sample_by_group", "bar", "样本在主要类别上如何分布？", "识别到分组变量"),
    ("A", "sample_by_time", "bar", "样本随年份如何变化？", "识别到时间变量"),
    ("A", "sample_by_region", "bar", "样本在地区上如何分布？", "识别到地区列"),
    ("A", "binary_prevalence", "bar + 95%CI", "关键二元变量的发生率是多少？", "≥1 个可用二元变量"),
    ("B", "outcome_distribution", "bar / histogram + box", "结果变量的分布如何？", "识别到结果变量"),
    ("B", "outcome_qq", "normal Q-Q", "结果变量是否接近正态分布？", "连续结果"),
    ("B", "treatment_distribution", "bar", "处理阶段/核心分组的构成如何？", "识别到处理变量"),
    ("B", "treatment_donut", "donut", "处理阶段/核心分组的占比如何？", "处理变量 2–6 类"),
    ("B", "dist_{}", "histogram + box", "该变量的分布是否偏态/多峰/有异常值？", "前 6 个数值变量"),
    ("B", "cat_{}", "bar", "该变量的类别构成如何？", "前 6 个类别变量"),
    ("C", "outcome_mean_by_{}", "bar + 95%CI", "连续结果的组间均值是否不同？", "连续结果 + 分组/处理/地区/审级"),
    ("C", "outcome_composition_by_{}", "100% stacked bar", "多分类结果的构成是否不同？", "多分类结果 + 分组/处理/地区/审级"),
    ("C", "outcome_by_group", "bar + 95%CI", "不同类别的结果率是否趋同？", "二分类结果"),
    ("C", "group_rate_bubble", "bubble", "类别结果率与样本量是什么关系？", "二分类结果"),
    ("C", "outcome_by_treatment", "bar + 95%CI", "不同处理阶段的结果率如何变化？", "二分类结果 + 处理变量"),
    ("C", "group_treatment_heatmap", "heatmap（行百分比）", "各类别内部的处理阶段构成是否不同？", "分组 + 处理变量"),
    ("C", "group_treatment_stacked", "100% stacked bar", "各类别内部的处理阶段构成是否不同？", "分组 + 处理变量"),
    ("C", "outcome_group_treatment_heatmap", "heatmap", "类别×阶段的结果率是否存在结构差异？", "二分类 + 分组 + 处理"),
    ("C", "outcome_by_region", "bar + 95%CI", "不同地区的结果率是否不同？", "二分类结果 + 地区"),
    ("C", "outcome_by_trial", "bar + 95%CI", "不同审级的结果率是否不同？", "二分类结果 + 审级"),
    ("C", "correlation_heatmap", "correlation heatmap", "变量之间是否存在明显相关/共线？", "≥2 个数值/二元变量"),
    ("C", "scatter_{}_{}", "scatter + OLS", "两个变量是否相关？", "相关性最高的 3 对数值变量"),
    ("D", "violin_{}", "violin + box + points", "该变量在不同类别间是否不同？", "前 2 个数值变量 + 分组"),
    ("D", "scatter_matrix", "scatter matrix", "数值变量两两之间是否存在非线性/离群结构？", "数值变量 ≥2"),
    ("D", "two_rate_gap_dumbbell", "dumbbell", "两类处理比例差距多大？", "config.dumbbell 指定两个 0/1 列"),
    ("D", "pca_scree", "scree + cumulative", "前几个主成分解释了多少方差？", "数值变量 ≥3"),
    ("D", "pca_biplot", "PCA biplot", "样本在主轴平面上是否形成类别结构？", "数值变量 ≥3"),
    ("D", "pca_loadings", "PCA loadings heatmap", "哪些变量在主轴上的载荷最高？", "数值变量 ≥3"),
    ("D", "cluster_dendrogram", "dendrogram", "样本/变量是否形成自然聚类？", "数值变量 ≥2 且 N≥min-n"),
    ("D", "cluster_mds", "classical MDS", "样本在低维相似性空间中是否分离？", "同上且重复行 <25%"),
    ("E", "sample_trend", "bar", "各年份样本量如何变化？", "时间变量"),
    ("E", "outcome_trend", "line + 95%CI", "结果比例随年份如何变化？", "二分类结果"),
    ("E", "outcome_control", "p control chart", "结果比例是否出现超出 3σ 的异常年份？", "二分类结果且 ≥3 个年份"),
    ("E", "outcome_trend_mean", "line + 95%CI", "结果均值随年份如何变化？", "连续结果"),
    ("E", "outcome_control_mean", "X-bar control chart", "结果均值是否出现超出 3σ 的异常年份？", "连续结果且 ≥3 个年份"),
    ("E", "outcome_composition_trend", "100% stacked bar", "结果类别构成随年份如何变化？", "多分类结果"),
    ("E", "treatment_composition_trend", "100% stacked bar", "处理阶段构成随年份如何变化？", "时间 + 处理变量"),
    ("E", "treatment_composition_area", "100% stacked area", "处理阶段构成随年份如何变化？", "时间 + 处理变量"),
    ("F", "forest_{}", "forest plot", "该模型的系数方向与不确定性如何？", "--coef（每模型 1 张）"),
    ("F", "model_roc", "ROC", "模型的区分度如何？", "--pred"),
    ("F", "model_calibration", "calibration curve", "模型预测概率是否校准？", "--pred"),
    ("F", "model_pred_distribution", "histogram", "预测概率在两类之间是否分离？", "--pred"),
    ("F", "model_confusion", "confusion matrix", "阈值 0.5 下的分类错误主要在哪里？", "--pred"),
    ("F", "model_pr", "precision-recall", "正类较少时精确率-召回率表现如何？", "--pred"),
    ("F", "model_lift", "decile lift", "高预测概率组的提升倍数有多大？", "--pred"),
    ("F", "survival_km", "Kaplan-Meier", "不同组的生存/未再犯概率如何变化？", "--survival-time/--survival-event"),
    ("G", "correspondence_biplot", "correspondence analysis biplot", "类别与处理阶段是否存在对应结构？", "分组 + 处理变量"),
    ("G", "pareto_group", "Pareto", "类别分布是否高度集中？", "识别到分组变量"),
]

# Manifest section → letter, for the catalogue table.
SECTION_LETTERS = {name: letter for letter, name in SECTIONS.items()}


def split_multi(values) -> list[str]:
    """Flatten repeated CLI values, splitting each on commas (ASCII or full width)."""
    out: list[str] = []
    for raw in values or []:
        for part in re.split(r"[,，]", str(raw)):
            part = part.strip()
            if part:
                out.append(part)
    return out


def print_catalog(stream=None) -> int:
    stream = stream or sys.stdout
    print(f"auto_chart_pack.py 图型清单：{len(CHART_CATALOG)} 项"
          "（--only 接受 slug、slug 前缀片段或图号 F05）", file=stream)
    print("段\tslug\t图型\t回答的问题\t触发条件", file=stream)
    for letter, slug, chart_type, question, when in CHART_CATALOG:
        print(f"{letter}\t{slug}\t{chart_type}\t{question}\t{when}", file=stream)
    print("", file=stream)
    print("示例：--only pca_biplot,model_roc   --sections C,D   --max-charts 20",
          file=stream)
    return 0


class ChartPack:
    # Manifest N scope used when neither the caller nor the config names one.
    n_scope_default = "sample"
    # model_id written into the manifest when the caller/config supplies none.
    model_id_default = ""

    def __init__(self, df: pd.DataFrame, out_dir: str, cfg: dict, formats: list[str],
                 top_n: int, min_n: int, key_cols: list[str] | None = None):
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
        # manifest v2 provenance
        self.key_cols = list(key_cols or [])
        self.data_hash = data_fingerprint(df, self.key_cols)
        self.n_scope_default = self.norm_scope(
            (cfg or {}).get("n_scope") or type(self).n_scope_default)
        self.model_id_default = str((cfg or {}).get("model_id")
                                    or type(self).model_id_default or "")
        # The categorical cycle the figures draw from, recorded per manifest row so
        # qa_outputs can check grayscale separability without guessing colours.
        palette = (cfg or {}).get("palette") or CATEGORICAL
        self.palette_cell = "|".join(str(c) for c in palette)
        # selection / budgeting
        self.max_charts = None
        self.only_selectors: list[str] = []
        self.wanted_sections: list[str] | None = None
        self._seq = 0
        self.filtered = 0
        self.limited = 0
        self.errors = 0

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

    @staticmethod
    def norm_scope(value) -> str:
        """Coerce *value* to one of CONTRACTS §3's ``n_scope`` values."""
        scope = str(value or "sample").strip().lower()
        if scope in N_SCOPES:
            return scope
        print(f"WARN: unknown n_scope {value!r}; using 'sample'", file=sys.stderr)
        return "sample"

    def configure_filters(self, only=None, sections=None, max_charts=None):
        """Restrict the pack to a subset of charts.

        ``only`` accepts manifest ids (``F05``), slugs (``pca_biplot``), slug
        fragments (``scatter``) and ``prefix*`` wildcards.  ``sections`` accepts
        letters (``A``) or section names (``数据质量``).  Chart ids keep their
        original numbering, so ``--only F05`` still reports ``F05``.  ``max_charts``
        of 0 or a negative number means "no cap".
        """
        self.only_selectors = [str(s).strip() for s in (only or []) if str(s).strip()]
        if sections is not None:
            wanted, unknown = [], []
            for token in split_multi(sections):
                name = self._section_name(token)
                wanted.append(name) if name else unknown.append(token)
            for token in unknown:
                print(f"WARN: unknown --sections value {token!r}; known: "
                      f"{', '.join(SECTIONS)}", file=sys.stderr)
            self.wanted_sections = wanted or None
        if max_charts is not None:
            value = int(max_charts)
            self.max_charts = value if value > 0 else None

    @staticmethod
    def _section_name(token: str) -> str | None:
        text = str(token).strip()
        if not text:
            return None
        if text.upper() in SECTIONS:
            return SECTIONS[text.upper()]
        for name in SECTIONS.values():
            if text == name or text in name:
                return name
        return None

    def _keep(self, cid: str, slug: str, section: str) -> bool:
        if self.wanted_sections is not None and section not in self.wanted_sections:
            return False
        if not self.only_selectors:
            return True
        cid_l, slug_l = cid.lower(), slug.lower()
        for raw in self.only_selectors:
            sel = raw.lower()
            if sel == cid_l or sel == slug_l or sel in slug_l:
                return True
            if sel.endswith("*") and (slug_l.startswith(sel[:-1])
                                      or cid_l.startswith(sel[:-1])):
                return True
        return False

    def ok_charts(self) -> list[dict]:
        return [m for m in self.manifest if m.get("status") == "ok"]

    def status_counts(self) -> dict:
        counts = {"ok": 0, "skipped": 0, "error": 0}
        for row in self.manifest:
            status = str(row.get("status", ""))
            if status == "ok":
                counts["ok"] += 1
            elif status.startswith("skipped"):
                counts["skipped"] += 1
            elif status.startswith("error"):
                counts["error"] += 1
        return counts

    def rel_path(self, path: str) -> str:
        """Manifest artifact path: relative to the manifest directory, POSIX style.

        The manifest then survives ``mv output/chart_pack other_machine`` -- the
        figure is still at ``figures/fig01_x.png`` next to the manifest it was
        listed in.  A path on another drive cannot be made relative, so it is
        written as-is (POSIX separators) rather than raising.
        """
        if not path:
            return ""
        try:
            rel = os.path.relpath(os.path.abspath(path),
                                  os.path.abspath(self.out_dir))
        except ValueError:                       # different drive on Windows
            return str(path).replace("\\", "/")
        return rel.replace("\\", "/")

    def save(self, fig, slug: str, section: str, question: str, chart_type: str,
             variables: list[str], n=None, caption: str = "", note: str = "",
             n_scope: str | None = None, model_id: str | None = None,
             extra: dict | None = None):
        """Write one figure and its manifest-v2 row.

        ``n`` accepts what CONTRACTS §3 allows: an int, ``"2,713"``, a range such as
        ``"3111→2713"`` (the first integer is stored, the range stays in the
        caption) or an ``N=2713`` prefixed string.  ``n_scope`` defaults to the
        pack's ``n_scope_default`` (normally ``sample``); ``corpus`` is the only
        scope that may report an ``n`` larger than the number of data rows.

        ``extra`` carries chart-specific facts (e.g. a forest plot's ``metric`` and
        ``rows_dropped``): they land in ``chart_pack.json`` and the Markdown digest
        but are not added to the CSV, whose columns are fixed by the contract.

        A figure that cannot be produced is still recorded: ``n<=0`` or an
        ``n``-vs-row-count violation becomes a manifest row whose ``status`` says
        why, instead of vanishing without a trace.
        """
        self._seq += 1
        cid = f"F{self._seq:02d}"
        if not self._keep(cid, slug, section):
            self.filtered += 1
            plt.close(fig)
            return
        if self.max_charts is not None and len(self.ok_charts()) >= self.max_charts:
            self.limited += 1
            plt.close(fig)
            return

        value, display = parse_n(n if n is not None else len(self.df))
        scope = self.norm_scope(n_scope or self.n_scope_default)
        row = {
            "id": cid, "section": section, "question": question,
            "chart_type": chart_type,
            "variables": "; ".join(str(v) for v in variables),
            "n": value if value is not None else "",
            "n_scope": scope, "png": "", "pdf": "", "tiff": "",
            "caption": fill_caption_n(caption, display or f"{len(self.df):,}"),
            "note": note, "dpi": "", "px_width": "",
            "model_id": model_id or self.model_id_default,
            "data_hash": self.data_hash, "status": "ok",
            # The cycle these figures draw from; qa_outputs checks it for
            # grayscale separability, so it has to be recorded per row.
            "palette": self.palette_cell,
        }
        if extra:
            row.update({str(k): v for k, v in extra.items()})

        if value is None:
            return self._record_skip(fig, row, "skipped: n 无法解析")
        if value <= 0:
            return self._record_skip(fig, row, "skipped: n<=0", stderr=False)
        if value > len(self.df) and scope != "corpus":
            reason = (f"error: n={value:,} > 数据行数 {len(self.df):,}"
                      f"（n_scope={scope}；语料级图请用 n_scope='corpus'）")
            self.errors += 1
            print(f"ERROR: {row['id']} {slug}: {reason}", file=sys.stderr)
            row["status"] = reason
            self.manifest.append(row)
            plt.close(fig)
            return

        name = f"fig{self._seq:02d}_{slug}"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fig.tight_layout(pad=0.4)
        except Exception:
            pass
        try:
            before_right = float(fig.subplotpars.right)
            lift = chart_type in TOP_LEGEND_CHART_TYPES or slug.startswith("stacked")
            top = self.adjust(fig, force=chart_type in FORCE_TOP_CHART_TYPES, lift=lift)
            note_parts = [note.strip(), f"top={top:.3f}"]
            after_right = float(fig.subplotpars.right)
            if abs(after_right - before_right) > 1e-6:
                note_parts.append(f"right={after_right:.3f}")
            row["note"] = "; ".join(x for x in note_parts if x)
            paths = save_fig(fig, self.fig_dir, name, formats=self.formats)
        except Exception as exc:                 # 一张图失败不该毁掉整包
            reason = f"error: {type(exc).__name__}: {exc}"[:240]
            self.errors += 1
            row["status"] = reason
            self.manifest.append(row)
            print(f"ERROR: {row['id']} {slug}: {reason}", file=sys.stderr)
            try:
                plt.close(fig)
            except Exception:
                pass
            return
        by_ext = {os.path.splitext(p)[1].lower().lstrip("."): p for p in paths}
        dpi, px_width = png_pixel_info(by_ext.get("png", ""))
        row.update({
            "png": self.rel_path(by_ext.get("png", "")),
            "pdf": self.rel_path(by_ext.get("pdf", "")),
            "tiff": self.rel_path(by_ext.get("tiff", "")),
            "dpi": dpi or "", "px_width": px_width or "",
        })
        self.manifest.append(row)

    def _record_skip(self, fig, row: dict, reason: str, stderr: bool = True):
        """Keep a manifest row for a chart that was not produced, and say so."""
        row["status"] = reason
        self.manifest.append(row)
        self.skip(row["section"], row["question"], reason)
        if stderr:
            print(f"WARN: {row['id']} {row['question']}: {reason}", file=sys.stderr)
        else:
            print(f"skip {row['id']} {row['question']}: {reason}")
        plt.close(fig)

    def adjust(self, fig, top: float | None = None, force: bool = False,
               lift: bool = False, pad: float = 0.008,
               min_top: float = 0.55, passes: int = 4) -> float:
        """Reserve canvas margin for a legend that lives outside the axes.

        ``tight_layout`` only accounts for artists *inside* the axes, so a legend
        anchored above them (``stacked_bar``/``stacked_area``) is either clipped by
        the figure edge or -- when its anchor keeps it on the canvas -- drawn on
        top of the bars.  CONTRACTS §7 bans ``bbox_inches="tight"`` (it silently
        lowers the DPI), so the margin has to come from shrinking the axes:
        ``fig.subplots_adjust(top=...)`` and, for a legend parked beside the axes
        (``pie_chart``), ``right=...``.

        ``lift`` re-anchors a top legend to sit just above the axes instead of over
        the data; ``force`` guarantees a margin even when the first measurement
        finds no overflow (stacked/pie/donut are the known offenders).

        Returns the resulting ``fig.subplotpars.top`` for the manifest ``note``.
        """
        if top is not None:
            fig.subplots_adjust(top=max(min_top, min(0.98, float(top))))
            return float(fig.subplotpars.top)
        if lift:
            for ax in fig.axes:
                self._lift_legend(ax)
        reserved = False
        for _ in range(max(1, int(passes))):
            cur_top = float(fig.subplotpars.top)
            cur_right = float(fig.subplotpars.right)
            dx, dy = self._legend_overflow(fig)
            new_top, new_right = cur_top, cur_right
            if dy > 1e-3:
                new_top = cur_top - (dy + pad) * 1.2
            elif force and not reserved:
                new_top = cur_top - 0.10      # flat margin for known offenders
            if dx > 1e-3:
                new_right = cur_right - (dx + pad) * 1.2
            new_top = max(min_top, min(cur_top, new_top))
            new_right = max(0.55, min(cur_right, new_right))
            if new_top >= cur_top - 1e-6 and new_right >= cur_right - 1e-6:
                break
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fig.subplots_adjust(top=new_top, right=new_right)
            reserved = True
        return float(fig.subplotpars.top)

    @staticmethod
    def _lift_legend(ax) -> None:
        """Anchor an axes legend just *above* the axes so it never covers data."""
        legend = ax.get_legend()
        if legend is None:
            return
        try:
            legend.set_loc("lower center")
            legend.set_bbox_to_anchor((0.5, 1.012), transform=ax.transAxes)
        except Exception:
            pass

    @staticmethod
    def _legend_overflow(fig) -> tuple[float, float]:
        """How far (figure fraction) an axes-external legend sticks out.

        Returns the raw ``(dx, dy)`` overhang past the canvas edge, so a legend
        that merely touches the edge is not treated as a layout problem.  A legend
        entirely inside its axes is skipped -- that is an ordinary in-axes legend,
        which ``tight_layout`` already accounts for.
        """
        entries = [(None, lg) for lg in getattr(fig, "legends", [])]
        for ax in fig.axes:
            legend = ax.get_legend()
            if legend is not None:
                entries.append((ax, legend))
        if not entries:
            return 0.0, 0.0
        try:
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
        except Exception:
            return 0.0, 0.0
        inv = fig.transFigure.inverted()
        dx = dy = 0.0
        for ax, legend in entries:
            try:
                box = legend.get_window_extent(renderer).transformed(inv)
                if ax is not None:
                    ax_box = ax.get_window_extent(renderer).transformed(inv)
                    if (float(box.y1) <= float(ax_box.y1) + 1e-6
                            and float(box.x1) <= float(ax_box.x1) + 1e-6):
                        continue          # inside the axes: tight_layout saw it
            except Exception:
                continue
            dx = max(dx, float(box.x1) - 1.0)
            dy = max(dy, float(box.y1) - 1.0)
        return max(0.0, dx), max(0.0, dy)

    def skip(self, section: str, question: str, reason: str):
        self.skipped.append({"section": section, "question": question, "reason": reason})

    def caption(self, extra: str = "", n: int | None = None) -> str:
        parts = [f"N={int(n if n is not None else len(self.df)):,}"]
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
        # One chart, up to 10 variables, each with its own valid N: there is no
        # single sample size. Report the span with n_scope="subgroup" instead of
        # a bare min(), which read as if the whole chart used that N.
        n_span = min(sizes) if min(sizes) == max(sizes) else f"{min(sizes)}→{max(sizes)}"
        self.save(fig, "binary_prevalence", "A 数据质量",
                  "关键二元变量的发生率是多少？", "bar + 95%CI",
                  cols, n_span,
                  self.caption("横轴标注各变量有效 N；误差线为 95% Wilson CI"),
                  note=f"per-variable n {min(sizes)}-{max(sizes)}",
                  n_scope="subgroup")

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
            fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
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
                    fig, ax = plt.subplots(figsize=(FIG_W, 3.8))
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
                                          fontsize=7.4)
                        if j == 0:
                            ax.set_ylabel(self.vlabel(a) + ("（log10）" if notes[a] == "log" else
                                                            "（≤P99）" if notes[a] == "clip" else ""),
                                          fontsize=7.4)
                        # 7.4 pt 是排版硬下限，网格里靠"少画刻度"腾地方而不是缩字：
                        # 只保留外圈刻度标签、每轴最多 3 个刻度。
                        ax.tick_params(labelsize=7.4)
                        if k >= 4:
                            ax.locator_params(axis="both", nbins=3)
                        if i < k - 1:
                            ax.tick_params(labelbottom=False)
                        if j > 0:
                            ax.tick_params(labelleft=False)
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
            ax.legend(frameon=False, fontsize=7.4, loc="best")
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
                    self.vlabel(c), fontsize=7.4, color=INK)
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
        inertia = sv ** 2
        total_inertia = float(inertia.sum())
        question = "类别与处理阶段是否存在对应结构？"
        if not np.isfinite(total_inertia) or total_inertia <= 0:
            self.skip("G 附录", question, "对应分析总惰性为零（行与列完全独立），无结构可展示")
            return
        # 只有一个非平凡维度时二维双标图没有意义：第二维奇异值退化为
        # ~1e-17 会让 y 轴数据跨度变成 1e-16 量级，文本坐标在 600 dpi 下
        # 溢出 int64，matplotlib 在 _set_transform 里直接抛 TypeError。
        if sv.size < 2 or inertia[1] / total_inertia < 1e-6:
            share = float(inertia[1] / total_inertia) if sv.size >= 2 else 0.0
            self.skip("G 附录", question,
                      f"对应分析第二维退化（第二维仅占惰性 {share:.2e}，"
                      f"第一维 {(inertia[0]/total_inertia*100):.1f}%），二维双标图无统计意义")
            return
        row = (u[:, :2] * sv[:2]) / np.sqrt(r)[:, None]
        col = (vt[:2].T * sv[:2]) / np.sqrt(c)[:, None]
        if not (np.isfinite(row).all() and np.isfinite(col).all()):
            self.skip("G 附录", question, "对应分析坐标含非有限值，跳过绘图")
            return
        fig, ax = plt.subplots(figsize=(FIG_W, 5.2))
        ax.scatter(row[:, 0], row[:, 1], s=28, color=BLUE, label="类别", zorder=3)
        ax.scatter(col[:, 0], col[:, 1], s=28, color=ORANGE, marker="s", label="阶段", zorder=3)
        for i, lab in enumerate(tab.index):
            ax.text(row[i, 0] + 0.02, row[i, 1] + 0.02, self.glabel(lab, group),
                    fontsize=7.4, color=BLUE)
        for i, lab in enumerate(tab.columns):
            ax.text(col[i, 0] + 0.02, col[i, 1] + 0.02, self.glabel(lab, treatment),
                    fontsize=7.4, color=ORANGE)
        ax.axhline(0, color=LGRAY, linewidth=0.5)
        ax.axvline(0, color=LGRAY, linewidth=0.5)
        # 显式给定范围：文本不参与自动缩放，若某轴数据跨度极小，
        # 自动缩放会留下一个数值上退化（~1e-16）的窗口。
        for setter, values in ((ax.set_xlim, np.concatenate([row[:, 0], col[:, 0]])),
                               (ax.set_ylim, np.concatenate([row[:, 1], col[:, 1]]))):
            lo, hi = float(np.min(values)), float(np.max(values))
            pad = (hi - lo) * 0.08 if hi > lo else 0.05
            setter(lo - pad, hi + pad)
        ax.set_xlabel(f"维度 1（{sv[0]**2/total_inertia*100:.1f}%）")
        ax.set_ylabel(f"维度 2（{sv[1]**2/total_inertia*100:.1f}%）")
        ax.legend(frameon=False, fontsize=7.4)
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
            rename = {str(x).lower().replace(" ", "_"): x for x in c.columns}

            def pick(*names):
                return next((rename[n] for n in names if n in rename), None)

            term = pick("term", "variable", "coef_name", "name")
            model = pick("model")
            metric_col = pick("metric")
            n_col = pick("n")
            # Two column families can coexist in one file when the stats layer fits
            # logit and OLS models: ``or/or_low/or_high`` (ratio scale, log axis) and
            # ``beta/ci_low/ci_high`` (linear scale).  The old code chose one family
            # for the whole file, so an OLS row whose ``or`` was empty got filtered
            # out and the forest plot silently lost half the models.
            generic_lo = pick("ci_low", "low", "ci_lower", "lcl")
            generic_hi = pick("ci_high", "high", "ci_upper", "ucl")
            log_family = (pick("or", "hr", "rr"),
                          pick("or_low", "hr_low", "rr_low") or generic_lo,
                          pick("or_high", "hr_high", "rr_high") or generic_hi)
            lin_family = (pick("beta", "estimate", "coef", "b"), generic_lo, generic_hi)
            log_label = ("OR" if pick("or") else "HR" if pick("hr")
                         else "RR" if pick("rr") else "OR")

            def numbers(row, cols) -> list[float] | None:
                """[est, lo, hi] if this row fills all three columns, else None."""
                if not all(cols):
                    return None
                values = []
                for col in cols:
                    try:
                        value = pd.to_numeric(row.get(col), errors="coerce")
                    except Exception:
                        return None
                    if pd.isna(value):
                        return None
                    values.append(float(value))
                return values

            def resolve(row) -> tuple[str, str, list[float] | None]:
                """(scale, metric label, [est, lo, hi]) for one coefficient row.

                A ``metric`` cell wins; otherwise the family this row actually fills
                decides.  Either way the row is kept when *any* family is complete,
                so mixed logit/OLS files no longer lose their OLS rows.
                """
                declared = ""
                if metric_col is not None:
                    raw = row.get(metric_col)
                    if pd.notna(raw):
                        declared = str(raw).strip()
                upper = declared.upper()
                attempts: list[tuple[str, str]] = []
                if upper in LOG_METRICS:
                    attempts.append(("log", upper))
                elif upper in LIN_METRICS:
                    attempts.append(("lin", "β"))
                for attempt in (("log", log_label), ("lin", "β")):
                    if attempt not in attempts:
                        attempts.append(attempt)
                for scale, label in attempts:
                    values = numbers(row, log_family if scale == "log" else lin_family)
                    if values:
                        return scale, label, values
                return "", declared.upper(), None

            if term and any(all(family) for family in (log_family, lin_family)):
                records, dropped_by_model = [], {}
                for _, row in c.iterrows():
                    scale, metric, values = resolve(row)
                    term_text = row.get(term)
                    if values is None or pd.isna(term_text):
                        key = str(row[model]) if model else "model"
                        dropped_by_model[key] = dropped_by_model.get(key, 0) + 1
                        continue
                    n_value = (pd.to_numeric(row.get(n_col), errors="coerce")
                               if n_col is not None else np.nan)
                    records.append({
                        "term": str(term_text), "scale": scale, "metric": metric,
                        "model": str(row[model]) if model else "model",
                        "est": values[0], "lo": values[1], "hi": values[2], "n": n_value,
                    })
                if not records:
                    self.skip("F 模型诊断", "模型系数图",
                              "coef CSV 的 estimate/CI 列没有可用数值")
                else:
                    tidy = pd.DataFrame(records)
                    per_model_scales = tidy.groupby("model")["scale"].nunique()
                    term_labels = self.cfg.get("term_labels", {})
                    for (m, scale), sub in tidy.groupby(["model", "scale"], sort=False):
                        try:
                            metric = str(sub["metric"].iloc[0]) or (
                                "OR" if scale == "log" else "β")
                            log_scale = scale == "log"
                            ref = 1.0 if log_scale else 0.0
                            n_model = len(self.df)
                            if sub["n"].notna().any():
                                try:
                                    n_model = int(float(sub["n"].dropna().iloc[0]))
                                except (TypeError, ValueError):
                                    pass
                            # n comes from the coef CSV (model rows), not from the data
                            # rows: when it exceeds them the scope is not row-level.
                            n_scope = "sample" if n_model <= len(self.df) else "corpus"
                            rows_dropped = int(dropped_by_model.get(str(m), 0))
                            slug = f"forest_{re.sub(r'[^A-Za-z0-9]+', '_', str(m))}"
                            if int(per_model_scales.get(m, 1)) > 1:
                                slug += "_" + (re.sub(r"[^A-Za-z0-9]+", "", metric.lower())
                                               or scale)
                            fig, ax = plt.subplots(
                                figsize=(FIG_W, max(3.2, 0.4 * len(sub) + 1.2)))
                            forest_plot(ax,
                                        [term_labels.get(str(x), short_label(x))
                                         for x in sub["term"]],
                                        sub["est"].values, sub["lo"].values,
                                        sub["hi"].values,
                                        ref=ref, log_scale=log_scale,
                                        xlabel=f"{metric}（95%CI）")
                            family = log_family if log_scale else lin_family
                            caption = (f"注：N={n_model:,}；模型 {m}；点为 {metric}，线为 95%CI；"
                                       f"参考线 {metric}={ref:g}；数据来源：分析数据集。")
                            if rows_dropped:
                                caption = (caption[:-1] +
                                           f"（{rows_dropped} 行缺 estimate/CI，未绘）。")
                            self.save(fig, slug, "F 模型诊断",
                                      f"{m} 的系数方向与不确定性如何？", "forest plot",
                                      [term, family[0], family[1], family[2]], n_model,
                                      caption, n_scope=n_scope, model_id=str(m),
                                      extra={"metric": metric, "rows_plotted": len(sub),
                                             "rows_dropped": rows_dropped})
                        except Exception as exc:
                            self.skip("F 模型诊断", f"{m} 的系数图",
                                      f"无法绘制: {type(exc).__name__}: {exc}"[:200])
            else:
                self.skip("F 模型诊断", "模型系数图",
                          "coef CSV 缺少 term 与 estimate/OR/beta 及 ci_low/ci_high"
                          "（也接受 or/or_low/or_high、low/high）")
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
        try:
            kaplan_meier(ax, sub["t"], sub["e"], group=g)
        except Exception as exc:
            plt.close(fig)
            self.skip("F 模型诊断", "生存/随访时间如何变化？",
                      f"无法绘制 Kaplan-Meier: {type(exc).__name__}: {exc}"[:200])
            return
        self.save(fig, "survival_km", "F 模型诊断",
                  "不同组的生存/未再犯概率如何变化？", "Kaplan-Meier",
                  [tcol, ecol] + ([group] if g is not None else []), len(sub),
                  self.caption("阶梯线为 Kaplan–Meier 估计；短竖线为删失点",
                               n=len(sub)))

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
        frame = pd.DataFrame(self.manifest)
        if not frame.empty:
            frame = frame.reindex(columns=[c for c in MANIFEST_COLUMNS if c in frame.columns])
        frame.to_csv(mpath, index=False, encoding="utf-8-sig")
        # ``counts.skipped`` counts manifest rows; ``skipped_total`` also counts the
        # pre-flight skips (no figure was ever drawn, e.g. missing --coef), so the
        # JSON and the Markdown headline cannot tell different stories.
        counts = self.status_counts()
        counts["skipped_total"] = len(self.skipped)
        with open(os.path.join(self.out_dir, "chart_pack.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": meta, "charts": self.manifest, "skipped": self.skipped,
                       "counts": counts}, fh, ensure_ascii=False, indent=2)
        lines = ["# 图表包", "",
                 f"- 数据：`{meta.get('data', '')}`",
                 f"- 分析样本：{int(meta.get('n') or 0):,}",
                 f"- 图表数：{counts['ok']}",
                 f"- manifest 行数：{len(self.manifest)}",
                 f"- 跳过：{len(self.skipped)}（其中 {counts['skipped']} 条记入 manifest）",
                 f"- 数据指纹（data_hash）：`{self.data_hash}`",
                 "", "## 图表清单", ""]
        for m in self.manifest:
            n_text = f"{m['n']:,}" if isinstance(m.get("n"), int) else "—"
            lines += [f"### {m['id']} {m['question']}", "",
                      f"- 类型：{m['chart_type']}",
                      f"- 变量：{m['variables']}",
                      f"- N：{n_text}（n_scope={m.get('n_scope') or 'sample'}）",
                      f"- 状态：{m.get('status', 'ok')}"]
            if m.get("metric") or m.get("rows_dropped") is not None:
                extra_bits = [f"标度：{m.get('metric') or '—'}"]
                if m.get("rows_plotted") is not None:
                    extra_bits.append(f"绘制行 {m['rows_plotted']}")
                extra_bits.append(f"未绘行 {m.get('rows_dropped', 0)}")
                lines += ["- " + "；".join(extra_bits)]
            if m.get("png"):
                lines += [f"- 文件：`{os.path.basename(m['png'])}` / "
                          f"`{os.path.basename(m.get('pdf', ''))}`"]
            lines += [f"- 图注：{m['caption']}", ""]
        if self.skipped:
            lines += ["## 跳过项", ""]
            for s in self.skipped:
                lines.append(f"- {s['section']}｜{s['question']}：{s['reason']}")
        with open(os.path.join(self.out_dir, "chart_pack.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return mpath


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a comprehensive chart pack.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("常规产出约 40–55 张图（见 references/07-chart-atlas.md）；"
                f"--max-charts 默认 {MAX_CHARTS}，只会更少不会更多。\n"
                "用 --list-charts 查看全部图型，再用 --only / --sections 挑子集。"))
    parser.add_argument("--data", default=None,
                        help="analysis CSV（--list-charts 时可省略）")
    parser.add_argument("--out", default="output/chart_pack")
    parser.add_argument("--config", default=None)
    parser.add_argument("--coef", default=None,
                        help="CSV: model,term,estimate/OR/beta,ci_low/ci_high,p"
                             "（or/or_low/or_high 与 beta/ci_low/ci_high 均可）")
    parser.add_argument("--pred", default=None, help="CSV: y_true,y_prob")
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--min-n", type=int, default=10)
    parser.add_argument("--max-categories", type=int, default=12)
    parser.add_argument("--only", action="append", metavar="IDS",
                        help="只产出这些图：图号（F05）、slug（pca_biplot）、"
                             "片段（scatter、model_*）；逗号分隔，可重复")
    parser.add_argument("--sections", action="append", metavar="NAMES",
                        help="只产出这些段：A,B,… 或段名（数据质量）；逗号分隔，可重复")
    parser.add_argument("--max-charts", type=int, default=MAX_CHARTS, metavar="N",
                        help=f"最多产出多少张图（默认 {MAX_CHARTS}；"
                             "常规包约 40–55 张，调小可加快试跑）；"
                             "0 或负数 = 不限制")
    parser.add_argument("--n-scope", choices=N_SCOPES, default=None,
                        help="manifest 的 n_scope 默认值；corpus 允许 n>数据行数的"
                             "语料级/漏斗类图（缺省 sample，config.n_scope 可覆盖）")
    parser.add_argument("--list-charts", action="store_true",
                        help="打印可用图型清单后退出")
    parser.add_argument("--survival-time", default=None, help="follow-up time column for Kaplan-Meier")
    parser.add_argument("--survival-event", default=None, help="event/censor column (1=event, 0=censor)")
    parser.add_argument("--survival-group", default=None, help="group column for Kaplan-Meier")
    parser.add_argument("--tiff", dest="tiff", action="store_true", default=True,
                        help="写 LZW TIFF（默认开启；这是默认行为，保留该开关只为兼容旧命令）")
    parser.add_argument("--no-tiff", dest="tiff", action="store_false",
                        help="不写 TIFF，只出 png+pdf（三格式约慢 30%%）")
    args = parser.parse_args()

    if args.list_charts:
        return print_catalog()
    if not args.data:
        print("ERROR: --data is required (or use --list-charts)", file=sys.stderr)
        return 2
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
    if args.n_scope:
        cfg["n_scope"] = args.n_scope
    set_style()
    key_cols = []
    for col in [outcome_col, group_col, treatment_col, time_col, id_col] + numeric[:4]:
        if col and col in df.columns and col not in key_cols:
            key_cols.append(col)
    pack = ChartPack(df, out_dir, cfg, formats, args.top_n, args.min_n, key_cols=key_cols)
    pack.set_outcome(outcome_col, kind, outcome_map)
    pack.configure_filters(only=split_multi(args.only),
                           sections=split_multi(args.sections) if args.sections else None,
                           max_charts=args.max_charts)

    prevalence_binaries = binary_predictors[:]
    if outcome_col and kind == "binary":
        prevalence_binaries = [outcome_col] + prevalence_binaries

    def stage(label: str, fn, *call_args, **call_kwargs):
        """Run one chart family; a crash there must not destroy the whole pack.

        Failing here means the *statistics* for that family broke (bad assumptions,
        degenerate table, missing column), not the drawing.  The failure is counted
        and reported, the remaining families still run, and the process exits 2 so
        the failure stays visible in CI.
        """
        try:
            fn(*call_args, **call_kwargs)
        except Exception as exc:
            pack.errors += 1
            msg = f"error: {type(exc).__name__}: {exc}"[:240]
            print(f"ERROR: {label}: {msg}", file=sys.stderr)
            pack.skipped.append({"section": label, "question": label, "reason": msg})
            try:
                plt.close("all")
            except Exception:
                pass

    stage("A 数据质量", pack.data_quality, group_col, time_col, region_col)
    stage("A 数据质量", pack.binary_prevalence, outcome_col, prevalence_binaries)
    stage("B 单变量", pack.outcome_distribution, outcome_col)
    stage("B 单变量", pack.univariate, numeric, categorical, treatment_col)
    stage("C 双变量", pack.bivariate, group_col, treatment_col, outcome_col,
          region_col, trial_col)
    corr_numeric = numeric + ([outcome_col] if outcome_col and kind == "continuous"
                              and outcome_col not in numeric else [])
    corr_binaries = binary_predictors + ([outcome_col] if outcome_col and kind in {"binary", "continuous"}
                                         and outcome_col not in binary_predictors else [])
    stage("C 双变量", pack.correlations, corr_numeric, corr_binaries)
    multivariate_numeric = (([outcome_col] if outcome_col and kind == "continuous"
                             and outcome_col not in numeric else []) + numeric)
    stage("D 多变量", pack.multivariate, multivariate_numeric, group_col, treatment_col)
    stage("D 多变量", pack.pca, numeric, group_col)
    stage("D 多变量", pack.clustering, numeric, group_col)
    stage("E 时间", pack.time_trends, time_col, outcome_col, treatment_col)
    stage("F 模型", pack.model_charts, args.coef, args.pred)
    stage("F 模型", pack.survival, cfg)
    stage("G 附录", pack.correspondence, group_col, treatment_col)
    stage("G 附录", pack.appendix, group_col)
    counts = pack.status_counts()
    if counts["ok"] == 0:
        hint = ""
        if pack.filtered:
            hint = ("（--only/--sections 过滤掉了全部图："
                    f"only={split_multi(args.only)} sections={split_multi(args.sections)}）")
        print("ERROR: no charts could be generated; check data columns and filter"
              + hint, file=sys.stderr)
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
        "n_scope": pack.n_scope_default,
        "data_hash": pack.data_hash,
        "max_charts": pack.max_charts,
        "only": pack.only_selectors,
        "sections": pack.wanted_sections,
    }
    mpath = pack.write(meta)
    total_errors = counts["error"] + pack.errors
    print(f"charts: {counts['ok']}  skipped: {len(pack.skipped)}"
          f"  filtered: {pack.filtered}  limited: {pack.limited}"
          f"  errors: {total_errors}")
    print(f"data_hash: {pack.data_hash}  n_scope: {pack.n_scope_default}"
          f"  manifest rows: {len(pack.manifest)}")
    print(f"manifest: {mpath}")
    print(f"figures: {pack.fig_dir}")
    return 2 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
