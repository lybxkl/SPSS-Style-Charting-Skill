# -*- coding: utf-8 -*-
"""Tests for ``tools/acceptance_cards.py`` (A52 / A60).

The point of the tool is that a ``passed`` claim can be re-executed, so these
tests exercise the CLI through ``subprocess`` against a throw-away ledger: they
cover exit codes, the JSON summary and the field-level errors, not just
importable helpers.  Nothing here touches the real ledger under
``docs/implementation/`` — every case is written into ``TempCase.tmp``.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest

from _helpers import ROOT, TempCase

TOOL = os.path.join(ROOT, "tools", "acceptance_cards.py")
PYTHON = sys.executable

#: Batch table, duplicated on purpose: the test is the independent oracle, it
#: must not read the table it is checking out of the module under test.
BATCHES = {
    "M0": ("T01", "T02", "T03", "T37", "T39"),
    "M1": ("T04", "T05", "T06", "T07", "T38"),
    "M2": tuple(f"T{i:02d}" for i in range(8, 14)),
    "M3": ("T14", "T15"),
    "M4": tuple(f"T{i:02d}" for i in range(16, 23)),
    "M5": ("T23", "T24", "T25", "T40"),
    "M6": tuple(f"T{i:02d}" for i in range(26, 32)),
    "M7": tuple(f"T{i:02d}" for i in range(32, 37)),
}

EXPECTATION = "validate 退出码为 0，且打印的 JSON 里 passed 等于 2"
COMMAND = "python tools/acceptance_cards.py validate"


def digest(text: str) -> str:
    """Mirror of the documented ``expectation_sha256`` recipe."""
    return hashlib.sha256(text.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()


class AcceptanceCardsCase(TempCase):
    """A miniature repository with one ledger, 60 cards and 40 tasks."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.p("repo")
        for part in ("docs/implementation", "tests/fixtures", "logs", "tools"):
            os.makedirs(os.path.join(self.repo, *part.split("/")), exist_ok=True)
        self._seed_files()
        self.cards = {}
        for i in range(1, 61):
            cid = f"A{i:02d}"
            self.cards[cid] = {
                "id": cid,
                "scenario": f"场景 {cid} 的行为必须被实际执行",
                "primary_task": "T39",
                "linked_tasks": ["T39"],
                "result": "unassessed",
                "runs": [],
                "evidence": [],
                "note": None,
                "gap": "尚未执行：缺 fixture、步骤与执行回执",
            }
        self.cards["A52"] = self._complete_card("A52")
        self.cards["A60"] = self._complete_card("A60")
        self.tasks = {}
        for batch, ids in BATCHES.items():
            for tid in ids:
                self.tasks[tid] = {"id": tid, "phase": batch,
                                   "state": "implemented",
                                   "acceptance_cases": ["A52"]}
        self.save()

    # ------------------------------------------------------------------ setup
    def _seed_files(self) -> None:
        with open(os.path.join(self.repo, "tests", "fixtures", "a52_card.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"fixture": "A52"}, fh)
        with open(os.path.join(self.repo, "logs", "a52_run.log"), "w",
                  encoding="utf-8") as fh:
            fh.write(f"$ {COMMAND}\n{{'passed': 2, 'errors': []}}\nexit 0\n")
        from pathlib import Path
        production = Path(self.repo)/"tools/fixture_producer.py"
        production.write_text("# Synthetic execution-receipt contract fixture, not an integration run.\n", encoding="utf-8")
        bindings = {"tools/fixture_producer.py": hashlib.sha256(production.read_bytes()).hexdigest()}
        log = Path(self.repo)/"logs/a52_run.log"
        fixture = Path(self.repo)/"tests/fixtures/a52_card.json"
        receipt = {"producer": "tools/run_acceptance.py", "sources_unchanged": True, "result": "passed",
                   "started_at": "2026-11-14T12:00:00+08:00", "finished_at": "2026-11-14T12:05:00+08:00",
                   "command": ["python", "synthetic_contract_fixture.py"], "tests_run": 2,
                   "production_before": bindings, "production_after": bindings,
                   "oracle_files": {"tests/fixtures/a52_card.json": hashlib.sha256(fixture.read_bytes()).hexdigest()},
                   "execution_log": "a52_run.log", "execution_log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                   "tests": {"synthetic.A52": {"status": "passed"}, "synthetic.A60": {"status": "passed"}}}
        mapping_path = Path(self.repo)/"logs/map.json"
        mapping_path.write_text(json.dumps({"cases": {cid: {"test_ids": [f"synthetic.{cid}"],
            "scenario_sha256": digest(f"真实执行后才有结论：{cid}"), "expectation_sha256": digest(EXPECTATION)} for cid in ("A52", "A60")}}), encoding="utf-8")
        receipt["mapping"] = {"path": "logs/map.json", "sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest()}
        path = Path(self.repo)/"logs/execution.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        self.receipt_sha = hashlib.sha256(path.read_bytes()).hexdigest()

    def _complete_card(self, cid: str) -> dict:
        return {
            "id": cid,
            "scenario": f"真实执行后才有结论：{cid}",
            "primary_task": "T39",
            "linked_tasks": ["T39"],
            "fixture": "tests/fixtures/a52_card.json",
            "steps": [
                f"cd {self.repo}; {COMMAND}",
                "python -c \"import json,sys; d=json.load(sys.stdin); "
                "assert d['passed']==2\"",
            ],
            "expectation": EXPECTATION,
            "expectation_recorded_at": "2026-11-14T10:00:00+08:00",
            "implemented_at": "2026-11-14T12:00:00+08:00",
            "expectation_sha256": digest(EXPECTATION),
            "observed": "退出码 0，passed=2，errors=[]，stderr 为空",
            "environment": "Python 3.12.4 / unittest(stdlib) / Windows 11 22631",
            "evidence": ["logs/a52_run.log"],
            "execution_receipts": [{"path": "logs/execution.json", "sha256": self.receipt_sha}],
            "test_ids": [f"synthetic.{cid}"],
            "command": COMMAND,
            "runs": [{"at": "2026-11-14T12:05:00+08:00", "command": COMMAND,
                      "environment": "Python 3.12.4", "result": "passed"}],
            "result": "passed",
            "note": "命令实跑，输出与独立期望一致",
            "gap": None,
        }

    # ------------------------------------------------------------------ utils
    def save(self) -> None:
        with open(self.results, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "kind": "test",
                       "cases": self.cards}, fh, ensure_ascii=False, indent=1)
        with open(self.tasks_path, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "kind": "test",
                       "tasks": self.tasks}, fh, ensure_ascii=False, indent=1)

    @property
    def results(self) -> str:
        return os.path.join(self.repo, "docs", "implementation",
                            "ACCEPTANCE-RESULTS.json")

    @property
    def tasks_path(self) -> str:
        return os.path.join(self.repo, "docs", "implementation",
                            "TASK-STATUS.json")

    def run_tool(self, *args: str, cwd: str | None = None):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            [PYTHON, TOOL, *args, "--repo", self.repo],
            cwd=cwd or self.repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env, timeout=180,
        )

    def payload(self, proc) -> dict:
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:      # pragma: no cover - diagnosability
            self.fail(f"stdout 不是 JSON：\n{proc.stdout}\nstderr:\n{proc.stderr}")

    def fields(self, proc) -> list[str]:
        return [str(e.get("field", "")) for e in self.payload(proc).get("errors", [])]

    # ------------------------------------------------------------------- tests
    def test_complete_card_validates(self):
        proc = self.run_tool("validate")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = self.payload(proc)
        self.assertEqual(data["passed"], 2)
        self.assertEqual(data["checked"], 2)
        self.assertEqual(data["errors"], [])

    def test_source_only_evidence_cannot_claim_passed(self):
        self.cards["A52"].pop("execution_receipts")
        self.save()
        result = self.run_tool("validate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("execution_receipts", self.fields(result))

    def test_mismatched_scenario_test_mapping_is_rejected(self):
        self.cards["A52"]["test_ids"] = ["synthetic.A60"]
        self.save()
        result = self.run_tool("validate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("execution_receipts", self.fields(result))

    def test_execution_for_old_program_version_is_rejected(self):
        from pathlib import Path
        (Path(self.repo)/"tools/fixture_producer.py").write_text("# changed after execution\n", encoding="utf-8")
        result = self.run_tool("validate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("execution_receipts", self.fields(result))

    def test_missing_evidence_file_is_named(self):
        self.cards["A52"]["evidence"] = ["logs/not_here.log"]
        self.save()
        proc = self.run_tool("validate")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        data = self.payload(proc)
        message = " ".join(e["message"] for e in data["errors"])
        self.assertIn("logs/not_here.log", message)
        self.assertIn("文件不存在", message)
        self.assertIn("evidence[0]", self.fields(proc))

    def test_prose_only_steps_is_error(self):
        self.cards["A52"]["steps"] = ["按验收卡逐项执行并确认"]
        self.save()
        proc = self.run_tool("validate")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("steps", self.fields(proc))
        self.assertIn("描述性文字", " ".join(
            e["message"] for e in self.payload(proc)["errors"]))

    def test_empty_expectation_is_error(self):
        self.cards["A52"]["expectation"] = ""
        self.save()
        proc = self.run_tool("validate")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("expectation", self.fields(proc))
        self.assertEqual(self.payload(proc)["passed"], 1)   # A60 still clean

    def test_expectation_recorded_after_implementation_fails_order_check(self):
        self.cards["A52"]["expectation_recorded_at"] = "2026-11-14T13:00:00+08:00"
        self.save()
        proc = self.run_tool("order-check")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("expectation", self.fields(proc))
        self.assertIn("不早于", " ".join(
            e["message"] for e in self.payload(proc)["errors"]))

    def test_rewritten_expectation_is_detected(self):
        self.cards["A52"]["expectation"] = "实现完成之后才补写的期望"
        self.save()
        proc = self.run_tool("order-check")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("expectation_sha256", self.fields(proc))
        self.assertIn("改写", " ".join(
            e["message"] for e in self.payload(proc)["errors"]))

    def test_batch_gate_blocks_planned_task_and_recovers(self):
        proc = self.run_tool("batch-gate", "--batch", "M1")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(self.payload(proc)["passed"])

        self.tasks["T05"]["state"] = "planned"
        self.save()
        proc = self.run_tool("batch-gate", "--batch", "M1")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        data = self.payload(proc)
        self.assertFalse(data["passed"])
        self.assertEqual([b["task"] for b in data["blockers"]], ["T05"])
        self.assertIn("planned", data["blockers"][0]["reason"])

        self.tasks["T05"]["state"] = "implemented"
        self.save()
        self.assertEqual(self.run_tool("batch-gate", "--batch", "M1").returncode, 0)

    def test_later_partial_batch_does_not_block_earlier_batch(self):
        self.tasks["T08"]["state"] = "partial"      # M2, later
        self.tasks["T09"]["state"] = "planned"      # M2, later
        self.cards["A11"]["result"] = "failed"      # M2 scenario
        self.save()
        self.assertEqual(self.run_tool("batch-gate", "--batch", "M1").returncode, 0)
        later = self.run_tool("batch-gate", "--batch", "M2")
        self.assertEqual(later.returncode, 2, later.stdout)
        self.assertIn("M2", self.payload(later)["blocked_by"])

    def test_render_lists_all_cards_and_expectation_field(self):
        out = self.p("out", "ACCEPTANCE-CARDS.md")
        proc = self.run_tool("render", "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        for i in range(1, 61):
            self.assertIn(f"A{i:02d}", text)
        self.assertIn("独立期望", text)
        self.assertIn(EXPECTATION, text)
        self.assertIn("尚未执行", text)             # the gap of the other 58
        self.assertEqual(self.payload(proc)["cards"], 60)

    def test_evidence_must_stay_inside_repository(self):
        self.cards["A52"]["evidence"] = ["../outside.txt"]
        self.save()
        proc = self.run_tool("validate")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("逃出仓库根", " ".join(
            e["message"] for e in self.payload(proc)["errors"]))

        self.cards["A52"]["evidence"] = [
            os.path.join(self.repo, "logs", "a52_run.log")]
        self.save()
        proc = self.run_tool("validate")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("绝对路径", " ".join(
            e["message"] for e in self.payload(proc)["errors"]))

    def test_unassessed_without_gap_is_error(self):
        self.cards["A01"]["gap"] = None
        self.save()
        proc = self.run_tool("validate")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("gap", self.fields(proc))


if __name__ == "__main__":
    unittest.main()
