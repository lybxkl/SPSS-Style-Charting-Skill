"""锁定三处校验器不再把正常写法读错。"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from qa_outputs import column_is_unique, resolve_key, check_name_sources
from verify_numbers import extract_text_numbers


def values(text):
    return [(kind, value, raw) for _start, _end, kind, value, raw in extract_text_numbers(text)]


def main():
    rows = [
        {"doc_id": "案1", "id": "案1-甲"},
        {"doc_id": "案1", "id": "案1-乙"},
    ]
    column, candidates = resolve_key(["doc_id", "id"], "auto", rows)
    assert column == "id", column
    assert candidates[0] == "doc_id"
    assert column_is_unique(rows, "id")
    assert not column_is_unique(rows, "doc_id")
    explicit, _ = resolve_key(["doc_id", "id"], "doc_id", rows)
    assert explicit == "doc_id"

    ci = values("修复 OR=0.758（95%CI 0.563–1.022）")
    assert ("pct", 95.0) not in [(kind, value) for kind, value, _raw in ci], ci
    assert any(kind == "stat" and abs(value - 0.758) < 1e-9 for kind, value, _raw in ci), ci

    months = values("均值 10.5 个月")
    assert all(value != 5 for _kind, value, _raw in months), months
    assert ("N", 10.0) not in [(kind, value) for kind, value, _raw in months], months

    people = values("被告人 4310 人")
    assert ("N", 4310.0) in [(kind, value) for kind, value, _raw in people], people
    percent = values("缓刑 63.7%")
    assert ("pct", 63.7) in [(kind, value) for kind, value, _raw in percent], percent

    with tempfile.TemporaryDirectory() as root:
        fmap = os.path.join(root, "figure_map.json")
        spec = os.path.join(root, "manuscript.json")
        # missing both -> errors (custom assembler skipped the name sources)
        assert check_name_sources(fmap, spec)["errors"]
        with open(fmap, "w", encoding="utf-8") as fh:
            json.dump([{"tag": "图1", "title": "样本结构", "image": "figures/f1.png"}], fh)
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"blocks": [{"type": "title", "text": "某研究"}]}, fh)
        assert not check_name_sources(fmap, spec)["errors"]
        # a figure_map without titles is not a usable name source
        with open(fmap, "w", encoding="utf-8") as fh:
            json.dump([{"tag": "图1", "image": "figures/f1.png"}], fh)
        assert check_name_sources(fmap, spec)["errors"]

    with tempfile.TemporaryDirectory() as root:
        fmap = os.path.join(root, "figure_map.json")
        spec = os.path.join(root, "manuscript.json")
        tmap = os.path.join(root, "table_map.json")
        dmap = os.path.join(root, "doc_map.json")
        with open(fmap, "w", encoding="utf-8") as fh:
            json.dump([{"tag": "图1", "title": "样本结构", "image": "figures/f1.png"}], fh)
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"blocks": [{"type": "title", "text": "某研究"}]}, fh)
        # table/doc name sources missing -> errors (deliverable tables/docs unnamed)
        assert check_name_sources(fmap, spec, tmap, dmap)["errors"]
        with open(tmap, "w", encoding="utf-8") as fh:
            json.dump([{"tag": "报表", "title": "描述统计", "file": "output/reports/d.csv"}], fh)
        with open(dmap, "w", encoding="utf-8") as fh:
            json.dump([{"title": "复核包", "file": "output/review/review_pack.md"}], fh)
        assert not check_name_sources(fmap, spec, tmap, dmap)["errors"]
        # untitled entries are not a usable name source
        with open(tmap, "w", encoding="utf-8") as fh:
            json.dump([{"tag": "报表", "file": "output/reports/d.csv"}], fh)
        assert check_name_sources(fmap, spec, tmap, dmap)["errors"]
        # scalar JSON must be an error, not a crash
        with open(tmap, "w", encoding="utf-8") as fh:
            json.dump("not a map", fh)
        assert check_name_sources(fmap, spec, tmap, dmap)["errors"]
    print("checker readings ok")


if __name__ == "__main__":
    main()
