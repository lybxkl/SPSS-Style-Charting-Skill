# -*- coding: utf-8 -*-
"""sample_review.py: seeded, stratified, coverage-accounted sampling for
extraction review (batch 2).

Self-selected samples cannot be audited; these tests pin the protocol:
same seed reproduces the same bytes, the flagged pool is never diluted,
floors and proportional splits behave, an unadjudicated sample never
reads as passed, and a user-declared recode ceiling is enforced.
"""
import json
import os

from _helpers import SCRIPTS, TempCase, run


def draw(review, out, *extra):
    return run("sample_review.py", "draw", "--review", review,
               "--out", out, *extra)


def read_csv(path):
    import csv
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def review_row(rel_path, field, value, needs_review="", raw="原文…",
               span="c0:p1", source="profile"):
    return {"rel_path": rel_path, "field": field, "value": value,
            "raw": raw, "source": source, "span": span, "na_hit": "",
            "cross_line": "", "needs_review": needs_review, "flags": "",
            "alternatives": "", "note": ""}


REVIEW_HEADER = ["rel_path", "field", "value", "raw", "source", "span",
                 "na_hit", "cross_line", "needs_review", "flags",
                 "alternatives", "note"]


def write_review(path, rows):
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_HEADER,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_dataset(path, rows):
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rel_path", "file",
                                                    "doc_type"])
        writer.writeheader()
        writer.writerows(rows)


class DrawCase(TempCase):
    def make_review(self, n_flagged=2, n_clean=6):
        rows = []
        for index in range(n_clean):
            rows.append(review_row(f"docs/a{index}.txt", "score",
                                   f"4.{index % 10}"))
        for index in range(n_flagged):
            rows.append(review_row(f"docs/b{index}.txt", "city", "北京",
                                    needs_review="cross_line"))
        review = self.p("extraction_review.csv")
        write_review(review, rows)
        dataset = self.p("dataset.csv")
        write_dataset(dataset, [
            {"rel_path": f"docs/a{index}.txt", "file": f"a{index}.txt",
             "doc_type": "问卷"} for index in range(n_clean)
        ] + [
            {"rel_path": f"docs/b{index}.txt", "file": f"b{index}.txt",
             "doc_type": "访谈"} for index in range(n_flagged)
        ])
        return review, dataset, rows


class TestDraw(DrawCase):
    def test_same_seed_reproduces_the_same_sample_bytes(self):
        review, dataset, _rows = self.make_review()
        first = self.p("r1")
        second = self.p("r2")
        proc = draw(review, first, "--dataset", dataset, "--seed",
                    "20261118", "--rate", "0.5")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(draw(review, second, "--dataset", dataset,
                              "--seed", "20261118", "--rate",
                              "0.5").returncode, 0)
        with open(os.path.join(first, "sample.csv"), "rb") as handle:
            a = handle.read()
        with open(os.path.join(second, "sample.csv"), "rb") as handle:
            b = handle.read()
        self.assertEqual(a, b)
        # and the protocol anchors the sample it produced: two strata
        # here because doc_type happens to align with the flag split
        protocol = read_json(os.path.join(first, "protocol.json"))
        self.assertEqual(protocol["seed"], "20261118")
        self.assertEqual(protocol["total"]["n_sample"], 4)
        self.assertEqual(len(protocol["strata"]), 2)

    def test_flagged_pool_is_a_mandatory_dimension(self):
        review, _dataset, rows = self.make_review()
        out = self.p("r")
        proc = draw(review, out, "--seed", "s", "--rate", "0.5")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sample = read_csv(os.path.join(out, "sample.csv"))
        strata = {row["stratum"] for row in sample}
        self.assertTrue(all("flagged=" in key for key in strata),
                        strata)
        flagged_total = sum(1 for row in rows
                            if row["needs_review"])
        self.assertEqual(flagged_total, 2)

    def test_min_per_stratum_puts_a_floor_on_every_stratum(self):
        review, dataset, _rows = self.make_review()
        out = self.p("r")
        proc = draw(review, out, "--dataset", dataset, "--seed", "s",
                    "--rate", "0.01", "--min-per-stratum", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        protocol = read_json(os.path.join(out, "protocol.json"))
        for stratum in protocol["strata"]:
            self.assertGreaterEqual(stratum["n_sample"], 1, stratum)
        # tiny rate + floor still caps at population size
        self.assertLessEqual(protocol["total"]["n_sample"],
                             protocol["total"]["n_population"])

    def test_fixed_n_splits_proportionally_and_sums_to_n(self):
        review, dataset, _rows = self.make_review(n_clean=8,
                                                  n_flagged=2)
        out = self.p("r")
        proc = draw(review, out, "--dataset", dataset, "--seed", "s",
                    "--n", "5", "--min-per-stratum", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        protocol = read_json(os.path.join(out, "protocol.json"))
        drawn = protocol["total"]["n_sample"]
        self.assertEqual(drawn, 5)
        for stratum in protocol["strata"]:
            self.assertGreaterEqual(stratum["n_sample"], 1)
            self.assertLessEqual(stratum["n_sample"],
                                 stratum["n_population"])

    def test_floor_survives_the_whole_allocation(self):
        # F1 regression: 17 rows / strata 3-7-7, --n 9 --min 3 must give
        # every stratum at least 3 (the old trim loop shaved one stratum
        # to 2 while the total still summed to 9)
        import csv
        review = self.p("extraction_review.csv")
        rows = []
        for doc_type, count in (("A", 3), ("B", 7), ("C", 7)):
            for index in range(count):
                rows.append(review_row(f"docs/{doc_type}{index}.txt",
                                        "score", "1"))
        write_review(review, rows)
        dataset = self.p("dataset.csv")
        with open(dataset, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle,
                                    fieldnames=["rel_path", "file",
                                                "doc_type"])
            writer.writeheader()
            for doc_type, count in (("A", 3), ("B", 7), ("C", 7)):
                for index in range(count):
                    writer.writerow(
                        {"rel_path": f"docs/{doc_type}{index}.txt",
                         "file": f"{doc_type}{index}.txt",
                         "doc_type": doc_type})
        out = self.p("r")
        proc = draw(review, out, "--dataset", dataset, "--seed", "s",
                    "--n", "9", "--min-per-stratum", "3")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        protocol = read_json(os.path.join(out, "protocol.json"))
        self.assertEqual(protocol["total"]["n_sample"], 9)
        by_key = {s["key"].split("|")[0]: s["n_sample"]
                  for s in protocol["strata"]}
        for key, n in by_key.items():
            self.assertGreaterEqual(n, 3,
                                    f"floor broken on {key}: {by_key}")
        # strata that got exactly the floor keep it; the remainder goes
        # to the larger strata proportionally
        self.assertEqual(sum(by_key.values()), 9)

    def test_n_smaller_than_capped_floor_budget_is_refused(self):
        # floors capped at stratum sizes: strata (1, 5), --n 3, min 2 ->
        # capped floors are 1+2=3 which fits, so this must pass now
        import csv
        review = self.p("extraction_review.csv")
        rows = [review_row("docs/a0.txt", "score", "1"),
                review_row("docs/b0.txt", "score", "2"),
                review_row("docs/b1.txt", "score", "3"),
                review_row("docs/b2.txt", "score", "4"),
                review_row("docs/b3.txt", "score", "5"),
                review_row("docs/b4.txt", "score", "6")]
        write_review(review, rows)
        dataset = self.p("dataset.csv")
        with open(dataset, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle,
                                    fieldnames=["rel_path", "file",
                                                "doc_type"])
            writer.writeheader()
            for rel in ("a0", "b0", "b1", "b2", "b3", "b4"):
                writer.writerow({"rel_path": f"docs/{rel}.txt",
                                 "file": f"{rel}.txt",
                                 "doc_type": "A" if rel[0] == "a" else "B"})
        out = self.p("r")
        proc = draw(review, out, "--dataset", dataset, "--seed", "s",
                    "--n", "3", "--min-per-stratum", "2")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        protocol = read_json(os.path.join(out, "protocol.json"))
        self.assertEqual(protocol["total"]["n_sample"], 3)
        # the single-row stratum cannot take more than its population
        by_key = {s["key"].split("|")[0]: s["n_sample"]
                  for s in protocol["strata"]}
        self.assertEqual(by_key["doc_type=A"], 1)

    def test_floor_budget_impossible_after_capping_is_refused(self):
        # floors capped at populations still exceed --n: 2+2=4 > 3
        import csv
        review = self.p("extraction_review.csv")
        rows = [review_row(f"docs/a{index}.txt", "score", "1")
                for index in range(2)] + \
               [review_row(f"docs/b{index}.txt", "score", "2")
                for index in range(2)] + \
               [review_row(f"docs/c{index}.txt", "score", "3")
                for index in range(5)]
        write_review(review, rows)
        dataset = self.p("dataset.csv")
        with open(dataset, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle,
                                    fieldnames=["rel_path", "file",
                                                "doc_type"])
            writer.writeheader()
            for rel in ("a0", "a1", "b0", "b1", "c0", "c1", "c2", "c3",
                        "c4"):
                writer.writerow({"rel_path": f"docs/{rel}.txt",
                                 "file": f"{rel}.txt",
                                 "doc_type": rel[0].upper()})
        proc = draw(review, self.p("r"), "--dataset", dataset,
                    "--seed", "s", "--n", "3", "--min-per-stratum", "2")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot honor --min-per-stratum", proc.stderr)

    def test_rate_and_n_are_mutually_exclusive(self):
        review, _dataset, _rows = self.make_review()
        proc = draw(review, self.p("r"), "--seed", "s", "--rate", "0.2",
                    "--n", "3")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not both", proc.stderr)

    def test_empty_population_is_refused(self):
        review = self.p("extraction_review.csv")
        write_review(review, [])
        proc = draw(review, self.p("r"), "--seed", "s", "--rate", "0.5")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("zero rows", proc.stderr)

    def test_review_without_review_columns_is_refused(self):
        import csv
        path = self.p("not_review.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["a", "b"])
            writer.writeheader()
            writer.writerow({"a": "1", "b": "2"})
        proc = draw(path, self.p("r"), "--seed", "s")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing columns", proc.stderr)

    def test_dataset_without_strata_column_is_refused(self):
        review, _dataset, _rows = self.make_review()
        import csv
        dataset = self.p("ds.csv")
        with open(dataset, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["rel_path", "file"])
            writer.writeheader()
            writer.writerow({"rel_path": "docs/a0.txt", "file": "a0.txt"})
        proc = draw(review, self.p("r"), "--dataset", dataset,
                    "--strata", "doc_type", "--seed", "s")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot stratify", proc.stderr)

    def test_out_pointing_at_a_file_is_refused(self):
        review, _dataset, _rows = self.make_review()
        blocker = self.p("blocker")
        open(blocker, "w").close()
        proc = draw(review, blocker, "--seed", "s")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a directory", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_verdict_columns_are_prepared_for_adjudication(self):
        review, _dataset, _rows = self.make_review(n_flagged=1,
                                                   n_clean=1)
        out = self.p("r")
        proc = draw(review, out, "--seed", "s", "--rate", "1.0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sample = read_csv(os.path.join(out, "sample.csv"))
        self.assertEqual(len(sample), 2)
        for row in sample:
            self.assertEqual(row["verdict"], "")
            self.assertEqual(row["corrected_value"], "")
            self.assertTrue(row["sample_id"].startswith("sp_"))
            self.assertTrue(row["span"])          # jump anchor survives


class TestTally(DrawCase):
    def filled_sample(self, verdicts):
        review, _dataset, _rows = self.make_review(n_clean=2,
                                                   n_flagged=1)
        out = self.p("r")
        self.assertEqual(draw(review, out, "--seed", "s", "--rate",
                              "1.0").returncode, 0)
        sample_path = os.path.join(out, "sample.csv")
        sample = read_csv(sample_path)
        self.assertEqual(len(sample), len(verdicts))
        import csv
        with open(sample_path, "w", encoding="utf-8-sig",
                  newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(sample[0]))
            writer.writeheader()
            for row, verdict in zip(sample, verdicts):
                row["verdict"] = verdict
                if verdict == "改判":
                    row["corrected_value"] = "上海"
                    row["reviewer_note"] = "原文写的是上海"
                writer.writerow(row)
        return sample_path

    def test_tally_counts_verdicts_and_lists_disagreements(self):
        sample = self.filled_sample(["保持", "保持", "改判"])
        out = self.p("tally.json")
        proc = run("sample_review.py", "tally", "--sample", sample,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tally = read_json(out)
        self.assertEqual(tally["overall"]["n_sample"], 3)
        self.assertEqual(tally["overall"]["agree"], 2)
        self.assertEqual(tally["overall"]["recode"], 1)
        self.assertEqual(tally["overall"]["recode_rate"], round(1 / 3, 4))
        self.assertEqual(len(tally["disagreements"]), 1)
        self.assertEqual(tally["disagreements"][0]["corrected_value"],
                         "上海")

    def test_partially_adjudicated_sample_is_not_a_completed_review(self):
        sample = self.filled_sample(["保持", "", "改判"])
        proc = run("sample_review.py", "tally", "--sample", sample,
                   "--out", self.p("tally.json"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no verdict", proc.stderr)

    def test_unknown_verdict_spelling_is_refused(self):
        sample = self.filled_sample(["保持", "对", "改判"])
        proc = run("sample_review.py", "tally", "--sample", sample,
                   "--out", self.p("tally.json"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown verdict", proc.stderr)

    def test_fail_above_is_enforced_when_declared(self):
        sample = self.filled_sample(["保持", "改判", "改判"])
        proc = run("sample_review.py", "tally", "--sample", sample,
                   "--fail-above", "0.10")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("exceeds --fail-above", proc.stderr)
        # the same sample passes under a ceiling the user declared higher
        ok = run("sample_review.py", "tally", "--sample", sample,
                 "--fail-above", "0.80")
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_recode_without_corrected_value_is_not_a_completed_review(self):
        # the protocol's hardest rule: a recode must state what the value
        # becomes. An uncorrected recode used to pass silently - now it
        # exits 2 like an unfilled verdict
        sample = self.filled_sample(["保持", "保持", "改判"])
        # blank out the corrected_value the helper wrote
        import csv
        rows = read_csv(sample)
        for row in rows:
            if row["verdict"] == "改判":
                row["corrected_value"] = ""
        with open(sample, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        proc = run("sample_review.py", "tally", "--sample", sample)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("without corrected_value", proc.stderr)

    def test_unverifiable_counts_as_filled_without_recode(self):
        sample = self.filled_sample(["保持", "无法核对", "保持"])
        out = self.p("tally.json")
        proc = run("sample_review.py", "tally", "--sample", sample,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tally = read_json(out)
        self.assertEqual(tally["overall"]["filled"], 3)
        self.assertEqual(tally["overall"]["unverifiable"], 1)
        self.assertEqual(tally["overall"]["recode_rate"], 0)

    def test_n_smaller_than_floor_budget_is_refused(self):
        # floors after population capping (2+2=4) exceed --n 1... actually
        # with --n 1 nothing fits at all; use the impossible case where
        # capped floors exceed the budget
        review, _dataset, _rows = self.make_review(n_clean=6,
                                                   n_flagged=2)
        proc = draw(review, self.p("r"), "--seed", "s", "--n", "1",
                    "--min-per-stratum", "2")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot honor --min-per-stratum", proc.stderr)

    def test_flag_detection_is_case_insensitive(self):
        # make_coding_sheet writes Yes/TRUE-style spellings; the flag
        # dimension must not depend on the casing
        rows = [review_row("docs/a0.txt", "score", "4.1",
                            needs_review="True"),
                review_row("docs/a1.txt", "score", "4.2",
                            needs_review="YES")]
        review = self.p("extraction_review.csv")
        write_review(review, rows)
        out = self.p("r")
        proc = draw(review, out, "--seed", "s", "--rate", "1.0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        protocol = read_json(os.path.join(out, "protocol.json"))
        flagged = {s["key"] for s in protocol["strata"]
                   if "flagged=yes" in s["key"]}
        self.assertEqual(len(flagged), 1)
        self.assertEqual(protocol["total"]["n_sample"], 2)

    def test_sample_missing_columns_is_refused(self):
        path = self.p("plain.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write("a,b\n1,2\n")
        proc = run("sample_review.py", "tally", "--sample", path)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing column", proc.stderr)
