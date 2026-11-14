# -*- coding: utf-8 -*-
"""References (T27) and full-manuscript assembly (T28).

Covers A33 (DOI exists but does not support the claim; abstract-only cannot
claim a full-text check) and A53 (an edited/reprinted sentence loses its old
support), plus the requirement that every printed number is traceable.
"""
import json
import os

from _helpers import TempCase, make_png

import claims as CL
import contract_v2 as C
import manuscript as MS
import refs as RF

PAPER = """Title: A study of participation
Abstract
This paper studies participation in a synthetic programme. We surveyed 120
participants and assigned them to a treatment and a control group. The primary
outcome is a questionnaire score, and the analysis compares the two groups
under a pre-specified model.
1 Introduction
Intro
2 Methods
We surveyed 120 participants in a synthetic programme between January and March.
Participants were assigned to the treatment group or the control group by a
pre-specified randomisation list. The questionnaire was administered once, and
the same instrument was used in both groups. No participant was excluded after
 enrolment, and the analysis follows the pre-registered specification.
3 Results
The treatment effect was 0.42 units (95% CI 0.11 to 0.73). The control group
mean was 0.10 and the treatment group mean was 0.52. The difference is small but
its confidence interval excludes zero, and the direction is consistent across
the pre-specified subgroups.
4 Discussion
The effect is consistent with prior work. It is modest in size and the sample is
synthetic, so the estimate should not be read as a substantive finding about any
real population.
References
[1] Zhang, L. (2021). A prior study. Journal of Examples, 3(2), 1-20.
"""


def paper_text(tmp, name="paper.txt", body=PAPER):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


class TestRefs(TempCase):
    def setUp(self):
        super().setUp()
        self.proj = C.Project(self.tmp)
        RF.register(self.proj, "C1", authors="Zhang, Li", title="A prior study",
                    year="2021", venue="Journal of Examples",
                    doi="10.1234/example.2021")
        self.meta = {"doi": "10.1234/example.2021", "title": "A prior study",
                     "authors": "Zhang, L.", "year": "2021",
                     "venue": "Journal of Examples"}

    def test_doi_metadata_mismatch_is_reported(self):
        res = RF.verify_doi(self.proj, "C1", metadata=self.meta)
        self.assertTrue(res["ok"])
        wrong = dict(self.meta, title="A different study")
        res = RF.verify_doi(self.proj, "C1", metadata=wrong)
        self.assertFalse(res["ok"])
        self.assertEqual(res["problems"][0]["field"], "title")

    def test_abstract_cannot_support_a_full_text_claim(self):
        text = paper_text(self.tmp, "abstract.txt",
                          "Abstract\nThis paper studies participation in a "
                          "synthetic programme with 120 participants.\n")
        RF.verify_access(self.proj, "C1", text_path=text, level="abstract")
        with self.assertRaises(RF.RefError) as ctx:
            RF.support(self.proj, "C1", claim_id="K1",
                       quote="We surveyed 120 participants.",
                       section="Methods", claim_level="full_text")
        self.assertIn("cannot support a full-text claim", str(ctx.exception))

    def test_full_text_quote_must_appear_verbatim(self):
        text = paper_text(self.tmp)
        RF.verify_access(self.proj, "C1", text_path=text, level="full_text")
        ok = RF.support(self.proj, "C1", claim_id="K1",
                        quote="The treatment effect was 0.42 units (95% CI "
                              "0.11 to 0.73).",
                        section="Results", page=2)
        self.assertTrue(ok["quote_verified"])
        with self.assertRaises(RF.RefError) as ctx:
            RF.support(self.proj, "C1", claim_id="K2",
                       quote="The treatment effect was 0.99 units.",
                       section="Results")
        self.assertIn("not present", str(ctx.exception))
        # check catches a stored quote that is not in the text
        rec = self.proj.latest("reference", "C1")
        payload = dict(rec["data"])
        payload["supports"] = list(payload["supports"]) + [{
            "cite_id": "C1", "claim": "K9",
            "quote": "this sentence is not in the paper at all",
            "quote_sha256": "0" * 8, "section": "Results", "page": 2,
            "claim_level": "full_text", "quote_verified": True,
            "note": "forged", "recorded_at": C._now()}]
        self.proj.append("reference", C.make_record(
            "reference", "C1", payload, producer=C.producer_for(
                "test", version="1", module_file=__file__),
            status=rec["status"], revision=rec["revision"] + 1),
            enforce_transition=False)
        check = RF.check_reference(self.proj, "C1")
        self.assertFalse(check["ok"])
        self.assertIn("quote_not_found",
                      [p["check"] for p in check["problems"]])

    def test_bibliography_marker_reveals_a_full_text_file(self):
        text = paper_text(self.tmp)
        with self.assertRaises(RF.RefError) as ctx:
            RF.verify_access(self.proj, "C1", text_path=text, level="abstract")
        self.assertIn("full text", str(ctx.exception))

    def test_reference_changed_after_access_is_detected(self):
        text = paper_text(self.tmp)
        RF.verify_access(self.proj, "C1", text_path=text, level="full_text")
        access = self.proj.latest("reference", "C1")["data"]["access"]
        stored = self.proj.root / access["text_path"]
        with open(stored, "a", encoding="utf-8") as fh:
            fh.write("\nappendix added later\n")
        check = RF.check_reference(self.proj, "C1")
        self.assertIn("access_text_changed",
                      [p["check"] for p in check["problems"]])

    def test_identity_change_invalidates_access_and_status_evidence(self):
        RF.verify_access(self.proj, "C1", text_path=paper_text(self.tmp), level="full_text")
        RF.register(self.proj, "C1", authors="Other", title="A different study", year="2025", venue="Other", doi="10.1234/other")
        current = self.proj.latest("reference", "C1")["data"]
        self.assertEqual(current["access"]["level"], "metadata")
        self.assertFalse(current["access"].get("text_path"))
        self.assertFalse(current.get("supports"))

    def test_retraction_lookup_is_bound_and_formal_use_is_refused(self):
        RF.verify_doi(self.proj, "C1", metadata=self.meta)
        RF.verify_access(self.proj, "C1", text_path=paper_text(self.tmp), level="full_text")
        status = paper_text(self.tmp, "status.txt", "10.1234/example.2021 — publisher notice: this synthetic article is retracted.")
        RF.record_publication_status(self.proj, "C1", status="retracted", evidence_path=status,
                                     source_url="https://example.invalid/fixture-only", reviewer="fixture-reviewer",
                                     note="Synthetic notice opened and DOI checked; no online lookup is claimed.")
        check = RF.check_reference(self.proj, "C1", formal=True)
        self.assertFalse(check["ok"])
        self.assertIn("retracted", str(check))


class TestManuscript(TempCase):
    def setUp(self):
        super().setUp()
        from _research_fixture import known_project
        self.proj = known_project(self.tmp)
        filler = ("该段用于说明研究背景、研究问题与分析策略，确保本节具备完整的"
                  "研究叙事而不是技术日志。")
        self.blocks = {
            "abstract": ("本研究考察一项合成项目的参与情况。样本为 120 名参与者，"
                         "随机分配到处理组与对照组。主要结果变量为问卷得分。"
                         "处理效应为 {effect} 个单位，提示干预与结果之间存在正向"
                         "关联。本摘要仅用于流水线验证，不代表真实实证结论。"
                         "研究问题、样本来源与分析策略在此一并说明，以便读者判断"
                         "结果的可推广范围。分析计划在数据收集前确定，并在附录中"
                         "给出完整的变量定义与测量方式。"),
            "introduction": filler * 12,
            "methods": ("我们招募了 120 名参与者，随机分配到处理组与对照组，"
                        "并使用同一份问卷测量结果变量。" + filler) * 8,
            "results": ("处理组的结果变量均值为 {treatment_mean}，对照组为 {control_mean}，"
                        "差值为 {effect}。" + filler) * 8,
            "discussion": ("该结果与既有研究的方向一致，但效应量较小，"
                           "不宜外推到其他人群。" + filler) * 8,
        }
        for section, text in self.blocks.items():
            CL.register_block(self.proj, block_id=f"b_{section}",
                              section=section, text=text, claims=[])

    def _numbers(self):
        return ({"effect": "0.42", "n": 120, "treatment_mean": "0.52", "control_mean": "0.10"},
                {"effect": {"model": "M1", "result": "M1", "parameter": "treatment", "unit": "score points", "format": ".2f"},
                 "n": {"model": "M1", "field": "n"},
                 "treatment_mean": {"dataset": "person", "aggregate": "mean", "column": "y", "where": {"treatment": "1"}, "format": ".2f"},
                 "control_mean": {"dataset": "person", "aggregate": "mean", "column": "y", "where": {"treatment": "0"}, "format": ".2f"}})

    def test_missing_section_blocks_assembly(self):
        proj = C.Project(self.p("other"))
        CL.register_block(proj, block_id="b_abstract", section="abstract",
                          text=self.blocks["abstract"], claims=[])
        with self.assertRaises(MS.ManuscriptError) as ctx:
            MS.build_docx(proj, docx_path=self.p("x.docx"), title="t",
                          authors="a", numbers={}, trace={}, required_sections=MS.REQUIRED_SECTIONS)
        self.assertIn("section_missing", str(ctx.exception))

    def test_untraceable_number_is_refused(self):
        numbers, trace = self._numbers()
        numbers["effect"] = "0.42"
        with self.assertRaises(MS.ManuscriptError) as ctx:
            MS.build_docx(self.proj, docx_path=self.p("x.docx"), title="t",
                          authors="a", numbers=numbers, trace={})
        self.assertIn("no trace", str(ctx.exception))

    def test_placeholder_without_value_is_refused(self):
        numbers, trace = self._numbers()
        del numbers["effect"]
        with self.assertRaises(MS.ManuscriptError) as ctx:
            MS.build_docx(self.proj, docx_path=self.p("x.docx"), title="t",
                          authors="a", numbers=numbers, trace=trace)
        self.assertIn("no value", str(ctx.exception))

    def test_real_docx_is_built_and_printed_text_matches(self):
        numbers, trace = self._numbers()
        docx = self.p("out", "paper.docx")
        info = MS.build_docx(self.proj, docx_path=docx, title="合成验证稿",
                             authors="Agent", numbers=numbers, trace=trace)
        self.assertTrue(os.path.isfile(docx))
        self.assertGreater(len(info["spans"]), 0)
        self.assertEqual(info["figures"], 0)
        res = MS.verify_printed(self.proj, docx_path=docx,
                                spans={k: list(v) for k, v in
                                       info["spans"].items()},
                                numbers=numbers, trace=trace)
        self.assertTrue(res["ok"], res)
        self.assertTrue(all(b["ok"] for b in res["blocks"]))

    def test_editing_after_assembly_makes_the_block_stale(self):
        numbers, trace = self._numbers()
        docx = self.p("out", "paper.docx")
        info = MS.build_docx(self.proj, docx_path=docx, title="t", authors="a",
                             numbers=numbers, trace=trace)
        CL.register_block(
            self.proj, block_id="b_results", section="results",
            text=self.blocks["results"].replace("{effect}", "0.99"), claims=[])
        res = MS.verify_printed(self.proj, docx_path=docx,
                                spans={k: list(v) for k, v in
                                       info["spans"].items()},
                                numbers=numbers, trace=trace)
        self.assertFalse(res["ok"])
        stale = [b for b in res["blocks"] if b["status"] == "stale"]
        self.assertEqual([b["block"] for b in stale], ["b_results"])
        self.assertEqual(stale[0]["findings"][0]["check"],
                         "printed_text_mismatch")

    def test_word_export_and_pdf_contain_the_reviewed_text(self):
        numbers, trace = self._numbers()
        docx = self.p("out", "paper.docx")
        info = MS.build_docx(self.proj, docx_path=docx, title="合成验证稿",
                             authors="Agent", numbers=numbers, trace=trace)
        pdf = self.p("out", "paper.pdf")
        try:
            out = MS.export_pdf(docx, pdf)
        except MS.ManuscriptError as exc:
            self.skipTest(f"no DOCX->PDF engine: {exc}")
        self.assertTrue(os.path.isfile(pdf))
        res = MS.verify_printed(self.proj, docx_path=docx,
                                spans={k: list(v) for k, v in
                                       info["spans"].items()}, pdf_path=pdf,
                                numbers=numbers, trace=trace)
        self.assertTrue(res["pdf"]["ok"], res["pdf"])
        self.assertGreaterEqual(res["pdf"]["pages"], 1)
        self.assertEqual(out["engine"], "word")

    def test_figure_dependency_registration(self):
        png = self.p("fig.png")
        make_png(png)
        info = MS.register_media_dependencies(
            self.proj, figures=[{"figure_id": "F1", "png": png,
                                 "results": ["M1.treatment"],
                                 "blocks": ["b_results"]}])
        self.assertGreaterEqual(info["edges"], 1)
        import depgraph
        graph = depgraph.DependencyGraph(self.proj)
        self.assertIn("figure:F1", [n["id"] for n in graph.nodes()])

    def test_word_pdf_restores_exact_original_image_and_rejects_wrong_backfill(self):
        from pathlib import Path
        from docx import Document
        from docx.shared import Cm
        import layout_check as LC
        png=Path(self.p("chart.png"));make_png(png)
        docx=Path(self.p("chart.docx")); pdf=Path(self.p("chart.pdf"))
        doc=Document();doc.add_picture(str(png),width=Cm(10));doc.add_paragraph("图 1 合成验证图");doc.save(docx)
        exported=MS.export_pdf(docx,pdf,figures=[{"figure_id":"F","png":str(png),"caption":"合成验证图"}])
        self.assertEqual(exported["figures_restored"],["F"])
        self.assertTrue(LC.match_images(LC.inspect_docx(docx),LC.inspect_pdf(pdf))["ok"])
        before=pdf.read_bytes()
        other=Path(self.p("other.png"))
        from PIL import Image
        Image.new("RGB",(50,50),"red").save(other)
        with self.assertRaises(MS.ManuscriptError):
            MS.export_pdf(docx,pdf,figures=[{"png":str(other),"caption":"合成验证图"}])
        self.assertEqual(pdf.read_bytes(),before)
