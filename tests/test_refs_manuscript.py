# -*- coding: utf-8 -*-
"""References (T27) and print-time manuscript evidence binding (T28).

Covers A33 (DOI exists but does not support the claim; abstract-only cannot
claim a full-text check) and A53 (an edited/reprinted sentence loses its old
support), plus the requirement that every printed number is traceable and the
printed text still matches the reviewed ledger blocks.
"""
import json
import os
from pathlib import Path

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

    def _docx(self, numbers, trace, figures=()):
        """Build the printed DOCX the way the single chain does: literal text."""
        from docx import Document
        from docx.shared import Cm
        os.makedirs(self.p("out"), exist_ok=True)
        docx = self.p("out", "paper.docx")
        doc = Document()
        for index, fig in enumerate(figures, 1):
            doc.add_picture(str(fig["png"]), width=Cm(fig.get("width_cm", 12)))
            doc.add_paragraph(f"图 {index}　{fig['caption']}")
        for section in ("abstract", "introduction", "methods",
                        "results", "discussion"):
            expected, _ = MS.resolve_numbers(self.blocks[section], numbers,
                                             trace, project=self.proj)
            for chunk in expected.split("\n\n"):
                doc.add_paragraph(chunk.strip())
        doc.save(docx)
        return docx

    def test_missing_required_section_is_reported(self):
        proj = C.Project(self.p("other"))
        CL.register_block(proj, block_id="b_abstract", section="abstract",
                          text=self.blocks["abstract"], claims=[])
        problems = MS.check_sections(
            MS.latest_blocks(proj), required_sections=MS.REQUIRED_SECTIONS)
        self.assertTrue(any(p["check"] == "section_missing"
                            and p["section"] == "introduction"
                            for p in problems))

    def test_untraceable_number_is_refused(self):
        numbers, trace = self._numbers()
        numbers["effect"] = "0.42"
        with self.assertRaises(MS.ManuscriptError) as ctx:
            MS.resolve_numbers(self.blocks["results"], numbers, {},
                               project=self.proj)
        self.assertIn("no trace", str(ctx.exception))

    def test_placeholder_without_value_is_refused(self):
        numbers, trace = self._numbers()
        del numbers["effect"]
        with self.assertRaises(MS.ManuscriptError) as ctx:
            MS.resolve_numbers(self.blocks["results"], numbers, trace,
                               project=self.proj)
        self.assertIn("no value", str(ctx.exception))

    def test_nonexistent_numeric_trace_is_refused(self):
        with self.assertRaises(MS.ManuscriptError):
            MS.resolve_numbers("estimate={beta}", {"beta": 999999},
                               {"beta": {"model": "DOES_NOT_EXIST"}},
                               project=self.proj)

    def test_printed_docx_text_matches_the_reviewed_blocks(self):
        numbers, trace = self._numbers()
        png = self.p("fig.png")
        make_png(png)
        figures = [{"figure_id": "F1", "png": png, "caption": "合成示例图",
                    "width_cm": 12}]
        docx = self._docx(numbers, trace, figures=figures)
        self.assertTrue(os.path.isfile(docx))
        res = MS.verify_printed(self.proj, docx_path=Path(docx),
                                numbers=numbers, trace=trace,
                                figures=[{**figures[0], "png": str(png)}])
        self.assertTrue(res["ok"], res)
        self.assertEqual(len(res["blocks"]), 5)
        self.assertTrue(all(b["ok"] for b in res["blocks"]))
        self.assertTrue(res["captions_ok"])

    def test_editing_the_ledger_after_printing_makes_the_block_stale(self):
        numbers, trace = self._numbers()
        docx = self._docx(numbers, trace)
        CL.register_block(
            self.proj, block_id="b_results", section="results",
            text=self.blocks["results"].replace("{effect}", "0.99"), claims=[])
        res = MS.verify_printed(self.proj, docx_path=Path(docx),
                                numbers=numbers, trace=trace, persist=False)
        self.assertFalse(res["ok"])
        stale = [b for b in res["blocks"] if b["status"] == "stale"]
        self.assertEqual([b["block"] for b in stale], ["b_results"])
        self.assertEqual(stale[0]["findings"][0]["check"],
                         "printed_text_mismatch")

    def test_pdf_export_contains_the_reviewed_text(self):
        from _helpers import run
        numbers, trace = self._numbers()
        docx = self._docx(numbers, trace)
        pdf = self.p("out", "paper.pdf")
        out = run("export_pdf_hires.py", "--docx", docx, "--out-pdf", pdf)
        if out.returncode != 0:
            self.skipTest(f"no DOCX->PDF engine: {out.stderr[:200]}")
        res = MS.verify_printed(self.proj, docx_path=Path(docx),
                                pdf_path=Path(pdf), numbers=numbers,
                                trace=trace, persist=False)
        self.assertTrue(res["pdf"]["ok"], res["pdf"])
        self.assertGreaterEqual(res["pdf"]["pages"], 1)
        self.assertTrue(res["ok"], res)

    def test_release_manuscript_branch_needs_the_real_docx(self):
        import release as R
        numbers, trace = self._numbers()
        result = R.evaluate(self.proj, {"sections": ["results"], "models": [],
                                        "claims": [], "allow_limited": True})
        check = next(c for c in result["checks"]
                     if c["check"] == "manuscript_verified")
        self.assertFalse(check["ok"])
        self.assertIn("scope.docx", check["detail"])

    def test_release_manuscript_branch_passes_on_a_matching_docx(self):
        import release as R
        from _helpers import run
        numbers, trace = self._numbers()
        docx = self._docx(numbers, trace)
        pdf = self.p("out", "paper.pdf")
        out = run("export_pdf_hires.py", "--docx", docx, "--out-pdf", pdf)
        if out.returncode != 0:
            self.skipTest(f"no DOCX->PDF engine: {out.stderr[:200]}")
        result = R.evaluate(self.proj, {
            "sections": ["results"], "models": [], "claims": [],
            "allow_limited": True, "docx": "out/paper.docx",
            "pdf": "out/paper.pdf", "numbers": numbers, "trace": trace})
        check = next(c for c in result["checks"]
                     if c["check"] == "manuscript_verified")
        self.assertTrue(check["ok"], check)
        numbers_check = next(c for c in result["checks"]
                             if c["check"] == "numbers_traceable")
        self.assertTrue(numbers_check["ok"], numbers_check)

    def test_omitting_numbers_and_trace_does_not_launder_numbers_traceable(self):
        # a literal-text manuscript with no declared numbers verifies zero
        # numbers: that must NOT upgrade a missing trace report to "verified"
        import release as R
        from docx import Document
        from _helpers import run
        proj = C.Project(self.p("plain"))
        text = "工作簿合计为 128，与独立重算一致。"
        CL.register_block(proj, block_id="b_results", section="results",
                          text=text, claims=[])
        docx = self.p("plain", "out", "paper.docx")
        os.makedirs(os.path.dirname(docx), exist_ok=True)
        doc = Document()
        doc.add_paragraph(text)
        doc.save(docx)
        pdf = self.p("plain", "out", "paper.pdf")
        out = run("export_pdf_hires.py", "--docx", docx, "--out-pdf", pdf)
        if out.returncode != 0:
            self.skipTest(f"no DOCX->PDF engine: {out.stderr[:200]}")
        result = R.evaluate(proj, {
            "sections": ["results"], "models": [], "claims": [],
            "allow_limited": True, "docx": "out/paper.docx",
            "pdf": "out/paper.pdf"})
        mv = next(c for c in result["checks"]
                  if c["check"] == "manuscript_verified")
        nt = next(c for c in result["checks"]
                  if c["check"] == "numbers_traceable")
        self.assertTrue(mv["ok"], mv)          # the text is genuinely printed
        self.assertFalse(nt["ok"], nt)         # ...but zero numbers were bound
        self.assertTrue(any("no numbers were bound" in w.get("detail", "")
                            for w in result["warnings"]), result["warnings"])

    def test_literal_placeholder_without_numbers_is_refused(self):
        from docx import Document
        proj = C.Project(self.p("ph"))
        CL.register_block(proj, block_id="b_results", section="results",
                          text="处理效应为 {effect}。", claims=[])
        docx = self.p("ph", "paper.docx")
        doc = Document()
        doc.add_paragraph("处理效应为 {effect}。")
        doc.save(docx)
        with self.assertRaises(MS.ManuscriptError) as ctx:
            MS.verify_printed(proj, docx_path=Path(docx), persist=False)
        self.assertIn("no value", str(ctx.exception))

    def test_declared_but_unresolved_trace_does_not_upgrade_numbers(self):
        # a non-empty scope.trace with zero resolved numbers is still zero
        # bindings: it must not launder a missing trace report either
        import release as R
        from docx import Document
        from _helpers import run
        proj = C.Project(self.p("junk"))
        text = "工作簿合计为 128，与独立重算一致。"
        CL.register_block(proj, block_id="b_results", section="results",
                          text=text, claims=[])
        docx = self.p("junk", "out", "paper.docx")
        os.makedirs(os.path.dirname(docx), exist_ok=True)
        doc = Document()
        doc.add_paragraph(text)
        doc.save(docx)
        pdf = self.p("junk", "out", "paper.pdf")
        out = run("export_pdf_hires.py", "--docx", docx, "--out-pdf", pdf)
        if out.returncode != 0:
            self.skipTest(f"no DOCX->PDF engine: {out.stderr[:200]}")
        result = R.evaluate(proj, {
            "sections": ["results"], "models": [], "claims": [],
            "allow_limited": True, "docx": "out/paper.docx",
            "pdf": "out/paper.pdf", "numbers": {}, "trace": {"junk": {}}})
        mv = next(c for c in result["checks"]
                  if c["check"] == "manuscript_verified")
        nt = next(c for c in result["checks"]
                  if c["check"] == "numbers_traceable")
        self.assertTrue(mv["ok"], mv)          # the text is genuinely printed
        self.assertFalse(nt["ok"], nt)         # zero numbers bound: no upgrade
        self.assertNotEqual(result["status"], "complete")

    def test_release_scope_figures_shape_is_validated(self):
        import release as R
        # historical identity form: strings are legal and fold into checks
        result = R.evaluate(self.proj, {"sections": ["results"], "models": [],
                                        "claims": [], "allow_limited": True,
                                        "figures": ["F1"]})
        self.assertIn("checks", result)
        mv = next((c for c in result["checks"]
                   if c["check"] == "manuscript_verified"), None)
        self.assertIsNotNone(mv)
        self.assertFalse(mv["ok"])             # still no scope.docx
        # a spec dict in the identity list is refused, not a raw traceback
        result = R.evaluate(self.proj, {"sections": ["results"], "models": [],
                                        "claims": [], "allow_limited": True,
                                        "figures": [{"figure_id": "F1"}]})
        self.assertEqual(result["status"], "not_ready")
        self.assertIn("figure id strings", result["checks"][0]["detail"])

    def test_missing_caption_fails_the_print_check(self):
        numbers, trace = self._numbers()
        docx = self._docx(numbers, trace)
        res = MS.verify_printed(self.proj, docx_path=Path(docx),
                                numbers=numbers, trace=trace,
                                figures=[{"figure_id": "F9",
                                          "caption": "不存在的图题"}],
                                persist=False)
        self.assertFalse(res["captions_ok"])
        self.assertFalse(res["ok"])

    def test_cli_verify_rejects_bad_inputs_cleanly(self):
        from _helpers import run
        numbers, trace = self._numbers()
        docx = self._docx(numbers, trace)
        root = str(self.proj.root)
        out = run("manuscript.py", "--root", root, "verify",
                  "--docx", self.p("nope.docx"))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is missing", out.stderr)
        out = run("manuscript.py", "--root", root, "verify",
                  "--docx", docx, "--numbers", self.p("missing.json"))
        self.assertEqual(out.returncode, 2)
        self.assertIn("cannot read", out.stderr)
        bad = self.p("bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{oops")
        out = run("manuscript.py", "--root", root, "verify",
                  "--docx", docx, "--numbers", bad)
        self.assertEqual(out.returncode, 2)
        self.assertIn("not valid JSON", out.stderr)
        nums = self.p("numbers.json")
        tracef = self.p("trace.json")
        with open(nums, "w", encoding="utf-8") as fh:
            json.dump(numbers, fh, ensure_ascii=False)
        with open(tracef, "w", encoding="utf-8") as fh:
            json.dump(trace, fh, ensure_ascii=False)
        out = run("manuscript.py", "--root", root, "verify",
                  "--docx", docx, "--numbers", nums, "--trace", tracef)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue((self.proj.root / "output" / "v2" / "manuscript"
                         / "verification.json").is_file())

    def test_cli_sections_flags_stale_blocks(self):
        from _helpers import run
        numbers, trace = self._numbers()
        docx = self._docx(numbers, trace)
        root = str(self.proj.root)
        out = run("manuscript.py", "--root", root, "sections")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("results", out.stdout)
        CL.register_block(
            self.proj, block_id="b_results", section="results",
            text=self.blocks["results"].replace("{effect}", "0.77"), claims=[])
        MS.verify_printed(self.proj, docx_path=Path(docx),
                          numbers=numbers, trace=trace)
        out = run("manuscript.py", "--root", root, "sections")
        self.assertEqual(out.returncode, 2)
        self.assertIn("block_stale", out.stdout)
