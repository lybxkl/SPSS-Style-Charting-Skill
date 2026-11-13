"""Synthetic counterexamples for palette semantics, rendering and QA coverage."""
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex

from _helpers import TempCase, run, write_csv, read_csv, make_png, SCRIPTS
import qa_outputs as qa
import pubfig as pf
import auto_chart_pack as cp


class PaletteDetails(TempCase):
    def manifest(self, palette="", **extra):
        row = {"id":"F1", "question":"synthetic", "chart_type":"bar", "variables":"x",
               "n":5, "png":make_png(self.p("fig.png")), "pdf":"", "caption":"N=5", "palette":palette}
        row.update(extra)
        return write_csv(self.p("manifest.csv"), list(row), [row])

    def test_black_white_cvd_does_not_warn_merely_for_equal_hue(self):
        result = qa.check_palette(["#111111", "#EEEEEE"], colorblind=True, strict=True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertGreater(result["min_delta_e"], 80)

    def test_cvd_distance_threshold_actually_controls_advice(self):
        colors = ["#D62728", "#2CA02C"]
        self.assertEqual(qa.check_palette(colors, colorblind=True, min_delta_e=0)["warnings"], [])
        self.assertTrue(qa.check_palette(colors, colorblind=True, min_delta_e=100)["warnings"])

    def test_unparseable_colour_is_incomplete_and_strict_request_fails(self):
        path = self.manifest("#111111|NOT-A-COLOR", palette_kind="categorical")
        result = qa.check_manifest(path)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["warnings"])
        self.assertFalse(result["palettes"][0]["pairwise_checked"])
        self.assertFalse(result["palettes"][0]["complete"])
        self.assertEqual(result["palette_unchecked"], 1)
        self.assertTrue(qa.check_manifest(path, strict_palette=True)["errors"])

    def test_colour_aliases_do_not_count_as_distinct_series_colours(self):
        result = qa.check_manifest(self.manifest("white|#fff|#FFFFFF", n_series=3))
        self.assertTrue(any("1 distinct" in message for message in result["warnings"]))

    def test_named_colours_with_spaces_survive_manifest_parsing(self):
        colors = qa.parse_palette("xkcd:sky blue|#F00")
        self.assertEqual(colors, ["xkcd:sky blue", "#F00"])
        self.assertEqual(qa.check_palette(colors)["unparsed"], [])

    def test_alpha_needs_rendered_review_without_forcing_a_palette_change(self):
        result = qa.check_manifest(self.manifest("#FF000080|#000000FF"), strict_palette=True)
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["palettes"][0]["complete"])
        self.assertFalse(result["palettes"][0]["strict"])
        self.assertEqual(result["palette_unchecked"], 1)
        self.assertTrue(any("opacity" in message for message in result["warnings"]))

    def test_invalid_threshold_cannot_silently_disable_a_requested_check(self):
        for threshold in (float("nan"), float("inf"), -1):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                qa.check_palette(["red", "blue"], min_delta_l=threshold)

    def test_cvd_only_inferred_cycle_is_not_claimed_as_actual_colour_verification(self):
        result = qa.check_manifest(self.manifest(n_series=2), graycheck=False, colorblind=True)
        self.assertEqual(result["palette_unchecked"], 1)
        self.assertFalse(result["palettes"][0]["complete"])
        self.assertEqual(result["palettes"][0]["source"], "assumed_default_cycle")

    def test_custom_mapping_keeps_its_freedom_but_invalid_metadata_is_visible(self):
        result = qa.check_manifest(self.manifest("red|NOT-A-COLOR", palette_kind="custom-map"), strict_palette=True)
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["palettes"][0]["pairwise_checked"])
        self.assertTrue(result["warnings"])

    def test_nonfinite_or_fractional_series_count_does_not_crash_or_get_truncated(self):
        for count in ("inf", "NaN", "1.9"):
            with self.subTest(count=count):
                result = qa.check_manifest(self.manifest(n_series=count))
                self.assertEqual(result["errors"], [])
                self.assertTrue(any("invalid n_series" in w for w in result["warnings"]))

    def test_review_pack_exposes_unassessed_palette_scope(self):
        file = self.p("qa.json")
        Path(file).write_text(json.dumps({"error_count":0,"warning_count":0,"checks":{"manifest":{
            "errors":[],"warnings":[],"palette_unchecked":2,"palette_eligible":2}}}), encoding="utf-8")
        result = run("review_pack.py", "--qa", file, "--out", self.p("review.md"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 张未完成", Path(self.p("review.md")).read_text(encoding="utf-8"))


class ColourRendering(TempCase):
    def tearDown(self):
        plt.close("all")
        super().tearDown()

    def test_chartpack_initialises_style_before_drawing_without_resetting_user_style(self):
        code = f"""
import sys, json
sys.path.insert(0, {SCRIPTS!r})
import pandas as pd
import pubfig as pf
from auto_chart_pack import ChartPack
import matplotlib.pyplot as plt
df = pd.DataFrame({{'x': [1]}})
ChartPack(df, {self.p('style')!r}, {{}}, ['png'], 8, 2)
fig, ax = plt.subplots()
default_size = ax.xaxis.label.get_fontsize()
families = ax.xaxis.label.get_fontfamily()
pf.set_style(base_size=11)
ChartPack(df, {self.p('custom_style')!r}, {{}}, ['png'], 8, 2)
fig2, ax2 = plt.subplots()
print(json.dumps({{'default_size': default_size, 'families': families,
                  'custom_size': ax2.xaxis.label.get_fontsize()}}))
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        sizes = json.loads(result.stdout)
        self.assertEqual(sizes["default_size"], 8.5)
        self.assertIn("Times New Roman", sizes["families"])
        self.assertEqual(sizes["custom_size"], 11)

    def test_nine_class_legend_and_title_are_separate_on_export_canvas(self):
        df = pd.DataFrame({"g": np.repeat(["A", "B"], 9),
                           "y": [f"C{i}" for i in range(9)] * 2})
        pack = cp.ChartPack(df, self.p("pack"), {}, ["png"], 20, 2)
        original_save = cp.save_fig
        observed = {}
        def inspect(fig, *args, **kwargs):
            fig.axes[0].set_title("SYNTHETIC COLOUR AUDIT")
            original_write = pf._write_formats
            def capture(*write_args, **write_kwargs):
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
                observed["legend"] = fig.axes[0].get_legend().get_window_extent(renderer)
                observed["title"] = fig.axes[0].title.get_window_extent(renderer)
                observed["canvas"] = fig.bbox
                return original_write(*write_args, **write_kwargs)
            with patch("pubfig._write_formats", side_effect=capture):
                return original_save(fig, *args, **kwargs)
        with patch("auto_chart_pack.save_fig", side_effect=inspect):
            pack.categorical_outcome_by("y", "g", "nine", "synthetic")
        self.assertEqual(pack.errors, 0, pack.manifest)
        self.assertGreater(observed["title"].y0, observed["legend"].y1 + 1)
        self.assertLessEqual(observed["title"].y1, observed["canvas"].y1)
        self.assertGreaterEqual(observed["legend"].y0, 0)

    def test_title_legend_layout_cannot_hide_missing_glyph_warning(self):
        with plt.rc_context({"font.family": ["DejaVu Sans"]}):
            fig, ax = plt.subplots(figsize=(3, 2))
            ax.plot([0, 1], [0, 1], label="synthetic")
            ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01))
            ax.set_title("维度")
            with self.assertRaisesRegex(RuntimeError, "渲染不出来"):
                pf.save_fig(fig, self.tmp, "missing-glyph", formats=("png",))
        self.assertFalse(Path(self.p("missing-glyph.png")).exists())

    def test_scatter_numpy_rgba_and_short_colour_names_are_collected(self):
        fig, ax = plt.subplots()
        ax.scatter([0,1], [0,1], c=np.array([[1,0,0,1],[0,0,1,1]]))
        ax.plot([0,1], [1,0], color="k")
        ax.plot([0,1], [2,2], color="w")
        ax.plot([0,1], [3,3], color="green", visible=False)
        fig.canvas.draw()
        colors = pf.figure_color_metadata(fig.axes)["colors"]
        self.assertEqual(set(colors), {"#FF0000", "#0000FF", "#000000", "#FFFFFF"})

    def test_line_markers_keep_their_separate_actual_face_and_edge_colours(self):
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1], color="blue", marker="o",
                markerfacecolor="red", markeredgecolor="black")
        ax.plot([0, 1], [1, 0], color="blue", marker="None", markerfacecolor="green")
        colors = pf.figure_color_metadata(fig.axes)["colors"]
        self.assertEqual(set(colors), {"#0000FF", "#FF0000", "#000000"})

    def test_scalar_image_records_real_colormap_without_fake_default_cycle(self):
        fig, ax = plt.subplots()
        ax.imshow([[0,1,2]], cmap="Blues")
        metadata = pf.figure_color_metadata(fig.axes)
        self.assertEqual(metadata["colors"], [])
        self.assertEqual(metadata["kind"], "continuous")
        self.assertEqual(metadata["colormaps"], ["Blues"])

    def test_scalar_scatter_does_not_expand_every_gradient_colour_into_a_category(self):
        fig, ax = plt.subplots()
        ax.scatter(np.arange(100), np.arange(100), c=np.arange(100), cmap="viridis")
        fig.canvas.draw()
        metadata = pf.figure_color_metadata(fig.axes)
        self.assertEqual(metadata["kind"], "continuous")
        self.assertEqual(metadata["colors"], [])
        self.assertEqual(metadata["colormaps"], ["viridis"])

    def test_rgb_image_does_not_claim_an_unused_default_colormap(self):
        fig, ax = plt.subplots()
        ax.imshow(np.ones((2,2,3)))
        metadata = pf.figure_color_metadata(fig.axes)
        self.assertEqual(metadata["kind"], "image")
        self.assertEqual(metadata["colormaps"], [])

    def test_custom_chart_palette_reaches_actual_artists_and_manifest(self):
        df = pd.DataFrame({"g":["A","A","B","B"], "y":["C","C","D","D"]})
        palette = ["#123456", "#ABCDEF"]
        pack = cp.ChartPack(df, self.p("pack"), {"palette":palette}, ["png"], 8, 2)
        observed, faces = set(), set()
        save = cp.save_fig
        def capture(fig, *args, **kwargs):
            for p in fig.axes[0].patches:
                faces.add(to_hex(p.get_facecolor()).upper())
                for color in (p.get_facecolor(), p.get_edgecolor()):
                    if color[3] > 0:
                        observed.add(to_hex(color).upper())
            return save(fig, *args, **kwargs)
        with patch("auto_chart_pack.save_fig", side_effect=capture):
            pack.categorical_outcome_by("y", "g", "custom", "synthetic")
        self.assertEqual(pack.errors, 0, pack.manifest)
        self.assertEqual(faces, set(palette))
        self.assertEqual(set(pack.manifest[0]["palette"].split("|")), observed)
        self.assertEqual(pack.group_colors("y", ["D"]), [palette[1]])

    def test_invalid_palette_cli_reports_configuration_error_without_traceback(self):
        data = write_csv(self.p("data.csv"), ["id","outcome_binary"], [[i,i%2] for i in range(12)])
        config = self.p("config.json")
        Path(config).write_text(json.dumps({"outcome":"outcome_binary","palette":["NOT-A-COLOR"]}),encoding="utf-8")
        result = run("auto_chart_pack.py", "--data", data, "--config", config,
                     "--out", self.p("pack"), "--only", "binary_prevalence")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid chart configuration", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_mds_keeps_nine_groups_and_outlier_inside_plot(self):
        xy = np.column_stack((np.arange(36), np.arange(36))).astype(float)
        xy[-1,0] = 10000
        groups = np.repeat([f"g{i}" for i in range(9)], 4)
        fig, ax = plt.subplots()
        pf.mds_plot(ax, xy, groups=groups)
        self.assertEqual(len(ax.collections), 9)
        self.assertEqual(sum(len(c.get_offsets()) for c in ax.collections), 36)
        self.assertGreater(ax.get_xlim()[1], 10000)

    def test_km_keeps_nine_eligible_groups(self):
        groups = np.repeat([f"g{i}" for i in range(9)], 4)
        fig, ax = plt.subplots()
        pf.kaplan_meier(ax, [1,2,3,4]*9, [1,0,1,0]*9, group=groups)
        self.assertEqual(len(ax.lines), 9)

    def test_km_does_not_silently_remove_small_groups_from_total_n(self):
        fig, ax = plt.subplots()
        pf.kaplan_meier(ax, [1,1,2,1,2,3,4], [1,1,0,1,0,1,0],
                        group=["A","B","B","C","C","C","C"])
        self.assertEqual(len(ax.lines), 3)
        self.assertEqual(sum(int(line.get_label().split("n=")[1].rstrip(")")) for line in ax.lines), 7)
