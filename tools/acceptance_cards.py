#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Make the acceptance ledger executable, and prove when it is only prose.

``docs/implementation/ACCEPTANCE-RESULTS.json`` claims 44 scenarios are
``passed``.  A claim is only worth something if somebody else can redo it:
a fixture, the commands actually run, an expectation frozen *before* the
implementation, the observed values, the environment, and evidence files that
exist on disk.  This tool checks exactly that and refuses to soften the verdict
(``unassessed`` is not a pass, ``--force`` does not exist).

    python tools/acceptance_cards.py validate
    python tools/acceptance_cards.py render
    python tools/acceptance_cards.py batch-gate --batch M2
    python tools/acceptance_cards.py order-check
    python tools/acceptance_cards.py drift

Exit codes: 0 = clean, 2 = violations.  Each subcommand prints one JSON object
on stdout so the result can be diffed between runs.

Field sources (deliberately narrow)
-----------------------------------
A ``passed`` card must carry ``fixture`` / ``steps`` / ``expectation`` /
``observed`` / ``environment`` / ``evidence`` / ``command`` as *top-level*
fields.  The single documented exception is ``command`` and ``environment``:
``tools/impl_ledger.py accept --command/--env`` stores them inside ``runs[]``,
so the last run entry counts as the same fact.  A design-phase ``fixture_spec``
("已知哈希原件，注入…") is NOT accepted as ``fixture`` — a description of what
the fixture should be is precisely the "写清楚就行" substitution A52 forbids.

``expectation_sha256``
----------------------
``sha256(expectation.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()``
— i.e. one 64-char lowercase hex digest of the expectation text with CRLF
normalised and outer whitespace stripped.  Any later edit to the text changes
the digest, which is how A60's "先期望后实现" is made falsifiable.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_REPO = TOOL_DIR.parent

#: Batch table from docs/RESEARCH-PIPELINE-ENHANCEMENT-PLAN-2026-11-14.md §6.
BATCHES: dict[str, tuple[str, ...]] = {
    "M0": ("T01", "T02", "T03", "T37", "T39"),
    "M1": ("T04", "T05", "T06", "T07", "T38"),
    "M2": tuple(f"T{i:02d}" for i in range(8, 14)),
    "M3": ("T14", "T15"),
    "M4": tuple(f"T{i:02d}" for i in range(16, 23)),
    "M5": ("T23", "T24", "T25", "T40"),
    "M6": tuple(f"T{i:02d}" for i in range(26, 32)),
    "M7": tuple(f"T{i:02d}" for i in range(32, 37)),
}
BATCH_ORDER: tuple[str, ...] = tuple(BATCHES)
GATE_STATES = ("implemented", "verified")

KNOWN_RESULTS = ("unassessed", "passed", "failed", "not_applicable", "blocked",
                 "partial")

VACUOUS = {
    "", "-", "--", "—", "n/a", "na", "none", "null", "nil", "tbd", "todo",
    "?", "？", "待定", "无", "见上", "同上", "略",
}

HINTS = {
    "fixture": "原件/fixture 路径或明确的 synthetic 说明",
    "steps": "≥1 条实际命令/操作，不能只有一句描述",
    "expectation": "独立期望，写明值/行为，且早于实现记录",
    "observed": "实际观察到的数值/状态/差异",
    "environment": "解释器、关键库版本或提供方",
    "evidence": "≥1 个真实存在的文件路径（仓库相对）",
    "command": "实际执行的命令",
    "note": "判定依据（passed 时不能为空）",
    "gap": "未核时缺什么（unassessed 必填）",
}

#: A step is "executable" only if it carries a command-shaped token.  Chinese
#: prose such as "按验收卡逐项执行并确认" has none of these and is rejected.
_EXEC_HINT = re.compile(
    r"(?:^|[\s;&|(])(?:python3?|py|pytest|unittest|pip|node|npm|pnpm|pwsh|"
    r"powershell|cmd|bash|sh|git|cd|mkdir|copy|cp|move|del|rm|ffmpeg|soffice|"
    r"libreoffice)\b"
    r"|--?[A-Za-z][\w-]*"
    r"|[A-Za-z0-9_.-]*[/\\][\w.-]+"
    r"|\.[A-Za-z]{2,5}\b"
    r"|[A-Za-z_]\w*\(",
    re.I,
)

_SYNTHETIC = re.compile(r"synthetic|合成|人工构造|构造的|fixture 内生成", re.I)

#: file-ish token: "a/b/c.json", "run.log", "docs/x"
_PATH_TOKEN = re.compile(r"(?:[\w.~-]*[/\\][\w.~/-]+)|(?:[\w.-]+\.[A-Za-z0-9]{1,6})")

_WIN_ABS = re.compile(r"^(?:[A-Za-z]:|[\\/])")

PROMPT_FIRST_CASE = "A60"


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(
        timespec="seconds")


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def _die(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _err(case_id: str, field: str, message: str) -> dict:
    return {"case": case_id, "field": field, "message": message}


def _short(text: object, limit: int = 90) -> str:
    value = " ".join(str(text).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _norm_ws(text: str) -> str:
    return " ".join(str(text).split()).lower()


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_vacuous(value: object) -> bool:
    return _text(value).lower() in VACUOUS


def _iso(value: object) -> _dt.datetime | None:
    """Parse an ISO-8601 timestamp; ``Z`` is accepted, garbage returns None."""
    raw = _text(value)
    if not raw:
        return None
    text = raw[:-1] + "+00:00" if raw[-1:] in ("Z", "z") else raw
    try:
        return _dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def expectation_hash(text: str) -> str:
    """Digest of the expectation text (see the module docstring)."""
    return hashlib.sha256(text.replace("\r\n", "\n").strip().encode("utf-8")
                          ).hexdigest()


def _stamp(moment: _dt.datetime | None) -> str:
    return moment.isoformat(timespec="seconds") if moment else "—"


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    repo = Path(args.repo).resolve() if getattr(args, "repo", None) else DEFAULT_REPO
    results = (Path(args.results).resolve() if getattr(args, "results", None)
               else repo / "docs" / "implementation" / "ACCEPTANCE-RESULTS.json")
    tasks = (Path(args.tasks).resolve() if getattr(args, "tasks", None)
             else repo / "docs" / "implementation" / "TASK-STATUS.json")
    return repo, results, tasks


def _cases(doc: dict) -> dict:
    cases = doc.get("cases")
    if isinstance(cases, dict):
        return cases
    if isinstance(cases, list):                      # tolerate the design layout
        return {c.get("id"): c for c in cases if isinstance(c, dict)}
    return {}


def _tasks(doc: dict) -> dict:
    tasks = doc.get("tasks")
    if isinstance(tasks, dict):
        return tasks
    if isinstance(tasks, list):
        return {t.get("id"): t for t in tasks if isinstance(t, dict)}
    return {}


# --------------------------------------------------------------------------- #
# evidence paths
# --------------------------------------------------------------------------- #
def _resolve_evidence(rel: object, repo: Path) -> tuple[str | None, Path | None]:
    """Return ``(problem, resolved)`` for one evidence entry.

    ``problem`` is a human sentence (None when fine); ``resolved`` is the
    absolute path when it could be computed.  A path must be repository
    relative, stay inside the repository, and exist as a file.
    """
    if not isinstance(rel, str) or not rel.strip():
        return "证据项必须是非空字符串", None
    text = rel.strip()
    pure = Path(text)
    if _WIN_ABS.match(text) or pure.is_absolute() or pure.anchor:
        return "必须是仓库相对路径，不能是绝对路径", None
    repo_root = repo.resolve()
    resolved = (repo_root / text).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return "路径逃出仓库根（../ 越界）", resolved
    if not resolved.is_file():
        return "文件不存在", resolved
    return None, resolved


# --------------------------------------------------------------------------- #
# field checks
# --------------------------------------------------------------------------- #
def _steps(case: dict) -> list:
    value = case.get("steps")
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _step_text(step: object) -> str:
    if isinstance(step, dict):
        for key in ("command", "cmd", "run"):
            if isinstance(step.get(key), str) and step[key].strip():
                return step[key].strip()
        return ""
    return step.strip() if isinstance(step, str) else ""


def _looks_executable(step: object) -> bool:
    if isinstance(step, dict):
        return bool(_step_text(step))
    text = _step_text(step)
    return bool(text) and bool(_EXEC_HINT.search(text))


def _run_value(case: dict, key: str) -> str:
    runs = case.get("runs")
    if not isinstance(runs, list):
        return ""
    for run in reversed(runs):
        if isinstance(run, dict):
            value = _text(run.get(key))
            if value:
                return value
    return ""


def _observed_at(case: dict) -> _dt.datetime | None:
    return _iso(case.get("observed_at")) or _iso(_run_value(case, "at"))


def _has_gap(case: dict) -> bool:
    value = case.get("gap")
    if isinstance(value, str):
        return not _is_vacuous(value)
    if isinstance(value, (list, tuple)):
        return any(not _is_vacuous(v) for v in value)
    if isinstance(value, dict):
        return any(not _is_vacuous(v) for v in value.values())
    return False


def _check_fixture(case: dict, repo: Path, errors: list[dict], cid: str) -> None:
    value = _text(case.get("fixture"))
    if not value:
        errors.append(_err(cid, "fixture", f"缺少 fixture（{HINTS['fixture']}）"))
        return
    if _SYNTHETIC.search(value):
        return
    tokens = [t for t in _PATH_TOKEN.findall(value) if "/" in t or "\\" in t or "." in t]
    if not tokens:
        errors.append(_err(cid, "fixture",
                           f"fixture 既不是存在的路径，也没有 synthetic 说明：{_short(value)}"))
        return
    missing = [t for t in tokens if not (repo / t.strip("'\"()")).exists()]
    if len(missing) == len(tokens):
        errors.append(_err(cid, "fixture",
                           f"fixture 路径不存在：{missing[0]}（{_short(value)}）"))


def _check_steps(case: dict, errors: list[dict], cid: str) -> list:
    steps = _steps(case)
    if not steps:
        errors.append(_err(cid, "steps", f"缺少 steps（{HINTS['steps']}）"))
        return []
    good = [s for s in steps if _looks_executable(s)]
    if not good:
        errors.append(_err(
            cid, "steps",
            f"steps 共 {len(steps)} 条，都是描述性文字，没有可执行命令/操作："
            f"{_short(_step_text(steps[0]))}"))
    return good


def _check_expectation(case: dict, errors: list[dict], cid: str) -> str:
    expectation = _text(case.get("expectation"))
    scenario = _text(case.get("scenario"))
    if not expectation or _is_vacuous(expectation):
        errors.append(_err(cid, "expectation",
                           f"缺少独立期望（{HINTS['expectation']}）"))
    elif scenario and _norm_ws(expectation) == _norm_ws(scenario):
        errors.append(_err(cid, "expectation",
                           "expectation 只是 scenario 的复述，不是一条独立期望"))
    recorded = _iso(case.get("expectation_recorded_at"))
    implemented = _iso(case.get("implemented_at"))
    if recorded is None:
        errors.append(_err(cid, "expectation_recorded_at",
                           "缺少/无法解析 expectation_recorded_at（ISO 时间）"))
    if implemented is None:
        errors.append(_err(cid, "implemented_at",
                           "缺少/无法解析 implemented_at（ISO 时间）"))
    if recorded and implemented and not recorded.timestamp() < implemented.timestamp():
        errors.append(_err(
            cid, "expectation",
            f"期望时间不早于实现时间：expectation_recorded_at={_stamp(recorded)} "
            f">= implemented_at={_stamp(implemented)}（A60：先期望后实现）"))
    return expectation


def _check_observed(case: dict, expectation: str, errors: list[dict],
                    cid: str) -> None:
    observed = _text(case.get("observed"))
    if not observed or _is_vacuous(observed):
        errors.append(_err(cid, "observed", f"缺少 observed（{HINTS['observed']}）"))
    elif expectation and _norm_ws(observed) == _norm_ws(expectation):
        errors.append(_err(cid, "observed",
                           "observed 与 expectation 完全相同，说明没有记录实际观察结果"))


def _check_environment(case: dict, errors: list[dict], cid: str) -> None:
    value = case.get("environment")
    if isinstance(value, dict):
        if any(_text(v) for v in value.values()):
            return
        errors.append(_err(cid, "environment", f"environment 为空（{HINTS['environment']}）"))
        return
    text = _text(value) or _run_value(case, "environment")
    if not text:
        errors.append(_err(cid, "environment", f"缺少 environment（{HINTS['environment']}）"))
        return
    if not (re.search(r"\d", text)
            or re.search(r"python|provider|提供方|版本|解释器|node|com|libreoffice",
                         text, re.I)):
        errors.append(_err(cid, "environment",
                           f"environment 未给出解释器/库版本/提供方：{_short(text)}"))


def _check_evidence(case: dict, repo: Path, errors: list[dict], cid: str,
                    required: bool) -> None:
    evidence = case.get("evidence")
    if evidence is None or evidence == [] or evidence == "":
        if required:
            errors.append(_err(cid, "evidence", f"缺少 evidence（{HINTS['evidence']}）"))
        return
    if not isinstance(evidence, list):
        errors.append(_err(cid, "evidence", "evidence 必须是路径列表"))
        return
    for index, item in enumerate(evidence):
        problem, _ = _resolve_evidence(item, repo)
        if problem:
            shown = item if isinstance(item, str) else repr(item)
            errors.append(_err(cid, f"evidence[{index}]", f"{shown}: {problem}"))


def _check_execution(case, repo, errors, cid):
    """A test source or prose log is not a structured execution receipt."""
    receipts = case.get("execution_receipts") or []
    test_ids = case.get("test_ids") or []
    if not receipts or not test_ids:
        errors.append(_err(cid, "execution_receipts", "passed需要绑定实际执行JSON及本卡对应test_ids；测试源码和自填observed不足以证明执行"))
        return
    observed_tests = {}
    for item in receipts:
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            errors.append(_err(cid, "execution_receipts", "每个回执需要path和实际SHA256"))
            continue
        problem, path = _resolve_evidence(item["path"], repo)
        if problem:
            errors.append(_err(cid, "execution_receipts", str(problem)))
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item["sha256"]:
                raise ValueError("执行回执哈希改变")
            receipt = _read_json(path)
            mapping = receipt.get("mapping") or {}
            map_path = repo / mapping["path"]
            if hashlib.sha256(map_path.read_bytes()).hexdigest() != mapping["sha256"]:
                raise ValueError("验收场景映射在执行后改变")
            mapped = _read_json(map_path)["cases"][cid]
            if (mapped["test_ids"] != test_ids or mapped["scenario_sha256"] != expectation_hash(case["scenario"])
                    or mapped["expectation_sha256"] != expectation_hash(case["expectation"])):
                raise ValueError("本卡场景/期望/测试映射与执行前冻结映射不一致")
            if receipt.get("producer") != "tools/run_acceptance.py" or not receipt.get("sources_unchanged"):
                raise ValueError("没有真实执行生产者或代码在执行中改变")
            if not receipt.get("production_before") or not receipt.get("oracle_files") or not receipt.get("command") or receipt.get("tests_run", 0) < 1:
                raise ValueError("执行回执缺少实际程序/fixture/命令/测试范围")
            if receipt.get("result") != "passed" or not _iso(receipt.get("started_at")) or not _iso(receipt.get("finished_at")):
                raise ValueError("执行未通过、未完成或缺实际时间")
            if receipt["production_before"] != receipt["production_after"]:
                raise ValueError("执行前后生产代码不一致")
            for rel, want in {**receipt["production_after"], **receipt["oracle_files"]}.items():
                source = repo / rel
                if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != want:
                    raise ValueError(f"回执不是当前代码/fixture版本: {rel}")
            log = path.parent / receipt["execution_log"]
            if hashlib.sha256(log.read_bytes()).hexdigest() != receipt["execution_log_sha256"]:
                raise ValueError("执行原始日志缺失或改变")
            observed_tests.update(receipt["tests"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(_err(cid, "execution_receipts", str(exc)))
    for test_id in test_ids:
        actual = observed_tests.get(test_id)
        if not actual or actual.get("status") != "passed":
            errors.append(_err(cid, "test_ids", f"没有本卡测试的实际通过结果（skip/mock不能冒充）: {test_id}"))


def _command_matches(command: str, steps: list) -> bool:
    needle = _norm_ws(command)
    if not needle:
        return False
    for step in steps:
        hay = _norm_ws(_step_text(step))
        if not hay:
            continue
        if needle == hay or needle in hay or hay in needle:
            return True
    return False


def _check_command(case: dict, steps: list, errors: list[dict], cid: str) -> str:
    command = _text(case.get("command")) or _run_value(case, "command")
    if not command:
        errors.append(_err(cid, "command", f"缺少 command（{HINTS['command']}）"))
        return ""
    if steps and not _command_matches(command, steps):
        errors.append(_err(
            cid, "command",
            f"command 与 steps 没有任何一条一致：command={_short(command)}"))
    return command


def validate_case(cid: str, case: dict, repo: Path) -> list[dict]:
    """Return every problem that stops this card from being re-executable."""
    errors: list[dict] = []
    result = _text(case.get("result"))
    if not result:
        errors.append(_err(cid, "result", "缺少 result（passed/unassessed/failed/…）"))
    elif result not in KNOWN_RESULTS:
        errors.append(_err(cid, "result",
                           f"未知 result {result!r}；允许 {list(KNOWN_RESULTS)}"))

    if result == "unassessed":
        if not _has_gap(case):
            errors.append(_err(cid, "gap",
                               "result=unassessed 但没有写 gap（未核必须写明缺什么）"))
        _check_evidence(case, repo, errors, cid, required=False)
        return errors
    if result != "passed":
        _check_evidence(case, repo, errors, cid, required=False)
        return errors

    _check_fixture(case, repo, errors, cid)
    steps = _check_steps(case, errors, cid)
    expectation = _check_expectation(case, errors, cid)
    _check_observed(case, expectation, errors, cid)
    _check_environment(case, errors, cid)
    _check_evidence(case, repo, errors, cid, required=True)
    _check_execution(case, repo, errors, cid)
    _check_command(case, steps, errors, cid)
    if not _text(case.get("note")):
        errors.append(_err(cid, "note", f"result=passed 但 note 为空（{HINTS['note']}）"))
    return errors


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def cmd_validate(args: argparse.Namespace) -> int:
    repo, results_path, _ = _paths(args)
    if not results_path.is_file():
        return _die(f"找不到结果台账 {results_path}")
    doc = _read_json(results_path)
    cases = _cases(doc)
    errors: list[dict] = []
    passed_total = 0
    passed_clean = 0
    for cid in sorted(cases):
        case = cases[cid] if isinstance(cases[cid], dict) else {}
        case_errors = validate_case(cid, case, repo)
        errors.extend(case_errors)
        if _text(case.get("result")) == "passed":
            passed_total += 1
            if not case_errors:
                passed_clean += 1

    histogram: dict[str, int] = {}
    for item in errors:
        field = str(item.get("field", "")).split("[", 1)[0]
        histogram[field] = histogram.get(field, 0) + 1
    summary = {
        "passed": passed_clean,
        "checked": passed_total,
        "errors": errors,
        "missing_fields": dict(sorted(histogram.items(),
                                      key=lambda kv: (-kv[1], kv[0]))),
        "results": str(results_path),
    }
    _emit(summary)
    return 2 if errors else 0


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def _cell(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        return "<br>".join(_cell(v) for v in value)
    if isinstance(value, dict):
        if not value:
            return "—"
        return "<br>".join(f"{k}: {_cell(v)}" for k, v in value.items())
    text = str(value).strip()
    return text.replace("|", r"\|").replace("\n", "<br>") if text else "—"


def _recorded(value: object) -> str:
    """Cell for a field that a re-executor needs: say so when it is missing."""
    return _cell(value) if value else "—（未记录）"


def _steps_cell(steps: list) -> str:
    if not steps:
        return "—（未记录）"
    rendered = []
    for index, step in enumerate(steps, 1):
        text = _step_text(step) or _cell(step)
        rendered.append(f"{index}. {_cell(text)}")
    return "<br>".join(rendered)


def _out_rel_dir(out: Path, repo: Path) -> str | None:
    try:
        return out.resolve().parent.relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def _evidence_cell(case: dict, repo: Path, out_rel: str | None) -> str:
    evidence = case.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return "—（未记录）"
    parts = []
    for item in evidence:
        if not isinstance(item, str) or not item.strip():
            parts.append(_cell(item))
            continue
        text = item.strip().replace("\\", "/")
        while text.startswith("./"):
            text = text[2:]
        problem, _ = _resolve_evidence(item, repo)
        href = posixpath.relpath(text, start=out_rel) if out_rel else text
        if problem:
            parts.append(f"[{_cell(text)}]({href})（{problem}）")
        else:
            parts.append(f"[{_cell(text)}]({href})")
    return "<br>".join(parts)


def _ordered_case_ids(cases: dict) -> list[str]:
    standard = [f"A{i:02d}" for i in range(1, 61)]
    present = [cid for cid in standard if cid in cases]
    extra = sorted(cid for cid in cases if cid not in set(standard))
    return present + extra


def cmd_render(args: argparse.Namespace) -> int:
    repo, results_path, _ = _paths(args)
    if not results_path.is_file():
        return _die(f"找不到结果台账 {results_path}")
    doc = _read_json(results_path)
    cases = _cases(doc)
    order = _ordered_case_ids(cases)
    out = (Path(args.out).resolve() if args.out
           else repo / "docs" / "implementation" / "ACCEPTANCE-CARDS.md")
    out_rel = _out_rel_dir(out, repo)

    counts: dict[str, int] = {}
    field_histogram: dict[str, int] = {}
    clean_passed = 0
    passed_total = 0
    for cid in order:
        case = cases.get(cid) if isinstance(cases.get(cid), dict) else {}
        result = _text(case.get("result")) or "（缺失）"
        counts[result] = counts.get(result, 0) + 1
        errors = validate_case(cid, case, repo)
        for item in errors:
            field = str(item.get("field", "")).split("[", 1)[0]
            field_histogram[field] = field_histogram.get(field, 0) + 1
        if result == "passed":
            passed_total += 1
            clean_passed += 0 if errors else 1

    lines: list[str] = []
    lines.append("# 验收卡 A01–A60（由台账生成，只读视图）")
    lines.append("")
    lines.append("> 本文件由 `python tools/acceptance_cards.py render` 生成，**不要手改**；"
                 "要改就改台账再重跑本命令。")
    lines.append(f"> 数据源：`{_rel(results_path, repo)}`")
    lines.append(f"> 生成时间：{_now()}")
    lines.append(f"> 自检（与 `validate` 同一套规则）：passed 卡 {passed_total} 张，"
                 f"其中 {clean_passed} 张字段齐备，"
                 f"{sum(field_histogram.values())} 条 error。")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append("| 结果 | 数量 |")
    lines.append("|---|---|")
    for key in sorted(counts):
        lines.append(f"| {_cell(key)} | {counts[key]} |")
    lines.append(f"| **合计** | **{len(order)}** |")
    lines.append("")
    if field_histogram:
        lines.append("## 缺失字段统计（validate 口径）")
        lines.append("")
        lines.append("| 字段 | 条数 |")
        lines.append("|---|---|")
        for field, number in sorted(field_histogram.items(),
                                    key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{field}` | {number} |")
        lines.append("")
    lines.append("## 卡片")
    lines.append("")
    for cid in order:
        case = cases[cid]
        lines.append(f"### {cid} · {_cell(case.get('scenario'))}")
        lines.append("")
        lines.append("| 项 | 内容 |")
        lines.append("|---|---|")
        lines.append(f"| 编号 | {cid} |")
        lines.append(f"| 场景 | {_cell(case.get('scenario'))} |")
        lines.append(f"| 主任务 | {_cell(case.get('primary_task'))} |")
        linked = case.get("linked_tasks")
        lines.append(f"| 关联任务 | {_cell(linked)} |")
        lines.append(f"| fixture | {_recorded(case.get('fixture'))} |")
        lines.append(f"| 步骤 | {_steps_cell(_steps(case))} |")
        lines.append(f"| 独立期望 | {_recorded(case.get('expectation'))} |")
        lines.append(f"| 实际观察 | {_recorded(case.get('observed'))} |")
        lines.append(f"| 环境 | {_recorded(case.get('environment'))} |")
        lines.append(f"| 证据 | {_evidence_cell(case, repo, out_rel)} |")
        lines.append(f"| 状态 | {_cell(case.get('result')) or '—'} |")
        lines.append(f"| gap | {_cell(case.get('gap')) or '—'} |")
        lines.append(f"| 期望记录 → 实现 | "
                     f"{_cell(case.get('expectation_recorded_at'))} → "
                     f"{_cell(case.get('implemented_at'))} |")
        notes = case.get("note")
        if notes:
            lines.append(f"| 备注 | {_cell(notes)} |")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("字段口径见 `tools/acceptance_cards.py` 模块文档：passed 卡必须同时具备 "
                 "fixture / steps / expectation / observed / environment / evidence / "
                 "command，且 `expectation_recorded_at` 早于 `implemented_at`；"
                 "unassessed 必须写 gap。")
    lines.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    summary = {
        "written": str(out),
        "cards": len(order),
        "results": dict(sorted(counts.items())),
        "passed_clean": clean_passed,
        "passed_total": passed_total,
        "missing_fields": dict(sorted(field_histogram.items(),
                                      key=lambda kv: (-kv[1], kv[0]))),
    }
    _emit(summary)
    return 0


def _rel(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- #
# batch-gate
# --------------------------------------------------------------------------- #
def _normalise_batch(value: str) -> str:
    text = (value or "").strip().upper()
    if text.isdigit():
        text = "M" + text
    return text


def _gate_batch(batch: str, tasks: dict, cases: dict, repo: Path) -> list[dict]:
    blockers: list[dict] = []
    for tid in BATCHES[batch]:
        task = tasks.get(tid)
        if not isinstance(task, dict):
            blockers.append({"batch": batch, "task": tid,
                             "reason": "任务不在 TASK-STATUS 台账中"})
            continue
        state = _text(task.get("state"))
        if state not in GATE_STATES:
            blockers.append({"batch": batch, "task": tid,
                             "reason": f"state={state or '缺失'}，需要 implemented/verified"})
        if not task.get("acceptance_cases"):
            blockers.append({"batch": batch, "task": tid, "reason": "任务没有实际关联验收场景"})
        for cid in task.get("acceptance_cases") or []:
            case = cases.get(cid)
            if not isinstance(case, dict):
                blockers.append({"batch": batch, "task": tid,
                                 "reason": f"关联场景 {cid} 不在结果台账中"})
            elif _text(case.get("result")) != "passed":
                blockers.append({"batch": batch, "task": tid,
                                 "reason": f"关联场景 {cid} 的 result={case.get('result')}"})
            elif validate_case(cid, case, repo):
                blockers.append({"batch": batch, "task": tid, "reason": f"关联场景 {cid} 的实际证据不完整或过期"})
    return blockers


def cmd_batch_gate(args: argparse.Namespace) -> int:
    repo, results_path, tasks_path = _paths(args)
    batch = _normalise_batch(args.batch)
    if batch not in BATCHES:
        return _die(f"未知批次 {args.batch!r}；允许 {list(BATCH_ORDER)}")
    for path, label in ((tasks_path, "TASK-STATUS"), (results_path, "ACCEPTANCE-RESULTS")):
        if not path.is_file():
            return _die(f"找不到{label}台账 {path}")
    tasks = _tasks(_read_json(tasks_path))
    cases = _cases(_read_json(results_path))

    # The gate is recursive backwards: a batch cannot pass on top of a broken
    # predecessor.  Later batches are irrelevant (a half-done M6 must not turn
    # an otherwise clean M1 into a failure).
    index = BATCH_ORDER.index(batch)
    checked = BATCH_ORDER[: index + 1]
    per_batch: dict[str, list[dict]] = {}
    for name in checked:
        per_batch[name] = _gate_batch(name, tasks, cases, repo)
    blockers = [item for name in checked for item in per_batch[name]]
    blocked_by = [name for name in checked if per_batch[name]]

    warnings = []
    for tid in BATCHES[batch]:
        task = tasks.get(tid) or {}
        phase = _text(task.get("phase"))
        if phase and phase != batch:
            warnings.append(f"{tid}: 台账 phase={phase}，批次表为 {batch}")

    summary = {
        "batch": batch,
        "passed": not blockers,
        "blocked_by": blocked_by,
        "checked_batches": list(checked),
        "blockers": blockers,
        "warnings": warnings,
    }
    _emit(summary)
    return 0 if not blockers else 2


# --------------------------------------------------------------------------- #
# order-check
# --------------------------------------------------------------------------- #
def cmd_order_check(args: argparse.Namespace) -> int:
    repo, results_path, _ = _paths(args)
    if not results_path.is_file():
        return _die(f"找不到结果台账 {results_path}")
    cases = _cases(_read_json(results_path))
    errors: list[dict] = []
    checked = 0
    clean = 0
    for cid in sorted(cases):
        case = cases[cid] if isinstance(cases[cid], dict) else {}
        if _text(case.get("result")) != "passed":
            continue
        checked += 1
        before = len(errors)
        recorded = _iso(case.get("expectation_recorded_at"))
        implemented = _iso(case.get("implemented_at"))
        if recorded is None:
            errors.append(_err(cid, "expectation_recorded_at",
                               "缺少/无法解析 expectation_recorded_at（ISO 时间）"))
        if implemented is None:
            errors.append(_err(cid, "implemented_at",
                               "缺少/无法解析 implemented_at（ISO 时间）"))
        if recorded and implemented and not recorded.timestamp() < implemented.timestamp():
            errors.append(_err(
                cid, "expectation",
                f"期望记录时间不早于实现时间：{_stamp(recorded)} >= "
                f"{_stamp(implemented)}（A60：先期望后实现）"))
        expectation = _text(case.get("expectation"))
        digest = _text(case.get("expectation_sha256")).lower()
        current = expectation_hash(expectation) if expectation else ""
        if not expectation:
            errors.append(_err(cid, "expectation", "缺少 expectation，无法校验哈希"))
        elif not digest:
            errors.append(_err(
                cid, "expectation_sha256",
                "缺少 expectation_sha256（无法证明期望在实现后没有被改写）"))
        elif digest != current:
            errors.append(_err(
                cid, "expectation_sha256",
                f"期望哈希不符：台账 {digest[:12]}… ≠ 当前文本 {current[:12]}…"
                "（期望在实现后被改写，先期望后实现不成立）"))
        if len(errors) == before:
            clean += 1
    summary = {
        "checked": checked,
        "ok": clean,
        "errors": errors,
        "results": str(results_path),
    }
    _emit(summary)
    return 0 if not errors else 2


# --------------------------------------------------------------------------- #
# drift
# --------------------------------------------------------------------------- #
def _grep(command: str, path: Path, limit: int = 4_000_000) -> bool:
    try:
        if path.stat().st_size > limit:
            return True                  # too big to call absence a finding
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    hay = _norm_ws(text)
    needle = _norm_ws(command)
    if needle and needle in hay:
        return True
    core = needle.split(";")[-1].strip()     # tolerate a leading `cd x;`
    return len(core) >= 8 and core in hay


def cmd_drift(args: argparse.Namespace) -> int:
    repo, results_path, tasks_path = _paths(args)
    if not results_path.is_file():
        return _die(f"找不到结果台账 {results_path}")
    cases = _cases(_read_json(results_path))
    tasks = _tasks(_read_json(tasks_path)) if tasks_path.is_file() else {}
    errors: list[dict] = []
    warnings: list[dict] = []
    checked = 0
    for cid in sorted(cases):
        case = cases[cid] if isinstance(cases[cid], dict) else {}
        evidence = case.get("evidence")
        evidence = evidence if isinstance(evidence, list) else []
        seen: dict[str, int] = {}
        for index, item in enumerate(evidence):
            problem, _ = _resolve_evidence(item, repo)
            if problem:
                shown = item if isinstance(item, str) else repr(item)
                errors.append(_err(cid, f"evidence[{index}]", f"{shown}: {problem}"))
                continue
            seen[item] = seen.get(item, 0) + 1
        if not seen:
            continue
        checked += 1
        for item, times in seen.items():
            if times > 1:
                warnings.append({"case": cid, "kind": "duplicate-evidence",
                                 "message": f"evidence 重复登记 {times} 次：{item}"})
        observed = _observed_at(case)
        if observed is None:
            warnings.append({"case": cid, "kind": "missing-observed-at",
                             "message": "没有 observed_at（runs[] 里也没有 at），"
                                        "无法核对证据是否事后补造"})
        else:
            for item in seen:
                path = (repo / item).resolve()
                try:
                    mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime,
                                                       _dt.timezone.utc)
                except OSError:
                    continue
                if mtime.timestamp() > observed.timestamp():
                    warnings.append({
                        "case": cid, "kind": "evidence-after-observation",
                        "message": f"证据 mtime {_stamp(mtime)} 晚于 observed_at "
                                   f"{_stamp(observed)}，像是事后补的：{item}"})
        command = _text(case.get("command")) or _run_value(case, "command")
        if command and not any(_grep(command, (repo / item).resolve())
                               for item in seen):
            warnings.append({
                "case": cid, "kind": "command-not-in-evidence",
                "message": f"command 在 {len(seen)} 个证据文件里都 grep 不到，"
                           f"证据不是这条命令的执行回执：{_short(command)}"})
        for tid in case.get("linked_tasks") or []:
            if tasks and tid not in tasks:
                warnings.append({"case": cid, "kind": "dangling-task",
                                 "message": f"linked_tasks 里的 {tid} 不在任务台账中"})
    summary = {
        "checked": checked,
        "errors": errors,
        "warnings": warnings,
        "results": str(results_path),
    }
    _emit(summary)
    return 0 if not errors else 2


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--repo", help="仓库根（默认：本工具的上一级目录）")
        parser.add_argument("--results", help="ACCEPTANCE-RESULTS.json 路径")
        parser.add_argument("--tasks", help="TASK-STATUS.json 路径")

    p_validate = sub.add_parser("validate", help="校验 passed 卡是否可执行")
    common(p_validate)
    p_render = sub.add_parser("render", help="生成 docs/implementation/ACCEPTANCE-CARDS.md")
    common(p_render)
    p_render.add_argument("--out", help="输出 Markdown 路径")
    p_gate = sub.add_parser("batch-gate", help="批次门检（递归检查前置批次）")
    common(p_gate)
    p_gate.add_argument("--batch", required=True, help="M0…M7（或 0…7）")
    p_order = sub.add_parser("order-check", help="A60 先期望后实现检查")
    common(p_order)
    p_drift = sub.add_parser("drift", help="台账与真实证据的漂移")
    common(p_drift)
    return ap


HANDLERS = {
    "validate": cmd_validate,
    "render": cmd_render,
    "batch-gate": cmd_batch_gate,
    "order-check": cmd_order_check,
    "drift": cmd_drift,
}


def main(argv: list[str] | None = None) -> int:
    try:                                    # Windows console defaults to cp936
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    args = build_parser().parse_args(argv)
    return HANDLERS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
