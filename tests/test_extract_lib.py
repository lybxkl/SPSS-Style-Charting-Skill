#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests for extract_lib.py — the field-extraction primitives.

Every assertion here is a defect that would otherwise be silent: a value that
is quietly wrong looks exactly like a value that is right. The fixtures use the
two shapes that really occur — a form printed one character per line, and a
Q/A interview transcript.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import SCRIPTS, TempCase  # noqa: E402

sys.path.insert(0, SCRIPTS)
import extract_lib as E  # noqa: E402

PROFILES = os.path.join(os.path.dirname(SCRIPTS), "profiles")

# A header printed one character per line, exactly as the PDF pipeline emits it.
SPLIT_HEADER = """审
理
法
院：****铁路运输****
案
号：(2020)陕****刑初64 号
裁
判
日
期：2020.12****
案
由：刑事/妨害社会管理秩序罪/破坏环境资源保护罪/滥伐林木罪
"""

INTERVIEW = """社区养老服务满意度访谈记录
访谈编号：IV-2024-017
受访者：李某
访谈日期：2024年3月5日
访谈地点：城东街道居家养老服务站
受访者年龄：71
一、基本情况
本次访谈时长约35分钟，采取半结构化方式。
二、访谈正文
问：您对社区食堂的饭菜质量满意吗？
答：还行吧，比家里做得清淡，就是花样少。
问：助餐服务从订餐到送到，一般要等多久？
答：平均半小时左右，下雨天更久。
"""


class NumTest(unittest.TestCase):
    def test_arabic_and_thousands(self):
        for raw, want in (("1358 元", 1358), ("1,358 元", 1358), ("1 358 元", 1358),
                          ("2021 年", 2021), ("1.2万", 12000)):
            self.assertEqual(E.num(raw), want, raw)

    def test_chinese_numeral(self):
        for raw, want in (("二〇二一", 2021), ("二十三", 23), ("十五", 15),
                          ("九千", 9000), ("一万五千", 15000),
                          ("一万零五百", 10500), ("零点五", 0.5)):
            self.assertEqual(E.num(raw), want, raw)

    def test_magnitude_applies_once(self):
        # 15万 must not be read as 15 * 10^4 * 10^4: the suffix belongs to the
        # Arabic branch only, otherwise every Chinese amount explodes.
        self.assertEqual(E.num("十五万"), 150000)
        self.assertEqual(E.num("十五万元"), 150000)


class QuantityTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(E.quantity("罚金2000元"), (2000, "元"))
        self.assertEqual(E.quantity("2万元"), (20000, "元"))
        self.assertEqual(E.quantity("三千元"), (3000, "元"))
        self.assertEqual(E.quantity("9千元"), (9000, "元"))
        self.assertEqual(E.quantity("十五万元"), (150000, "元"))

    def test_unit_conversion(self):
        self.assertEqual(E.quantity("1.5小时"), (90, "分钟"))
        self.assertEqual(E.quantity("四十分钟"), (40, "分钟"))
        self.assertEqual(E.quantity("半小时"), (30, "分钟"))
        self.assertEqual(E.quantity("0.5公顷"), (7.5, "亩"))

    def test_earliest_mention_wins(self):
        # "半小时" sits right after the anchor; a distant "40分钟" must not win
        # just because the 分钟 alias happened to be tried first.
        text = "答：平均半小时左右。……一次四十分钟。"
        self.assertEqual(E.quantity(text), (30, "分钟"))

    def test_span_covers_numeral_and_unit(self):
        hit = E.quantity_find("并处罚金人民币三千元。")
        self.assertEqual(hit[0], 3000)
        self.assertEqual("并处罚金人民币三千元。"[hit[2][0]:hit[2][1]], "三千元")


class DateDurationTest(unittest.TestCase):
    def test_date_shapes(self):
        for raw in ("2021年3月5日", "二〇二一年三月五日", "2021.03.05", "2021-3-5"):
            self.assertEqual(E.date(raw), "2021-03-05", raw)

    def test_month_only_is_not_invented(self):
        self.assertEqual(E.date("2021年3月"), "2021-03")

    def test_impossible_date_is_rejected(self):
        self.assertIsNone(E.date("2021年13月40日"))

    def test_duration_sums_adjacent_parts(self):
        # Reading only the last match would turn 33 months into 9.
        self.assertEqual(E.duration("判处有期徒刑二年九个月"), 33)
        self.assertEqual(E.duration("三年"), 36)


class KvBlockTest(TempCase):
    def test_split_header_is_read_per_line(self):
        self.assertEqual(E.kv_block(SPLIT_HEADER, ["案号"])[0],
                         "(2020)陕****刑初64 号")
        self.assertEqual(E.kv_block(SPLIT_HEADER, ["审理法院"])[0], "****铁路运输****")

    def test_value_never_crosses_a_line(self):
        # Crossing the line would swallow the next field — the most expensive
        # defect of the first round.
        text = "案号：\n(2020)陕1 号\n案由：滥伐林木罪\n"
        self.assertEqual(E.kv_block(text, ["案号"])[0], "(2020)陕1 号")

    def test_redaction_is_reported_not_swallowed(self):
        value, _span, meta = E.kv_block(SPLIT_HEADER, ["审理法院"])
        self.assertTrue(meta["redacted"])

    def test_absent_label_returns_none(self):
        self.assertIsNone(E.kv_block(SPLIT_HEADER, ["审判长"]))


class SectionTest(unittest.TestCase):
    def test_last_occurrence_wins(self):
        # Running headers repeat the title above the body.
        text = "判决如下：一、驳回上诉。\n判决如下：一、判处拘役二个月。"
        body, _ = E.section(text, "判决如下")
        self.assertTrue(body.startswith("一、判处拘役二个月"))

    def test_marker_may_be_written_one_char_per_line(self):
        text = "判\n决\n如\n下：一、判处拘役二个月。"
        body, _ = E.section(text, "判决如下")
        self.assertIn("拘役二个月", body)

    def test_end_markers_cut_the_tail(self):
        text = "判决如下：一、判处拘役。如不服本判决，可上诉。"
        body, _ = E.section(text, "判决如下", ["如不服本判决"])
        self.assertNotIn("上诉", body)

    def test_missing_marker_is_none_and_minus_one(self):
        self.assertEqual(E.section("无关文本", "判决如下"), (None, -1))


class NegationTest(unittest.TestCase):
    def test_clause_opening_cue(self):
        self.assertTrue(E.negate("不予支持该请求", (0, 2)))

    def test_double_cue_cancels(self):
        self.assertFalse(E.negate("没有不满意", (2, 5)))

    def test_charge_name_is_not_a_negation(self):
        # 非法 is part of a charge name, not a negation of the amount beside it.
        self.assertFalse(E.negate("因非法捕捞水产品罪，判处罚金9000元", (16, 20)))

    def test_value_before_cue_is_not_negated(self):
        self.assertFalse(E.negate("已缴纳修复费1250元", (2, 6)))


class WindowEvidenceTest(unittest.TestCase):
    def test_evidence_round_trip(self):
        text = "一二三四五六七八九十" * 30
        span = (120, 124)
        snippet = E.window(text, span)["snippet"]
        line = E.evidence_line("field", snippet, span)
        self.assertTrue(E.verify_evidence(text, line))

    def test_evidence_line_has_no_newline(self):
        text = "第一行\n第二行含金额1250元\n第三行"
        span = text.index("1250"), text.index("1250") + 4
        line = E.evidence_line("amount", E.window(text, span)["snippet"], span)
        self.assertNotIn("\n", line)
        self.assertTrue(E.verify_evidence(text, line))

    def test_wrong_offsets_are_rejected(self):
        text = "第一行\n第二行含金额1250元\n第三行"
        self.assertFalse(E.verify_evidence(text, "amount=1250@0-4"))

    def test_out_of_range_is_rejected(self):
        self.assertFalse(E.verify_evidence("short", "a=x@100-104"))


class ProfileTest(TempCase):
    def _write(self, obj, name="p.json"):
        path = self.p(name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        return path

    def _base(self, **over):
        field = {"name": "case_no", "func": "kv_block", "type": "text",
                 "na": ["未提及"], "labels": ["案号"]}
        field.update(over)
        return {"profile": "t", "fields": [field]}

    def test_missing_na_is_rejected(self):
        field = {"name": "x", "func": "pattern", "type": "text", "pattern": "a"}
        with self.assertRaises(E.ProfileError):
            E.validate_profile({"profile": "t", "fields": [field]})

    def test_reserved_column_is_rejected(self):
        with self.assertRaises(E.ProfileError):
            E.validate_profile(self._base(name="rel_path"))

    def test_bad_field_name_is_rejected(self):
        with self.assertRaises(E.ProfileError):
            E.validate_profile(self._base(name="Case No"))

    def test_unknown_scope_is_rejected(self):
        with self.assertRaises(E.ProfileError):
            E.validate_profile(self._base(scope="dispositive"))

    def test_missing_required_param_is_rejected(self):
        field = {"name": "x", "func": "pattern", "type": "text", "na": ["未提及"]}
        with self.assertRaises(E.ProfileError):
            E.validate_profile({"profile": "t", "fields": [field]})

    def test_two_shipped_profiles_are_valid(self):
        for name in ("legal-judgment.json", "eldercare-interview.json"):
            profile = E.load_profile(os.path.join(PROFILES, name))
            self.assertTrue(profile["fields"])

    def test_hash_is_stable(self):
        path = os.path.join(PROFILES, "legal-judgment.json")
        self.assertEqual(E.profile_sha256(path), E.profile_sha256(path))
        self.assertEqual(len(E.profile_sha256(path)), 64)


class ApplyProfileTest(unittest.TestCase):
    def setUp(self):
        self.legal = E.load_profile(os.path.join(PROFILES, "legal-judgment.json"))
        self.elder = E.load_profile(os.path.join(PROFILES, "eldercare-interview.json"))

    def test_split_header_fields(self):
        out = E.apply_profile(self.legal, SPLIT_HEADER, base_dir=PROFILES)
        self.assertEqual(out["fields"]["case_no"]["value"], "(2020)陕****刑初64 号")
        self.assertEqual(out["fields"]["cause"]["value"],
                         "刑事/妨害社会管理秩序罪/破坏环境资源保护罪/滥伐林木罪")

    def test_missing_section_yields_na_not_zero(self):
        out = E.apply_profile(self.legal, SPLIT_HEADER, base_dir=PROFILES)
        self.assertIsNone(out["fields"]["claim_items"]["value"])
        self.assertEqual(out["fields"]["claim_items"]["source"], "none")

    def test_bool_absent_is_false_not_none(self):
        # "no complaint" and "section not found" must stay distinguishable.
        out = E.apply_profile(self.elder, INTERVIEW, base_dir=PROFILES)
        self.assertIs(out["fields"]["complaint_any"]["value"], False)
        self.assertEqual(out["fields"]["complaint_any"]["source"], "absent")

    def test_question_line_does_not_answer_for_the_respondent(self):
        out = E.apply_profile(self.elder, INTERVIEW, base_dir=PROFILES)
        self.assertEqual(out["fields"]["satisfaction"]["value"], "一般")

    def test_label_anchored_value_without_unit(self):
        out = E.apply_profile(self.elder, INTERVIEW, base_dir=PROFILES)
        self.assertEqual(out["fields"]["respondent_age"]["value"], 71)

    def test_every_evidence_line_verifies(self):
        for profile, text in ((self.legal, SPLIT_HEADER), (self.elder, INTERVIEW)):
            out = E.apply_profile(profile, text, base_dir=PROFILES)
            for line in out["evidence"]:
                self.assertTrue(E.verify_evidence(text, line), line)

    def test_impossible_fallback_is_skipped_not_raised(self):
        profile = {"profile": "t", "fields": [{
            "name": "mood", "func": "canon", "type": "text", "na": ["未提及"],
            "vocab": {"好": "好"}, "fallback": ["pattern"]}]}
        out = E.apply_profile(profile, "今天很差", base_dir=PROFILES)
        self.assertIsNone(out["fields"]["mood"]["value"])
        self.assertEqual(out["fields"]["mood"].get("fallback_skipped", 0), 1)


class LibraryIsDomainNeutralTest(unittest.TestCase):
    def test_no_domain_words_in_the_library(self):
        """extract_lib must not know any research field: profiles carry that."""
        banned = ("legal", "判决", "案号", "法院", "刑", "care", "养老")
        with open(os.path.join(SCRIPTS, "extract_lib.py"), encoding="utf-8") as fh:
            body = fh.read()
        hits = [w for w in banned if w in body]
        self.assertEqual(hits, [], f"domain words leaked into extract_lib: {hits}")


class NumeralChainTest(unittest.TestCase):
    """One reader for every numeral shape.

    Reading the same numeral with two different sets of rules (forward for
    ``num``, backward for ``quantity``) made ``1亿零5万`` come out as 50000 in
    one place and 1e8 in another. Both agreed with themselves and disagreed with
    the document, which is the worst failure mode available.
    """

    def test_filler_zero_does_not_end_the_chain(self):
        self.assertEqual(E.num("1亿零五万"), 100050000)
        self.assertEqual(E.num("一亿零五万"), 100050000)
        self.assertEqual(E.num("1亿零五十万"), 100500000)

    def test_cn_digit_group_inside_arabic_chain(self):
        self.assertEqual(E.num("10亿零5万"), 1000050000)

    def test_quantity_does_not_apply_the_alias_magnitude_twice(self):
        self.assertEqual(E.quantity("1亿零五万元"), (100050000, "元"))
        self.assertEqual(E.quantity("十五万元"), (150000, "元"))
        self.assertEqual(E.quantity("两百五十万元"), (2500000, "元"))
        self.assertEqual(E.quantity("1200万元"), (12000000, "元"))

    def test_plain_and_compound_units_still_read(self):
        self.assertEqual(E.quantity("2000元"), (2000, "元"))
        self.assertEqual(E.quantity("9千元"), (9000, "元"))
        self.assertEqual(E.quantity("3万5千元"), (35000, "元"))
        self.assertEqual(E.quantity("一万零五百元"), (10500, "元"))


class DateAnchorTest(unittest.TestCase):
    def test_anchor_beats_completeness(self):
        text = "裁判日期：2021.03**** 正文又说 1988 年7 月11 日"
        self.assertEqual(E.date_find(text, anchor=6)[0], "2021-03")

    def test_without_anchor_the_document_order_decides(self):
        """Three passes over three patterns used to rank by pattern, not position."""
        text = "2021 年3 月 后文 2020 年5 月8 日"
        self.assertEqual(E.date_find(text)[0], "2021-03")

    def test_redacted_date_keeps_the_year_instead_of_borrowing_a_body_date(self):
        """A masked date is still an observation: 2021******** means 2021.

        Treating it as "no date" made the field fall back to some other event's
        date in the body — a 33-year error that reads as dirty data.
        """
        text = "裁判日期：2021******** 正文又说 1988 年7 月11 日"
        self.assertEqual(E.date_find(text, anchor=6)[0], "2021")
        self.assertEqual(E.date(text), "2021")

    def test_space_inside_a_numeral_does_not_end_the_chain(self):
        """PDF extraction sprinkles spaces: `1亿 5万` is one number."""
        self.assertEqual(E.num("1亿 5万"), 100050000)
        self.assertEqual(E.quantity("1亿 5万元"), (100050000, "元"))


class ItemsAndVocabTest(unittest.TestCase):
    def test_full_width_bracket_enumeration_is_recognised(self):
        text = "（一）支付修复费\n（二）公开道歉\n"
        self.assertEqual([label for label, _, _ in E.items(text, "paren")],
                         ["一", "二"])

    def test_duplicate_alias_across_categories_is_refused(self):
        with self.assertRaises(ValueError):
            E.canon([("很满意", (0, 3))], [("很满意", "一般"), ("很满意", "满意")])


class ProfileKeyTest(unittest.TestCase):
    def test_key_the_func_never_reads_is_refused(self):
        with self.assertRaises(E.ProfileError):
            E.validate_profile({
                "profile": "probe",
                "fields": [{"name": "a", "func": "kv_block", "type": "text",
                            "na": "未提及", "label": "编号", "pattern": "x"}],
            })


if __name__ == "__main__":
    unittest.main()