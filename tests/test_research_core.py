# -*- coding: utf-8 -*-
"""Dependency graph and transactional publishing.

Covers A29 (change impact incl. negative judgements), A31 (graph half),
A53 (graph half), A48 (no half-published state), A49 (concurrent writers),
A50 (checkpoint invalidation) and A55 (reuse receipts are distinct).
"""
import json
import os
import subprocess
import sys
import time

from _helpers import PYTHON, SCRIPTS, TempCase

import contract_v2 as C
import depgraph as D
import txn as T


def project(tmp):
    return C.Project(tmp)


class TestGraph(TempCase):
    def setUp(self):
        super().setUp()
        self.proj = project(self.tmp)
        self.g = D.DependencyGraph(self.proj)

    def test_register_and_version_bump_records_event(self):
        a = self.g.register("source", "materials/a.pdf", "sha256:aaa",
                            label="a.pdf")
        self.assertEqual(a["status"], "active")
        same = self.g.register("source", "materials/a.pdf", "sha256:aaa")
        self.assertEqual(same["revision"], 1)
        bumped = self.g.register("source", "materials/a.pdf", "sha256:bbb")
        self.assertEqual(bumped["revision"], 2)
        events = [e["data"]["event"] for e in self.g.events()]
        self.assertEqual(events, ["created", "content_changed"])

    def test_impact_is_transitive_across_every_edge_type(self):
        self.g.register("source", "a.pdf", "h1")
        self.g.register("dataset", "d1", "h2")
        self.g.register("model", "m1", "h3")
        self.g.register("figure", "f1", "h4")
        self.g.register("claim", "c1", "h5")
        self.g.register("block", "b1", "h6")
        self.g.add_edge("source:a.pdf", "dataset:d1", "supplies")
        self.g.add_edge("dataset:d1", "model:m1", "supplies")
        self.g.add_edge("model:m1", "figure:f1", "presents")
        self.g.add_edge("model:m1", "claim:c1", "cites")
        self.g.add_edge("claim:c1", "block:b1", "cites")
        res = self.g.impact(["source:a.pdf"])
        self.assertEqual(res["affected_count"], 5)
        self.assertEqual(sorted(res["by_type"]), ["block", "claim", "dataset",
                                                  "figure", "model"])

    def test_negative_judgements_are_reflagged_on_new_material(self):
        self.g.register("source", "a.pdf", "h1")
        self.g.register("dataset", "d1", "h2")
        self.g.add_edge("source:a.pdf", "dataset:d1", "excludes",
                        note="a.pdf has no treatment variable")
        res = self.g.impact(["source:a.pdf"])
        self.assertIn("dataset:d1", res["rejudge_negative"])

    def test_derivation_cycle_rejected(self):
        self.g.register("dataset", "a", "h1")
        self.g.register("dataset", "b", "h2")
        self.g.add_edge("dataset:a", "dataset:b", "derived")
        with self.assertRaises(D.CycleError):
            self.g.add_edge("dataset:b", "dataset:a", "derived")

    def test_self_edge_rejected(self):
        self.g.register("dataset", "a", "h1")
        with self.assertRaises(D.CycleError):
            self.g.add_edge("dataset:a", "dataset:a", "supplies")

    def test_unknown_edge_type_rejected(self):
        with self.assertRaises(D.GraphError):
            self.g.add_edge("a", "b", "vibes")

    def test_negative_edge_does_not_create_false_cycle(self):
        self.g.register("dataset", "a", "h1")
        self.g.register("dataset", "b", "h2")
        self.g.add_edge("dataset:a", "dataset:b", "derived")
        self.g.add_edge("dataset:b", "dataset:a", "excludes")   # judgement, not derivation
        self.assertTrue(self.g.check()["ok"])

    def test_mark_stale_and_check(self):
        self.g.register("dataset", "a", "h1")
        self.g.register("claim", "c", "h2")
        self.g.add_edge("dataset:a", "claim:c", "cites")
        stale = self.g.mark_stale(["dataset:a"], reason="source changed")
        self.assertEqual(stale[0]["status"], "stale")
        self.assertTrue(self.g.check()["ok"])
        self.assertEqual(len(self.g.events()), 3)

    def test_graph_persists_across_instances(self):
        self.g.register("source", "a.pdf", "h1")
        self.g.add_edge("source:a.pdf", "dataset:d", "supplies")
        again = D.DependencyGraph(C.Project(self.tmp))
        self.assertEqual(len(again.nodes()), 1)
        self.assertEqual(len(again.edges()), 1)

    def test_cli_roundtrip(self):
        from _helpers import run
        self.assertEqual(run("depgraph.py", "--root", self.tmp, "register",
                             "--type", "source", "--id", "a.pdf",
                             "--version", "h1").returncode, 0)
        out = run("depgraph.py", "--root", self.tmp, "register", "--type",
                  "dataset", "--id", "d1", "--version", "h2")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(run("depgraph.py", "--root", self.tmp, "edge",
                             "--from", "source:a.pdf", "--to", "dataset:d1",
                             "--type", "supplies").returncode, 0)
        out = run("depgraph.py", "--root", self.tmp, "impact", "--changed",
                  "source:a.pdf")
        self.assertIn("dataset:d1", out.stdout)
        self.assertEqual(run("depgraph.py", "--root", self.tmp,
                             "check").returncode, 0)


class TestTransaction(TempCase):
    def test_commit_publishes_and_verifies(self):
        proj = project(self.tmp)
        src = self.p("input.csv")
        open(src, "w", encoding="utf-8").write("a,b\n1,2\n")
        t = T.Transaction(proj, label="table1")
        t.snapshot_inputs([src])
        t.bind_code([os.path.join(SCRIPTS, "txn.py")])
        t.stage("results/table1.csv", "a,b\n1,2\n")
        manifest = t.commit(message="first")
        self.assertTrue(T.verify_commit(proj, manifest["commit"]))
        self.assertEqual(T.read_published(proj, "results/table1.csv"),
                         b"a,b\n1,2\n")
        pointer = T.read_pointer(proj)
        self.assertEqual(pointer["commit"], manifest["commit"])

    def test_input_changed_between_start_and_commit_blocks_publish(self):
        proj = project(self.tmp)
        src = self.p("input.csv")
        open(src, "w", encoding="utf-8").write("v\n1\n")
        t = T.Transaction(proj)
        t.snapshot_inputs([src])
        t.stage("out.csv", "v\n1\n")
        open(src, "w", encoding="utf-8").write("v\n2\n")   # raced edit
        with self.assertRaises(T.InputChanged):
            t.commit()
        self.assertIsNone(T.read_pointer(proj))
        self.assertEqual(t.state, "open")
        info = t.fail("input changed")
        self.assertEqual(info["state"], "failed")

    def test_missing_staged_file_blocks_publish_and_previous_version_survives(self):
        proj = project(self.tmp)
        t1 = T.Transaction(proj)
        t1.stage("out.csv", "v1\n")
        first = t1.commit()
        t2 = T.Transaction(proj)
        t2.stage("out.csv", "v2\n")
        os.unlink(os.path.join(t2.staging, "out.csv"))     # simulated disk failure
        with self.assertRaises(T.PublishError):
            t2.commit()
        self.assertEqual(T.read_pointer(proj)["commit"], first["commit"])
        self.assertEqual(T.read_published(proj, "out.csv"), b"v1\n")

    def test_empty_run_refuses_to_publish(self):
        proj = project(self.tmp)
        with self.assertRaises(T.PublishError):
            T.Transaction(proj).commit()

    def test_parent_version_guard(self):
        proj = project(self.tmp)
        t1 = T.Transaction(proj)
        t1.stage("out.csv", "v1\n")
        t1.commit()
        t2 = T.Transaction(proj)
        t2.stage("out.csv", "v2\n")
        t2.expect_parent("out.csv", "f" * 64)
        with self.assertRaises(T.ParentVersionError):
            t2.commit()
        self.assertEqual(T.read_published(proj, "out.csv"), b"v1\n")

    def test_idempotent_commit_same_content_same_id(self):
        proj = project(self.tmp)
        ids = []
        for _ in range(2):
            t = T.Transaction(proj, parent="root")
            t.stage("out.csv", "same\n")
            ids.append(t.commit()["commit"])
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(len(list(proj.path("commits").glob("*.json"))), 1)

    def test_interrupted_run_is_recoverable_but_never_published(self):
        proj = project(self.tmp)
        script = (
            "import sys, os; sys.path.insert(0, r'%s');"
            "import contract_v2 as C, txn as T;"
            "p=C.Project(r'%s'); t=T.Transaction(p);"
            "t.stage('out.csv','half');"
            "os._exit(1)" % (SCRIPTS, self.tmp))
        proc = subprocess.run([PYTHON, "-c", script], capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIsNone(T.read_pointer(proj))
        runs = [p.name for p in proj.path("runs").iterdir() if p.is_dir()]
        self.assertEqual(len(runs), 1)
        st = T.recover(proj, runs[0])
        self.assertEqual(st["state"], "interrupted")
        self.assertEqual(st["staged"], ["out.csv"])
        self.assertIn("never published", st["note"])

    def test_concurrent_writer_is_locked_out(self):
        proj = project(self.tmp)
        script = (
            "import sys, time; sys.path.insert(0, r'%s');"
            "import contract_v2 as C, txn as T;"
            "p=C.Project(r'%s'); l=T.Lock(p,'review:d1',timeout=5); l.acquire();"
            "print('locked', flush=True); time.sleep(2.5); l.release()"
            % (SCRIPTS, self.tmp))
        proc = subprocess.Popen([PYTHON, "-c", script], stdout=subprocess.PIPE,
                                text=True)
        try:
            line = proc.stdout.readline()
            self.assertIn("locked", line)
            with self.assertRaises(T.LockError):
                T.Lock(proj, "review:d1", timeout=0.2).acquire()
        finally:
            proc.kill()
            proc.wait(timeout=10)
        T.Lock(proj, "review:d1", timeout=1.0, stale_after=0.01).acquire().release()

    def test_stale_lock_from_dead_pid_is_reclaimed(self):
        proj = project(self.tmp)
        path = proj.path("locks", "x.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"pid": 999999, "at": time.time(), "run_id": "dead"},
                  open(path, "w", encoding="utf-8"))
        lock = T.Lock(proj, "x", timeout=0.5)
        lock.acquire()
        self.assertTrue(lock.taken)
        lock.release()

    def test_checkpoint_all_layers_must_match(self):
        proj = project(self.tmp)
        base = {"inputs": {"a": "h1"}, "code": {"c": "h2"},
                "rules": {"r": "h3"}, "environment": {"py": "3.12"},
                "review_version": "s1"}
        cp = C.make_record("checkpoint", "cp1", dict(
            step="model", inputs=base["inputs"], code=base["code"],
            rules=base["rules"], environment=base["environment"],
            review_version=base["review_version"]), producer=C.producer_for(
                "test", module_file=os.path.join(SCRIPTS, "contract_v2.py")))
        self.assertTrue(T.checkpoint_state(cp, base)["valid"])
        for layer in base:
            moved = dict(base)
            moved[layer] = ({"a": "other"} if isinstance(base[layer], dict)
                            else "other")
            res = T.checkpoint_state(cp, moved)
            self.assertFalse(res["valid"], layer)
            self.assertEqual(res["mismatches"][0]["layer"], layer)

    def test_recover_committed_run(self):
        proj = project(self.tmp)
        t = T.Transaction(proj)
        t.stage("o.csv", "x\n")
        t.commit()
        st = T.recover(proj, t.run_id)
        self.assertEqual(st["state"], "committed")
        self.assertTrue(st["published"])

    def test_cli_status_and_verify(self):
        from _helpers import run
        proj = project(self.tmp)
        t = T.Transaction(proj)
        t.stage("o.csv", "x\n")
        manifest = t.commit()
        out = run("txn.py", "--root", self.tmp, "status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(manifest["commit"], out.stdout)
        ok = run("txn.py", "--root", self.tmp, "verify", "--commit",
                 manifest["commit"])
        self.assertEqual(ok.returncode, 0, ok.stderr)
