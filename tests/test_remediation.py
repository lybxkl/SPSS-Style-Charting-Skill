"""Regressions for audit F01-F20, with positive producer/consumer chains.

Expected behavior is derived from the pre-fix independent audit, not the old
implementation's return values. Fixtures are synthetic and reread originals.
"""
import csv
import json
import os
from pathlib import Path
import sys
import threading
import time

from _helpers import TempCase, PYTHON
from _research_fixture import known_project, final_review, csv_write
from test_models_entities import make_linear_data, spec_for
import claims as CL
import contract_v2 as C
import designcheck as DC
import gaps as G
import manuscript as MS
import models as M
import ocr_provider as OCR
import release as R
import review_workbench as WB
import search_index as SI
import source_units as SU
import txn as T
import validation as V


class AuditFixes(TempCase):
    def project(self):
        return C.Project(self.tmp)

    def indexed(self, texts=None):
        p = self.project()
        materials = Path(self.tmp) / "materials"
        materials.mkdir(exist_ok=True)
        for name, text in (texts or {"a.txt": "alpha 7", "b.txt": "secret_value 42"}).items():
            (materials / name).write_text(text, encoding="utf-8")
        units = SU.SourceUnits(p, root=self.tmp)
        units.build(materials)
        index = SI.SearchIndex(p, units)
        index.build(materials)
        inventory = [{"source": path.name, "sha256": C.file_sha256(path)} for path in materials.iterdir()]
        return p, index, inventory

    def math(self, family, parameters):
        p = self.project()
        path = Path(self.tmp) / "problem.json"
        path.write_text(json.dumps(parameters), encoding="utf-8")
        M.register(p, {"id": "OPT", "family": family, "purpose": "known-answer synthetic problem",
                       "inputs": [{"role": "constraints", "dataset": "problem.json", "sha256": C.file_sha256(path), "keys": ["constraint"]}],
                       "n_semantics": {"kind": "none"}, "dimensions": 1, "constraints": ["declared bounds and matrices"],
                       "parameters": parameters,
                       "result": {"type": "optimum", "target_parameter": "objective", "unit": "u", "scale": "linear"}})
        out = M.solve(p, "OPT")
        return p, out, p.latest("model_result", "OPT")["data"]["payload"]

    def test_c01_fake_verification_does_not_release(self):
        p = self.project()
        (Path(self.tmp) / "fake.json").write_text(json.dumps({"status": "verified", "error_count": 0, "datasets": {"ghost": {"status": "verified"}}}))
        self.assertNotEqual(R.evaluate(p, {"datasets": ["ghost"], "verification": "fake.json"})["status"], "complete")

    def test_c02_model_without_source_or_method_review_does_not_release(self):
        p = self.project()
        make_linear_data(self.tmp)
        M.register(p, spec_for(self.tmp))
        M.fit(p, "M1")
        V.independent_ols(p, "M1")
        self.assertNotEqual(R.evaluate(p, {"models": ["M1"]})["status"], "complete")

    def test_c03_tampered_ledger_is_rejected_by_normal_reads(self):
        p = self.project()
        rec = CL.register_claim(p, claim_type="material_fact", text="synthetic draft", block_id="B", section="results", support=[])
        path = p.ledger_path("claim")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["status"] = "supported"
        path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
        with self.assertRaises(C.IntegrityError):
            p.latest("claim", rec["id"])
        self.assertEqual(R.evaluate(p, {"claims": [rec["id"]]})["status"], "failed")

    def test_c04_milp_integer_domain_is_honored(self):
        p, out, result = self.math("milp", {"c": [1], "A_ub": [[-1]], "b_ub": [-0.5], "bounds": [[0, 5]], "integrality": [1]})
        self.assertEqual(out["status"], "certified_global", out)
        self.assertAlmostEqual(result["solution"][0], 1)
        self.assertAlmostEqual(result["estimate"], 1)
        self.assertLessEqual(result["certificate"]["integrality_error"], 1e-7)

    def test_c05_nonlinear_bounds_and_unsupported_methods(self):
        target = Path(self.tmp) / "objective.py"
        target.write_text("def objective(x):\n    return float(x[0]**2)\n", encoding="utf-8")
        _, out, result = self.math("nonlinear", {"objective": str(target) + ":objective", "dimensions": 1, "x0": [2], "bounds": [[2, None]]})
        self.assertEqual(out["status"], "local_optimum", out)
        self.assertAlmostEqual(result["solution"][0], 2, places=6)
        self.assertAlmostEqual(result["estimate"], 4, places=6)
        rejected = M._solve_core({"kind": "nonlinear", "objective": str(target) + ":objective", "x0": [2], "bounds": [[2, None]], "method": "BFGS"})
        self.assertEqual(rejected["quality"], "error")

    def test_c06_open_family_and_role_are_registerable(self):
        make_linear_data(self.tmp)
        spec = spec_for(self.tmp, family="user_defined_survival")
        spec["inputs"].append({**spec["inputs"][0], "role": "user_defined_baseline"})
        self.assertEqual(M.register(self.project(), spec)["data"]["family"], "user_defined_survival")

    def test_c07_python_runner_is_invoked_and_result_bound(self):
        make_linear_data(self.tmp)
        p = self.project()
        M.register(p, spec_for(self.tmp, family="user_linear"))
        called = []
        def runner(project, spec):
            called.append(True)
            with open(Path(self.tmp) / "data/linear.csv", encoding="utf-8") as stream:
                n = sum(1 for _ in csv.DictReader(stream))
            return {"type": "scalar", "target_parameter": "x", "unit": "score points", "scale": "linear", "estimate": 3.0, "n": n}
        out = M.fit(p, "M1", runner=runner)
        self.assertEqual(out["status"], "estimated", out)
        self.assertEqual(called, [True])
        self.assertTrue(M.current_result(p, p.latest("model_result", "M1")))

    def test_c08_workbench_events_are_consumed_by_final(self):
        p = known_project(self.tmp, n=6, fit=False)
        verifier, _ = __import__("evidence").final_review(p)
        self.assertEqual(len(verifier.cells), 18)
        registry = json.loads((p.root / "research_registry.json").read_text())
        self.assertTrue(WB.review_gate(p, registry["datasets"][0])["claim_complete"])

    def test_c09_staging_rejects_escape_without_writing(self):
        p = self.project()
        original = Path(self.tmp) / "materials/raw.txt"
        original.parent.mkdir()
        original.write_text("ORIGINAL")
        tx = T.Transaction(p)
        for target in (str(original), "../../raw.txt", "C:/other/raw.txt", "a/../raw.txt"):
            with self.assertRaises(T.TxnError):
                tx.stage(target, "WRONG")
        self.assertEqual(original.read_text(), "ORIGINAL")

    def test_c10_code_drift_blocks_commit(self):
        p = self.project()
        code = Path(self.tmp) / "analysis.py"
        code.write_text("old")
        tx = T.Transaction(p)
        tx.bind_code([code])
        tx.stage("out.txt", "result")
        code.write_text("changed")
        with self.assertRaises(T.InputChanged):
            tx.commit()
        self.assertIsNone(T.read_pointer(p))

    def test_c11_live_long_lock_cannot_be_stolen_or_released_by_other_owner(self):
        p = self.project()
        first = T.Lock(p, "live", timeout=0).acquire()
        try:
            meta = json.loads(first.path.read_text())
            meta["at"] = time.time()-7200
            first.path.write_text(json.dumps(meta))
            with self.assertRaises(T.LockError):
                T.Lock(p, "live", timeout=0).acquire()
            first.token = "wrong-owner"
            first.release()
            self.assertTrue(first.path.exists())
        finally:
            if first.path.exists():
                first.path.unlink()

    def test_c12_filtered_search_covers_only_scanned_sources(self):
        p, index, inventory = self.indexed()
        run = index.search("secret_value", sources=["a.txt"])
        self.assertEqual(run["hits"], 0)
        self.assertFalse(SI.searches_cover(p, [run["run"]], inventory)["complete"])
        self.assertTrue(SI.searches_cover(p, [index.search("secret_value")["run"]], inventory)["complete"])

    def test_c13_zero_hits_or_nonexistent_dataset_cannot_close_gap(self):
        p, index, _ = self.indexed()
        gap = G.open_gap(p, target="dataset:D", requirement="absent", status_detail="needs search")
        run = index.search("ABSENT")
        with self.assertRaises(ValueError):
            G.attach_search(p, gap["id"], run["run"], conclusion="found", note="incorrect declaration")
        found = index.search("alpha")
        G.attach_search(p, gap["id"], found["run"], conclusion="found", note="a.txt has alpha 7")
        with self.assertRaises(ValueError):
            G.resolve(p, gap["id"], dataset="does-not-exist", cells=[{"key": "K", "column": "x", "value": 7}], resolution="incorrect declaration")

    def test_c14_open_gap_is_a_failed_release_check(self):
        p = self.project()
        G.open_gap(p, target="dataset:D", requirement="required count", status_detail="not searched")
        result = R.evaluate(p, {})
        self.assertFalse(next(c for c in result["checks"] if c["check"] == "gaps_closed")["ok"])

    def test_c15_nonexistent_numeric_trace_is_rejected(self):
        p = self.project()
        CL.register_block(p, block_id="B", section="用户自定章节", text="estimate={beta}", claims=[])
        with self.assertRaises(MS.ManuscriptError):
            MS.resolve_numbers("estimate={beta}", {"beta": 999999},
                               {"beta": {"model": "DOES_NOT_EXIST"}}, project=p)

    def test_c16_custom_sections_are_preserved_and_partial_print_fails(self):
        from docx import Document
        p = self.project()
        for section in ("研究说明", "appendix", "额外补充"):
            CL.register_block(p, block_id=section, section=section, text="Synthetic " + section, claims=[])
        doc = Document()
        for section in ("研究说明", "appendix", "额外补充"):
            doc.add_paragraph("Synthetic " + section)
        full = Path(self.tmp)/"paper.docx"
        doc.save(full)
        self.assertTrue(MS.verify_printed(p, docx_path=full, persist=False)["ok"])
        partial = Document()
        partial.add_paragraph("Synthetic 研究说明")
        partial.add_paragraph("Synthetic 额外补充")
        part = Path(self.tmp)/"partial.docx"
        partial.save(part)
        res = MS.verify_printed(p, docx_path=part, persist=False)
        self.assertFalse(res["ok"])
        self.assertIn("appendix", [b["block"] for b in res["blocks"]
                                   if b["status"] == "stale"])

    def test_c17_refit_invalidates_old_validation(self):
        p = self.project()
        make_linear_data(self.tmp, slope=3)
        M.register(p, spec_for(self.tmp)); M.fit(p, "M1"); V.independent_ols(p, "M1")
        self.assertTrue(V.is_current(p, "M1"))
        make_linear_data(self.tmp, slope=7)
        M.register(p, spec_for(self.tmp)); M.fit(p, "M1")
        self.assertFalse(V.is_current(p, "M1"))
        self.assertFalse(next(c for c in R.evaluate(p, {"models": ["M1"]})["checks"] if c["check"] == "results_validated")["ok"])

    def test_c18_long_text_tail_is_searchable_and_new_material_invalidates_receipt(self):
        p, index, inventory = self.indexed({"long.txt": "x"*200001 + "\nTAIL_MEASUREMENT 42"})
        run = index.search("TAIL_MEASUREMENT")
        self.assertEqual(run["hits"], 1)
        (Path(self.tmp)/"materials/new.txt").write_text("new material")
        self.assertTrue(index.stale()["stale"])
        with self.assertRaises(ValueError):
            SI.require_executed(p, run["run"])

    def test_c19_concurrent_different_successors_cannot_both_replace_same_parent(self):
        p = self.project()
        initial = T.Transaction(p); initial.stage("result.txt", "v1"); initial.commit()
        txs = [T.Transaction(p, run_id=name) for name in ("left", "right")]
        for i, tx in enumerate(txs): tx.stage("result.txt", f"v2-{i}")
        barrier = threading.Barrier(2)
        successes, rejections, unexpected = [], [], []
        def publish(tx):
            barrier.wait()
            try: successes.append(tx.commit())
            except T.ParentVersionError as exc: rejections.append(str(exc))
            except Exception as exc: unexpected.append(repr(exc))
        threads = [threading.Thread(target=publish, args=(tx,)) for tx in txs]
        for thread in threads: thread.start()
        for thread in threads: thread.join(20)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(unexpected, [])
        self.assertEqual((len(successes), len(rejections)), (1, 1))

    def test_c20_false_diagnostic_does_not_satisfy_method_check(self):
        link = DC.linkage({"design_features": {"clustered": True}},
                          {"diagnostics": {"cluster_count": 2, "cluster_robust_or_mixed": False}})
        self.assertFalse(link["ok"])

    def test_c21_source_reread_is_not_a_dataset_cell_review(self):
        from PIL import Image
        p = self.project()
        materials = Path(self.tmp)/"materials"; materials.mkdir()
        Image.new("RGB", (20,20), "white").save(materials/"scan.png")
        units = SU.SourceUnits(p, root=self.tmp); units.build(materials)
        OCR.adjudicate(p, units, units.units()[0], "synthetic", reviewer="audit", note="Opened original synthetic scan")
        verifier = object.__new__(__import__("verify_dataset").Verifier)
        verifier.root, verifier.issues = Path(self.tmp), []
        verifier.v2_review_bound({}, __import__("verify_dataset").parse_time(__import__("verify_dataset").stamp()))
        self.assertEqual(verifier.issues, [])

    def test_c22_unrun_stability_requests_remain_visible_and_unassessed(self):
        p = self.project(); make_linear_data(self.tmp)
        M.register(p, spec_for(self.tmp)); M.fit(p, "M1"); V.independent_ols(p, "M1")
        out = V.stability(p, "M1", ["cluster", "lag"])
        rows = p.latest("validation_result", out["record"])["data"]["independent"]["variants"]
        self.assertEqual(out["status"], "unassessed")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["status"] == "needs_data" for r in rows))

    def test_c23_model_paths_are_consumable_by_design_check(self):
        p = self.project(); make_linear_data(self.tmp)
        M.register(p, spec_for(self.tmp))
        self.assertTrue(DC.role_accounting(M.load_spec(p, "M1")["data"])["ok"])

    def test_positive_review_fit_validate_assess_release_chain(self):
        p = known_project(self.tmp, n=40)
        result = R.evaluate(p, {"datasets": ["person"], "models": ["M1"], "claims": []})
        self.assertEqual(result["status"], "complete", result)

    def test_disjoint_publishes_preserve_other_outputs(self):
        p = self.project()
        a, b = T.Transaction(p), T.Transaction(p)
        a.stage("a.csv", "A"); b.stage("b.csv", "B")
        a.commit(); b.commit()
        self.assertEqual(T.read_published(p, "a.csv"), b"A")
        self.assertEqual(T.read_published(p, "b.csv"), b"B")

    def test_known_multiple_comparison_answers(self):
        expected = [0.03, 0.06, 0.06]
        for actual, answer in zip(V.adjust_pvalues([0.01, 0.03, 0.04], method="holm"), expected):
            self.assertAlmostEqual(actual, answer)
        self.assertEqual(V.adjust_pvalues([0.01, 0.03, 0.04], method="bonferroni"), [0.03, 0.09, 0.12])

    def test_external_command_non_coefficient_output_and_independent_adapter(self):
        p = self.project(); make_linear_data(self.tmp)
        script = Path(self.tmp)/"adapter.py"
        script.write_text('''import csv,json
rows=list(csv.DictReader(open("data/linear.csv")))
b=(float(rows[-1]["y"])-float(rows[0]["y"]))/(float(rows[-1]["x"])-float(rows[0]["x"]))
json.dump({"type":"curve", "target_parameter":"x", "unit":"score points", "scale":"linear", "estimate":b, "n":len(rows), "values":[float(r["y"]) for r in rows]},open("native.json","w"))
''', encoding="utf-8")
        checker = Path(self.tmp)/"checker.py"
        checker.write_text('''def check(project,spec):
    import csv
    rows=list(csv.DictReader(open(project.root/"data/linear.csv")))
    x=[float(r["x"]) for r in rows]; y=[float(r["y"]) for r in rows]
    mx=sum(x)/len(x); my=sum(y)/len(y)
    return {"estimate":sum((a-mx)*(b-my) for a,b in zip(x,y))/sum((a-mx)**2 for a in x), "n":len(rows)}
''', encoding="utf-8")
        spec = spec_for(self.tmp, family="agent_selected_curve")
        spec["executor"] = {"command": [PYTHON, str(script)], "result": "native.json", "code": [str(script)], "timeout_seconds": 20}
        M.register(p, spec)
        result = M.fit(p, "M1")
        self.assertEqual(result["status"], "estimated", result)
        record = p.latest("model_result", "M1")
        self.assertEqual(record["data"]["result_type"], "curve")
        self.assertEqual(len(record["data"]["payload"]["values"]), 40)
        self.assertEqual(record["data"]["native_sha256"], C.file_sha256(Path(self.tmp)/"native.json"))
        checked = V.independent_check(p, "M1", validator=str(checker)+":check", fields=["estimate","n"])
        self.assertEqual(checked["status"], "passed", checked)
        self.assertTrue(V.is_current(p, "M1"))

    def test_ode_is_a_trajectory_not_an_optimization_result(self):
        import math
        rhs = Path(self.tmp)/"rhs.py"
        rhs.write_text("def rhs(t,y):\n    return [-y[0]]\n", encoding="utf-8")
        _, out, result = self.math("ode", {"rhs": str(rhs)+":rhs", "t_span": [0,1], "y0": [1], "t_eval": [0,0.5,1]})
        self.assertEqual(out["status"], "feasible", out)
        self.assertEqual(result["type"], "trajectory")
        self.assertAlmostEqual(result["solution"][0], math.exp(-1), places=6)
        self.assertEqual(result["trajectory"]["time"], [0,0.5,1])

    def test_group_and_time_prediction_use_training_only_preprocessing(self):
        p = self.project(); make_linear_data(self.tmp, n=50)
        M.register(p, spec_for(self.tmp))
        result = V.prediction_validation(p, "M1", target="y", predictors=["x"], split="group", group="id")
        self.assertLess(result["test_rmse"], 1e-10)
        observed = p.latest("validation_result", result["record"])["data"]["observed"]
        self.assertEqual(observed["basis"]["overlap"], [])
        self.assertFalse(set(map(tuple, observed["train_keys"])) & set(map(tuple, observed["test_keys"])))

    def test_multidimensional_native_view_keeps_large_integer_and_axis_identity(self):
        import numpy as np
        import audit_view as AV
        p = self.project()
        native = Path(self.tmp)/"matrix.npy"
        np.save(native, np.array([9007199254740993+i for i in range(8)], dtype=np.int64).reshape(2,2,2))
        builder = Path(self.tmp)/"builder.py"
        builder.write_text('''def build(native,view):
    import numpy as np,csv,json
    a=np.load(native,allow_pickle=False)
    with open(view,"w",encoding="utf-8",newline="") as f:
        w=csv.writer(f);w.writerow(["flat","index","value","dtype"])
        for k,index in enumerate(np.ndindex(a.shape)):
            w.writerow([k,json.dumps(index),str(int(a[index])),str(a.dtype)])
    return {"shape":list(a.shape),"dtype":str(a.dtype),"elements":int(a.size)}
''', encoding="utf-8")
        verifier = Path(self.tmp)/"verifier.py"
        verifier.write_text('''def check(native,view,scope):
    import numpy as np,csv,json,itertools
    a=np.load(native,allow_pickle=False)
    with open(view,encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
    indices=[tuple(json.loads(r["index"])) for r in rows]
    expected=set(itertools.product(*(range(n) for n in a.shape)))
    checks=[{"check":"shape","ok":list(a.shape)==scope["shape"]},
            {"check":"coverage","ok":len(rows)==a.size and set(indices)==expected},
            {"check":"order","ok":[r["flat"] for r in rows]==list(map(str,range(a.size)))},
            {"check":"exact_values","ok":all(r["value"]==str(int(a[index])) and r["dtype"]==str(a.dtype) for r,index in zip(rows,indices))}]
    return {"checks":checks}
''', encoding="utf-8")
        built = AV.build_view(p, native, adapter=str(builder)+":build", verifier=str(verifier)+":check")
        self.assertTrue(AV.verify_view(p, built["view"])["ok"])
        view = p.root/built["view"]
        text = view.read_text(encoding="utf-8")
        self.assertIn("9007199254740993", text)
        view.write_text(text.replace("9007199254741000", "9007199254741001"), encoding="utf-8")
        self.assertFalse(AV.verify_view(p, built["view"], record=False)["ok"])

    def test_archive_member_names_cannot_escape_and_duplicate_names_are_preserved(self):
        import zipfile
        p = self.project()
        materials = Path(self.tmp)/"materials"; materials.mkdir()
        with zipfile.ZipFile(materials/"payload.zip", "w") as archive:
            archive.writestr("../../outside.txt", "outside bytes")
            archive.writestr("same.txt", "first")
            archive.writestr("same.txt", "second")
        units = SU.SourceUnits(p, root=self.tmp); units.build(materials)
        members = units.units("member")
        self.assertEqual(len(members), 3)
        paths = [(p.root/u["data"]["representation"]).resolve() for u in members]
        self.assertEqual(len(set(paths)), 3)
        self.assertTrue(all(p.dir in path.parents for path in paths))
        self.assertEqual({path.read_text() for path in paths}, {"outside bytes", "first", "second"})
        self.assertFalse((Path(self.tmp)/"outside.txt").exists())

    def test_contextual_support_review_is_required_and_refit_invalidates_it(self):
        import support_review as SR
        p = known_project(self.tmp, n=40)
        claim = CL.register_claim(p, claim_id="slope", block_id="result", text="The estimated slope is 0.42.",
                                  section="results", claim_type="result", support=[{"kind":"result", "id":"M1"}])
        self.assertFalse(SR.is_current(p, claim))
        source = p.root/"materials/raw.csv"
        reviewed = SR.review(p, "slope", decision="supported", reviewer="fixture:independent-formula",
                             note="Reopened original rows and recomputed the treatment difference: 0.52 minus 0.10; association only.",
                             reread_scopes=[{"path":str(source), "sha256":C.file_sha256(source), "locator":"all original CSV rows; y and treatment"}])
        self.assertTrue(SR.is_current(p, reviewed))
        M.fit(p, "M1")
        self.assertFalse(SR.is_current(p, reviewed))

    def test_builtin_never_discards_weight_or_multiple_fit_input(self):
        p = self.project(); make_linear_data(self.tmp)
        spec = spec_for(self.tmp); spec["weights"] = "x"
        M.register(p, spec)
        result = M.fit(p, "M1")
        self.assertEqual(result["status"], "failed")
        self.assertIn("weights/offset", str(result))

    def test_result_comparison_preserves_scale_denominator_and_time(self):
        p = self.project(); make_linear_data(self.tmp)
        spec = spec_for(self.tmp); M.register(p, spec); M.fit(p, "M1")
        other = dict(spec, id="M2", result={**spec["result"], "scale":"log", "denominator":"eligible participants", "time_scope":"2015-2023"})
        M.register(p, other); M.fit(p, "M2")
        comparison = V.compare_results(p, "M1", "M2")
        self.assertFalse(comparison["comparable"])
        self.assertEqual(set(comparison["differences"]), {"scale", "denominator", "time_scope"})

    def test_docx_note_and_csv_multiline_are_not_lost(self):
        import zipfile
        from docx import Document
        p = self.project(); materials = p.root/"materials"; materials.mkdir()
        doc = Document(); doc.add_paragraph("Main text"); doc.save(materials/"notes.docx")
        with zipfile.ZipFile(materials/"notes.docx", "a") as archive:
            archive.writestr("word/footnotes.xml", '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:footnote w:id="8"><w:p><w:r><w:t>Recovered footnote 731</w:t></w:r></w:p></w:footnote></w:footnotes>')
        (materials/"multiline.csv").write_text('id,"long\nheader"\n1,"first\nsecond"\n', encoding="utf-8", newline="")
        units = SU.SourceUnits(p, root=self.tmp); units.build(materials)
        all_units = units.units()
        recovered = "\n".join((p.root/u["data"]["representation"]).read_text(encoding="utf-8") for u in all_units if u["data"].get("representation"))
        self.assertIn("Recovered footnote 731", recovered)
        records = [u for u in all_units if u["data"]["source"].endswith("multiline.csv") and u["data"].get("unit_type") == "table"]
        # Logical records contain both lines; physical newlines must not invent observations.
        self.assertEqual(records[0]["data"]["recovered_scope"]["logical_records"], 1)
        self.assertEqual(records[0]["data"]["recovered_scope"]["header"], ["id", "long\nheader"])
        self.assertIn("first\nsecond", recovered)

    def test_cluster_and_gee_execute_with_actual_group_identity(self):
        import numpy as np
        p = self.project(); make_linear_data(self.tmp, n=80)
        path = p.root/"data/linear.csv"
        with path.open(encoding="utf-8", newline="") as stream: rows = list(csv.DictReader(stream))
        for k,row in enumerate(rows):
            row["group"] = str(k//4)
            row["y"] = str(float(row["y"]) + 0.1*np.sin(k) + (k//4)*0.02)
        csv_write(path, list(rows[0]), [list(r.values()) for r in rows])
        spec = spec_for(self.tmp); spec.update(cov_type="cluster", cluster="group")
        M.register(p, spec); self.assertEqual(M.fit(p, "M1")["status"], "estimated")
        actual = p.latest("model_result", "M1")["data"]["payload"]
        self.assertEqual(actual["diagnostics"]["cluster_count"], 20)
        gee = {**spec, "id":"GEE", "family":"gee", "groups":"group"}
        gee.pop("cov_type"); gee.pop("cluster")
        M.register(p, gee); self.assertEqual(M.fit(p, "GEE")["status"], "estimated")
        actual = p.latest("model_result", "GEE")["data"]["payload"]
        self.assertEqual(actual["diagnostics"]["within_unit_structure"]["method"], "gee")
        self.assertEqual(actual["diagnostics"]["unit_count"], 20)
        self.assertTrue(actual["diagnostics"]["converged"])

    def test_manuscript_tables_require_real_data_and_preserve_every_cell(self):
        from docx import Document
        p = known_project(self.tmp, n=20)
        CL.register_block(p, block_id="methods", section="methods", text="Synthetic table validation example.", claims=[])
        target = p.root/"paper.docx"
        spec = {"csv": "data/person.csv", "table_id": "raw"}
        rows = MS.table_rows(p, spec)
        doc = Document()
        doc.add_paragraph("Synthetic table validation example.")
        table = doc.add_table(rows=len(rows), cols=len(rows[0]))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                table.cell(r, c).text = value
        doc.save(target)
        res = MS.verify_printed(p, docx_path=target, tables=[spec], persist=False)
        self.assertTrue(res["tables_ok"])
        self.assertTrue(res["ok"], res)
        doc = Document(target); doc.tables[0].cell(1,2).text = "999"; doc.save(target)
        self.assertFalse(MS.verify_printed(p, docx_path=target, tables=[spec], persist=False)["ok"])
        csv_write(p.root/"fake.csv", ["estimate"], [["999"]])
        with self.assertRaises(MS.ManuscriptError):
            MS.table_rows(p, {"csv":"fake.csv"})
        (p.root/"ragged.csv").write_text("a,b\n1,2,3\n", encoding="utf-8")
        with self.assertRaises(MS.ManuscriptError):
            MS.table_rows(p, {"csv":"ragged.csv"})

    def test_rebuilt_dataset_can_be_fully_rereviewed_after_key_replacement(self):
        p = known_project(self.tmp, n=12, fit=False)
        source = p.root/"materials/raw.csv"
        with source.open(encoding="utf-8", newline="") as stream: rows = list(csv.DictReader(stream))
        for row in rows: row["id"] = "NEW-" + row["id"]
        for target in (source, p.root/"data/person.csv"):
            csv_write(target,["id","treatment","y"],[[r[k] for k in ("id","treatment","y")] for r in rows])
        path = p.root/"data/person.prov.jsonl"
        proofs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for item in proofs:
            item["key"] = "NEW-" + item["key"]
            if item["column"] == "id":
                item["value"] = "NEW-" + item["value"]; item["sources"][0]["raw"] = item["value"]
            item["sources"][0]["sha256"] = C.file_sha256(source)
        path.write_text("".join(json.dumps(r)+"\n" for r in proofs),encoding="utf-8")
        final_review(p.root)
        report = json.loads((p.root/"output/dataset/dataset_verification.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["cell_count"], 36)
        self.assertEqual(len((p.root/"data/person.review.jsonl").read_text().splitlines()),36)
        self.assertEqual(len(p.read("review_event")),72)
        entry=json.loads((p.root/"research_registry.json").read_text())["datasets"][0]
        self.assertTrue(WB.review_gate(p,entry)["claim_complete"])

    def test_new_dispute_overrides_previous_approval_across_timezones(self):
        from datetime import datetime,timezone,timedelta
        import verify_dataset as VD
        import contextlib,io
        p=known_project(self.tmp,n=12,fit=False)
        entry=json.loads((p.root/"research_registry.json").read_text())["datasets"][0]
        exported=WB.export_html(p,entry)
        row=WB.blind_template(p,entry,snapshot=exported)[0]
        source=row["first_pass_sources"][0]
        with (p.root/source["path"]).open(encoding="utf-8",newline="") as stream: originals=list(csv.DictReader(stream))
        observed=originals[source["locator"]["row"]-1][source["locator"]["column"]]
        row.update(value_here=observed,reviewer="timezone-source-rereader",note="Reopened original CSV row and column and checked this exact entity.",
                   reread_scope=source,checked_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
        old=WB.import_second_pass(p,entry,[row],snapshot=exported)
        WB.write_review_file(p,entry,old["review_lines"])
        row.update(value_here="conflicting reread",checked_at=datetime.now(timezone.utc).isoformat())
        dispute=WB.import_second_pass(p,entry,[row],snapshot=exported)
        self.assertEqual(len(dispute["conflicts"]),1)
        self.assertFalse(WB.review_gate(p,entry)["claim_complete"])
        with contextlib.redirect_stdout(io.StringIO()):
            code=VD.main(["--registry","research_registry.json","--root",str(p.root),"--out",str(p.root/"output/dataset"),"--stage","final","--snapshot",exported["snapshot_path"]])
        self.assertEqual(code,2)
        with (p.root/"output/dataset/cell_issues.csv").open(encoding="utf-8-sig") as stream: issues=list(csv.DictReader(stream))
        self.assertTrue(any("latest second pass is disputed" in item["detail"] for item in issues))

    def test_raster_fonts_need_exact_live_render_proof_at_actual_placement(self):
        import fitz
        import matplotlib.pyplot as plt
        import pandas as pd
        import figsemantics as FS
        import layout_check as LC
        from docx import Document
        from docx.shared import Cm
        p=self.project(); png=p.root/"plot.png"
        data=pd.DataFrame({"group":["A","B"],"score":[1.,2.]})
        fig,ax=plt.subplots(figsize=(6,4),dpi=100)
        ax.bar(data["group"],data["score"]);ax.tick_params(labelsize=12)
        fig.savefig(png,dpi=600)
        mapping={"type":"bar","x":"group","y":"score"}
        record=FS.record_figure(p,"F",fig,mapping,"data.csv","fixture-only",FS.check_figure(fig,data,mapping),FS.label_geometry(fig),FS.palette_report(fig),png_path=str(png),dpi=600)
        plt.close(fig)
        docx=p.root/"plot.docx"; pdf_path=p.root/"plot.pdf"
        doc=Document();doc.add_picture(str(png),width=Cm(15));doc.add_paragraph("图 1 Synthetic chart");doc.save(docx)
        with fitz.open() as pdf:
            page=pdf.new_page();page.insert_image(fitz.Rect(50,50,50+15*72/2.54,50+10*72/2.54),filename=str(png));pdf.save(pdf_path)
        figure={"figure_id":"F","png":str(png),"caption":"Synthetic chart"}
        no_proof=LC.check_placement(docx,pdf_path,figures=[figure])
        self.assertFalse(next(c for c in no_proof["checks"] if c["check"]=="min_fontsize")["ok"])
        checked=LC.check_placement(docx,pdf_path,figures=[{**figure,"figure_record":record}])
        self.assertTrue(checked["ok"],checked)
        proof=checked["images"][0]["raster_font_proof"]
        self.assertAlmostEqual(proof["observed"],12*15/15.24,places=4)
        too_small=LC.check_placement(docx,pdf_path,figures=[{**figure,"figure_record":record}],min_fontsize=13)
        self.assertFalse(too_small["ok"])
        record["data"]["png_sha256"]="0"*64
        self.assertIsNone(LC.bound_raster_fontsize({**figure,"figure_record":record},[{"width_cm":15}],[{"width_cm":15}]))
