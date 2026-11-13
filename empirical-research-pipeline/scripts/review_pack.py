#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the pre-delivery review packet a model (or a coauthor) reads.

The packet is deliberately factual: every number in it comes from an artefact
that is listed in the header and hashed.  It does not decide whether the study
is right; it puts the things a reviewer will attack in one place — sample,
missingness, model N, figure references, number-trace failures, unresolved
judgments — so the model can review its own work before a human sees it.

Usage:
  python scripts/review_pack.py --data output/dataset/analysis.csv \
      --stats output/stats --figures output/chart_pack/chart_manifest.csv \
      --verify output/verify/number_issues.csv --decisions decisions.jsonl \
      --out output/review/review_pack.md
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime

SCRIPT_VERSION = "1.0.0"

NA_TOKENS = {"", "na", "n/a", "nan", "none", "null", "缺失", "未记录", "未提及"}


def _sha12(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:12]
    except OSError:
        return "missing"


def _fingerprint(path: str | None) -> str:
    """Content hash of a file, or a stable listing hash of a directory."""
    if not path:
        return ""
    if os.path.isfile(path):
        return _sha12(path)
    if os.path.isdir(path):
        digest = hashlib.sha256()
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                digest.update(rel.encode("utf-8"))
                if name.endswith((".csv", ".json", ".md", ".txt")):
                    with open(full, "rb") as fh:
                        digest.update(fh.read())
                else:
                    digest.update(str(os.path.getsize(full)).encode("ascii"))
        return digest.hexdigest()[:12]
    return ""


def _read_csv(path: str | None) -> list[dict]:
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _read_json(path: str | None) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_jsonl(path: str | None) -> list[dict]:
    if not path or not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
    return out


def _num(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _data_section(rows: list[dict], flag: str) -> dict:
    if not rows:
        return {"provided": False}
    columns = list(rows[0].keys())
    metadata = {"rel_path", "file", "doc_type"}
    missing = []
    for column in columns:
        if column in metadata or column.endswith("_src"):
            continue
        blank = sum(1 for row in rows
                    if str(row.get(column, "")).strip().lower() in NA_TOKENS)
        share = blank / len(rows) if rows else 0.0
        if blank:
            missing.append({"column": column, "n": blank, "share": round(share, 4)})
    missing.sort(key=lambda item: (-item["share"], item["column"]))
    flagged = 0
    if flag and flag in columns:
        flagged = sum(1 for row in rows
                      if str(row.get(flag, "")).strip().lower()
                      in {"1", "1.0", "true", "yes", "是"})
    return {"provided": True, "rows": len(rows), "columns": len(columns),
            "columns_list": columns[:12],
            "missing": missing[:5], "flag": flag if flag in columns else "",
            "flagged": flagged}


def _missing_section(path: str | None) -> dict:
    rows = _read_csv(path)
    if not rows:
        return {"provided": False}
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        field = row.get("field") or ""
        bucket = row.get("bucket") or ""
        n = _num(row.get("n"))
        if not field or not bucket or n is None:
            continue
        buckets.setdefault(field, {})[bucket] = int(n)
    unparsed = {field: counts["unparsed"] for field, counts in buckets.items()
                if counts.get("unparsed")}
    return {"provided": True, "buckets": buckets, "unparsed": unparsed,
            "fields": len(buckets)}


def _funnel_section(path: str | None) -> dict:
    rows = _read_csv(path)
    if not rows:
        return {"provided": False}
    stages = []
    for row in rows:
        n = _num(row.get("n"))
        if n is not None:
            stages.append({"stage": row.get("stage") or "", "n": int(n)})
    monotonic = all(stages[i]["n"] >= stages[i + 1]["n"]
                    for i in range(len(stages) - 1))
    return {"provided": True, "stages": stages, "monotonic": monotonic,
            "first": stages[0]["n"] if stages else None,
            "last": stages[-1]["n"] if stages else None}


def _model_section(stats_dir: str | None, data_rows: int | None) -> dict:
    if not stats_dir or not os.path.isdir(stats_dir):
        return {"provided": False}
    coef = _read_csv(os.path.join(stats_dir, "coef_all.csv"))
    fit = _read_csv(os.path.join(stats_dir, "fit.csv"))
    models = {}
    for row in coef:
        name = row.get("model") or row.get("id") or "model"
        entry = models.setdefault(name, {"model": name, "terms": 0,
                                         "n": None, "type": row.get("type", "")})
        entry["terms"] += 1
        n = _num(row.get("n"))
        if n is not None:
            entry["n"] = int(n) if entry["n"] is None else max(entry["n"], int(n))
    fit_by_model = {row.get("model") or row.get("id"): row for row in fit}
    out = []
    for name, entry in models.items():
        fit_row = fit_by_model.get(name) or {}
        entry["n_fit"] = int(_num(fit_row.get("n")) or 0) or None
        entry["r2"] = fit_row.get("pseudo_r2") or fit_row.get("r2")
        out.append(entry)
    return {"provided": True, "models": out, "data_rows": data_rows}


def _figure_section(manifest: str | None) -> dict:
    rows = _read_csv(manifest)
    if not rows:
        return {"provided": False}
    status = Counter((row.get("status") or "ok").strip() or "ok" for row in rows)
    sections = Counter((row.get("section") or "").strip() for row in rows)
    ns = [int(_num(row.get("n"))) for row in rows if _num(row.get("n")) is not None]
    return {"provided": True, "count": len(rows),
            "status": dict(status), "sections": dict(sections),
            "n_min": min(ns) if ns else None, "n_max": max(ns) if ns else None,
            "not_ok": [row.get("id") for row in rows
                       if (row.get("status") or "ok").strip() not in ("", "ok")]}


def _verify_section(path: str | None) -> dict:
    rows = _read_csv(path)
    if not path or not os.path.isfile(path):
        return {"provided": False}
    severity = Counter((row.get("severity") or "").strip() for row in rows)
    checks = Counter((row.get("check") or "").strip() for row in rows)
    errors = [row for row in rows if (row.get("severity") or "").strip() == "error"]
    return {"provided": True, "total": len(rows), "severity": dict(severity),
            "checks": dict(checks),
            "errors": [{"check": row.get("check"), "where": row.get("where"),
                        "detail": row.get("detail")} for row in errors[:5]]}


def _qa_section(path: str | None) -> dict:
    report = _read_json(path)
    if not report:
        return {"provided": False}
    checks = {}
    for name, value in (report.get("checks") or {}).items():
        if not isinstance(value, dict):
            continue
        checks[name] = {"errors": len(value.get("errors") or []),
                        "warnings": len(value.get("warnings") or [])}
        if "palette_unchecked" in value:
            checks[name]["palette_unchecked"] = value["palette_unchecked"]
            checks[name]["palette_eligible"] = value.get("palette_eligible")
    return {"provided": True,
            "error_count": report.get("error_count", 0),
            "warning_count": report.get("warning_count", 0),
            "checks": checks}


def _decision_section(path: str | None) -> dict:
    rows = _read_jsonl(path)
    if not rows:
        return {"provided": False}
    stages = Counter(str(row.get("stage") or "") for row in rows)
    unresolved = [row for row in rows if row.get("needs_human")]
    return {"provided": True, "count": len(rows), "stages": dict(stages),
            "unresolved": len(unresolved),
            "unresolved_targets": [row.get("target") for row in unresolved[:5]]}


def _questions(sample: dict, models: dict, figures: dict, verify: dict,
               qa: dict, decisions: dict, limit: int) -> list[str]:
    out = []
    if sample.get("provided") and sample.get("missing"):
        top = sample["missing"][0]
        out.append(f"缺失值：`{top['column']}` 有 {top['n']} 行缺失"
                   f"（{top['share']:.1%}），是资料没问、原文没记载，"
                   "还是抽取规则没覆盖？")
    funnel = sample.get("funnel") or {}
    if funnel.get("provided"):
        out.append(f"样本选择：漏斗从 {funnel['first']} 降到 {funnel['last']}，"
                   "每一档排除是否都能在 `skipped_documents.csv` 找到原因？")
    missing = sample.get("missing_source") or {}
    if missing.get("provided") and missing.get("unparsed"):
        field, n = next(iter(missing["unparsed"].items()))
        out.append(f"缺失来源：`{field}` 有 {n} 条 `unparsed`——文字找到了但没解析出值。"
                   "先修抽取规则或写 decision，不要把它写成“未提及”。")
    if models.get("provided"):
        gaps = [model for model in models["models"]
                if model.get("n_fit") and models.get("data_rows")
                and model["n_fit"] != models["data_rows"]]
        if gaps:
            item = gaps[0]
            out.append(f"样本口径：模型 `{item['model']}` 的 N={item['n_fit']}，"
                       f"分析数据有 {models['data_rows']} 行；差异原因是否写进表注？")
        else:
            out.append("模型：每个系数表的 N 与样本漏斗是否同一口径，"
                       "参照组和标准误类型是否在表注里说明？")
    if figures.get("provided"):
        if figures.get("not_ok"):
            out.append(f"图表：{len(figures['not_ok'])} 张图状态不是 ok"
                       f"（{', '.join(map(str, figures['not_ok'][:4]))}），为什么仍要交付？")
        elif verify.get("provided") and verify.get("checks", {}).get("V-04"):
            out.append(f"图表：有 {verify['checks']['V-04']} 条图号未被正文引用；"
                       "每一张留下的图是否都在正文承担了论证？")
    if verify.get("provided"):
        errors = verify.get("severity", {}).get("error", 0)
        if errors:
            out.append(f"数字：{errors} 个 error 仍未解决；正文中的每个 N/OR/p "
                       "是否都能回到表或图？")
    if decisions.get("provided") and decisions.get("unresolved"):
        out.append(f"判断：{decisions['unresolved']} 条 decisions 仍标记 needs_human；"
                   "这些取舍是否应该由作者拍板？")
    if qa.get("provided") and qa.get("error_count"):
        out.append(f"终检：qa_report 有 {qa['error_count']} 个 error；"
                   "是产物问题还是闸门配置问题？")
    if not out:
        out.append("当前输入没有暴露明显的数字或结构问题；请人工确认研究问题、"
                   "变量定义与结论边界是否仍然成立。")
    return out[:limit]


def _render(payload: dict) -> str:
    lines = ["# 交付前审稿包", "",
             f"- 生成时间：{payload['generated_at']}",
             f"- 审稿包版本：{SCRIPT_VERSION}", "",
             "## 输入与指纹", ""]
    for name, item in payload["inputs"].items():
        state = "已提供" if item["exists"] else "未提供"
        lines.append(f"- `{name}`：{state}"
                     + (f"，sha256:{item['sha256']}" if item["exists"] else ""))
    lines.append("")

    sample = payload["sample"]
    lines += ["## 1. 样本", ""]
    if sample.get("provided"):
        lines.append(f"- 分析数据：{sample['rows']} 行 × {sample['columns']} 列")
        if sample.get("flag"):
            lines.append(f"- `{sample['flag']}=1`：{sample['flagged']} 行")
        for item in sample.get("missing", []):
            lines.append(f"- 缺失：`{item['column']}` {item['n']} 行"
                         f"（{item['share']:.1%}）")
        missing_source = sample.get("missing_source") or {}
        if missing_source.get("provided"):
            for field, counts in list(missing_source["buckets"].items())[:3]:
                detail = "，".join(f"{bucket}={n}" for bucket, n in sorted(counts.items()))
                lines.append(f"- 缺失来源：`{field}` {detail}")
        funnel = sample.get("funnel") or {}
        if funnel.get("provided"):
            lines.append(f"- 样本漏斗：{funnel['first']} → {funnel['last']}；"
                         f"单调不增：{'是' if funnel['monotonic'] else '否'}")
            lines.append("- 漏斗阶段：" + "；".join(
                f"{item['stage']}={item['n']}" for item in funnel["stages"]))
    else:
        lines.append("- 未提供 `--data`")
    lines.append("")

    models = payload["models"]
    lines += ["## 2. 模型", ""]
    if models.get("provided"):
        for item in models["models"]:
            r2 = f"，R²={item['r2']}" if item.get("r2") not in (None, "") else ""
            lines.append(f"- `{item['model']}`：{item['terms']} 个系数，"
                         f"N={item.get('n_fit') or item.get('n') or '未记录'}{r2}")
    else:
        lines.append("- 未提供 `--stats`（或目录里没有 coef_all.csv / fit.csv）")
    lines.append("")

    figures = payload["figures"]
    lines += ["## 3. 图表", ""]
    if figures.get("provided"):
        lines.append(f"- 图数：{figures['count']}；N 范围："
                     f"{figures['n_min']}–{figures['n_max']}")
        lines.append(f"- 状态：{figures['status']}")
        if figures.get("not_ok"):
            lines.append(f"- 非 ok：{', '.join(map(str, figures['not_ok']))}")
    else:
        lines.append("- 未提供 `--figures`")
    lines.append("")

    verify = payload["numbers"]
    lines += ["## 4. 数字溯源", ""]
    if verify.get("provided"):
        lines.append(f"- 问题总数：{verify['total']}；严重度：{verify['severity']}")
        lines.append(f"- 检查分布：{verify['checks']}")
        for item in verify.get("errors", []):
            lines.append(f"- error `{item['check']}` {item['where']}：{item['detail']}")
    else:
        lines.append("- 未提供 `--verify`")
    lines.append("")

    qa = payload["qa"]
    lines += ["## 5. 终检与判断", ""]
    if qa.get("provided"):
        lines.append(f"- qa_report：{qa['error_count']} error / "
                     f"{qa['warning_count']} warning")
        for name, item in qa.get("checks", {}).items():
            if item["errors"] or item["warnings"]:
                lines.append(f"- `{name}`：{item['errors']} error / "
                             f"{item['warnings']} warning")
            if item.get("palette_unchecked"):
                lines.append(f"- `{name}` 配色：{item['palette_unchecked']} 张未完成此项离散色诊断；"
                             "这是建议性检查范围，需结合实际渲染复核，不等同于数据错误。")
    else:
        lines.append("- 未提供 `--qa`")
    decisions = payload["decisions"]
    if decisions.get("provided"):
        lines.append(f"- decisions：{decisions['count']} 条；"
                     f"待人工：{decisions['unresolved']} 条")
        for target in decisions.get("unresolved_targets", []):
            lines.append(f"- 待拍板：`{target}`")
    else:
        lines.append("- 未提供 `--decisions`（抽取/变量/方法的判断没有留下台账）")
    lines.append("")

    research = payload.get("research") or {}
    if research.get("provided"):
        lines += ["## 全资料、逐格复核与开放模型覆盖", "",
                  f"- research_gate：{research.get('status')}；{research.get('error_count', 0)} error",
                  f"- 来源 {research.get('source_count', 0)}；数据集 {research.get('dataset_count', 0)}；候选模型 {research.get('model_count', 0)}"]
        for issue in research.get("issues", []):
            lines.append(f"- error `{issue.get('where')}`：{issue.get('detail')}")
        lines.append("")

    lines += ["## 6. 审稿人最可能先问的问题", ""]
    for index, question in enumerate(payload["questions"], 1):
        lines.append(f"{index}. {question}")
    lines += ["", "## 7. 交付前自检", "",
              "- [ ] 每个 N 都有口径（描述样本 / 模型样本 / 有效样本）",
              "- [ ] 每张图都在正文被引用，且图号连续",
              "- [ ] 每个正文数字都能回到表、图或 numbers.csv",
              "- [ ] 缺失值策略、参照组、标准误类型写在表注里",
              "- [ ] 未解决的 decisions 已由作者拍板",
              "- [ ] 结论没有超出数据能支持的范围", ""]
    return "\n".join(lines)


def build_pack(args) -> dict:
    inputs = {}
    for name, path in (("data", args.data), ("stats", args.stats),
                       ("figures", args.figures), ("verify", args.verify),
                       ("qa", args.qa), ("decisions", args.decisions),
                       ("sample_flow", args.sample_flow),
                        ("missing", args.missing),
                        ("research_gate", getattr(args, "research_gate", None))):
        inputs[name] = {"path": path, "exists": bool(path and os.path.exists(path)),
                        "sha256": _fingerprint(path)}
    data_rows = _read_csv(args.data)
    sample = _data_section(data_rows, args.flag)
    sample["funnel"] = _funnel_section(args.sample_flow)
    sample["missing_source"] = _missing_section(args.missing)
    models = _model_section(args.stats, sample.get("rows"))
    figures = _figure_section(args.figures)
    verify = _verify_section(args.verify)
    qa = _qa_section(args.qa)
    decisions = _decision_section(args.decisions)
    research_path = getattr(args, "research_gate", None)
    research = _read_json(research_path)
    research["provided"] = bool(research_path and os.path.isfile(research_path))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": inputs,
        "sample": sample,
        "models": models,
        "figures": figures,
        "numbers": verify,
        "qa": qa,
        "decisions": decisions,
        "research": research,
        "questions": _questions(sample, models, figures, verify, qa,
                                decisions, args.top),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a factual pre-delivery review packet.")
    parser.add_argument("--data", default=None, help="analysis CSV")
    parser.add_argument("--stats", default=None, help="stats output directory")
    parser.add_argument("--figures", default=None, help="chart_manifest.csv")
    parser.add_argument("--verify", default=None, help="number_issues.csv")
    parser.add_argument("--qa", default=None, help="qa_report.json")
    parser.add_argument("--decisions", default=None, help="decisions.jsonl")
    parser.add_argument("--research-gate", default=None, help="research_gate.json (all datasets, sources and model coverage)")
    parser.add_argument("--sample-flow", default=None, help="sample_flow.csv")
    parser.add_argument("--missing", default=None,
                        help="missing_by_source.csv (missing-value mechanism)")
    parser.add_argument("--flag", default="in_analysis",
                        help="analysis flag column (default in_analysis)")
    parser.add_argument("--top", type=int, default=5,
                        help="maximum review questions (default 5)")
    parser.add_argument("--out", default="review_pack.md",
                        help="Markdown output path; JSON is written beside it")
    args = parser.parse_args(argv)

    if not any((args.data, args.stats, args.figures, args.verify,
                args.qa, args.decisions, args.sample_flow, args.missing, args.research_gate)):
        print("ERROR: give at least one input (--data/--stats/--figures/"
              "--verify/--qa/--decisions)", file=sys.stderr)
        return 2

    payload = build_pack(args)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(_render(payload))
    json_path = os.path.splitext(args.out)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"review pack: {args.out}")
    print(f"review json: {json_path}")
    print(f"questions: {len(payload['questions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
