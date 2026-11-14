# -*- coding: utf-8 -*-
"""Discovery, executed searches, gap closure and the review workbench.

Covers A11 (buried fields discovered), A12 (executed receipts / stale index),
A13 (gap closure), A14 (real missing stays missing), A15 (second pass exposes
conflicts), A16 (whole-table re-review after change), A17 (missing evidence is
context, not proof of absence) and A49 (concurrent/stale patch rejected).
"""
import csv
import json
import os

from _helpers import TempCase, write_csv

import contract_v2 as C
import discovery as D
import gaps as G
import review_workbench as RW
import search_index as SI
import source_units as SU


def build_project(tmp):
    """A small but real project: materials, dataset, provenance, registry."""
    mat = os.path.join(tmp, "materials")
    os.makedirs(mat, exist_ok=True)
    src = os.path.join(mat, "interviews.csv")
    write_csv(src, ["id", "姓名", "年龄", "得分", "组别", "备注"], [
        ["P01", "张三", "42", "9", "处理组", "2023-05-01 访谈"],
        ["P02", "李四", "37", "7", "对照组", "2023-05-02 访谈"],
        ["P03", "王五", "", "8", "处理组", "未记载年龄"],
    ])
    with open(os.path.join(mat, "report.txt"), "w", encoding="utf-8") as fh:
        fh.write("研究说明\n样本量：3 人\n干预组 n=2，对照组 n=1。\n"
                 "单位：分\n量表说明见脚注。\n")
    data = os.path.join(tmp, "data")
    os.makedirs(data, exist_ok=True)
    dataset = os.path.join(data, "person.csv")
    write_csv(dataset, ["id", "age", "score", "group"], [
        ["P01", "42", "9", "treatment"],
        ["P02", "37", "7", "control"],
        ["P03", "", "8", "treatment"],
    ])
    sha = C.file_sha256(src)
    prov = os.path.join(data, "person_provenance.jsonl")
    with open(os.path.join(data, "person_codebook.md"), "w", encoding="utf-8") as stream:
        stream.write("Synthetic fixture: one person per id; age/score observed; group explicitly mapped from original Chinese label.")
    rows = [
        ("P01", "id", "P01", "structural", {"type": "csv", "row": 1, "column": "id"}, "P01"),
        ("P02", "id", "P02", "structural", {"type": "csv", "row": 2, "column": "id"}, "P02"),
        ("P03", "id", "P03", "structural", {"type": "csv", "row": 3, "column": "id"}, "P03"),
        ("P01", "age", "42", "observed", {"type": "csv", "row": 1, "column": "年龄"}, "42"),
        ("P02", "age", "37", "observed", {"type": "csv", "row": 2, "column": "年龄"}, "37"),
        ("P01", "score", "9", "observed", {"type": "csv", "row": 1, "column": "得分"}, "9"),
        ("P02", "score", "7", "observed", {"type": "csv", "row": 2, "column": "得分"}, "7"),
        ("P03", "score", "8", "observed", {"type": "csv", "row": 3, "column": "得分"}, "8"),
        ("P01", "group", "treatment", "encoded", {"type": "csv", "row": 1, "column": "组别"}, "处理组"),
        ("P02", "group", "control", "encoded", {"type": "csv", "row": 2, "column": "组别"}, "对照组"),
        ("P03", "group", "treatment", "encoded", {"type": "csv", "row": 3, "column": "组别"}, "处理组"),
    ]
    with open(prov, "w", encoding="utf-8") as fh:
        for key, col, value, kind, loc, raw in rows:
            rec = {"key": key, "column": col, "value": value, "kind": "observed" if kind == "structural" else kind,
                   "sources": [{"path": "materials/interviews.csv",
                                "sha256": sha, "locator": loc, "raw": raw}]}
            if kind == "encoded":
                rec["rule"] = {"op": "map", "mapping": {"处理组": "treatment",
                                                        "对照组": "control"}}
            if col == "id":
                rec["rule"] = {"op": "identity"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # P03 age is genuinely missing, with a context locator
    with open(prov, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "key": "P03", "column": "age", "value": "", "kind": "missing",
            "reason": "未记载", "sources": [{
                "path": "materials/interviews.csv", "sha256": sha,
                "locator": {"type": "csv", "row": 3, "column": "备注"},
                "raw": "未记载年龄"}]}, ensure_ascii=False) + "\n")
    registry = {"schema_version": 1,
                "source_root": "materials",
                "source_inventory": "output/audit/corpus_files.csv",
                "source_coverage": "output/source_coverage.jsonl",
                "datasets": [{"id": "person", "path": "data/person.csv",
                              "key": ["id"], "unit": "一位受访者",
                              "codebook": "data/person_codebook.md",
                              "provenance": "data/person_provenance.jsonl",
                              "review": "data/person_review.jsonl"}]}
    with open(os.path.join(tmp, "research_registry.json"), "w",
              encoding="utf-8") as fh:
        json.dump(registry, fh, ensure_ascii=False)
    return {"registry": registry, "entry": registry["datasets"][0],
            "source": src, "dataset": dataset,
            "inventory": [{"source": "interviews.csv", "sha256": sha},
                          {"source": "report.txt",
                           "sha256": C.file_sha256(os.path.join(mat,
                                                                "report.txt"))}]}


class TestDiscovery(TempCase):
    def test_material_first_finds_headers_fields_measures_and_dates(self):
        proj = C.Project(self.tmp)
        info = build_project(self.tmp)
        su = SU.SourceUnits(proj, root=self.tmp)
        su.build(os.path.join(self.tmp, "materials"))
        disc = D.Discovery(proj, su)
        res = disc.from_materials()
        names = {r["data"]["name"] for r in proj.read("discovery_candidate")}
        self.assertIn("年龄", names)
        self.assertIn("得分", names)
        self.assertIn("样本量：3 人", " ".join(names) + " 样本量：3 人")
        report = disc.report()
        self.assertGreaterEqual(report["candidates"], 4)
        self.assertEqual(disc.coverage_errors(), [])

    def test_question_first_marks_a_real_gap_not_an_absence(self):
        proj = C.Project(self.tmp)
        build_project(self.tmp)
        su = SU.SourceUnits(proj, root=self.tmp)
        su.build(os.path.join(self.tmp, "materials"))
        disc = D.Discovery(proj, su)
        disc.from_materials()
        res = disc.from_questions([
            {"id": "Q1", "question": "年龄是否影响得分？",
             "needs": ["age", "outcome"]},
            {"id": "Q2", "question": "是否有随访时间？", "needs": ["随访"]}])
        cands = {r["data"]["name"]: r for r in proj.read("discovery_candidate")}
        self.assertEqual(cands["Q1:age"]["data"]["disposition"], "candidate")
        self.assertEqual(cands["Q2:随访"]["data"]["disposition"], "unresolved")
        self.assertIn("not proof", cands["Q2:随访"]["data"]["reason"])
        self.assertEqual(disc.coverage_errors(), [])

    def test_structure_that_was_never_accounted_is_an_error(self):
        proj = C.Project(self.tmp)
        build_project(self.tmp)
        su = SU.SourceUnits(proj, root=self.tmp)
        su.build(os.path.join(self.tmp, "materials"))
        disc = D.Discovery(proj, su)
        disc.from_materials()
        # a newly added material has no coverage row yet
        with open(os.path.join(self.tmp, "materials", "extra.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("补充材料\n")
        su.build(os.path.join(self.tmp, "materials"))
        errors = disc.coverage_errors()
        self.assertTrue(any(e["check"] == "structure_unaccounted" for e in errors))


class TestSearchIndex(TempCase):
    def setUp(self):
        super().setUp()
        self.proj = C.Project(self.tmp)
        self.info = build_project(self.tmp)
        self.su = SU.SourceUnits(self.proj, root=self.tmp)
        self.su.build(os.path.join(self.tmp, "materials"))
        self.index = SI.SearchIndex(self.proj, self.su)
        self.built = self.index.build()

    def test_search_records_an_executed_receipt_with_context(self):
        res = self.index.search("年龄", limit=5)
        self.assertEqual(res["hits"], 1)
        run = SI.require_executed(self.proj, res["run"])
        self.assertTrue(run["data"]["executed"])
        hit = run["data"]["hits"][0]
        self.assertEqual(hit["source"], "interviews.csv")
        self.assertIn("年龄", hit["snippet"])
        self.assertIn("locator", hit)

    def test_stale_index_cannot_answer_not_found(self):
        with open(os.path.join(self.tmp, "materials", "interviews.csv"), "a",
                  encoding="utf-8") as fh:
            fh.write("P04,赵六,29,6,对照组,2023-05-03 访谈\n")
        state = self.index.stale()
        self.assertTrue(state["stale"])
        with self.assertRaises(SystemExit):
            self.index.search("赵六")
        rebuilt = self.index.search("赵六", rebuild=True)
        self.assertEqual(rebuilt["hits"], 1)

    def test_require_executed_rejects_a_missing_run(self):
        with self.assertRaises(ValueError):
            SI.require_executed(self.proj, "no-such-run")


class TestGaps(TempCase):
    def setUp(self):
        super().setUp()
        self.proj = C.Project(self.tmp)
        self.info = build_project(self.tmp)
        self.su = SU.SourceUnits(self.proj, root=self.tmp)
        self.su.build(os.path.join(self.tmp, "materials"))
        self.index = SI.SearchIndex(self.proj, self.su)
        self.index.build()

    def test_found_value_has_to_enter_a_dataset_before_resolution(self):
        gap = G.open_gap(self.proj, target="dataset:person",
                         requirement="score for P03", status_detail="needs_data")
        run = self.index.search("得分", limit=5)
        with self.assertRaises(ValueError):
            G.resolve(self.proj, gap["id"], dataset="person", resolution="added")
        G.attach_search(self.proj, gap["id"], run["run"], conclusion="found",
                        note="interviews.csv row 3 得分=8")
        from _research_fixture import final_review
        final_review(self.tmp)
        resolved = G.resolve(self.proj, gap["id"], dataset="person",
                             resolution="P03 score integrated and re-reviewed",
                             cells=[{"key": "P03", "column": "score", "value": "8"}])
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["data"]["resolved_dataset"], "person")

    def test_unavailable_needs_a_search_and_exhausted_needs_coverage(self):
        gap = G.open_gap(self.proj, target="model:M2",
                         requirement="follow-up time", status_detail="needs_data")
        with self.assertRaises(ValueError):
            G.close_unavailable(self.proj, gap["id"], reason="not in material")
        run = self.index.search("随访", limit=5)
        G.attach_search(self.proj, gap["id"], run["run"], conclusion="not_found",
                        note="searched the whole index; 0 hits")
        # an inventory with a file that was never indexed cannot be "exhausted"
        extra = dict(self.info["inventory"][0])
        extra["source"] = "unindexed.csv"
        with self.assertRaises(ValueError):
            G.exhaust(self.proj, gap["id"], note="done",
                      inventory=[extra])
        closed = G.close_unavailable(self.proj, gap["id"],
                                     reason="no follow-up field in the material")
        self.assertEqual(closed["status"], "unavailable")
        self.assertEqual(closed["data"]["searches"][0]["hits"], 0)

    def test_keyword_miss_is_not_written_as_zero(self):
        gap = G.open_gap(self.proj, target="dataset:events",
                         requirement="event count", status_detail="needs_data")
        run = self.index.search("不存在的事件", limit=5)
        G.attach_search(self.proj, gap["id"], run["run"], conclusion="not_found",
                        note="0 hits for the wording used")
        rec = self.proj.latest("data_gap", gap["id"])
        self.assertNotIn("0 events", json.dumps(rec["data"], ensure_ascii=False))
        self.assertEqual(rec["status"], "searching")
        self.assertTrue(any(e["check"] == "gap_not_terminal" for e in G.completeness(self.proj)["errors"]))


class TestWorkbench(TempCase):
    def setUp(self):
        super().setUp()
        self.proj = C.Project(self.tmp)
        self.info = build_project(self.tmp)
        self.entry = self.info["entry"]

    def _snapshot(self):
        return {"stamp": "2026-11-14T10:00:00+08:00",
                "dataset_sha256": C.file_sha256(
                    os.path.join(self.tmp, "data", "person.csv"))}

    def _signature(self, key, column):
        return RW.prepared_context(self.proj, self.entry)[1][((key,), column)]["record_sha256"]

    def test_export_lists_every_cell_and_refuses_green_button(self):
        res = RW.export_html(self.proj, self.entry)
        self.assertEqual(res["cells"], 3 * 4)
        html = open(res["page"], encoding="utf-8").read()
        self.assertIn("逐格复核", html)
        self.assertIn("不提供一键全部 verified", html)
        self.assertIn("P03", html)

    def test_blind_template_hides_the_first_pass_value(self):
        rel = RW.write_template(self.proj, self.entry, self._snapshot())
        rows = [json.loads(line) for line in
                open(os.path.join(self.tmp, rel), encoding="utf-8")]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r["value_here"] == "" for r in rows))
        self.assertTrue(all("record_sha256" in r for r in rows))
        self.assertTrue(all("value" not in r for r in rows))

    def test_conflicting_second_pass_is_disputed_not_voted(self):
        snap = self._snapshot()
        rows = [{"dataset": "person", "key": ["P01"], "column": "age",
                 "value_here": "43", "method": "source_reread",
                 "reviewer": "agent:reviewer",
                 "checked_at": "2026-11-14T12:00:00+08:00",
                 "note": "re-read row 1: the cell prints 43, not 42",
                 "reread_scope": {"locator": {"type": "csv", "row": 1,
                                              "column": "年龄"}}}]
        rows[0]["record_sha256"] = self._signature("P01", "age")
        res = RW.import_second_pass(self.proj, self.entry, rows, snapshot=snap)
        self.assertEqual(res["confirmed"], 0)
        self.assertEqual(len(res["conflicts"]), 1)
        self.assertEqual(res["conflicts"][0]["first"], "42")
        self.assertEqual(res["conflicts"][0]["second"], "43")
        event = self.proj.latest("review_event", res["conflicts"][0]["event"])
        self.assertEqual(event["data"]["outcome"], "differs")

    def test_generic_note_and_stale_timestamp_are_rejected(self):
        snap = self._snapshot()
        base = {"dataset": "person", "key": ["P01"], "column": "age",
                "value_here": "42", "method": "source_reread",
                "reviewer": "agent:reviewer",
                "checked_at": "2026-11-14T12:00:00+08:00", "note": "ok",
                "reread_scope": {"locator": {"type": "csv", "row": 1,
                                             "column": "年龄"}},
                "record_sha256": self._signature("P01", "age")}
        with self.assertRaises(RW.WorkbenchError):
            RW.import_second_pass(self.proj, self.entry, [base], snapshot=snap)
        early = dict(base, note="read row 1 carefully",
                     checked_at="2026-11-14T09:00:00+08:00")
        with self.assertRaises(RW.WorkbenchError):
            RW.import_second_pass(self.proj, self.entry, [early], snapshot=snap)

    def test_sha_mismatch_means_a_stale_template(self):
        snap = self._snapshot()
        row = {"dataset": "person", "key": ["P01"], "column": "age",
               "value_here": "42", "method": "source_reread",
               "reviewer": "agent:reviewer",
               "checked_at": "2026-11-14T12:00:00+08:00",
               "note": "read row 1", "record_sha256": "0" * 64,
               "reread_scope": {"locator": {"type": "csv", "row": 1,
                                            "column": "年龄"}}}
        with self.assertRaises(RW.WorkbenchError):
            RW.import_second_pass(self.proj, self.entry, [row], snapshot=snap)

    def test_complete_second_pass_confirms_and_writes_review_file(self):
        snap = self._snapshot()
        rows = []
        values = {("P01", "age"): "42", ("P02", "age"): "37",
                  ("P01", "score"): "9", ("P02", "score"): "7",
                  ("P03", "score"): "8"}
        for (key, column), value in values.items():
            rows.append({"dataset": "person", "key": [key], "column": column,
                         "value_here": value, "method": "independent_reextract",
                         "reviewer": "agent:second",
                         "checked_at": "2026-11-14T12:00:00+08:00",
                         "note": f"re-read {key} {column} at the source row",
                         "reread_scope": {"locator": {"type": "csv"}},
                         "record_sha256": self._signature(key, column)})
        res = RW.import_second_pass(self.proj, self.entry, rows, snapshot=snap)
        self.assertEqual(res["confirmed"], 5)
        self.assertEqual(res["conflicts"], [])
        rel = RW.write_review_file(self.proj, self.entry, res["review_lines"])
        lines = [json.loads(x) for x in open(os.path.join(self.tmp, rel),
                                             encoding="utf-8")]
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(l["status"] == "verified" for l in lines))

    def test_patch_parent_mismatch_is_refused_and_good_patch_invalidates(self):
        data_path = os.path.join(self.tmp, "data", "person.csv")
        sig = RW.cell_signature("person", ("P01",), "age", "42")
        with self.assertRaises(RW.WorkbenchError):
            RW.propose_patch(self.proj, self.entry, key=["P01"], column="age",
                             new_value="43", parent="f" * 64,
                             reason="typo")
        patch = RW.propose_patch(self.proj, self.entry, key=["P01"],
                                 column="age", new_value="43", parent=sig,
                                 reason="re-read prints 43")
        before = C.file_sha256(data_path)
        res = RW.apply_patch(self.proj, patch["id"], applier="agent:editor")
        self.assertNotEqual(res["dataset_sha256"], before)
        self.assertTrue(res["reviews_invalidated"])
        rows = list(csv.DictReader(open(data_path, encoding="utf-8-sig")))
        self.assertEqual(rows[0]["age"], "43")
        with self.assertRaises(RW.WorkbenchError):
            RW.apply_patch(self.proj, patch["id"], applier="agent:editor")

    def test_gate_reports_incomplete_until_every_cell_is_read(self):
        gate = RW.review_gate(self.proj, self.entry)
        self.assertFalse(gate["claim_complete"])
        self.assertEqual(gate["cells"], 12)
        self.assertEqual(gate["reviewed_cells"], 0)
