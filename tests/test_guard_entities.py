# -*- coding: utf-8 -*-
"""Original-material protection (A01) and entity identity (A18).

A01: a rewritten/deleted original is detected and restored, a hard link into the
frozen tree is refused, an output directory overlapping the sources is refused,
and a failed guard does not produce a success receipt.
A18: homonyms are not merged, aliases are, and a similarity heuristic never
forces a match on masked identifiers.
"""
import hashlib
import os
import stat

from _helpers import TempCase, write_csv

import entities as E
import source_guard as SG


class TestSourceGuard(TempCase):
    def _tree(self):
        root = self.p("materials")
        os.makedirs(root)
        with open(os.path.join(root, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("original content\n")
        with open(os.path.join(root, "b.txt"), "w", encoding="utf-8") as fh:
            fh.write("second file\n")
        return root

    def test_rewritten_and_deleted_originals_are_restored(self):
        root = self._tree()
        guard = SG.SourceGuard(root, self.p("proj"))
        guard.freeze()
        for name in ("a.txt", "b.txt"):
            os.chmod(os.path.join(root, name), stat.S_IWRITE | stat.S_IREAD)
        with open(os.path.join(root, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("tampered\n")
        os.unlink(os.path.join(root, "b.txt"))
        result = guard.finish()
        self.assertEqual(len(result["restored"]), 2, result)
        self.assertEqual(open(os.path.join(root, "a.txt"),
                              encoding="utf-8").read(), "original content\n")
        self.assertEqual(open(os.path.join(root, "b.txt"),
                              encoding="utf-8").read(), "second file\n")
        self.assertEqual(result["errors"], [])

    def test_hardlink_into_the_frozen_tree_is_forbidden(self):
        root = self._tree()
        guard = SG.SourceGuard(root, self.p("proj"))
        guard.freeze()
        out = self.p("out")
        os.makedirs(out)
        link = os.path.join(out, "sneaky.txt")
        try:
            os.link(os.path.join(root, "a.txt"), link)
        except OSError:
            self.skipTest("this filesystem does not support hard links")
        self.assertTrue(guard.forbidden(link))
        self.assertFalse(guard.forbidden(os.path.join(out, "fresh.txt")))

    def test_overlapping_output_directory_is_refused(self):
        root = self._tree()
        with self.assertRaises(ValueError):
            SG.SourceGuard(root, os.path.join(root, "project"))
        # a project root that *contains* the sources would put generated files
        # next to the originals; the guard refuses it
        with self.assertRaises(ValueError):
            SG.SourceGuard(root, root)

    def test_added_files_are_reported_not_silently_ignored(self):
        root = self._tree()
        guard = SG.SourceGuard(root, self.p("proj"))
        guard.freeze()
        with open(os.path.join(root, "new.txt"), "w", encoding="utf-8") as fh:
            fh.write("added later\n")
        result = guard.finish()
        self.assertEqual(len(result["added"]), 1)
        self.assertTrue(result["added"][0].endswith("new.txt"))

    def test_no_success_receipt_when_restore_fails(self):
        root = self._tree()
        guard = SG.SourceGuard(root, self.p("proj"))
        guard.freeze()
        backup = guard.records[0]["backup"]
        target = guard.records[0]["path"]
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("tampered\n")
        os.unlink(backup)
        result = guard.finish()
        self.assertTrue(result["errors"], "a failed restore must be reported")
        self.assertFalse(any(r.endswith("a.txt") for r in result["restored"]))


class TestEntityIdentity(TempCase):
    def setUp(self):
        super().setUp()
        import contract_v2
        self.proj = contract_v2.Project(self.tmp)
        self.reg = E.Entities(self.proj)

    def test_homonyms_are_not_merged(self):
        a = self.reg.register("person", "A001",
                              attributes={"name": "张伟"},
                              sources=[{"doc": "i1"}])
        b = self.reg.register("person", "A002",
                              attributes={"name": "张伟"},
                              sources=[{"doc": "i2"}])
        self.assertNotEqual(a["id"], b["id"])
        names = [r["id"] for r in self.proj.read("entity")]
        self.assertEqual(len(set(names)), 2)

    def test_alias_merges_into_the_same_entity(self):
        a = self.reg.register("person", "A001",
                              attributes={"name": "张伟"},
                              sources=[{"doc": "i1"}])
        b = self.reg.register("person", "A001",
                              attributes={"name": "张伟"},
                              sources=[{"doc": "i2"}], aliases=["小张"])
        self.assertEqual(a["id"], b["id"])
        latest = self.proj.latest("entity", a["id"])
        self.assertIn("小张", latest["data"]["aliases"])
        self.assertEqual(len([r for r in self.proj.read("entity")
                              if r["id"] == a["id"]]), 2)

    def test_conflicting_stable_id_is_recorded_not_hidden(self):
        a = self.reg.register("person", "A001",
                              attributes={"name": "张伟"},
                              sources=[{"doc": "i1"}])
        b = self.reg.register("person", "A001",
                              attributes={"name": "张伟（别名）"},
                              sources=[{"doc": "i2"}])
        self.assertEqual(a["id"], b["id"])
        latest = self.proj.latest("entity", a["id"])
        self.assertTrue(latest["data"].get("conflicts"))

    def test_masked_identifiers_are_not_matched_by_similarity(self):
        a = self.reg.register("person", "2020-001",
                              attributes={"name": "李*"},
                              sources=[{"doc": "i1"}])
        b = self.reg.register("person", "2020-002",
                              attributes={"name": "李*"},
                              sources=[{"doc": "i2"}])
        self.assertNotEqual(a["id"], b["id"])
        # no relation was invented between them
        self.assertEqual(self.proj.read("relation"), [])
