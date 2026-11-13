"""Reproduce colour/layout audit figures. All observations are synthetic.

Run from the repository root: python docs/audit-2026-11-14-palette/render_synthetic.py
No source material or empirical research conclusions are used here.
"""
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "empirical-research-pipeline" / "scripts"))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import auto_chart_pack as cp
import pubfig as pf
import qa_outputs as qa


def main():
    out = Path(__file__).resolve().parent / "synthetic"
    df = pd.DataFrame([
        {"g": group, "y": f"C{i+1}"}
        for group in ("A", "B") for i in range(9) for _ in range(i + 1)
    ])
    df["id"] = np.arange(len(df))
    df["signal"] = np.sin(df["id"] / 10)
    palette = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#F0E442",
               "#56B4E9", "#E69F00", "#111111", "#999999"]
    pack = cp.ChartPack(df, str(out), {"palette": palette}, ["png", "pdf"], 20, 2)
    geometry = {}
    original_save = cp.save_fig
    original_write = pf._write_formats

    def with_title(fig, *args, **kwargs):
        fig.axes[0].set_title("SYNTHETIC COLOUR AUDIT")
        def capture(*write_args, **write_kwargs):
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            legend = fig.axes[0].get_legend().get_window_extent(renderer)
            title = fig.axes[0].title.get_window_extent(renderer)
            geometry.update({"title_legend_gap_pt": float((title.y0 - legend.y1) * 72 / fig.dpi),
                             "title_inside_canvas": bool(title.y1 <= fig.bbox.y1),
                             "legend_entries": len(fig.axes[0].get_legend().get_texts())})
            return original_write(*write_args, **write_kwargs)
        with patch("pubfig._write_formats", side_effect=capture):
            return original_save(fig, *args, **kwargs)

    with patch("auto_chart_pack.save_fig", side_effect=with_title):
        pack.categorical_outcome_by("y", "g", "nine_classes", "synthetic colour audit")
    fig, ax = plt.subplots(figsize=(15 / 2.54, 3.8))
    scatter = ax.scatter(df["id"], df["signal"], c=df["id"], cmap="viridis")
    fig.colorbar(scatter, ax=ax, label="synthetic index")
    ax.set_title("SYNTHETIC COLOUR AUDIT")
    pack.save(fig, "continuous", "synthetic", "synthetic continuous audit", "scatter",
              ["id", "signal"], len(df), "Synthetic observations only; N=90")
    pack.write({"data": "SYNTHETIC ONLY", "n": len(df)})
    checks = {"manifest": qa.check_manifest(str(out / "chart_manifest.csv"), colorblind=True),
              "figures": qa.check_figures(str(out / "figures"), min_dpi=600,
                                           min_fontsize=7.2, width_cm=15)}
    result = {"synthetic": True, "geometry": geometry, "checks": checks,
              "error_count": sum(len(c["errors"]) for c in checks.values()),
              "warning_count": sum(len(c["warnings"]) for c in checks.values())}
    (out / "qa.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "geometry": geometry,
                      "errors": result["error_count"], "warnings": result["warning_count"]}))
    if pack.errors or result["error_count"] or geometry.get("title_legend_gap_pt", 0) < 2.9:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
