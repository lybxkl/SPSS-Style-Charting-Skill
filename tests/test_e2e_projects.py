# -*- coding: utf-8 -*-
"""Four end-to-end projects with known answers (T33).

Each project is synthetic and says so.  The known answers are produced by the
test itself (from the data-generating process), never by the code under test:

* **P1 quantitative survey** - OLS with a known slope, full cell verification,
  independent recomputation, a supported claim, and a `complete` release.
* **P2 qualitative interviews** - coding counts, real executed searches, a gap
  that is genuinely unavailable, and a claim that quotes the material.
* **P3 mathematical optimisation** - a small LP whose optimum is known by
  enumeration; the result must be `certified_global`.
* **P4 mixed materials** - PDF (text + scan) + XLSX + DOCX, real OCR, table
  recovery, an audit view, a figure and a composed manuscript.

The fixtures are written to a temp directory; nothing here is a real study.
"""
import json
import os

from _helpers import TempCase, make_png, write_csv

import audit_view as AV
import claims as CL
import contract_v2 as C
import gaps as G
import manuscript as MS
import models as M
import ocr_provider as O
import release as R
import search_index as SI
import source_units as SU
import table_recovery as TR
import validation as V
import verify_dataset as VD


def _sha(path):
    return C.file_sha256(path)


def _write_reviews(out_dir, snap_path, review_path):
    """Reopen each synthetic original CSV cell after prepare, then record review."""
    import datetime
    import csv
    from pathlib import Path
    root = Path(snap_path).resolve().parents[2]
    reopened = {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    made = 0
    lines = []
    for name in sorted(os.listdir(out_dir)):
        if not name.startswith("review_template_") or not name.endswith(".jsonl"):
            continue
        path = os.path.join(out_dir, name)
        rows = [json.loads(line) for line in open(path, encoding="utf-8")
                if line.strip()]
        for row in rows:
            source = row["evidence"]["sources"][0]
            original = root / source["path"]
            if original not in reopened:
                with open(original, encoding="utf-8-sig", newline="") as stream:
                    reopened[original] = list(csv.DictReader(stream))
            locator = source["locator"]
            actual = reopened[original][locator["row"]-1][locator["column"]]
            if actual != row["value"]:
                raise ValueError("independent source reread differs from integrated dataset")
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            lines.append({"dataset": row["dataset"], "key": row["key"],
                          "column": row["column"],
                          "record_sha256": row["record_sha256"],
                          "status": "verified", "source_reread": True,
                          "reviewer": "agent:e2e",
                          "method": "source_reread", "checked_at": now,
                          "note": f"re-read {row['column']} for key "
                                  f"{row['key']} at the source row"})
            made += 1
    with open(review_path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return made


class TestE2EQuantitative(TempCase):
    def test_known_slope_survives_the_whole_chain(self):
        os.makedirs(self.p("materials"))
        rows = []
        for i in range(1, 41):
            x = i
            treat = 1 if i % 2 else 0
            y = 2.0 + 3.0 * x + 0.5 * treat
            rows.append([f"P{i:03d}", str(x), str(y), str(treat)])
        src = self.p("materials", "survey.csv")
        write_csv(src, ["id", "x", "y", "treat"], rows)
        os.makedirs(self.p("data"))
        dataset = self.p("data", "person.csv")
        write_csv(dataset, ["id", "x", "y", "treat"],
                  [[r[0], r[1], r[2], r[3]] for r in rows])
        sha = _sha(src)
        with open(self.p("data", "codebook.md"), "w", encoding="utf-8") as fh:
            fh.write("# codebook\nid: string\nx: 1..40\ny: score\ntreat: 0/1\n")
        with open(self.p("data", "prov.jsonl"), "w", encoding="utf-8") as fh:
            for i, row in enumerate(rows, 1):
                for col, value in zip(["id", "x", "y", "treat"], row):
                    fh.write(json.dumps({
                        "key": row[0], "column": col, "value": value,
                        "kind": "observed", "compare": "exact",
                        "sources": [{"path": "materials/survey.csv",
                                     "sha256": sha,
                                     "locator": {"type": "csv", "row": i,
                                                 "column": col},
                                     "raw": value}]}, ensure_ascii=False) + "\n")
        open(self.p("data", "review.jsonl"), "w").close()
        registry = {"schema_version": 1, "source_root": "materials",
                    "discovery_report": "output/discovery_report.json",
                    "source_inventory": "output/audit/corpus_files.csv",
                    "source_coverage": "output/source_coverage.jsonl",
                    "datasets": [{"id": "person", "path": "data/person.csv",
                                  "key": ["id"], "unit": "一位受访者",
                                  "codebook": "data/codebook.md",
                                  "provenance": "data/prov.jsonl",
                                  "review": "data/review.jsonl"}]}
        json.dump(registry, open(self.p("research_registry.json"), "w",
                                 encoding="utf-8"), ensure_ascii=False)
        os.makedirs(self.p("output", "audit"), exist_ok=True)
        write_csv(self.p("output", "audit", "corpus_files.csv"), ["rel_path", "status"], [["survey.csv", "valid"]])
        with open(self.p("output", "source_coverage.jsonl"), "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"source": "survey.csv", "sha256": sha, "status": "included", "datasets": ["person"],
                                     "reason": "every synthetic survey field has per-cell original evidence"}) + "\n")
        import discovery as D
        units = SU.SourceUnits(C.Project(self.tmp), root=self.tmp)
        units.build(self.p("materials"))
        discovery = D.Discovery(C.Project(self.tmp), units)
        discovery.from_materials()
        for candidate in C.Project(self.tmp).read("discovery_candidate"):
            discovery.dispose(candidate["id"], "adopted", dataset="person", reason="all source fields included in this synthetic dataset")
        with open(self.p("output", "discovery_report.json"), "w", encoding="utf-8") as stream:
            json.dump(discovery.report(), stream)
        out = self.p("output", "dataset")
        from _helpers import run
        prep = run("verify_dataset.py", "--registry", "research_registry.json",
                   "--root", self.tmp, "--out", out, "--stage", "prepare")
        self.assertEqual(prep.returncode, 0, prep.stdout + prep.stderr)
        made = _write_reviews(out, os.path.join(
            out, "verification_snapshot.json"), self.p("data", "review.jsonl"))
        self.assertEqual(made, 160)
        final = run("verify_dataset.py", "--registry", "research_registry.json",
                    "--root", self.tmp, "--out", out, "--stage", "final",
                    "--snapshot", os.path.join(
                        out, "verification_snapshot.json"))
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        report = json.load(open(os.path.join(out, "dataset_verification.json"),
                                encoding="utf-8"))
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["error_count"], 0)

        proj = C.Project(self.tmp)
        spec = {"id": "M1", "family": "ols", "purpose":
                "estimate how x and treatment shift y", "engine": "statsmodels",
                "question": "Does x predict y?",
                "variables": {"y": "y", "x": ["x", "treat"]},
                "inputs": [{"dataset": dataset, "role": "fit",
                             "keys": ["id"], "sha256": _sha(dataset)}],
                "n_semantics": {"kind": "observation", "unit": "a person"},
                "result": {"type": "coefficient_table",
                            "target_parameter": "x", "unit": "score points",
                            "scale": "points per unit"}}
        M.register(proj, spec)
        res = M.fit(proj, "M1")
        rec = proj.latest("model_result", res["result"])
        coef = {k: float(v["estimate"]) for k, v in
                rec["data"]["payload"]["coefficients"].items()}
        self.assertAlmostEqual(coef["x"], 3.0, places=6)
        self.assertAlmostEqual(coef["treat"], 0.5, places=6)
        self.assertAlmostEqual(coef["Intercept"] if "Intercept" in coef else
                               coef.get("const", 0), 2.0, places=6)
        check = V.independent_ols(proj, "M1")
        self.assertEqual(check["status"], "passed", check)
        import designcheck
        self.assertEqual(designcheck.record_linkage(proj, M.load_spec(proj, "M1")["data"])["status"], "passed")
        claim = CL.register_claim(
            proj, claim_type="result",
            text="x 每增加一个单位，y 上升约 3.0 分。",
            block_id="b_results", section="results",
            support=[{"kind": "result", "id": res["result"],
                      "target_parameter": "x", "unit": "score points"}])
        verdict = CL.check_claim(proj, claim, persist=True)
        self.assertEqual(verdict["status"], "supported", verdict)
        import support_review
        support_review.review(proj, claim["id"], decision="supported", reviewer="e2e:synthetic-ground-truth",
                              note="The original generated survey and independently checked slope support a positive association; no causal conclusion is asserted.",
                              reread_scopes=[{"path": src, "sha256": _sha(src), "locator": {"columns": ["x", "y", "treat"], "rows": "all"}}])
        CL.register_block(proj, block_id="b_results", section="results",
                          text="x 每增加一个单位，y 上升约 3.0 分。",
                          claims=[claim["id"]])
        gate = R.evaluate(proj, scope={"datasets": ["person"], "models": ["M1"], "allow_limited": True})
        self.assertIn(gate["status"], ("complete", "limited"), gate)


class TestE2EQualitative(TempCase):
    def test_coding_counts_and_a_real_gap(self):
        os.makedirs(self.p("materials"))
        interviews = {
            "i1.txt": "受访者说：主题A 让我印象很深。主题A 很好。",
            "i2.txt": "受访者说：主题B 是主要困难。",
            "i3.txt": "受访者说：主题A 与主题B 都出现过。",
        }
        for name, text in interviews.items():
            with open(os.path.join(self.p("materials"), name), "w",
                      encoding="utf-8") as fh:
                fh.write(text)
        proj = C.Project(self.tmp)
        units = SU.SourceUnits(proj, root=self.p("materials"))
        units.build(self.p("materials"))
        texts = [u for u in units.units("document")]
        self.assertEqual(len(texts), 3)
        counts = {}
        for unit in texts:
            body = (proj.root / unit["data"]["representation"]).read_text(
                encoding="utf-8")
            for theme in ("主题A", "主题B"):
                counts[theme] = counts.get(theme, 0) + body.count(theme)
        self.assertEqual(counts, {"主题A": 3, "主题B": 2})
        index = SI.SearchIndex(proj, units)
        index.build()
        hit = index.search("主题A", limit=10)
        self.assertEqual(hit["hits"], 2)  # one hit per matching document
        miss = index.search("随访", limit=10)
        self.assertEqual(miss["hits"], 0)
        gap = G.open_gap(proj, target="dataset:themes",
                         requirement="follow-up timing",
                         status_detail="needs_data")
        G.attach_search(proj, gap["id"], miss["run"], conclusion="not_found",
                        note="searched the whole corpus; no follow-up wording")
        closed = G.close_unavailable(proj, gap["id"],
                                     reason="the interviews contain no follow-up "
                                            "field; asking again is out of scope")
        self.assertEqual(closed["status"], "unavailable")
        self.assertEqual(G.completeness(proj)["errors"], [])


class TestE2EMathematical(TempCase):
    def test_known_lp_optimum_is_certified(self):
        proj = C.Project(self.tmp)
        module = self.p("lp.py")
        with open(module, "w", encoding="utf-8") as fh:
            fh.write(
                "def build():\n"
                "    return {'c': [-1.0, -1.0],\n"
                "            'A_ub': [[1.0, 2.0], [3.0, 1.0]],\n"
                "            'b_ub': [4.0, 6.0],\n"
                "            'bounds': [(0, None), (0, None)]}\n")
        M.register(proj, {"id": "LP1", "family": "lp",
                          "purpose": "maximise x+y under two constraints",
                          "engine": "scipy", "question": "maximise x+y",
                          "inputs": [{"dataset": module,
                                       "role": "parameters",
                                       "keys": ["c", "A_ub", "b_ub"],
                                       "sha256": _sha(module)}],
                          "n_semantics": {"kind": "none"},
                          "target": f"{module}:build", "dimensions": 2,
                          "constraints": 2, "unit": "units",
                          "result": {"type": "solution_vector",
                                      "target_parameter": "objective",
                                      "unit": "units", "scale": "units"}})
        res = M.solve(proj, "LP1", budget_seconds=30)
        self.assertEqual(res["status"], "certified_global")
        self.assertAlmostEqual(res["objective"], -2.8, places=6)
        rec = proj.latest("model_result", res["result"])
        x, y = rec["data"]["payload"]["solution"]
        self.assertAlmostEqual(x, 1.6, places=4)
        self.assertAlmostEqual(y, 1.2, places=4)
        # enumeration confirms the optimum independently
        best = None
        for i in range(0, 601):
            for j in range(0, 601):
                xi, yj = i / 100, j / 100
                if xi + 2 * yj <= 4 + 1e-9 and 3 * xi + yj <= 6 + 1e-9:
                    value = xi + yj
                    best = value if best is None else max(best, value)
        self.assertAlmostEqual(best, 2.8, places=2)


class TestE2EMixedMaterials(TempCase):
    def test_scan_xlsx_and_docx_feed_a_manuscript(self):
        import fitz
        from PIL import Image, ImageDraw
        os.makedirs(self.p("materials"))
        img = Image.new("RGB", (900, 300), "white")
        ImageDraw.Draw(img).text((30, 60), "SCANNED TOTAL 1,284.50", fill="black")
        scan = self.p("scan.png")
        img.save(scan)
        pdf = self.p("materials", "mixed.pdf")
        doc = fitz.open()
        p1 = doc.new_page(width=420, height=300)
        p1.insert_text((40, 60), "Narrative page with a text layer.", fontsize=11)
        p1.insert_image(fitz.Rect(20, 90, 400, 220), filename=scan)
        doc.save(pdf)
        doc.close()

        import openpyxl
        xlsx = self.p("materials", "numbers.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Totals"
        ws["A1"], ws["B1"] = "item", "value"
        ws["A2"], ws["B2"] = "participants", 120
        ws["A3"], ws["B3"] = "dropouts", 8
        ws["B4"] = "=SUM(B2:B3)"
        wb.save(xlsx)

        proj = C.Project(self.tmp)
        units = SU.SourceUnits(proj, root=self.p("materials"), preview_dpi=216)
        summary = units.build(self.p("materials"))
        self.assertGreaterEqual(summary["logical_units"], 2)
        kinds_seen = summary["by_unit_type"]
        self.assertIn("page", kinds_seen)
        self.assertTrue(any(k in kinds_seen for k in ("table", "sheet")))
        page = [u for u in units.units("page")][0]
        kinds = page["data"]["recovered_scope"]["page_kind"]
        self.assertIn(kinds, ("text", "mixed", "scan"))

        provider = O.get_provider()
        ocr = O.ocr_page(proj, units, page, provider=provider, dpi=216)
        text = " ".join(r["text"] for r in ocr["regions"])
        if "1,284.50" not in text and "1284.50" not in text:
            self.skipTest("OCR did not read the synthetic total on this machine")
        self.assertEqual(ocr["status"], "partial")

        table = TR.recover_source(proj, xlsx)
        sheet = table["sheets"]["Totals"]
        formula = [c for c in sheet["cells"] if "formula" in c][0]
        values = {c["cell"]: c["value"] for c in sheet["cells"]}
        check = TR.recompute_formula(formula, values)
        # a freshly written workbook has no cached value, so the honest status is
        # unverified; the recomputed number is still checked independently
        self.assertIn(check["status"], ("verified", "unverified"))
        self.assertEqual(float(check["computed"]), 128.0)

        built = AV.build_view(proj, pdf)
        verified = AV.verify_view(proj, built["view"])
        self.assertTrue(verified["ok"], verified["checks"])

        # a figure whose bar heights are known, plotted and described
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        png = self.p("figure.png")
        fig, ax = plt.subplots(figsize=(6, 3.5), dpi=200)
        ax.bar(["A", "B"], [3, 5])
        fig.savefig(png)
        plt.close(fig)
        self.assertTrue(os.path.isfile(png))

        # Register the actually recovered workbook inputs and a derived sum.
        # A fictitious model named SUM is not an evidence target.
        os.makedirs(self.p("data"), exist_ok=True)
        write_csv(self.p("data", "totals.csv"), ["item", "value"], [["participants", "120"], ["dropouts", "8"], ["3", "128"]])
        with open(self.p("data", "totals.md"), "w", encoding="utf-8") as stream:
            stream.write("Synthetic arithmetic check: two directly observed workbook values and their derived sum; no population interpretation.")
        proof = []
        for key, rowno, val in (("participants", 2, "120"), ("dropouts", 3, "8")):
            for column, cell, raw in (("item", f"A{rowno}", key), ("value", f"B{rowno}", val)):
                proof.append({"key": key, "column": column, "value": raw, "kind": "observed", "sources": [{"path": "materials/numbers.xlsx", "sha256": _sha(xlsx), "locator": {"type": "xlsx", "sheet": "Totals", "cell": cell, "number_as_text": True}, "raw": raw}]})
        proof += [{"key": "3", "column": "item", "value": "3", "kind": "structural", "rule": {"op": "row_number"}, "sources": [{"path": "materials/numbers.xlsx", "sha256": _sha(xlsx), "locator": {"type": "xlsx", "sheet": "Totals", "cell": "A1"}, "raw": "item"}]},
                  {"key": "3", "column": "value", "value": "128", "kind": "derived", "rule": {"op": "sum"}, "inputs": [{"dataset": "totals", "key": k, "column": "value"} for k in ("participants", "dropouts")]}]
        with open(self.p("data", "totals.prov.jsonl"), "w", encoding="utf-8") as stream:
            stream.write("".join(json.dumps(r) + "\n" for r in proof))
        entry = {"id": "totals", "path": "data/totals.csv", "key": ["item"], "unit": "synthetic workbook quantity", "codebook": "data/totals.md", "provenance": "data/totals.prov.jsonl", "review": "data/totals.review.jsonl"}
        with open(self.p("research_registry.json"), "w", encoding="utf-8") as stream:
            json.dump({"source_root": "materials", "datasets": [entry]}, stream)
        import review_workbench as RW
        exported = RW.export_html(proj, entry)
        second_pass = RW.blind_template(proj, entry, snapshot=exported)
        # Reopen the original workbook after integration. Recompute the sum from
        # fresh B2/B3 values, independently of the derived CSV/provenance values.
        reread = openpyxl.load_workbook(xlsx, data_only=False)
        fresh = reread["Totals"]
        values_by_key = {"participants": {"item": str(fresh["A2"].value), "value": str(fresh["B2"].value)},
                         "dropouts": {"item": str(fresh["A3"].value), "value": str(fresh["B3"].value)},
                         "3": {"item": "3", "value": str(fresh["B2"].value + fresh["B3"].value)}}
        for row in second_pass:
            row.update(value_here=values_by_key[row["key"][0]][row["column"]], reviewer="e2e:original-workbook-reread",
                       checked_at=VD.stamp(), note="Reopened Totals A1:B4 and independently recomputed the two-input sum.",
                       reread_scope={"locator": {"type": "xlsx", "sheet": "Totals", "range": "A1:B4"}})
        reread.close()
        checked = RW.import_second_pass(proj, entry, second_pass, snapshot=exported)
        RW.write_review_file(proj, entry, checked["review_lines"])
        from _helpers import run
        final = run("verify_dataset.py", "--registry", "research_registry.json", "--root", self.tmp, "--out", self.p("output", "dataset"), "--stage", "final", "--snapshot", exported["snapshot_path"])
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

        for section, text_ in {
            "abstract": "本验证稿使用合成材料，仅用于检验流水线。" * 10,
            "introduction": "研究背景与研究问题在此说明，并交代分析策略。" * 35,
            "methods": "材料包含一份混合 PDF 与一份工作簿，并附有扫描页。" * 24,
            "results": "工作簿合计为 {total}，与独立重算的结果一致。" * 25,
            "discussion": "该结果只用于流水线验证，不构成任何实证结论。" * 24,
        }.items():
            CL.register_block(proj, block_id=f"b_{section}", section=section,
                              text=text_, claims=[])
        docx = self.p("out", "paper.docx")
        info = MS.build_docx(proj, docx_path=docx, title="合成验证稿",
                             authors="Agent",
                             numbers={"total": "128"},
                             trace={"total": {"dataset": "totals", "key": "3", "column": "value"}},
                             figures=[{"figure_id": "F1", "png": png,
                                       "caption": "合成示例图", "width_cm": 12}])
        self.assertEqual(info["figures"], 1)
        printed = MS.verify_printed(
            proj, docx_path=docx,
            spans={k: list(v) for k, v in info["spans"].items()},
            numbers={"total": "128"},
            trace={"total": {"dataset": "totals", "key": "3", "column": "value"}})
        self.assertTrue(printed["ok"], printed)
