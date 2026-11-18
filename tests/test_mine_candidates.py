# -*- coding: utf-8 -*-
"""Tests for scripts/mine_candidates.py: candidates with evidence
anchors, no content judgment, deterministic under a declared seed."""
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(
    HERE, "..", "empirical-research-pipeline", "scripts"))
SCRIPT = os.path.join(SCRIPTS, "mine_candidates.py")


def run(*argv):
    return subprocess.run([sys.executable, SCRIPT, *argv],
                          capture_output=True, text=True,
                          encoding="utf-8", timeout=300)


def run_env(extra_env, *argv):
    env = dict(os.environ)
    for key, value in extra_env.items():
        existing = env.get(key)
        env[key] = value if not existing else value + os.pathsep + existing
    return subprocess.run([sys.executable, SCRIPT, *argv],
                          capture_output=True, text=True,
                          encoding="utf-8", timeout=300, env=env)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mine-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)

    def write(self, rel, text):
        path = self.p(*rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def corpus(self, name, entries, root=None):
        path = self.p(name)
        with open(path, "w", encoding="utf-8") as handle:
            for entry in entries:
                if isinstance(entry, tuple):
                    handle.write(f"{entry[0]}\t{entry[1]}\n")
                else:
                    handle.write(f"{entry}\n")
        return path

    def read_csv(self, name, out="out"):
        path = self.p(out, name)
        with open(path, encoding="utf-8-sig") as handle:
            return handle.read()

    def receipt(self, out="out"):
        with open(self.p(out, "mine_receipt.json"), encoding="utf-8") as fh:
            return json.load(fh)


TEXTS = {
    "a.txt": "服务质量满意度显著提升，客户投诉率并未下降。\n服务态度良好，响应及时。\n",
    "b.txt": "服务质量持续改善。满意度调查结果上升。\n投诉处理流程繁琐，客户不满。\n",
    "c.txt": "产品质量稳定，故障率低。\n服务响应速度快，客户满意。\n",
    "d.txt": "产品交付延迟，客户投诉增加。\n满意度下降明显。\n",
}


def build_project(case: TempCase, texts=TEXTS):
    docs = case.p("docs")
    os.makedirs(docs, exist_ok=True)
    entries = []
    for name, text in texts.items():
        case.write(f"docs/{name}", text)
        entries.append(name)
    listing = case.corpus("corpus_files.txt", entries)
    return docs, listing


class TestGuardrails(TempCase):
    def test_missing_corpus_refused(self):
        proc = run("--root", self.p("docs"), "--corpus", self.p("no.txt"),
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("corpus listing not found", proc.stderr)

    def test_out_pointing_at_file_refused(self):
        docs, listing = build_project(self)
        blocker = self.p("blocker")
        open(blocker, "w").close()
        proc = run("--root", docs, "--corpus", listing, "--out", blocker)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a directory", proc.stderr)

    def test_seed_required_for_topics(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--topics", "3")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--seed is required", proc.stderr)

    def test_seed_required_for_scan_k(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--scan-k", "2,3")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--seed is required", proc.stderr)

    def test_topics_below_two_refused(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--topics", "1",
                   "--seed", "7")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("at least 2", proc.stderr)

    def test_hash_mismatch_skips_document(self):
        docs = self.p("docs")
        os.makedirs(docs)
        self.write("docs/a.txt", TEXTS["a.txt"])
        listing = self.corpus("corpus_files.txt", [("a.txt", "0" * 64)])
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("empty corpus", proc.stderr)

    def test_missing_document_skips_but_others_mine(self):
        docs, listing = build_project(self)
        listing = self.corpus("corpus_files.txt",
                              ["a.txt", "missing.txt", "b.txt"])
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["inputs"]["n_documents"], 2)
        self.assertEqual(receipt["inputs"]["skipped_missing"],
                         ["missing.txt"])

    def test_bad_scan_k_refused(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--scan-k", "x,3",
                   "--seed", "5")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("comma-separated integers", proc.stderr)
        # a bad spec is refused before anything is built: no orphan
        # tables, no half-written receipt
        self.assertFalse(os.path.exists(self.p("out",
                                               "keyword_candidates.csv")))
        self.assertFalse(os.path.exists(self.p("out", "mine_receipt.json")))

    def test_topics_k_above_document_count_refused(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--topics", "6",
                   "--seed", "5")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must stay below the document count", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertFalse(os.path.exists(self.p("out",
                                               "keyword_candidates.csv")))

    def test_single_document_topics_refused(self):
        texts = {"only.txt": "服务质量满意度提升，客户投诉下降。\n"}
        docs, listing = build_project(self, texts)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--topics", "2",
                   "--seed", "5", "--min-df", "1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must stay below the document count", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_topics_k_above_vocabulary_refused_cleanly(self):
        # four documents whose vocabulary is only two terms: K=3 fits
        # the doc count but not nndsvda's n_components constraint - the
        # refusal must be a clean exit 2, not a sklearn traceback
        texts = {name: "甲 乙 甲 乙\n" for name in
                 ("w.txt", "x.txt", "y.txt", "z.txt")}
        docs, listing = build_project(self, texts)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--topics", "3",
                   "--seed", "5", "--min-df", "1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("exceeds what this corpus supports", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertFalse(os.path.exists(self.p("out",
                                               "keyword_candidates.csv")))

    def test_stopwords_bad_path_refused(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--stopwords",
                   self.p("no-such-stopwords.txt"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read stopwords file", proc.stderr)

    def test_corpus_csv_without_rel_path_column_refused(self):
        docs, listing = build_project(self)
        bad = self.write("bad.csv", "path,md5\na.txt,0\n")
        proc = run("--root", docs, "--corpus", bad,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must have a rel_path column", proc.stderr)

    def test_undecodable_listing_refused(self):
        docs, listing = build_project(self)
        bad = self.p("bad-listing.bin")
        with open(bad, "wb") as handle:
            handle.write(b"\xff\xfe\x00\xd8\xff\xff\x01\x02")
        proc = run("--root", docs, "--corpus", bad,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read corpus listing", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_bad_min_values_refused(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--top", "0")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("at least 1", proc.stderr)

    def test_refused_run_leaves_no_output_directory(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--top", "0")
        self.assertEqual(proc.returncode, 2)
        # nothing is created on disk before every validation passes -
        # not even the output directory itself
        self.assertFalse(os.path.exists(self.p("out")))


class TestCandidates(TempCase):
    def test_default_run_produces_tables_and_receipt(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(self.p("out",
                                              "keyword_candidates.csv")))
        self.assertTrue(os.path.isfile(self.p("out",
                                              "pair_candidates.csv")))
        self.assertTrue(os.path.isfile(self.p("out", "mine_receipt.json")))
        self.assertFalse(os.path.isfile(self.p("out",
                                              "topic_assignments.csv")))
        keywords = self.read_csv("keyword_candidates.csv")
        self.assertIn("term,doc_freq,n_docs,tfidf_mean", keywords)
        self.assertIn("满意度", keywords)
        # evidence anchors on every row
        for line in keywords.strip().splitlines()[1:]:
            fields = line.split(",")
            self.assertEqual(len(fields), 8)
            self.assertTrue(fields[4].endswith(".txt"))
            self.assertTrue(int(fields[5]) >= 1)

    def test_topics_and_scan_k_run(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--topics", "2",
                   "--scan-k", "2,3,4", "--seed", "20261118",
                   "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        topics = self.read_csv("topic_assignments.csv")
        self.assertIn("rel_path,topic,weight", topics)
        profile = self.read_csv("k_profile.csv")
        self.assertIn("k,silhouette,note", profile)
        receipt = self.receipt()
        self.assertEqual(len(receipt["topics"]), 2)
        self.assertEqual(receipt["params"]["seed"], 20261118)

    def test_same_seed_same_bytes(self):
        docs, listing = build_project(self)
        for out in ("out1", "out2"):
            proc = run("--root", docs, "--corpus", listing,
                       "--out", self.p(out), "--topics", "2",
                       "--scan-k", "2,3", "--seed", "20261118",
                       "--min-df", "1")
            self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in ("keyword_candidates.csv", "pair_candidates.csv",
                     "topic_assignments.csv", "k_profile.csv"):
            with open(self.p("out1", name), "rb") as left, \
                    open(self.p("out2", name), "rb") as right:
                self.assertEqual(left.read(), right.read())
        # the receipt differs only by generated_at
        r1 = self.receipt("out1")
        r2 = self.receipt("out2")
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_stopwords_shape_the_candidates(self):
        docs, listing = build_project(self)
        stop = self.write("stop.txt", "客户\n投诉\n")
        base = run("--root", docs, "--corpus", listing,
                   "--out", self.p("base"), "--min-df", "1")
        self.assertEqual(base.returncode, 0, base.stderr)
        filtered = run("--root", docs, "--corpus", listing,
                       "--out", self.p("filt"), "--stopwords", stop,
                       "--min-df", "1")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        keywords = self.read_csv("keyword_candidates.csv", out="filt")
        self.assertNotIn("客户", [line.split(",")[0] for line in
                                  keywords.strip().splitlines()[1:]])
        receipt = self.receipt("filt")
        self.assertTrue(receipt["inputs"]["stopwords_sha256"])

    def test_pairs_carry_sentence_anchors(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1",
                   "--min-count", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        pairs = self.read_csv("pair_candidates.csv")
        header = ("term_a,term_b,cooccurrence,pmi,top_document,top_line,"
                  "second_document,second_line")
        self.assertIn(header, pairs)

    def test_receipt_records_tokenizer_and_inputs(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertIn(receipt["inputs"]["tokenizer"], ("jieba", "fallback"))
        self.assertEqual(receipt["inputs"]["n_documents"], 4)
        self.assertTrue(receipt["inputs"]["corpus_sha256"])
        self.assertIn("candidates, not findings", receipt["note"])

    def test_english_corpus_mines_words(self):
        texts = {
            "one.txt": "patient satisfaction improved after the "
                       "intervention. complaints decreased.\n",
            "two.txt": "patient satisfaction stayed high. staff response "
                       "was quick.\n",
        }
        docs, listing = build_project(self, texts)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        keywords = self.read_csv("keyword_candidates.csv")
        terms = [line.split(",")[0] for line in
                 keywords.strip().splitlines()[1:]]
        self.assertIn("patient", terms)
        self.assertIn("satisfaction", terms)
        # English function words like 'the' are content judgments for the
        # researcher's stopword file, NOT the engine - documented in 09.
        # The engine floor only drops single ASCII letters.
        self.assertNotIn("a", terms)

    def test_pure_punctuation_corpus_is_refused_cleanly(self):
        texts = {"x.txt": "。。。！！！123 456\n"}
        docs, listing = build_project(self, texts)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        # no terms survive the engine floor: a refusable input, not a
        # crash - the message names the actual cause
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no terms survive", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_empty_documents_do_not_crash_and_are_counted(self):
        # empty text documents stay in the corpus (they count in
        # n_documents and in df denominators, they contribute no
        # terms); they are not an error
        texts = {"a.txt": TEXTS["a.txt"], "empty.txt": "\n \n"}
        docs, listing = build_project(self, texts)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["inputs"]["n_documents"], 2)

    def test_gb18030_documents_are_read(self):
        docs = self.p("docs")
        os.makedirs(docs)
        payload = "服务质量满意度提升。\n投诉率下降。\n"
        with open(os.path.join(docs, "g.txt"), "w",
                  encoding="gb18030", newline="") as handle:
            handle.write(payload)
        listing = self.corpus("corpus_files.txt", ["g.txt"])
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        keywords = self.read_csv("keyword_candidates.csv")
        self.assertIn("满意度", keywords)


class TestTokenizers(TempCase):
    """The tokenizer is a documented degradation, both paths tested."""

    def test_fallback_path_is_deterministic(self):
        sys.path.insert(0, SCRIPTS)
        try:
            import mine_candidates as mc
            text = "服务质量满意度提升 improved satisfaction"
            tokens = mc._fallback_tokens(text)
            self.assertEqual(tokens, mc._fallback_tokens(text))
            self.assertIn("satisfaction", tokens)
            self.assertIn("满", tokens)          # single CJK char
            self.assertIn("服务", tokens)        # char bigram
        finally:
            sys.path.pop(0)

    def test_tokenize_uses_engine_floor(self):
        sys.path.insert(0, SCRIPTS)
        try:
            import mine_candidates as mc
            text = "the 。。。 cat 坐在 mat"
            tokens = mc.tokenize(text)
            self.assertNotIn("。。。", tokens)
            joined = " ".join(tokens)
            self.assertIn("cat", joined)
            # 'the' is a 3-letter word: the engine floor does not drop it
            # (content stopwords are the researcher's declaration)
            self.assertIn("the", tokens)
        finally:
            sys.path.pop(0)

    def test_fullwidth_letters_survive_the_engine_floor(self):
        # fullwidth latin letters and halfwidth katakana are CONTENT
        # letters: dropping them would be a content judgment. Fullwidth
        # digits and punctuation are still contentless machinery.
        sys.path.insert(0, SCRIPTS)
        try:
            import mine_candidates as mc
            punct = mc._punct_re().match
            self.assertIsNone(punct("ＡＢＣ"))    # fullwidth letters
            self.assertIsNone(punct("ｱｲｳ"))      # halfwidth katakana
            self.assertIsNone(punct("サービス"))  # katakana word
            self.assertIsNotNone(punct("１２３"))  # fullwidth digits
            self.assertIsNotNone(punct("！？"))    # fullwidth punct
            self.assertIsNotNone(punct("。，"))    # CJK punct
        finally:
            sys.path.pop(0)


class TestAnchorTruth(TempCase):
    """The tool's core promise: every anchor names a line that actually
    holds the term. These tests exist because the first implementation
    zipped CSR column indices as if they were row indices - every
    anchor silently pointed at the first document."""

    TEXTS = {
        "one.txt": "服务质量满意度显著提升。\n服务态度良好。\n",
        "two.txt": "产品质量稳定故障率低。\n交付延迟明显。\n",
        "three.txt": "客户投诉率并未下降。\n响应速度快。\n客户满意。\n",
    }

    def _lines(self, out="out"):
        table = self.read_csv("keyword_candidates.csv", out=out)
        return list(csv.DictReader(table.splitlines()))

    def test_keyword_anchors_hold_the_term(self):
        docs, listing = build_project(self, self.TEXTS)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        top_docs = set()
        for row in self._lines():
            top_docs.add(row["top_document"])
            lines = self.TEXTS[row["top_document"]].splitlines()
            self.assertIn(row["term"],
                          lines[int(row["top_line"]) - 1],
                          f"term {row['term']!r} not on "
                          f"{row['top_document']}:{row['top_line']}")
            if row["second_document"]:
                # evidence docs are distinct documents (never a
                # duplicate of the top doc), and the second line holds
                # the term too
                self.assertNotEqual(row["second_document"],
                                    row["top_document"])
                lines2 = self.TEXTS[row["second_document"]].splitlines()
                self.assertIn(row["term"],
                              lines2[int(row["second_line"]) - 1])
        # the anchor must be able to reach documents beyond the first
        # listed one - that was the silent failure mode
        self.assertIn("three.txt", top_docs)
        self.assertIn("two.txt", top_docs)

    def test_term_unique_to_one_document_anchors_there(self):
        docs, listing = build_project(self, self.TEXTS)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = {row["term"]: row for row in self._lines()}
        self.assertIn("客户", rows)
        # '客户' appears only in three.txt: its strongest-evidence doc
        # must be three.txt (with jieba or the fallback tokenizer)
        self.assertEqual(rows["客户"]["top_document"], "three.txt")

    def test_pair_anchors_hold_both_terms(self):
        docs, listing = build_project(self, self.TEXTS)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1",
                   "--min-count", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        pairs = list(csv.DictReader(
            self.read_csv("pair_candidates.csv").splitlines()))
        self.assertTrue(pairs)
        for row in pairs:
            lines = self.TEXTS[row["top_document"]].splitlines()
            line = lines[int(row["top_line"]) - 1]
            self.assertIn(row["term_a"], line)
            self.assertIn(row["term_b"], line)

    def test_crlf_documents_keep_line_numbers(self):
        docs = self.p("docs")
        os.makedirs(docs)
        text = "开头一行。\r\n中间一行。\r\n斑马出现在第三行。\r\n"
        with open(os.path.join(docs, "crlf.txt"), "w",
                  encoding="utf-8", newline="") as handle:
            handle.write(text)
        listing = self.corpus("corpus_files.txt", ["crlf.txt"])
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = {row["term"]: row for row in self._lines()}
        self.assertIn("斑马", rows)
        self.assertEqual(rows["斑马"]["top_document"], "crlf.txt")
        self.assertEqual(int(rows["斑马"]["top_line"]), 3)


class TestAuditCsvListing(TempCase):
    """corpus_files.csv is what audit_corpus.py actually writes: the
    mining tool must consume it directly (header row, md5 hashes,
    status and dedupe facts) instead of a format nobody produces."""

    AUDIT_FIELDS = ["rel_path", "top", "name", "ext", "kind", "bytes",
                    "pages", "chars", "chars_effective", "images",
                    "encrypted", "status", "year_hint", "md5",
                    "dup_group", "dup_content_group", "dup_role",
                    "dup_role_content", "dedupe_group", "dedupe_role",
                    "error", "error_kind"]

    def _md5(self, path):
        with open(path, "rb") as handle:
            return hashlib.md5(handle.read()).hexdigest()

    def _write_audit_csv(self, rows, name="corpus_files.csv"):
        path = self.p(name)
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.AUDIT_FIELDS,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_audit_csv_listing_is_mined_with_audit_facts(self):
        docs = self.p("docs")
        os.makedirs(docs)
        texts = {
            "a.txt": "服务质量满意度提升，客户满意。\n",
            "b.txt": "产品故障率稳定。\n",
            "c.txt": "交付延迟，客户不满。\n",
            "d.txt": "响应速度慢。\n",
        }
        for name, text in texts.items():
            self.write(f"docs/{name}", text)
        rows = [
            {"rel_path": "a.txt", "status": "valid",
             "dedupe_role": "keeper", "md5": self._md5(
                 os.path.join(docs, "a.txt"))},
            # audit says this is image-only: trust its machine fact
            {"rel_path": "b.txt", "status": "image_only",
             "dedupe_role": "", "md5": self._md5(
                 os.path.join(docs, "b.txt"))},
            # audit already elected a keeper: the duplicate is skipped
            {"rel_path": "c.txt", "status": "valid",
             "dedupe_role": "duplicate", "md5": self._md5(
                 os.path.join(docs, "c.txt"))},
            # md5 mismatch: skipped with the real reason
            {"rel_path": "d.txt", "status": "valid",
             "dedupe_role": "", "md5": "0" * 32},
        ]
        listing = self._write_audit_csv(rows)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["inputs"]["listing_format"], "csv")
        self.assertEqual(receipt["inputs"]["hash_algorithm"], "md5")
        self.assertEqual(receipt["inputs"]["n_documents"], 1)
        self.assertEqual(receipt["inputs"]["skipped_audit_status"],
                         ["b.txt (image_only)"])
        self.assertEqual(receipt["inputs"]["skipped_audit_dedupe"],
                         ["c.txt"])
        self.assertEqual(receipt["inputs"]["skipped_hash_mismatch"],
                         ["d.txt"])
        keywords = self.read_csv("keyword_candidates.csv")
        self.assertIn("满意度", keywords)

    def test_tsv_duplicate_rel_paths_are_counted_once(self):
        docs, listing = build_project(self)
        listing = self.corpus("corpus_files.txt",
                              ["a.txt", "a.txt", "b.txt"])
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["inputs"]["listing_format"], "tsv")
        self.assertEqual(receipt["inputs"]["n_documents"], 2)
        self.assertEqual(receipt["inputs"]["skipped_duplicate"],
                         ["a.txt"])

    def test_partial_hash_mismatch_skips_only_that_file(self):
        docs = self.p("docs")
        os.makedirs(docs)
        self.write("docs/a.txt", TEXTS["a.txt"])
        self.write("docs/b.txt", TEXTS["b.txt"])
        real = subprocess.run(
            [sys.executable, "-c",
             "import hashlib,sys;"
             "print(hashlib.sha256(open(sys.argv[1],'rb').read())"
             ".hexdigest())",
             os.path.join(docs, "a.txt")],
            capture_output=True, text=True).stdout.strip()
        listing = self.corpus(
            "corpus_files.txt", [("a.txt", real), ("b.txt", "0" * 64)])
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["inputs"]["hash_algorithm"], "sha256")
        self.assertEqual(receipt["inputs"]["n_documents"], 1)
        self.assertEqual(receipt["inputs"]["skipped_hash_mismatch"],
                         ["b.txt"])

    def test_undecodable_file_recorded_separately_from_missing(self):
        docs, listing = build_project(self)
        bad = os.path.join(docs, "garbage.bin")
        with open(bad, "wb") as handle:
            handle.write(b"\xff\xfe\x00\xd8\xff\xff\x01\x02")
        listing = self.corpus("corpus_files.txt",
                              ["a.txt", "garbage.bin"])
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["inputs"]["skipped_missing"], [])
        self.assertEqual(receipt["inputs"]["skipped_undecodable"],
                         ["garbage.bin"])
        self.assertEqual(receipt["inputs"]["n_documents"], 1)

    def test_single_column_csv_header_is_not_a_document(self):
        # a .csv listing whose header is exactly the one column name:
        # the header must not leak into skipped_missing as a fake path
        docs = self.p("docs")
        os.makedirs(docs)
        self.write("docs/a.txt", TEXTS["a.txt"])
        listing = self.write("corpus.csv", "rel_path\na.txt\n")
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["inputs"]["listing_format"], "csv")
        self.assertEqual(receipt["inputs"]["n_documents"], 1)
        self.assertEqual(receipt["inputs"]["skipped_missing"], [])

    def test_receipt_records_corpus_bytes(self):
        docs, listing = build_project(self)
        proc = run("--root", docs, "--corpus", listing,
                   "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        # actual on-disk bytes (the writer translates \n per platform)
        expected = sum(os.path.getsize(os.path.join(docs, name))
                       for name in TEXTS)
        self.assertEqual(receipt["inputs"]["corpus_bytes"], expected)


class TestIsolation(TempCase):
    """Exit 3 (no sklearn) and the CLI-level fallback tokenizer, via
    fake packages that fail at import time - the documented degraded
    paths of decision #2."""

    def _fake_package(self, name):
        pkg_root = os.path.join(self.tmp, "fakepkgs")
        pkg = os.path.join(pkg_root, name)
        os.makedirs(pkg, exist_ok=True)
        with open(os.path.join(pkg, "__init__.py"), "w",
                  encoding="utf-8") as handle:
            handle.write("raise ImportError('isolated test fake')\n")
        return pkg_root

    def test_sklearn_missing_exits_3_with_clean_message(self):
        docs, listing = build_project(self)
        fake_root = self._fake_package("sklearn")
        proc = run_env({"PYTHONPATH": fake_root},
                       "--root", docs, "--corpus", listing,
                       "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("scikit-learn is required", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertFalse(os.path.exists(self.p("out",
                                               "keyword_candidates.csv")))

    def test_cli_falls_back_to_char_tokenizer_without_jieba(self):
        docs, listing = build_project(self)
        fake_root = self._fake_package("jieba")
        proc = run_env({"PYTHONPATH": fake_root},
                       "--root", docs, "--corpus", listing,
                       "--out", self.p("out"), "--min-df", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["inputs"]["tokenizer"], "fallback")
        terms = [row.split(",")[0] for row in
                 self.read_csv("keyword_candidates.csv")
                 .strip().splitlines()[1:]]
        # fallback = single chars + char bigrams: bigrams must appear
        self.assertTrue(any(len(term) == 2 and
                            "\u4e00" <= term[0] <= "\u9fff"
                            for term in terms))
        self.assertTrue(any(len(term) == 1 and
                            "\u4e00" <= term <= "\u9fff"
                            for term in terms))


class TestStandardLayout(TempCase):
    """The shape the workflow action registers must work end to end from
    a project root: audit writes corpus_files.csv with ``--root data``,
    mining consumes it with the same ``--root`` while ``--corpus``/``--out``
    resolve against the working directory (audit step args and action args
    are both cwd-relative there)."""

    AUDIT = os.path.join(SCRIPTS, "audit_corpus.py")

    def test_registered_action_shape_runs_from_project_root(self):
        for name, text in TEXTS.items():
            self.write(f"data/{name}", text)
        proc = subprocess.run(
            [sys.executable, self.AUDIT, "--root", "data",
             "--out-dir", "output/audit", "--min-chars", "1"],
            cwd=self.tmp, capture_output=True, text=True,
            encoding="utf-8", timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(
            self.p("output", "audit", "corpus_files.csv")))

        # exactly the args workflow.json's mine-candidates action binds
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--root", "data",
             "--corpus", "output/audit/corpus_files.csv",
             "--out", "output/mining", "--min-df", "1",
             "--seed", "20261118"],
            cwd=self.tmp, capture_output=True, text=True,
            encoding="utf-8", timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        receipt_path = self.p("output", "mining", "mine_receipt.json")
        with open(receipt_path, encoding="utf-8") as handle:
            receipt = json.load(handle)
        inputs = receipt["inputs"]
        self.assertEqual(inputs["n_documents"], len(TEXTS))
        self.assertEqual(inputs["skipped_missing"], [])
        self.assertEqual(inputs["corpus"],
                         "output/audit/corpus_files.csv")
        keyword_path = self.p("output", "mining",
                              "keyword_candidates.csv")
        self.assertTrue(os.path.isfile(keyword_path))
        with open(keyword_path, encoding="utf-8-sig") as handle:
            body = handle.read()
        # evidence anchors must name the real documents under data/
        self.assertIn("a.txt", body)


if __name__ == "__main__":
    unittest.main()
