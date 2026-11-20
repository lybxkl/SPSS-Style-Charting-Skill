"""目录骨架与命名覆盖：别名归组、杂散声明、表/文档标题覆盖；通用不写死学科。"""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from layout_conformance import check, main


def put(root, rel, text="x"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def fixture(root):
    put(root, "output/audit/corpus_files.csv", "rel_path\na.pdf\n")
    put(root, "output/analysis_pack/fit.csv", "a\n1\n")
    put(root, "output/chart_pack/chart_manifest.csv", "id\n1\n")
    put(root, "output/reports/descriptive_stats.csv", "a\n1\n")
    put(root, "output/review/review_pack.md", "# 复核包\n")
    put(root, "output/tables/table1.csv", "a\n1\n")
    put(root, "output/qa/qa_report.json", "{}")
    put(root, "output/gates/state.json", "{}")
    put(root, "output/v2/claims.jsonl", "{}\n")
    put(root, "output/table_map.json", json.dumps(
        [{"tag": "报表", "title": "描述统计", "file": "output/reports/descriptive_stats.csv"}],
        ensure_ascii=False))
    put(root, "output/doc_map.json", json.dumps(
        [{"title": "复核包", "file": "output/review/review_pack.md"}], ensure_ascii=False))
    put(root, "manuscript.json", json.dumps({"blocks": [
        {"type": "title", "text": "某研究"},
        {"type": "table", "csv": "output/tables/table1.csv", "caption": "罪名结构"},
    ]}, ensure_ascii=False))


def args(root):
    return (root, os.path.join(root, "research_registry.json"),
            os.path.join(root, "output", "table_map.json"),
            os.path.join(root, "output", "doc_map.json"),
            os.path.join(root, "manuscript.json"))


def main_test():
    with tempfile.TemporaryDirectory() as root:
        fixture(root)
        result = check(*args(root))
        assert result["error_count"] == 0, result["errors"]
        groups = {g["key"]: g for g in result["groups"]}
        # 物理别名自动归入规范组
        assert groups["output/stats"]["dirs"] == ["output/analysis_pack"]
        assert groups["output/figures"]["dirs"] == ["output/chart_pack"]
        assert groups["output/tables"]["dirs"] == ["output/reports", "output/tables"]
        assert groups["output/ledger"]["dirs"] == ["output/gates", "output/v2"]
        assert groups["output/stats"]["label"] == "统计"

        # 杂散目录未声明 -> error
        put(root, "output/custom/x.csv", "a\n1\n")
        result = check(*args(root))
        assert result["stray"] == ["output/custom"]
        assert any("undeclared" in e for e in result["errors"])

        # registry layout 声明后归组；绝对路径标题条目也要能对上
        put(root, "research_registry.json", json.dumps(
            {"layout": {"output/tables": ["output/custom"]}}))
        put(root, "output/table_map.json", json.dumps([
            {"tag": "报表", "title": "描述统计", "file": "output/reports/descriptive_stats.csv"},
            {"title": "自定义表", "file": os.path.join(root, "output", "custom", "x.csv")},
        ], ensure_ascii=False))
        result = check(*args(root))
        assert result["error_count"] == 0, result["errors"]
        assert "output/custom" in {g["key"]: g for g in result["groups"]}["output/tables"]["dirs"]

        # 非规范键 -> error
        put(root, "research_registry.json", json.dumps(
            {"layout": {"output/nope": ["output/custom"]}}))
        result = check(*args(root))
        assert any("not a canonical group" in e for e in result["errors"])

        # 同一目录挂两个组 -> error
        put(root, "research_registry.json", json.dumps(
            {"layout": {"output/tables": ["output/custom"], "output/docs": ["output/custom"]}}))
        result = check(*args(root))
        assert any("two groups" in e for e in result["errors"])

        # 已知别名改挂其他组 -> error（防逃避命名覆盖），仍按原规范组归组核覆盖
        put(root, "research_registry.json", json.dumps(
            {"layout": {"output/docs": ["output/reports"]}}))
        result = check(*args(root))
        assert any("cannot rehang" in e for e in result["errors"]), result["errors"]
        groups = {g["key"]: g for g in result["groups"]}
        assert "output/reports" in groups["output/tables"]["dirs"]

        # layout 值接受字符串；嵌套/越界目录声明 -> error
        put(root, "research_registry.json", json.dumps(
            {"layout": {"output/tables": "output/custom", "output/docs": ["output/review/sub"]}}))
        result = check(*args(root))
        assert any("first-level" in e for e in result["errors"]), result["errors"]
        assert "output/custom" in {g["key"]: g for g in result["groups"]}["output/tables"]["dirs"]

    with tempfile.TemporaryDirectory() as root:
        fixture(root)
        # 无标题交付表 -> error（manuscript 引用的表仍被覆盖）
        put(root, "output/table_map.json", "[]")
        result = check(*args(root))
        assert any("untitled deliverable output/reports/descriptive_stats.csv" in e
                   for e in result["errors"]), result["errors"]
        assert not any("table1.csv" in e for e in result["errors"])

        # 空目录 warning 不拦截
        os.makedirs(os.path.join(root, "output", "docs"))
        put(root, "output/table_map.json", json.dumps(
            [{"tag": "报表", "title": "描述统计", "file": "output/reports/descriptive_stats.csv"}],
            ensure_ascii=False))
        result = check(*args(root))
        assert result["error_count"] == 0, result["errors"]
        assert any("empty directory output/docs" in w for w in result["warnings"])

        # 标量 JSON 命名源 -> warning 降级为空覆盖表（交付件无标题即 error），不崩
        put(root, "output/table_map.json", '"not a map"')
        result = check(*args(root))
        assert any("untitled deliverable" in e for e in result["errors"])
        put(root, "output/table_map.json", json.dumps(
            [{"tag": "报表", "title": "描述统计", "file": "output/reports/descriptive_stats.csv"}],
            ensure_ascii=False))

        # CLI 退出码与分组报告落盘（查看器读取的现成产物）
        assert main(["--root", root]) == 0
        report = os.path.join(root, "output", "qa", "layout_conformance.json")
        with io.open(report, encoding="utf-8") as fh:
            saved = json.load(fh)
        assert saved["groups"] and saved["error_count"] == 0
        put(root, "output/custom/y.csv", "a\n1\n")
        assert main(["--root", root]) == 2
    print("layout conformance ok")


if __name__ == "__main__":
    main_test()