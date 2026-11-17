"""使用中暴露的抽取、漏斗和文稿路径。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from assemble_manuscript import resolve_asset
from extract_lib import apply_profile, quantity
from verify_numbers import model_stage_ref


def main():
    fine = quantity("并处罚金人民币1500.00元", want="元")
    assert fine is not None and abs(fine[0] - 1500) < 1e-6, fine

    profile_path = os.path.join(os.path.dirname(__file__), "..", "profiles", "legal-judgment.json")
    with open(profile_path, encoding="utf-8") as fh:
        profile = json.load(fh)
    text = (
        "本院认为，被告人甲认罪认罚。\n"
        "本院认为，以上事实清楚。\n"
        "判决如下：被告人甲犯污染环境罪，单处罚金人民币1500.00元；"
        "被告人乙犯污染环境罪，判处有期徒刑六个月。"
        "如不服本判决，可上诉。"
    )
    fields = apply_profile(profile, text)["fields"]
    assert fields["guilty_plea"]["value"] is True, fields["guilty_plea"]
    assert fields["sentence_months"]["value"] is None, fields["sentence_months"]
    assert fields["fine_yuan"]["value"] == 1500, fields["fine_yuan"]

    combined = (
        "判决如下：被告人甲犯甲罪，判处有期徒刑一年，并处罚金人民币500元；"
        "犯乙罪，判处有期徒刑六个月，并处罚金人民币800元；"
        "决定执行有期徒刑十个月，并处罚金人民币1500.00元。"
    )
    semicolon = (
        "判决如下：犯甲罪，判处有期徒刑一年，并处罚金500元；"
        "决定执行有期徒刑十个月；并处罚金人民币1500.00元。"
    )
    split_fine = apply_profile(profile, "本院认为，事实清楚。\n" + semicolon)["fields"]
    assert split_fine["fine_yuan"]["value"] == 1500, split_fine["fine_yuan"]
    assert split_fine["sentence_months"]["value"] == 10, split_fine["sentence_months"]

    denied = apply_profile(profile, "本院认为，被告人不认罪认罚。\n判决如下：被告人甲犯某罪，单处罚金100元。")["fields"]
    assert denied["guilty_plea"]["value"] is not True, denied["guilty_plea"]

    again = apply_profile(profile, "本院认为，事实清楚。\n" + combined)["fields"]
    assert again["sentence_months"]["value"] == 10, again["sentence_months"]
    assert again["fine_yuan"]["value"] == 1500, again["fine_yuan"]

    control = apply_profile(profile, "本院认为。\n判决如下：被告人甲犯某罪，判处管制二年。")["fields"]
    assert control["sentence_months"]["value"] == 24, control["sentence_months"]

    restore = apply_profile(profile, "判决如下：赔偿被害人1000元。")["fields"]
    assert restore["restore_amount"]["value"] is None, restore["restore_amount"]

    note = "stage=一审刑事判决分析样本。缓刑是子集；不要把句号后的字算进阶段名"
    assert model_stage_ref(note) == "一审刑事判决分析样本", model_stage_ref(note)

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
