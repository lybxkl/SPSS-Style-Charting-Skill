#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数字溯源校验器 (Sprint C1) -- verify_numbers.py

论文里最贵的错误不是"图不够清晰"，而是正文写 1358、表里写 1357。
本脚本把每个数字追到它的来源，把每一处对不上写成一条可定位的 issue：

- V-01 表内合计：合计/总计/小计/Total 行与列必须等于其余项之和；
        分类变量（取值数 <= 12）各水平计数之和必须等于表注 N=，
        没有 N= 时对照 sample_flow.csv 的 stage。
- V-02 表图同值：manifest 图注里的 N 必须等于同号表里的 N。
- V-03 正文数字溯源：md/docx 里的 N=/OR=/β=/p</百分比/…份 必须能在
        表格（或 --numbers 的 numbers.csv）里找到；找不到就是 error。
- V-04 图号连续且被引用：图号必须从 1 连续；正文至少引用每个图号一次。
- V-05 样本 N 跨表一致：同一 n_scope 的模型表 N 必须一致，除非显式
        标注了 sample/subset。
- V-06 漏斗对账：sample_flow.csv 的 n 必须单调不增。

输出：
    number_issues.csv  severity,check,where,expected,actual,detail
    number_trace.csv   number,source_file,source_row,source_col,matched_by

退出码：有 error -> 2；只有 warning 且 --fail-on-warn -> 2；否则 0。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Reuse the authoritative parsers instead of growing a second, drifting copy.
from qa_outputs import N_RE, parse_n, read_rows

SCRIPT_VERSION = "1.0.0"

TOTAL_LABELS = ("合计", "总计", "小计", "总和", "total", "sum")
# A column literally named "n"/"N" is a sample size, not a category count:
# robustness.csv / heterogeneity.csv carry one N per model row, and summing them
# would be meaningless.  Only explicit count headers take part in V-01.
COUNT_HEADERS = {"频数", "计数", "数量", "案例数", "个数", "频次", "count", "size", "frequency"}
FIG_ID_HEADERS = ("id", "figure", "fig", "label", "图号", "编号", "图表")
CAPTION_HEADERS = ("caption", "图注", "标题", "说明", "title")
SCOPE_HEADERS = ("n_scope", "scope", "样本范围")
STATUS_HEADERS = ("status", "state", "状态")
STATUS_OK = {"ok", "done", "success", "ready", "完成", "成功"}
NUMBER_HEADERS = ("figure_no", "fig_no", "figureno", "figure_number", "序号")
SAMPLE_HEADERS = ("sample", "subset", "子样本", "样本")
SCOPE_ALIASES = {"corpus": "corpus", "语料": "corpus", "全语料": "corpus",
                 "语料总量": "corpus", "sample": "sample", "样本": "sample",
                 "分析样本": "sample"}
KIND_HEADERS = ("kind", "类型", "口径")
NOTE_HEADERS = ("note", "备注", "说明")
KIND_ALIASES = {"stage": "stage", "阶段": "stage", "累计": "stage", "累计口径": "stage",
                "excluded": "excluded", "排除": "excluded", "剔除": "excluded",
                "剔除数": "excluded", "model": "model", "模型": "model",
                "模型样本": "model"}
MODEL_FILE_RE = re.compile(r"^(?:coef_.*|fit)\.csv$", re.I)
TABLE_FILE_RE = re.compile(r"^table(a?)0*(\d+)", re.I)
# Numbers inside these columns are identifiers (dates, case numbers, paths), not
# statistics; letting them into the index makes V-03 trace anything to a path.
ID_COLUMN_RE = re.compile(
    r"^(?:id|doc_?id|file|filename|file_?name|path|rel_?path|case_?no|"
    r"文件|文件名|路径|相对路径|编号|图号|案号)$", re.I)
P_COLUMN_RE = re.compile(r"^(?:p|p_?value|p_?val|p值|显著性|sig)$", re.I)

# V-03 semantic classes (R3-01).  A number in the prose may only be evidenced by
# a cell that measures the same thing: a p-value column cannot prove a share,
# and an estimate column cannot prove a sample size.
COUNT_COLUMN_RE = re.compile(
    r"^(?:n|样本量|样本数|样本|count|频数|案例数|个数|数量|size|frequency)$", re.I)
EST_COLUMN_RE = re.compile(
    r"^(?:or|hr|rr|beta|β|b|est|estimate|coef|系数|估计|统计量|stat|chi2|χ2|"
    r"t值|z值|f值|r)$", re.I)
PCT_COLUMN_RE = re.compile(r"(?:%|占比|比例|百分比|率|percent|pct|rate)", re.I)
SEMANTIC_POOLS = ("count", "estimate", "p", "pct", "raw")
TEXT_SEMANTICS = {"N": "count", "stat": "estimate", "p<": "p", "p=": "p", "pct": "pct"}
SEVERITIES = ("error", "warning", "info")
# A p-value cell may carry its comparison operator ("<0.001"); the operator is
# part of the evidence (R3-02).
SAMPLE_FULL_ALIASES = {"full", "all", "全部", "全样本", "总体", "无"}

CELL_NUMBER_RE = re.compile(r"^-?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?$")
TOKEN_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
OP_TOKEN_RE = re.compile(
    r"(<=|<|＝|=|＜)?\s*(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
THOUSAND_GAP_RE = re.compile(r"(?<=\d)[ \u00a0](?=\d)")

TEXT_PATTERNS = (
    ("N", re.compile(r"[NＮ]\s*[=＝]\s*([0-9][0-9,，\u00a0 ]*)")),
    ("N", re.compile(r"([0-9][0-9,，\u00a0 ]*)\s*(?:份|个|件|人|条)")),
    ("stat", re.compile(r"(?<![A-Za-z])(?:OR|HR|RR|β|B|r)\s*[=＝]\s*(-?\d+(?:\.\d+)?)", re.I)),
    ("p<", re.compile(r"[pP]\s*[<＜]\s*(\d*\.?\d+)")),
    ("p=", re.compile(r"[pP]\s*[=＝]\s*(\d*\.?\d+)")),
    ("pct", re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")),
)


def fmt_number(value) -> str:
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6g}"


def to_number(value):
    """Parse one table cell into a float, or None when it is not a number.

    Percentages are scaled to proportions so that 65.7% and 0.657 compare
    equal; both sides of a comparison go through this function.
    """
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", " ").replace("，", ",")
    text = text.replace(" ", "")
    if not text:
        return None
    scale = 1.0
    if text.endswith("%"):
        text = text[:-1]
        scale = 0.01
    if not CELL_NUMBER_RE.match(text):
        return None
    try:
        return float(text.replace(",", "")) * scale
    except ValueError:
        return None


def cell_tokens_ops(value) -> list[tuple[str, float]]:
    """Every (operator, number) pair in a cell, keeping "<0.001" comparisons."""
    text = str(value or "")
    if not text:
        return []
    text = text.replace("\u00a0", " ").replace("，", ",")
    text = THOUSAND_GAP_RE.sub("", text)
    tokens = []
    for match in OP_TOKEN_RE.finditer(text):
        op = (match.group(1) or "=").replace("＜", "<").replace("＝", "=")
        try:
            tokens.append((op, float(match.group(2).replace(",", ""))))
        except ValueError:
            continue
    return tokens


def cell_tokens(value) -> list[float]:
    """Every numeric token inside a cell ("N=2713", "中位67,100元")."""
    return [number for _op, number in cell_tokens_ops(value)]


def column_semantics(name) -> str:
    """Semantic class of a table column, used to keep V-03 evidence same-kind."""
    text = str(name or "").strip()
    if not text:
        return "raw"
    if P_COLUMN_RE.match(text):
        return "p"
    if COUNT_COLUMN_RE.match(text):
        return "count"
    if EST_COLUMN_RE.match(text):
        return "estimate"
    if PCT_COLUMN_RE.search(text):
        return "pct"
    return "raw"


def token_semantics(kind: str) -> str:
    """Semantic class of a prose number, from the pattern that matched it."""
    return TEXT_SEMANTICS.get(kind, "raw")


def is_identifier_column(name) -> bool:
    """True for columns whose numbers identify rows instead of measuring them."""
    return bool(ID_COLUMN_RE.match(str(name or "").strip()))


def normalize_scope(value) -> str:
    """Map a declared scope ("corpus"/"sample"/语料/样本) to its canonical form."""
    return SCOPE_ALIASES.get(str(value or "").strip().lower(), "")


def normalize_kind(value) -> str:
    """Map a sample_flow kind ("stage"/"excluded"/累计/剔除) to its canonical form."""
    return KIND_ALIASES.get(str(value or "").strip().lower(), "")


def parse_scope_map(items) -> dict:
    """Parse repeated "name=scope" arguments into {basename: scope}."""
    mapping = {}
    for item in items or []:
        name, _, scope = str(item).partition("=")
        name, scope = name.strip(), normalize_scope(scope)
        if not name or not scope:
            raise ValueError(f"作用域声明应为 表名=sample|corpus，收到 {item!r}")
        mapping[os.path.basename(name)] = scope
        stem = os.path.splitext(os.path.basename(name))[0]
        mapping.setdefault(stem, scope)
    return mapping


def is_total_label(text) -> bool:
    label = str(text or "").strip().lower()
    if not label:
        return False
    if label in TOTAL_LABELS:
        return True
    return label.startswith(("合计", "总计", "小计", "total", "sum"))


def is_note_row(row) -> bool:
    first = next((str(value).strip() for value in row.values() if str(value or "").strip()), "")
    if not first:
        return False
    if first.startswith(("注", "Note", "note", "说明")):
        return True
    return bool(N_RE.search(first))


class Table:
    def __init__(self, path: str, rows: list[dict]):
        self.path = path
        self.name = os.path.basename(path)
        self.rows = rows
        self.header = list(rows[0].keys()) if rows else []


class Figure:
    def __init__(self, series, number, sub, n, is_range, caption, where, scope=""):
        self.series = series
        self.number = number
        self.sub = sub
        self.n = n
        self.is_range = is_range
        self.caption = caption
        self.where = where
        # "corpus" (full corpus) or "sample" (analysis sample); "" = undeclared.
        self.scope = scope

    @property
    def id(self) -> str:
        return f"{self.series}{self.number}{self.sub}"


class Report:
    def __init__(self):
        self.issues: list[dict] = []
        self.traces: list[dict] = []
        self.checked = 0
        self.traced = 0

    def add(self, severity, check, where, expected="", actual="", detail=""):
        if severity not in SEVERITIES:
            # A typo here would silently defeat --fail-on-warn, so fail loudly.
            raise ValueError(f"severity must be one of {SEVERITIES}, got {severity!r}")
        self.issues.append({
            "severity": severity,
            "check": check,
            "where": str(where),
            "expected": fmt_number(expected) if not isinstance(expected, str) else expected,
            "actual": fmt_number(actual) if not isinstance(actual, str) else actual,
            "detail": str(detail),
        })

    def error(self, check, where, expected="", actual="", detail=""):
        self.add("error", check, where, expected, actual, detail)

    def warning(self, check, where, expected="", actual="", detail=""):
        self.add("warning", check, where, expected, actual, detail)

    def info(self, check, where, expected="", actual="", detail=""):
        self.add("info", check, where, expected, actual, detail)

    @property
    def errors(self) -> int:
        return sum(1 for issue in self.issues if issue["severity"] == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for issue in self.issues if issue["severity"] == "warning")

    @property
    def infos(self) -> int:
        return sum(1 for issue in self.issues if issue["severity"] == "info")

    @property
    def ignored(self) -> int:
        """Numbers dropped by --ignore; info rows of other checks do not count."""
        return sum(1 for issue in self.issues if issue["check"] == "V-03-ignored")


# --------------------------------------------------------------------------
# loading helpers -- every failure becomes a located error, never a silent skip
# --------------------------------------------------------------------------

def load_tables(directory: str, report: Report) -> list[Table]:
    if not os.path.exists(directory):
        report.error("input", directory, "目录存在", "不存在", "无法读取表格目录")
        return []
    if os.path.isfile(directory):
        paths = [directory]
    else:
        paths = sorted(
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith(".csv")
        )
    if not paths:
        report.error("input", directory, "至少一个 *.csv", "0 个", "表格目录里没有 CSV")
        return []
    tables = []
    for path in paths:
        try:
            rows = read_rows(path)
        except Exception as exc:  # noqa: BLE001 - reported with class + message
            report.error("parse", os.path.basename(path), "可解析的 CSV", "解析失败",
                         f"{type(exc).__name__}: {exc}")
            continue
        tables.append(Table(path, rows))
    return tables


def find_table_n(table: Table):
    """Return (n, where) for the sample size stated inside a table."""
    for row_no, row in enumerate(table.rows, start=2):
        for col, value in row.items():
            match = N_RE.search(str(value or ""))
            if not match:
                continue
            n, _ = parse_n(match.group(1))
            if n is not None:
                return n, f"{table.name}:{row_no}:{col}"
    for row_no, row in enumerate(table.rows, start=2):
        cells = [str(value or "") for value in row.values()]
        if cells and any(key in cells[0] for key in ("样本量", "样本数", "总样本", "N（", "N(")):
            for value in cells[1:]:
                n, _ = parse_n(value)
                if n is not None:
                    return n, f"{table.name}:{row_no}"
    return None, ""


def load_manifest(path: str, report: Report) -> list[Figure]:
    try:
        rows = read_rows(path)
    except Exception as exc:  # noqa: BLE001
        report.error("parse", os.path.basename(path), "可解析的 CSV", "解析失败",
                     f"{type(exc).__name__}: {exc}")
        return []
    if not rows:
        report.error("V-02", os.path.basename(path), "至少一行图注", "0 行", "manifest 为空或只有表头")
        return []
    name = os.path.basename(path)
    header = list(rows[0].keys())
    lowered = {col.strip().lower(): col for col in header}
    id_col = next((col for col in header if col.strip().lower() in FIG_ID_HEADERS), None)
    caption_col = next((col for col in header if col.strip().lower() in CAPTION_HEADERS), None)
    n_col = lowered.get("n")
    scope_col = next((col for col in header if col.strip().lower() in SCOPE_HEADERS), None)
    status_col = next((col for col in header if col.strip().lower() in STATUS_HEADERS), None)
    number_col = next((col for col in header if col.strip().lower() in NUMBER_HEADERS), None)
    if id_col is None and number_col is None:
        report.error("V-02", name, "id/figure 列", str(header),
                     "manifest 缺少图号列（id/figure/图号/figure_no）")
        return []
    figures = []
    next_number = 1
    for index, row in enumerate(rows, start=2):
        where = f"{name}:{index}"
        if status_col is not None:
            status = str(row.get(status_col) or "").strip().lower()
            if status and status not in STATUS_OK:
                report.info("V-02", where, "status=ok", status,
                            "该行 status 不是 ok，已跳过（不参与图号与 N 校验）")
                continue
        parsed = None
        if number_col is not None:
            parsed = parse_fig_id(row.get(number_col))
        if parsed is None and id_col is not None:
            parsed = parse_fig_id(row.get(id_col))
        if parsed is None and caption_col:
            # An explicit "图N" in the caption wins over the row order.
            parsed = parse_fig_id(row.get(caption_col))
        by_order = parsed is None
        if by_order:
            # chart_pack manifests use package ids (A01/F01/G01); the manuscript
            # order is the only book-level figure number they carry.
            series, number, sub = "图", next_number, ""
        else:
            series, number, sub = parsed
        next_number = max(next_number, number + 1)
        caption = str(row.get(caption_col) or "") if caption_col else ""
        n, is_range = (None, False)
        if n_col is not None:
            n, is_range = parse_n(row.get(n_col))
        if n is None:
            match = N_RE.search(caption)
            if match:
                n, is_range = parse_n(match.group(1))
        if n is None:
            report.error("V-02", where, "caption 含 N=", caption[:40] or "(空)",
                         "图注里没有可解析的 N")
            continue
        if by_order:
            report.traces.append({
                "number": f"{series}{number}",
                "source_file": where,
                "source_row": str(index),
                "source_col": "id",
                "matched_by": "manifest-order",
            })
        figures.append(Figure(series, number, sub, n, is_range, caption, where,
                              normalize_scope(row.get(scope_col)) if scope_col else ""))
    _check_duplicate_figures(figures, report)
    return figures


def _check_duplicate_figures(figures, report):
    """Two rows claiming one book-level figure number is a real conflict."""
    seen = {}
    for figure in figures:
        seen.setdefault((figure.series, figure.number), []).append(figure)
    for (series, number), items in seen.items():
        if len(items) > 1:
            report.error("V-02", f"{series}{number} 图号", "一个图号只对应一行",
                         "、".join(item.where for item in items),
                         f"{series}{number} 被 {len(items)} 行 manifest 占用")


def parse_fig_id(text):
    """Return (series, number, sub) for 图3 / Figure 3 / 附图1 / Figure1a."""
    match = re.search(r"(附图|附录|appendix|figure|fig\.?|图)\s*([0-9]+)\s*([a-zA-Z]?)",
                      str(text or ""), re.I)
    if not match:
        return None
    prefix = match.group(1).lower()
    series = "附图" if prefix in ("附图", "附录", "appendix") else "图"
    return series, int(match.group(2)), (match.group(3) or "").lower()


def load_sample_flow(path: str, report: Report):
    """Return (list of n, list of (stage, n, kind), has_kind_column)."""
    try:
        rows = read_rows(path)
    except Exception as exc:  # noqa: BLE001
        report.error("parse", os.path.basename(path), "可解析的 CSV", "解析失败",
                     f"{type(exc).__name__}: {exc}")
        return [], [], False
    if not rows:
        report.error("V-06", os.path.basename(path), "至少一行", "0 行", "sample_flow 为空")
        return [], [], False
    header = list(rows[0].keys())
    n_col = next((col for col in header if col.strip().lower() == "n"), None)
    stage_col = next((col for col in header if col.strip().lower() in ("stage", "阶段", "步骤")), None)
    kind_col = next((col for col in header if col.strip().lower() in KIND_HEADERS), None)
    note_col = next((col for col in header if col.strip().lower() in NOTE_HEADERS), None)
    if n_col is None:
        report.error("V-06", os.path.basename(path), "n 列", str(header), "sample_flow 缺少 n 列")
        return [], [], False
    stages, numbers = [], []
    for index, row in enumerate(rows, start=2):
        n, _ = parse_n(row.get(n_col))
        stage = str(row.get(stage_col) or f"第{index - 1}行") if stage_col else f"第{index - 1}行"
        if n is None:
            report.error("V-06", f"{os.path.basename(path)}:{index}", "整数 n",
                         str(row.get(n_col)), "n 不是可解析的数字")
            continue
        kind = "stage"
        if kind_col:
            raw_kind = str(row.get(kind_col) or "").strip()
            kind = normalize_kind(raw_kind)
            if not kind:
                report.error("V-06", f"{os.path.basename(path)}:{index}",
                             "kind ∈ stage|excluded|model", raw_kind,
                             "kind 只能是 stage（累计）、excluded（本步剔除数）"
                             "或 model（模型样本）")
                continue
        note = str(row.get(note_col) or "") if note_col else ""
        stages.append((stage, n, kind, note))
        numbers.append(n)
    return numbers, stages, bool(kind_col)


def read_text_file(path: str) -> str:
    last_error = None
    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            with open(path, encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        return handle.read()


def read_docx_text(path: str) -> str:
    from docx import Document

    document = Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    return "\n".join(parts)


# --------------------------------------------------------------------------
# V-01 表内合计
# --------------------------------------------------------------------------

def check_category_counts(table: Table, flow_numbers, tolerance, report: Report):
    note_n, note_where = find_table_n(table)
    count_cols = [col for col in table.header if col.strip().lower() in COUNT_HEADERS]
    if not count_cols:
        return
    data_rows = [
        row for row in table.rows
        if not is_note_row(row) and not any(is_total_label(row.get(col)) for col in table.header)
    ]
    if not data_rows or len(data_rows) > 12:
        return
    for col in count_cols:
        values = [to_number(row.get(col)) for row in data_rows]
        if any(value is None for value in values) or not values:
            continue
        total = sum(values)
        if note_n is not None:
            if abs(total - note_n) > tolerance:
                report.error("V-01", note_where or table.name, note_n, total,
                             f"分类变量 {col} 各水平计数之和 {fmt_number(total)} ≠ 表注 N={note_n}")
        elif flow_numbers:
            if not any(abs(total - stage_n) <= tolerance for stage_n in flow_numbers):
                report.error("V-01", f"{table.name}:{col}", "sample_flow 中的某个 stage",
                             total, f"分类变量 {col} 计数之和 {fmt_number(total)} 与 sample_flow 任何 stage 都不一致")


def check_totals(table: Table, flow_numbers, tolerance, report: Report):
    if not table.rows:
        return
    total_indexes = {
        index for index, row in enumerate(table.rows)
        if any(is_total_label(row.get(col)) for col in table.header)
    }
    if total_indexes:
        for index in sorted(total_indexes):
            row = table.rows[index]
            label_cols = {col for col in table.header if is_total_label(row.get(col))}
            for col in table.header:
                if col in label_cols:
                    continue
                actual = to_number(row.get(col))
                if actual is None:
                    continue
                parts = [
                    to_number(other.get(col))
                    for position, other in enumerate(table.rows)
                    if position not in total_indexes
                ]
                parts = [value for value in parts if value is not None]
                if len(parts) < 2:
                    continue
                expected = sum(parts)
                if abs(expected - actual) > tolerance:
                    report.error("V-01", f"{table.name}:row{index + 2}:{col}", expected, actual,
                                 f"合计行 {col}={fmt_number(actual)}，其余各行之和={fmt_number(expected)}，"
                                 f"差 {fmt_number(abs(expected - actual))}")
        for col in table.header:
            if not is_total_label(col):
                continue
            for index, row in enumerate(table.rows):
                if index in total_indexes:
                    continue
                actual = to_number(row.get(col))
                if actual is None:
                    continue
                parts = [
                    to_number(row.get(other))
                    for other in table.header
                    if other != col and not is_total_label(other)
                ]
                parts = [value for value in parts if value is not None]
                if len(parts) < 2:
                    continue
                expected = sum(parts)
                if abs(expected - actual) > tolerance:
                    report.error("V-01", f"{table.name}:row{index + 2}:{col}", expected, actual,
                                 f"合计列 {col}={fmt_number(actual)}，同行其余列之和={fmt_number(expected)}，"
                                 f"差 {fmt_number(abs(expected - actual))}")
    check_category_counts(table, flow_numbers, tolerance, report)


# --------------------------------------------------------------------------
# V-02 表图同值
# --------------------------------------------------------------------------

def table_scope_of(table, scope_map, explicit_only=False) -> str:
    """Scope of a table: CLI declaration > its own n_scope column > sample.

    With explicit_only=True an undeclared table returns "" instead of the
    "sample" default, so V-02 can tell "declared sample" from "never said".
    """
    if table.name in scope_map:
        return scope_map[table.name]
    stem = os.path.splitext(table.name)[0]
    if stem in scope_map:
        return scope_map[stem]
    for col in table.header:
        if col.strip().lower() in SCOPE_HEADERS:
            values = {normalize_scope(row.get(col)) for row in table.rows}
            values.discard("")
            if len(values) == 1:
                return values.pop()
    return "" if explicit_only else "sample"


def check_figure_vs_table(figures, tables, report: Report, table_scopes=None, corpus_numbers=()):
    """Compare a figure's N with its table only when both sides declare a scope.

    Pairing figure 2 with table2 by number alone is a guess: in the real project
    figure 2 counts the corpus (2878) while table2 describes the analysis sample
    (2713), and the guess produced a false error (R3-05).
    """
    table_scopes = table_scopes or {}
    corpus_numbers = list(corpus_numbers)
    by_key = {}
    for table in tables:
        match = TABLE_FILE_RE.match(table.name)
        if not match:
            continue
        series = "附图" if match.group(1) else "图"
        by_key.setdefault((series, int(match.group(2))), []).append(table)
    for figure in figures:
        if figure.is_range:
            continue
        paired = by_key.get((figure.series, figure.number), [])
        figure_scope = figure.scope or ""
        if figure_scope == "corpus":
            _check_corpus_figure(figure, paired, table_scopes, corpus_numbers, report)
            continue
        for table in paired:
            table_scope = table_scope_of(table, table_scopes, explicit_only=True)
            n, where = find_table_n(table)
            if not figure_scope or not table_scope:
                report.info("V-02", f"{figure.where} vs {table.name}", figure.n,
                            n if n is not None else "",
                            f"{figure.id} N={fmt_number(figure.n)} 与 {table.name} "
                            f"N={fmt_number(n) if n is not None else '未声明'} 未配对："
                            "图与表只有编号相同，需用 --figure-scope/--table-scope "
                            "声明同一口径后才做数值比对")
                continue
            report.traces.append({
                "number": fmt_number(figure.n),
                "source_file": figure.where,
                "source_row": figure.id,
                "source_col": "V-02-pair",
                "matched_by": f"{table.name} (scope={table_scope})",
            })
            if table_scope != figure_scope:
                report.warning("V-02", f"{figure.where} vs {table.name}", figure.n,
                               n if n is not None else "",
                               f"{figure.id} scope={figure_scope}（N={fmt_number(figure.n)}），"
                               f"{table.name} scope={table_scope}"
                               f"（N={fmt_number(n) if n is not None else '未声明'}）："
                               "两边分母不同，不做数值比对")
                continue
            if n is None:
                report.warning("V-02", table.name, figure.n, "",
                               f"表 {table.name} 未声明 N，无法与 {figure.id} 的图注比对")
                continue
            if abs(n - figure.n) > 0.5:
                report.error("V-02", f"{figure.where} vs {where}", figure.n, n,
                             f"{figure.id} 图注 N={figure.n}，{table.name} N={n}，"
                             f"差 {fmt_number(abs(n - figure.n))}")


def _check_corpus_figure(figure, paired, table_scopes, corpus_numbers, report):
    """A corpus-scope figure is measured against the corpus, not against a sample table."""
    corpus_tables = [table for table in paired
                     if table_scope_of(table, table_scopes) == "corpus"]
    if corpus_tables:
        for table in corpus_tables:
            n, where = find_table_n(table)
            if n is None:
                report.warning("V-02", table.name, figure.n, "",
                               f"表 {table.name} 未声明 N，无法与 {figure.id} 的图注比对")
            elif abs(n - figure.n) > 0.5:
                report.error("V-02", f"{figure.where} vs {where}", figure.n, n,
                             f"{figure.id} 图注 N={figure.n}，{table.name}（corpus）N={n}，"
                             f"差 {fmt_number(abs(n - figure.n))}")
    elif corpus_numbers:
        if figure.n not in corpus_numbers:
            report.error("V-02", figure.where,
                         "/".join(fmt_number(number) for number in corpus_numbers[:5]),
                         figure.n,
                         f"{figure.id} 声明 scope=corpus，N={figure.n} 不在 sample_flow 的任何 "
                         "stage 里（语料总量与各阶段累计数均对不上）")
    else:
        report.warning("V-02", figure.where, "语料总量", "未提供",
                       f"{figure.id} 声明 scope=corpus，但没有 --sample-flow 也没有 corpus "
                       "口径的表，无法核对语料总量")
    for table in paired:
        table_scope = table_scope_of(table, table_scopes)
        if table_scope == "corpus":
            continue
        n, _where = find_table_n(table)
        report.warning("V-02", f"{figure.where} vs {table.name}", figure.n,
                       n if n is not None else "",
                       f"{figure.id} scope=corpus（N={fmt_number(figure.n)}），"
                       f"{table.name} scope={table_scope}"
                       f"（N={fmt_number(n) if n is not None else '未声明'}）："
                       "两边分母不同，不做数值比对")


# --------------------------------------------------------------------------
# V-03 正文数字溯源
# --------------------------------------------------------------------------

def is_legal_citation(text: str, start: int, end: int) -> bool:
    """True for "第 1234 条" style references: a statute article, not a statistic."""
    if not re.search(r"[条款项章节]\s*$", text[start:end]):
        return False
    return bool(re.search(r"第\s*$", text[max(0, start - 4):start]))


def extract_text_numbers(text: str):
    """Yield (start, kind, value, raw) for every number the contract cares about."""
    matches = []
    for kind, pattern in TEXT_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0)
            if kind == "N":
                digits = re.sub(r"[^\d]", "", match.group(1))
                if not digits:
                    continue
                value = float(digits)
            else:
                try:
                    value = float(match.group(1))
                except ValueError:
                    continue
            if is_legal_citation(text, match.start(), match.end()):
                continue
            matches.append((match.start(), match.end(), kind, value, raw))
    # Longer/earlier match wins: "N=1 358 份" must not also count as "358 份".
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept = []
    for item in matches:
        if any(not (item[1] <= other[0] or item[0] >= other[1]) for other in kept):
            continue
        kept.append(item)
    return kept


def build_table_index(tables):
    """Map semantic class -> [(op, value, where)] for every table cell.

    Identifier-like columns (rel_path/file/case_no/...) are skipped: a year or a
    case number inside a file name is not a statistic and would make V-03 trace
    text numbers to a path fragment.  The semantic class comes from the column
    name so that a p-value cell can never stand in for a percentage (R3-01).
    """
    index = {key: [] for key in SEMANTIC_POOLS}
    for table in tables:
        for row_no, row in enumerate(table.rows, start=2):
            for col, value in row.items():
                if is_identifier_column(col):
                    continue
                semantic = column_semantics(col)
                for op, number in cell_tokens_ops(value):
                    where = f"tables/{table.name}:{row_no}:{col}"
                    index[semantic].append((op, number, where))
    return index


def find_evidence(index, semantic, kind, value, tolerance) -> str:
    """Where a same-semantic cell proves `value`, or "" when there is none.

    "raw" columns (descriptive 取值/备注 style) are the last resort: they carry
    no declared measure, so they may back any prose number, but only after the
    typed pools failed.
    """
    for pool in (semantic, "raw"):
        for op, candidate, where in index.get(pool, ()):
            if kind == "p<":
                # The table's own "<0.001" matches "<.001"; a concrete p passes
                # only when it is really smaller than the prose bound (R3-02).
                if op == "<" and abs(candidate - value) <= tolerance:
                    return where
                if op == "=" and candidate < value:
                    return where
            elif kind == "p=":
                if op == "=" and abs(candidate - value) <= tolerance:
                    return where
            elif matches_value(kind, value, candidate, tolerance):
                return where
    return ""


def load_numbers_csv(path: str, report: Report):
    """Load --numbers rows: at least a value column, optional label/source."""
    try:
        rows = read_rows(path)
    except Exception as exc:  # noqa: BLE001
        report.error("parse", os.path.basename(path), "可解析的 CSV", "解析失败",
                     f"{type(exc).__name__}: {exc}")
        return []
    if not rows:
        return []
    header = {col.strip().lower(): col for col in rows[0].keys()}
    value_col = next((header[key] for key in ("value", "数值", "val") if key in header), None)
    if value_col is None:
        report.error("input", os.path.basename(path), "value 列", str(list(rows[0].keys())),
                     "--numbers 至少要有 value 列（可选 label,source）")
        return []
    label_col = next((header[key] for key in ("label", "标签", "说明") if key in header), None)
    entries = []
    for index, row in enumerate(rows, start=2):
        number = to_number(row.get(value_col))
        if number is None:
            report.error("parse", f"{os.path.basename(path)}:{index}", "数字",
                         row.get(value_col), "--numbers 的 value 不是数字")
            continue
        entries.append({
            "value": number,
            "label": str(row.get(label_col) or "") if label_col else "",
            "path": os.path.basename(path),
            "row": index,
        })
    return entries


FIGURE_DATA_HEADERS = ("figure", "label", "value")


def load_figure_data(paths, report: Report):
    """Load --figure-data CSVs: numbers printed inside figures (figure,label,value).

    A number that exists only in a figure (the 808 cases of figure 2c) still has
    a legitimate source; declaring it here keeps V-03 honest instead of widening
    the matcher.  Only count/pct values are accepted: a figure's amount must not
    be allowed to "prove" a p value.
    """
    entries = []
    for path in paths or []:
        try:
            rows = read_rows(path)
        except Exception as exc:  # noqa: BLE001
            report.error("parse", os.path.basename(path), "可解析的 CSV", "解析失败",
                         f"{type(exc).__name__}: {exc}")
            continue
        header = {col.strip().lower(): col for col in (rows[0].keys() if rows else [])}
        missing = [key for key in FIGURE_DATA_HEADERS if key not in header]
        if missing:
            report.error("input", os.path.basename(path), "figure,label,value",
                         "缺少列 " + ", ".join(missing),
                         "--figure-data 的列固定为 figure,label,value")
            continue
        for index, row in enumerate(rows, start=2):
            label = str(row.get(header["label"]) or "").strip()
            figure = str(row.get(header["figure"]) or "").strip()
            value = to_number(row.get(header["value"]))
            where = f"{os.path.basename(path)}:{index}"
            if value is None:
                report.error("parse", where, "数字", row.get(header["value"]),
                             "--figure-data 的 value 不是数字")
                continue
            semantic = "pct" if ("%" in label or PCT_COLUMN_RE.search(label)) else "count"
            entries.append({
                "figure": figure,
                "label": label,
                "value": value,
                "semantic": semantic,
                "where": where,
                "path": os.path.basename(path),
                "row": index,
            })
    return entries


def matches_value(kind: str, value: float, candidate: float, tolerance: float) -> bool:
    if kind == "pct":
        # Compare in percentage points: 65.7% matches 65.7 and 0.657, but a
        # tolerance of 0.5 must not turn "1" into a match for "50.7%".
        return (abs(candidate - value) <= tolerance
                or abs(candidate * 100.0 - value) <= tolerance)
    return abs(candidate - value) <= tolerance


def check_text_numbers(text: str, source: str, tables, numbers_csv, report: Report,
                       tolerance: float, ignore_patterns=(), figure_data=()):
    index = build_table_index(tables)
    for start, _end, kind, value, raw in extract_text_numbers(text):
        line = text.count("\n", 0, start) + 1
        ignored = next((pattern for pattern in ignore_patterns if pattern.search(raw)), None)
        if ignored is not None:
            # Never silent: the skip itself is recorded as an info row.
            report.info("V-03-ignored", f"{source}:{line}: {raw}", "", "",
                        f"命中 --ignore {ignored.pattern}，跳过溯源")
            continue
        semantic = token_semantics(kind)
        where = f"{source}:{line}: {raw}"
        matched_by = ""
        trace = {
            "number": raw,
            "source_file": source,
            "source_row": line,
            "source_col": kind,
            "matched_by": "none",
        }
        figure_hit = find_figure_data(figure_data, semantic, kind, value, tolerance)
        if figure_hit is not None:
            # A declared figure number is a real source, but it is weaker than a
            # table cell, so the hit is recorded as info rather than passing mute.
            matched_by = "figure-data"
            trace.update({
                "source_file": figure_hit["path"],
                "source_row": str(figure_hit["row"]),
                "source_col": "value",
            })
            report.info("V-03-figure", where, figure_hit["value"], value,
                        f"由 {figure_hit['figure'] or '未命名图'}（{figure_hit['label']}）提供，"
                        f"见 {figure_hit['where']}（--figure-data）")
        else:
            numbers_hit = find_numbers_entry(numbers_csv, kind, value, tolerance)
            if numbers_hit is not None:
                matched_by = "numbers"
                trace.update({"source_file": "numbers.csv", "source_row": str(numbers_hit["row"]),
                              "source_col": "value"})
                report.info("V-03-numbers", where, numbers_hit["value"], value,
                            f"由 --numbers 提供（{numbers_hit['label'] or '未命名'}，"
                            f"见 {numbers_hit['path']}:{numbers_hit['row']}）")
            else:
                matched_by = find_evidence(index, semantic, kind, value, tolerance)
                if not matched_by:
                    _report_untraced(source, line, kind, value, raw, semantic, index, tables, report)
        trace["matched_by"] = matched_by or "none"
        report.checked += 1
        if matched_by:
            report.traced += 1
        report.traces.append(trace)


def find_numbers_entry(entries, kind, value, tolerance):
    """First --numbers row equal to the prose number, or None.

    numbers.csv is the declared home for narrative counts that never appear in a
    table (3 107 份, 5 750 个 ...), so a hit is recorded as info, not silently.
    """
    for entry in entries or ():
        if matches_value(kind, value, entry["value"], tolerance):
            return entry
    return None


def find_figure_data(entries, semantic, kind, value, tolerance):
    """First --figure-data row that can prove the prose number, or None.

    Only count/pct entries qualify: the amount printed in a figure must never be
    accepted as evidence for a p value or an estimate.
    """
    if semantic not in ("count", "pct"):
        return None
    for entry in entries or ():
        if entry["semantic"] != semantic:
            continue
        if matches_value(kind, value, entry["value"], tolerance):
            return entry
    return None


def _report_untraced(source, line, kind, value, raw, semantic, index, tables, report):
    """Explain why a prose number has no evidence, naming the semantic pool."""
    where = f"{source}:{line}: {raw}"
    if kind == "p=":
        shadow = next((spot for op, candidate, spot in index.get("p", ())
                       if op == "<" and abs(candidate - value) <= tolerance_slack(value)), "")
        if shadow:
            report.error("V-03", where, f"表里有确定的 p = {fmt_number(value)}",
                         f"只有上界 p < {fmt_number(value)}",
                         f"正文写 {raw}，但 {shadow} 只给了上界，没有确定值")
            return
    if kind == "p<":
        report.error("V-03", where, f"表中有 p < {fmt_number(value)}", "没有",
                     f"正文写 {raw}，但所有表里都没有可比的 p 值（同语义 p 列）")
        return
    report.error("V-03", where, f"表格中存在同语义（{semantic}）的数值", "未找到",
                 f"正文数字 {raw}（{fmt_number(value)}，语义 {semantic}）在 {len(tables)} 个表里"
                 "找不到同语义的单元格；其他语义的列（如 est 列、p 列）不能作为证据")


def tolerance_slack(value: float) -> float:
    """Absolute tolerance used when matching p-value bounds ("<.001" vs 0.001)."""
    return max(abs(value) * 1e-6, 1e-12)


# --------------------------------------------------------------------------
# V-04 图号连续且被引用
# --------------------------------------------------------------------------

def check_figure_numbering(figures, text, report: Report):
    by_series = {}
    for figure in figures:
        by_series.setdefault(figure.series, set()).add(figure.number)
    for series, numbers in by_series.items():
        missing = [number for number in range(1, max(numbers) + 1) if number not in numbers]
        if missing:
            report.error("V-04", f"{series}编号", f"1..{max(numbers)} 连续",
                         "缺少 " + "、".join(f"{series}{number}" for number in missing),
                         f"{series}号不连续，缺 {len(missing)} 个")
    if not text:
        return
    for figure in figures:
        if figure.series == "附图":
            pattern = rf"(?:附图|附录|Appendix)\s*0*{figure.number}(?!\d)"
        else:
            pattern = rf"(?<!附)(?:图|Figure|Fig\.?)\s*0*{figure.number}(?!\d)"
        if not re.search(pattern, text, re.I):
            report.warning("V-04", figure.where, f"正文引用 {figure.id}", "未找到",
                           f"正文没有引用 {figure.id}")


# --------------------------------------------------------------------------
# V-05 样本 N 跨表一致
# --------------------------------------------------------------------------

def check_model_n(tables, report: Report):
    """Models that claim the same scope must report the same N.

    `sample` groups the comparison ("full" is not a subset: auto_stats writes it
    on every row, and treating it as "declared subset" silently disabled this
    check -- R3-04).  A row that declares a different n_scope is excluded from
    the baseline and the exclusion is written to number_trace.csv.
    """
    entries = []
    for table in tables:
        lowered = {col.strip().lower(): col for col in table.header}
        is_model = bool(MODEL_FILE_RE.match(table.name)) or "n_scope" in lowered
        if not is_model:
            continue
        n_col = lowered.get("n")
        if n_col is None:
            continue
        scope_col = next((lowered[key] for key in SCOPE_HEADERS if key in lowered), None)
        sample_col = next((lowered[key] for key in SAMPLE_HEADERS if key in lowered), None)
        for index, row in enumerate(table.rows, start=2):
            n, _ = parse_n(row.get(n_col))
            if n is None:
                continue
            declared_scope = normalize_scope(row.get(scope_col)) if scope_col else ""
            scope = declared_scope or "sample"
            sample = str(row.get(sample_col) or "").strip() if sample_col else ""
            if sample.strip().lower() in SAMPLE_FULL_ALIASES:
                sample = ""
            entries.append((scope, sample, n, declared_scope, f"{table.name}:{index}"))
    groups = {}
    for entry in entries:
        groups.setdefault(entry[1], []).append(entry)
    for sample, items in groups.items():
        # Within one sample group, the dominant n_scope sets the baseline; a row
        # that explicitly declares another scope is excluded (and traced) rather
        # than reported as a mismatch.
        dominant = Counter(entry[0] for entry in items).most_common(1)[0][0]
        same_scope = [entry for entry in items if entry[0] == dominant]
        baseline = Counter(entry[2] for entry in same_scope).most_common(1)[0][0]
        for scope, _sample, n, declared_scope, where in items:
            if scope != dominant:
                report.info("V-05", where, baseline, n,
                            f"该行声明 n_scope={declared_scope or scope}，与基准口径 "
                            f"{dominant}（N={baseline}）不同，已排除比较")
                report.traces.append({
                    "number": fmt_number(n),
                    "source_file": where,
                    "source_row": "",
                    "source_col": "V-05-scope",
                    "matched_by": f"excluded: n_scope={declared_scope or scope}",
                })
                continue
            if n == baseline:
                continue
            group = f"n_scope={dominant}" + (f", sample={sample}" if sample else "")
            report.error("V-05", where, baseline, n,
                         f"同一 {group} 的模型表 N 不一致（{baseline} vs {n}）")


# --------------------------------------------------------------------------
# V-06 漏斗对账
# --------------------------------------------------------------------------

KIND_HINT = "；修法：在 sample_flow.csv 加一列 kind，剔除行写 excluded，累计行写 stage"
KIND_MISSING = ("该行缺 kind，按 stage 处理；若此行不是漏斗阶段请补 "
                "kind=excluded|model")
STAGE_REF_RE = re.compile(r"stage\s*[=＝:：]\s*([^;；,，]+)")


def model_stage_ref(note) -> str:
    """Return the stage name a model row points at ("note=stage=分析样本")."""
    match = STAGE_REF_RE.search(str(note or ""))
    return match.group(1).strip() if match else ""


def check_sample_flow(stages, report: Report, has_kind=True, source="sample_flow.csv"):
    """Stages never grow; excluded rows fit inside their stage; models fit a stage.

    A file without a kind column mixes cumulative stages with exclusion counts,
    which produced six cascading errors on the real project.  Collapse them into
    one summary error plus per-row infos so the defect stays visible without
    drowning the report (R3-15).  Every affected row also gets a trace line, so
    the reader can see which row of sample_flow.csv needs a kind.
    """
    stage_ns = {}
    for item in stages:
        kind = item[2] if len(item) > 2 else "stage"
        if kind == "stage":
            stage_ns[item[0].strip()] = item[1]
    last_stage_n = None
    last_stage_name = ""
    violations = []
    for index, item in enumerate(stages, start=2):
        stage, n = item[0], item[1]
        kind = item[2] if len(item) > 2 else "stage"
        note = item[3] if len(item) > 3 else ""
        where = f"stage:{index}:{stage}"
        if n < 0:
            report.error("V-06", where, "n >= 0", n, f"stage「{stage}」n={n} 不能为负")
            continue
        if kind == "excluded":
            if last_stage_n is not None and n > last_stage_n:
                report.error("V-06", where, last_stage_n, n,
                             f"剔除行「{stage}」n={n} 大于上一条 stage「{last_stage_name}」"
                             f"n={last_stage_n}；剔除数不能超过该步的累计样本")
            continue
        if kind == "model":
            _check_model_row(stage, n, note, stage_ns, where, report)
            continue
        if last_stage_n is not None and n > last_stage_n:
            violations.append((index, where, stage, n, last_stage_n, last_stage_name))
        last_stage_n, last_stage_name = n, stage
    if not violations:
        return
    if has_kind or len(violations) == 1:
        hint = "" if has_kind else KIND_HINT
        for index, where, stage, n, previous_n, previous_name in violations:
            extra = "" if has_kind else KIND_MISSING
            report.error("V-06", where, previous_n, n,
                         f"stage「{stage}」n={n} 大于上一 stage「{previous_name}」"
                         f"n={previous_n}；累计口径应单调不增（混入排除计数或被手改）"
                         f"{extra}{hint}")
            _trace_missing_kind(report, source, index, stage, n, has_kind)
        return
    index, where, stage, n, previous_n, previous_name = violations[0]
    report.error("V-06", where, previous_n, n,
                 f"漏斗混排：共 {len(violations)} 处 n 回升（首个：stage「{stage}」n={n} > "
                 f"上一 stage「{previous_name}」n={previous_n}）；剔除数与累计数混在同一列，"
                 f"单调性无法判定。{KIND_MISSING}{KIND_HINT}")
    for index, where, stage, n, previous_n, previous_name in violations:
        report.info("V-06", where, previous_n, n,
                    f"stage「{stage}」n={n} 大于上一 stage「{previous_name}」n={previous_n}")
        _trace_missing_kind(report, source, index, stage, n, has_kind)


def _trace_missing_kind(report, source, index, stage, n, has_kind):
    """One trace line per suspect row: this is the row that needs a kind."""
    if has_kind:
        return
    report.traces.append({
        "number": fmt_number(n),
        "source_file": source,
        "source_row": str(index),
        "source_col": "kind",
        "matched_by": f"assumed stage (missing kind): {stage}",
    })


def _check_model_row(stage, n, note, stage_ns, where, report):
    """A model row is a subset of one declared stage, not a funnel step."""
    ref = model_stage_ref(note)
    if not ref:
        report.error("V-06", where, "note 里写 stage=<阶段名>", note or "（空）",
                     "kind=model 的行必须在 note 里写明对应的累计 stage，"
                     "例如 note=stage=分析样本")
        return
    ref_n = stage_ns.get(ref)
    if ref_n is None:
        available = "、".join(list(stage_ns)[:6]) or "（无 stage 行）"
        report.error("V-06", where, "note 指向已存在的 stage", ref,
                     f"note 指向的 stage「{ref}」不在 sample_flow 里；可用：{available}")
        return
    if n > ref_n:
        report.error("V-06", where, ref_n, n,
                     f"模型行「{stage}」n={n} 大于其来源 stage「{ref}」n={ref_n}；"
                     "模型样本只能是该 stage 的子集")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# input requirements
# --------------------------------------------------------------------------

CHECK_REQUIREMENTS = {
    "V-01": ("tables",),
    "V-02": ("tables",),
    "V-05": ("tables",),
    "V-06": ("flow",),
}
FLAG_NAMES = {
    "tables": "--tables",
    "figures": "--figures-manifest",
    "text": "--md/--docx",
    "flow": "--sample-flow",
    "numbers": "--numbers",
}


def missing_inputs(selected, available) -> list[tuple[str, str]]:
    """[(check, flag)] for every selected check whose input was not supplied."""
    missing = []
    for check in sorted(selected):
        if check == "V-03":
            # V-03 needs a table index, a numbers.csv whitelist or figure data.
            if not (available.get("tables") or available.get("numbers")
                    or available.get("figure_data")):
                missing.append((check, "--tables 或 --numbers 或 --figure-data"))
            continue
        if check == "V-04":
            if not available.get("figures"):
                missing.append((check, "--figures-manifest"))
            if not available.get("text"):
                missing.append((check, "--md 或 --docx"))
            continue
        for key in CHECK_REQUIREMENTS.get(check, ()):
            if not available.get(key):
                missing.append((check, FLAG_NAMES[key]))
    return missing


def write_outputs(report: Report, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    issues_path = os.path.join(out_dir, "number_issues.csv")
    trace_path = os.path.join(out_dir, "number_trace.csv")
    with open(issues_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "severity", "check", "where", "expected", "actual", "detail"])
        writer.writeheader()
        writer.writerows(report.issues)
    with open(trace_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "number", "source_file", "source_row", "source_col", "matched_by"])
        writer.writeheader()
        writer.writerows(report.traces)
    return issues_path, trace_path


def print_summary(report: Report):
    print(f"numbers checked: {report.checked}  traced: {report.traced}  "
          f"issues: {report.errors} error / {report.warnings} warning")
    if report.infos:
        # Exempted numbers stay visible: a growing ignore list must be noticed.
        print(f"ignored: {report.ignored} (by --ignore)")


def write_run_json(out_dir: str, argv_list, check: str):
    """Record SCRIPT_VERSION once per output directory; never overwrite a run.json."""
    path = os.path.join(out_dir, "run.json")
    if os.path.exists(path):
        return None
    payload = {
        "script": "verify_numbers.py",
        "version": SCRIPT_VERSION,
        "check": check,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "argv": list(argv_list),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="数字溯源校验器：核对表格、图注、正文与样本漏斗里的数字是否一致")
    parser.add_argument("--out", required=True, help="输出目录（number_issues.csv / number_trace.csv）")
    parser.add_argument("--tables", default=None, help="表格目录（*.csv）或单个 CSV")
    parser.add_argument("--figures-manifest", dest="manifest", default=None, help="图表 manifest CSV")
    parser.add_argument("--docx", default=None, help="论文成稿 .docx")
    parser.add_argument("--md", default=None, help="论文成稿 .md")
    parser.add_argument("--sample-flow", dest="sample_flow", default=None, help="sample_flow.csv")
    parser.add_argument("--numbers", default=None,
                        help="numbers.csv（value 列必需，可选 label,source）")
    parser.add_argument("--figure-data", dest="figure_data", action="append", default=[],
                        metavar="CSV", help="图内数字来源（figure,label,value；可重复）")
    parser.add_argument("--check",
                        choices=("all", "tables", "cross", "text", "trace", "figures", "flow"),
                        default="all", help="只跑某一组检查（trace=V-03，figures=V-04）")
    parser.add_argument("--tolerance", type=float, default=0.5, help="数值容差（默认 0.5）")
    parser.add_argument("--table-scope", dest="table_scopes", action="append", default=[],
                        metavar="NAME=sample|corpus", help="声明某张表的分母（可重复，缺省 sample）")
    parser.add_argument("--figure-scope", dest="figure_scopes", action="append", default=[],
                        metavar="ID=sample|corpus", help="声明某张图的分母（可重复，缺省读 manifest 的 n_scope）")
    parser.add_argument("--ignore", dest="ignore", action="append", default=[],
                        metavar="REGEX", help="命中的正文数字跳过溯源，记 info（可重复）")
    parser.add_argument("--fail-on-warn", action="store_true", help="只有 warning 也返回 2")
    args = parser.parse_args(argv)
    raw_argv = list(argv) if argv is not None else sys.argv[1:]

    report = Report()
    try:
        table_scopes = parse_scope_map(args.table_scopes)
        figure_scopes = parse_scope_map(args.figure_scopes)
    except ValueError as exc:
        report.error("input", "--table-scope/--figure-scope", "NAME=sample|corpus", "无法解析", str(exc))
        table_scopes, figure_scopes = {}, {}
    ignore_patterns = []
    for pattern in args.ignore:
        try:
            ignore_patterns.append(re.compile(pattern))
        except re.error as exc:
            report.error("input", f"--ignore {pattern}", "合法正则", "无法编译", f"re.error: {exc}")
    selected = {"V-01", "V-02", "V-03", "V-04", "V-05", "V-06"}
    if args.check == "tables":
        selected = {"V-01"}
    elif args.check == "cross":
        selected = {"V-02", "V-05"}
    elif args.check == "text":
        selected = {"V-03", "V-04"}
    elif args.check == "trace":
        selected = {"V-03"}
    elif args.check == "figures":
        selected = {"V-04"}
    elif args.check == "flow":
        selected = {"V-06"}

    sources = [args.tables, args.manifest, args.docx, args.md, args.sample_flow, args.numbers]
    if not any(sources):
        report.error("input", "输入", "至少一个来源", "无",
                     "nothing to verify: 请提供 --tables / --figures-manifest / --md / --docx / "
                     "--sample-flow / --numbers 之一")
        issues_path, trace_path = write_outputs(report, args.out)
        print_summary(report)
        print(f"issues: {issues_path}")
        print(f"trace: {trace_path}")
        run_path = write_run_json(args.out, raw_argv, args.check)
        if run_path:
            print(f"run: {run_path}")
        return 2

    # --check groups that need a specific source fail loudly instead of passing:
    # a run that silently skips half its checks reports "0 issues" and looks green.
    available = {
        "tables": bool(args.tables),
        "figures": bool(args.manifest),
        "text": bool(args.md or args.docx),
        "flow": bool(args.sample_flow),
        "numbers": bool(args.numbers),
        "figure_data": bool(args.figure_data),
    }
    for check, flag in missing_inputs(selected, available):
        report.error(check, "input", flag, "未提供", f"missing input {flag}")

    tables = load_tables(args.tables, report) if args.tables else []
    figures = load_manifest(args.manifest, report) if args.manifest else []
    flow_numbers, flow_stages, flow_has_kind = ([], [], False)
    if args.sample_flow:
        flow_numbers, flow_stages, flow_has_kind = load_sample_flow(args.sample_flow, report)
    numbers_csv = load_numbers_csv(args.numbers, report) if args.numbers else []
    figure_data = load_figure_data(args.figure_data, report) if args.figure_data else []

    # A figure is corpus-scope when the CLI says so, when the manifest declares
    # n_scope, or when its N equals the first (raw) stage of the funnel.  An
    # undeclared figure keeps scope "" so V-02 can refuse to pair it (R3-05).
    corpus_total = flow_numbers[0] if flow_numbers else None
    for figure in figures:
        declared = figure_scopes.get(figure.id) or figure.scope
        if not declared and corpus_total is not None and figure.n == corpus_total:
            declared = "corpus"
        figure.scope = declared or ""

    text = ""
    text_source = ""
    if args.md:
        try:
            text = read_text_file(args.md)
            text_source = os.path.basename(args.md)
        except Exception as exc:  # noqa: BLE001
            report.error("parse", os.path.basename(args.md), "可读的 Markdown", "解析失败",
                         f"{type(exc).__name__}: {exc}")
    if args.docx:
        try:
            docx_text = read_docx_text(args.docx)
            text = f"{text}\n{docx_text}" if text else docx_text
            text_source = os.path.basename(args.docx)
        except Exception as exc:  # noqa: BLE001
            report.error("parse", os.path.basename(args.docx), "可读的 .docx", "解析失败",
                         f"{type(exc).__name__}: {exc}")

    if "V-01" in selected and tables:
        for table in tables:
            check_totals(table, flow_numbers, args.tolerance, report)
    if "V-02" in selected and figures:
        check_figure_vs_table(figures, tables, report, table_scopes, flow_numbers)
    if "V-03" in selected and text:
        check_text_numbers(text, text_source, tables, numbers_csv, report, args.tolerance,
                           ignore_patterns, figure_data)
    if "V-04" in selected and figures:
        check_figure_numbering(figures, text, report)
    if "V-05" in selected and tables:
        check_model_n(tables, report)
    if "V-06" in selected and flow_stages:
        check_sample_flow(flow_stages, report, flow_has_kind,
                          os.path.basename(args.sample_flow))

    issues_path, trace_path = write_outputs(report, args.out)
    print_summary(report)
    print(f"issues: {issues_path}")
    print(f"trace: {trace_path}")
    run_path = write_run_json(args.out, raw_argv, args.check)
    if run_path:
        print(f"run: {run_path}")

    if report.errors:
        return 2
    if report.warnings and args.fail_on_warn:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
