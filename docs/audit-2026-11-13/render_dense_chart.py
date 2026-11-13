"""Reproducible SYNTHETIC layout fixture; these are not research results."""
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "empirical-research-pipeline" / "scripts"))
from auto_chart_pack import ChartPack
from pubfig import set_style


def main():
    set_style()
    folder = Path(__file__).resolve().parent
    names = ["宣告缓刑", "缴纳罚金", "自首", "坦白", "认罪认罚",
             "立功", "退赔", "生态修复与被害人谅解", "前科劣迹", "累犯"]
    counts = [62, 71, 30, 52, 39, 2, 8, 41, 3, 11]
    # Exactly 100 synthetic observations per item, with known integer counts.
    df = pd.DataFrame({f"v{i}": [1]*k + [0]*(100-k) for i, k in enumerate(counts)})
    pack = ChartPack(df, str(folder), {"variable_labels": dict(zip(df, names))},
                     ["png", "pdf"], top_n=8, min_n=5)
    save = pack.save
    def save_synthetic(fig, *args, **kwargs):
        fig.axes[0].set_title("合成排版测试（非研究结果）", fontsize=9)
        save(fig, *args, **kwargs)
    pack.save = save_synthetic
    pack.binary_prevalence(None, list(df))
    manifest = {"fixture": "SYNTHETIC, not research evidence", "n": 100,
                "counts": counts, "charts": pack.manifest}
    (folder / "dense_chart_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if pack.errors:
        raise SystemExit(2)
    import fitz
    with fitz.open(folder / pack.manifest[0]["pdf"]) as pdf:
        pdf[0].get_pixmap(dpi=150).save(str(folder / "dense_chart_preview.png"))
    print(json.dumps({"status": "passed", "charts": len(pack.manifest),
                      "categories": len(counts), "layout": pack.manifest[0]["tick_layout"]}))


if __name__ == "__main__":
    main()
