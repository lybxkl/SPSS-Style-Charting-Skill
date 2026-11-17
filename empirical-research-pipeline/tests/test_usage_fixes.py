"""抽取规则由项目剖面声明；引擎不写死某一类文书的切段词。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from assemble_manuscript import resolve_asset
from extract_lib import apply_profile, quantity
from verify_numbers import model_stage_ref


def main():
    engine = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "extract_lib.py"), encoding="utf-8").read()
    for word in ("决定执行", "判处", "被告人", "本院认为"):
        assert word not in engine, word

    fine = quantity("并处罚金人民币1500.00元", want="元")
    assert fine is not None and abs(fine[0] - 1500) < 1e-6, fine

    profile = {
        "profile": "project-authored",
        "sections": {
            "announced": {"start": ["决定执行"], "end": ["。"], "last": True},
        },
        "fields": [
            {"name": "months", "func": "duration", "type": "numeric", "unit": "月",
             "scope": "announced", "hint": "有期徒刑", "na": "无"},
            {"name": "fine", "func": "quantity", "type": "numeric", "unit": "元",
             "scope": "announced", "hint": "罚金", "na": "无"},
        ],
    }
    text = (
        "判处有期徒刑一年，并处罚金500元；"
        "决定执行有期徒刑十个月；并处罚金人民币1500.00元。"
    )
    fields = apply_profile(profile, text)["fields"]
    assert fields["months"]["value"] == 10, fields["months"]
    assert fields["fine"]["value"] == 1500, fields["fine"]

    assert model_stage_ref("stage=分析样本。后面是说明；不要吃进阶段名") == "分析样本"

    with tempfile.TemporaryDirectory() as root:
        spec_dir = os.path.join(root, "draft")
        os.makedirs(os.path.join(root, "output", "tables"))
        os.makedirs(spec_dir)
        target = os.path.join(root, "output", "tables", "a.csv")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("id\n1\n")
        found = resolve_asset("output/tables/a.csv", root, spec_dir)
        assert os.path.samefile(found, target), found

    print("usage fixes ok")


if __name__ == "__main__":
    main()
