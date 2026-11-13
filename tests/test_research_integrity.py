# -*- coding: utf-8 -*-
"""Source-cell verification, backfill coverage and arbitrary-engine receipts.

All data/review attestations here are explicitly synthetic test fixtures.
Production review tasks must be performed, never approved by this helper.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _helpers import TempCase, run, write_csv
from verify_dataset import Verifier, load_json, load_jsonl, sha256


class IntegrityCase(TempCase):
    def put(self, name, value):
        path = Path(self.p(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return str(path)

    def json(self, name, value):
        return self.put(name, json.dumps(value, ensure_ascii=False, indent=2))

    def jsonl(self, name, rows):
        return self.put(name, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    def setUp(self):
        super().setUp()
        self.source = write_csv(self.p("raw", "source.csv"), ["id", "x", "y"], [["A", "2", "3"], ["B", "4", "5"]])
        write_csv(self.p("data.csv"), ["id", "x", "y", "total"], [["A", "2", "3", "5"], ["B", "4", "5", "9"]])
        self.put("codebook.md", "Synthetic fixture: x and y are observations; total=x+y.")
        self.records = []
        for row, (key, x, y, total) in enumerate([("A", "2", "3", "5"), ("B", "4", "5", "9")], 1):
            for col, value in [("id", key), ("x", x), ("y", y)]:
                self.records.append({"key": key, "column": col, "value": value, "kind": "observed",
                                     "sources": [{"path": "raw/source.csv", "sha256": sha256(self.source),
                                                  "locator": {"type": "csv", "row": row, "column": col}, "raw": value}]})
            self.records.append({"key": key, "column": "total", "value": total, "kind": "derived",
                                 "rule": {"op": "sum"}, "compare": "numeric",
                                 "inputs": [{"dataset": "people", "key": key, "column": c} for c in ["x", "y"]]})
        self.jsonl("provenance.jsonl", self.records)
        self.registry = {"schema_version": 1, "source_root": "raw", "source_inventory": "inventory.csv",
                         "source_coverage": "coverage.jsonl", "discovery_report": "discovery.md", "model_plan": "models.jsonl",
                         "datasets": [{"id": "people", "path": "data.csv", "key": "id", "unit": "one synthetic person",
                                       "codebook": "codebook.md", "provenance": "provenance.jsonl", "review": "reviews.jsonl"}]}
        self.save_registry()
        write_csv(self.p("inventory.csv"), ["rel_path", "status"], [["source.csv", "valid"]])
        self.jsonl("coverage.jsonl", [{"source": "source.csv", "sha256": sha256(self.source),
                                      "status": "included", "datasets": ["people"], "reason": "Synthetic person records"}])
        self.put("discovery.md", "Synthetic discovery: person table and derived totals; no event times observed.")
        self.model = {"id": "M1", "dataset": "people", "family": "custom mathematical method",
                      "question": "What is the sum?", "reason": "Synthetic deterministic example",
                      "requirements": {"x": "observed numeric values"}, "status": "completed", "n": 2,
                      "receipt": "run.json", "diagnostics": "diagnostics.json", "sample": "sample.csv"}
        self.jsonl("models.jsonl", [self.model])

    def save_registry(self):
        self.json("registry.json", self.registry)

    def check(self, final=False, *extra):
        args = ["--registry", self.p("registry.json"), "--root", self.tmp, "--out", self.p("verify")]
        if final:
            args += ["--stage", "final", "--snapshot", self.p("verify", "verification_snapshot.json")]
        return run("verify_dataset.py", *args, *extra)

    def approve_fixture(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        tasks = load_jsonl(next(Path(self.p("verify")).glob("review_template_*.jsonl")))
        for r in tasks:
            r.update(status="verified", source_reread=True, reviewer="synthetic-test-reviewer",
                     method="source_reread", note="Synthetic fixture; expected cells independently specified in test",
                     checked_at=datetime.now(timezone.utc).isoformat())
        self.jsonl("reviews.jsonl", tasks)
        result = self.check(True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return tasks

    def make_run(self, body=None):
        if not Path(self.p("verify", "dataset_verification.json")).exists():
            self.approve_fixture()
        code = body or ("import csv,json\n"
                        "with open('data.csv',encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))\n"
                        "with open('sample.csv','w',newline='',encoding='utf-8') as f:\n"
                        " w=csv.writer(f);w.writerow(['id']);w.writerows([[r['id']] for r in rows])\n"
                        "with open('diagnostics.json','w') as f: json.dump({'n':len(rows),'design':'synthetic'},f)\n"
                        "with open('summary.json','w') as f: json.dump({'sum':sum(float(r['x']) for r in rows)},f)\n")
        self.put("analysis.py", code)
        return run("run_model.py", "--id", "M1", "--root", self.tmp,
                   "--registry", "registry.json", "--verification", "verify/dataset_verification.json",
                   "--input", "data.csv", "--code", "analysis.py",
                   "--output", "sample.csv", "--output", "diagnostics.json", "--output", "summary.json",
                   "--receipt", self.p("run.json"), "--", sys.executable, "analysis.py")

    def gate(self):
        return run("research_gate.py", "--registry", self.p("registry.json"), "--root", self.tmp,
                   "--verification", self.p("verify", "dataset_verification.json"), "--out", self.p("gate.json"))


class CellVerificationTests(IntegrityCase):
    def test_valid_cells_and_independently_computed_totals(self):
        self.approve_fixture()
        self.assertEqual(load_json(self.p("verify", "dataset_verification.json"))["cell_count"], 8)

    def test_prepare_does_not_generate_approvals(self):
        self.assertEqual(self.check().returncode, 0)
        tasks = load_jsonl(next(Path(self.p("verify")).glob("review_template_*.jsonl")))
        self.assertTrue(all(t["status"] == "pending" and not t["source_reread"] for t in tasks))
        self.assertFalse(Path(self.p("reviews.jsonl")).exists())
        self.assertEqual(self.check(True).returncode, 2)

    def test_dataset_and_ledger_cannot_agree_on_a_fabricated_raw_value(self):
        write_csv(self.p("data.csv"), ["id", "x", "y", "total"], [["A", "999", "3", "1002"], ["B", "4", "5", "9"]])
        self.records[1]["value"] = "999"
        self.records[1]["sources"][0]["raw"] = "999"
        self.records[3]["value"] = "1002"
        self.jsonl("provenance.jsonl", self.records)
        self.assertEqual(self.check().returncode, 2)
        self.assertIn("reopened source", Path(self.p("verify", "cell_issues.csv")).read_text(encoding="utf-8-sig"))

    def test_source_hash_mutation_is_rejected(self):
        Path(self.source).write_text("id,x,y\nA,999,3\nB,4,5\n", encoding="utf-8")
        self.assertEqual(self.check().returncode, 2)

    def test_every_cell_including_identifier_needs_provenance(self):
        self.jsonl("provenance.jsonl", self.records[1:])
        self.assertEqual(self.check().returncode, 2)

    def test_duplicate_cell_provenance_is_rejected(self):
        self.jsonl("provenance.jsonl", self.records + [self.records[0]])
        self.assertEqual(self.check().returncode, 2)

    def test_wrong_derived_total_is_rejected(self):
        write_csv(self.p("data.csv"), ["id", "x", "y", "total"], [["A", "2", "3", "6"], ["B", "4", "5", "9"]])
        self.records[3]["value"] = "6"
        self.jsonl("provenance.jsonl", self.records)
        self.assertEqual(self.check().returncode, 2)

    def test_derived_cycle_is_rejected(self):
        self.records[3]["inputs"] = [{"dataset": "people", "key": "A", "column": "total"}]
        self.jsonl("provenance.jsonl", self.records)
        self.assertEqual(self.check().returncode, 2)

    def test_missing_values_require_context_and_cannot_be_zero(self):
        self.records[1].update(kind="missing", value="", reason="not_reported")
        write_csv(self.p("data.csv"), ["id", "x", "y", "total"], [["A", "", "3", "5"], ["B", "4", "5", "9"]])
        self.jsonl("provenance.jsonl", self.records)
        result = self.check()
        self.assertEqual(result.returncode, 2)  # total cannot reuse a missing x as if it were observed

    def test_broad_tolerance_without_precision_reason_is_rejected(self):
        self.records[3].update(tolerance="100")
        self.jsonl("provenance.jsonl", self.records)
        self.assertEqual(self.check().returncode, 2)

    def test_blanket_review_does_not_cover_other_cells(self):
        tasks = self.approve_fixture()
        self.jsonl("reviews.jsonl", tasks[:1])
        self.assertEqual(self.check(True).returncode, 2)

    def test_old_review_cannot_be_reused_after_data_or_codebook_change(self):
        self.approve_fixture()
        self.put("codebook.md", "Changed interpretation of x")
        self.assertEqual(self.check(True).returncode, 2)
        self.assertEqual(self.check().returncode, 0)
        self.assertEqual(self.check(True).returncode, 2)  # new prepare still needs new per-cell reviews

    def test_rejected_or_prebuild_review_is_not_approved(self):
        tasks = self.approve_fixture()
        tasks[0]["checked_at"] = "2001-01-01T00:00:00+00:00"
        self.jsonl("reviews.jsonl", tasks)
        self.assertEqual(self.check(True).returncode, 2)

    def test_ragged_csv_does_not_silently_discard_data(self):
        self.put("data.csv", "id,x,y,total\nA,2,3,5,EXTRA\n")
        self.assertEqual(self.check().returncode, 2)

    def test_duplicate_json_fields_are_not_silently_overwritten(self):
        self.put("registry.json", '{"datasets": [], "datasets": []}')
        self.assertEqual(self.check().returncode, 2)

    def test_multiple_datasets_and_composite_keys_have_no_shared_unit_limit(self):
        write_csv(self.p("panel.csv"), ["id", "wave", "value"], [["A", "1", "2"], ["A", "2", "3"]])
        records = []
        for key, source_col, value in [(["A", "1"], "x", "2"), (["A", "2"], "y", "3")]:
            for col, v, raw_col in [("id", "A", "id"), ("wave", key[1], "x" if key[1] == "1" else "y"), ("value", value, source_col)]:
                r = {"key": key, "column": col, "value": v, "kind": "observed",
                     "sources": [{"path": "raw/source.csv", "sha256": sha256(self.source),
                                  "locator": {"type": "csv", "row": 1, "column": raw_col}, "raw": "A" if col == "id" else value}]}
                if col == "wave":
                    r["rule"] = {"op": "map", "mapping": {value: key[1]}}
                records.append(r)
        self.jsonl("panel_provenance.jsonl", records)
        self.registry["datasets"].append({"id": "panel", "path": "panel.csv", "key": ["id", "wave"],
                                           "unit": "person-wave", "codebook": "codebook.md",
                                           "provenance": "panel_provenance.jsonl", "review": "panel_reviews.jsonl"})
        self.save_registry()
        self.assertEqual(self.check().returncode, 0)
        self.assertEqual(load_json(self.p("verify", "verification_snapshot.json"))["cells"], 14)

    def test_text_spans_are_reopened_and_crlf_is_normalised(self):
        path = self.put("raw/note.txt", "ID A\nAge 2 years")
        v = Verifier(self.p("registry.json"), self.tmp)
        source = {"path": path, "sha256": sha256(path), "locator": {"type": "text", "start": 9, "end": 10}, "raw": "2"}
        self.assertEqual(v.source(source), "2")
        source["raw"] = "9"
        with self.assertRaises(ValueError):
            v.source(source)

    def test_custom_adapters_are_opt_in_and_hashed(self):
        self.put("adapter.py", "def recompute(rule,values):\n return int(values[0])+int(values[1])\n")
        self.records[3]["rule"] = {"op": "custom", "adapter": "independent"}
        self.jsonl("provenance.jsonl", self.records)
        self.assertEqual(self.check().returncode, 2)
        result = self.check(False, "--adapter", "independent=adapter.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ResearchCoverageTests(IntegrityCase):
    def test_successful_noop_cannot_relabel_old_outputs_as_new_results(self):
        self.approve_fixture()
        self.assertEqual(self.make_run().returncode, 0)
        result = self.make_run("pass\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not regenerated", load_json(self.p("run.json"))["error"])

    def test_model_execution_requires_final_review_before_launch(self):
        self.assertEqual(self.check().returncode, 0)
        self.put("analysis.py", "open('LAUNCHED','w').write('must not launch')\n")
        result = run("run_model.py", "--id", "M1", "--root", self.tmp,
                     "--registry", "registry.json", "--verification", "verify/dataset_verification.json",
                     "--input", "data.csv", "--code", "analysis.py", "--output", "LAUNCHED",
                     "--receipt", self.p("run.json"), "--", sys.executable, "analysis.py")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(Path(self.p("LAUNCHED")).exists())

    def test_any_method_family_can_run_and_pass_with_bound_evidence(self):
        self.approve_fixture()
        self.assertEqual(self.make_run().returncode, 0)
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_material_requires_rediscovery(self):
        self.approve_fixture()
        self.make_run()
        self.put("raw/extra.txt", "New unprocessed source")
        self.assertEqual(self.gate().returncode, 2)

    def test_unaccounted_source_cannot_disappear(self):
        self.approve_fixture()
        self.make_run()
        self.jsonl("coverage.jsonl", [])
        self.assertEqual(self.gate().returncode, 2)

    def test_source_disposition_must_agree_with_actual_cell_evidence(self):
        self.approve_fixture()
        self.make_run()
        self.jsonl("coverage.jsonl", [{"source": "source.csv", "sha256": sha256(self.source),
                                      "status": "excluded", "reason": "Pretend unused"}])
        self.assertEqual(self.gate().returncode, 2)

    def test_missing_data_cannot_be_skipped_without_material_backfill(self):
        self.model.update(status="insufficient_data", assessment="discovery.md")
        self.jsonl("models.jsonl", [self.model])
        self.approve_fixture()
        self.assertEqual(self.gate().returncode, 2)
        self.model["gaps"] = [{"requirement": "observed event time", "conclusion": "Original material does not record time",
                               "searches": [{"source": "source.csv", "sha256": sha256(self.source),
                                             "result": "not_found", "note": "Read all three original columns: id,x,y; no event date"}]}]
        self.jsonl("models.jsonl", [self.model])
        self.assertEqual(self.gate().returncode, 0)

    def test_partial_backfill_or_found_but_unresolved_data_is_rejected(self):
        self.model.update(status="insufficient_data", assessment="discovery.md",
                          gaps=[{"requirement": "event time", "conclusion": "not ready", "searches": []}])
        self.jsonl("models.jsonl", [self.model])
        self.approve_fixture()
        self.assertEqual(self.gate().returncode, 2)
        self.model["gaps"][0]["searches"] = [{"source": "source.csv", "sha256": sha256(self.source),
                                             "result": "found", "note": "Found something"}]
        self.jsonl("models.jsonl", [self.model])
        self.assertEqual(self.gate().returncode, 2)

    def test_old_statistics_are_rejected_after_code_or_output_changes(self):
        self.approve_fixture()
        self.make_run()
        self.put("summary.json", '{"sum":999}')
        self.assertEqual(self.gate().returncode, 2)

    def test_model_n_is_bound_to_actual_sample_keys(self):
        self.approve_fixture()
        self.make_run()
        self.model["n"] = 99
        self.jsonl("models.jsonl", [self.model])
        self.assertEqual(self.gate().returncode, 2)

    def test_modified_review_invalidates_final_report(self):
        tasks = self.approve_fixture()
        self.make_run()
        tasks[0]["status"] = "rejected"
        self.jsonl("reviews.jsonl", tasks)
        self.assertEqual(self.gate().returncode, 2)

    def test_engine_failure_or_mutated_inputs_is_never_completed(self):
        result = self.make_run("raise RuntimeError('synthetic failure')\n")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(load_json(self.p("run.json"))["status"], "error")
        result = self.make_run("open('data.csv','w').write('changed')\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("changed a declared input", load_json(self.p("run.json"))["error"])

    def test_receipt_cannot_overwrite_input_data(self):
        self.approve_fixture()
        before = Path(self.p("data.csv")).read_bytes()
        self.put("noop.py", "pass\n")
        result = run("run_model.py", "--id", "M1", "--root", self.tmp,
                     "--registry", "registry.json", "--verification", "verify/dataset_verification.json",
                     "--input", "data.csv", "--code", "noop.py",
                     "--output", "out.txt", "--receipt", self.p("data.csv"), "--", sys.executable, "noop.py")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(Path(self.p("data.csv")).read_bytes(), before)

    def test_excluded_zero_byte_material_is_accounted_without_entering_data(self):
        self.put("raw/empty.txt", "")
        write_csv(self.p("inventory.csv"), ["rel_path", "status"], [["source.csv", "valid"], ["empty.txt", "zero_byte"]])
        coverage = load_jsonl(self.p("coverage.jsonl"))
        coverage.append({"source": "empty.txt", "sha256": sha256(self.p("raw/empty.txt")),
                         "status": "excluded", "reason": "Zero-byte synthetic fixture has no observations"})
        self.jsonl("coverage.jsonl", coverage)
        self.approve_fixture()
        self.make_run()
        self.assertEqual(self.gate().returncode, 0)


class OpenCoverageTests(TempCase):
    def test_pairwise_scatter_does_not_drop_rows_because_a_third_variable_is_missing(self):
        import pandas as pd
        import matplotlib.pyplot as plt
        import auto_chart_pack as charts
        df = pd.DataFrame({"x": range(12), "y": [1, 2, 3, 4, 5, 6] + [None]*6,
                           "z": [None]*6 + [2, 4, 6, 8, 10, 12]})
        pack = charts.ChartPack(df, self.tmp, {}, [], 8, 2)
        saved = []
        def save(fig, slug, section, question, chart_type, variables, n, caption, **kwargs):
            saved.append((slug, n, caption))
            plt.close(fig)
        pack.save = save
        pack.correlations(["x", "y", "z"], [])
        scatter = [r for r in saved if r[0].startswith("scatter_")]
        self.assertEqual(len(scatter), 2)
        self.assertEqual([r[1] for r in scatter], [6, 6])
        heat = next(r for r in saved if r[0] == "correlation_heatmap")
        self.assertEqual(heat[1], 12)
        self.assertIn("全列完整案例 0", heat[2])

    def test_pca_defaults_to_real_complete_cases_without_imputation_or_clipping(self):
        import numpy as np
        import pandas as pd
        import matplotlib.pyplot as plt
        from unittest.mock import patch
        import auto_chart_pack as charts
        df = pd.DataFrame({"x": [1, 2, 3, 4, 5, 1000], "y": [3, 8, None, 1, 6, 7],
                           "z": [5, 3, 9, 2, 7, 4]})
        original = df.copy(deep=True)
        pack = charts.ChartPack(df, self.tmp, {}, [], 8, 2)
        saved = []
        def save(fig, slug, section, question, chart_type, variables, n, caption, **kwargs):
            saved.append((n, caption))
            plt.close(fig)
        pack.save = save
        svd = np.linalg.svd
        with patch("auto_chart_pack.np.linalg.svd", wraps=svd) as captured:
            pack.pca(["x", "y", "z"], None)
        complete = df.dropna()
        expected = ((complete - complete.mean()) / complete.std()).values
        np.testing.assert_allclose(captured.call_args.args[0], expected)
        self.assertEqual([r[0] for r in saved], [5, 5, 5])
        self.assertTrue(all("未插补" in r[1] for r in saved))
        pd.testing.assert_frame_equal(df, original)

    def test_review_packet_includes_all_dataset_model_coverage_report(self):
        Path(self.p("gate.json")).write_text(json.dumps({"status": "verified", "error_count": 0,
                                                         "source_count": 7, "dataset_count": 4, "model_count": 23}), encoding="utf-8")
        result = run("review_pack.py", "--research-gate", self.p("gate.json"), "--out", self.p("review.md"))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = load_json(self.p("review.json"))
        self.assertEqual(payload["research"]["dataset_count"], 4)
        self.assertEqual(payload["research"]["model_count"], 23)

    def test_all_pairwise_correlations_include_columns_after_the_old_fourteen_cap(self):
        import numpy as np
        import pandas as pd
        from auto_stats import correlations
        names = [f"x{i}" for i in range(16)]
        df = pd.DataFrame(np.random.default_rng(7).normal(size=(80, 16)), columns=names)
        result = correlations(df, names, [])
        self.assertEqual(len(result), 120)
        self.assertTrue(((result["var1"] == "x14") & (result["var2"] == "x15")).any())

    def test_univariate_default_includes_variables_after_old_sixty_cap(self):
        import numpy as np
        import pandas as pd
        from auto_stats import univariate_models
        names = [f"x{i}" for i in range(62)]
        df = pd.DataFrame(np.random.default_rng(17).normal(size=(100, 63)), columns=["y", *names])
        result, skipped = univariate_models(df, "y", names, [], "continuous")
        self.assertEqual(len(result), 62)
        self.assertIn("x61", result["predictor"].tolist())
        limited, skip = univariate_models(df, "y", names, [], "continuous", max_predictors=2)
        self.assertEqual(len(limited), 2)
        self.assertEqual(len(skip), 60)

    def test_full_table_fingerprint_detects_swaps_and_nonkey_column_edits(self):
        import pandas as pd
        from auto_chart_pack import data_fingerprint
        df = pd.DataFrame({"id": ["A", "B"], "x": [1, 2], "y": [3, 4]})
        old = data_fingerprint(df, ["id"])
        changed = df.copy()
        changed["x"] = [2, 1]  # same n, same sum, different observations
        self.assertNotEqual(old, data_fingerprint(changed, ["id"]))
        self.assertNotEqual(old, data_fingerprint(df.iloc[::-1], ["id"]))

    def test_model_spec_zero_limit_can_fit_more_than_twenty_models(self):
        import numpy as np
        rng = np.random.default_rng(3)
        rows = [[str(i), float(x), float(2*x+e)] for i, (x, e) in enumerate(zip(rng.normal(size=35), rng.normal(size=35)))]
        write_csv(self.p("data.csv"), ["id", "x", "y"], rows)
        spec = {"models": [{"id": f"M{i}", "type": "ols", "outcome": "y", "predictors": ["x"]} for i in range(21)]}
        Path(self.p("spec.json")).write_text(json.dumps(spec), encoding="utf-8")
        result = run("auto_stats.py", "--data", self.p("data.csv"), "--spec", self.p("spec.json"),
                     "--out", self.p("models"), "--max-models", 0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(self.p("models", "coef_M20.csv")).is_file())
