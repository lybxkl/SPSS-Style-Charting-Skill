# -*- coding: utf-8 -*-
"""table_map/doc_map 命名源：脚本自动登记、合并不丢条目、目录闸门端到端。"""
from __future__ import annotations

import json
import os
import unittest

from _helpers import TempCase, run, write_csv


class NameMapCase(TempCase):
    def read_map(self, name):
        path = self.p("output", name)
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def put_map(self, name, entries):
        path = self.p("output", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False)


class TestReportTables(NameMapCase):
    def test_reports_register_titled_maps(self):
        data = write_csv(self.p("data", "analysis.csv"),
                         ["id", "charge", "year"],
                         [["1", "甲", 2020], ["2", "乙", 2021]])
        proc = run("report_tables.py", "--dataset", data,
                   "--out", "output/reports", cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tmap = self.read_map("table_map.json")
        self.assertTrue(tmap)
        titles = {os.path.basename(it["file"]): it["title"] for it in tmap}
        self.assertEqual(titles.get("descriptive_stats.csv"), "描述统计")
        self.assertEqual(titles.get("frequency_tables.csv"), "频数表")
        dmap = self.read_map("doc_map.json")
        self.assertTrue(any(it["title"] == "数据报告" for it in dmap))


class TestAssemble(NameMapCase):
    def test_manuscript_tables_merge_without_losing_entries(self):
        self.put_map("table_map.json",
                     [{"tag": "报表", "title": "描述统计",
                       "file": "output/reports/descriptive_stats.csv"}])
        write_csv(self.p("t.csv"), ["charge", "n"], [["甲", 976]])
        spec = self.p("spec.json")
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"blocks": [
                {"type": "title", "text": "某研究"},
                {"type": "table", "csv": "t.csv", "caption": "罪名结构"},
            ]}, fh, ensure_ascii=False)
        proc = run("assemble_manuscript.py", "--spec", spec,
                   "--out", "output/manuscript.docx", cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tmap = self.read_map("table_map.json")
        titles = {it["title"] for it in tmap}
        self.assertIn("描述统计", titles)  # 先登记的报表条目不被覆盖丢失
        self.assertIn("罪名结构", titles)
        entry = next(it for it in tmap if it["title"] == "罪名结构")
        self.assertEqual(entry["tag"], "表1")


class TestReviewPack(NameMapCase):
    def test_review_pack_registers_doc_map(self):
        data = write_csv(self.p("data", "analysis.csv"),
                         ["id", "in_analysis"], [["1", 1], ["2", 0]])
        proc = run("review_pack.py", "--data", data,
                   "--out", "output/review/review_pack.md", cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        dmap = self.read_map("doc_map.json")
        self.assertTrue(any(it["title"] == "复核包"
                            and it["file"].endswith("review_pack.md") for it in dmap))


class TestLayoutGateEndToEnd(NameMapCase):
    def test_gate_report_written_and_stray_blocked(self):
        write_csv(self.p("output", "reports", "descriptive_stats.csv"),
                  ["a"], [["1"]])
        self.put_map("table_map.json",
                     [{"tag": "报表", "title": "描述统计",
                       "file": "output/reports/descriptive_stats.csv"}])
        proc = run("layout_conformance.py", "--root", ".", cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(self.p("output", "qa", "layout_conformance.json"),
                  encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertEqual(report["error_count"], 0)
        self.assertTrue(any(g["key"] == "output/tables" for g in report["groups"]))

        os.makedirs(self.p("output", "custom"))
        write_csv(self.p("output", "custom", "x.csv"), ["a"], [["1"]])
        proc = run("layout_conformance.py", "--root", ".", cwd=self.tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("undeclared", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()