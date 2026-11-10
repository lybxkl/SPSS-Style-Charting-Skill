import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, run, write_csv, read_csv, make_png, make_text_pdf

import contextlib
import csv
import glob
import io
import json
from unittest import mock

import audit_corpus
import text_extract

LONG = "本研究使用问卷调查数据，样本来自三个城市的社区服务中心。" * 8


def call_main(module, args):
    """Run a script's main() in-process and capture its console output."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(list(args))
    return code, out.getvalue(), err.getvalue()


class CorpusCase(TempCase):
    """A small corpus exercising every audit branch."""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "corpus")
        os.makedirs(self.root)
        self.out = os.path.join(self.tmp, "out")
        self._write("good.txt", LONG)
        self._write("copy.txt", LONG)
        self._write("empty.txt", "")
        self._write("._side.pdf", "junk")
        self._write("bad.pdf", "not a pdf")
        self._write("unknown.xyz", "???")
        self._write("_Duplicates/dup.txt", LONG)
        self._write("sub/deep.txt", LONG + "补充说明。")

    def _write(self, rel, text, binary=False):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if binary:
            with open(path, "wb") as fh:
                fh.write(text)
        else:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        return path

    def audit(self, *extra, out=None):
        out = out or self.out
        return run("audit_corpus.py", "--root", self.root, "--out-dir", out, *extra)

    def rows(self, out=None):
        return read_csv(os.path.join(out or self.out, "corpus_files.csv"))

    def row_by_name(self, name, out=None):
        for row in self.rows(out):
            if row["name"] == name:
                return row
        self.fail(f"no row for {name}")

    def summary(self, out=None):
        with open(os.path.join(out or self.out, "corpus_summary.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def report(self, out=None):
        with open(os.path.join(out or self.out, "corpus_report.md"), encoding="utf-8") as fh:
            return fh.read()


class TestAuditSemantics(CorpusCase):
    def test_aud01_unreadable_file_does_not_kill_scan(self):
        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            if os.path.basename(str(path)) == "good.txt":
                raise PermissionError("simulated access denied")
            return real_stat(path, *args, **kwargs)

        with mock.patch.object(audit_corpus.os, "stat", side_effect=fake_stat):
            code, out, _ = call_main(audit_corpus,
                                     ["--root", self.root, "--out-dir", self.out])
        self.assertEqual(code, 0)
        self.assertIn("unreadable: 1", out)
        bad = self.row_by_name("good.txt")
        self.assertEqual(bad["status"], "unreadable")
        self.assertIn("PermissionError", bad["error"])
        self.assertEqual(self.summary()["unreadable_files"], 1)
        # The rest of the scan survived: copy.txt is still valid.
        self.assertEqual(self.row_by_name("copy.txt")["status"], "valid")
        # --fail-on-issues treats unreadable as blocking too.
        with mock.patch.object(audit_corpus.os, "stat", side_effect=fake_stat):
            code, _, _ = call_main(audit_corpus,
                                   ["--root", self.root, "--out-dir", self.out,
                                    "--fail-on-issues"])
        self.assertEqual(code, 2)

    def test_aud01_classify_exception_is_recorded(self):
        real_classify = audit_corpus.classify

        def fake_classify(path, rec, ext, min_chars):
            if os.path.basename(path) == "deep.txt":
                raise RuntimeError("simulated classify crash")
            return real_classify(path, rec, ext, min_chars)

        with mock.patch.object(audit_corpus, "classify", side_effect=fake_classify):
            code, _, _ = call_main(audit_corpus,
                                   ["--root", self.root, "--out-dir", self.out])
        self.assertEqual(code, 0)
        deep = self.row_by_name("deep.txt")
        self.assertEqual(deep["status"], "unreadable")
        self.assertIn("classify crash", deep["error"])

    def test_aud02_windows_hidden_attribute(self):
        if os.name != "nt":
            self.skipTest("Windows-only attribute")
        import ctypes
        path = self._write("secret.txt", LONG)
        ok = ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)
        self.assertTrue(ok)
        self.addCleanup(ctypes.windll.kernel32.SetFileAttributesW, str(path), 0x80)
        hidden_dir = os.path.join(self.root, "secret_dir")
        os.makedirs(hidden_dir)
        nested = os.path.join(hidden_dir, "inside.txt")
        with open(nested, "w", encoding="utf-8") as fh:
            fh.write(LONG)
        self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(str(hidden_dir), 0x2))
        self.addCleanup(ctypes.windll.kernel32.SetFileAttributesW, str(hidden_dir), 0x80)
        self.audit()
        self.assertEqual(self.row_by_name("secret.txt")["status"], "hidden")
        self.assertEqual(self.row_by_name("inside.txt")["status"], "hidden")

    def test_aud03_page_numbers_do_not_count_as_text(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        doc = fitz.open()
        for i in range(30):
            page = doc.new_page()
            page.insert_text((72, 72), f"{i + 1}/30")
        pdf = os.path.join(self.root, "scan.pdf")
        doc.save(pdf)
        doc.close()
        self.audit()
        row = self.row_by_name("scan.pdf")
        self.assertGreaterEqual(int(row["chars"]), 100)
        self.assertLess(int(row["chars_effective"]), 100)
        self.assertEqual(row["status"], "textless")

    def test_aud04_effective_chars_ignores_layout_newlines(self):
        self.assertEqual(text_extract.effective_chars("审\n理\n法\n院："), 5)
        self.assertEqual(text_extract.effective_chars("a\n3/26\n b"), 2)
        rec = text_extract.inspect_file(self._write("lines.txt", "审\n理\n法\n院：\n1/1\n"))
        self.assertEqual(rec["chars_effective"], 5)

    def test_aud05_content_dedupe_finds_reformatted_copy(self):
        os.makedirs(os.path.join(self.root, "reformat"))
        self._write("reformat/same.txt", LONG + "独立文本。" + "\n\n")
        self._write("same.txt", LONG + "独立文本。")
        self.audit()
        before = self.summary()
        self.assertEqual(before["content_duplicate_groups"], 0)  # opt-in only
        self.audit("--content-dedupe")
        after = self.summary()
        self.assertGreaterEqual(after["content_duplicate_groups"], 1)
        content_rows = [r for r in self.rows() if r["dup_content_group"]]
        self.assertTrue(any(r["rel_path"] == "same.txt" for r in content_rows))
        self.assertIn("keeper", {r["dup_role_content"] for r in content_rows})

    def test_aud06_sampling_frame(self):
        self.audit("--min-chars", "42")
        frame = self.summary()["sampling_frame"]
        self.assertEqual(frame["root"], self.root)
        self.assertEqual(frame["ext"], [])
        self.assertEqual(frame["min_chars"], 42)
        self.assertFalse(frame["content_dedupe"])
        self.assertEqual(frame["generated_by"], "audit_corpus.py")
        report = self.report()
        self.assertIn("## 抽样框", report)
        self.assertIn("最小有效字符数：42", report)

    def test_aud07_rel_path_and_relpath_columns(self):
        self.audit()
        with open(os.path.join(self.out, "corpus_files.csv"), "rb") as fh:
            self.assertTrue(fh.read(3) == b"\xef\xbb\xbf")
        with open(os.path.join(self.out, "corpus_files.csv"),
                  encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh))
        self.assertEqual(header[:2], ["rel_path", "relpath"])
        row = self.row_by_name("copy.txt")
        self.assertEqual(row["rel_path"], row["relpath"])
        dup_rows = read_csv(os.path.join(self.out, "corpus_duplicates.csv"))
        self.assertTrue(dup_rows)
        for item in dup_rows:
            self.assertEqual(item["rel_path"], item["relpath"])

    def test_aud16_legacy_audit_csv_is_written(self):
        """corpus_audit.csv must keep existing (same table, same bytes).

        The per-file table is now corpus_files.csv, but every downstream command,
        the README quick start and ``make_coding_sheet.py --audit`` used to point
        at corpus_audit.csv; dropping it silently broke those callers.
        """
        self.audit()
        new = os.path.join(self.out, "corpus_files.csv")
        old = os.path.join(self.out, "corpus_audit.csv")
        self.assertTrue(os.path.isfile(old), "legacy corpus_audit.csv was not written")
        with open(new, "rb") as fh:
            new_bytes = fh.read()
        with open(old, "rb") as fh:
            old_bytes = fh.read()
        self.assertEqual(new_bytes, old_bytes)
        self.assertIn("corpus_audit.csv", self.report())

    def test_aud08_root_level_top_label(self):
        self.audit()
        self.assertEqual(self.row_by_name("good.txt")["top"], "(root)")
        self.assertIn("(root)", self.summary()["by_top"])
        self.assertIn("(root)", self.report())

    def test_aud09_skip_dir_is_case_insensitive(self):
        self.audit()
        self.assertEqual(self.row_by_name("dup.txt")["status"], "quarantined")

    def test_aud10_no_hash_is_reported_honestly(self):
        self.audit("--no-hash")
        summary = self.summary()
        self.assertTrue(summary["hash_disabled"])
        self.assertEqual(summary["duplicate_groups"], 0)
        self.assertIn("未检测（--no-hash）", self.report())
        self.assertEqual(read_csv(os.path.join(self.out, "corpus_duplicates.csv")), [])

    def test_aud11_out_dir_inside_root_is_not_rescanned(self):
        inside = os.path.join(self.root, "audit_out")
        self.audit(out=inside)
        first = self.summary(out=inside)["total_files"]
        self.audit(out=inside)
        second = self.summary(out=inside)["total_files"]
        self.assertEqual(first, second)
        self.assertFalse([r for r in self.rows(out=inside)
                          if r["rel_path"].startswith("audit_out/")])
        self.assertTrue(self.summary(out=inside)["out_dir_inside_root"])
        self.assertIn("已跳过", self.report(out=inside))

    def test_aud11b_out_dir_equal_root_is_not_self_audited(self):
        first = self.audit(out=self.root)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_total = self.summary(out=self.root)["total_files"]
        self.assertTrue(self.summary(out=self.root)["out_dir_same_as_root"])
        second = self.audit(out=self.root)
        self.assertEqual(second.returncode, 0, second.stderr)
        summary = self.summary(out=self.root)
        self.assertEqual(summary["total_files"], first_total)
        self.assertGreaterEqual(summary["out_products_skipped"], 4)
        self.assertIn("已按产物文件名跳过", self.report(out=self.root))

    def test_aud12_md5_coverage_is_reported(self):
        self.audit()
        coverage = self.summary()["md5_coverage"]
        self.assertGreater(coverage["hashed"], 0)
        self.assertLessEqual(coverage["hashed"], coverage["hashable"])
        self.assertIn("MD5 覆盖率", self.report())

    def test_aud13_keeper_rules_and_reason(self):
        self._write("year/报告2020.txt", LONG + "甲")
        self._write("year/报告.txt", LONG + "甲")
        self._write("copy/a.txt", LONG + "乙")
        self._write("copy/a副本.txt", LONG + "乙")
        self._write("tie/xa.txt", LONG + "丙")
        self._write("tie/xb.txt", LONG + "丙")
        self.audit()
        rows = self.rows()
        dup = {r["rel_path"]: r for r in read_csv(
            os.path.join(self.out, "corpus_duplicates.csv"))}
        self.assertEqual(dup["year/报告2020.txt"]["role"], "keeper")
        self.assertEqual(dup["year/报告2020.txt"]["keeper_reason"], "year_hint")
        self.assertEqual(dup["copy/a.txt"]["role"], "keeper")
        self.assertEqual(dup["copy/a.txt"]["keeper_reason"], "no_copy_marker")
        tie = {k: v for k, v in dup.items() if k.startswith("tie/")}
        keeper = [r for r in tie.values() if r["role"] == "keeper"]
        self.assertEqual(len(keeper), 1)
        self.assertEqual(keeper[0]["keeper_reason"], "tie_first")
        self.assertGreaterEqual(self.summary()["keeper_ties"], 1)

    def test_aud14_year_hint_boundaries(self):
        self.assertEqual(audit_corpus.year_hint("1920px.png"), "")
        self.assertEqual(audit_corpus.year_hint("file-2000-1.pdf"), "")
        self.assertEqual(audit_corpus.year_hint("报告[2021].pdf"), "2021")
        self.assertEqual(audit_corpus.year_hint("报告（2019）.pdf"), "2019")

    def test_aud16_max_files_truncation_recorded(self):
        self.audit("--max-files", "2")
        summary = self.summary()
        self.assertEqual(summary["total_files"], 2)
        self.assertEqual(summary["max_files"], 2)
        self.assertTrue(summary["truncated"])
        self.assertIn("截断", self.report())

    def test_aud17_pages_missing_counter(self):
        self.audit()
        summary = self.summary()
        self.assertIn("pages_missing", summary)
        self.assertIsInstance(summary["pages_total"], int)

    def test_empty_corpus_is_not_success(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        proc = run("audit_corpus.py", "--root", empty,
                   "--out-dir", os.path.join(self.tmp, "empty_out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no files found", proc.stderr)

    def test_aud18_error_kinds_distinguish_unsupported_and_corrupt(self):
        self.audit()
        self.assertEqual(self.row_by_name("bad.pdf")["status"], "corrupt")
        self.assertEqual(self.row_by_name("bad.pdf")["error_kind"], "broken")
        unknown = self.row_by_name("unknown.xyz")
        self.assertEqual(unknown["status"], "unsupported")
        self.assertEqual(unknown["error_kind"], "unsupported")


class TestDedupe(TempCase):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "corpus")
        os.makedirs(self.root)
        self.audit_dir = os.path.join(self.tmp, "audit")
        self.keep = self._write("keep.txt", LONG)
        self.dup = self._write("keep副本.txt", LONG)
        proc = run("audit_corpus.py", "--root", self.root, "--out-dir", self.audit_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.audit_csv = os.path.join(self.audit_dir, "corpus_files.csv")

    def _write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def dedupe(self, *extra):
        return run("dedupe_corpus.py", "--audit", self.audit_csv, "--root", self.root,
                   "--out-dir", self.audit_dir, *extra)

    def log(self):
        return read_csv(os.path.join(self.audit_dir, "move_log.csv"))

    def plan(self):
        return read_csv(os.path.join(self.audit_dir, "dedupe_plan.csv"))

    def test_ded05_plan_marks_existence_and_md5(self):
        proc = self.dedupe()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = self.plan()
        self.assertIn("exists", plan[0])
        self.assertIn("md5", plan[0])
        self.assertTrue(all(row["exists"] == "yes" for row in plan))
        self.assertGreaterEqual(len(glob.glob(os.path.join(self.audit_dir, "dedupe_plan_*.csv"))), 1)

    def test_ded04_apply_logs_and_undo_restores(self):
        proc = self.dedupe("--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        moved_to = os.path.join(self.root, "_duplicates", "keep副本.txt")
        self.assertTrue(os.path.isfile(moved_to))
        self.assertFalse(os.path.exists(self.dup))
        log = self.log()
        self.assertEqual(set(log[0]), {"group", "src", "dest", "action", "status", "reason"})
        self.assertEqual(log[0]["status"], "moved")
        undo = run("dedupe_corpus.py", "--undo",
                   os.path.join(self.audit_dir, "move_log.csv"))
        self.assertEqual(undo.returncode, 0, undo.stderr)
        self.assertTrue(os.path.isfile(self.dup))
        self.assertFalse(os.path.exists(moved_to))

    def test_ded04_undo_conflict_refuses_overwrite(self):
        self.assertEqual(self.dedupe("--apply").returncode, 0)
        moved_to = os.path.join(self.root, "_duplicates", "keep副本.txt")
        with open(self.dup, "w", encoding="utf-8") as fh:
            fh.write("new occupant")
        undo = run("dedupe_corpus.py", "--undo",
                   os.path.join(self.audit_dir, "move_log.csv"))
        self.assertEqual(undo.returncode, 2)
        self.assertIn("conflict=1", undo.stdout)
        self.assertTrue(os.path.isfile(moved_to))
        with open(self.dup, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "new occupant")

    def test_ded04_copy_undo_removes_verified_copy(self):
        proc = self.dedupe("--copy", "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        copied_to = os.path.join(self.root, "_duplicates", "keep副本.txt")
        self.assertTrue(os.path.isfile(copied_to))
        undo = run("dedupe_corpus.py", "--undo",
                   os.path.join(self.audit_dir, "move_log.csv"))
        self.assertEqual(undo.returncode, 0, undo.stderr)
        self.assertIn("removed=1", undo.stdout)
        self.assertFalse(os.path.exists(copied_to))
        self.assertTrue(os.path.isfile(self.dup))
        with open(self.dup, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), LONG)

    def test_ded04_undo_nothing_to_undo_is_an_error(self):
        log = os.path.join(self.audit_dir, "move_log.csv")
        write_csv(log, ["group", "src", "dest", "action", "status", "reason"],
                  [{"group": "G0001", "src": self.dup, "dest": self.dup,
                    "action": "keep", "status": "copied", "reason": "manual"}])
        proc = run("dedupe_corpus.py", "--undo", log)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("nothing to undo", proc.stderr)

    def test_ded01_missing_keeper_skips_whole_group(self):
        os.remove(self.keep)
        proc = self.dedupe("--apply")
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(os.path.isfile(self.dup))          # nothing moved
        statuses = {row["status"] for row in self.log()}
        self.assertEqual(statuses, {"skipped"})
        self.assertTrue(any(row["exists"] == "no" for row in self.plan()))

    def test_ded02_failures_return_nonzero(self):
        os.remove(self.keep)
        proc = self.dedupe("--apply")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("skipped", proc.stdout)

    def test_ded03_changed_duplicate_is_not_moved(self):
        with open(self.dup, "w", encoding="utf-8") as fh:
            fh.write("内容已经变了，不再是同一个文件。")
        proc = self.dedupe("--apply")
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(os.path.isfile(self.dup))
        self.assertIn("skipped", {row["status"] for row in self.log()})
        plan = [row for row in self.plan() if row["role"] == "duplicate"][0]
        self.assertEqual(plan["md5_ok"], "no")

    def test_ded07_missing_keeper_row_warns(self):
        csv_path = os.path.join(self.tmp, "audit", "manual.csv")
        write_csv(csv_path, ["rel_path", "relpath", "name", "dup_group", "dup_role"],
                  [["a.txt", "a.txt", "a.txt", "G1", "duplicate"]])
        proc = run("dedupe_corpus.py", "--audit", csv_path, "--root", self.root,
                   "--out-dir", self.audit_dir)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("keepers", proc.stderr)

    def test_ded08_no_duplicate_groups_is_a_clean_no_op(self):
        """A corpus without duplicates must not look like a broken step."""
        csv_path = os.path.join(self.tmp, "audit", "nodup.csv")
        write_csv(csv_path, ["rel_path", "relpath", "dup_group", "dup_role"],
                  [["keep.txt", "keep.txt", "", ""]])
        proc = run("dedupe_corpus.py", "--audit", csv_path, "--root", self.root,
                   "--out-dir", self.audit_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("nothing to do", proc.stdout)
        plan = os.path.join(self.audit_dir, "dedupe_plan.csv")
        self.assertTrue(os.path.exists(plan), "an empty plan must still be written")
        self.assertEqual(read_csv(plan), [], "header only, no planned moves")
        # --apply on an empty plan is also a success, not a failure
        proc2 = run("dedupe_corpus.py", "--audit", csv_path, "--root", self.root,
                    "--out-dir", self.audit_dir, "--apply")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)


class TestTextExtract(TempCase):
    def make(self, rel, text, binary=False):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if binary:
            with open(path, "wb") as fh:
                fh.write(text)
        else:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        return path

    def test_ext01_cli_writes_documented_columns(self):
        self.make("a.txt", LONG)
        self.make("b.html", "<p>hello</p>")
        make_text_pdf(os.path.join(self.tmp, "c.pdf"))
        make_png(os.path.join(self.tmp, "d.png"))
        out = os.path.join(self.tmp, "report", "rows.csv")
        proc = run("text_extract.py", "--root", self.tmp, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = read_csv(out)
        self.assertEqual(len(rows), 4)
        for column in ("rel_path", "ext", "kind", "pages", "chars",
                       "chars_effective", "encoding", "error"):
            self.assertIn(column, rows[0])
        kinds = {row["rel_path"]: row["kind"] for row in rows}
        self.assertEqual(kinds["a.txt"], "text")
        self.assertEqual(kinds["d.png"], "image")

    def test_ext01_cli_jsonl_and_min_chars(self):
        self.make("a.txt", LONG)
        out = os.path.join(self.tmp, "rows.jsonl")
        proc = run("text_extract.py", "--root", self.tmp, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, encoding="utf-8") as fh:
            payload = json.loads(fh.readline())
        self.assertEqual(payload["rel_path"], "a.txt")
        proc = run("text_extract.py", "--root", self.tmp, "--min-chars", "100000")
        self.assertEqual(proc.returncode, 2)

    def test_ext01_cli_requires_input(self):
        self.assertEqual(run("text_extract.py").returncode, 2)
        self.assertEqual(run("text_extract.py", "--file",
                             os.path.join(self.tmp, "missing.txt")).returncode, 2)

    def test_ext01_cli_repeated_files_and_ext_filter(self):
        a = self.make("a.txt", LONG)
        b = self.make("b.txt", LONG + "乙")
        make_png(os.path.join(self.tmp, "c.png"))
        out = os.path.join(self.tmp, "picked.csv")
        proc = run("text_extract.py", "--root", self.tmp, "--file", a, "--file", b,
                   "--ext", "txt", "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = read_csv(out)
        self.assertEqual([row["rel_path"] for row in rows], ["a.txt", "b.txt"])

    def test_ext02_latin1_fallback_is_flagged(self):
        path = self.make("binary.txt", b"\xff\xff\xff", binary=True)
        rec = text_extract.inspect_file(path)
        self.assertEqual(rec["encoding"], "latin-1(fallback)")
        self.assertIn("mojibake", rec["error"])
        self.assertEqual(rec["error_kind"], "mojibake")

    def test_ext03_pdf_text_extraction_still_works(self):
        path = os.path.join(self.tmp, "plain.pdf")
        make_text_pdf(path, "hello page")
        self.assertEqual(text_extract.extract_text(path).strip(), "hello page")

    def test_ext03_partial_pdf_keeps_readable_pages(self):
        path = os.path.join(self.tmp, "partial.pdf")
        make_text_pdf(path, "page one")
        with mock.patch.object(text_extract, "_pdf_pages_text",
                               return_value=(["page one", ""], 1)):
            self.assertEqual(text_extract.extract_text(path).strip(), "page one")
        with mock.patch.object(text_extract, "_pdf_pages_text",
                               return_value=([""], 1)):
            with self.assertRaises(ValueError):
                text_extract.extract_text(path)

    def test_ext04_permission_encrypted_pdf_with_text_is_readable(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "readable text " * 20)
        path = os.path.join(self.tmp, "crypted.pdf")
        doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner",
                 user_pw="", permissions=fitz.PDF_PERM_PRINT)
        doc.close()
        rec = text_extract.inspect_file(path)
        self.assertTrue(rec["encrypted"])
        self.assertGreater(rec["chars_effective"], 0)
        self.assertEqual(rec["error"], "")

    def test_ext05_ole_container_is_encrypted_office(self):
        path = self.make("enc.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
                         binary=True)
        rec = text_extract.inspect_file(path)
        self.assertEqual(rec["encrypted"], 1)
        self.assertEqual(rec["error_kind"], "encrypted_office")

    def test_ext06_unc_long_path(self):
        if os.name != "nt":
            self.skipTest("Windows-only path handling")
        unc = "\\\\server\\share\\" + ("深度目录" * 60)
        self.assertTrue(text_extract.win_path(unc).startswith("\\\\?\\UNC\\"))

    def test_ext07_large_text_is_skipped_without_reading(self):
        path = os.path.join(self.tmp, "huge.txt")
        with open(path, "wb") as fh:
            fh.seek(51 * 1024 * 1024)
            fh.write(b"x")
        rec = text_extract.inspect_file(path)
        self.assertEqual(rec["error_kind"], "too_large")

    def test_ext08_html_text_keeps_angle_bracket_content(self):
        path = self.make("page.html", "<html><body><p>a &lt;b&gt; c</p></body></html>")
        self.assertIn("<b>", text_extract.extract_text(path))

    def test_ext10_chars_and_chars_effective(self):
        path = self.make("mixed.txt", "审\n理\n法\n院：\n1/1\n")
        rec = text_extract.inspect_file(path)
        self.assertEqual(rec["chars"], 13)
        self.assertEqual(rec["chars_effective"], 5)


if __name__ == "__main__":
    unittest.main()
