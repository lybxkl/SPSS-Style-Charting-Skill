#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small helper library for publication-grade figures.

It standardizes the boring parts (width, fonts, spines, CI, export) so each
figure script only contains the actual data and geometry.

Example:
    import matplotlib.pyplot as plt
    from pubfig import set_style, save_fig, wilson_ci, forest_plot

    W = set_style()
    fig, ax = plt.subplots(figsize=(W, 4))
    ...
    save_fig(fig, "output/figures", "fig1")
"""
from __future__ import annotations

import math
import os
import sys
import re
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter, NullLocator

CM = 1 / 2.54
INK = "#121212"
GRID = "#ECECEC"
BLUE = "#1C4E7B"
ORANGE = "#E18560"
GREEN = "#4B6E52"
GRAY = "#BABABA"
LGRAY = "#D8D8D8"
RED = "#67130A"
GREY5 = LGRAY  # backwards-compatible alias used by older palettes
PURPLE = "#1D1932"   # deepest step: reads almost black, still violet by hue
TEAL = "#588B78"     # the second new hue the audit asked for (deep green)

#: The categorical cycle every multi-series helper draws from.  These eight
#: colours sit on a 10.8 L* ladder (10.5, 21.5, ... 86.3), so any subset is
#: separable in grayscale as well as in colour, and eight series never repeat a
#: colour.  ``INK``/``GRID`` stay out of the cycle: they are structure, not data.
CATEGORICAL = [BLUE, ORANGE, GREEN, RED, TEAL, PURPLE, GRAY, LGRAY]

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


#: Families that ship a usable CJK glyph set; used only to explain a failure.
_CJK_FAMILY_HINTS = (
    "SimSun", "宋体", "NSimSun", "SimHei", "黑体", "KaiTi", "楷体", "FangSong",
    "仿宋", "Microsoft YaHei", "微软雅黑", "Microsoft JhengHei", "Songti SC",
    "STSong", "Noto Sans CJK", "Noto Serif CJK", "Source Han", "WenQuanYi",
    "PingFang", "Hiragino Sans GB", "Droid Sans Fallback", "AR PL",
)
_CJK_TOKEN_RE = None  # built lazily; no module-level regex import needed


def _looks_cjk(name: str) -> bool:
    """True for a font family name that plausibly carries Han glyphs."""
    if any("\u4e00" <= ch <= "\u9fff" for ch in name):
        return True
    lowered = name.lower()
    for token in _CJK_FAMILY_HINTS:
        if token.lower() in lowered:
            return True
    return False


def cjk_font_candidates(limit: int = 10) -> list[str]:
    """Installed families that can actually draw Chinese (for error messages)."""
    try:
        from matplotlib import font_manager
        entries = list(font_manager.fontManager.ttflist)
    except Exception:
        return []
    names = []
    for entry in entries:
        fname = str(getattr(entry, "fname", "") or "")
        if not fname.lower().endswith((".ttf", ".ttc", ".otf")):
            continue
        name = str(getattr(entry, "name", "") or "").strip()
        if not name or not _looks_cjk(name) or name in names:
            continue
        names.append(name)
    return sorted(names)[:limit]


def check_cjk_font(name: str) -> None:
    """Strict variant: raise unless ``name`` itself is installed."""
    from matplotlib import font_manager
    try:
        font_manager.findfont(name, fallback_to_default=False)
        return
    except Exception:
        pass
    _raise_no_font(name)


def _raise_no_font(name: str) -> None:
    candidates = cjk_font_candidates()
    hint = "、".join(candidates) if candidates else "（本机未发现中文字体）"
    raise RuntimeError(
        f"中文字体 {name!r} 不存在：图里的中文会画成方框（豆腐块）。"
        f"本机可用的中文字体：{hint}。"
        f"请用 set_style(font_cjk=...) 指定其中一个，或安装 SimSun / Noto Sans CJK。"
    )


def resolve_cjk_font(name: str) -> tuple[str, str | None]:
    """Return ``(family_to_use, warning_or_None)`` for a requested CJK family.

    Three tiers, each of them audible:

    1. the family is installed -> use it;
    2. it is missing but some CJK family exists -> substitute the first one and
       say so on stderr (silently drawing tofu boxes is the bug we are fixing,
       and hard-failing would break machines that only draw Latin figures);
    3. no CJK family at all -> RuntimeError, because nothing can be substituted.
    """
    from matplotlib import font_manager
    try:
        font_manager.findfont(name, fallback_to_default=False)
        return name, None
    except Exception:
        pass
    candidates = cjk_font_candidates()
    if not candidates:
        _raise_no_font(name)
    substitute = candidates[0]
    return substitute, (f"warning: 字体 {name!r} 不存在，已改用 {substitute!r}；"
                        f"如需固定请 set_style(font_cjk=...)")


def set_style(width_cm: float = 15.0,
              font_cjk: str = "SimSun",
              font_latin: str = "Times New Roman",
              base_size: float = 8.5,
              dpi: int = 600) -> float:
    """Apply publication defaults and return the figure width in inches.

    The width is also written into ``figure.figsize`` (height = 0.62 × width),
    so ``plt.subplots()`` called without an explicit ``figsize`` already gets
    the 15 cm single-column canvas instead of matplotlib's 6.4 in default.
    An explicit ``figsize=`` at the call site still wins.
    """
    width_in = width_cm * CM
    font_cjk, font_warning = resolve_cjk_font(font_cjk)
    if font_warning:
        print(font_warning, file=sys.stderr)
    plt.rcParams.update({
        "font.family": [font_latin, font_cjk],
        # The resolved CJK family leads the sans list, so a missing Latin face
        # still lands on a font that can draw Chinese.
        "font.sans-serif": [font_cjk, "DejaVu Sans"],
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
        "figure.figsize": (width_in, width_in * 0.62),
        "figure.dpi": dpi,
        "savefig.dpi": dpi,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.facecolor": "white",
    })
    return width_in


def style_axis(ax, grid_axis: str | None = "y") -> None:
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.set_axisbelow(True)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.5, zorder=0)
    ax.tick_params(axis="both", colors="#333333")


def panel_letter_size(fontsize=None) -> float:
    """Panel letters are the body size or one step larger, never smaller."""
    if fontsize is not None:
        return float(fontsize)
    return max(8.5, float(plt.rcParams.get("font.size", 8.5)))


def panel_label(ax, letter: str, x: float = -0.02, y: float = 1.035,
                fontsize=None) -> None:
    ax.text(x, y, letter, transform=ax.transAxes,
            fontsize=panel_letter_size(fontsize),
            fontweight="bold", ha="left", va="bottom", color=INK)


_DUMMY_RE = re.compile(r"^(.+?)\[(?:T\.)?(.+?)\]$")
# patsy wrappers: C(x) / C(x, Treatment('a')) / C(x, Treatment(reference='a'))
_PATSY_C_RE = re.compile(r"^C\(\s*([^,()]+?)\s*(?:,.*)?\)$")


def _strip_patsy(name: str) -> str:
    """``C(x)`` / ``C(x, Treatment('a'))`` -> ``x``."""
    s = str(name).strip()
    m = _PATSY_C_RE.match(s)
    return m.group(1).strip() if m else s


def short_label(value, col: str = "", max_chars: int | None = None) -> str:
    """Shorten a tick/axis label without destroying its meaning.

    Parameters
    ----------
    value:
        Raw label, typically a model term. Both ``var[T.level]`` (statsmodels /
        patsy) and ``var_水平`` are accepted.
    col:
        Optional variable name the label belongs to; accepted for API symmetry
        with the chart pack and currently unused.
    max_chars:
        Hard character budget. ``None`` means 24 for ASCII labels and 16 for
        labels containing CJK text (wider glyphs).

    Returns
    -------
    str
        ``var[T.level]`` becomes ``var：level`` so dummy levels stay readable
        and distinct; the label is only truncated when it really is too long,
        and the ellipsis is appended at the end. No character is ever deleted
        from the middle of the label (the old ``replace("罪", "")`` turned
        ``单位犯罪`` into ``单位犯`` and collapsed every dummy of one variable
        into the same 8-character prefix).
    """
    s = str(value).strip()
    m = _DUMMY_RE.match(s)
    if m:
        s = f"{_strip_patsy(m.group(1))}[{m.group(2)}]"
        m = _DUMMY_RE.match(s)
    if max_chars is None:
        max_chars = 24 if re.fullmatch(r"[A-Za-z0-9_ .,%\-]+", s) else 16
    max_chars = max(3, int(max_chars))
    if m:
        var, level = m.group(1), m.group(2)
        full = f"{var}：{level}"
        if len(full) <= max_chars:
            return full
        if len(level) + 2 <= max_chars:
            keep = max_chars - len(level) - 2
            return f"{var[:max(keep, 1)]}…：{level}"
        return level[: max_chars - 1] + "…"
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _log_tick_candidates(lo: float, hi: float, max_ticks: int = 9) -> list[float]:
    """Pick readable major tick positions inside ``[lo, hi]`` on a log axis."""
    if not (np.isfinite(lo) and np.isfinite(hi)) or lo <= 0 or hi <= lo:
        return []
    decades = np.arange(math.floor(math.log10(lo)), math.ceil(math.log10(hi)) + 1)
    ticks = [m * 10.0 ** d for d in decades for m in (1, 2, 5)]
    ticks = [t for t in ticks if lo * 0.999 <= t <= hi * 1.001]
    if len(ticks) > max_ticks:
        ticks = [10.0 ** d for d in decades if lo * 0.999 <= 10.0 ** d <= hi * 1.001]
    return ticks or [lo, hi]


def _fix_log_ticks(ax, ticks=None, axis: str = "x") -> None:
    """Make a log axis print clean, fixed labels.

    A log axis in matplotlib draws minor ticks by default and ``{x:g}`` style
    auto labels; both produce a row of unlabelled ticks and mixed
    ``1``/``1e+08`` strings. This turns the minor ticks off entirely
    (``NullLocator`` + ``NullFormatter`` + zero length), pins the major ticks to
    an explicit list and formats them with ``{x:g}``.

    Parameters
    ----------
    ax:
        Axes whose log axis is being fixed. The axis must already be set to
        ``log`` (call this *after* ``set_xscale("log")`` / ``set_yscale("log")``).
    ticks:
        Explicit major tick positions. ``None`` derives 1/2/5×10^k positions
        from the current view limits.
    axis:
        ``"x"`` (default) or ``"y"``.
    """
    target = ax.xaxis if axis == "x" else ax.yaxis
    target.set_minor_locator(NullLocator())
    target.set_minor_formatter(NullFormatter())
    ax.tick_params(axis=axis, which="minor", length=0)
    if ticks is None:
        limits = ax.get_xlim() if axis == "x" else ax.get_ylim()
        ticks = _log_tick_candidates(float(limits[0]), float(limits[1]))
    try:
        target.set_major_locator(FixedLocator([float(t) for t in ticks]))
    except (TypeError, ValueError):
        pass
    target.set_major_formatter(FuncFormatter(lambda v, pos: f"{v:g}"))


def _fit_legend(ax, legend, pad: float = 0.012, min_top: float = 0.55,
                passes: int = 3) -> float:
    """Shrink the axes until an above-axes legend fits inside the canvas.

    ``tight_layout`` does not account for legends anchored outside the axes, so
    a legend placed at ``bbox_to_anchor=(0.5, 1.16)`` is silently cropped once
    ``save_fig`` refuses ``bbox_inches="tight"`` (it lowers the resolution).
    This measures the legend in figure coordinates and lowers
    ``subplotpars.top`` just enough to keep it on the canvas.

    Returns the resulting ``fig.subplotpars.top`` (the value actually used).
    """
    fig = ax.get_figure()
    for _ in range(max(1, int(passes))):
        try:
            fig.canvas.draw()
            bbox = legend.get_window_extent(fig.canvas.get_renderer())
            bbox = bbox.transformed(fig.transFigure.inverted())
        except Exception:  # pragma: no cover - backend without a renderer
            break
        overflow = float(bbox.y1) + pad - 1.0
        if overflow <= 0:
            break
        new_top = max(min_top, fig.subplotpars.top - overflow * 1.15)
        if new_top >= fig.subplotpars.top - 1e-6:
            break
        fig.subplots_adjust(top=new_top)
    return float(fig.subplotpars.top)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Identical to ``auto_stats.wilson_ci`` (same expression order and the same
    clamp to ``p``), so a rate reported by the screening pack and a rate drawn
    on a figure can never disagree. ``tests/test_stats_charts.py`` asserts the
    equality; if you change one implementation, change the other.

    Parameters
    ----------
    k: successes. ``n``: trials. ``z``: normal quantile (1.96 for 95%).
    Returns ``(low, high)``, or ``(nan, nan)`` when ``n <= 0``.
    """
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    # The Wilson interval always brackets p mathematically; clamp away the
    # 1e-16 float noise so degenerate groups (all 0 or all 1) never yield a
    # negative error-bar length.
    return (max(0.0, min(center - half, p)), min(1.0, max(center + half, p)))


def _apply_pad(fig, pad):
    """Inset the axes by ``pad`` inches without ``bbox_inches="tight"``.

    Tight bounding boxes crop/scale the canvas and therefore change the effective
    resolution ``qa_outputs.py`` measures (884 -> 724 px).  Adjusting the subplot
    parameters keeps the canvas and the dpi intact.
    """
    if not pad:
        return
    try:
        fw, fh = (float(v) for v in fig.get_size_inches()[:2])
        dx, dy = float(pad) / max(fw, 1e-9), float(pad) / max(fh, 1e-9)
        sp = fig.subplotpars
        left = min(max(sp.left + dx, 0.0), 0.45)
        right = max(min(sp.right - dx, 1.0), 0.55)
        bottom = min(max(sp.bottom + dy, 0.0), 0.45)
        top = max(min(sp.top - dy, 1.0), 0.55)
        if left < right and bottom < top:
            fig.subplots_adjust(left=left, right=right, bottom=bottom, top=top)
    except Exception:  # pragma: no cover - defensive: never break export
        pass


def _write_formats(fig, out_dir: str, name: str,
                   formats: Sequence[str] = ("png", "pdf", "tiff"),
                   dpi: int = 600) -> list[str]:
    """Write one figure in every requested format; returns the written paths."""
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
    return paths


def save_fig(fig, out_dir: str, name: str,
             formats: Sequence[str] = ("png", "pdf", "tiff"),
             dpi: int = 600, pad: float | None = None) -> list[str]:
    """Save PNG (600 dpi), vector PDF, and LZW TIFF. Returns written paths.

    Parameters
    ----------
    fig:
        Figure to export (it is closed afterwards).
    out_dir / name:
        Target directory and file stem (``<name>.png`` etc.).
    formats:
        Any of ``"png"``, ``"pdf"``, ``"tiff"``.
    dpi:
        Raster resolution; the figure keeps its physical size, so a 15 cm wide
        figure stays 15 cm wide (3543 px at 600 dpi).
    pad:
        Extra white margin **in inches**. ``None`` (default) leaves the canvas
        and the axes untouched. A positive value insets the axes with
        ``fig.subplots_adjust`` instead of ``bbox_inches="tight"``: tight
        bounding boxes crop/scale the figure and therefore change the effective
        resolution that ``qa_outputs.py`` measures.
    """
    _apply_pad(fig, pad)
    paths = _write_formats(fig, out_dir, name, formats, dpi)
    plt.close(fig)
    return paths


# --------------------------------------------------------------- composition
# A figure in a journal is a *grid* of panels, not one axes.  ``compose_figure``
# builds that grid with an explicit ``GridSpec`` so every panel's physical size
# is computable (``panel_sizes_cm``), which is what the QA step needs to decide
# whether a 6 pt label will still be legible after the figure is placed.

def _rc_size(key: str, fallback: float = 8.5) -> float:
    """Read a font size from rcParams, tolerating the string values matplotlib allows."""
    try:
        return float(plt.rcParams.get(key, fallback))
    except (TypeError, ValueError):
        return float(fallback)


def _styled_label(letter: str, style: str = "(a)") -> str:
    """``(a)`` / ``a)`` / ``a.`` / ``a`` / ``(A)`` from a single lowercase letter."""
    text = str(style or "(a)")
    if "(" in text and ")" in text:
        out = f"({letter})"
    elif ")" in text:
        out = f"{letter})"
    elif "." in text:
        out = f"{letter}."
    else:
        out = letter
    if any(ch.isupper() for ch in text):
        out = out.upper()
    return out


def _panel_letters(count: int, style: str = "(a)") -> list[str]:
    out = []
    for i in range(max(0, int(count))):
        if i < 26:
            letter = chr(ord("a") + i)
        else:  # aa, ab, ... (a 2x2 figure never reaches this, a 5x6 might)
            letter = chr(ord("a") + (i // 26) - 1) + chr(ord("a") + i % 26)
        out.append(_styled_label(letter, style))
    return out


def _figure_texts(fig, axes) -> list:
    items = []
    for ax in axes:
        try:
            items.extend(list(ax.texts))
            items.extend([ax.xaxis.label, ax.yaxis.label, ax.title])
            legend = ax.get_legend()
            if legend is not None:
                items.extend(list(legend.get_texts()))
            items.extend(list(ax.get_xticklabels()))
            items.extend(list(ax.get_yticklabels()))
        except Exception:  # pragma: no cover - artist without font properties
            continue
    try:
        items.extend(list(fig.texts))
        for legend in getattr(fig, "legends", []):
            items.extend(list(legend.get_texts()))
    except Exception:  # pragma: no cover
        pass
    return items


def _measure_min_fontsize(fig, axes) -> float:
    """Smallest *actually rendered* font size inside the figure, in points.

    ``rcParams`` is not the answer: a panel may pass ``fontsize=6`` to one label
    and the figure then carries 6 pt type while every other string is 8.5 pt.
    Drawing first and reading ``get_fontsize()`` off the artists catches that.
    """
    try:
        fig.canvas.draw()
    except Exception:  # pragma: no cover - headless edge case
        pass
    sizes = []
    for text in _figure_texts(fig, axes):
        try:
            if not str(text.get_text() or "").strip():
                continue
            sizes.append(float(text.get_fontsize()))
        except Exception:  # pragma: no cover
            continue
    return float(min(sizes)) if sizes else float("nan")


def _measure_panel_sizes_cm(fig, axes) -> list[list[float]]:
    """Physical panel sizes in cm, from ``get_position()`` and the figure size.

    This is exact for a GridSpec figure.  It is geometry, not typography: type
    does not shrink with the panel, it shrinks with the ratio of the placed
    figure width to the designed width, which is what ``qa_outputs`` models.
    """
    try:
        fig.canvas.draw()
    except Exception:  # pragma: no cover
        pass
    width_in, height_in = (float(v) for v in fig.get_size_inches()[:2])
    out = []
    for ax in axes:
        pos = ax.get_position()
        out.append([round(float(pos.width) * width_in * 2.54, 2),
                    round(float(pos.height) * height_in * 2.54, 2)])
    return out


def _legend_overhang(fig, axes=None) -> tuple[float, float]:
    """How far legends and panel titles stick out past the canvas.

    ``tight_layout``/``subplots_adjust`` move the axes but not an
    ``bbox_to_anchor`` outside them, so a legend placed above the axes (or a
    title pushed above a lifted legend) is what runs off the canvas; only the
    top/right margins can absorb it. Everything drawn outside its own axes is
    measured: legends, titles, and free-standing ``ax.text`` labels.
    """
    axes = list(fig.axes) if axes is None else list(axes)
    targets: list[tuple[object, object]] = []
    for ax in axes:
        legend = ax.get_legend()
        if legend is not None:
            targets.append((ax, legend))
        title = getattr(ax, "title", None)
        if title is not None and str(title.get_text() or "").strip():
            targets.append((ax, title))
        for text in getattr(ax, "texts", []):
            if str(text.get_text() or "").strip():
                targets.append((ax, text))
    for text in getattr(fig, "texts", []):
        if str(text.get_text() or "").strip():
            targets.append((None, text))
    for legend in getattr(fig, "legends", []):
        targets.append((None, legend))
    if not targets:
        return (0.0, 0.0)
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
    except Exception:  # pragma: no cover
        return (0.0, 0.0)
    inverse = fig.transFigure.inverted()
    dx = dy = 0.0
    for ax, artist in targets:
        try:
            box = artist.get_window_extent(renderer).transformed(inverse)
            if ax is not None:
                abox = ax.get_window_extent(renderer).transformed(inverse)
                if box.y1 <= abox.y1 + 1e-6 and box.x1 <= abox.x1 + 1e-6:
                    continue  # fully inside its own axes: no margin needed
            dx = max(dx, float(box.x1) - 1.0)
            dy = max(dy, float(box.y1) - 1.0)
        except Exception:  # pragma: no cover
            continue
    return (max(0.0, dx), max(0.0, dy))


def _lift_above_legend(ax) -> None:
    """Re-anchor a legend that straddles the top edge of its axes, above it."""
    legend = ax.get_legend()
    if legend is None:
        return
    try:
        legend.set_loc("lower center")
        legend.set_bbox_to_anchor((0.5, 1.012), transform=ax.transAxes)
    except Exception:  # pragma: no cover
        pass


def _collect_colors(axes) -> list[str]:
    """Colours actually painted on ``axes`` (patches, lines, collections).

    Pure white and the near-white background/frame shades are skipped, and the
    order is first-seen, so a caller can record "the palette this figure used".
    """
    from matplotlib.colors import to_hex

    seen: list[str] = []
    skip = {"#FFFFFF", "#000000"}
    for ax in axes:
        artists = list(getattr(ax, "patches", []) or [])
        artists += list(getattr(ax, "lines", []) or [])
        artists += list(getattr(ax, "collections", []) or [])
        for artist in artists:
            candidates = []
            for getter in ("get_facecolor", "get_color", "get_edgecolor"):
                try:
                    candidates.append(getattr(artist, getter)())
                except Exception:
                    continue
            for value in candidates:
                try:
                    rgba = value[0] if len(value) and isinstance(value[0], (list, tuple)) else value
                    if len(rgba) < 3:
                        continue
                    if len(rgba) == 4 and float(rgba[3]) == 0.0:
                        continue
                    hex_value = to_hex(rgba).upper()
                except Exception:
                    continue
                if hex_value in skip or hex_value in seen:
                    continue
                seen.append(hex_value)
    return seen


def compose_figure(panels, out_dir: str | None = None, name: str = "figure",
                   nrows: int = 1, ncols: int = 1, width_cm: float = 15.0,
                   height_cm: float | None = None, panel_w_cm: float | None = None,
                   label_style: str = "(a)", space=None, share_x: bool = False,
                   share_y: bool = False, formats: Sequence[str] = ("png", "pdf", "tiff"),
                   dpi: int = 600, title: str | None = None) -> dict:
    """Assemble several panels into ONE publication figure.

    Parameters
    ----------
    panels:
        List of dicts::

            {"draw": callable(ax),        # required: draw the panel on this axes
             "label": "(a)",              # optional; default runs (a), (b), ...
             "title": "分罪名",            # optional panel title
             "xlabel": "...", "ylabel": "...",
             "legend": {"loc": "upper right", "frameon": False}}  # optional

        The callable receives the axes created inside the GridSpec; it must not
        save the figure itself.
    out_dir / name / formats / dpi:
        Passed to the writer. ``out_dir=None`` measures and returns without
        writing anything (useful in tests).
    nrows / ncols:
        Grid shape. Unused cells in the last row stay blank.
    width_cm / height_cm:
        Physical canvas. ``width_cm`` defaults to the 15 cm journal column. When
        ``height_cm`` is ``None`` a panel height of ~0.74 x panel width is used.
    panel_w_cm:
        Per-panel width instead of a total width: ``width_cm`` becomes
        ``panel_w_cm * ncols``.
    label_style:
        Panel-label format: ``"(a)"``, ``"a)"``, ``"a."``, ``"a"`` (upper-case
        variants keep the case).
    space:
        Float (applied to both wspace/hspace) or a dict of ``subplots_adjust``
        keys (``left/right/top/bottom/wspace/hspace``).
    share_x / share_y:
        Share tick ranges per column / per row.
    title:
        Optional figure title drawn above the grid.

    Returns
    -------
    dict with ``fig`` (left OPEN: close it yourself), ``paths``,
    ``panel_sizes_cm`` (one ``[w, h]`` per panel), ``min_fontsize_pt`` (smallest
    font actually rendered), ``width_cm``, ``height_cm``, plus ``dpi``,
    ``px_width`` and a ``note`` string for the chart manifest.

    Notes
    -----
    Layout uses ``GridSpec`` + explicit ``subplots_adjust``; ``bbox_inches="tight"``
    is never used because it crops the canvas and silently lowers the resolution
    QA measures (884 -> 724 px). The PNG is read back after writing and a
    ``RuntimeError`` is raised when ``px / (width_cm / 2.54)`` does not
    reproduce ``dpi`` within 1 dpi.
    """
    panels = list(panels or [])
    if not panels:
        raise ValueError("compose_figure needs at least one panel")
    nrows, ncols = int(nrows), int(ncols)
    if nrows <= 0 or ncols <= 0:
        raise ValueError("nrows and ncols must be positive")
    if len(panels) > nrows * ncols:
        raise ValueError(f"{len(panels)} panel(s) do not fit in {nrows}x{ncols}")
    for i, panel in enumerate(panels):
        if not isinstance(panel, dict) or not callable(panel.get("draw")):
            raise TypeError(f"panel {i} must be a dict with a callable 'draw'")

    if panel_w_cm:
        width_cm = float(panel_w_cm) * ncols
    width_cm = float(width_cm)
    if width_cm <= 0:
        raise ValueError("width_cm must be positive")
    if height_cm is None:
        per_row = (float(panel_w_cm) if panel_w_cm else width_cm / ncols) * 0.74
        height_cm = per_row * nrows + (0.85 if title else 0.15)
    height_cm = float(height_cm)
    if height_cm <= 0:
        raise ValueError("height_cm must be positive")

    try:
        if float(plt.rcParams.get("font.size", 10.0)) == 10.0:
            set_style(width_cm)  # caller did not configure the house style
    except (TypeError, ValueError):  # pragma: no cover
        pass
    base_size = _rc_size("axes.labelsize", 8.5)

    fig = plt.figure(figsize=(width_cm * CM, height_cm * CM))
    try:
        fig.set_layout_engine("none")
    except Exception:  # pragma: no cover - older matplotlib
        pass
    grid = fig.add_gridspec(nrows, ncols)
    adjust = {"left": 0.085, "right": 0.985, "bottom": 0.115,
              "top": 0.885 if title else 0.950, "wspace": 0.35, "hspace": 0.48}
    if isinstance(space, dict):
        adjust.update({k: float(v) for k, v in space.items() if k in adjust})
    elif space is not None:
        adjust["wspace"] = adjust["hspace"] = float(space)
    fig.subplots_adjust(**adjust)

    axes: list = []
    first_in_col: dict[int, object] = {}
    first_in_row: dict[int, object] = {}
    for index, panel in enumerate(panels):
        row, col = divmod(index, ncols)
        shared = {}
        if share_x and col in first_in_col:
            shared["sharex"] = first_in_col[col]
        if share_y and row in first_in_row:
            shared["sharey"] = first_in_row[row]
        ax = fig.add_subplot(grid[row, col], **shared)
        first_in_col.setdefault(col, ax)
        first_in_row.setdefault(row, ax)
        axes.append(ax)

    letters = _panel_letters(len(panels), label_style)
    for index, (ax, panel) in enumerate(zip(axes, panels)):
        try:
            panel["draw"](ax)
        except Exception as exc:
            raise RuntimeError(
                f"panel {index} ({panel.get('label') or letters[index]}) failed to draw: "
                f"{type(exc).__name__}: {exc}") from exc
        if panel.get("xlabel"):
            ax.set_xlabel(str(panel["xlabel"]))
        if panel.get("ylabel"):
            ax.set_ylabel(str(panel["ylabel"]))
        if panel.get("title"):
            ax.set_title(str(panel["title"]), fontsize=base_size, pad=3)
        label = panel.get("label") or letters[index]
        if label:
            ax.text(-0.02 if index % ncols == 0 else 0.0, 1.035, str(label),
                    transform=ax.transAxes, fontsize=panel_letter_size(base_size),
                    fontweight="bold", ha="left", va="bottom", color=INK)
        legend_spec = panel.get("legend")
        if legend_spec:
            if isinstance(legend_spec, dict):
                ax.legend(**legend_spec)
            else:
                ax.legend()

    # A legend anchored above the axes overlaps the panel it belongs to; lift it
    # above the top edge, then let the margins absorb whatever still overhangs.
    # A panel title would then collide with the lifted legend, so the whole row's
    # titles move above the legend (titles stay level across the row).
    title_pad_by_row: dict[int, float] = {}
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        inverse = fig.transFigure.inverted()
        for index, ax in enumerate(axes):
            legend = ax.get_legend()
            if legend is None:
                continue
            box = legend.get_window_extent(renderer).transformed(inverse)
            abox = ax.get_window_extent(renderer).transformed(inverse)
            if float(box.y1) > float(abox.y1) + 1e-6 and float(box.y1) > float(abox.y0):
                _lift_above_legend(ax)
                if panels[index].get("title"):
                    fig.canvas.draw()
                    box = legend.get_window_extent(renderer).transformed(inverse)
                    abox = ax.get_window_extent(renderer).transformed(inverse)
                    height_in = float(fig.get_size_inches()[1])
                    pad = (float(box.y1) - float(abox.y1)) * height_in * 72.0 + 2.0
                    row = index // ncols
                    title_pad_by_row[row] = max(title_pad_by_row.get(row, 0.0), pad)
    except Exception:  # pragma: no cover
        pass
    for index, ax in enumerate(axes):
        panel_title = panels[index].get("title")
        pad = title_pad_by_row.get(index // ncols)
        if panel_title and pad:
            ax.set_title(str(panel_title), fontsize=base_size, pad=max(3.0, pad))

    for _ in range(4):
        dx, dy = _legend_overhang(fig, axes)
        if max(dx, dy) <= 1e-4:
            break
        pars = fig.subplotpars
        new_top = max(0.55, float(pars.top) - (dy + 0.008) * 1.2)
        new_right = max(0.75, float(pars.right) - (dx + 0.008) * 1.2)
        if new_top >= float(pars.top) - 1e-6 and new_right >= float(pars.right) - 1e-6:
            break
        fig.subplots_adjust(top=new_top, right=new_right)

    if title:
        fig.suptitle(str(title), fontsize=base_size + 0.5, y=0.985)

    used_colors = _collect_colors(axes)
    panel_sizes = _measure_panel_sizes_cm(fig, axes)
    min_fontsize = _measure_min_fontsize(fig, axes)
    pars = fig.subplotpars

    paths: list[str] = []
    if out_dir:
        paths = _write_formats(fig, out_dir, name, formats, dpi)

    px_width = None
    png_path = next((p for p in paths if str(p).lower().endswith(".png")), None)
    if png_path:
        try:
            from PIL import Image
            with Image.open(png_path) as image:
                px_width = int(image.size[0])
        except Exception:  # pragma: no cover - PIL missing
            px_width = None
        if px_width is not None:
            measured = px_width / (width_cm * CM) if width_cm else 0.0
            if abs(measured - float(dpi)) > 1.0:
                raise RuntimeError(
                    f"compose_figure: {name}.png is {px_width}px at {width_cm:g} cm, "
                    f"i.e. {measured:.1f} dpi instead of {dpi}")
    elif width_cm:
        px_width = int(round(width_cm * CM * float(dpi)))

    return {
        "fig": fig,
        "paths": paths,
        "panel_sizes_cm": panel_sizes,
        "colors": used_colors,
        "min_fontsize_pt": min_fontsize,
        "width_cm": round(width_cm, 3),
        "height_cm": round(height_cm, 3),
        "dpi": int(dpi),
        "px_width": px_width,
        "nrows": nrows,
        "ncols": ncols,
        "top": round(float(pars.top), 3),
        "right": round(float(pars.right), 3),
        "left": round(float(pars.left), 3),
        "bottom": round(float(pars.bottom), 3),
        "note": f"panel={nrows}x{ncols}; top={float(pars.top):.3f}; "
                f"right={float(pars.right):.3f}",
    }


def _clip_huge_span(ax, est, lo, hi, ref: float = 1.0,
                    max_decades: float = 8.0) -> bool:
    """P-04: keep one quasi-separated CI from flattening the whole forest plot.

    A coefficient sitting on a near-empty cell can carry a bound around
    ``OR ≈ 1e9``.  On a log axis that stretches the scale over nine decades and
    every other interval collapses into a dot.  When the log span of the bounds
    exceeds ``max_decades`` the x limits are trimmed around the median
    estimate (always keeping ``ref`` visible) and a short note is drawn, so the
    reader sees that some intervals run off the axis instead of silently losing
    them.

    Returns ``True`` when the axis was trimmed.
    """
    vals = np.asarray(list(lo), dtype=float).tolist() + \
        np.asarray(list(hi), dtype=float).tolist() + [float(ref)]
    pos = np.asarray([v for v in vals if np.isfinite(v) and v > 0], dtype=float)
    if len(pos) < 2:
        return False
    span = float(np.log10(pos.max()) - np.log10(pos.min()))
    if span <= max_decades:
        return False
    est_pos = [v for v in np.asarray(list(est), dtype=float)
               if np.isfinite(v) and v > 0]
    mid = float(np.median(np.log10(est_pos))) if est_pos else \
        float(np.median(np.log10(pos)))
    left = float(np.log10(pos.min()))
    right = float(np.log10(pos.max()))
    half = max_decades / 2.0 - 0.5
    x0 = max(left, mid - half)
    x1 = min(right, mid + half)
    ref_log = float(np.log10(ref)) if ref > 0 else None
    if ref_log is not None:
        x0 = min(x0, ref_log)
        x1 = max(x1, ref_log)
    if x1 > x0:
        ax.set_xlim(10.0 ** x0, 10.0 ** x1)
    ax.text(0.995, 0.012, "部分 CI 超出显示范围", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=7.4, color=GRAY)
    return True


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
    """Draw a forest plot with solid significant / hollow non-significant points.

    Parameters
    ----------
    ax: target axes.
    labels: one row label per estimate (``pubfig.short_label`` keeps dummy
        levels readable).
    estimates / lows / highs: point estimate and 95% CI bounds. Rows with a
        non-finite value are dropped; an empty set writes a placeholder note.
    ref: null value of the effect scale (1 for OR/HR/RR, 0 for β).
    log_scale: draw the x axis on a log scale. Refused automatically (and the
        axis switched to linear) when any bound is <= 0 — a log axis cannot show
        a negative β. When enabled, minor ticks are switched off and the major
        ticks are pinned to ``{x:g}`` labels (CONTRACTS §7). A span wider than
        8 decades (a nearly separated dummy, ``OR ≈ 1e9``) is clipped around the
        median estimate with a "部分 CI 超出显示范围" note instead of letting one
        row flatten every other interval.
    xlabel: x axis label.
    color_sig / color_ns: fill / edge colours for significant and
        non-significant rows.
    marker_size: scatter marker area in points².
    """
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
        # P-04: a CI spanning > 8 decades (quasi-separation, OR ≈ 1e9) is
        # clipped with an explicit note rather than allowed to flatten the plot.
        _clip_huge_span(ax, est, lo, hi, ref)
    ax.set_xlabel(xlabel)
    style_axis(ax, "x")
    if log_scale:
        # P-07: a log axis keeps its minor ticks and mixed scientific labels
        # unless they are switched off after the scale is applied.
        _fix_log_ticks(ax)


def bar_with_ci(ax, labels: Sequence[str], estimates: Iterable[float],
                lows: Iterable[float], highs: Iterable[float],
                color: str = BLUE, width: float = 0.62,
                ylim_headroom: float = 0.08,
                annotate: bool = False,
                fmt: str = "{:.3g}") -> None:
    """Bar chart with 95% CI error bars.

    Parameters
    ----------
    ax: target axes.
    labels: one bar label per estimate.
    estimates / lows / highs: bar height and 95% CI bounds.
    color / width: bar fill colour and bar width in category units.
    ylim_headroom: fraction of the tallest upper CI bound added above the bars
        so the caps are never clipped by the axes frame. ``0`` disables the
        y-limit (legacy behaviour). Only applied when every value is >= 0.
    annotate: write the estimate above each upper CI bound; the text is placed
        just above the cap, inside the headroom reserved above, so it never
        overlaps the error bar.
    fmt: format string for the annotation (default ``"{:.3g}"``).
    """
    est = np.asarray(list(estimates), dtype=float)
    lo = np.asarray(list(lows), dtype=float)
    hi = np.asarray(list(highs), dtype=float)
    x = np.arange(len(labels))
    ax.bar(x, est, width=width, color=color, edgecolor="none", zorder=2)
    ax.errorbar(x, est, yerr=[est - lo, hi - est], fmt="none",
                ecolor=INK, elinewidth=0.8, capsize=2.2, zorder=3)
    finite = np.isfinite(est) & np.isfinite(lo) & np.isfinite(hi)
    top = float(np.nanmax(hi[finite])) if finite.any() else float("nan")
    floor = float(np.nanmin(np.r_[est[finite], lo[finite]])) if finite.any() else float("nan")
    if ylim_headroom and ylim_headroom > 0 and np.isfinite(top) and top > 0 \
            and np.isfinite(floor) and floor >= 0:
        ax.set_ylim(0, top * (1 + float(ylim_headroom)))
    if annotate:
        offset = max((ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.012, 1e-9)
        for xx, e, h in zip(x, est, hi):
            if not np.isfinite(h):
                continue
            ax.text(xx, h + offset, fmt.format(float(e)), ha="center",
                    va="bottom", fontsize=7.4, color=INK)
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
                legend: bool = True, legend_loc: str = "upper center",
                legend_anchor: tuple[float, float] | None = None,
                adjust_top: bool = True, ncol: int | None = None) -> float | None:
    """Stacked bar / 100% stacked bar.

    Parameters
    ----------
    ax: target axes.
    row_labels: one label per bar (category on x, or y when ``horizontal``).
    series: one array per stack, all the same length as ``row_labels``.
    series_labels: legend label of each stack.
    colors: palette; cycled when there are more stacks than colours.
    normalize: divide each bar by its total (100% stacked bar).
    horizontal: draw horizontal bars.
    legend: draw the legend at all.
    legend_loc: matplotlib legend ``loc``; default ``"upper center"``.
    legend_anchor: ``bbox_to_anchor``; default ``(0.5, 1.02)`` — just above the
        axes but *inside* the canvas. The old hard-coded ``1.16`` pushed the
        legend outside the figure, and because ``save_fig`` must not use
        ``bbox_inches="tight"`` (it lowers the effective dpi, CONTRACTS §7) the
        legend was cropped out of the PNG.
    adjust_top: measure the legend after drawing and lower
        ``fig.subplotpars.top`` until it fits on the canvas.
    ncol: legend columns; default ``min(number of stacks, 4)``.

    Returns
    -------
    float | None
        The ``subplotpars.top`` actually used (``None`` when no legend and no
        adjustment was made).
    """
    labels = list(row_labels)
    mats = [np.asarray(list(s), dtype=float) for s in series]
    if normalize:
        totals = np.sum(mats, axis=0)
        totals[totals == 0] = 1
        mats = [m / totals for m in mats]
    palette = list(colors or CATEGORICAL)
    if len(series_labels) > len(palette):
        warnings.warn(
            f"{len(series_labels)} series cycle a {len(palette)}-colour palette; "
            "at least two series share a colour", RuntimeWarning, stacklevel=2)
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
    top = None
    if legend:
        leg = ax.legend(frameon=False, ncol=ncol or min(len(series_labels), 4),
                        loc=legend_loc,
                        bbox_to_anchor=(0.5, 1.02) if legend_anchor is None else legend_anchor)
        if adjust_top:
            top = _fit_legend(ax, leg)
    return top


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
                        fontsize=7.4, color="white" if val > vmid else INK)
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
                        fontsize=7.4, color="white" if abs(val) > 0.55 else INK)
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
    if logx:
        _fix_log_ticks(ax, axis="x")
    if logy:
        _fix_log_ticks(ax, axis="y")
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
                     bins: int = 10, color: str = BLUE,
                     annotate_n: bool = False) -> None:
    """Calibration curve: observed rate vs mean predicted probability.

    Parameters
    ----------
    ax: target axes.
    y_true: binary outcome (0/1, bool, or mapped text labels).
    y_prob: predicted probability per observation.
    bins: number of quantile bins (fewer when the probabilities tie).
    color: line/marker colour.
    annotate_n: write the bin size next to each point.

    Notes
    -----
    The last bin is closed on both ends (``p == max`` belongs to it); the old
    ``(p >= lo) & (p < hi)`` loop silently dropped the highest-risk
    observation(s), which is exactly the point a calibration plot is read for.
    """
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
        # searchsorted-right minus one puts p == max into the last bin and
        # keeps every observation in exactly one bin.
        idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
        for b in range(len(edges) - 1):
            m = idx == b
            if m.sum() == 0:
                continue
            xs.append(float(p[m].mean()))
            ys.append(float(y[m].mean()))
            ns.append(int(m.sum()))
    ax.plot([0, 1], [0, 1], color=LGRAY, linewidth=0.6, linestyle=(0, (2, 2)))
    ax.plot(xs, ys, color=color, marker="o", markersize=3.5, linewidth=0.9)
    if annotate_n:
        for xx, yy, nn in zip(xs, ys, ns):
            ax.annotate(f"n={nn}", (xx, yy), xytext=(4, -8),
                        textcoords="offset points", fontsize=7.4, color=INK)
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
                    fontsize=7.4, color=INK)
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
        ax.text(-0.03, a, f"{lab} {a:.1f}", ha="right", va="center", fontsize=7.4)
        ax.text(1.03, b, f"{b:.1f}", ha="left", va="center", fontsize=7.4)
    ax.set_xlim(-0.25, 1.2)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([left_label, right_label])
    style_axis(ax, "y")


def stacked_area(ax, x: Sequence[float], series: Sequence[Iterable[float]],
                 series_labels: Sequence[str], colors: Sequence[str] | None = None,
                 normalize: bool = True, alpha: float = 0.9,
                 legend_loc: str = "upper center",
                 legend_anchor: tuple[float, float] | None = None,
                 adjust_top: bool = True, ncol: int | None = None) -> float | None:
    """Stacked area chart (e.g. treatment composition over years).

    Parameters
    ----------
    ax: target axes.
    x: numeric x values, or categorical values (they are position-encoded).
    series: one array per band, all the same length as ``x``.
    series_labels: legend label of each band.
    colors: palette; cycled when there are more bands than colours.
    normalize: divide each x position by its total (composition, y limits 0–1).
    alpha: band transparency.
    legend_loc: matplotlib legend ``loc``; default ``"upper center"``.
    legend_anchor: ``bbox_to_anchor``; default ``(0.5, 1.02)`` (inside canvas).
    adjust_top: shrink the axes until the legend fits on the canvas.
    ncol: legend columns; default ``min(number of bands, 4)``.

    Returns
    -------
    float | None
        The ``subplotpars.top`` actually used, or ``None`` without adjustment.
    """
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
    palette = list(colors or CATEGORICAL)
    if len(series_labels) > len(palette):
        warnings.warn(
            f"{len(series_labels)} bands cycle a {len(palette)}-colour palette; "
            "at least two bands share a colour", RuntimeWarning, stacklevel=2)
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
    leg = ax.legend(frameon=False, ncol=ncol or min(len(series_labels), 4),
                    loc=legend_loc,
                    bbox_to_anchor=(0.5, 1.02) if legend_anchor is None else legend_anchor)
    if not adjust_top:
        return None
    return _fit_legend(ax, leg)


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
                    fontsize=7.4, color=INK)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    style_axis(ax, "both")


def pie_chart(ax, labels: Sequence[str], values: Iterable[float],
              colors: Sequence[str] | None = None, donut: bool = True,
              max_categories: int = 6, min_pct: float = 0.8,
              sort: bool = True, label_threshold: float = 0.0) -> None:
    """Part-to-whole pie/donut.

    Parameters
    ----------
    ax: target axes.
    labels: one label per slice.
    values: slice sizes; non-finite and non-positive values are dropped.
    colors: palette; cycled when there are more slices than colours.
    donut: draw a donut (white centre + ``N=`` total) instead of a pie.
    max_categories: kept slices before the tail is merged into ``"其他"``.
    min_pct: smallest percentage that gets an in-slice ``%`` label
        (below it the slice still exists, only the number is hidden).
    sort: order slices from largest to smallest.
    label_threshold: share of the total (0–1) below which a slice is merged
        into ``"其他"``. Slices under the threshold crowd the legend with
        one-figure categories; ``0`` keeps every slice (legacy behaviour).
    """
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
    if label_threshold and label_threshold > 0:
        share = vals / float(vals.sum())
        keep = share >= float(label_threshold)
        if not keep.all() and keep.any():
            rest = float(vals[~keep].sum())
            vals = np.r_[vals[keep], rest]
            labs = [l for l, k in zip(labs, keep) if k] + ["其他"]
    total = vals.sum()
    palette = list(colors or CATEGORICAL)
    if len(vals) > len(palette):
        warnings.warn(
            f"{len(vals)} slices cycle a {len(palette)}-colour palette; "
            "at least two slices share a colour", RuntimeWarning, stacklevel=2)
    palette = (palette * (len(vals) // len(palette) + 1))[:len(vals)]
    wedges, _, autotexts = ax.pie(
        vals, labels=None, colors=palette, startangle=90, counterclock=False,
        autopct=lambda p: f"{p:.0f}%" if p >= min_pct else "",
        pctdistance=0.75, wedgeprops={"linewidth": 0.6, "edgecolor": "white"},
        textprops={"fontsize": 7.4},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontsize(7.4)
    ax.legend(wedges, [f"{l}（{v / total * 100:.1f}%）" for l, v in zip(labs, vals)],
              frameon=False, fontsize=7.4, loc="center left",
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
    ax.legend(frameon=False, fontsize=7.4, loc="best")


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
        palette = list(CATEGORICAL)
        for i, level in enumerate(g.value_counts().head(6).index):
            m = (g == level).to_numpy()
            ax.scatter(xy[m, 0], xy[m, 1], s=9, alpha=0.45, linewidths=0,
                       color=palette[i % len(palette)], label=str(level))
        ax.legend(frameon=False, fontsize=7.4, loc="best")
    else:
        ax.scatter(xy[:, 0], xy[:, 1], s=9, alpha=0.4, color=BLUE, linewidths=0)
    if labels is not None and len(labels) == xy.shape[0] and len(labels) <= 20:
        for i, lab in enumerate(labels):
            ax.annotate(str(lab), (xy[i, 0], xy[i, 1]), xytext=(3, 3),
                        textcoords="offset points", fontsize=7.4, color=INK)
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
    """Decile lift chart; returns per-bin counts and lift.

    Bin 1 (``D1``) is the **highest** predicted-probability decile, matching the
    axis label. The old code ranked the raw score ascending, so ``D1`` was the
    *lowest*-risk decile while the axis still claimed "D1=最高" — the chart read
    backwards.
    """
    y = binary_array(y_true)
    s = pd.to_numeric(pd.Series(list(y_score)), errors="coerce").to_numpy(float)
    mask = np.isfinite(y) & np.isfinite(s)
    y, s = y[mask], s[mask]
    if len(y) < bins or len(np.unique(y)) < 2:
        ax.text(0.5, 0.5, "样本不足或单一类别", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)
        ax.set_axis_off()
        return pd.DataFrame()
    # rank(-score): rank 1 = highest score, so bin 0 (=D1) = highest risk.
    ranks = pd.qcut(pd.Series(-s).rank(method="first"), bins, labels=False).to_numpy()
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
    ax.legend(frameon=False, fontsize=7.4)
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
    palette = list(CATEGORICAL)
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
        ax.legend(frameon=False, fontsize=7.4, loc="best")
