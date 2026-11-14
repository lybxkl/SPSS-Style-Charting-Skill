# -*- coding: utf-8 -*-
"""Environment binding, cache honesty, scheduler and the release gate.

Covers A34 (environment snapshot before/after), A35 (reuse is not a re-run),
A36 (scheduler respects dependencies and budgets), A55 (four release states),
A56 (limited release still needs the hard gates), A57 (partial cannot bypass),
A59 (dangling dependency blocks a step).
"""
import json
import os

from _helpers import TempCase, write_csv

import contract_v2 as C
import lifecycle as L
import release as R


class TestEnvironment(TempCase):
    def test_snapshot_and_drift(self):
        proj = C.Project(self.tmp)
        os.makedirs(os.path.join(self.tmp, "rules"))
        with open(os.path.join(self.tmp, "rules", "coding.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("rule v1\n")
        rec = L.snapshot(proj, name="run1", ruledir="rules",
                         config={"lang": "zh"})
        self.assertEqual(rec["data"]["phase"], "run1")
        self.assertIn("python", rec["data"])
        self.assertIn("packages", rec["data"])
        same = L.compare(proj, "run1")
        self.assertFalse(same["drifted"], same["changes"])
        with open(os.path.join(self.tmp, "rules", "coding.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("rule v2\n")
        drifted = L.compare(proj, "run1")
        self.assertTrue(drifted["drifted"])
        self.assertTrue(any(c["section"] == "external_inputs"
                            for c in drifted["changes"]))
        rec2 = proj.latest("environment_snapshot", "env:run1")
        self.assertEqual(rec2["status"], "drifted")

    def test_seed_is_not_treated_as_proof(self):
        proj = C.Project(self.tmp)
        rec = L.snapshot(proj, name="s", seeds={"numpy": 42})
        self.assertEqual(rec["data"]["seeds"]["numpy"], 42)
        out = L.compare(proj, "s")
        self.assertIn("seed does not make", out["note"])


class TestCache(TempCase):
    def test_reuse_writes_a_new_run_and_never_redates(self):
        proj = C.Project(self.tmp)
        os.makedirs(os.path.join(self.tmp, "data"))
        src = os.path.join(self.tmp, "data", "in.csv")
        write_csv(src, ["a"], [["1"]])
        art = os.path.join(self.tmp, "data", "out.json")
        with open(art, "w", encoding="utf-8") as fh:
            fh.write('{"v": 1}')
        implementation=self.p("script.py")
        with open(implementation,"w",encoding="utf-8") as stream:stream.write("# actual synthetic implementation\n")
        key = L.cache_key(inputs={"data/in.csv": C.file_sha256(src)},
                          code={"script.py": C.file_sha256(implementation)}, rules={}, label="fit",
                          environment={"python": "3.12"})
        rec = L.put(proj, key, artifact="data/out.json",
                    inputs={"data/in.csv": C.file_sha256(src)},
                    code={"script.py": C.file_sha256(implementation)}, rules={},
                    environment={"python": "3.12"})
        first = L.reuse(proj, key, run_id="run-a")
        self.assertTrue(first["reused"])
        second = L.reuse(proj, key, run_id="run-b")
        self.assertTrue(second["reused"])
        step = proj.latest("workflow_step", second["run"])
        self.assertFalse(step["data"]["run_state"]["ran_again"])
        self.assertEqual(step["data"]["run_state"]["origin_run"], "manual")
        entry = proj.latest("cache_entry", key)
        self.assertEqual(entry["data"]["reuse"]["count"], 2)

    def test_changed_input_invalidates_the_cache(self):
        proj = C.Project(self.tmp)
        os.makedirs(os.path.join(self.tmp, "data"))
        src = os.path.join(self.tmp, "data", "in.csv")
        write_csv(src, ["a"], [["1"]])
        art = os.path.join(self.tmp, "data", "out.json")
        with open(art, "w", encoding="utf-8") as fh:
            fh.write("{}")
        key = "k1"
        L.put(proj, key, artifact="data/out.json",
              inputs={"data/in.csv": C.file_sha256(src)}, code={}, rules={},
              environment={})
        with open(src, "a", encoding="utf-8") as fh:
            fh.write("2\n")
        out = L.reuse(proj, key, run_id="r")
        self.assertFalse(out["reused"])
        self.assertEqual(out["state"], "stale")
        self.assertEqual(proj.latest("cache_entry", key)["status"], "stale")


class TestScheduler(TempCase):
    def test_dependencies_and_budget(self):
        proj = C.Project(self.tmp)
        L.plan(proj, [
            {"id": "ingest", "goal": "read materials", "produces": ["a.csv"]},
            {"id": "fit", "goal": "fit M1", "depends_on": ["ingest"],
             "budget": {"tokens": 100}},
            {"id": "write", "goal": "write paper", "depends_on": ["fit"]}])
        self.assertEqual(L.ready(proj), ["ingest"])
        with self.assertRaises(SystemExit):
            L.start(proj, "fit")
        L.start(proj, "ingest")
        L.finish(proj, "ingest", status="completed", detail="52 files")
        self.assertEqual(L.ready(proj), ["fit"])
        L.start(proj, "fit", token_budget=50)
        done = L.finish(proj, "fit", status="completed", tokens_used=140)
        self.assertTrue(done["data"]["run_state"]["over_budget"])
        self.assertEqual(L.blocked_by(proj), {})
        self.assertEqual(L.ready(proj), ["write"])

    def test_failed_dependency_keeps_the_successor_blocked(self):
        proj = C.Project(self.tmp)
        L.plan(proj, [{"id": "a", "goal": "x"},
                      {"id": "b", "goal": "y", "depends_on": ["a"]}])
        L.start(proj, "a")
        L.finish(proj, "a", status="failed", detail="crash")
        self.assertEqual(L.ready(proj), [])
        self.assertEqual(L.blocked_by(proj), {"b": ["a"]})


class TestRelease(TempCase):
    def _base(self):
        proj = C.Project(self.tmp)
        os.makedirs(os.path.join(self.tmp, "output", "verify"))
        write_csv(os.path.join(self.tmp, "output", "verify",
                               "number_issues.csv"), ["severity"], [])
        os.makedirs(os.path.join(self.tmp, "output", "dataset"))
        return proj

    def test_empty_project_is_not_ready(self):
        proj = self._base()
        scope = {"models": ["M1"], "claims": []}
        res = R.evaluate(proj, scope)
        self.assertEqual(res["status"], "not_ready")
        self.assertTrue(res["errors"])

    def test_complete_release_requires_real_evidence(self):
        proj = self._base()
        # a registered spec that never ran is not terminal
        spec = {"id": "M1", "family": "ols", "purpose": "x",
                "variables": {"y": "y", "x": ["x"]},
                "inputs": [{"role": "fit", "dataset": "data/d.csv",
                            "sha256": "0" * 64, "keys": ["id"]}],
                "n_semantics": {"kind": "observation", "unit": "one row"},
                "result": {"type": "coefficient_table",
                           "target_parameter": "x", "unit": "u",
                           "scale": "linear"}}
        import models as M
        M.register(proj, spec)
        res = R.evaluate(proj, {"models": ["M1"]})
        self.assertEqual(res["status"], "not_ready")
        self.assertTrue(any(e["detail"].startswith("status is ready")
                            for e in res["errors"]))

    def test_partial_scope_does_not_bypass_a_hard_gate(self):
        proj = self._base()
        scope = {"datasets": ["person"], "models": [], "claims": [],
                 "allow_limited": True}
        report = {"status": "partial", "error_count": 0,
                  "datasets": [{"id": "person", "status": "verified"}]}
        with open(os.path.join(self.tmp, "output", "dataset",
                               "dataset_verification.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh)
        res = R.evaluate(proj, scope)
        self.assertNotEqual(res["status"], "limited")
        self.assertEqual(res["status"], "not_ready")
        self.assertTrue(any(c["check"] == "datasets_reviewed" and not c["ok"]
                            for c in res["checks"]))

    def test_limited_is_allowed_only_when_every_hard_gate_passes(self):
        from _research_fixture import known_project
        proj = known_project(self.tmp, n=6, second_dataset=True, fit=False)
        scope = {"datasets": ["person"], "models": [], "claims": [],
                 "allow_limited": True, "artifacts": []}
        res = R.evaluate(proj, scope)
        self.assertEqual(res["status"], "limited", res["errors"])
        self.assertEqual(res["uncovered"], ["events"])
        # without the explicit opt-in the same gap is not_ready
        no_opt = dict(scope)
        no_opt.pop("allow_limited")
        self.assertEqual(R.evaluate(proj, no_opt)["status"], "not_ready")

    def test_missing_artifact_fails_the_release(self):
        proj = self._base()
        report = {"status": "verified", "error_count": 0, "datasets": []}
        with open(os.path.join(self.tmp, "output", "dataset",
                               "dataset_verification.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh)
        res = R.evaluate(proj, {"artifacts": ["out/final.docx"]})
        self.assertEqual(res["status"], "not_ready")
        self.assertTrue(any(e["check"] == "artifacts_present"
                            for e in res["errors"]))

    def test_build_writes_a_manifest_with_the_real_status(self):
        proj = self._base()
        out = R.build(proj, {"models": [], "claims": [],
                             "artifacts": ["output/verify/number_issues.csv"]})
        self.assertEqual(out["status"], "not_ready")
        manifest = json.loads((proj.root / out["manifest"]).read_text(
            encoding="utf-8"))
        self.assertEqual(manifest["status"], "not_ready")
        self.assertEqual(len(manifest["artifacts"]), 1)
        rec = proj.latest("release_snapshot")
        self.assertEqual(rec["status"], "not_ready")
