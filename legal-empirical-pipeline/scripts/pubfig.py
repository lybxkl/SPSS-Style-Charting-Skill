#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small helper library for publication-grade figures.

It standardizes the boring parts (width, fonts, spines, CI, export) so each
figure script only contains the actual data and geometry.

Example:
    import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
    from pubfig import set_style, save_fig, wilson_ci, forest_plot

    W = set_style()
    fig, ax = plt.subplots(figsize=(W, 4))
    ...
    save_fig(fig, "output/figures", "fig1")
"""
from __future__ import annotations

import os
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

CM = 1 / 2.54
INK = "#1A1A1A"
GRID = "#E4E4E4"
BLUE = "#2F5C8A"
ORANGE = "#B45F3C"
GREEN = "#5B7F62"
GRAY = "#8A8A8A"
LGRAY = "#C9C9C9"
RED = "#8E3324"

POSITIVE_LABELS = {
    "是": 1, "否": 0, "有": 1, "无": 0, "发生": 1, "未发生": 0,
    "支持": 1, "不支持": 0, "明确支持": 1, "未明确支持": 0,
    "阳性": 1, "阴性": 0, "yes": 1, "no": 0, "true": 1, "false": 0,
}


def binary_array(values, positive: str | None = None) -> np.ndarray:
    """Coerce labels to 0/1. Ambiguous two-level labels raise instead of guessing."""
    arr = list(values)
    numeric = pd.to_numeric(pd.Series(arr), errors="coerce")
    if numeric.notna().sum() == len([v for v in arr if v == v]):
        unique = set(numeric.dropna().unique())
        if unique <= {0, 1}:
            return numeric.to_numpy(dtype=float)
        raise ValueError("binary labels must be 0/1")
    text = [str(v).strip() for v in arr]
    levels = list(dict.fromkeys([v for v in text if v not in {"", "nan", "None"}]))
    if positive is not None:
        table = {level: (1 if level == positive else 0) for level in levels}
    else:
        table = {}
        for level in levels:
            key = level.lower()
            if key in POSITIVE_LABELS:
                table[level] = POSITIVE_LABELS[key]
        if len(table) != len(levels) or set(table.values()) != {0, 1}:
            raise ValueError("ambiguous binary labels; pass positive= or encode as 0/1")
    mapped = pd.Series(text).map(table)
    if set(mapped.dropna().unique()) != {0, 1}:
        raise ValueError("ambiguous binary labels; pass positive= or encode as 0/1")
    return mapped.to_numpy(dtype=float)


def set_style(width_cm: float = 15.0,
              font_cjk: str = "SimSun",
              font_latin: str = "Times New Roman",
              base_size: float = 8.5,
              dpi: int = 600) -> float:
    """Apply publication defaults and return the figure width in inches."""
    plt.rcParams.update({
        "font.family": [font_latin, font_cjk],
        "font.size": base_size,
        "axes.labelsize": base_size,
        "axes.titlesize": base_size,
        "xtick.labelsize": max(7.0, base_size - 0.5),
        "ytick.labelsize": max(7.0, base_size - 0.5),
        "legend.fontsize": max(7.0, base_size - 1.1),
        "axes.linewidth": 0.6,
        "axes.edgecolor": "#333333",
        "xtick.color": "#333333",
        "ytick.color": "#333333",
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 2.6,
        "ytick.major.size": 2.6,
        "xtick.major.pad": 2.2,
        "ytick.major.pad": 2.2,
        "axes.unicode_minus": False,
        "figure.dpi": dpi,
        "savefig.dpi": dpi,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.facecolor": "white",
    })
    return width_cm * CM


def style_axis(ax, grid_axis: str | None = "y") -> None:
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.set_axisbelow(True)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.5, zorder=0)
    ax.tick_params(axis="both", colors="#333333")


def panel_label(ax, letter: str, x: float = -0.02, y: float = 1.035) -> None:
    ax.text(x, y, letter, transform=ax.transAxes, fontsize=9,
            fontweight="bold", ha="left", va="bottom", color=INK)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, center - half), min(1.0, center + half))


def save_fig(fig, out_dir: str, name: str,
             formats: Sequence[str] = ("png", "pdf", "tiff"),
             dpi: int = 600) -> list[str]:
    """Save PNG (600 dpi), vector PDF, and LZW TIFF. Returns written paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for ext in formats:
        path = os.path.join(out_dir, f"{name}.{ext}")
        if ext == "tiff":
            fig.savefig(path, dpi=dpi, facecolor="white",
                        pil_kwargs={"compression": "tiff_lzw"})
        elif ext == "png":
            fig.savefig(path, dpi=dpi, facecolor="white")
        else:
            fig.savefig(path, facecolor="white")
        paths.append(path)
    plt.close(fig)
    return paths


def forest_plot(ax,
                labels: Sequence[str],
                estimates: Iterable[float],
                lows: Iterable[float],
                highs: Iterable[float],
                ref: float = 1.0,
                log_scale: bool = True,
                xlabel: str = "OR（95%CI）",
                color_sig: str = BLUE,
                color_ns: str = GRAY,
                marker_size: float = 18) -> None:
    """Draw a forest plot with solid significant / hollow non-significant points."""
    est = np.asarray(list(estimates), dtype=float)
    lo = np.asarray(list(lows), dtype=float)
    hi = np.asarray(list(highs), dtype=float)
    labels = list(labels)
    ok = np.isfinite(est) & np.isfinite(lo) & np.isfinite(hi)
    est, lo, hi = est[ok], lo[ok], hi[ok]
    labels = [lab for lab, keep in zip(labels, ok) if keep]
    if not len(labels):
        ax.text(0.5, 0.5, "无可绘制的估计值", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        return
    if log_scale and min(float(est.min()), float(lo.min()), float(hi.min())) <= 0:
        log_scale = False
        if xlabel.startswith("OR"):
            xlabel = "效应量（95%CI）"
    y = np.arange(len(labels))[::-1]
    sig = (lo > ref) | (hi < ref)
    for yy, e, l, h, s in zip(y, est, lo, hi, sig):
        ax.plot([l, h], [yy, yy], color=INK if s else LGRAY,
                linewidth=0.8, solid_capstyle="butt", zorder=2)
        ax.scatter([e], [yy], s=marker_size, zorder=3,
                   facecolor=color_sig if s else "white",
                   edgecolor=color_sig if s else color_ns, linewidth=0.8)
    ax.axvline(ref, color=GRAY, linewidth=0.6, linestyle=(0, (2, 2)), zorder=1)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    if log_scale:
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{x:g}"))
    ax.set_xlabel(xlabel)
    style_axis(ax, "x")


def bar_with_ci(ax, labels: Sequence[str], estimates: Iterable[float],
                lows: Iterable[float], highs: Iterable[float],
                color: str = BLUE, width: float = 0.62) -> None:
    """Bar chart with 95% CI error bars."""
    est = np.asarray(list(estimates), dtype=float)
    lo = np.asarray(list(lows), dtype=float)
    hi = np.asarray(list(highs), dtype=float)
    x = np.arange(len(labels))
    ax.bar(x, est, width=width, color=color, edgecolor="none", zorder=2)
    ax.errorbar(x, est, yerr=[est - lo, hi - est], fmt="none",
                ecolor=INK, elinewidth=0.8, capsize=2.2, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    style_axis(ax, "y")


# ---------------------------------------------------------------------------
# Extended atlas: distribution, composition, correlation, diagnostics
# ---------------------------------------------------------------------------

def bar_counts(ax, labels: Sequence[str], values: Iterable[float],
               color: str = BLUE, horizontal: bool = False,
               annotate: bool = True, fmt: str = "{:,.0f}",
               xlabel: str = "", ylabel: str = "") -> None:
    """Plain bar chart for counts or percentages, with optional value labels."""
    vals = np.asarray(list(values), dtype=float)
    labels = list(labels)
    if horizontal:
        y = np.arange(len(labels))[::-1]
        ax.barh(y, vals, height=0.62, color=color, edgecolor="none", zorder=2)
        ax.set_yticks(y)
        ax.set_yticklabels(labels)
        if annotate:
            span = max(vals) if len(vals) and max(vals) > 0 else 1
            for yy, v in zip(y, vals):
                ax.text(v + span * 0.012, yy, fmt.format(v), va="center",
                        ha="left", fontsize=7.8)
        ax.set_xlabel(xlabel)
        style_axis(ax, "x")
    else:
        x = np.arange(len(labels))
        ax.bar(x, vals, width=0.62, color=color, edgecolor="none", zorder=2)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        if annotate:
            span = max(vals) if len(vals) and max(vals) > 0 else 1
            for xx, v in zip(x, vals):
                ax.text(xx, v + span * 0.012, fmt.format(v), va="bottom",
                        ha="center", fontsize=7.8)
        ax.set_ylabel(ylabel)
        style_axis(ax, "y")


def plot_distribution(ax_hist, ax_box, values: Iterable[float],
                      bins: int = 30, color: str = BLUE,
                      xlabel: str = "") -> None:
    """Histogram + horizontal boxplot for one continuous variable."""
    vals = np.asarray([v for v in values if v == v], dtype=float)
    if not len(vals):
        ax_hist.text(0.5, 0.5, "无可用数据", transform=ax_hist.transAxes,
                     ha="center", va="center", fontsize=8)
        ax_hist.set_axis_off()
        ax_box.set_axis_off()
        return
    ax_hist.hist(vals, bins=bins, color=color, alpha=0.82,
                 edgecolor="white", linewidth=0.4, zorder=2)
    ax_hist.set_xlabel(xlabel)
    ax_hist.set_ylabel("频数")
    style_axis(ax_hist, "y")
    ax_box.boxplot(vals, vert=False, widths=0.5, patch_artist=True,
                   showfliers=True, flierprops={"markersize": 2.2,
                                                "markerfacecolor": GRAY,
                                                "markeredgecolor": GRAY},
                   boxprops={"facecolor": "white", "edgecolor": INK,
                             "linewidth": 0.7},
                   medianprops={"color": ORANGE, "linewidth": 1.0},
                   whiskerprops={"color": INK, "linewidth": 0.6},
                   capprops={"color": INK, "linewidth": 0.6})
    ax_box.set_yticks([])
    ax_box.set_xlabel("")
    for spine in ["top", "right", "left"]:
        ax_box.spines[spine].set_visible(False)
    ax_box.tick_params(axis="y", left=False)


def plot_violin(ax, groups: Sequence[Iterable[float]], labels: Sequence[str],
                color: str = BLUE, show_points: bool = True,
                rotate: int = 0, ylabel: str = "") -> None:
    """Violin + box + jittered points for group comparisons."""
    data = [np.asarray([v for v in g if v == v], dtype=float) for g in groups]
    if not any(len(g) for g in data):
        ax.text(0.5, 0.5, "无可用数据", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    parts = ax.violinplot(data, showmeans=False, showmedians=False,
                          showextrema=False, widths=0.72)
    for body in parts["bodies"]:
        body.set_facecolor(color)
        body.set_edgecolor("none")
        body.set_alpha(0.28)
    bp = ax.boxplot(data, widths=0.12, patch_artist=True, showfliers=False,
                    boxprops={"facecolor": "white", "edgecolor": INK,
                              "linewidth": 0.6},
                    medianprops={"color": ORANGE, "linewidth": 0.9},
                    whiskerprops={"color": INK, "linewidth": 0.5},
                    capprops={"color": INK, "linewidth": 0.5})
    for patch in bp["boxes"]:
        patch.set_alpha(0.9)
    if show_points:
        rng = np.random.default_rng(42)
        for i, vals in enumerate(data, 1):
            if len(vals) > 400:
                vals = rng.choice(vals, 400, replace=False)
            jitter = rng.normal(0, 0.035, len(vals))
            ax.scatter(np.full(len(vals), i) + jitter, vals, s=2.2,
                       color=INK, alpha=0.25, linewidths=0, zorder=1)
    ax.set_xticks(np.arange(1, len(labels) + 1))
    ax.set_xticklabels(labels, rotation=rotate, ha="right" if rotate else "center")
    ax.set_ylabel(ylabel)
    style_axis(ax, "y")


def stacked_bar(ax, row_labels: Sequence[str], series: Sequence[Iterable[float]],
                series_labels: Sequence[str], colors: Sequence[str] | None = None,
                normalize: bool = True, horizontal: bool = False,
                legend: bool = True) -> None:
    """Stacked bar/100% stacked bar. series is a list of arrays, one per stack."""
    labels = list(row_labels)
    mats = [np.asarray(list(s), dtype=float) for s in series]
    if normalize:
        totals = np.sum(mats, axis=0)
        totals[totals == 0] = 1
        mats = [m / totals for m in mats]
    palette = list(colors or [BLUE, ORANGE, GREEN, GRAY, LGRAY, RED])
    colors = [palette[i % len(palette)] for i in range(len(series_labels))]
    n = len(labels)
    if horizontal:
        y = np.arange(n)[::-1]
        left = np.zeros(n)
        for m, lab, col in zip(mats, series_labels, colors):
            ax.barh(y, m, left=left, height=0.66, color=col, label=lab,
                    edgecolor="white", linewidth=0.3)
            left += m
        ax.set_yticks(y)
        ax.set_yticklabels(labels)
        ax.set_xlim(0, 1)
        style_axis(ax, "x")
    else:
        x = np.arange(n)
        bottom = np.zeros(n)
        for m, lab, col in zip(mats, series_labels, colors):
            ax.bar(x, m, bottom=bottom, width=0.66, color=col, label=lab,
                   edgecolor="white", linewidth=0.3)
            bottom += m
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylim(0, 1)
        style_axis(ax, "y")
    if legend:
        ax.legend(frameon=False, ncol=min(len(series_labels), 4),
                  loc="upper center", bbox_to_anchor=(0.5, 1.16))


def line_ci(ax, x: Sequence[float], y: Iterable[float],
            lows: Iterable[float] | None = None,
            highs: Iterable[float] | None = None,
            color: str = BLUE, marker: str = "o", label: str | None = None,
            ylabel: str = "", xlabel: str = "") -> None:
    """Line chart with optional 95% CI error bars; accepts numeric or categorical x."""
    raw_x = list(x)
    categorical = False
    try:
        xv = np.asarray(raw_x, dtype=float)
    except (TypeError, ValueError):
        cats = list(dict.fromkeys(raw_x))
        position = {value: i for i, value in enumerate(cats)}
        xv = np.asarray([position[value] for value in raw_x], dtype=float)
        categorical = True
    yv = np.asarray(list(y), dtype=float)
    if lows is not None and highs is not None:
        lo = np.asarray(list(lows), dtype=float)
        hi = np.asarray(list(highs), dtype=float)
        ax.errorbar(xv, yv, yerr=[yv - lo, hi - yv], color=color, marker=marker,
                    markersize=3.6, linewidth=0.9, elinewidth=0.7,
                    capsize=2.0, label=label, zorder=2)
    else:
        ax.plot(xv, yv, color=color, marker=marker, markersize=3.6,
                linewidth=0.9, label=label, zorder=2)
    if categorical:
        ax.set_xticks(np.arange(len(cats)))
        ax.set_xticklabels(cats)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    style_axis(ax, "y")


def heatmap(ax, matrix, row_labels: Sequence[str], col_labels: Sequence[str],
            cmap: str = "Blues", annotate: bool = True, fmt: str = ".1f",
            vmin: float | None = None, vmax: float | None = None,
            cbar: bool = True):
    """Annotated heatmap for cross-tabs, loadings, or rates."""
    mat = np.asarray(matrix, dtype=float)
    im = ax.imshow(mat, cmap=cmap, aspect="auto", vmin=vmin, vmax=vmax)
    ax.set_xticks(np.arange(len(col_labels)))
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_xticklabels(col_labels, rotation=35, ha="right")
    ax.set_yticklabels(row_labels)
    if annotate:
        finite = mat[np.isfinite(mat)]
        vmid = (finite.min() + finite.max()) / 2 if finite.size else 0
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                val = mat[i, j]
                if val != val:
                    continue
                ax.text(j, i, format(val, fmt), ha="center", va="center",
                        fontsize=6.8, color="white" if val > vmid else INK)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if cbar:
        fig = ax.get_figure()
        fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    return im


def corr_heatmap(ax, df, method: str = "pearson", cmap: str = "RdBu_r",
                 annotate: bool = True) -> None:
    """Correlation heatmap from a pandas DataFrame (lower triangle shown)."""
    corr = df.corr(method=method, numeric_only=True)
    if corr.empty or len(corr.columns) < 2:
        ax.text(0.5, 0.5, "有效数值变量不足", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    mat = corr.to_numpy(dtype=float)
    mask = np.triu(np.ones_like(mat, dtype=bool), k=1)
    mat = np.ma.array(mat, mask=mask)
    im = ax.imshow(mat, cmap=cmap, vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(np.arange(len(corr.columns)))
    ax.set_yticks(np.arange(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
    ax.set_yticklabels(corr.columns)
    if annotate:
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                if i < j:
                    continue
                val = corr.iloc[i, j]
                ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                        fontsize=6.4, color="white" if abs(val) > 0.55 else INK)
    ax.tick_params(length=0)
    fig = ax.get_figure()
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)


def scatter_fit(ax, x: Iterable[float], y: Iterable[float],
                color: str = BLUE, xlabel: str = "", ylabel: str = "",
                logx: bool = False, logy: bool = False) -> float:
    """Scatter with OLS fit line; returns Pearson r."""
    xv = np.asarray(list(x), dtype=float)
    yv = np.asarray(list(y), dtype=float)
    ok = np.isfinite(xv) & np.isfinite(yv)
    xv, yv = xv[ok], yv[ok]
    ax.scatter(xv, yv, s=8, color=color, alpha=0.28, linewidths=0, zorder=2)
    if len(xv) >= 3 and np.std(xv) > 0 and np.std(yv) > 0:
        coef = np.polyfit(xv, yv, 1)
        xx = np.linspace(xv.min(), xv.max(), 100)
        ax.plot(xx, np.polyval(coef, xx), color=ORANGE, linewidth=1.0, zorder=3)
        r = float(np.corrcoef(xv, yv)[0, 1])
        ax.text(0.03, 0.95, f"r = {r:.2f}", transform=ax.transAxes,
                va="top", ha="left", fontsize=7.5)
    else:
        r = float("nan")
    if logx:
        ax.set_xscale("log")
    if logy:
        ax.set_yscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    style_axis(ax, "both")
    return r


def roc_curve(ax, y_true: Iterable[int], y_score: Iterable[float],
              color: str = BLUE, label: str | None = None) -> float:
    """ROC curve from binary labels and continuous scores; returns AUC."""
    try:
        y = binary_array(y_true)
    except ValueError as exc:
        ax.text(0.5, 0.5, str(exc), transform=ax.transAxes,
                ha="center", va="center", fontsize=7.5, wrap=True)
        ax.set_axis_off()
        return float("nan")
    s = np.asarray(list(y_score), dtype=float)
    ok = np.isfinite(s) & np.isfinite(y)
    y, s = y[ok], s[ok]
    if len(y) == 0 or len(np.unique(y)) < 2:
        ax.text(0.5, 0.5, "单一结果类别，ROC 不可估计", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return float("nan")
    if float(np.nanmax(s) - np.nanmin(s)) == 0:
        ax.text(0.5, 0.5, "预测分数为常数，ROC 不可估计", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return float("nan")
    order = np.argsort(-s)
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    tpr = tp / max(tp[-1], 1)
    fpr = fp / max(fp[-1], 1)
    auc = float(np.trapezoid(tpr, fpr)) if hasattr(np, "trapezoid") else float(np.trapz(tpr, fpr))
    ax.plot(fpr, tpr, color=color, linewidth=1.0,
            label=(label or "ROC") + f"（AUC={auc:.3f}）")
    ax.plot([0, 1], [0, 1], color=LGRAY, linewidth=0.6, linestyle=(0, (2, 2)))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("1 − 特异度")
    ax.set_ylabel("灵敏度")
    style_axis(ax, "both")
    ax.legend(frameon=False, loc="lower right")
    return auc


def calibration_plot(ax, y_true: Iterable[int], y_prob: Iterable[float],
                     bins: int = 10, color: str = BLUE) -> None:
    """Calibration curve: observed rate vs mean predicted probability."""
    try:
        y = binary_array(y_true)
    except ValueError as exc:
        ax.text(0.5, 0.5, str(exc), transform=ax.transAxes,
                ha="center", va="center", fontsize=7.5, wrap=True)
        ax.set_axis_off()
        return
    p = np.asarray(list(y_prob), dtype=float)
    ok = np.isfinite(p) & np.isfinite(y)
    y, p = y[ok], p[ok]
    if len(p) == 0:
        ax.text(0.5, 0.5, "无可用预测值", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges = np.unique(edges)
    xs, ys, ns = [], [], []
    if len(edges) < 2:
        xs, ys, ns = [float(p.mean())], [float(y.mean())], [len(p)]
    else:
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (p >= lo) & (p < hi)
            if m.sum() == 0:
                continue
            xs.append(float(p[m].mean()))
            ys.append(float(y[m].mean()))
            ns.append(int(m.sum()))
    ax.plot([0, 1], [0, 1], color=LGRAY, linewidth=0.6, linestyle=(0, (2, 2)))
    ax.plot(xs, ys, color=color, marker="o", markersize=3.5, linewidth=0.9)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("预测概率")
    ax.set_ylabel("实际发生率")
    style_axis(ax, "both")


def pareto(ax, labels: Sequence[str], counts: Iterable[float],
           color: str = BLUE, line_color: str = ORANGE,
           rotate: int = 35) -> None:
    """Pareto chart: sorted bars + cumulative percentage line."""
    vals = np.asarray(list(counts), dtype=float)
    order = np.argsort(-vals)
    vals = vals[order]
    labels = [list(labels)[i] for i in order]
    cum = np.cumsum(vals) / max(vals.sum(), 1) * 100
    x = np.arange(len(vals))
    ax.bar(x, vals, color=color, width=0.66, edgecolor="none", zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=rotate, ha="right")
    ax.set_ylabel("频数")
    style_axis(ax, "y")
    ax2 = ax.twinx()
    ax2.plot(x, cum, color=line_color, marker="o", markersize=2.8, linewidth=0.9)
    ax2.set_ylim(0, 105)
    ax2.set_ylabel("累计百分比（%）")
    ax2.spines["top"].set_visible(False)


def scree_plot(ax, explained_variance: Iterable[float],
               color: str = BLUE) -> None:
    """Scree + cumulative variance plot for PCA/factor analysis."""
    ev = np.asarray(list(explained_variance), dtype=float)
    if ev.sum() > 1.5:
        ev = ev / ev.sum() * 100
    x = np.arange(1, len(ev) + 1)
    ax.plot(x, ev, color=color, marker="o", markersize=3.2, linewidth=0.9,
            label="单个成分")
    ax.set_xlabel("成分")
    ax.set_ylabel("解释方差（%）")
    ax2 = ax.twinx()
    ax2.plot(x, np.cumsum(ev), color=ORANGE, marker="s", markersize=2.8,
             linewidth=0.9, label="累计")
    ax2.set_ylim(0, 105)
    ax2.set_ylabel("累计（%）")
    ax2.spines["top"].set_visible(False)
    style_axis(ax, "y")


def biplot(ax, scores, loadings, labels: Sequence[str] | None = None,
           color: str = BLUE, arrow_color: str = ORANGE,
           scale: float = 1.0) -> None:
    """PCA biplot: observations as points, variables as arrows."""
    sc = np.asarray(scores, dtype=float)
    ld = np.asarray(loadings, dtype=float)
    ax.scatter(sc[:, 0], sc[:, 1], s=7, color=color, alpha=0.25, linewidths=0)
    ax.axhline(0, color=LGRAY, linewidth=0.5)
    ax.axvline(0, color=LGRAY, linewidth=0.5)
    if labels is not None:
        for i, lab in enumerate(labels):
            ax.arrow(0, 0, ld[i, 0] * scale, ld[i, 1] * scale,
                     color=arrow_color, width=0.001, head_width=0.025,
                     length_includes_head=True, alpha=0.9)
            ax.text(ld[i, 0] * scale * 1.08, ld[i, 1] * scale * 1.08, lab,
                    fontsize=6.8, color=INK)
    ax.set_xlabel("成分 1")
    ax.set_ylabel("成分 2")
    style_axis(ax, "both")


def dumbbell(ax, labels: Sequence[str], left: Iterable[float],
             right: Iterable[float], left_label: str = "左",
             right_label: str = "右", color_left: str = BLUE,
             color_right: str = ORANGE) -> None:
    """Dumbbell chart for two paired rates/values per category."""
    lv = np.asarray(list(left), dtype=float)
    rv = np.asarray(list(right), dtype=float)
    y = np.arange(len(labels))[::-1]
    for yy, a, b in zip(y, lv, rv):
        ax.plot([a, b], [yy, yy], color=LGRAY, linewidth=1.2, zorder=1)
    ax.scatter(lv, y, s=20, color=color_left, label=left_label, zorder=2)
    ax.scatter(rv, y, s=20, color=color_right, label=right_label, zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    style_axis(ax, "x")
    ax.legend(frameon=False, loc="lower right")


def slopegraph(ax, labels: Sequence[str], left: Iterable[float],
               right: Iterable[float], left_label: str = "前",
               right_label: str = "后", color_up: str = BLUE,
               color_down: str = ORANGE) -> None:
    """Slopegraph for paired values at two points."""
    lv = np.asarray(list(left), dtype=float)
    rv = np.asarray(list(right), dtype=float)
    for lab, a, b in zip(labels, lv, rv):
        col = color_up if b >= a else color_down
        ax.plot([0, 1], [a, b], color=col, marker="o", markersize=3,
                linewidth=0.8, alpha=0.75)
        ax.text(-0.03, a, f"{lab} {a:.1f}", ha="right", va="center", fontsize=6.6)
        ax.text(1.03, b, f"{b:.1f}", ha="left", va="center", fontsize=6.6)
    ax.set_xlim(-0.25, 1.2)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([left_label, right_label])
    style_axis(ax, "y")


def stacked_area(ax, x: Sequence[float], series: Sequence[Iterable[float]],
                 series_labels: Sequence[str], colors: Sequence[str] | None = None,
                 normalize: bool = True, alpha: float = 0.9) -> None:
    """Stacked area chart (e.g. treatment composition over years)."""
    raw_x = list(x)
    categorical = False
    try:
        xv = np.asarray(raw_x, dtype=float)
    except (TypeError, ValueError):
        cats = list(dict.fromkeys(raw_x))
        position = {value: i for i, value in enumerate(cats)}
        xv = np.asarray([position[value] for value in raw_x], dtype=float)
        categorical = True
    mats = [np.asarray(list(s), dtype=float) for s in series]
    if normalize:
        totals = np.sum(mats, axis=0)
        totals[totals == 0] = 1
        mats = [m / totals for m in mats]
    palette = list(colors or [BLUE, ORANGE, GREEN, GRAY, LGRAY, RED])
    cols = [palette[i % len(palette)] for i in range(len(series_labels))]
    ax.stackplot(xv, *mats, labels=list(series_labels), colors=cols, alpha=alpha)
    if len(xv) == 1:
        ax.set_xlim(float(xv[0]) - 0.5, float(xv[0]) + 0.5)
    else:
        ax.set_xlim(float(xv.min()), float(xv.max()))
    if categorical:
        ax.set_xticks(np.arange(len(cats)))
        ax.set_xticklabels(cats)
    if normalize:
        ax.set_ylim(0, 1)
    style_axis(ax, "y")
    ax.legend(frameon=False, ncol=min(len(series_labels), 4),
              loc="upper center", bbox_to_anchor=(0.5, 1.16))


def bubble(ax, x: Iterable[float], y: Iterable[float], size: Iterable[float],
           labels: Sequence[str], color: str = BLUE,
           xlabel: str = "", ylabel: str = "") -> None:
    """Bubble chart; size is scaled to 20-260 points."""
    xv = np.asarray(list(x), dtype=float)
    yv = np.asarray(list(y), dtype=float)
    sv = np.asarray(list(size), dtype=float)
    if not len(xv):
        ax.text(0.5, 0.5, "无可用数据", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    smax = max(float(np.nanmax(sv)), 1.0)
    sizes = 20 + 240 * (sv / smax)
    ax.scatter(xv, yv, s=sizes, color=color, alpha=0.55,
               edgecolor="white", linewidth=0.5, zorder=2)
    for xx, yy, lab in zip(xv, yv, labels):
        ax.annotate(str(lab), (xx, yy), xytext=(3, 3), textcoords="offset points",
                    fontsize=6.6, color=INK)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    style_axis(ax, "both")


def pie_chart(ax, labels: Sequence[str], values: Iterable[float],
              colors: Sequence[str] | None = None, donut: bool = True,
              max_categories: int = 6, min_pct: float = 0.8,
              sort: bool = True) -> None:
    """Part-to-whole pie/donut; merges the tail into '其他' and drops tiny labels."""
    vals = np.asarray(list(values), dtype=float)
    labs = [str(x) for x in labels]
    mask = np.isfinite(vals) & (vals > 0)
    vals, labs = vals[mask], [l for l, m in zip(labs, mask) if m]
    if not len(vals):
        ax.text(0.5, 0.5, "无可用数据", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    if sort:
        order = np.argsort(vals)[::-1]
        vals, labs = vals[order], [labs[i] for i in order]
    if len(vals) > max_categories:
        keep = max_categories - 1
        vals = np.r_[vals[:keep], vals[keep:].sum()]
        labs = labs[:keep] + ["其他"]
    total = vals.sum()
    palette = list(colors or [BLUE, ORANGE, GREEN, GRAY, RED, "#7B6D8D"])
    palette = (palette * (len(vals) // len(palette) + 1))[:len(vals)]
    wedges, _, autotexts = ax.pie(
        vals, labels=None, colors=palette, startangle=90, counterclock=False,
        autopct=lambda p: f"{p:.0f}%" if p >= min_pct else "",
        pctdistance=0.75, wedgeprops={"linewidth": 0.6, "edgecolor": "white"},
        textprops={"fontsize": 7},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontsize(7)
    ax.legend(wedges, [f"{l}（{v / total * 100:.1f}%）" for l, v in zip(labs, vals)],
              frameon=False, fontsize=6.8, loc="center left",
              bbox_to_anchor=(0.94, 0.5))
    if donut:
        ax.add_artist(plt.Circle((0, 0), 0.52, color="white", zorder=5))
        ax.text(0, 0, f"N={int(total)}", ha="center", va="center",
                fontsize=8, color=INK, zorder=6)
    ax.set_aspect("equal")


def qq_plot(ax, values: Iterable[float], max_points: int = 5000) -> float:
    """Normal Q-Q plot; returns the correlation between theoretical and sample quantiles."""
    from scipy import stats
    v = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna().to_numpy(float)
    if len(v) < 3 or np.nanstd(v) == 0:
        ax.text(0.5, 0.5, "样本不足或为常数", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return float("nan")
    if len(v) > max_points:
        rng = np.random.default_rng(42)
        v = rng.choice(v, max_points, replace=False)
    (osm, osr), (slope, intercept, r) = stats.probplot(v, dist="norm")
    ax.scatter(osm, osr, s=8, color=BLUE, alpha=0.45, linewidths=0)
    ax.plot(osm, slope * osm + intercept, color=ORANGE, linewidth=1.0)
    ax.set_xlabel("理论正态分位数")
    ax.set_ylabel("样本分位数")
    style_axis(ax, "both")
    return float(r)


def control_chart(ax, x: Sequence, y: Iterable[float],
                  n: Iterable[float] | None = None,
                  center: float | None = None,
                  sigma: float | None = None,
                  ylabel: str = "比例") -> None:
    """Shewhart control chart. For proportions pass n to use 3-sigma p-chart limits."""
    yv = np.asarray(list(y), dtype=float)
    xv = list(x)
    mask = np.isfinite(yv)
    yv = yv[mask]
    xv = [v for v, m in zip(xv, mask) if m]
    if len(yv) < 3:
        ax.text(0.5, 0.5, "时间点不足", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    pos = np.arange(len(yv))
    if center is None:
        center = float(np.nanmean(yv))
    if sigma is None:
        if n is not None:
            nv = np.asarray(list(n), dtype=float)[mask]
            nv = np.where(nv > 0, nv, np.nan)
            sigma = np.sqrt(max(center * (1 - center), 1e-12) / np.nanmean(nv))
        else:
            sigma = float(np.nanstd(yv, ddof=1))
    upper = center + 3 * sigma
    lower = max(0.0, center - 3 * sigma)
    ax.plot(pos, yv, color=BLUE, linewidth=0.9, marker="o", markersize=2.8, zorder=3)
    ax.axhline(center, color=GREEN, linewidth=0.8, linestyle="-", label=f"中心线 {center:.3f}")
    ax.axhline(upper, color=RED, linewidth=0.7, linestyle="--", label="±3σ 控制限")
    ax.axhline(lower, color=RED, linewidth=0.7, linestyle="--")
    out = (yv > upper) | (yv < lower)
    if out.any():
        ax.scatter(pos[out], yv[out], s=26, color=RED, zorder=4, label="越界点")
    step = max(1, len(xv) // 12)
    tick_pos = pos[::step]
    ax.set_xticks(tick_pos)
    ax.set_xticklabels([str(v) for v in xv][::step], rotation=0)
    ax.set_ylabel(ylabel)
    ax.set_ylim(min(lower, float(np.nanmin(yv))) - 0.05,
                max(upper, float(np.nanmax(yv))) + 0.05)
    style_axis(ax, "y")
    ax.legend(frameon=False, fontsize=6.6, loc="best")


def dendrogram_plot(ax, matrix, labels: Sequence[str] | None = None,
                    method: str = "ward", metric: str = "euclidean",
                    max_labels: int = 24) -> None:
    """Hierarchical clustering dendrogram for standardized numeric variables."""
    from scipy.cluster.hierarchy import dendrogram, linkage
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 3 or arr.shape[1] < 2:
        ax.text(0.5, 0.5, "样本或变量不足", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    arr = np.nan_to_num(arr, nan=0.0)
    z = linkage(arr, method=method, metric=metric)
    labs = list(labels) if labels is not None and len(labels) == arr.shape[0] else None
    if labs is not None and len(labs) > max_labels:
        labs = None
    dendrogram(z, ax=ax, labels=labs, no_labels=labs is None,
               leaf_rotation=90, leaf_font_size=6.4,
               color_threshold=0.7 * max(z[:, 2]),
               above_threshold_color=GRAY)
    ax.set_ylabel("聚类距离")
    ax.tick_params(axis="x", labelsize=6.2)
    style_axis(ax, "y")


def classical_mds(dist, n_components: int = 2) -> tuple[np.ndarray, float]:
    """Classical (Torgerson) MDS without sklearn; returns coords and explained ratio."""
    d = np.asarray(dist, dtype=float)
    n = d.shape[0]
    if n < 3:
        return np.empty((0, n_components)), float("nan")
    d = (d + d.T) / 2
    j = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * j @ (d ** 2) @ j
    vals, vecs = np.linalg.eigh(b)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    pos = vals > 1e-9
    k = min(n_components, int(pos.sum()))
    if k == 0:
        return np.zeros((n, n_components)), 0.0
    coords = vecs[:, :k] * np.sqrt(vals[:k])
    if k < n_components:
        coords = np.pad(coords, ((0, 0), (0, n_components - k)))
    explained = float(vals[pos][:k].sum() / vals[pos].sum()) if vals[pos].sum() > 0 else 0.0
    return coords, explained


def mds_plot(ax, coords, labels: Sequence[str] | None = None,
             groups: Sequence | None = None, explained: float | None = None) -> None:
    """Scatter of MDS coordinates, optionally colored by group."""
    xy = np.asarray(coords, dtype=float)
    if xy.ndim != 2 or xy.shape[0] < 2:
        ax.text(0.5, 0.5, "样本不足", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    if groups is not None:
        g = pd.Series(list(groups)).astype(str).replace(
            {"nan": "未记载", "None": "未记载", "<NA>": "未记载"})
        palette = [BLUE, ORANGE, GREEN, GRAY, RED, "#7B6D8D"]
        for i, level in enumerate(g.value_counts().head(6).index):
            m = (g == level).to_numpy()
            ax.scatter(xy[m, 0], xy[m, 1], s=9, alpha=0.45, linewidths=0,
                       color=palette[i % len(palette)], label=str(level))
        ax.legend(frameon=False, fontsize=6.6, loc="best")
    else:
        ax.scatter(xy[:, 0], xy[:, 1], s=9, alpha=0.4, color=BLUE, linewidths=0)
    if labels is not None and len(labels) == xy.shape[0] and len(labels) <= 20:
        for i, lab in enumerate(labels):
            ax.annotate(str(lab), (xy[i, 0], xy[i, 1]), xytext=(3, 3),
                        textcoords="offset points", fontsize=6.2, color=INK)
    qx = np.nanquantile(xy[:, 0], [0.01, 0.99])
    qy = np.nanquantile(xy[:, 1], [0.01, 0.99])
    ax.set_xlim(qx[0] - 0.1 * (qx[1] - qx[0] + 1e-9),
                qx[1] + 0.1 * (qx[1] - qx[0] + 1e-9))
    ax.set_ylim(qy[0] - 0.1 * (qy[1] - qy[0] + 1e-9),
                qy[1] + 0.1 * (qy[1] - qy[0] + 1e-9))
    ax.set_xlabel("MDS 维度 1" + (f"（解释 {explained * 100:.1f}%）" if explained is not None else ""))
    ax.set_ylabel("MDS 维度 2")
    style_axis(ax, "both")


def pr_curve(ax, y_true: Iterable, y_score: Iterable[float]) -> float:
    """Precision-recall curve; returns average precision (AP)."""
    y = binary_array(y_true)
    s = pd.to_numeric(pd.Series(list(y_score)), errors="coerce").to_numpy(float)
    mask = np.isfinite(y) & np.isfinite(s)
    y, s = y[mask], s[mask]
    if len(y) < 2 or len(np.unique(y)) < 2:
        ax.text(0.5, 0.5, "需要两个类别", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return float("nan")
    order = np.argsort(s)[::-1]
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / max(tp[-1], 1)
    ap = float(np.sum(np.diff(np.r_[0, recall]) * precision))
    prevalence = float(y.mean())
    ax.plot(recall, precision, color=BLUE, linewidth=1.2, label=f"AP={ap:.3f}")
    ax.axhline(prevalence, color=GRAY, linewidth=0.8, linestyle="--",
               label=f"基线={prevalence:.3f}")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("召回率")
    ax.set_ylabel("精确率")
    style_axis(ax, "both")
    ax.legend(frameon=False, loc="best")
    return ap


def lift_chart(ax, y_true: Iterable, y_score: Iterable[float],
               bins: int = 10) -> pd.DataFrame:
    """Decile lift chart; returns per-bin counts and lift."""
    y = binary_array(y_true)
    s = pd.to_numeric(pd.Series(list(y_score)), errors="coerce").to_numpy(float)
    mask = np.isfinite(y) & np.isfinite(s)
    y, s = y[mask], s[mask]
    if len(y) < bins or len(np.unique(y)) < 2:
        ax.text(0.5, 0.5, "样本不足或单一类别", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return pd.DataFrame()
    ranks = pd.qcut(pd.Series(s).rank(method="first"), bins, labels=False).to_numpy()
    overall = y.mean()
    rows = []
    for b in range(bins):
        m = ranks == b
        if m.sum() == 0:
            continue
        rows.append({"bin": b + 1, "n": int(m.sum()), "events": int(y[m].sum()),
                     "event_rate": float(y[m].mean()),
                     "lift": float(y[m].mean() / overall) if overall else np.nan})
    tab = pd.DataFrame(rows)
    ax.bar(tab["bin"], tab["lift"], color=BLUE, width=0.72)
    ax.axhline(1.0, color=RED, linewidth=0.8, linestyle="--", label="随机基线")
    ax.set_xticks(tab["bin"])
    ax.set_xticklabels([f"D{int(b)}" for b in tab["bin"]])
    ax.set_xlabel("按预测概率十分位（D1=最高）")
    ax.set_ylabel("提升倍数（Lift）")
    style_axis(ax, "y")
    ax.legend(frameon=False, fontsize=6.8)
    return tab


def confusion_heatmap(ax, y_true: Iterable, y_score: Iterable[float],
                      threshold: float = 0.5,
                      labels: Sequence[str] = ("负类", "正类")) -> np.ndarray:
    """2×2 confusion matrix heatmap at a probability threshold."""
    y = binary_array(y_true)
    s = pd.to_numeric(pd.Series(list(y_score)), errors="coerce").to_numpy(float)
    mask = np.isfinite(y) & np.isfinite(s)
    y, s = y[mask], s[mask]
    if len(y) < 2 or len(np.unique(y)) < 2:
        ax.text(0.5, 0.5, "需要两个类别", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return np.zeros((2, 2), dtype=int)
    pred = (s >= threshold).astype(int)
    mat = np.zeros((2, 2), dtype=int)
    for t in (0, 1):
        for p in (0, 1):
            mat[t, p] = int(((y == t) & (pred == p)).sum())
    heatmap(ax, mat, [f"真实{l}" for l in labels],
            [f"预测{l}" for l in labels], fmt=".0f", cmap="Blues")
    ax.set_xlabel("预测类别")
    ax.set_ylabel("真实类别")
    return mat


def kaplan_meier(ax, time: Iterable[float], event: Iterable,
                 group: Sequence | None = None) -> None:
    """Kaplan-Meier survival curves with censoring ticks; no external dependency."""
    t = pd.to_numeric(pd.Series(list(time)), errors="coerce").to_numpy(float)
    e = binary_array(event)
    mask = np.isfinite(t) & np.isfinite(e) & (t >= 0)
    t, e = t[mask], e[mask]
    if len(t) < 3:
        ax.text(0.5, 0.5, "随访数据不足", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return
    g = (pd.Series(list(group)).astype(str)
         .replace({"nan": "未记载", "None": "未记载", "<NA>": "未记载"}).to_numpy()
         if group is not None else np.array(["全体"] * len(t), dtype=object))
    g = g[mask]
    palette = [BLUE, ORANGE, GREEN, GRAY, RED, "#7B6D8D"]
    for i, level in enumerate(pd.Series(g).value_counts().head(6).index):
        m = g == level
        tt, ee = t[m], e[m]
        if len(tt) < 3:
            continue
        order = np.argsort(tt)
        tt, ee = tt[order], ee[order]
        uniq = np.unique(tt[ee == 1])
        surv = 1.0
        xs, ys = [0.0], [1.0]
        for u in uniq:
            at_risk = int((tt >= u).sum())
            events = int(((tt == u) & (ee == 1)).sum())
            if at_risk <= 0:
                continue
            surv *= (1 - events / at_risk)
            xs += [u, u]
            ys += [ys[-1], surv]
        cens = tt[ee == 0]
        if len(cens):
            cy = []
            for c in cens:
                idx = np.searchsorted(xs, c, side="right") - 1
                cy.append(ys[max(idx, 0)])
            ax.scatter(cens, cy, marker="|", s=12, color=palette[i % len(palette)],
                       linewidths=0.8, zorder=3)
        ax.step(xs, ys, where="post", color=palette[i % len(palette)],
                linewidth=1.0, label=str(level))
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("随访时间")
    ax.set_ylabel("生存概率")
    style_axis(ax, "both")
    if group is not None:
        ax.legend(frameon=False, fontsize=6.8, loc="best")
