"""Independent synthetic counterexamples found in the multi-angle audit."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from _helpers import TempCase, run, write_csv, read_csv, make_png, make_docx, make_figure_pdf
from test_research_integrity import IntegrityCase
from verify_dataset import load_json, sha256


class IntegrityAudit(IntegrityCase):
    def test_raw_output_path_is_rejected_without_launch_or_original_change(self):
        raw = self.put("raw/excluded.txt", "SYNTHETIC ORIGINAL")
        self.approve_fixture()
        self.put("bad.py", "open('LAUNCHED','w').write('bad')\nopen('raw/excluded.txt','w').write('lost')\n")
        result = run("run_model.py", "--id", "M1", "--root", self.tmp, "--registry", "registry.json",
                     "--verification", "verify/dataset_verification.json", "--input", "data.csv", "--code", "bad.py",
                     "--output", "raw/excluded.txt", "--receipt", self.p("bad_run.json"), "--", "python", "bad.py")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(Path(self.p("LAUNCHED")).exists())
        self.assertEqual(Path(raw).read_text(), "SYNTHETIC ORIGINAL")

    def test_undeclared_raw_mutation_is_detected_and_restored(self):
        self.put("raw/excluded.txt", "SYNTHETIC ORIGINAL")
        self.approve_fixture()
        result = self.make_run("import os,stat\np='raw/excluded.txt'\nos.chmod(p,stat.S_IWRITE|stat.S_IREAD)\nopen(p,'w').write('lost')\n")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(Path(self.p("raw/excluded.txt")).read_text(), "SYNTHETIC ORIGINAL")
        self.assertTrue(load_json(self.p("run.json"))["source_protection"]["restored"])

    def test_stripped_old_receipt_never_bypasses_new_rules(self):
        self.approve_fixture()
        self.assertEqual(self.make_run().returncode, 0)
        receipt = load_json(self.p("run.json"))
        self.put("codebook.md", "New synthetic rule version")
        self.approve_fixture()
        receipt["inputs"] = [r for r in receipt["inputs"] if Path(r["path"]).name == "data.csv"]
        receipt.pop("verification")
        self.json("run.json", receipt)
        self.assertEqual(self.gate().returncode, 2)

    def test_empty_observation_requires_missing_kind_and_reason(self):
        write_csv(self.p("data.csv"), ["id", "x", "y", "total"], [["A", "", "3", "5"], ["B", "4", "5", "9"]])
        self.records[1]["value"] = ""
        self.jsonl("provenance.jsonl", self.records)
        self.assertEqual(self.check().returncode, 2)
        self.assertIn("empty observations", Path(self.p("verify/cell_issues.csv")).read_text(encoding="utf-8-sig"))

    def test_large_integer_sum_has_no_implicit_decimal_context_rounding(self):
        huge = 10 ** 28
        write_csv(self.source, ["id", "x", "y"], [["A", str(huge), "1"], ["B", "4", "5"]])
        self.records[1]["value"] = self.records[1]["sources"][0]["raw"] = str(huge)
        self.records[2]["value"] = self.records[2]["sources"][0]["raw"] = "1"
        for r in self.records:
            for s in r.get("sources", []):
                s["sha256"] = sha256(self.source)
        for total, expected in [(huge+1, 0), (huge, 2)]:
            write_csv(self.p("data.csv"), ["id", "x", "y", "total"], [["A", str(huge), "1", str(total)], ["B", "4", "5", "9"]])
            self.records[3]["value"] = str(total)
            self.jsonl("provenance.jsonl", self.records)
            self.assertEqual(self.check().returncode, expected)

    def test_corrupt_inventory_source_cannot_be_included(self):
        self.approve_fixture()
        self.make_run()
        write_csv(self.p("inventory.csv"), ["rel_path", "status"], [["source.csv", "corrupt"]])
        self.assertEqual(self.gate().returncode, 2)


class CorpusAudit(TempCase):
    def test_text_dedup_preserves_decimal_and_case_distinctions(self):
        from audit_corpus import content_key
        self.assertNotEqual(content_key("金额 1.2 万"), content_key("金额 12 万"))
        self.assertNotEqual(content_key("ID a1"), content_key("ID A1"))

    def test_content_duplicates_are_counted_and_removed_by_downstream_coding(self):
        raw = Path(self.p("raw")); raw.mkdir()
        text = "SYNTHETIC 这份测试材料有金额 1.2 万元以及相同的登记正文。" * 5
        (raw/"one.txt").write_text(text, encoding="utf-8")
        (raw/"two.txt").write_text(text, encoding="gb18030")
        (raw/"three.txt").write_bytes((raw/"one.txt").read_bytes())
        result = run("audit_corpus.py", "--root", raw, "--out-dir", self.p("audit"), "--content-dedupe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(load_json(self.p("audit/corpus_summary.json"))["unique_valid_files"], 1)
        result = run("dedupe_corpus.py", "--root", raw, "--audit", self.p("audit/corpus_files.csv"), "--out-dir", self.p("audit"))
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = read_csv(self.p("audit/dedupe_plan.csv"))
        self.assertEqual(sum(r["role"] == "duplicate" for r in plan), 2)
        result = run("make_coding_sheet.py", "--root", raw, "--audit", self.p("audit/corpus_files.csv"), "--out", self.p("coding"))
        self.assertEqual(result.returncode, 0, result.stderr)
        records = Path(self.p("coding/coding_sheet.jsonl")).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(records), 1)

    def test_office_story_text_includes_headers_footnotes_and_notes(self):
        from text_extract import extract_text
        for name, members, expected in [
            ("a.docx", {"word/document.xml": "正文", "word/footnotes.xml": "附注数据", "word/header1.xml": "表头数据"}, ["正文", "附注数据", "表头数据"]),
            ("a.pptx", {"ppt/slides/slide1.xml": "幻灯片", "ppt/notesSlides/notesSlide1.xml": "讲者数据"}, ["幻灯片", "讲者数据"])]:
            with zipfile.ZipFile(self.p(name), "w") as z:
                for member, value in members.items():
                    z.writestr(member, f"<root><p><t>{value}</t></p></root>".encode("utf-8"))
            text = extract_text(self.p(name))
            for value in expected:
                self.assertIn(value, text)


class StatisticsAudit(TempCase):
    def test_missing_category_does_not_become_reference_group(self):
        import methods_lib as ml
        df = pd.DataFrame({"g": ["A"]*15 + ["B"]*15 + [None]*15,
                           "y": list(np.arange(15))+list(np.arange(15)+10)+[1000]*15})
        res = ml.linear_regression(df, "y", ["g"], robust=None)
        table = res.tables[0][1].set_index("term")
        self.assertAlmostEqual(table.loc["g_B", "beta"], 10)
        self.assertEqual(res.stats["n"], 30)

    def test_numeric_dose_is_continuous_unless_codebook_says_category(self):
        import methods_lib as ml
        df = pd.DataFrame({"dose": [1,2,3,4,5]*12, "y": np.arange(60)})
        X, names = ml._design(df, ["dose"])
        self.assertEqual(names, ["dose"])
        df.attrs["variable_types"] = {"dose": "categorical"}
        self.assertEqual(ml._design(df, ["dose"])[0].shape[1], 4)

    def test_explicit_age_outcome_type_overrides_integer_code_heuristic(self):
        from analysis_utils import outcome_kind, encode_binary
        self.assertEqual(outcome_kind(pd.Series(range(20,70)), declared_type="continuous")[0], "continuous")
        self.assertIsNone(encode_binary(pd.Series(["a","b"]), {"a": .9, "b": 1.9})[0])

    def test_efa_diagnostics_use_same_complete_cases_as_correlation_matrix(self):
        import methods_lib as ml
        from scipy import stats
        rng = np.random.default_rng(42)
        full = pd.DataFrame(rng.normal(size=(80,3)), columns=list("abc"))
        tail = pd.DataFrame({"a": np.arange(50), "b": np.arange(50), "c": np.nan})
        df = pd.concat([full, tail], ignore_index=True)
        result = ml.kmo_bartlett(df, list("abc"))
        R = full.corr().to_numpy()
        statistic = -(len(full)-1-(2*3+5)/6)*np.log(np.linalg.det(R))
        self.assertAlmostEqual(result["bartlett_p"], stats.chi2.sf(statistic,3), places=5)
        self.assertEqual(result["n"], 80)

    def test_tied_prediction_auc_and_ap_are_invariant_to_row_order(self):
        import pubfig as pf
        for y in ([1,0,1,0], [0,1,0,1]):
            fig, axes = plt.subplots(1,2)
            self.assertAlmostEqual(pf.roc_curve(axes[0], y, [.8,.8,.2,.2]), .5)
            self.assertAlmostEqual(pf.pr_curve(axes[1], y, [.8,.8,.2,.2]), .5)
            plt.close(fig)

    def test_p_control_limits_use_each_point_sample_size(self):
        import pubfig as pf
        fig, ax = plt.subplots()
        rates, sizes = np.array([.2,.1,.1]), np.array([5,1000,1000])
        center = np.average(rates, weights=sizes)
        pf.control_chart(ax, [1,2,3], rates, sizes)
        expected = np.minimum(1, center + 3*np.sqrt(center*(1-center)/sizes))
        np.testing.assert_allclose(ax.lines[2].get_ydata(), expected)
        plt.close(fig)

    def test_km_uses_common_mask_for_missing_and_negative_times(self):
        import pubfig as pf
        fig, ax = plt.subplots()
        pf.kaplan_meier(ax, [1,2,3,None,-1], [1,0,1,1,1])
        self.assertTrue(ax.lines)
        self.assertAlmostEqual(ax.lines[0].get_ydata()[-1], 0)
        plt.close(fig)

    def test_forest_uses_beta_when_or_column_is_all_missing(self):
        import paper_figures as paper
        file = write_csv(self.p("coef.csv"), ["term","metric","beta","estimate","or","ci_low","ci_high","or_low","or_high"],
                         [["x","beta",2,2,"",1.9,2.1,"",""]])
        labels, estimates, low, high, metric = paper._forest_frame({"coef": file})
        self.assertEqual(estimates, [2.])
        self.assertEqual(low, [1.9])

    def test_scree_percentages_are_not_renormalized_to_one_hundred(self):
        import pubfig as pf
        fig, ax = plt.subplots()
        pf.scree_plot(ax, [70,20], values_are_percent=True, total_variables=4)
        self.assertEqual(fig.axes[1].lines[0].get_ydata()[-1], 90)
        plt.close(fig)

    def test_pca_chart_loadings_equal_correlations_with_component_scores(self):
        import auto_chart_pack as cp
        rng = np.random.default_rng(9)
        x = rng.normal(size=60)
        df = pd.DataFrame({f"x{i}": x+rng.normal(scale=.2,size=60) for i in range(3)})
        captured = []
        original = cp.heatmap
        def capture(ax, data, *args, **kwargs):
            captured.append(np.asarray(data))
            return original(ax, data, *args, **kwargs)
        pack = cp.ChartPack(df, self.tmp, {}, [], 8, 5)
        pack.save = lambda fig,*a,**k: plt.close(fig)
        with patch("auto_chart_pack.heatmap", side_effect=capture):
            pack.pca(list(df.columns), None)
        Z = (df-df.mean())/df.std()
        U,S,Vt = np.linalg.svd(Z,full_matrices=False)
        expected = np.array([[np.corrcoef(Z.iloc[:,i],U[:,j]*S[j])[0,1] for j in range(3)] for i in range(3)])
        np.testing.assert_allclose(np.abs(captured[0]), np.abs(expected), atol=1e-10)


class DeliveryAudit(TempCase):
    def test_empty_placeholder_and_malformed_table_never_build(self):
        from assemble_manuscript import load_numbers, read_table, SpecError
        file = write_csv(self.p("numbers.csv"), ["key","value"], [["n",""]])
        with self.assertRaises(SpecError): load_numbers(file)
        for text in ["g,n,n\nA,2,99\n", "g,n\nA,2,EXTRA\n"]:
            Path(self.p("table.csv")).write_text(text)
            with self.assertRaises(SpecError): read_table({"csv":"table.csv"},self.tmp)

    def test_wrong_p_and_coefficient_are_not_proved_by_broad_tolerance(self):
        import verify_numbers as vn
        table = vn.Table("table.csv", [{"p": ".001", "OR": "1.2"}])
        report = vn.Report()
        vn.check_text_numbers("p=.40；OR=1.65", "synthetic.md", [table], [], report, .5)
        self.assertEqual(report.errors, 2)
        report = vn.Report()
        vn.check_text_numbers("p=.40", "synthetic.md", [], [{"value":.4,"label":"proportion"}], report, .5)
        self.assertEqual(report.errors, 1)

    def test_lowercase_n_leading_decimal_and_p_leq_are_checked(self):
        import verify_numbers as vn
        values = vn.extract_text_numbers("n=999; β=.99; p≤.0001; t=42")
        self.assertEqual(len(values), 4)

    def test_corrupt_images_pdf_and_empty_output_paths_fail_qa(self):
        import qa_outputs as qa
        folder = Path(self.p("figs")); folder.mkdir()
        (folder/"bad.png").write_bytes(b"not an image")
        (folder/"bad.pdf").write_bytes(b"not a PDF")
        self.assertTrue(qa.check_figures(str(folder), min_fontsize=7.2)["errors"])
        manifest = write_csv(self.p("manifest.csv"), ["id","question","chart_type","variables","n","png","pdf","caption"],
                             [["F1","q","bar","x",3,"","","N=3"]])
        self.assertTrue(qa.check_manifest(manifest)["errors"])

    def test_vertical_dpi_is_checked_for_stretched_image(self):
        import fitz
        import qa_outputs as qa
        from export_pdf_hires import image_widths
        png = make_png(self.p("wide.png"), 3600,100)
        doc = fitz.open(); page=doc.new_page(); page.insert_image(fitz.Rect(50,50,475.2,410), filename=png,keep_proportion=False)
        self.assertLess(image_widths(doc)[0]["dpi"],25)
        doc.save(self.p("stretch.pdf")); doc.close()
        self.assertTrue(qa.check_pdf(self.p("stretch.pdf"),min_dpi=600)["errors"])

    def test_docx_actual_width_scales_source_vector_font_size(self):
        import fitz
        import qa_outputs as qa
        folder=Path(self.p("figs")); folder.mkdir()
        doc=fitz.open(); page=doc.new_page(width=15/2.54*72,height=5/2.54*72)
        page.insert_text((30,40), "SYNTHETIC 7.3 pt",fontsize=7.3)
        doc.save(str(folder/"Figure1.pdf"))
        page.get_pixmap(dpi=600).save(str(folder/"Figure1.png"));doc.close()
        make_docx(self.p("paper.docx"), ["图1 Synthetic"],str(folder/"Figure1.png"),width_cm=6)
        placements=qa.check_docx(self.p("paper.docx"))["placements"]
        report=qa.check_figures(str(folder),min_fontsize=7.2,placements=placements)
        self.assertTrue(report["errors"])
        self.assertAlmostEqual(report["min_fontsize"],2.92,places=1)

    def test_wrong_figure_title_does_not_backfill_another_image(self):
        import fitz
        from export_pdf_hires import find_figure_page
        doc=fitz.open();page=doc.new_page();png=make_png(self.p("x.png"))
        page.insert_image(fitz.Rect(50,50,250,150),filename=png)
        page.insert_text((50,170),"Figure1 Actual caption")
        self.assertIsNone(find_figure_page(doc,"Figure1","Wrong title"))
        doc.close()

    def test_empty_number_issue_report_is_reported_as_provided(self):
        from review_pack import _verify_section
        file=write_csv(self.p("issues.csv"),["severity","check","where","detail"],[])
        result=_verify_section(file)
        self.assertTrue(result["provided"])
        self.assertEqual(result["total"],0)
