# -*- coding: utf-8 -*-
"""compute_kappa.py: double-coding agreement is computed, not asserted.

The coding protocol (references/02-coding-protocol.md) requires double coding
or an independent re-read with Cohen's kappa reported. These tests pin the
math, the artefacts and the exit codes.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, run, write_csv, read_csv

import compute_kappa as ck


class TestKappaMath(unittest.TestCase):
    """The kappa formula itself."""

    def test_known_kappa_value(self):
        # Hand-computed: po = 4/5 = .8. Marginals A: x=3,y=2; B: x=2,y=3.
        # pe = 3/5*2/5 + 2/5*3/5 = .48; kappa = (.8-.48)/(.52).
        pairs = [("x", "x"), ("x", "x"), ("x", "y"), ("y", "y"), ("y", "y")]
        stats = ck.cohen_kappa(pairs)
        self.assertEqual(stats["n_pairs"], 5)
        self.assertEqual(stats["n_agree"], 4)
        self.assertAlmostEqual(stats["agreement_rate"], 0.8)
        self.assertAlmostEqual(stats["cohen_kappa"], (0.8 - 0.48) / 0.52)

    def test_perfect_agreement_is_kappa_one(self):
        stats = ck.cohen_kappa([("a", "a"), ("b", "b")])
        self.assertAlmostEqual(stats["cohen_kappa"], 1.0)

    def test_chance_agreement_is_kappa_zero(self):
        stats = ck.cohen_kappa([("a", "a"), ("a", "b"), ("a", "a")])
        # A is constant (all "a"), B agrees 2/3: kappa = (2/3 - 2/3)/(1/3) = 0.
        self.assertAlmostEqual(stats["cohen_kappa"], 0.0)
        self.assertEqual(stats["note"], "one coder is constant")

    def test_both_constant_is_undefined_not_a_crash(self):
        stats = ck.cohen_kappa([("a", "a"), ("a", "a")])
        self.assertIsNone(stats["cohen_kappa"])
        self.assertIn("undefined", stats["note"])

    def test_empty_is_reported(self):
        stats = ck.cohen_kappa([])
        self.assertEqual(stats["n_pairs"], 0)
        self.assertIsNone(stats["cohen_kappa"])


class TestKappaCLI(TempCase):
    """Artifacts, evidence alignment and exit codes through the CLI."""

    def _coding(self, name, rows):
        path = self.p(name)
        write_csv(path, ["rel_path", "plea", "fine", "plea_src", "fine_src"],
                  [{**row, "plea_src": "kv_block", "fine_src": "quantity"}
                   for row in rows])
        return path

    def _evidence(self, name, records):
        path = self.p(name)
        with open(path, "w", encoding="utf-8") as fh:
            for rel, field, line in records:
                fh.write(json.dumps(
                    {"rel_path": rel, "evidence": [f"{field}={line}"]},
                    ensure_ascii=False) + "\n")
        return path

    def test_report_disagreements_and_sample_md(self):
        a = self._coding("a.csv", [
            {"rel_path": "d1.txt", "plea": "认罪", "fine": "500"},
            {"rel_path": "d2.txt", "plea": "不认罪", "fine": "1000"},
            {"rel_path": "d3.txt", "plea": "认罪", "fine": ""},
            {"rel_path": "d4.txt", "plea": "认罪", "fine": "800"},
        ])
        b = self._coding("b.csv", [
            {"rel_path": "d1.txt", "plea": "认罪", "fine": "500"},
            {"rel_path": "d2.txt", "plea": "认罪", "fine": "1000"},
            {"rel_path": "d3.txt", "plea": "认罪", "fine": ""},
            {"rel_path": "d4.txt", "plea": "认罪", "fine": "900"},
        ])
        ev_a = self._evidence("a.jsonl", [("d2.txt", "plea", "不认罪@10-13")])
        ev_b = self._evidence("b.jsonl", [("d2.txt", "plea", "认罪@10-12")])
        out = self.p("kappa")
        proc = run("compute_kappa.py", "--a", a, "--b", b,
                   "--a-evidence", ev_a, "--b-evidence", ev_b, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = {row["variable"]: row
                  for row in read_csv(os.path.join(out, "kappa_report.csv"))}
        self.assertIn("plea", report)
        self.assertIn("fine", report)
        self.assertNotIn("plea_src", report)      # *_src columns never compared
        self.assertNotIn("doc_type", report)
        self.assertEqual(report["fine"]["n_disagree"], "1")
        self.assertEqual(report["fine"]["n_agree"], "3")
        dis = {row["field"]: row
               for row in read_csv(os.path.join(out, "disagreements.csv"))}
        self.assertEqual(dis["plea"]["doc"], "d2.txt")
        self.assertEqual(dis["plea"]["evidence_a"], "plea=不认罪@10-13")
        self.assertEqual(dis["plea"]["evidence_b"], "plea=认罪@10-12")
        sample = open(os.path.join(out, "coding-sample.md"),
                      encoding="utf-8").read()
        self.assertIn("抽样复核：", sample)
        self.assertIn("kappa_report.csv", sample)

    def test_identical_codings_agree_everywhere(self):
        rows = [{"rel_path": f"d{i}.txt", "plea": "认罪" if i % 2 else "不认罪",
                 "fine": str(i * 100)} for i in range(6)]
        a = self._coding("a.csv", rows)
        b = self._coding("b.csv", rows)
        out = self.p("kappa")
        proc = run("compute_kappa.py", "--a", a, "--b", b, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = {row["variable"]: row
                  for row in read_csv(os.path.join(out, "kappa_report.csv"))}
        self.assertEqual(report["plea"]["n_disagree"], "0")
        self.assertAlmostEqual(float(report["plea"]["cohen_kappa"]), 1.0)
        self.assertEqual(read_csv(os.path.join(out, "disagreements.csv")), [])

    def test_low_kappa_variables_are_named(self):
        # plea agrees 5/6 with a mixed marginal -> kappa well below 1 but the
        # rater B is constant, so kappa is 0 and the variable must be flagged.
        a = self._coding("a.csv", [
            {"rel_path": f"d{i}.txt", "plea": "认罪" if i % 5 else "不认罪",
             "fine": "1"} for i in range(6)])
        b = self._coding("b.csv", [
            {"rel_path": f"d{i}.txt", "plea": "认罪", "fine": "1"}
            for i in range(6)])
        out = self.p("kappa")
        proc = run("compute_kappa.py", "--a", a, "--b", b, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("kappa < 0.6", proc.stdout)
        self.assertIn("plea", proc.stdout)
        sample = open(os.path.join(out, "coding-sample.md"),
                      encoding="utf-8").read()
        self.assertIn("plea", sample)

    def test_no_overlapping_documents_exits_2(self):
        a = self._coding("a.csv", [{"rel_path": "d1.txt", "plea": "认罪",
                                    "fine": "500"}])
        b = self._coding("b.csv", [{"rel_path": "z9.txt", "plea": "认罪",
                                     "fine": "500"}])
        proc = run("compute_kappa.py", "--a", a, "--b", b,
                   "--out", self.p("kappa"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no document appears in both", proc.stderr)

    def test_duplicate_keys_exit_2(self):
        a = self._coding("a.csv", [
            {"rel_path": "d1.txt", "plea": "认罪", "fine": "1"},
            {"rel_path": "d1.txt", "plea": "认罪", "fine": "2"}])
        b = self._coding("b.csv", [{"rel_path": "d1.txt", "plea": "认罪",
                                    "fine": "1"}])
        proc = run("compute_kappa.py", "--a", a, "--b", b,
                   "--out", self.p("kappa"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate", proc.stderr)

    def test_missing_file_exits_2(self):
        proc = run("compute_kappa.py", "--a", self.p("nope.csv"),
                   "--b", self.p("nope2.csv"), "--out", self.p("kappa"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr)

    def test_no_key_column_exits_2(self):
        a = self.p("a.csv")
        write_csv(a, ["plea", "fine"], [["认罪", "1"]])
        b = self.p("b.csv")
        write_csv(b, ["plea", "fine"], [["认罪", "1"]])
        proc = run("compute_kappa.py", "--a", a, "--b", b,
                   "--out", self.p("kappa"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no alignable document key", proc.stderr)

    def test_file_column_and_one_sided_fields(self):
        # Real dataset.csv rows carry ``file`` and coders sometimes fill a
        # variable only one round: identifiers must never be compared as
        # variables, and one-sided variables must be named, not dropped.
        a = self.p("a.csv")
        write_csv(a, ["rel_path", "file", "decision", "note_only_a"],
                  [["d1.txt", "corpus/d1.txt", "yes", "x"],
                   ["d2.txt", "corpus/d2.txt", "no", "y"]])
        b = self.p("b.csv")
        write_csv(b, ["rel_path", "file", "decision"],
                  [["d1.txt", "corpus/d1.txt", "yes"],
                   ["d2.txt", "corpus/d2.txt", "no"]])
        out = self.p("kappa")
        proc = run("compute_kappa.py", "--a", a, "--b", b, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = {row["variable"]: row
                  for row in read_csv(os.path.join(out, "kappa_report.csv"))}
        self.assertIn("decision", report)
        self.assertNotIn("file", report)          # identifier, not a variable
        self.assertNotIn("note_only_a", report)   # one-sided, not compared
        self.assertIn("A-only variables (not compared): note_only_a",
                      proc.stdout)
        sample = open(os.path.join(out, "coding-sample.md"),
                      encoding="utf-8").read()
        self.assertIn("仅 A 编了", sample)
        self.assertIn("note_only_a", sample)


if __name__ == "__main__":
    unittest.main()
