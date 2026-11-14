# -*- coding: utf-8 -*-
"""Figure semantics: artists vs data, measured label geometry, palette roles.

Covers acceptance scenarios A37 (real palette usage reported as advice, never a
mandatory restyle) and A38's figure half (measured geometry and saved-file
checks; final Word/PDF placement is ``layout_check``'s job, not this module's).

Every expected mean/SD/count is computed here with pandas/numpy -- never with
the functions under test.
"""
import json
import os
import sys
import unittest

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.container import BarContainer

from _helpers import SCRIPTS, TempCase, run

import contract_v2 as C
import figsemantics as fs


# ---------------------------------------------------------------------------
# deterministic synthetic data
# ---------------------------------------------------------------------------
def bar_frame():
    """Three groups, three values each: means 4/5/6, sample SD 3.0."""
    return pd.DataFrame({
        "group": ["A", "B", "C", "A", "B", "C", "A", "B", "C"],
        "score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
    })


def scatter_frame():
    """Eight rows, three with a missing score -> five drawable points."""
    return pd.DataFrame({
        "age": [20, 21, 22, 23, 24, 25, 26, 27],
        "score": [1.0, 2.0, None, 4.0, 5.0, None, 7.0, None],
    })


class FigureCase(TempCase):
    """TempCase with a pinned matplotlib style (other modules may set 600 dpi)."""

    def setUp(self):
        super().setUp()
        self._rc = plt.rcParams.copy()
        plt.rcParams.update({
            "font.family": ["DejaVu Sans"],
            "font.size": 10.0,
            "figure.dpi": 100,
            "savefig.dpi": 150,
            "axes.unicode_minus": False,
        })

    def tearDown(self):
        plt.close("all")
        plt.rcParams.update(self._rc)
        super().tearDown()

    # -- drawing helpers (expected values computed from the data only) ------
    def bar_figure(self, frame, error_scale=None, colors=None):
        means = frame.groupby("group", sort=False)["score"].mean()
        stds = frame.groupby("group", sort=False)["score"].std(ddof=1)
        yerr = None if error_scale is None else stds.to_numpy() * error_scale
        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=100)
        ax.bar(list(means.index), means.to_numpy(), yerr=yerr, capsize=3,
               color=colors)
        fig.canvas.draw()
        return fig, ax, means, stds

    def dense_figure(self, count=60, width_cm=44.0, fontsize=7.2):
        """60 categories on a wide canvas: horizontal labels genuinely overlap.

        The canvas is deliberately wider than a 15 cm journal page.  At 15 cm
        the tick pitch of 60 labels is below the glyph height, so *no* rotation
        (30/45/60/75) can reduce the measured overlap -- the labels already
        overlap before rotation and would still overlap afterwards.  44 cm is
        the narrowest width found where rotation is the real repair, which is
        what this test needs to exercise; the checks below therefore assert a
        measured reduction, not a fixed dpi/width recipe.
        """
        labels = [f"group{i:02d}" for i in range(count)]
        fig, ax = plt.subplots(figsize=(width_cm / 2.54, 4.0), dpi=100)
        ax.bar(range(count), np.linspace(1.0, 20.0, count))
        ax.set_xticks(range(count))
        ax.set_xticklabels(labels)
        ax.tick_params(axis="x", labelsize=fontsize)
        fig.canvas.draw()
        return fig, ax, labels

    def rotate30(self, fig, ax):
        for tick in ax.get_xticklabels():
            tick.set_rotation(30)
            tick.set_rotation_mode("anchor")
            tick.set_ha("right")
            tick.set_va("center")
        fig.canvas.draw()

    def bar_containers(self, ax):
        return [container for container in ax.containers
                if isinstance(container, BarContainer)]


class DescribeAxesTest(FigureCase):
    def test_reads_artist_values_and_not_the_original_arguments(self):
        frame = bar_frame()
        fig, ax, means, stds = self.bar_figure(frame, error_scale=1.0)
        described = fs.describe_axes(fig)
        axis = described["axes"][0]
        self.assertEqual(len(axis["bars"]), 3)
        drawn = [bar["height"] for bar in axis["bars"]]
        for value, category in zip(drawn, means.index):
            self.assertAlmostEqual(value, means[category], places=12)
        self.assertEqual([tick["text"] for tick in axis["xticklabels"]],
                         ["A", "B", "C"])
        self.assertEqual(len(axis["errorbars"]), 3)
        for error in axis["errorbars"]:
            self.assertAlmostEqual(error["length"] / 2.0, stds["A"], places=12)

        # The report must follow the artist, not the value that was requested.
        self.bar_containers(ax)[0].patches[1].set_height(0.5)
        changed = fs.describe_axes(fig)["axes"][0]["bars"][1]
        self.assertAlmostEqual(changed["height"], 0.5, places=12)

    def test_3d_and_contour_are_reported_unverifiable_with_a_reason(self):
        fig = plt.figure()
        axes = fig.add_subplot(projection="3d")
        axes.scatter([1, 2], [2, 3], [3, 4])
        described = fs.describe_axes(fig)
        reasons = [item for item in described["unverifiable"]
                   if item["what"] == "3d"]
        self.assertTrue(reasons)
        self.assertTrue(all(item.get("reason") for item in reasons))

        fig2, ax2 = plt.subplots()
        ax2.contour(np.arange(25.0).reshape(5, 5))
        described2 = fs.describe_axes(fig2)
        self.assertTrue([item for item in described2["unverifiable"]
                         if item["what"] == "contour"])
        self.assertTrue(all(item.get("reason")
                            for item in described2["unverifiable"]))


class BarCheckTest(FigureCase):
    def test_bar_heights_match_means_and_a_changed_bar_names_its_category(self):
        frame = bar_frame()
        means = frame.groupby("group")["score"].mean()
        fig, ax, _, _ = self.bar_figure(frame)
        mapping = {"type": "bar", "x": "group", "y": "score"}

        result = fs.check_figure(fig, frame, mapping)
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["dropped"], 0)
        heights = {check["subject"]["category"]: check["observed"]
                   for check in result["checks"] if check["check"] == "bar_height"}
        for category in ("A", "B", "C"):
            self.assertAlmostEqual(heights[category], means[category], places=9)

        self.bar_containers(ax)[0].patches[1].set_height(0.5)   # category "B"
        failed = fs.check_figure(fig, frame, mapping)
        self.assertFalse(failed["ok"])
        bad = [check for check in failed["checks"] if not check["ok"]]
        self.assertTrue(bad)
        self.assertTrue(any(check.get("subject", {}).get("category") == "B"
                            for check in bad),
                        "the failing category must be named")
        self.assertIn("B", " ".join(check["detail"] for check in bad))

    def test_errorbar_length_matches_sd_and_a_shortened_bar_is_caught(self):
        frame = bar_frame()
        stds = frame.groupby("group")["score"].std(ddof=1)
        mapping = {"type": "bar", "x": "group", "y": "score",
                   "error": {"kind": "sd"}}

        fig, _, _, _ = self.bar_figure(frame, error_scale=1.0)
        good = fs.check_figure(fig, frame, mapping)
        self.assertTrue(good["ok"], good["checks"])
        observed = [check["observed"] for check in good["checks"]
                    if check["check"] == "error_length"]
        for value, category in zip(observed, stds.index):
            self.assertAlmostEqual(value, stds[category], places=9)

        short, _, _, _ = self.bar_figure(frame, error_scale=0.5)
        bad = fs.check_figure(short, frame, mapping)
        self.assertFalse(bad["ok"])
        failed = [check for check in bad["checks"] if not check["ok"]]
        self.assertTrue(failed)
        self.assertTrue(all(check["check"] == "error_length" for check in failed))
        for check in failed:
            self.assertAlmostEqual(check["observed"],
                                   stds[check["subject"]["category"]] / 2.0,
                                   places=9)

    def test_se_declaration_uses_the_standard_error(self):
        frame = bar_frame()
        counts = frame.groupby("group")["score"].count()
        stds = frame.groupby("group")["score"].std(ddof=1)
        mapping = {"type": "bar", "x": "group", "y": "score",
                   "error": {"kind": "se"}}
        # yerr is SD here: the figure is wrong on purpose and must be caught.
        fig, _, _, _ = self.bar_figure(frame, error_scale=1.0)
        wrong = fs.check_figure(fig, frame, mapping)
        self.assertFalse(wrong["ok"])
        expected_se = {category: stds[category] / np.sqrt(counts[category])
                       for category in stds.index}
        failed = [check for check in wrong["checks"] if not check["ok"]]
        for check in failed:
            self.assertAlmostEqual(check["expected"],
                                   expected_se[check["subject"]["category"]],
                                   places=9)

    def test_declared_sorting_is_honoured_and_absent_sorting_is_not_guessed(self):
        frame = pd.DataFrame({
            "group": ["C", "A", "B", "C", "A", "B"],
            "score": [6.0, 1.0, 2.0, 3.0, 4.0, 5.0],
        })
        means = frame.groupby("group")["score"].mean()      # A=2.5 B=3.5 C=4.5
        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=100)
        ax.bar(["A", "B", "C"], [means["A"], means["B"], means["C"]])
        fig.canvas.draw()
        base = {"type": "bar", "x": "group", "y": "score"}

        unsorted = fs.check_figure(fig, frame, base)
        self.assertFalse(unsorted["ok"])
        self.assertTrue(any(check["check"] == "category_labels"
                            and not check["ok"]
                            for check in unsorted["checks"]))

        declared = fs.check_figure(fig, frame, dict(base, sorting="ascending"))
        self.assertTrue(declared["ok"], declared["checks"])

    def test_grouped_bars_with_a_series_are_matched_per_group(self):
        frame = pd.DataFrame({
            "group": ["A", "A", "B", "B", "A", "A", "B", "B"],
            "arm": ["ctl", "ctl", "ctl", "ctl", "trt", "trt", "trt", "trt"],
            "score": [1.0, 3.0, 2.0, 4.0, 5.0, 7.0, 6.0, 8.0],
        })
        means = frame.groupby(["arm", "group"], sort=False)["score"].mean()
        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=100)
        positions = np.arange(2)
        width = 0.35
        ax.bar(positions - width / 2, [means[("ctl", "A")], means[("ctl", "B")]],
               width, label="ctl")
        ax.bar(positions + width / 2, [means[("trt", "A")], means[("trt", "B")]],
               width, label="trt")
        ax.set_xticks(positions)
        ax.set_xticklabels(["A", "B"])
        ax.legend()
        fig.canvas.draw()

        result = fs.check_figure(
            fig, frame,
            {"type": "bar", "x": "group", "y": "score", "series": "arm"})
        self.assertTrue(result["ok"], result["checks"])
        observed = {(check["subject"]["category"], check["subject"]["series"]):
                    check["observed"] for check in result["checks"]
                    if check["check"] == "bar_height"}
        for (arm, group), value in means.items():
            self.assertAlmostEqual(observed[(group, arm)], value, places=9)

    def test_changed_category_order_is_reported_with_the_first_mismatch(self):
        frame = bar_frame()
        means = frame.groupby("group")["score"].mean()
        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=100)
        order = ["B", "A", "C"]
        ax.bar(order, [means[category] for category in order])
        fig.canvas.draw()
        result = fs.check_figure(fig, frame,
                                 {"type": "bar", "x": "group", "y": "score"})
        self.assertFalse(result["ok"])
        failed = {check["check"]: check for check in result["checks"]
                  if not check["ok"]}
        self.assertIn("category_labels", failed)
        self.assertIn("order", failed["category_labels"]["detail"])

    def test_changed_category_text_is_reported(self):
        frame = bar_frame()
        means = frame.groupby("group")["score"].mean()
        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=100)
        ax.bar(["A", "B", "C"], means.to_numpy())
        ax.set_xticks([0, 1, 2])
        ax.set_xticklabels(["A", "B", "D"])
        fig.canvas.draw()
        result = fs.check_figure(fig, frame,
                                 {"type": "bar", "x": "group", "y": "score"})
        self.assertFalse(result["ok"])
        details = " ".join(check["detail"] for check in result["checks"]
                           if not check["ok"])
        self.assertIn("D", details)


class ScatterCheckTest(FigureCase):
    def test_point_count_equals_non_missing_rows_and_dropped_is_recorded(self):
        frame = scatter_frame()
        complete = frame.dropna(subset=["age", "score"])
        fig, ax = plt.subplots(figsize=(5.0, 4.0), dpi=100)
        ax.scatter(complete["age"], complete["score"])
        fig.canvas.draw()

        result = fs.check_figure(fig, frame,
                                 {"type": "scatter", "x": "age", "y": "score"})
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["dropped"], 3)
        self.assertEqual(result["n"], 5)
        counts = [check for check in result["checks"]
                  if check["check"] == "scatter_count"]
        self.assertEqual(counts[0]["expected"], 5)
        self.assertEqual(counts[0]["observed"], 5)

        # Dropping a drawn point must be visible as a count mismatch.
        collection = ax.collections[0]
        collection.set_offsets(np.asarray(collection.get_offsets())[:-1])
        bad = fs.check_figure(fig, frame,
                              {"type": "scatter", "x": "age", "y": "score"})
        self.assertFalse(bad["ok"])
        self.assertTrue(any(check["check"] == "scatter_count"
                            and not check["ok"] for check in bad["checks"]))


class LineCheckTest(FigureCase):
    def test_line_point_order_and_per_group_counts(self):
        frame = pd.DataFrame({
            "wave": [1, 2, 3, 1, 2, 3],
            "score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "arm": ["ctl"] * 3 + ["trt"] * 3,
        })
        fig, ax = plt.subplots(figsize=(5.0, 4.0), dpi=100)
        for arm in ("ctl", "trt"):
            part = frame.loc[frame["arm"] == arm]
            ax.plot(part["wave"], part["score"], marker="o", label=arm)
        ax.legend()
        fig.canvas.draw()
        mapping = {"type": "line", "x": "wave", "y": "score", "series": "arm"}

        result = fs.check_figure(fig, frame, mapping)
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["dropped"], 0)

        # Reverse one series' order in the artist: same points, wrong order.
        ax.lines[0].set_ydata([3.0, 2.0, 1.0])
        bad = fs.check_figure(fig, frame, mapping)
        self.assertFalse(bad["ok"])
        self.assertTrue(any(check["check"] == "line_points"
                            and not check["ok"] for check in bad["checks"]))

    def test_legend_entry_count_must_equal_the_group_count(self):
        frame = pd.DataFrame({
            "wave": [1, 2, 3, 1, 2, 3],
            "score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "arm": ["ctl"] * 3 + ["trt"] * 3,
        })
        fig, ax = plt.subplots(figsize=(5.0, 4.0), dpi=100)
        for arm in ("ctl", "trt"):
            part = frame.loc[frame["arm"] == arm]
            ax.plot(part["wave"], part["score"], label=arm)
        fig.canvas.draw()
        mapping = {"type": "line", "x": "wave", "y": "score", "series": "arm"}
        missing_legend = fs.check_figure(fig, frame, mapping)
        self.assertFalse(missing_legend["ok"])
        self.assertTrue(any(check["check"] == "legend_entries"
                            and not check["ok"]
                            for check in missing_legend["checks"]))

        ax.legend()
        fig.canvas.draw()
        with_legend = fs.check_figure(fig, frame, mapping)
        self.assertTrue(with_legend["ok"], with_legend["checks"])


class LabelGeometryTest(FigureCase):
    def test_dense_labels_overlap_then_rotate_reduces_without_deleting_any(self):
        fig, ax, labels = self.dense_figure()
        baseline = fs.label_geometry(fig)
        self.assertEqual(baseline["n_labels"], 60)
        self.assertGreater(baseline["overlaps"], 0)
        self.assertEqual([label["text"] for label in baseline["labels"]], labels)
        self.assertEqual(baseline["measure"],
                         "renderer window_extent; rotated glyph boxes (SAT)")

        options = fs.layout_options(fig, baseline)
        self.assertTrue(options)
        for option in options:
            self.assertIn(option["option"], fs.LAYOUT_OPTIONS)
            self.assertFalse(option.get("deletes_labels", False))
            self.assertTrue(option.get("supported_by"))
            self.assertEqual(option.get("labels_kept"), 60)
            reason = str(option.get("reason", "")).lower()
            for forbidden in ("delete", "drop", "truncate", "shrink",
                              "smaller font", "remove"):
                self.assertNotIn(forbidden, reason,
                                 f"layout option suggests {forbidden}: {option}")
        rotations = [option for option in options if option["option"] == "rotate"]
        self.assertTrue(rotations)
        self.assertTrue(rotations[0]["reason"])
        self.assertIn("measured", rotations[0]["supported_by"])
        widening = [option for option in options if option["option"] == "widen"]
        self.assertTrue(widening)
        self.assertGreater(widening[0]["needed_width_cm"],
                           widening[0]["current_width_cm"])
        self.assertGreater(widening[0]["needed_width_cm"], 44.0)

        # Asking for options must not mutate the figure.
        after_options = fs.label_geometry(fig)
        self.assertEqual(after_options["overlaps"], baseline["overlaps"])

        self.rotate30(fig, ax)
        rotated = fs.label_geometry(fig)
        self.assertLess(rotated["overlaps"], baseline["overlaps"])
        self.assertEqual(rotated["n_labels"], 60)
        self.assertEqual([label["text"] for label in rotated["labels"]], labels)
        expected = [option for option in rotations if option["angle"] == 30]
        self.assertTrue(expected)
        self.assertEqual(expected[0]["expected_overlaps"],
                         rotated["overlaps"])


class PaletteReportTest(FigureCase):
    def test_single_categorical_sequential_and_diverging_roles_are_reported(self):
        frame = bar_frame()
        single = self.bar_figure(frame, colors="#1C4E7B")[0]
        roles = {(entry["source"], entry["role"])
                 for entry in fs.palette_report(single)["roles"]}
        self.assertIn(("bars", "single"), roles)

        categorical = self.bar_figure(
            frame, colors=["#1C4E7B", "#E18560", "#4B6E52"])[0]
        roles = {(entry["source"], entry["role"])
                 for entry in fs.palette_report(categorical)["roles"]}
        self.assertIn(("bars", "categorical"), roles)

        fig, ax = plt.subplots(figsize=(5.0, 4.0), dpi=100)
        scatter = ax.scatter(range(20), range(20), c=np.arange(20),
                             cmap="viridis")
        roles = {(entry["source"], entry["role"])
                 for entry in fs.palette_report(fig)["roles"]}
        self.assertIn(("collections", "sequential"), roles)
        _ = scatter

        fig2, ax2 = plt.subplots(figsize=(5.0, 4.0), dpi=100)
        ax2.imshow(np.arange(64.0).reshape(8, 8), cmap="RdBu_r")
        roles = {(entry["source"], entry["role"])
                 for entry in fs.palette_report(fig2)["roles"]}
        self.assertIn(("images", "diverging"), roles)

    def test_palette_stays_a_suggestion_and_never_changes_ok(self):
        frame = bar_frame()
        # Close, non-monotonic greys: a taste opinion, not a data error.
        colors = ["#777777", "#808080", "#6E6E6E"]
        fig, _, means, _ = self.bar_figure(frame, colors=colors)
        report = fs.palette_report(fig)
        self.assertFalse(report["mandatory"])
        self.assertTrue(report["suggestions"])
        self.assertTrue(all(item["severity"] == "suggestion"
                            for item in report["suggestions"]))
        self.assertTrue(all(item["mandatory"] is False
                            for item in report["suggestions"]))
        self.assertNotIn("must", json.dumps(report["suggestions"]).lower())

        result = fs.check_figure(fig, frame,
                                 {"type": "bar", "x": "group", "y": "score"})
        self.assertTrue(result["ok"], result["checks"])
        png = os.path.join(self.tmp, "palette.png")
        fig.savefig(png, dpi=150)
        record = fs.record_figure(C.Project(self.tmp), "F-palette", fig,
                                  {"type": "bar", "x": "group", "y": "score",
                                   "error": {"kind": "sd"}},
                                  "data.csv", "c" * 64, result, None, report, png_path=png, dpi=150)
        self.assertEqual(record["status"], "checked")
        _ = means


class RecordAndSavedTest(FigureCase):
    def _recorded_figure(self):
        frame = bar_frame()
        fig, _, _, _ = self.bar_figure(frame, error_scale=1.0)
        png = self.p("fig.png")
        pdf = self.p("fig.pdf")
        fig.savefig(png, dpi=150)
        fig.savefig(pdf)
        mapping = {"type": "bar", "x": "group", "y": "score",
                   "error": {"kind": "sd"}}
        checks = fs.check_figure(fig, frame, mapping)
        project = C.Project(self.tmp)
        record = fs.record_figure(project, "F1", fig, mapping,
                                  "data/analysis.csv", "d" * 64, checks,
                                  fs.label_geometry(fig),
                                  fs.palette_report(fig),
                                  png_path=png, pdf_path=pdf, dpi=150)
        return frame, fig, png, pdf, mapping, record

    def test_record_is_a_valid_v2_figure_spec_in_the_expected_ledger(self):
        _, _, png, pdf, _, record = self._recorded_figure()
        self.assertEqual(record["status"], "checked")
        self.assertEqual(record["revision"], 1)
        C.validate_record(record, strict=True)
        self.assertIn("figure-elements", record["requires_features"])
        self.assertEqual(record["data"]["figure_id"], "F1")
        self.assertEqual(record["data"]["png"], "fig.png")
        self.assertEqual(record["data"]["pdf"], "fig.pdf")
        bars = record["data"]["elements_observed"]["axes"][0]["bars"]
        self.assertEqual(len(bars), 3)
        self.assertTrue(record["data"]["checks"])
        self.assertEqual(
            record["data"]["elements_observed"]["canvas"]["px"], [900, 600])

        path = os.path.join(self.tmp, "output", "v2", "figure_spec.jsonl")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(len(rows), 1)
        C.validate_record(rows[0])
        self.assertEqual(rows[0]["data"]["figure_id"], "F1")
        self.assertEqual(rows[0]["data"]["elements_observed"]["canvas"]["px"],
                         [900, 600])
        _ = png, pdf

    def test_a_failing_check_records_status_failed_as_a_new_revision(self):
        frame, fig, png, pdf, mapping, first = self._recorded_figure()
        self.assertEqual(first["status"], "checked")
        self.bar_containers(fig.axes[0])[0].patches[0].set_height(999.0)
        broken = fs.check_figure(fig, frame, mapping)
        self.assertFalse(broken["ok"])
        revision = fs.record_figure(C.Project(self.tmp), "F1", fig, mapping,
                                    "data/analysis.csv", "d" * 64, broken,
                                    fs.label_geometry(fig),
                                    fs.palette_report(fig),
                                    png_path=png, pdf_path=pdf, dpi=150)
        self.assertEqual(revision["status"], "failed")
        self.assertEqual(revision["revision"], 2)
        C.validate_record(revision)

    def test_check_saved_detects_a_replaced_png_and_reports_bitmap_limits(self):
        _, _, png, pdf, _, _ = self._recorded_figure()
        good = fs.check_saved("F1", png, pdf, root=self.tmp)
        self.assertTrue(good["ok"], good["checks"])
        self.assertFalse(good["fully_verified"])
        self.assertEqual(good["png"]["px"], [900, 600])
        self.assertAlmostEqual(good["png"]["dpi"][0], 150.0, places=0)
        self.assertTrue([item for item in good["unverifiable"]
                         if "element" in item["what"]])

        from PIL import Image
        Image.new("RGB", (320, 240), "white").save(png, dpi=(96, 96))
        bad = fs.check_saved("F1", png, pdf, root=self.tmp)
        self.assertFalse(bad["ok"])
        pixels = [check for check in bad["checks"]
                  if check["check"] == "png_pixels"]
        self.assertTrue(pixels)
        self.assertEqual(pixels[0]["expected"], [900, 600])
        self.assertEqual(pixels[0]["observed"], [320, 240])
        hashes = [check for check in bad["checks"]
                  if check["check"] == "png_sha256"]
        self.assertTrue(hashes and not hashes[0]["ok"])

    def test_check_saved_without_a_pdf_marks_the_pdf_unverifiable(self):
        _, _, png, _, _, _ = self._recorded_figure()
        result = fs.check_saved("F1", png, None, root=self.tmp)
        self.assertTrue(result["ok"], result["checks"])
        self.assertTrue(any(item["what"] == "pdf"
                            for item in result["unverifiable"]))


class CliTest(FigureCase):
    def write_module(self):
        module_path = self.p("figmod.py")
        with open(module_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                "import matplotlib\n"
                "matplotlib.use('Agg')\n"
                "import matplotlib.pyplot as plt\n"
                "def make():\n"
                "    fig, ax = plt.subplots(figsize=(5, 4), dpi=100)\n"
                "    ax.bar(['A', 'B', 'C'], [1.0, 2.0, 3.0])\n"
                "    return fig\n")
        return module_path

    def test_inspect_accepts_a_json_spec(self):
        self.write_module()
        spec_path = self.p("figure_spec.json")
        with open(spec_path, "w", encoding="utf-8") as handle:
            json.dump({"figure": "figmod:make"}, handle)
        inspected = run("figsemantics.py", "--root", self.tmp,
                        "inspect", "--figure", spec_path)
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        report = json.loads(inspected.stdout)
        self.assertEqual(len(report["figure"]["axes"][0]["bars"]), 3)

    def test_inspect_and_check_cli_round_trip(self):
        self.write_module()
        inspected = run("figsemantics.py", "--root", self.tmp,
                        "inspect", "--figure", "figmod:make")
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        report = json.loads(inspected.stdout)
        self.assertEqual(len(report["figure"]["axes"][0]["bars"]), 3)
        self.assertEqual(report["label_geometry"]["n_labels"], 3)
        self.assertIn("mandatory", report["palette"])

        # A recorded figure can be checked from the CLI as well.
        fig = plt.figure(figsize=(5.0, 4.0), dpi=100)
        axis = fig.add_subplot()
        axis.bar(["A", "B", "C"], [1.0, 2.0, 3.0])
        fig.canvas.draw()
        png = self.p("cli.png")
        fig.savefig(png, dpi=150)
        mapping = {"type": "bar", "x": "group", "y": "score"}
        frame = pd.DataFrame({"group": ["A", "B", "C"],
                              "score": [1.0, 2.0, 3.0]})
        checks = fs.check_figure(fig, frame, mapping)
        self.assertTrue(checks["ok"])
        fs.record_figure(C.Project(self.tmp), "CLI1", fig, mapping,
                         "data.csv", "e" * 64, checks, None, None,
                         png_path=png, dpi=150)
        checked = run("figsemantics.py", "--root", self.tmp, "check", "CLI1")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
