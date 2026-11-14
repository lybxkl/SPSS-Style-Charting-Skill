# -*- coding: utf-8 -*-
"""v2 checks inside verify_dataset (T13) and design/diagnostic linkage (T20).

Covers A45 (role accounting, repeated measures, leakage), A46 (legal empty table
needs range evidence), A47 (v2 obligations and review events) and the part of
A51 that says two numbers must not be called independent when they share
preprocessing or provenance.
"""
import csv
import json
import os

from _helpers import TempCase, run, write_csv

import contract_v2 as C
import designcheck as DC


def _registry(tmp, dataset_rel="data/person.csv", key="id",
              prov="data/prov.jsonl", review="data/review.jsonl",
              columns=None):
    return {"schema_version": 1, "source_root": "materials",
            "source_inventory": "output/audit/corpus_files.csv",
            "source_coverage": "output/source_coverage.jsonl",
            "datasets": [{"id": "person", "path": dataset_rel, "key": [key],
                          "unit": "一位受访者",
                          "codebook": "data/codebook.md",
                          "provenance": prov, "review": review}]}


class TestVerifyV2(TempCase):
    def _setup(self, rows, kinds, *, review_event=None, empty_evidence=False,
               unit_id=None):
        os.makedirs(self.p("data"), exist_ok=True)
        os.makedirs(self.p("materials"), exist_ok=True)
        src = self.p("materials", "raw.csv")
        write_csv(src, ["id", "score"],
                  [[r[0], r[1]] for r in rows])
        with open(self.p("data", "codebook.md"), "w", encoding="utf-8") as fh:
            fh.write("# codebook\nid: string\nscore: number\n")
        ds = self.p("data", "person.csv")
        write_csv(ds, ["id", "score"], [[r[0], r[1]] for r in rows])
        sha = C.file_sha256(src)
        prov_path = self.p("data", "prov.jsonl")
        with open(prov_path, "w", encoding="utf-8") as fh:
            for i, ((rid, score), kind) in enumerate(zip(rows, kinds), 1):
                for col, value in (("id", rid), ("score", score)):
                    rec = {"key": rid, "column": col, "value": value,
                           "kind": "observed" if col == "id" else kind,
                           "compare": "exact",
                           "sources": [{"path": "materials/raw.csv",
                                        "sha256": sha,
                                        "locator": {"type": "csv", "row": i,
                                                    "column": col},
                                        "raw": value}]}
                    if col == "id":
                        rec["rule"] = {"op": "identity"}
                    if kind != "observed" and col != "id":
                        rec.setdefault("method", "calibrated pixels")
                        rec.setdefault("uncertainty", "+-0.4")
                        rec.setdefault("inputs", [{"path": "materials/raw.csv"}])
                    if unit_id and col == "score":
                        rec["sources"][0]["unit"] = unit_id
                        rec["sources"][0]["reread"] = False
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        open(self.p("data", "review.jsonl"), "w", encoding="utf-8").close()
        with open(self.p("research_registry.json"), "w", encoding="utf-8") as fh:
            json.dump(_registry(self.tmp), fh, ensure_ascii=False)
        proj = C.Project(self.tmp)
        if unit_id:
            payload = {"unit_type": "region", "source": "materials/raw.csv",
                       "source_sha256": sha, "parent_source": "materials/raw.csv",
                       "locator": {"type": "page_region"},
                       "representation": "output/v2/units/rep/x.png",
                       "representation_sha256": "0" * 64,
                       "engine": {"name": "rapidocr", "version": "1.4.4"},
                       "recovered_scope": {"transcript": "3"},
                       "unrecovered": ["OCR transcription is not verified"]}
            unit = C.make_record("source_unit", unit_id, payload,
                                 producer=C.producer_for(
                                     "test", version="1",
                                     module_file=__file__), status="partial")
            proj.append("source_unit", unit, enforce_transition=False)
        else:
            # any v2 ledger entry enables the v2 checks
            payload = {"unit_type": "document", "source": "materials/raw.csv",
                       "source_sha256": sha, "parent_source": "materials/raw.csv",
                       "locator": {"type": "whole_file"},
                       "representation": "output/v2/units/rep/raw.txt",
                       "representation_sha256": "0" * 64,
                       "engine": {"name": "text", "version": "1"},
                       "recovered_scope": {"chars": 10},
                       "unrecovered": []}
            unit = C.make_record("source_unit", "u0", payload,
                                 producer=C.producer_for(
                                     "test", version="1",
                                     module_file=__file__), status="recovered")
            proj.append("source_unit", unit, enforce_transition=False)
        if empty_evidence:
            import audit_view as AV
            AV.record_empty_table(proj, "person", window="2020-01-01..2020-12-31",
                                  denominator="412 cases",
                                  source_rel="materials/raw.csv",
                                  source_sha256=sha, reread_by="agent:reread",
                                  reread_note="read all rows",
                                  columns=["id", "score"])
        if review_event:
            rec = C.make_record("review_event", "re1", review_event,
                                producer=C.producer_for(
                                    "test", version="1", module_file=__file__), status="recorded")
            proj.append("review_event", rec, enforce_transition=False)
        return proj

    def _prepare(self):
        out = self.p("output", "dataset")
        return run("verify_dataset.py", "--registry", "research_registry.json",
                   "--root", self.tmp, "--out", out, "--stage", "prepare")

    def _issues(self):
        path = self.p("output", "dataset", "cell_issues.csv")
        if not os.path.isfile(path):
            return []
        return list(csv.DictReader(open(path, encoding="utf-8-sig")))

    def test_observed_cells_pass_without_v2_noise(self):
        self._setup([("P1", "3"), ("P2", "4")], ["observed", "observed"])
        res = self._prepare()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([i for i in self._issues() if i["check"].startswith("v2_")],
                         [])

    def test_generated_value_without_method_is_an_error(self):
        self._setup([("P1", "3")], ["estimated"])
        # strip the obligations back out
        path = self.p("data", "prov.jsonl")
        lines = []
        for line in open(path, encoding="utf-8"):
            rec = json.loads(line)
            if rec["column"] == "score":
                rec.pop("method", None)
                rec.pop("uncertainty", None)
                rec.pop("inputs", None)
            lines.append(json.dumps(rec, ensure_ascii=False))
        open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        self._prepare()
        checks = [i["check"] for i in self._issues()]
        self.assertIn("v2_obligation", checks)
        detail = [i["detail"] for i in self._issues()
                  if i["check"] == "v2_obligation"][0]
        self.assertIn("method", detail)

    def test_partial_ocr_unit_cannot_back_an_observed_cell(self):
        self._setup([("P1", "3")], ["observed"], unit_id="ocr1")
        self._prepare()
        checks = [i["check"] for i in self._issues()]
        self.assertIn("v2_partial_evidence", checks)

    def test_image_approx_needs_a_reread_of_the_partial_unit(self):
        self._setup([("P1", "3")], ["image_approx"], unit_id="ocr1")
        self._prepare()
        checks = [i["check"] for i in self._issues()]
        self.assertIn("v2_partial_evidence", checks)
        detail = [i["detail"] for i in self._issues()
                  if i["check"] == "v2_partial_evidence"][0]
        self.assertIn("without a recorded re-read", detail)

    def test_empty_table_needs_range_evidence(self):
        self._setup([], [])
        self._prepare()
        self.assertIn("v2_empty_table",
                      [i["check"] for i in self._issues()])

    def test_empty_table_with_evidence_passes(self):
        self._setup([], [], empty_evidence=True)
        res = self._prepare()
        self.assertNotIn("v2_empty_table",
                         [i["check"] for i in self._issues()], res.stdout)

    def test_review_event_without_independence_is_rejected(self):
        self._setup([("P1", "3")], ["observed"], review_event={
            "dataset": "person", "key": ["P1"], "column": "score",
            "value_under_review": "3", "record_sha256": "x" * 8,
            "method": "source_reread", "reviewer": "agent:t",
            "independence": "trust_me", "reread_scope": {"locator": {}},
            "second_pass": {"value": "3", "outcome": "confirmed",
                            "checked_at": "2026-11-14T12:00:00+08:00"},
            "outcome": "confirmed", "checked_at": "2026-11-14T12:00:00+08:00",
            "note": "read the row"})
        from verify_dataset import Verifier, key_tuple, parse_time
        verifier = Verifier("research_registry.json", self.tmp)
        verifier.prepare()
        expected = {(t["dataset"], key_tuple(t["key"]), t["column"]): t
                    for t in verifier.traces}
        verifier.issues.clear()
        verifier.v2_review_bound(expected, parse_time("2026-11-01T00:00:00+00:00"))
        checks = [i["check"] for i in verifier.issues]
        self.assertIn("v2_review_event", checks)
        details = " ".join(i["detail"] for i in verifier.issues)
        self.assertIn("independence", details)

    def test_report_carries_the_v2_section(self):
        self._setup([("P1", "3")], ["estimated"])
        self._prepare()
        report = json.load(open(self.p("output", "dataset",
                                       "dataset_verification.json"),
                                encoding="utf-8"))
        self.assertTrue(report["contract_v2"]["enabled"])
        self.assertGreaterEqual(report["contract_v2"]["cells_checked"], 2)


class TestDesignCheck(TempCase):
    def _csv(self, name, header, rows):
        path = self.p(name)
        write_csv(path, header, rows)
        return path

    def test_clustered_and_repeated_design_requires_diagnostics(self):
        path = self._csv("person.csv", ["id", "class", "score", "w"],
                         [["P1", "C1", "3", "2"], ["P2", "C2", "4", "3"],
                          ["P1", "C1", "5", "2"], ["P2", "C2", "6", "3"]])
        features = DC.infer_design(path, keys=["id"], weight_column="w",
                                   cluster_column="class")
        self.assertTrue(features["clustered"])
        self.assertTrue(features["repeated"])
        self.assertTrue(features["weighted"])
        self.assertEqual(features["max_rows_per_unit"], 2)
        required = {r["check"] for r in DC.required_diagnostics(features)}
        self.assertIn("cluster_count", required)
        self.assertIn("unit_count", required)
        self.assertIn("weighted_vs_unweighted_n", required)

    def test_missing_diagnostics_fail_the_linkage(self):
        path = self._csv("d.csv", ["id", "score"],
                         [["P1", "1"], ["P2", "2"]])
        features = DC.infer_design(path, keys=["id"])
        spec = {"id": "M1", "design_features": features}
        link = DC.linkage(spec, {})
        self.assertFalse(link["ok"])
        self.assertIn("epv_or_power", link["missing"])
        good = DC.linkage(spec, {"diagnostics": {"epv_or_power": "12 events/variable"},
                                 "sample_scope": {"n": 2, "unit": "person"}})
        self.assertTrue(good["ok"], good["missing"])

    def test_leakage_between_train_and_test_is_rejected(self):
        train = self._csv("train.csv", ["id", "x", "y"],
                          [["P1", "1", "2"], ["P2", "2", "4"]])
        test = self._csv("test.csv", ["id", "x", "y"],
                         [["P2", "2", "4"], ["P3", "3", "6"]])
        spec = {"id": "M1",
                "inputs": [{"dataset": str(train), "role": "fit",
                            "keys": ["id"],
                            "sha256": C.file_sha256(train)},
                           {"dataset": str(test), "role": "test",
                            "keys": ["id"],
                            "sha256": C.file_sha256(test)}],
                "n_semantics": {"kind": "observation", "unit": "person"}}
        res = DC.role_accounting(spec)
        self.assertFalse(res["ok"])
        checks = {p["check"] for p in res["problems"]}
        self.assertIn("split_leakage", checks)
        self.assertEqual(res["by_role"]["fit"]["units"], 2)
        self.assertEqual(res["by_role"]["test"]["units"], 2)
        # rows are not summed into an independent N
        self.assertEqual(res["n_by_role_not_summed"], {"fit": 2, "test": 2})

    def test_disjoint_roles_and_repeated_measures_are_distinguished(self):
        train = self._csv("train.csv", ["id", "x", "y"],
                          [["P1", "1", "2"], ["P1", "2", "4"], ["P2", "3", "6"]])
        test = self._csv("test.csv", ["id", "x", "y"], [["P3", "4", "8"]])
        spec = {"id": "M2",
                "inputs": [{"dataset": str(train), "role": "fit",
                            "keys": ["id"], "sha256": C.file_sha256(train)},
                           {"dataset": str(test), "role": "test",
                            "keys": ["id"], "sha256": C.file_sha256(test)}],
                "n_semantics": {"kind": "observation", "unit": "person"}}
        res = DC.role_accounting(spec)
        self.assertTrue(res["ok"], res["problems"])
        self.assertEqual(res["repeated_roles"],
                         [{"role": "fit", "rows": 3, "units": 2}])
        self.assertEqual(res["n_by_role_not_summed"]["fit"], 2)

    def test_record_linkage_writes_a_validation_result(self):
        proj = C.Project(self.tmp)
        path = self._csv("d.csv", ["id", "score"], [["P1", "1"], ["P2", "2"]])
        features = DC.infer_design(path, keys=["id"])
        spec = {"id": "M9", "design_features": features,
                "inputs": [{"dataset": str(path), "role": "fit",
                            "keys": ["id"], "sha256": C.file_sha256(path)}],
                "n_semantics": {"kind": "observation", "unit": "person"}}
        out = DC.record_linkage(proj, spec, result={})
        self.assertEqual(out["status"], "failed")
        rec = proj.latest("validation_result", "design:M9")
        self.assertEqual(rec["data"]["target"]["kind"], "design_linkage")
        self.assertIn("epv_or_power", rec["data"]["observed"]["missing"])
