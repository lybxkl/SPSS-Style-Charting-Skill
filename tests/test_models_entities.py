# -*- coding: utf-8 -*-
"""Entities/joins, the model registry, independent validation and stability.

Covers A19 (unit harmonisation and join audit), A20 (multi-input roles), A21
(no-sample-N for a mathematical model), A22/A23 (solve quality), A24 (N is the
observed unit), A25 (V-05 n vs n_dropna), A26 (conditions evaluated), A27
(independent numeric validation), A28 (shared wrong preprocessing is not
independence), A29 (stability gated on validation), A30 (fragile estimate is
reported).
"""
import json
import os

from _helpers import TempCase, write_csv

import contract_v2 as C
import entities as E
import models as M
import validation as V


def make_linear_data(tmp, n=40, slope=3.0, intercept=2.0, missing=0):
    rows = []
    for i in range(n):
        x = (i % 10) + 1
        y = intercept + slope * x
        rows.append([f"id{i:03d}", str(x), "" if i < missing else f"{y:.6f}"])
    path = os.path.join(tmp, "data", "linear.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_csv(path, ["id", "x", "y"], rows)
    return path


def spec_for(tmp, *, spec_id="M1", family="ols", extra=None):
    path = os.path.join(tmp, "data", "linear.csv")
    spec = {
        "id": spec_id, "family": family, "purpose": "test model",
        "variables": {"y": "y", "x": ["x"], "controls": []},
        "inputs": [{"role": "fit", "dataset": "data/linear.csv",
                    "sha256": C.file_sha256(path), "keys": ["id"]}],
        "n_semantics": {"kind": "observation", "unit": "one record"},
        "result": {"type": "coefficient_table", "target_parameter": "x",
                   "unit": "score points", "scale": "linear"},
    }
    if extra:
        spec.update(extra)
    return spec


class TestEntities(TempCase):
    def test_relations_are_between_registered_entities(self):
        proj = C.Project(self.tmp)
        ents = E.Entities(proj)
        ents.register_type("firm", fields=["name"], identity_rule="reg_no")
        ents.register("firm", "A-001", attributes={"name": "甲公司"},
                      sources=[{"path": "materials/a.csv"}])
        ents.register("person", "P01", attributes={"name": "张三"},
                      sources=[{"path": "materials/b.csv"}])
        rel = ents.relation("firm:A-001", "person:P01", "employs",
                            evidence=[{"path": "materials/a.csv",
                                       "locator": {"type": "csv", "row": 1}}])
        self.assertEqual(rel["data"]["relation_type"], "employs")
        with self.assertRaises(ValueError):
            ents.relation("firm:A-001", "person:P99", "employs", evidence=[])

    def test_join_audit_counts_units_not_rows(self):
        proj = C.Project(self.tmp)
        os.makedirs(os.path.join(self.tmp, "data"))
        write_csv(os.path.join(self.tmp, "data", "left.csv"),
                  ["id", "name", "size"], [["A", "甲", "10"], ["B", "乙", "20"]])
        write_csv(os.path.join(self.tmp, "data", "right.csv"),
                  ["id", "name", "size"],
                  [["a", "甲", "11"], ["a", "甲", "12"], ["B", "乙", "20"]])
        out = E.join_tables(proj, left_rel="data/left.csv",
                            right_rel="data/right.csv", left_key="id",
                            how="left", unit="one firm")
        self.assertEqual(out["rows"]["left"], 2)
        self.assertEqual(out["rows"]["output"], 3)   # a duplicated by the join
        self.assertEqual(out["distinct_units"], 2)
        self.assertIn("a", out["rows"]["duplicate_right_keys"])
        self.assertTrue(out["conflicts"])
        audit = proj.latest("join_audit")
        self.assertIn("not additive", audit["data"]["notes"])
        self.assertEqual(audit["status"], "failed")

    def test_unit_harmonisation_is_explicit(self):
        proj = C.Project(self.tmp)
        os.makedirs(os.path.join(self.tmp, "data"))
        write_csv(os.path.join(self.tmp, "data", "money.csv"),
                  ["id", "amount"], [["A", "1.5"], ["B", ""]])
        out = E.harmonise_units(proj, dataset_rel="data/money.csv",
                                column="amount", from_unit="万元", to_unit="元")
        self.assertEqual(out["factor"], 10000.0)
        rows = [ln.strip().split(",") for ln in
                open(os.path.join(self.tmp, out["output"]),
                     encoding="utf-8").read().strip().splitlines()]
        self.assertEqual(rows[1], ["A", "15000.0"])
        self.assertEqual(rows[2], ["B", ""])
        with self.assertRaises(ValueError):
            E.convert_unit(1.0, "元", "cm")


class TestModelRegistry(TempCase):
    def test_statistical_spec_needs_observation_semantics(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp)
        bad = spec_for(self.tmp)
        bad["n_semantics"] = {"kind": "none"}
        with self.assertRaises(M.ModelError):
            M.register(proj, bad)
        good = M.register(proj, spec_for(self.tmp))
        self.assertEqual(good["status"], "ready")

    def test_math_spec_must_not_invent_n(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp)
        math_spec = spec_for(self.tmp, spec_id="OPT1", family="lp")
        math_spec.pop("result")
        math_spec["dimensions"] = 2
        math_spec["constraints"] = ["x>=0"]
        with self.assertRaises(M.ModelError):
            M.register(proj, math_spec)        # statistical N semantics kept
        math_spec["n_semantics"] = {"kind": "none"}
        rec = M.register(proj, math_spec)
        self.assertEqual(rec["data"]["sample_accounting"]["kind"], "none")

    def test_conditions_detect_a_changed_dataset_version(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp)
        M.register(proj, spec_for(self.tmp))
        with open(os.path.join(self.tmp, "data", "linear.csv"), "a",
                  encoding="utf-8") as fh:
            fh.write("zzz,1,5\n")
        cond = M.conditions(proj, "M1")
        self.assertFalse(cond["ok"])
        bad = [f for f in cond["findings"]
               if f["check"] == "input_version[fit]"]
        self.assertFalse(bad[0]["ok"])
        self.assertIn("re-bind", bad[0]["detail"])

    def test_ols_recovers_the_known_slope_and_n(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp, n=40, slope=3.0, missing=4)
        M.register(proj, spec_for(self.tmp))
        out = M.fit(proj, "M1")
        self.assertEqual(out["status"], "estimated", out)
        self.assertAlmostEqual(out["estimate"], 3.0, places=6)
        rec = proj.latest("model_result", "M1")
        res = rec["data"]["payload"]
        self.assertEqual(res["n"], 36)
        self.assertEqual(res["n_dropna"], 4)
        self.assertEqual(res["sample_unit"], "one record")
        self.assertEqual(res["unit"], "score points")

    def test_multi_input_roles_are_separate_versions_and_n_is_not_summed(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp, n=20)
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)
        write_csv(os.path.join(self.tmp, "data", "holdout.csv"),
                  ["id", "x", "y"], [["h1", "1", "5"], ["h2", "2", "8"]])
        spec = spec_for(self.tmp)
        spec["inputs"].append({"role": "validate",
                               "dataset": "data/holdout.csv",
                               "sha256": C.file_sha256(os.path.join(
                                   self.tmp, "data", "holdout.csv")),
                               "keys": ["id"]})
        M.register(proj, spec)
        cond = M.conditions(proj, "M1")
        self.assertTrue(cond["ok"], cond)
        out = M.fit(proj, "M1")
        res = proj.latest("model_result", "M1")["data"]["payload"]
        self.assertEqual(res["n"], 20)          # holdout rows are not added
        self.assertEqual(out["status"], "estimated")

    def test_causal_and_global_claims_are_scope_checked(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp)
        M.register(proj, spec_for(self.tmp))
        M.fit(proj, "M1")
        bad = M.assert_conclusion_scope(proj, "M1", {"causal": True})
        self.assertFalse(bad["ok"])
        self.assertIn("causal", " ".join(bad["problems"]))
        bad2 = M.assert_conclusion_scope(proj, "M1", {"global_optimum": True})
        self.assertFalse(bad2["ok"])
        good = M.assert_conclusion_scope(proj, "M1", {"unit": "score points"})
        self.assertTrue(good["ok"])


class TestMathModels(TempCase):
    def _lp_spec(self, proj, *, c, A_ub=None, b_ub=None, bounds=None,
                 spec_id="OPT1"):
        make_linear_data(self.tmp)
        spec = {"id": spec_id, "family": "lp", "purpose": "linear program",
                "inputs": [{"role": "fit", "dataset": "data/linear.csv",
                            "sha256": C.file_sha256(os.path.join(
                                self.tmp, "data", "linear.csv")),
                            "keys": ["id"]}],
                "n_semantics": {"kind": "none"},
                "dimensions": len(c), "constraints": ["declared bounds"],
                "parameters": {"c": c, "A_ub": A_ub, "b_ub": b_ub,
                               "bounds": bounds or [[0, None]] * len(c)},
                "result": {"type": "linear_program", "target_parameter": "obj",
                           "unit": "yuan", "scale": "absolute"}}
        M.register(proj, spec)
        return spec

    def test_lp_reports_certified_optimum(self):
        proj = C.Project(self.tmp)
        self._lp_spec(proj, c=[-1, -2],
                      A_ub=[[1, 1], [1, 0], [0, 1]], b_ub=[4, 3, 3])
        out = M.solve(proj, "OPT1", budget_seconds=20)
        self.assertEqual(out["status"], "certified_global")
        self.assertAlmostEqual(out["objective"], -7.0, places=6)
        rec = proj.latest("model_result", "OPT1")
        res = rec["data"]["payload"]
        self.assertEqual(res["solve_quality"], "certified_global")
        self.assertIsNone(rec["data"]["sample_scope"]["n"])
        self.assertEqual(rec["data"]["sample_scope"]["kind"], "none")
        claim = M.assert_conclusion_scope(proj, "OPT1", {"sample": True})
        self.assertFalse(claim["ok"])

    def test_infeasible_and_unbounded_are_distinct_states(self):
        proj = C.Project(self.tmp)
        self._lp_spec(proj, c=[1, 1], A_ub=[[1, 1]], b_ub=[-1], spec_id="INF")
        inf = M.solve(proj, "INF", budget_seconds=20)
        self.assertEqual(inf["status"], "infeasible")
        proj2 = C.Project(os.path.join(self.tmp, "p2"))
        os.makedirs(os.path.join(self.tmp, "p2"), exist_ok=True)
        make_linear_data(os.path.join(self.tmp, "p2"))
        spec = {"id": "UNB", "family": "lp", "purpose": "unbounded",
                "inputs": [{"role": "fit", "dataset": "data/linear.csv",
                            "sha256": C.file_sha256(os.path.join(
                                self.tmp, "p2", "data", "linear.csv")),
                            "keys": ["id"]}],
                "n_semantics": {"kind": "none"}, "dimensions": 2,
                "constraints": ["x>=0"],
                "parameters": {"c": [-1, -1],
                               "bounds": [[0, None], [0, None]]},
                "result": {"type": "linear_program", "target_parameter": "obj",
                           "unit": "yuan", "scale": "absolute"}}
        M.register(proj2, spec)
        unb = M.solve(proj2, "UNB", budget_seconds=20)
        self.assertEqual(unb["status"], "unbounded")

    def test_nonlinear_timeout_is_a_state_not_a_crash(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp)
        spin = os.path.join(self.tmp, "spin.py")
        with open(spin, "w", encoding="utf-8") as fh:
            fh.write("import time\n"
                     "def objective(x):\n"
                     "    time.sleep(30)\n"
                     "    return sum(v*v for v in x)\n")
        spec = {"id": "NLP", "family": "nonlinear", "purpose": "slow",
                "inputs": [{"role": "fit", "dataset": "data/linear.csv",
                            "sha256": C.file_sha256(os.path.join(
                                self.tmp, "data", "linear.csv")),
                            "keys": ["id"]}],
                "n_semantics": {"kind": "none"}, "dimensions": 2,
                "constraints": ["x in R^2"],
                "parameters": {"objective": f"{spin}:objective",
                               "x0": [1, 1]},
                "result": {"type": "optimization_solution",
                           "target_parameter": "obj", "unit": "u",
                           "scale": "absolute"}}
        M.register(proj, spec)
        out = M.solve(proj, "NLP", budget_seconds=1.5)
        self.assertEqual(out["status"], "timeout")
        res = proj.latest("model_result", "NLP")["data"]["payload"]
        self.assertEqual(res["solve_quality"], "timeout")
        self.assertIn("budget", res["message"])


class TestValidation(TempCase):
    def test_independent_ols_agrees_and_detects_a_changed_fit(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp, n=50, slope=-2.5)
        M.register(proj, spec_for(self.tmp))
        M.fit(proj, "M1")
        out = V.independent_ols(proj, "M1")
        self.assertEqual(out["status"], "passed", out)
        self.assertLess(out["max_relative_difference"], 1e-6)
        self.assertEqual(out["independence"]["layers"],
                         ["numeric"])
        # tamper with the stored estimate: the independent route must notice
        rec = proj.latest("model_result", "M1")
        payload = json.loads(json.dumps(rec["data"]))
        payload["payload"]["coefficients"]["x"]["estimate"] = 99.0
        new = C.make_record("model_result", rec["id"], payload,
                            producer=C.producer_for("tamper", version="1",
                                                    module_file=__file__),
                            status="produced", revision=rec["revision"] + 1)
        proj.append("model_result", new, enforce_transition=False)
        bad = V.independent_ols(proj, "M1")
        self.assertEqual(bad["status"], "failed")

    def test_shared_preprocessing_is_not_independence(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp)
        M.register(proj, spec_for(self.tmp))
        M.fit(proj, "M1")
        out = V.independent_ols(proj, "M1", shared_preprocessing=True)
        self.assertEqual(out["status"], "agrees_but_not_independent")
        self.assertIn("transform", out["independence"]["shared"])
        self.assertTrue(any("arithmetic only" in n for n in
                            [out["independence"]["note"]]))

    def test_stability_requires_validation_then_reports_fragility(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp, n=30, slope=3.0)
        M.register(proj, spec_for(self.tmp))
        M.fit(proj, "M1")
        with self.assertRaises(SystemExit):
            V.stability(proj, "M1", ["drop_control"])
        V.independent_ols(proj, "M1")
        out = V.stability(proj, "M1", ["drop_control", "subsample"])
        self.assertFalse(out["fragile"])
        self.assertEqual(out["n_variants"], 2)   # the inapplicable request remains visible
        rows = proj.latest("validation_result", out["record"])["data"]["independent"]["variants"]
        self.assertEqual(rows[0]["status"], "not_applicable")

    def test_sign_flip_is_reported(self):
        flipped = V.summarise_stability([
            {"variant": "a", "estimate": 0.4,
             "ci": {"ci_low": 0.1, "ci_high": 0.7}},
            {"variant": "b", "estimate": -0.2,
             "ci": {"ci_low": -0.5, "ci_high": 0.05}}], 0.4)
        self.assertTrue(flipped["sign_flip"])
        self.assertTrue(flipped["fragile"])
        self.assertEqual(flipped["range"], [-0.2, 0.4])
        stable = V.summarise_stability([
            {"variant": "a", "estimate": 0.4,
             "ci": {"ci_low": 0.1, "ci_high": 0.7}},
            {"variant": "b", "estimate": 0.3,
             "ci": {"ci_low": 0.05, "ci_high": 0.6}}], 0.4)
        self.assertFalse(stable["sign_flip"])
        self.assertFalse(stable["fragile"])

    def test_stability_record_stores_the_summary(self):
        proj = C.Project(self.tmp)
        make_linear_data(self.tmp, n=30, slope=3.0)
        M.register(proj, spec_for(self.tmp))
        M.fit(proj, "M1")
        V.independent_ols(proj, "M1")
        out = V.stability(proj, "M1", ["subsample"])
        rec = proj.latest("validation_result", out["record"])
        self.assertIn("sign_flip", rec["data"]["observed"])
        self.assertEqual(rec["status"], "passed")
