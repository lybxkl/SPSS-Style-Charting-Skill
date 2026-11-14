# -*- coding: utf-8 -*-
"""Reconcile what a matplotlib figure *actually drew* with the data behind it.

The v2 contract already has a ``figure_spec`` record, but a record is only
evidence if its values were read back from the artists.  This module is that
reading step:

* :func:`describe_axes` walks every ``Axes`` and reports real artist values
  (``get_height``/``get_x``/``get_y``/``get_window_extent``), never the
  arguments the caller once passed to ``bar``/``plot``/``scatter``.
* :func:`check_figure` compares those readings with a declared mapping
  (``{"type": "bar", "x": "group", "y": "score"}``): bar heights against
  per-category means, error-bar lengths against SD/SE, scatter counts against
  the non-missing row count, line point order, category tick text and legend
  entry counts.  Rows that cannot be drawn (missing/invalid) are dropped
  *explicitly* and reported, never silently.
* :func:`label_geometry` measures x tick labels with the real renderer and
  counts overlapping adjacent labels.  It reports; it never "fixes" a crowded
  axis by deleting labels, truncating text or shrinking the font.
* :func:`layout_options` turns the measured geometry into actionable options
  (rotate / expand / widen / subplot) with the measurement that supports each
  one.
* :func:`palette_report` reports the colours that are really used and a
  *heuristic* role (sequential/diverging/categorical/single).  Every remark it
  makes is a suggestion; nothing here can fail a figure.
* :func:`record_figure` writes the ``figure_spec`` v2 record; :func:`check_saved`
  measures an exported PNG/PDF and compares it with that declaration.

Things this module deliberately cannot judge are returned in ``unverifiable``
with a reason: a stand-alone bitmap has no vector element list, 3D axes cannot
be inverted back to data coordinates, contour bands only expose their levels,
and a raster image's pixels are not the plotted data table.

CLI::

    python figsemantics.py --root . inspect --figure mymod:make_figure
    python figsemantics.py --root . inspect --figure figure_spec.json
    python figsemantics.py --root . check F1 [--png ...] [--pdf ...]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from matplotlib.colors import to_hex, to_rgba
from matplotlib.container import BarContainer, ErrorbarContainer

from contract_v2 import (
    Project,
    StatusTransitionError,
    check_transition,
    make_record,
    producer_for,
)

__version__ = "2.0"

CM_PER_INCH = 2.54
#: The only layout actions this module may recommend.  Deleting categories,
#: truncating labels and shrinking the font are not on the list on purpose.
LAYOUT_OPTIONS = ("rotate", "expand", "widen", "subplot")
MIN_DPI = 300          #: widely used journal minimum for raster artwork
OVERLAP_TOLERANCE_PX = 0.5


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------
def _get_renderer(fig):
    """Draw ``fig`` and return ``(renderer, problem)``.

    ``problem`` is a human-readable reason when no renderer exists; callers
    must then treat text geometry as unverifiable instead of guessing.
    """
    try:
        fig.canvas.draw()
    except Exception as exc:                       # pragma: no cover - backend
        return None, f"canvas draw failed: {type(exc).__name__}: {exc}"
    try:
        return fig.canvas.get_renderer(), None
    except AttributeError:                         # pragma: no cover - backend
        return None, ("the active canvas has no get_renderer(); tick/text "
                      "geometry cannot be measured on this backend")


def _json_safe(value: Any) -> Any:
    """Convert numpy/float values to plain JSON, mapping non-finite to null.

    ``contract_v2.canonical_json`` refuses NaN/Infinity, and a record that
    cannot be hashed is worse than a record with an explicit ``null``.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _resolve_rgba(value) -> tuple[float, float, float, float] | None:
    """RGBA for a real colour spec, resolving the ``C0``..``C9`` cycle."""
    if value is None:
        return None
    try:
        return tuple(float(c) for c in to_rgba(value))       # type: ignore[arg-type]
    except (ValueError, TypeError):
        pass
    match = re.fullmatch(r"C(\d+)", str(value).strip())
    if match:
        import matplotlib as mpl
        cycle = mpl.rcParams.get("axes.prop_cycle")
        colors = list(cycle.by_key().get("color", [])) if cycle is not None else []
        if colors:
            return tuple(float(c) for c in
                         to_rgba(colors[int(match.group(1)) % len(colors)]))
    return None


def _hex_color(value) -> str | None:
    rgba = _resolve_rgba(value)
    if rgba is None or rgba[3] <= 0:
        return None
    return to_hex(rgba, keep_alpha=rgba[3] < 0.999).upper()


def _effective_alpha(artist, rgba) -> float:
    base = float(rgba[3]) if rgba is not None else 1.0
    own = artist.get_alpha()
    if own is not None:
        try:
            base = float(own)
        except (TypeError, ValueError):
            pass
    return base


def _rgb_to_lab(rgba: Sequence[float]) -> tuple[float, float, float]:
    """sRGB (0..1) -> CIELAB (D65).  Used only for palette advice."""
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else \
            ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(float(c)) for c in rgba[:3])
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def _unique_order(values: Iterable[Any]) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        if not any(value == item for item in seen):
            seen.append(value)
    return seen


def _category_key(value: Any) -> tuple[str, Any]:
    """Compare a data category with a rendered tick label without formatting noise.

    ``1`` / ``1.0`` / ``"1"`` must be the same category; ``"A"`` and ``"a"``
    must not.
    """
    if isinstance(value, (bool, np.bool_)):
        return ("str", str(value))
    if isinstance(value, (int, float, np.integer, np.floating)):
        try:
            return ("num", round(float(value), 12))
        except (TypeError, ValueError):
            return ("str", str(value))
    text = str(value).strip()
    try:
        return ("num", round(float(text), 12))
    except (TypeError, ValueError):
        return ("str", text)


def _close(a: float | None, b: float | None, rel: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    if not (math.isfinite(float(a)) and math.isfinite(float(b))):
        return False
    left, right = float(a), float(b)
    return abs(left - right) <= max(1e-12, rel * max(abs(left), abs(right)))


def _check(checks: list[dict], name: str, ok: bool, expected, observed,
           detail: str, subject: Mapping | None = None) -> None:
    item = {"check": name, "ok": bool(ok), "expected": _json_safe(expected),
            "observed": _json_safe(observed), "detail": detail}
    if subject is not None:
        item["subject"] = _json_safe(dict(subject))
    checks.append(item)


# ---------------------------------------------------------------------------
# describe_axes: read the artists, not the call arguments
# ---------------------------------------------------------------------------
def _text_record(text, renderer) -> dict:
    box = None
    if renderer is not None:
        try:
            bbox = text.get_window_extent(renderer)
            box = [float(bbox.x0), float(bbox.y0),
                   float(bbox.x1), float(bbox.y1)]
        except Exception:                          # pragma: no cover - backend
            box = None
    rgba = _resolve_rgba(text.get_color())
    return {
        "text": text.get_text(),
        "fontsize": float(text.get_fontsize()),
        "rotation": float(text.get_rotation()),
        "rotation_mode": str(text.get_rotation_mode()),
        "ha": str(text.get_ha()),
        "va": str(text.get_va()),
        "color": _hex_color(text.get_color()),
        "alpha": _effective_alpha(text, rgba),
        "bbox_px": box,
    }


def _tick_pairs(ax, direction: str):
    """Visible major ticks inside the axis limits, as ``(position, Text)``."""
    axis = ax.xaxis if direction == "x" else ax.yaxis
    limits = ax.get_xlim() if direction == "x" else ax.get_ylim()
    lower, upper = sorted(float(v) for v in limits)
    out = []
    for position, tick in zip(axis.get_majorticklocs(), axis.get_ticklabels()):
        if not (lower - 1e-9 <= float(position) <= upper + 1e-9):
            continue    # the locator proposes ticks just outside the view
        if tick.get_visible() and tick.get_text():
            out.append((float(position), tick))
    return out


def _legend_entries(ax) -> list[dict] | None:
    legend = ax.get_legend()
    if legend is None:
        return None
    handles = list(getattr(legend, "legend_handles", None)
                   or getattr(legend, "legendHandles", []) or [])
    entries = []
    for index, text in enumerate(legend.get_texts()):
        record = {"label": text.get_text()}
        if index < len(handles):
            handle = handles[index]
            try:
                if hasattr(handle, "get_facecolor"):
                    record["facecolor"] = _hex_color(handle.get_facecolor())
                if hasattr(handle, "get_edgecolor"):
                    record["edgecolor"] = _hex_color(handle.get_edgecolor())
                if hasattr(handle, "get_color"):
                    record["color"] = _hex_color(handle.get_color()) \
                        or record.get("facecolor")
                if hasattr(handle, "get_marker"):
                    marker = str(handle.get_marker())
                    record["marker"] = None if marker in ("None", "none", "") else marker
            except Exception:                      # pragma: no cover - proxy
                pass
        entries.append(record)
    return entries


def _errorbar_entries(container: ErrorbarContainer) -> list[dict]:
    """Real error-bar extents from the drawn ``LineCollection`` segments."""
    entries: list[dict] = []
    try:
        collections = container.lines[2]
    except (AttributeError, IndexError):
        return entries
    for collection in collections or ():
        try:
            segments = collection.get_segments()
        except Exception:                          # pragma: no cover - defensive
            continue
        for segment in segments:
            if len(segment) < 2:
                continue
            (x0, y0), (x1, y1) = segment[0], segment[1]
            if abs(float(y1) - float(y0)) >= abs(float(x1) - float(x0)):
                entries.append({
                    "orientation": "vertical",
                    "x": (float(x0) + float(x1)) / 2.0,
                    "y": (float(y0) + float(y1)) / 2.0,
                    "low": min(float(y0), float(y1)),
                    "high": max(float(y0), float(y1)),
                    "length": abs(float(y1) - float(y0)),
                })
            else:
                entries.append({
                    "orientation": "horizontal",
                    "x": (float(x0) + float(x1)) / 2.0,
                    "y": (float(y0) + float(y1)) / 2.0,
                    "low": min(float(x0), float(x1)),
                    "high": max(float(x0), float(x1)),
                    "length": abs(float(x1) - float(x0)),
                })
    return entries


def _describe_axis(ax, index: int, renderer, unverifiable: list[dict]) -> dict:
    bbox = ax.bbox
    entry: dict = {
        "index": index,
        "name": str(getattr(ax, "name", "")),
        "position": [float(v) for v in ax.get_position().bounds],
        "bbox_px": [float(bbox.x0), float(bbox.y0),
                    float(bbox.x1), float(bbox.y1)],
        "xlabel": ax.get_xlabel(),
        "ylabel": ax.get_ylabel(),
        "title": ax.get_title(),
        "xlim": [float(v) for v in ax.get_xlim()],
        "ylim": [float(v) for v in ax.get_ylim()],
        "xscale": ax.get_xscale(),
        "yscale": ax.get_yscale(),
        "bars": [],
        "lines": [],
        "collections": [],
        "errorbars": [],
        "texts": [],
        "xticklabels": [],
        "yticklabels": [],
        "legend": None,
        "images": [],
        "unverifiable": [],
    }

    for axis_name in ("x", "y"):
        for position, tick in _tick_pairs(ax, axis_name):
            record = _text_record(tick, renderer)
            record["position"] = position
            entry[f"{axis_name}ticklabels"].append(record)

    for text in list(ax.texts) + [ax.xaxis.label, ax.yaxis.label]:
        if not text.get_visible() or not text.get_text():
            continue
        entry["texts"].append(_text_record(text, renderer))
    if ax.get_title():
        entry["texts"].append(_text_record(ax.title, renderer))

    for container in list(ax.containers):
        if isinstance(container, BarContainer):
            orientation = str(getattr(container, "orientation", "vertical"))
            for patch in container.patches:
                if patch is None or not patch.get_visible():
                    continue
                face = _resolve_rgba(patch.get_facecolor())
                edge = _resolve_rgba(patch.get_edgecolor())
                entry["bars"].append({
                    "x": float(patch.get_x()),
                    "y": float(patch.get_y()),
                    "width": float(patch.get_width()),
                    "height": float(patch.get_height()),
                    "orientation": orientation,
                    "facecolor": _hex_color(patch.get_facecolor()),
                    "edgecolor": _hex_color(patch.get_edgecolor()),
                    "alpha": _effective_alpha(patch, face),
                    "edge_alpha": _effective_alpha(patch, edge),
                    "label": patch.get_label(),
                })
        elif isinstance(container, ErrorbarContainer):
            for item in _errorbar_entries(container):
                item["label"] = container.get_label()
                try:
                    item["color"] = _hex_color(container.lines[1][0].get_color())
                except Exception:                  # pragma: no cover - defensive
                    item["color"] = None
                entry["errorbars"].append(item)

    for line in list(ax.lines):
        if not line.get_visible():
            continue
        xdata = np.asarray(line.get_xdata(orig=False), dtype=float)
        ydata = np.asarray(line.get_ydata(orig=False), dtype=float)
        marker = str(line.get_marker())
        entry["lines"].append({
            "x": [float(v) for v in xdata],
            "y": [float(v) for v in ydata],
            "n_points": int(len(xdata)),
            "marker": None if marker in ("None", "none", "") else marker,
            "markersize": float(line.get_markersize()),
            "color": _hex_color(line.get_color()),
            "linestyle": str(line.get_linestyle()),
            "linewidth": float(line.get_linewidth()),
            "alpha": _effective_alpha(line, _resolve_rgba(line.get_color())),
            "label": line.get_label(),
        })

    for collection in list(ax.collections):
        name = type(collection).__name__
        record: dict = {"kind": name,
                        "visible": bool(collection.get_visible()),
                        "alpha": collection.get_alpha()}
        if "Contour" in name:
            record["levels"] = [float(v) for v in
                                np.asarray(getattr(collection, "levels", []),
                                           dtype=float)]
            entry["collections"].append(record)
            unverifiable.append({
                "axes": index, "what": "contour",
                "reason": ("contour bands only expose their levels; the "
                           "underlying grid values cannot be recovered from "
                           "the drawn polygons")})
            continue
        offsets = None
        try:
            offsets = np.asarray(collection.get_offsets(), dtype=float)
        except Exception:                          # pragma: no cover - defensive
            offsets = None
        if offsets is not None and offsets.ndim == 2 and offsets.shape[1] == 2:
            record["offsets"] = [[float(x), float(y)] for x, y in offsets]
            record["n_points"] = int(len(offsets))
        else:
            record["n_points"] = 0
        try:
            data = collection.get_array()
        except Exception:                          # pragma: no cover - defensive
            data = None
        if data is not None:
            record["mapped"] = True
            # A mapped collection takes its colours from the colour map at draw
            # time; there are no per-point facecolors on the artist itself.
            record["colors"] = []
            record["cmap"] = getattr(collection.get_cmap(), "name", None)
            try:
                record["vmin"], record["vmax"] = (
                    float(collection.norm.vmin), float(collection.norm.vmax))
            except Exception:                      # pragma: no cover - defensive
                record["vmin"] = record["vmax"] = None
        else:
            record["mapped"] = False
            colors = [_hex_color(c) for c in
                      np.asarray(collection.get_facecolors())] \
                if len(collection.get_facecolors()) else []
            record["facecolors"] = [c for c in colors if c]
            # "colors" is the name callers look for; facecolors is the artist
            # attribute it actually comes from.  Keep both for mapped and
            # unmapped collections so a report never has an empty colour field.
            record["colors"] = list(record["facecolors"])
            try:
                record["sizes"] = [float(v) for v in collection.get_sizes()]
            except Exception:                      # pragma: no cover - defensive
                record["sizes"] = []
            edges = [_hex_color(c) for c in
                     np.asarray(collection.get_edgecolors())] \
                if len(collection.get_edgecolors()) else []
            record["edgecolors"] = [c for c in edges if c]
        entry["collections"].append(record)

    for image in list(ax.images):
        if not image.get_visible():
            continue
        array = np.asarray(image.get_array())
        entry["images"].append({
            "shape": [int(v) for v in array.shape],
            "cmap": getattr(image.get_cmap(), "name", None),
            "vmin": float(image.norm.vmin) if image.norm.vmin is not None else None,
            "vmax": float(image.norm.vmax) if image.norm.vmax is not None else None,
            "interpolation": str(image.get_interpolation()),
            "alpha": image.get_alpha(),
        })
        unverifiable.append({
            "axes": index, "what": "image",
            "reason": ("a raster image's pixels are not the plotted data table; "
                       "colour map/vmin/vmax are reported but cell values "
                       "cannot be reconciled from the artist alone")})

    entry["legend"] = _legend_entries(ax)
    legend = ax.get_legend()
    if legend is not None and renderer is not None:
        try:
            legend_box = legend.get_window_extent(renderer)
            entry["legend_bbox_px"] = [float(legend_box.x0),
                                       float(legend_box.y0),
                                       float(legend_box.x1),
                                       float(legend_box.y1)]
        except Exception:                          # pragma: no cover - backend
            entry["legend_bbox_px"] = None

    if str(getattr(ax, "name", "")) == "3d":
        unverifiable.append({
            "axes": index, "what": "3d",
            "reason": ("a 3D projection cannot be inverted from the rendered "
                       "artists back to data coordinates; positions are only "
                       "readable in their native 3D data space")})
    return entry


def describe_axes(fig) -> dict:
    """Read every Axes of ``fig`` and return only values taken from artists.

    Returns ``{"figure": {...}, "axes": [...], "unverifiable": [...]}``.  Each
    axis carries ``bars``/``lines``/``collections``/``errorbars``/``texts``/
    ``xticklabels``/``yticklabels``/``legend`` exactly as the rendered figure
    has them; a value that is invisible is not invented.
    """
    renderer, problem = _get_renderer(fig)
    unverifiable: list[dict] = []
    if problem:
        unverifiable.append({"axes": None, "what": "renderer",
                             "reason": problem})
    axes = [_describe_axis(ax, index, renderer, unverifiable)
            for index, ax in enumerate(fig.axes)]
    width_in, height_in = (float(v) for v in fig.get_size_inches()[:2])
    return {
        "figure": {
            "size_in": [width_in, height_in],
            "size_cm": [width_in * CM_PER_INCH, height_in * CM_PER_INCH],
            "dpi": float(fig.dpi),
            "n_axes": len(fig.axes),
            "suptitle": fig.get_suptitle(),
        },
        "axes": axes,
        "unverifiable": unverifiable,
    }


# ---------------------------------------------------------------------------
# check_figure: data <-> drawn elements
# ---------------------------------------------------------------------------
def _as_frame(dataset):
    import pandas as pd
    if isinstance(dataset, pd.DataFrame):
        return dataset.copy()
    if isinstance(dataset, Mapping):
        return pd.DataFrame(dataset)
    return pd.DataFrame(list(dataset))


def _numeric_column(frame, column: str):
    """Coerce ``column`` to float; return ``(values, invalid_count)``."""
    import pandas as pd
    values = pd.to_numeric(frame[column], errors="coerce")
    invalid = int(values.isna().sum() - frame[column].isna().sum())
    return values, max(0, invalid)


def _legend_check(checks: list[dict], axis_desc: dict,
                  expected_labels: Sequence[str]) -> None:
    entries = axis_desc.get("legend")
    if entries is None:
        _check(checks, "legend_entries", False, len(expected_labels), 0,
               (f"no legend is drawn but {len(expected_labels)} group(s) are "
                f"declared; legend entry count cannot equal the group count"))
        return
    labels = [str(item.get("label", "")) for item in entries]
    expected = [str(v) for v in expected_labels]
    same = len(labels) == len(expected) and all(
        _same_label(a, b) for a, b in zip(labels, expected))
    if same:
        detail = f"legend has {len(labels)} entries matching the groups {expected}"
    elif len(labels) != len(expected):
        detail = (f"legend has {len(labels)} entries, data declares "
                  f"{len(expected)} group(s)")
    else:
        detail = f"legend labels {labels} do not match the groups {expected}"
    _check(checks, "legend_entries", same, expected, labels, detail)


def _same_label(a: str, b: str) -> bool:
    return a.strip() == b.strip() or _category_key(a) == _category_key(b)


def _category_label_check(checks: list[dict], axis_desc: dict,
                          expected_categories: Sequence[Any]) -> None:
    drawn = [t["text"] for t in axis_desc.get("xticklabels", [])]
    expected = [str(c) for c in expected_categories]
    if not drawn:
        _check(checks, "category_labels", False, expected, drawn,
               "no visible x tick labels; the categorical order cannot be read")
        return
    keys_equal = len(drawn) == len(expected) and all(
        _category_key(a) == _category_key(b) for a, b in zip(drawn, expected))
    detail = f"x tick labels {drawn} match the data categories {expected}"
    if not keys_equal:
        first = next((i for i, (a, b) in enumerate(zip(drawn, expected))
                      if _category_key(a) != _category_key(b)), None)
        if len(drawn) != len(expected):
            detail = (f"{len(drawn)} x tick labels for {len(expected)} data "
                      f"categories; drawn={drawn}")
        elif first is not None:
            detail = (f"first mismatch at position {first}: drawn "
                      f"{drawn[first]!r} != data {expected[first]!r} "
                      f"(order/spelling changed)")
    _check(checks, "category_labels", keys_equal, expected, drawn, detail)


def _cluster_by_tick(bars: Sequence[dict], axis_desc: dict, vertical: bool):
    """Assign every bar to a rendered x tick (its category) and sort within it."""
    ticks = sorted(((t["position"], t["text"])
                    for t in axis_desc.get("xticklabels", [])),
                   key=lambda item: item[0])
    if not ticks:
        return None
    centers = []
    for bar in bars:
        if vertical:
            centers.append(bar["x"] + bar["width"] / 2.0)
        else:
            centers.append(bar["y"] + bar["height"] / 2.0)
    spacing = (ticks[-1][0] - ticks[0][0]) / (len(ticks) - 1) if len(ticks) > 1 else 1.0
    clusters: dict[str, list[dict]] = {}
    for center, bar in zip(centers, bars):
        position, text = min(ticks, key=lambda item: abs(item[0] - center))
        if abs(position - center) > max(abs(spacing) * 0.6, 1e-6):
            continue    # a bar that sits on no tick is reported as extra
        clusters.setdefault(text, []).append((center, bar))
    return {text: [bar for _, bar in sorted(items, key=lambda item: item[0])]
            for text, items in clusters.items()}


def _ordered_categories(values: Iterable[Any], sorting: Any) -> list[Any]:
    """Data category order, honouring a declared ``sorting`` mapping field."""
    categories = _unique_order(values)
    key = str(sorting or "").strip().lower()
    if key in ("asc", "ascending", "sort_asc", "sorted"):
        return sorted(categories, key=lambda v: _category_key(v))
    if key in ("desc", "descending", "sort_desc", "reverse"):
        return sorted(categories, key=lambda v: _category_key(v), reverse=True)
    return categories


def _check_bar(dataset, mapping, axis_desc, checks, unverifiable):
    xcol, ycol = mapping["x"], mapping["y"]
    series = mapping.get("series")
    frame = dataset
    required = [xcol, ycol] + ([series] if series else [])
    missing = frame[required].isna().any(axis=1)
    dropped = int(missing.sum())
    data = frame.loc[~missing].copy()
    numeric, invalid = _numeric_column(data, ycol)
    if invalid:
        dropped += invalid
        data = data.loc[numeric.notna()].copy()
        numeric = numeric.loc[numeric.notna()]
    if data.empty:
        raise ValueError("check_figure: no complete rows left after dropping "
                         f"missing values in {required}")
    data[ycol] = numeric

    categories = _ordered_categories(data[xcol].tolist(), mapping.get("sorting"))
    series_names = _unique_order(data[series].tolist()) if series else [None]
    group_cols = [xcol] + ([series] if series else [])
    grouped = data.groupby(group_cols, sort=False, observed=True, dropna=False)
    means = grouped[ycol].mean()
    counts = grouped[ycol].count()
    stds = grouped[ycol].std(ddof=1)

    def gmap(series_obj) -> dict:
        out = {}
        for key, value in series_obj.items():
            if not isinstance(key, tuple):
                key = (key,)
            out[key] = float(value) if value == value else None
        return out

    mean_map, count_map, sd_map = gmap(means), gmap(counts), gmap(stds)

    def combo_key(category, group):
        return (category,) if not series else (category, group)

    # Only category/series combinations that really have rows are expected:
    # an unbalanced group is not a missing bar.
    expected_keys = [(cat, s) for cat in categories for s in series_names
                     if combo_key(cat, s) in mean_map]
    expected_centers = [(cat, s, mean_map.get(combo_key(cat, s)),
                         count_map.get(combo_key(cat, s)))
                        for cat, s in expected_keys]
    errors_declared = bool(mapping.get("error"))
    error_kind = ""
    if errors_declared:
        error_kind = str((mapping.get("error") or {}).get("kind", "sd")).lower()
        if error_kind in ("std", "sd"):
            error_kind = "sd"
        elif error_kind in ("sem", "se"):
            error_kind = "se"
        else:
            unverifiable.append({
                "what": "error.kind", "reason": f"error kind {error_kind!r} is "
                                                "not implemented (sd/se only)"})
            errors_declared = False

    bars = axis_desc.get("bars", [])
    vertical = all(bar["orientation"] == "vertical" for bar in bars) if bars else True

    _category_label_check(checks, axis_desc, categories)

    clusters = _cluster_by_tick(bars, axis_desc, vertical)
    if clusters is None:
        _check(checks, "bar_count", False, len(expected_centers), len(bars),
               "no visible x ticks: bars cannot be assigned to categories")
        clusters = {}
    by_key: dict[tuple, dict] = {}
    for text, members in clusters.items():
        key = _category_key(text)
        for series_index, bar in enumerate(members):
            if series_index >= len(series_names):
                break
            by_key[(key, series_index)] = bar
    observed_count = sum(len(v) for v in clusters.values())
    _check(checks, "bar_count", observed_count == len(expected_centers),
           len(expected_centers), observed_count,
           f"{observed_count} bars drawn for {len(expected_centers)} "
           f"category/series combination(s)")

    orientation = "vertical" if vertical else "horizontal"
    error_items = [item for item in axis_desc.get("errorbars", [])
                   if item["orientation"] == orientation]

    for cat, s in expected_keys:
        series_index = series_names.index(s)
        key = combo_key(cat, s)
        mean = mean_map.get(key)
        observed_bar = by_key.get((_category_key(cat), series_index))
        subject = {"category": cat, "series": s} if series else {"category": cat}
        if observed_bar is None:
            _check(checks, "bar_height", False, mean, None,
                   f"no bar found for category {cat!r}"
                   + (f" series {s!r}" if series else ""), subject)
            continue
        value = observed_bar["height"] if vertical else observed_bar["width"]
        if mean is None:
            unverifiable.append({
                "what": "bar_height", "category": cat,
                "reason": "the declared category/series has no rows; "
                          "the mean is undefined"})
            continue
        ok = _close(value, mean)
        delta = value - mean
        _check(checks, "bar_height", ok, round(mean, 10), round(float(value), 10),
               (f"bar {cat!r}" + (f"/{s!r}" if series else "")
                + (f" height {value:.6g} equals the mean {mean:.6g}" if ok else
                   f" height {value:.6g} != mean {mean:.6g} "
                   f"(delta {delta:+.3g})")),
               subject)
        if not errors_declared:
            continue
        n = count_map.get(key)
        sd = sd_map.get(key)
        if not n or n < 2 or sd is None:
            unverifiable.append({
                "what": "error_length", "category": cat,
                "reason": f"group has n={n}; SD/SE requires at least 2 values"})
            continue
        expected_error = sd if error_kind == "sd" else sd / math.sqrt(n)
        center = (observed_bar["x"] + observed_bar["width"] / 2.0) if vertical \
            else (observed_bar["y"] + observed_bar["height"] / 2.0)
        tolerance = 1e-6 * max(1.0, abs(center))
        candidates = sorted(
            (item for item in error_items
             if abs(float(item["x"] if vertical else item["y"]) - center)
             <= tolerance),
            key=lambda item: abs(float(item["x"] if vertical else item["y"])
                                 - center))
        if not candidates:
            _check(checks, "error_present", False, expected_error, None,
                   f"no {error_kind.upper()} error bar drawn at category "
                   f"{cat!r}", subject)
            continue
        drawn = candidates[0]["length"] / 2.0
        ok = _close(drawn, expected_error)
        _check(checks, "error_length", ok, round(float(expected_error), 10),
               round(float(drawn), 10),
               (f"error bar at {cat!r} is {drawn:.6g} long and the "
                f"{error_kind.upper()} of the group is {expected_error:.6g}"
                if ok else
                f"error bar at {cat!r} is {drawn:.6g} long but the "
                f"{error_kind.upper()} of the group is {expected_error:.6g}"),
               subject)

    if series:
        _legend_check(checks, axis_desc, [str(s) for s in series_names])
        return dropped, [str(s) for s in series_names]
    return dropped, []


def _compare_point_sets(expected: np.ndarray, observed: np.ndarray):
    """Return ``None`` when two point multisets match, else the first problem."""
    if len(expected) != len(observed):
        return {"problem": "count", "expected": len(expected),
                "observed": len(observed)}
    if len(expected) == 0:
        return None
    scale = max(1.0, float(np.max(np.abs(expected))),
                float(np.max(np.abs(observed))))
    left = expected[np.lexsort((expected[:, 1], expected[:, 0]))]
    right = observed[np.lexsort((observed[:, 1], observed[:, 0]))]
    bad = ~np.isclose(left, right, rtol=0.0, atol=1e-9 * scale)
    rows = np.where(bad.any(axis=1))[0]
    if not len(rows):
        return None
    row = int(rows[0])
    return {"problem": "value",
            "expected": [float(left[row, 0]), float(left[row, 1])],
            "observed": [float(right[row, 0]), float(right[row, 1])]}


def _mismatch_detail(problem: Mapping) -> str:
    if problem.get("problem") == "count":
        return (f"{problem['observed']} drawn point(s) for "
                f"{problem['expected']} data point(s)")
    return (f"first mismatched point data={problem['expected']} "
            f"drawn={problem['observed']}")


def _check_scatter(dataset, mapping, axis_desc, checks, unverifiable):
    xcol, ycol = mapping["x"], mapping["y"]
    series = mapping.get("series")
    required = [xcol, ycol] + ([series] if series else [])
    frame = dataset
    missing = frame[required].isna().any(axis=1)
    dropped = int(missing.sum())
    data = frame.loc[~missing].copy()
    if data.empty:
        raise ValueError("check_figure: no complete rows for the scatter plot")
    numeric, invalid = _numeric_column(data, ycol)
    if invalid:
        dropped += invalid
        data = data.loc[numeric.notna()].copy()
        numeric = numeric.loc[numeric.notna()]
    data[ycol] = numeric
    points = np.column_stack([data[xcol].to_numpy(dtype=float),
                              data[ycol].to_numpy(dtype=float)])

    collections = [c for c in axis_desc.get("collections", [])
                   if c.get("kind") == "PathCollection" and c.get("n_points")]
    observed = []
    for collection in collections:
        observed.extend(collection.get("offsets") or [])
    observed_array = np.asarray(observed, dtype=float).reshape(-1, 2) \
        if observed else np.zeros((0, 2), dtype=float)

    _check(checks, "scatter_count", len(observed_array) == len(points),
           len(points), len(observed_array),
           f"{len(observed_array)} drawn point(s) for {len(points)} non-missing "
           f"row(s)")

    if series:
        groups = _unique_order(data[series].tolist())
        if len(groups) != len(collections):
            _check(checks, "scatter_groups", False, len(groups),
                   len(collections),
                   f"{len(collections)} scatter collection(s) for {len(groups)} "
                   f"declared group(s)")
        else:
            for group, collection in zip(groups, collections):
                subset = data.loc[data[series] == group]
                expected_group = np.column_stack([
                    subset[xcol].to_numpy(dtype=float),
                    subset[ycol].to_numpy(dtype=float)])
                drawn_group = np.asarray(collection.get("offsets") or [],
                                         dtype=float).reshape(-1, 2)
                problem = _compare_point_sets(expected_group, drawn_group)
                _check(checks, "scatter_points", problem is None,
                       len(expected_group), len(drawn_group),
                       f"series {group!r}: "
                       + ("all points match the data" if problem is None else
                          _mismatch_detail(problem)),
                       {"series": group})
        return dropped, [str(g) for g in groups]

    problem = _compare_point_sets(points, observed_array)
    _check(checks, "scatter_points", problem is None,
           [[round(float(x), 10), round(float(y), 10)] for x, y in points][:50],
           [[round(float(x), 10), round(float(y), 10)] for x, y in observed_array][:50],
           "drawn points are the data rows as a multiset"
           if problem is None else _mismatch_detail(problem))
    return dropped, []


def _check_line(dataset, mapping, axis_desc, checks, unverifiable):
    xcol, ycol = mapping["x"], mapping["y"]
    series = mapping.get("series")
    required = [xcol, ycol] + ([series] if series else [])
    frame = dataset
    missing = frame[required].isna().any(axis=1)
    dropped = int(missing.sum())
    data = frame.loc[~missing].copy()
    if data.empty:
        raise ValueError("check_figure: no complete rows for the line chart")
    numeric, invalid = _numeric_column(data, ycol)
    if invalid:
        dropped += invalid
        data = data.loc[numeric.notna()].copy()
        numeric = numeric.loc[numeric.notna()]
    data[ycol] = numeric

    groups = _unique_order(data[series].tolist()) if series else [None]
    categories = _unique_order(data[xcol].tolist())

    drawn = [line for line in axis_desc.get("lines", [])
             if line.get("n_points", 0) > 0]
    reference = mapping.get("reference_line")
    if reference is not None and drawn:
        reference = float(reference)
        kept = []
        for line in drawn:
            xs, ys = np.asarray(line["x"]), np.asarray(line["y"])
            if len(ys) == 2 and np.allclose(ys, reference, atol=1e-12) and \
                    np.allclose(xs, [0.0, 1.0], atol=1e-12):
                continue        # axhline reference line, declared by the mapping
            kept.append(line)
        drawn = kept

    _check(checks, "line_count", len(drawn) == len(groups),
           len(groups), len(drawn),
           f"{len(drawn)} drawn line(s) for {len(groups)} declared group(s)")

    non_numeric_x = data[xcol].dtype == object or \
        data[xcol].apply(lambda v: isinstance(v, str)).any()
    if non_numeric_x:
        _category_label_check(checks, axis_desc, categories)

    for index, group in enumerate(groups):
        subset = data if group is None else data.loc[data[series] == group]
        expected_y = subset[ycol].to_numpy(dtype=float)
        subject = {"series": group} if series else {}
        if index >= len(drawn):
            _check(checks, "line_points", False, len(expected_y), None,
                   f"no line drawn for group {group!r}", subject)
            continue
        line = drawn[index]
        drawn_y = np.asarray(line["y"], dtype=float)
        if len(drawn_y) != len(expected_y):
            _check(checks, "line_points", False, len(expected_y),
                   len(drawn_y),
                   f"group {group!r}: {len(drawn_y)} drawn point(s) for "
                   f"{len(expected_y)} row(s)", subject)
            continue
        if non_numeric_x:
            expected_x = np.arange(len(expected_y), dtype=float)
            label = f"group {group!r}: categorical x order"
        else:
            expected_x = subset[xcol].to_numpy(dtype=float)
            label = f"group {group!r}: x/y values in data order"
        drawn_x = np.asarray(line["x"], dtype=float)
        ok = np.allclose(drawn_x, expected_x, rtol=0, atol=1e-9) and \
            np.allclose(drawn_y, expected_y, rtol=0, atol=1e-9)
        _check(checks, "line_points", ok,
               [[round(float(x), 10), round(float(y), 10)]
                for x, y in zip(expected_x, expected_y)],
               [[round(float(x), 10), round(float(y), 10)]
                for x, y in zip(drawn_x, drawn_y)],
               label + (" match" if ok else " differ"), subject)

    if series:
        _legend_check(checks, axis_desc, [str(g) for g in groups])
        return dropped, [str(g) for g in groups]
    return dropped, []


def check_figure(fig, dataset, mapping: Mapping) -> dict:
    """Reconcile the drawn artists of ``fig`` with ``dataset`` under ``mapping``.

    ``mapping`` declares what the figure is supposed to show::

        {"type": "bar", "x": "group", "y": "score", "error": {"kind": "sd"}}
        {"type": "scatter", "x": "age", "y": "score", "label": "id"}
        {"type": "line", "x": "wave", "y": "score", "series": "arm"}

    Returns ``{"ok", "checks", "dropped", "unverifiable", "n", "groups"}``.
    ``ok`` is true only when every executed check passed; anything that cannot
    be judged is listed in ``unverifiable`` with a reason (it is never counted
    as a pass).
    """
    mapping = dict(mapping or {})
    kind = str(mapping.get("type") or "").lower()
    for key in ("x", "y"):
        if not mapping.get(key):
            raise ValueError(f"mapping is missing the {key!r} column")
    frame = _as_frame(dataset)
    for column in [mapping["x"], mapping["y"]] + \
            ([mapping["series"]] if mapping.get("series") else []):
        if column not in frame.columns:
            raise ValueError(f"dataset has no column {column!r} "
                             f"(columns: {list(frame.columns)})")

    described = describe_axes(fig)
    index = int(mapping.get("axes", 0) or 0)
    if index < 0 or index >= len(described["axes"]):
        raise ValueError(f"mapping.axes={index} but the figure has "
                         f"{len(described['axes'])} axes")
    axis_desc = described["axes"][index]

    checks: list[dict] = []
    unverifiable = [dict(item) for item in described["unverifiable"]
                    if item.get("axes") in (None, index)]
    dropped = 0
    groups: list[str] = []
    if kind == "bar":
        dropped, groups = _check_bar(frame, mapping, axis_desc, checks,
                                     unverifiable)
    elif kind == "scatter":
        dropped, groups = _check_scatter(frame, mapping, axis_desc, checks,
                                         unverifiable)
    elif kind == "line":
        dropped, groups = _check_line(frame, mapping, axis_desc, checks,
                                      unverifiable)
    else:
        _check(checks, "mapping_type", False, "bar|scatter|line", kind,
               f"unsupported figure mapping type {kind!r}")
    n = int(len(frame) - dropped)
    return {
        "ok": bool(checks) and all(item["ok"] for item in checks),
        "checks": checks,
        "dropped": int(dropped),
        "unverifiable": unverifiable,
        "n": n,
        "groups": groups,
    }


# ---------------------------------------------------------------------------
# label_geometry: measured tick-label extents
# ---------------------------------------------------------------------------
def _polygon(text, renderer):
    """Corners of the text's *rotated* box (axis-aligned boxes are not enough).

    ``Text.get_window_extent`` already returns the rotated box, so the width and
    height of the unrotated layout are measured separately and rotated here --
    that is the rectangle the glyphs really occupy.
    """
    box = text.get_window_extent(renderer)
    rotation = float(text.get_rotation() or 0.0)
    theta = math.radians(rotation)
    if abs(rotation) <= 1e-9:
        width, height = box.width, box.height
    else:
        original = text.get_rotation()
        text.set_rotation(0)
        try:
            unrotated = text.get_window_extent(renderer)
        finally:
            text.set_rotation(original)
        width, height = unrotated.width, unrotated.height
    corners = np.array([[-width / 2, -height / 2], [width / 2, -height / 2],
                        [width / 2, height / 2], [-width / 2, height / 2]])
    rotation_matrix = np.array([[math.cos(theta), -math.sin(theta)],
                                [math.sin(theta), math.cos(theta)]])
    centre = [(box.x0 + box.x1) / 2.0, (box.y0 + box.y1) / 2.0]
    return corners @ rotation_matrix.T + centre, width, height


def _polygon_gap(left, right) -> float:
    """Max projection gap over the SAT axes; negative means they overlap."""
    best = -float("inf")
    for polygon in (left, right):
        edges = np.roll(polygon, -1, axis=0) - polygon
        for edge in edges:
            normal = np.array([-edge[1], edge[0]])
            length = float(np.linalg.norm(normal))
            if not length:
                continue
            normal /= length
            left_proj, right_proj = left @ normal, right @ normal
            gap = max(float(right_proj.min() - left_proj.max()),
                      float(left_proj.min() - right_proj.max()))
            best = max(best, gap)
    return best


def _overlap(left, right) -> bool:
    return _polygon_gap(left, right) < -OVERLAP_TOLERANCE_PX


def _axis_label_records(ax, direction: str, renderer) -> list[dict]:
    records = []
    for position, tick in _tick_pairs(ax, direction):
        polygon, width, height = _polygon(tick, renderer)
        box = tick.get_window_extent(renderer)
        records.append({
            "position": float(position),
            "text": tick.get_text(),
            "rotation": float(tick.get_rotation()),
            "fontsize": float(tick.get_fontsize()),
            "bbox": [float(box.x0), float(box.y0),
                     float(box.x1), float(box.y1)],
            "polygon": polygon,
            "width": float(width),
            "height": float(height),
        })
    return records


def _measure_axis(ax, index: int, renderer, fig) -> tuple[dict, list[dict]]:
    records = _axis_label_records(ax, "x", renderer)
    overlaps = bbox_overlaps = 0
    min_gap = None
    outside = 0
    labels = []
    canvas_width, canvas_height = fig.bbox.width, fig.bbox.height
    for position, (current, following) in enumerate(zip(records, records[1:])):
        if _overlap(current["polygon"], following["polygon"]):
            overlaps += 1
        if current["bbox"][0] < following["bbox"][2] and \
                following["bbox"][0] < current["bbox"][2] and \
                current["bbox"][1] < following["bbox"][3] and \
                following["bbox"][1] < current["bbox"][3]:
            bbox_overlaps += 1
        gap = following["bbox"][0] - current["bbox"][2]
        min_gap = gap if min_gap is None else min(min_gap, gap)
        _ = position
    for record in records:
        x0, y0, x1, y1 = record["bbox"]
        is_outside = (x0 < -1 or y0 < -1 or x1 > canvas_width + 1
                      or y1 > canvas_height + 1)
        outside += int(is_outside)
        labels.append({
            "axes": index,
            "axis": "x",
            "text": record["text"],
            "position": record["position"],
            "rotation": record["rotation"],
            "fontsize": record["fontsize"],
            "bbox_px": [round(v, 3) for v in record["bbox"]],
            "width_px": round(record["width"], 3),
            "height_px": round(record["height"], 3),
            "outside": bool(is_outside),
        })
    entry = {
        "axes": index,
        "n_labels": len(records),
        "overlaps": overlaps,
        "bbox_overlaps": bbox_overlaps,
        "min_gap_px": None if min_gap is None else round(float(min_gap), 3),
        "outside": outside,
        "fontsize_min": min((r["fontsize"] for r in records), default=None),
        "rotations": sorted({r["rotation"] for r in records}),
    }
    return entry, labels


def label_geometry(fig) -> dict:
    """Measure the real x tick labels of ``fig`` and report their collisions.

    ``overlaps`` counts adjacent pairs whose *rotated* glyph boxes intersect
    (the honest test for tilted text); ``bbox_overlaps`` is the same count for
    the raw axis-aligned ``window_extent`` boxes and is reported for contrast.
    ``outside`` counts labels that spill past the canvas.  No label is removed,
    truncated or resized by this function.
    """
    renderer, problem = _get_renderer(fig)
    unverifiable = []
    if problem:
        unverifiable.append({"what": "renderer", "reason": problem})
        return {"overlaps": 0, "bbox_overlaps": 0, "min_gap_px": None,
                "outside": 0, "n_labels": 0, "labels": [], "axes": [],
                "unverifiable": unverifiable}
    axes_entries, labels = [], []
    for index, ax in enumerate(fig.axes):
        entry, axis_labels = _measure_axis(ax, index, renderer, fig)
        axes_entries.append(entry)
        labels.extend(axis_labels)
    gaps = [entry["min_gap_px"] for entry in axes_entries
            if entry["min_gap_px"] is not None]
    fontsize = min((entry["fontsize_min"] for entry in axes_entries
                    if entry["fontsize_min"] is not None), default=None)
    return {
        "overlaps": int(sum(entry["overlaps"] for entry in axes_entries)),
        "bbox_overlaps": int(sum(entry["bbox_overlaps"] for entry in axes_entries)),
        "min_gap_px": None if not gaps else round(float(min(gaps)), 3),
        "outside": int(sum(entry["outside"] for entry in axes_entries)),
        "n_labels": len(labels),
        "fontsize_min": fontsize,
        "measure": "renderer window_extent; rotated glyph boxes (SAT)",
        "labels": labels,
        "axes": axes_entries,
        "unverifiable": unverifiable,
    }


# ---------------------------------------------------------------------------
# layout_options: measured, actionable, never destructive
# ---------------------------------------------------------------------------
def _apply_rotation(ax, angle: float) -> list[tuple]:
    state = []
    for tick in ax.get_xticklabels():
        state.append((tick, tick.get_rotation(), tick.get_rotation_mode(),
                      tick.get_ha(), tick.get_va()))
        tick.set_rotation(angle)
        tick.set_rotation_mode("anchor")
        tick.set_ha("right")
        tick.set_va("center")
    return state


def _restore_rotation(state: Sequence[tuple]) -> None:
    for tick, rotation, mode, ha, va in state:
        tick.set_rotation(rotation)
        tick.set_rotation_mode(mode)
        tick.set_ha(ha)
        tick.set_va(va)


def _measure_with_angle(fig, index: int, angle: float):
    ax = fig.axes[index]
    state = _apply_rotation(ax, angle)
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        entry, labels = _measure_axis(ax, index, renderer, fig)
        return entry, labels
    finally:
        _restore_rotation(state)
        try:
            fig.canvas.draw()
        except Exception:                          # pragma: no cover - backend
            pass


def layout_options(fig, geometry: Mapping) -> list[dict]:
    """Turn measured label geometry into options with their evidence.

    Every option keeps all labels at their current font size.  ``rotate`` and
    ``widen`` report what was measured, not what was assumed: rotations are
    applied to the live figure, re-rendered and re-measured, then restored.
    """
    geometry = dict(geometry or {})
    axes_entries = geometry.get("axes") or []
    options: list[dict] = []
    labels = geometry.get("labels") or []
    for entry in axes_entries:
        if not entry.get("n_labels"):
            continue
        index = int(entry["axes"])
        ax = fig.axes[index]
        n_labels = int(entry["n_labels"])
        fontsize = entry.get("fontsize_min")
        initial = int(entry.get("overlaps") or 0)
        outside_now = int(entry.get("outside") or 0)
        if not initial and not outside_now:
            continue
        axis_labels = [item for item in labels if item.get("axes") == index] \
            or [item for item in labels
                if int(item.get("axes", 0) or 0) == index]

        if initial:
            measured = []
            for angle in (30, 45, 60, 75):
                after, after_labels = _measure_with_angle(fig, index, angle)
                measured.append((angle, after, after_labels))
            working = [(angle, data, after_labels)
                       for angle, data, after_labels in measured
                       if data["overlaps"] < initial]
            working.sort(key=lambda item: (item[1]["overlaps"],
                                           item[1]["outside"], item[0]))
            for angle, data, _labels_after in working[:2]:
                options.append({
                    "option": "rotate",
                    "angle": angle,
                    "axes": [index],
                    "reason": (f"{initial} of {max(0, n_labels - 1)} adjacent "
                               f"label pairs overlap at {fontsize:.1f}pt; "
                               f"rotating {angle}° measured "
                               f"{data['overlaps']} overlap(s), "
                               f"{data['outside']} label(s) past the canvas"),
                    "supported_by": ("measured window_extent; rotated boxes "
                                     "re-rendered"),
                    "expected_overlaps": int(data["overlaps"]),
                    "expected_outside": int(data["outside"]),
                    "labels_kept": n_labels,
                    "deletes_labels": False,
                })
            best_angle, best, best_labels = min(
                measured, key=lambda item: (item[1]["overlaps"],
                                            item[1]["outside"]))
        else:
            best_angle, best, best_labels = 0, entry, axis_labels
        if best["outside"] or outside_now:
            # Reserve bottom space for the labels that actually dip below the
            # canvas: after the measured rotation when one helps, otherwise as
            # drawn now.  This is a clipping fix, not an overlap fix.
            contender = best_labels if best["outside"] else axis_labels
            lowest = min((item["bbox_px"][1] for item in contender),
                         default=0.0)
            bottom_cm = max(0.0, -float(lowest)) / max(float(fig.dpi), 1.0) \
                * CM_PER_INCH + 0.1
            outside = max(int(best["outside"]), outside_now)
            options.append({
                "option": "expand",
                "axes": [index],
                "bottom_cm": round(bottom_cm, 2),
                "reason": (f"{outside} label(s) extend past the canvas edge at "
                           f"{fontsize:.1f}pt; about {bottom_cm:.2f} cm of extra "
                           f"bottom space keeps every label inside without "
                           f"changing its text or size"),
                "supported_by": "measured label extents below the canvas edge",
                "labels_kept": n_labels,
                "deletes_labels": False,
            })

        if not initial:
            continue
        unrotated = [item for item in axis_labels
                     if abs(float(item.get("rotation", 0.0))) < 1e-9]
        widths = [float(item.get("width_px") or 0.0) for item in unrotated]
        if len(widths) < 2:
            continue
        required_spacing = max((widths[i] + widths[i + 1]) / 2.0 + 2.0
                               for i in range(len(widths) - 1))
        axes_width_px = float(ax.bbox.width)
        figure_width_px = float(fig.bbox.width)
        if axes_width_px <= 0 or figure_width_px <= 0:
            continue
        required_axes_px = required_spacing * max(1, n_labels - 1) + \
            (widths[0] + widths[-1]) / 2.0
        needed_px = required_axes_px * figure_width_px / axes_width_px
        current_cm = figure_width_px / max(float(fig.dpi), 1.0) * CM_PER_INCH
        needed_cm = needed_px / max(float(fig.dpi), 1.0) * CM_PER_INCH
        if needed_cm > current_cm + 0.2:
            options.append({
                "option": "widen",
                "axes": [index],
                "needed_width_cm": round(needed_cm, 1),
                "current_width_cm": round(current_cm, 1),
                "reason": (f"keeping every label horizontal needs about "
                           f"{needed_cm:.1f} cm of canvas (currently "
                           f"{current_cm:.1f} cm at {fontsize:.1f}pt); "
                           f"measured widths require "
                           f"{required_spacing:.1f}px between adjacent ticks"),
                "supported_by": "measured extents",
                "expected_overlaps": None,
                "estimate": ("geometric from measured label widths; the widened "
                             "canvas was not re-rendered"),
                "labels_kept": n_labels,
                "deletes_labels": False,
            })
        if needed_cm > current_cm * 1.5 and (best["overlaps"] or 0):
            panels = max(2, int(math.ceil(needed_cm / max(current_cm, 1.0))))
            options.append({
                "option": "subplot",
                "axes": [index],
                "panels": panels,
                "reason": (f"even {best_angle}° rotation leaves "
                           f"{best['overlaps']} overlap(s) and widening to "
                           f"{needed_cm:.1f} cm exceeds 1.5x the current "
                           f"{current_cm:.1f} cm; {panels} panels keep every "
                           f"label at {fontsize:.1f}pt"),
                "supported_by": "measured extents",
                "labels_kept": n_labels,
                "deletes_labels": False,
            })
    return options


# ---------------------------------------------------------------------------
# palette_report: report the real colours, advise only
# ---------------------------------------------------------------------------
_SEQUENTIAL_CMAPS = {
    "viridis", "plasma", "inferno", "magma", "cividis", "blues", "greens",
    "greys", "grays", "oranges", "purples", "reds", "ylorbr", "ylorrd",
    "ylgn", "ylgnbu", "bugn", "bupu", "gnbu", "pubu", "pubugn", "purd",
    "orrd", "bone", "copper", "pink", "wistia", "spring", "summer", "autumn",
    "winter", "cool", "hot", "afmhot", "gist_heat", "gist_yarg", "binary",
}
_DIVERGING_CMAPS = {
    "rdbu", "rdbu_r", "coolwarm", "bwr", "seismic", "piyg", "prgn", "brbg",
    "rdylbu", "rdylgn", "spectral", "rdgy", "puor", "berlin", "managua",
    "vanimo", "rdwh", "cet_diverging",
}
_QUALITATIVE_CMAPS = {
    "tab10", "tab20", "tab20b", "tab20c", "set1", "set2", "set3", "paired",
    "pastel1", "pastel2", "dark2", "accent", "hsv",
}


def _classify_colors(colors: Sequence[str]) -> tuple[str, str]:
    """Return ``(role, basis)`` for a list of real colour hex strings."""
    unique = list(dict.fromkeys(colors))
    if not unique:
        return "unknown", "no data colours found"
    if len(unique) == 1:
        return "single", "one data colour"
    labs = [_rgb_to_lab(_resolve_rgba(c)) for c in unique
            if _resolve_rgba(c) is not None]        # type: ignore[arg-type]
    if len(labs) < 2:
        return "unknown", "colours could not be parsed as RGB"
    lightness = [lab[0] for lab in labs]
    chroma = [math.hypot(lab[1], lab[2]) for lab in labs]
    increasing = all(b > a for a, b in zip(lightness, lightness[1:]))
    decreasing = all(b < a for a, b in zip(lightness, lightness[1:]))
    if (increasing or decreasing) and len(labs) >= 3:
        return "sequential", ("lightness increases/decreases monotonically "
                              "across the drawn colours")
    if len(labs) >= 3:
        middle = slice(1, -1)
        interior_light = any(value > max(lightness[0], lightness[-1]) + 5
                             for value in lightness[middle])
        interior_dark = any(value < min(lightness[0], lightness[-1]) - 5
                            for value in lightness[middle])
        neutral_middle = any(value < 12 for value in chroma[middle])
        saturated_ends = chroma[0] > 20 and chroma[-1] > 20
        if (interior_light or interior_dark) and neutral_middle and saturated_ends:
            return "diverging", ("a near-neutral middle sits between two "
                                 "saturated ends")
    return "categorical", "distinct colours assigned to discrete elements"


def _classify_cmap(name: str | None) -> tuple[str, str]:
    key = str(name or "").lower()
    if not key:
        return "unknown", "no colour map name"
    if key in _DIVERGING_CMAPS:
        return "diverging", f"colour map {name!r} is a diverging map"
    if key in _QUALITATIVE_CMAPS:
        return "categorical", f"colour map {name!r} is a qualitative map"
    if key in _SEQUENTIAL_CMAPS:
        return "sequential", f"colour map {name!r} is a sequential map"
    return "sequential", (f"colour map {name!r} is not in the known "
                          f"diverging/qualitative lists; treated as sequential")


def _palette_entry(role: str, source: str, axes: int, colors: Sequence[str],
                   alphas: Sequence[float], basis: str,
                   markers: Sequence[str] = (), edges: Sequence[str] = (),
                   colormap: str | None = None,
                   extra: Mapping | None = None) -> dict:
    unique_colors = list(dict.fromkeys(colors))
    entry = {
        "role": role,
        "role_source": "inferred",
        "source": source,
        "axes": axes,
        "colors": unique_colors,
        "n_colors": len(unique_colors),
        "n_elements": len(colors),
        "alpha": sorted({round(float(a), 4) for a in alphas}) or [1.0],
        "transparent": any(float(a) < 0.999 for a in (alphas or (1.0,))),
        "markers": list(dict.fromkeys(m for m in markers if m)),
        "edgecolors": list(dict.fromkeys(edges)),
        "basis": basis,
    }
    if colormap:
        entry["colormap"] = colormap
    if extra:
        entry.update(extra)
    return entry


def palette_report(fig) -> dict:
    """Report the colours/markers/alpha actually used by the figure.

    The role is a *heuristic* reading of the artists (colour map identity, or
    monotonic lightness / near-neutral middle / discrete colours).  All output
    is advisory: ``mandatory`` is always false and every remark is a
    ``suggestion``.  Nothing in this report can fail a figure.
    """
    roles: list[dict] = []
    colormaps: list[dict] = []
    unverifiable: list[dict] = []
    for index, ax in enumerate(fig.axes):
        bar_colors, bar_alphas, bar_edges = [], [], []
        for container in list(ax.containers):
            if not isinstance(container, BarContainer):
                continue
            for patch in container.patches:
                if patch is None or not patch.get_visible():
                    continue
                color = _hex_color(patch.get_facecolor())
                if color:
                    bar_colors.append(color)
                    bar_alphas.append(_effective_alpha(
                        patch, _resolve_rgba(patch.get_facecolor())))
                edge = _hex_color(patch.get_edgecolor())
                if edge:
                    bar_edges.append(edge)
        if bar_colors:
            role, basis = _classify_colors(bar_colors)
            roles.append(_palette_entry(role, "bars", index, bar_colors,
                                        bar_alphas, basis,
                                        edges=list(dict.fromkeys(bar_edges))))

        line_colors, line_alphas, markers, edges = [], [], [], []
        for line in list(ax.lines):
            if not line.get_visible() or len(line.get_xdata()) == 0:
                continue
            rgba = _resolve_rgba(line.get_color())
            color = _hex_color(line.get_color())
            if color:
                line_colors.append(color)
                line_alphas.append(_effective_alpha(line, rgba))
            marker = str(line.get_marker())
            if marker not in ("None", "none", ""):
                markers.append(marker)
            marker_edge = _hex_color(line.get_markeredgecolor())
            if marker_edge:
                edges.append(marker_edge)
        if line_colors:
            role, basis = _classify_colors(line_colors)
            roles.append(_palette_entry(role, "lines", index, line_colors,
                                        line_alphas, basis, markers=markers,
                                        edges=list(dict.fromkeys(edges))))

        for collection in list(ax.collections):
            name = type(collection).__name__
            if "Contour" in name:
                unverifiable.append({
                    "axes": index, "what": "contour colours",
                    "reason": "contour colours follow levels, not categories; "
                              "the level values are in describe_axes"})
                continue
            try:
                offsets = collection.get_offsets()
            except Exception:                      # pragma: no cover - defensive
                offsets = None
            has_points = offsets is not None and len(offsets) > 0
            if not has_points:
                continue
            try:
                mapped = collection.get_array() is not None
            except Exception:                      # pragma: no cover - defensive
                mapped = False
            if mapped:
                cmap = getattr(collection.get_cmap(), "name", None)
                role, basis = _classify_cmap(cmap)
                roles.append(_palette_entry(
                    role, "collections", index, [], [collection.get_alpha() or 1.0],
                    basis, colormap=cmap,
                    extra={"mapped": True,
                           "vmin": _json_safe(getattr(collection.norm, "vmin", None)),
                           "vmax": _json_safe(getattr(collection.norm, "vmax", None))}))
                colormaps.append({"name": cmap, "axes": index,
                                  "artist": "collection", "role": role})
            else:
                face = [_hex_color(c) for c in collection.get_facecolors()]
                face = [c for c in face if c]
                alpha = collection.get_alpha()
                if alpha is None and len(collection.get_facecolors()):
                    alpha = float(np.asarray(collection.get_facecolors())[0][3])
                role, basis = _classify_colors(face)
                roles.append(_palette_entry(
                    role, "collections", index, face,
                    [alpha if alpha is not None else 1.0], basis,
                    extra={"n_points": int(len(offsets))}))

        for image in list(ax.images):
            if not image.get_visible():
                continue
            cmap = getattr(image.get_cmap(), "name", None)
            role, basis = _classify_cmap(cmap)
            roles.append(_palette_entry(
                role, "images", index, [], [image.get_alpha() or 1.0], basis,
                colormap=cmap,
                extra={"mapped": True,
                       "vmin": _json_safe(image.norm.vmin),
                       "vmax": _json_safe(image.norm.vmax)}))
            colormaps.append({"name": cmap, "axes": index, "artist": "image",
                              "role": role})
            unverifiable.append({
                "axes": index, "what": "image palette",
                "reason": "a raster image's per-pixel colours are not a "
                          "discrete palette; only the colour map is reported"})

    suggestions: list[dict] = []
    for entry in roles:
        if entry["role"] != "categorical" or len(entry["colors"]) < 2:
            continue
        labs = [_rgb_to_lab(_resolve_rgba(c)) for c in entry["colors"]
                if _resolve_rgba(c) is not None]        # type: ignore[arg-type]
        spread = min((abs(a[0] - b[0]) for i, a in enumerate(labs)
                      for b in labs[i + 1:]), default=None)
        if spread is not None and spread < 10:
            suggestions.append({
                "severity": "suggestion", "mandatory": False,
                "code": "categorical_lightness_spread",
                "source": entry["source"], "axes": entry["axes"],
                "message": (f"categorical colours differ by only "
                            f"{spread:.1f} L*; the 10 L* gap is an internal "
                            f"heuristic, not a journal rule -- check the "
                            f"rendered figure with linestyle/marker/labels"),
            })
        if entry["markers"] == [] and not entry["edgecolors"]:
            suggestions.append({
                "severity": "suggestion", "mandatory": False,
                "code": "color_only_encoding",
                "source": entry["source"], "axes": entry["axes"],
                "message": ("categorical groups are distinguished only by "
                            "colour here; markers/linestyles/labels may add a "
                            "second channel (optional)"),
            })
        if entry["transparent"]:
            suggestions.append({
                "severity": "suggestion", "mandatory": False,
                "code": "transparency_needs_rendered_review",
                "source": entry["source"], "axes": entry["axes"],
                "message": (f"alpha {entry['alpha']} was used; review the "
                            f"actual served size and background -- colour "
                            f"distance alone does not cover transparency"),
            })
    return {
        "roles": roles,
        "colormaps": colormaps,
        "suggestions": suggestions,
        "mandatory": False,
        "unverifiable": unverifiable,
    }


# ---------------------------------------------------------------------------
# record + saved-file checks
# ---------------------------------------------------------------------------
def _rel_posix(path: str, root: str) -> str:
    if not path:
        return ""
    try:
        relative = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:                             # different drive
        relative = os.path.abspath(path)
    return relative.replace("\\", "/")


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canvas_info(fig, png_path: str | None, dpi: float | None) -> dict:
    width_in, height_in = (float(v) for v in fig.get_size_inches()[:2])
    info = {
        "size_in": [width_in, height_in],
        "size_cm": [round(width_in * CM_PER_INCH, 3),
                    round(height_in * CM_PER_INCH, 3)],
        "dpi": float(dpi if dpi is not None else fig.dpi),
        "dpi_source": "declared argument" if dpi is not None else "figure",
    }
    if png_path and os.path.isfile(png_path):
        try:
            from PIL import Image
            with Image.open(png_path) as image:
                info["px"] = [int(image.size[0]), int(image.size[1])]
                meta = image.info.get("dpi")
                if meta:
                    # The artifact is the truth: record what the file really
                    # says instead of the dpi someone meant to pass.
                    info["dpi"] = round(float(meta[0]), 2)
                    info["png_dpi"] = [round(float(meta[0]), 2),
                                       round(float(meta[1]), 2)]
                    info["dpi_source"] = "png metadata"
            info["png_sha256"] = _file_sha256(png_path)
        except Exception as exc:                   # pragma: no cover - corrupt
            info["png_error"] = f"{type(exc).__name__}: {exc}"
    else:
        info["px"] = [int(round(width_in * info["dpi"])),
                      int(round(height_in * info["dpi"]))]
    return info


def _append_with_transitions(project: Project, kind: str, record_id: str,
                             payload: Mapping, *, producer: Mapping,
                             input_refs: Sequence[Mapping],
                             status: str, extensions: Mapping | None = None):
    """Append ``status``, inserting a legal ``declared`` step when needed."""
    previous = project.latest(kind, record_id)
    revision = 1 if previous is None else int(previous["revision"]) + 1
    chain = [status]
    if previous is not None:
        try:
            check_transition(kind, previous["status"], status)
        except StatusTransitionError:
            # e.g. stale -> failed is not legal; re-declare first, then fail.
            chain = ["declared", status]
    record = None
    for state in chain:
        record = make_record(kind, record_id, payload, producer=producer,
                             status=state, revision=revision,
                             input_refs=input_refs, extensions=extensions)
        project.append(kind, record, enforce_transition=True)
        revision += 1
    return record


def record_figure(project: Project, figure_id: str, fig, mapping: Mapping,
                  dataset_rel: str, dataset_sha: str, checks: Mapping,
                  geometry: Mapping, palette: Mapping, *, png_path: str = "",
                  pdf_path: str = "", dpi: float | None = None,
                  question: str = "", caption: str = "") -> dict:
    """Write one v2 ``figure_spec`` record from the measured readings.

    ``status`` is ``checked`` when every check passed and ``failed`` otherwise;
    the payload keeps the real element readings (``elements_observed``), the
    individual checks, the label geometry and the palette report.  The record
    validates against :mod:`contract_v2` before it is appended.
    """
    mapping = dict(mapping or {})
    checks = dict(checks or {})
    geometry = dict(geometry or label_geometry(fig))
    palette = dict(palette or palette_report(fig))
    described = describe_axes(fig)
    canvas = _canvas_info(fig, png_path or None, dpi)
    from matplotlib.text import Text
    rendered_text = [_text_record(t, fig.canvas.get_renderer()) for t in fig.findobj(Text)
                     if t.get_visible() and t.get_text() and t.get_alpha() != 0]
    artifact_matches = False
    if png_path and os.path.isfile(png_path):
        import io
        from layout_check import image_content_sha256
        buffer = io.BytesIO()
        render_dpi = float(canvas["dpi"])
        if abs(render_dpi - round(render_dpi)) < 0.02:
            render_dpi = round(render_dpi)
        fig.savefig(buffer, format="png", dpi=render_dpi, **dict(mapping.get("savefig") or {}))
        artifact_matches = image_content_sha256(buffer.getvalue())[0] == image_content_sha256(Path(png_path).read_bytes())[0]

    payload = {
        "figure_id": str(figure_id),
        "question": str(question or mapping.get("question") or ""),
        "inputs": [{"kind": "dataset", "id": str(dataset_rel),
                    "sha256": str(dataset_sha)}],
        "denominator": str(mapping.get("denominator")
                           or (f"N={checks['n']}"
                               if checks.get("n") is not None else "")),
        "unit": str(mapping.get("unit") or ""),
        "series_declared": [str(v) for v in (checks.get("groups") or [])],
        "elements_observed": {
            "rendered_text": rendered_text,
            "axes": described["axes"],
            "figure": described["figure"],
            "canvas": canvas,
            "unverifiable": described["unverifiable"] +
                            list(checks.get("unverifiable") or []),
        },
        "checks": list(checks.get("checks") or []),
        "png": _rel_posix(png_path, project.root) if png_path else "",
        "pdf": _rel_posix(pdf_path, project.root) if pdf_path else "",
        "png_sha256": _file_sha256(png_path) if png_path and os.path.isfile(png_path) else "",
        "pdf_sha256": _file_sha256(pdf_path) if pdf_path and os.path.isfile(pdf_path) else "",
        "transform": str(mapping.get("transform") or ""),
        "sorting": str(mapping.get("sorting") or ""),
        "error_type": str((mapping.get("error") or {}).get("kind") or "")
        if mapping.get("error") else "",
        "reference_line": ("" if mapping.get("reference_line") is None
                           else str(mapping.get("reference_line"))),
        "palette": palette,
        "labels": {
            "tick_texts": [str(item["text"]) for item in geometry.get("labels", [])],
            "geometry": geometry,
        },
        "caption": str(caption or mapping.get("caption") or ""),
        "notes": (f"ok={bool(checks.get('ok'))}; "
                  f"{len(checks.get('checks') or [])} check(s); "
                  f"{len(checks.get('unverifiable') or [])} unverifiable; "
                  f"palette suggestions "
                  f"{len(palette.get('suggestions') or [])} (advisory)"),
    }
    payload["checks"].append({"check": "saved_png_matches_live_figure", "ok": artifact_matches,
                              "detail": "decoded rendered pixels must match the actual delivered PNG; declare savefig options when used"})
    if mapping.get("placement"):
        payload["placement"] = dict(mapping["placement"])
    payload = _json_safe(payload)
    producer = producer_for("figsemantics", version=__version__,
                            module_file=__file__,
                            config={"mapping": mapping,
                                    "type": str(mapping.get("type") or "")})
    input_refs = [{"kind": "dataset", "id": str(dataset_rel),
                   "sha256": str(dataset_sha)}]
    layout_ok = not geometry.get("overlaps") and not geometry.get("outside") and not geometry.get("unverifiable")
    status = ("checked" if artifact_matches else "declared" if not png_path else "failed") if checks.get("ok") and layout_ok else "failed"
    return _append_with_transitions(
        project, "figure_spec", str(figure_id), payload, producer=producer,
        input_refs=input_refs, status=status,
        extensions={"measured_by": "figsemantics", "version": __version__})


def _measure_png(path: str) -> dict:
    from PIL import Image
    info: dict = {"path": path}
    with Image.open(path) as image:
        info["px"] = [int(image.size[0]), int(image.size[1])]
        info["mode"] = str(image.mode)
        info["format"] = str(image.format)
        meta = image.info.get("dpi")
        info["dpi"] = [round(float(meta[0]), 2), round(float(meta[1]), 2)] \
            if meta else None
        info["sha256"] = _file_sha256(path)
        info["bytes"] = int(os.path.getsize(path))
    if info["dpi"]:
        info["physical_cm"] = [round(info["px"][0] / info["dpi"][0] *
                                     CM_PER_INCH, 3),
                               round(info["px"][1] / info["dpi"][1] *
                                     CM_PER_INCH, 3)]
    else:
        info["physical_cm"] = None
    return info


def _measure_pdf(path: str) -> dict:
    import fitz
    info: dict = {"path": path, "pages": 0, "images": [],
                  "text_layer": False, "text": ""}
    document = fitz.open(path)
    try:
        info["pages"] = int(document.page_count)
        if document.page_count:
            page = document[0]
            info["page_pt"] = [round(float(page.rect.width), 2),
                               round(float(page.rect.height), 2)]
            info["page_cm"] = [round(float(page.rect.width) / 72.0 *
                                     CM_PER_INCH, 3),
                               round(float(page.rect.height) / 72.0 *
                                     CM_PER_INCH, 3)]
            text = page.get_text("text")
            info["text"] = text
            info["text_layer"] = bool(text.strip())
            for image in page.get_images(full=True):
                xref = int(image[0])
                try:
                    extracted = document.extract_image(xref)
                except Exception:                  # pragma: no cover - corrupt
                    continue
                rects = page.get_image_rects(xref)
                widths = [rect.width for rect in rects] or [0.0]
                placed_in = max(widths) / 72.0 if widths else 0.0
                dpi = (extracted["width"] / placed_in) if placed_in > 0 else None
                info["images"].append({
                    "xref": xref,
                    "px": [int(extracted["width"]), int(extracted["height"])],
                    "placed_cm": round(placed_in * CM_PER_INCH, 3),
                    "effective_dpi": round(float(dpi), 1) if dpi else None,
                })
    finally:
        document.close()
    return info


def check_saved(spec_id: str, png_path: str, pdf_path: str | None = None, *,
                root: str = ".") -> dict:
    """Measure an exported PNG/PDF and compare it with its ``figure_spec``.

    The declaration comes from ``<root>/output/v2/figure_spec.jsonl``.  Only
    facts a file can prove are checked (pixel size, dpi, physical size, hashes,
    PDF page/placement, text layer).  Element counts, label collisions and the
    palette cannot be recovered from a bitmap: those go to ``unverifiable``
    with the reason instead of being counted as a pass.
    """
    project = Project(root, create=False)
    record = project.latest("figure_spec", spec_id)
    checks: list[dict] = []
    unverifiable: list[dict] = []

    def resolve(path: str) -> str:
        if not path:
            return ""
        return path if os.path.isabs(path) else os.path.join(str(project.root),
                                                             path)

    declared = record["data"] if record else {}
    observed = declared.get("elements_observed") or {}
    canvas = observed.get("canvas") or {}
    png_path = png_path or resolve(declared.get("png") or "")
    if pdf_path is None:
        pdf_path = ""
    pdf_path = pdf_path or ""
    png_path = resolve(png_path)
    pdf_path = resolve(pdf_path)

    _check(checks, "spec_record", record is not None, True, record is not None,
           f"figure_spec {spec_id!r} found" if record else
           f"no figure_spec record {spec_id!r}; there is nothing to verify "
           f"the file against")

    png_info: dict = {}
    if not png_path or not os.path.isfile(png_path):
        _check(checks, "png_exists", False, png_path, None,
               f"PNG not found: {png_path!r}")
    else:
        _check(checks, "png_exists", True, png_path, png_path, "PNG present")
        try:
            png_info = _measure_png(png_path)
            _check(checks, "png_readable", True, "readable", png_info["format"],
                   f"PNG {png_info['px'][0]}x{png_info['px'][1]} "
                   f"{png_info['mode']}")
        except Exception as exc:
            _check(checks, "png_readable", False, "readable", None,
                   f"{type(exc).__name__}: {exc}")

    if png_info:
        expected_px = canvas.get("px")
        if expected_px:
            same = [int(v) for v in expected_px] == png_info["px"]
            _check(checks, "png_pixels", same, list(expected_px),
                   png_info["px"],
                   f"declared PNG is {expected_px[0]}x{expected_px[1]}px; the "
                   f"file on disk is {png_info['px'][0]}x{png_info['px'][1]}px")
        else:
            unverifiable.append({"what": "png_pixels",
                                 "reason": "the record declares no pixel size"})
        expected_sha = canvas.get("png_sha256")
        if expected_sha:
            same = expected_sha == png_info["sha256"]
            _check(checks, "png_sha256", same, expected_sha[:12],
                   png_info["sha256"][:12],
                   "the PNG bytes match the recorded export"
                   if same else
                   "the PNG on disk is a different image than the recorded "
                   "export (content hash differs)")
        else:
            unverifiable.append({"what": "png_sha256",
                                 "reason": "the record has no PNG hash; a "
                                           "replaced file cannot be detected"})
        expected_dpi = canvas.get("dpi")
        if expected_dpi and png_info["dpi"]:
            same = abs(float(expected_dpi) - float(png_info["dpi"][0])) <= 1.0
            _check(checks, "png_dpi", same, float(expected_dpi),
                   png_info["dpi"][0],
                   f"declared {expected_dpi} dpi; the PNG metadata says "
                   f"{png_info['dpi'][0]} dpi")
        elif not png_info["dpi"]:
            unverifiable.append({"what": "png_dpi",
                                 "reason": "the PNG carries no dpi metadata; "
                                           "effective resolution cannot be "
                                           "derived from the file alone"})
        if canvas.get("size_cm") and png_info.get("physical_cm"):
            same = all(abs(float(a) - float(b)) <= 0.05 for a, b in
                       zip(canvas["size_cm"], png_info["physical_cm"]))
            _check(checks, "png_physical_size", same,
                   [round(float(v), 2) for v in canvas["size_cm"]],
                   [round(float(v), 2) for v in png_info["physical_cm"]],
                   "pixel size / dpi equals the declared physical figure size")
        unverifiable.extend([
            {"what": "element_counts", "reason": (
                "a bitmap has no vector element list: bars/lines/collections/"
                "error-bar counts cannot be recovered from the saved PNG; "
                "re-inspect the live Figure instead")},
            {"what": "label_geometry", "reason": (
                "tick-label boxes, overlaps and font size cannot be measured "
                "from the rendered pixels")},
            {"what": "palette_roles", "reason": (
                "the colour map/normalisation is not recoverable from the "
                "bitmap; only the rendering is visible")},
        ])

    pdf_info: dict = {}
    if pdf_path:
        if not os.path.isfile(pdf_path):
            _check(checks, "pdf_exists", False, pdf_path, None,
                   f"PDF not found: {pdf_path!r}")
        else:
            _check(checks, "pdf_exists", True, pdf_path, pdf_path, "PDF present")
            try:
                pdf_info = _measure_pdf(pdf_path)
                _check(checks, "pdf_pages", True, 1, pdf_info["pages"],
                       f"{pdf_info['pages']} page(s)")
                if canvas.get("size_cm") and pdf_info.get("page_cm"):
                    same = all(abs(float(a) - float(b)) <= 0.2 for a, b in
                               zip(canvas["size_cm"], pdf_info["page_cm"]))
                    _check(checks, "pdf_page_size", same,
                           [round(float(v), 2) for v in canvas["size_cm"]],
                           pdf_info["page_cm"],
                           "PDF page size equals the declared figure canvas")
                if not pdf_info["images"]:
                    _check(checks, "pdf_vector", True, "vector artwork",
                           "vector", "the PDF has no embedded raster image; "
                                     "effective dpi is not applicable")
                    unverifiable.append({"what": "pdf_effective_dpi",
                                         "reason": "vector PDF: there is no "
                                                   "raster image to measure"})
                else:
                    for image in pdf_info["images"]:
                        if png_info.get("px") and image["px"] != png_info["px"]:
                            _check(checks, "pdf_embedded_pixels", False,
                                   png_info["px"], image["px"],
                                   "the image embedded in the PDF is not the "
                                   "PNG on disk")
                        dpi = image.get("effective_dpi")
                        if dpi is not None:
                            _check(checks, "pdf_effective_dpi", dpi >= MIN_DPI,
                                   MIN_DPI, dpi,
                                   f"effective dpi of the placed image is "
                                   f"{dpi} (minimum {MIN_DPI})")
                        unverifiable.append({
                            "what": "pdf_element_counts",
                            "reason": "the PDF drawing list is not a "
                                      "data-to-artist mapping; element counts "
                                      "must be re-read from the live Figure"})
                labels = (declared.get("labels") or {}).get("tick_texts") or []
                if pdf_info["text_layer"]:
                    text = pdf_info["text"]
                    missing = [label for label in labels
                               if str(label) not in text]
                    if labels:
                        _check(checks, "pdf_labels_present", not missing,
                               len(labels), len(labels) - len(missing),
                               "all recorded tick labels appear in the PDF "
                               "text layer" if not missing else
                               f"labels missing from the PDF text layer: "
                               f"{missing[:6]}")
                    unverifiable.append({
                        "what": "pdf_label_geometry",
                        "reason": "extracted text spans do not expose the "
                                  "rotated tick-label boxes; overlap must be "
                                  "re-measured from the live Figure"})
                else:
                    unverifiable.append({
                        "what": "pdf_text_layer",
                        "reason": "the PDF has no text layer (rasterised); "
                                  "tick labels cannot be checked from it"})
            except Exception as exc:
                _check(checks, "pdf_readable", False, "readable", None,
                       f"{type(exc).__name__}: {exc}")
    else:
        unverifiable.append({"what": "pdf", "reason":
                             "no PDF was inspected (pdf_path not given)"})

    return {
        "spec_id": str(spec_id),
        "ok": bool(checks) and all(item["ok"] for item in checks),
        "fully_verified": not unverifiable,
        "checks": checks,
        "unverifiable": unverifiable,
        "png": png_info,
        "pdf": pdf_info,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _import_figure(source: str, root: str):
    path = Path(source)
    mapping: Mapping = {}
    dataset = None
    if path.suffix.lower() == ".json" and path.is_file():
        spec = json.loads(path.read_text(encoding="utf-8"))
        source = str(spec.get("figure") or spec.get("module") or "")
        mapping = spec.get("mapping") or {}
        dataset = spec.get("dataset")
        if dataset and not os.path.isabs(str(dataset)):
            dataset = str(Path(root) / str(dataset))
    module_name, _, function_name = source.partition(":")
    if not module_name or not function_name:
        raise ValueError("inspect --figure needs 'module:function' or a JSON "
                         "spec with a 'figure' entry")
    for candidate in (root, os.path.join(root, "empirical-research-pipeline",
                                        "scripts")):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    module = importlib.import_module(module_name)
    function = getattr(module, function_name)
    result = function()
    if isinstance(result, Mapping) and "figure" in result:
        return result["figure"], result.get("mapping") or mapping, \
            result.get("dataset") or dataset
    if isinstance(result, tuple):
        fig = result[0]
        mapping = result[1] if len(result) > 1 else mapping
        dataset = result[2] if len(result) > 2 else dataset
        return fig, mapping, dataset
    return result, mapping, dataset


def _load_dataset(path: str):
    import pandas as pd
    if path.lower().endswith((".csv", ".tsv")):
        return pd.read_csv(path, sep="\t" if path.lower().endswith(".tsv")
                           else ",")
    return pd.read_json(path)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="figure semantics: artists vs data, label geometry, "
                    "palette roles, figure_spec records")
    parser.add_argument("--root", default=".", help="project root (default .)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect = subparsers.add_parser("inspect", help="inspect a live Figure")
    inspect.add_argument("--figure", required=True,
                         help="'module:function' or a JSON spec")
    inspect.add_argument("--json-out", default=None,
                         help="also write the report to this file")
    check = subparsers.add_parser("check", help="check a saved PNG/PDF")
    check.add_argument("spec_id")
    check.add_argument("--png", default=None)
    check.add_argument("--pdf", default=None)
    args = parser.parse_args(argv)

    if args.command == "inspect":
        fig, mapping, dataset = _import_figure(args.figure, args.root)
        geometry = label_geometry(fig)
        report = {
            "figure": describe_axes(fig),
            "label_geometry": geometry,
            "layout_options": layout_options(fig, geometry),
            "palette": palette_report(fig),
        }
        if mapping and dataset is not None:
            frame = _load_dataset(dataset) if isinstance(dataset, str) else dataset
            report["checks"] = check_figure(fig, frame, mapping)
        text = json.dumps(_json_safe(report), ensure_ascii=False, indent=1,
                          allow_nan=False)
        if args.json_out:
            Path(args.json_out).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0

    project = Project(args.root, create=False)
    record = project.latest("figure_spec", args.spec_id)
    png = args.png or (record["data"].get("png") if record else "")
    pdf = args.pdf or (record["data"].get("pdf") if record else "")
    result = check_saved(args.spec_id, png or "", pdf or "", root=args.root)
    print(json.dumps(_json_safe(result), ensure_ascii=False, indent=1,
                     allow_nan=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":                        # pragma: no cover - CLI
    sys.exit(_main(sys.argv[1:]))
