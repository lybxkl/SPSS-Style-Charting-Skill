#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble journal figures (Figure1.png/pdf/tiff) from a ``paper.json`` spec.

``auto_chart_pack.py`` produces one chart per question. A manuscript needs the
opposite: a handful of *composite* figures, each one a labelled panel grid drawn
on a single 15 cm canvas. This script is that step, and it writes the same
manifest v2 columns as the chart pack so ``qa_outputs.py`` can audit both with
one command.

Usage:
    python paper_figures.py --paper paper.json --out output/paper_figs
    python paper_figures.py --paper paper.json --out out --tiff --dpi 600
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import warnings


import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from pubfig import (  # noqa: E402
    CM, INK, CATEGORICAL, set_style, style_axis, bar_counts, bar_with_ci,
    stacked_bar, line_ci, scatter_fit, pie_chart, forest_plot, compose_figure,
)
#: Reading N is the checker's job, not a second implementation's: a manifest we
#: write with one parser and audit with another silently validates its own bug.
from qa_outputs import parse_n as _checker_parse_n  # noqa: E402

N_SCOPES = ("sample", "subgroup", "corpus")
WIDTH_CM = 15.0
# Same order as ``auto_chart_pack.MANIFEST_COLUMNS``: qa_outputs.py reads both.
MANIFEST_COLUMNS = ["id", "question", "chart_type", "variables", "n", "n_scope",
                    "png", "pdf", "caption", "dpi", "px_width", "model_id",
                    "data_hash", "tiff", "note", "section", "status", "palette"]

#: Digits with thousands separators.  A space belongs to the number only
#: when another digit follows it, so "N=2,713 份" keeps its space.
_N_NUM_RE = r"\d(?:[\d,，]|[\s\u00a0](?=\d))*"
_N_TOKEN_RE = re.compile(
    rf"[Nn]\s*[=＝]\s*{_N_NUM_RE}(?:[→\-–—~～至]\s*{_N_NUM_RE})?")
_N_PREFIX_RE = re.compile(r"^[NnＮ]\s*[=＝]\s*")
_LOG_METRICS = {"OR", "HR", "RR", "AOR", "ODDS RATIO", "HAZARD RATIO"}


# --------------------------------------------------------------- small helpers

def parse_n(value) -> tuple[int | None, str]:
    """Return ``(int, display)`` for ``2713`` / ``2,713`` / ``N=2713`` / ``3111→2713``.

    The number comes from :func:`qa_outputs.parse_n` -- the very parser that later
    audits the manifest -- so the producer cannot truncate what the checker would
    have accepted.  A range keeps its original text for the caption (``3 111→2 713``)
    but resolves to its first number, which is the contract in
    ``docs/CONTRACTS.md`` section 3.
    """
    if value is None or isinstance(value, bool):
        return None, ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not float(value).is_integer():
            return None, str(value)
        number = int(value)
        return number, f"{number:,}"
    text = str(value).strip()
    if not text:
        return None, ""
    number, is_range = _checker_parse_n(text)
    if number is None:
        return None, text
    if is_range:
        return number, _N_PREFIX_RE.sub("", text.replace("＝", "=")).strip()
    return number, f"{number:,}"


def _n_digits(raw: str) -> str:
    """``N=2,713`` -> ``2713`` (only digits matter when comparing two tokens)."""
    return re.sub(r"[^0-9]", "", _N_PREFIX_RE.sub("", raw))


def fill_caption_n(caption: str, display: str) -> tuple[str, str | None]:
    """Rewrite the caption's N, returning ``(text, conflict)``.

    Only the **first** ``N=`` belongs to the figure's own sample size.  A caption
    such as "N=3,111 份文书；其中 N=2,713 份有金额" carries two different numbers;
    overwriting both with one value silently rewrites the population into the
    analytic subset, so a differing second token is left alone and reported back
    through ``conflict`` (``None`` when there is nothing to report).
    """
    text = str(caption or "").strip()
    token = f"N={display}"
    matches = list(_N_TOKEN_RE.finditer(text))
    if not matches:
        return (f"{text}（{token}）" if text else f"注：{token}。"), None
    wanted = re.sub(r"[^0-9]", "", str(display))
    pieces = []
    last = 0
    conflict = None
    for index, match in enumerate(matches):
        pieces.append(text[last:match.start()])
        raw = match.group(0)
        if index == 0 or _n_digits(raw) == wanted:
            pieces.append(token)
        else:
            pieces.append(raw)
            if conflict is None:
                conflict = raw
        last = match.end()
    pieces.append(text[last:])
    return "".join(pieces), conflict


def png_pixel_info(path: str) -> tuple[int, int]:
    """``(dpi, px_width)`` read back from the written PNG; ``(0, 0)`` on failure."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            dpi = image.info.get("dpi") or (0, 0)
            return int(round(float(dpi[0]))), int(image.size[0])
    except Exception:
        return 0, 0


def rel_posix(path: str, base: str) -> str:
    """Path relative to the manifest directory, with POSIX separators."""
    if not path:
        return ""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
    except ValueError:  # different drive: keep an absolute path, still POSIX
        rel = os.path.abspath(path)
    return rel.replace("\\", "/")


def spec_hash(spec) -> str:
    """8-char md5 over the canonical paper spec (reproducibility anchor)."""
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:8]


def _column(data: dict, *names, default=None):
    for name in names:
        if isinstance(data, dict) and data.get(name) is not None:
            return data[name]
    return default


def _series_block(data: dict) -> tuple[list[str], list[list[float]], list[str]]:
    """Normalise ``series`` into (labels, values-by-row, series-labels) for stacked_bar."""
    raw = data.get("series") or []
    labels: list[str] = []
    rows: list[list[float]] = []
    names: list[str] = []
    if raw and isinstance(raw[0], dict):
        for item in raw:
            names.append(str(item.get("label", f"系列{len(names) + 1}")))
            rows.append([float(v) for v in (item.get("values") or [])])
        labels = [str(v) for v in _column(data, "x", "rows", "labels", default=[])]
    else:  # list of lists
        rows = [[float(v) for v in item] for item in raw]
        names = [str(v) for v in _column(data, "series_labels", "legend", default=[])]
        if len(names) < len(rows):
            names += [f"系列{i}" for i in range(len(names), len(rows))]
        labels = [str(v) for v in _column(data, "x", "rows", "labels", default=[])]
    if not labels and rows:
        labels = [str(i + 1) for i in range(len(rows[0]))]
    return labels, rows, names


# ------------------------------------------------------------------ chart draws

def draw_bar(ax, data: dict) -> None:
    labels = [str(v) for v in _column(data, "x", "labels", "categories", default=[])]
    values = _column(data, "y", "values", "counts", default=[])
    bar_counts(ax, labels, values, horizontal=bool(data.get("horizontal")),
               color=data.get("color", "#1C4E7B"))


def draw_bar_with_ci(ax, data: dict) -> None:
    labels = [str(v) for v in _column(data, "x", "labels", default=[])]
    est = _column(data, "estimate", "y", "values", default=[])
    low = _column(data, "low", "lo", "ci_low", default=[])
    high = _column(data, "high", "hi", "ci_high", default=[])
    bar_with_ci(ax, labels, est, low, high, annotate=bool(data.get("annotate")))


def draw_stacked_bar(ax, data: dict) -> None:
    labels, rows, names = _series_block(data)
    stacked_bar(ax, labels, rows, names, normalize=bool(data.get("normalize", True)),
                legend=bool(data.get("legend", True)))


def draw_line(ax, data: dict) -> None:
    x = _column(data, "x", default=list(range(len(_column(data, "y", "values", default=[])))))
    y = _column(data, "y", "values", default=[])
    line_ci(ax, x, y, _column(data, "low", "y_low", "ci_low"),
            _column(data, "high", "y_high", "ci_high"),
            label=data.get("label"), ylabel=data.get("ylabel", ""),
            xlabel=data.get("xlabel", ""))


def draw_scatter(ax, data: dict) -> None:
    x = _column(data, "x", default=[])
    y = _column(data, "y", default=[])
    if data.get("fit", True):
        scatter_fit(ax, x, y, xlabel=data.get("xlabel", ""), ylabel=data.get("ylabel", ""))
    else:
        ax.scatter(x, y, s=9, color=data.get("color", "#1C4E7B"), alpha=0.75,
                   edgecolor="none")
        style_axis(ax, "both")


def draw_hist(ax, data: dict) -> None:
    values = [float(v) for v in _column(data, "values", "x", "y", default=[])
              if v == v]
    bins = int(data.get("bins", 24))
    ax.hist(values, bins=bins, color=data.get("color", "#1C4E7B"), alpha=0.82,
            edgecolor="white", linewidth=0.4, zorder=2)
    ax.set_xlabel(data.get("xlabel", ""))
    ax.set_ylabel(data.get("ylabel", "频数"))
    style_axis(ax, "y")


def draw_pie(ax, data: dict) -> None:
    labels = [str(v) for v in _column(data, "labels", "x", default=[])]
    values = _column(data, "values", "y", default=[])
    pie_chart(ax, labels, values, donut=bool(data.get("donut", True)),
              sort=bool(data.get("sort", True)))


def _forest_frame(data: dict):
    """Return (labels, estimates, lows, highs, metric) from a CSV path or arrays."""
    path = data.get("coef") or data.get("coef_path") or data.get("file")
    if path:
        import pandas as pd
        frame = pd.read_csv(path)
        rename = {str(c).strip().lower(): c for c in frame.columns}
        term_col = next((rename[k] for k in ("term", "variable", "name") if k in rename), None)
        metric_col = rename.get("metric")
        metric = ""
        if metric_col is not None:
            values = [str(v).strip() for v in frame[metric_col].dropna().tolist()]
            metric = values[0].upper() if values else ""
        est_col = next((rename[k] for k in ("or", "estimate", "beta", "hr", "coef")
                        if k in rename), None)
        low_col = next((rename[k] for k in ("or_low", "ci_low", "low", "ci_lower")
                        if k in rename), None)
        high_col = next((rename[k] for k in ("or_high", "ci_high", "high", "ci_upper")
                         if k in rename), None)
        if term_col is None or est_col is None or low_col is None or high_col is None:
            raise ValueError(f"coef CSV needs term/estimate/ci_low/ci_high columns: {path}")
        if not metric:
            metric = "OR" if str(est_col).lower() in ("or", "hr", "rr") else ""
        labels = [str(v) for v in frame[term_col].tolist()]
        return (labels,
                [float(v) for v in frame[est_col].astype(float).tolist()],
                [float(v) for v in frame[low_col].astype(float).tolist()],
                [float(v) for v in frame[high_col].astype(float).tolist()],
                metric)
    labels = [str(v) for v in _column(data, "terms", "term", "labels", "x", default=[])]
    return (labels,
            _column(data, "estimate", "y", "values", default=[]),
            _column(data, "low", "ci_low", default=[]),
            _column(data, "high", "ci_high", default=[]),
            str(data.get("metric", "")).strip().upper())


def draw_forest(ax, data: dict) -> None:
    labels, est, low, high, metric = _forest_frame(data)
    if not labels:
        raise ValueError("forest panel needs a 'coef' CSV path or term/estimate arrays")
    log_scale = metric in _LOG_METRICS
    ref = 1.0 if log_scale else 0.0
    forest_plot(ax, labels, est, low, high, ref=ref, log_scale=log_scale,
                xlabel=data.get("xlabel") or ("OR（95%CI）" if log_scale else "β（95%CI）"))


CHART_DRAW = {
    "bar": draw_bar,
    "bar_with_ci": draw_bar_with_ci,
    "stacked_bar": draw_stacked_bar,
    "line": draw_line,
    "scatter": draw_scatter,
    "hist": draw_hist,
    "pie": draw_pie,
    "forest": draw_forest,
}


# --------------------------------------------------------------- figure build

def panel_data_length(panel: dict) -> int:
    """Best-effort N for one panel: array length, or the coef CSV row count."""
    data = panel.get("data") or {}
    if data.get("coef") or data.get("coef_path") or data.get("file"):
        try:
            import pandas as pd
            return int(len(pd.read_csv(data.get("coef") or data.get("coef_path")
                                       or data.get("file"))))
        except Exception:
            return 0
    best = 0
    for key in ("x", "y", "values", "labels", "estimate", "low", "high",
                "terms", "series"):
        value = data.get(key)
        if isinstance(value, (list, tuple)):
            length = len(value)
        elif isinstance(value, dict):
            length = len(value.get("values") or [])
        else:
            continue
        best = max(best, length)
    return best


def figure_n(spec: dict, data_rows: int | None = None):
    """The declared N, or ``None``.

    N is never inferred from the panel data: a forest panel has one row per
    coefficient and a bar panel has one row per category, so "rows of panel
    data" can only ever be a coincidentally plausible lie.

    The one sanctioned exception is an explicit ``"n": "auto"`` together with
    ``--data``: then N is the number of analysis rows, which is exactly the
    quantity a caption's "N=" is supposed to name.  The row records
    ``note=n_from=data rows`` so a reader can see it was not typed by hand.
    """
    raw = spec.get("n")
    if raw in (None, ""):
        return None, ""
    if isinstance(raw, str) and raw.strip().lower() == "auto":
        if not data_rows:
            raise ValueError(
                "n is 'auto' but no analysis data was given; pass --data <file> "
                "or write the sample size explicitly")
        return int(data_rows), "n_from=data rows"
    number, _ = parse_n(raw)
    return (int(number) if number is not None else None), ""


def build_panels(spec: dict) -> tuple[list[dict], list[str], list[str]]:
    """Turn the JSON panel list into ``compose_figure`` panels."""
    panels, charts, variables = [], [], []
    for index, raw in enumerate(spec.get("panels") or []):
        chart = str(raw.get("chart", "bar")).strip().lower()
        draw = CHART_DRAW.get(chart)
        if draw is None:
            raise ValueError(f"unknown chart type {chart!r} "
                             f"(supported: {', '.join(sorted(CHART_DRAW))})")
        data = raw.get("data") or {}
        charts.append(chart)
        names = _column(data, "variables", default=None)
        if names:
            variables.extend([str(v) for v in (names if isinstance(names, list) else [names])])
        else:
            variables.extend([str(v) for v in _column(data, "x", "labels", default=[])][:4])

        def make(draw=draw, data=data):
            def draw_panel(ax):
                draw(ax, data)
            return draw_panel

        panels.append({
            "draw": make(),
            "label": raw.get("label"),
            "title": raw.get("title"),
            "xlabel": raw.get("xlabel"),
            "ylabel": raw.get("ylabel"),
            "legend": raw.get("legend"),
        })
        _ = index
    if not panels:
        raise ValueError("figure has no panels")
    return panels, charts, variables


def build_figure(spec: dict, out_dir: str, formats, dpi: int,
                 width_cm: float, data_rows: int | None = None) -> dict:
    """Compose one figure and return its manifest row."""
    fig_id = str(spec.get("id") or "").strip()
    if not fig_id:
        raise ValueError("every figure needs an 'id' (used as the file stem)")
    panels, charts, variables = build_panels(spec)
    n, n_note = figure_n(spec, data_rows)
    if n is not None and n <= 0:
        raise ValueError(f"{fig_id}: N must be positive (got {n})")
    scope = str(spec.get("n_scope") or "sample").strip().lower() or "sample"
    if scope not in N_SCOPES:
        warnings.warn(f"{fig_id}: unknown n_scope {scope!r}, using 'sample'")
        scope = "sample"
    # A range keeps its original wording (``3 111→2 713``) in both the manifest
    # cell and the caption; collapsing it to its first number is how the old
    # parser turned 3 111 documents into "N=3".
    notes = [n_note] if n_note else []
    if n is None:
        n_cell = "NA"
        status = "skipped: n unknown"
        notes.append("n_missing")
        caption = str(spec.get("caption", "") or "").strip()
    else:
        status = "ok"
        raw_n = spec.get("n")
        if isinstance(raw_n, str) and raw_n.strip().lower() == "auto":
            raw_n = None          # already resolved from --data; do not show "auto"
        if raw_n not in (None, ""):
            number, display = parse_n(raw_n)
            n_cell = display if display not in (f"{n:,}", str(n)) else n
        else:
            display, n_cell = f"{n:,}", n
        caption, conflict = fill_caption_n(spec.get("caption", ""), display)
        if conflict:
            notes.append(f"n_conflict=caption: 另有一个 {conflict}")

    columns = int(spec.get("ncols") or len(panels))
    rows = int(spec.get("nrows") or max(1, -(-len(panels) // max(1, columns))))
    result = compose_figure(
        panels, out_dir=out_dir, name=fig_id, nrows=rows, ncols=columns,
        width_cm=width_cm, height_cm=spec.get("height_cm"),
        formats=formats, dpi=dpi, title=spec.get("title"),
    )
    plt.close(result["fig"])
    by_ext = {os.path.splitext(p)[1].lstrip(".").lower(): p for p in result["paths"]}
    png = by_ext.get("png", "")
    dpi_png, px_width = png_pixel_info(png) if png else (0, 0)
    return {
        "id": fig_id,
        "question": str(spec.get("question", "")),
        "chart_type": " + ".join(dict.fromkeys(charts)),
        "variables": "; ".join(dict.fromkeys([v for v in variables if v])),
        "n": n_cell,
        "n_scope": scope,
        "png": rel_posix(png, out_dir),
        "pdf": rel_posix(by_ext.get("pdf", ""), out_dir),
        "caption": caption,
        "dpi": dpi_png or int(dpi),
        "px_width": px_width,
        "model_id": str(spec.get("model_id", "")),
        "data_hash": spec_hash(spec),
        "tiff": rel_posix(by_ext.get("tiff", ""), out_dir),
        "note": "; ".join([result["note"],
                           f"min_fontsize={result['min_fontsize_pt']:.1f}"] + notes),
        "section": ",".join(str(s) for s in (spec.get("sections") or [])),
        "status": status,
        # What the panels actually painted, so the grayscale gate has something
        # real to check (a declared-but-unused cycle would pass vacuously).
        "palette": "|".join(result.get("colors") or CATEGORICAL),
    }


def write_manifest(rows: list[dict], out_dir: str) -> str:
    import csv
    path = os.path.join(out_dir, "paper_figures_manifest.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


# ------------------------------------------------------------------------ CLI

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble paper figures from a paper.json spec.")
    parser.add_argument("--paper", required=True, help="figure spec (JSON)")
    parser.add_argument("--out", default="output/paper_figs", help="output directory")
    parser.add_argument("--tiff", action="store_true",
                        help="also write TIFF (png+pdf are always written)")
    parser.add_argument("--dpi", type=int, default=600, help="raster dpi (default 600)")
    parser.add_argument("--width-cm", type=float, default=WIDTH_CM,
                        help="figure width in cm (default 15.0)")
    parser.add_argument("--data", default=None,
                        help="analysis CSV; required only by figures with n='auto'")
    args = parser.parse_args()

    if not os.path.isfile(args.paper):
        print(f"ERROR: paper spec not found: {args.paper}", file=sys.stderr)
        return 2
    try:
        with open(args.paper, encoding="utf-8-sig") as handle:
            spec = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read {args.paper}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2
    figures = spec.get("figures") if isinstance(spec, dict) else None
    if not isinstance(figures, list) or not figures:
        print("ERROR: paper spec needs a non-empty 'figures' list", file=sys.stderr)
        return 2
    if args.dpi < 72:
        print("ERROR: --dpi must be at least 72", file=sys.stderr)
        return 2

    data_rows = None
    if args.data:
        try:
            import pandas as pd
            data_rows = int(len(pd.read_csv(args.data, low_memory=False)))
        except Exception as exc:
            print(f"ERROR: cannot read --data {args.data}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        print(f"data: {data_rows} rows ({args.data})")

    formats = ["png", "pdf"] + (["tiff"] if args.tiff else [])
    os.makedirs(args.out, exist_ok=True)
    try:
        set_style(args.width_cm)
    except RuntimeError as exc:            # missing CJK font -> tofu boxes
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    rows, errors = [], 0
    for spec_item in figures:
        fig_id = str(spec_item.get("id") or "?")
        try:
            row = build_figure(spec_item, args.out, formats, args.dpi,
                               args.width_cm, data_rows)
        except Exception as exc:
            errors += 1
            plt.close("all")
            print(f"ERROR {fig_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
            rows.append({
                "id": fig_id,
                "question": str(spec_item.get("question", "")),
                "chart_type": " + ".join(str(p.get("chart", "")) for p in
                                         (spec_item.get("panels") or [])),
                "variables": "", "n": "NA", "n_scope": "sample", "png": "", "pdf": "",
                "caption": str(spec_item.get("caption", "")), "dpi": int(args.dpi),
                "px_width": 0, "model_id": str(spec_item.get("model_id", "")),
                "data_hash": spec_hash(spec_item), "tiff": "",
                "note": "", "section": "", "status": f"error: {type(exc).__name__}",
            })
            continue
        rows.append(row)
        print(f"{row['id']}: {row['chart_type']}  n={row['n']} ({row['n_scope']})  "
              f"px={row['px_width']}  {row['png']}")

    manifest = write_manifest(rows, args.out)
    ok = sum(1 for row in rows if row["status"] == "ok")
    print(f"figures: {len(rows)}  ok: {ok}  errors: {errors}")
    print(f"manifest: {manifest}")
    return 2 if (errors or not ok) else 0


if __name__ == "__main__":
    raise SystemExit(main())
