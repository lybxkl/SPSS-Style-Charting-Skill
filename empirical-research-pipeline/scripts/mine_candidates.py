# -*- coding: utf-8 -*-
"""Material mining - candidates, not findings.

The judgment split the skill runs on: the machine surfaces words, pairs
and coarse topic groupings that COULD matter, with the sentences that
support each candidate attached as anchors; deciding which of them mean
anything, name a construct, or enter the codebook stays with the
researcher (human or model) reading the material. Nothing here writes to
decisions ledgers, claim ledgers or anything a gate consumes - the
outputs are CSV candidate tables plus a receipt that pins them to the
input bytes.

Inputs come from a corpus listing in either of two shapes: the audit
step's ``corpus_files.csv`` (header row; ``rel_path`` drives the mining,
the ``sha256``/``md5`` columns verify the bytes when present, rows the
audit already marked ``status != valid`` or ``dedupe_role == duplicate``
are skipped with a receipt note), or a plain TSV with one ``rel_path``
or ``rel_path\tsha256`` per line (``#`` comments and blank lines
skipped). Files are read from the project root; repeated rel_paths are
dropped so a document cannot be counted twice. Every candidate row
keeps ``rel_path`` and a line number so a human opens the source at the
exact spot.

CLI::

    python scripts/mine_candidates.py --root . \
        --corpus output/audit/corpus_files.csv \
        --out output/mining

    python scripts/mine_candidates.py --root . --corpus ... --out ... \
        --stopwords draft/stopwords.txt --top 30 --min-df 2 \
        --topics 5 --scan-k 3,4,5,6 --seed 20261118

Determinism: same corpus + same parameters + same seed reproduce the
byte-identical tables (topics use a fixed seed). Chinese tokenization
prefers jieba when installed; without it the fallback tokenizer splits
English on whitespace and Chinese into single characters plus character
bigrams (documented degradation, still deterministic). A stopword list
is the researcher's call: the engine only drops empty tokens, pure
punctuation and single ASCII characters, and whatever the passed list
says.

Exit codes: 0 success, 2 refusable input errors, 3 the mining itself
failed (missing sklearn).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_VERSION = "1.1.0"

# The engine applies no content judgment. What it always drops is
# contentless machinery: empty tokens, pure punctuation/digits/symbols
# runs, and single ASCII letters. Anything else must be declared in the
# researcher's stopword file (an example list is documented in
# references/09-field-extraction.md).
# \W and \d already partition the fullwidth forms correctly (fullwidth
# digits ０-９ are \d, fullwidth punctuation ！？ is \W), so the explicit
# range below only repeats the CJK punctuation block. Fullwidth latin
# letters (ＡＢＣ) and halfwidth katakana (ｱｲｳ) are \w letters and
# SURVIVE the floor - dropping them would be a content judgment the
# engine is not allowed to make.
_PUNCT_RE = re.compile(
    r"^[\W\d_]+$|^[\u3000-\u303f]+$|^[a-zA-Z]$")


def _punct_re():
    return _PUNCT_RE


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def md5_file(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


class MineEmpty(Exception):
    """No terms survive the tokenizer + stopword combination."""


def tokenize(text: str) -> list[str]:
    """Language-agnostic tokenizer: jieba when importable (Chinese-aware,
    deterministic), else English whitespace + Chinese single chars and
    character bigrams. Output tokens are always non-empty and pass the
    engine floor; the caller applies the researcher's stopword list."""
    tokens: list[str] = []
    try:
        import jieba  # type: ignore
    except ImportError:
        tokens = _fallback_tokens(text)
    else:
        # jieba logs "Building prefix dict" at INFO on first run and
        # writes it to stderr; stderr is for errors in this skill.
        jieba.setLogLevel(logging.WARNING)
        raw = jieba.lcut(text)
        for piece in raw:
            piece = piece.strip()
            # engine floor: drop empty and single-ASCII-letter tokens
            # (contentless machinery; a researcher's stopword list is the
            # only content filter)
            if piece and not _punct_re().match(piece) \
                    and not (len(piece) == 1 and piece.isascii()
                             and piece.isalpha()):
                tokens.append(piece)
    return tokens


_FALLBACK_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-\'0-9]*")
_FALLBACK_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


def _fallback_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    # english-ish words
    for match in _FALLBACK_WORD_RE.finditer(text):
        word = match.group(0)
        if len(word) > 1:
            tokens.append(word)
    # chinese single chars + bigrams (no dictionary, deterministic)
    chars = _FALLBACK_HAN_RE.findall(text)
    tokens.extend(chars)
    for first, second in zip(chars, chars[1:]):
        tokens.append(first + second)
    return tokens


def _decode_text_file(path: str) -> str:
    """utf-8-sig -> gb18030 -> big5, the same chain the corpus reader
    uses; listing and stopword files get no weaker treatment than the
    documents themselves."""
    with open(path, "rb") as handle:
        raw = handle.read()
    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: not decodable as utf-8/gb18030/big5")


def read_corpus_listing(path: str):
    """Corpus listings come in two shapes:

    - ``corpus_files.csv`` - the audit step's own output, or any
      hand-made ``rel_path,sha256`` CSV (detected by a header starting
      with ``rel_path,``, or a ``.csv`` file with a comma'd header or
      the single-column header ``rel_path``). ``rel_path`` drives the
      mining, ``sha256``/``md5`` columns verify the bytes when present,
      and rows the audit already marked (``status != valid`` or
      ``dedupe_role == duplicate``) are skipped with a receipt note.
    - a plain TSV: one ``rel_path`` or ``rel_path\\tsha256`` per line,
      ``#`` comments and blank lines skipped.

    Repeated rel_paths are dropped (first occurrence wins) so a
    document cannot be counted twice; duplicates are reported. Returns
    ``(entries, meta)`` where meta carries the detected format and the
    duplicate list, or ``None`` after printing why the listing is
    refused.
    """
    try:
        text = _decode_text_file(path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot read corpus listing {path} ({exc})",
              file=sys.stderr)
        return None
    entries: list[dict] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    lines = text.splitlines()
    header = lines[0].strip() if lines else ""
    # CSV mode: the audit CSV's own header, or any .csv file with a
    # comma'd header (a hand-made rel_path,sha256 listing), or a
    # .csv file whose header is exactly the single column name.
    # Everything else is the plain TSV format.
    ext = os.path.splitext(path)[1].lower()
    is_csv = header.startswith("rel_path,") or (
        ext == ".csv" and "," in header) or (
        ext == ".csv" and header == "rel_path")
    if is_csv:
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames or []
        if "rel_path" not in fieldnames:
            print("ERROR: corpus CSV must have a rel_path column",
                  file=sys.stderr)
            return None
        for row in reader:
            rel = (row.get("rel_path") or "").strip()
            if not rel:
                continue
            if rel in seen:
                duplicates.append(rel)
                continue
            seen.add(rel)
            entries.append({
                "rel_path": rel,
                "sha256": (row.get("sha256") or "").strip(),
                "md5": (row.get("md5") or "").strip(),
                "status": (row.get("status") or "").strip(),
                "dedupe_role": (row.get("dedupe_role") or "").strip(),
                "format": "csv",
            })
        listing_format = "csv"
    else:
        for line_no, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            rel = parts[0].strip()
            sha = parts[1].strip() if len(parts) > 1 else ""
            if not rel:
                print(f"ERROR: corpus listing line {line_no} has no path",
                      file=sys.stderr)
                return None
            if rel in seen:
                duplicates.append(rel)
                continue
            seen.add(rel)
            entries.append({"rel_path": rel, "sha256": sha, "md5": "",
                            "status": "", "dedupe_role": "",
                            "format": "tsv"})
        listing_format = "tsv"
    return entries, {"format": listing_format, "duplicates": duplicates}


def load_stopwords(path: str | None) -> set[str]:
    if not path:
        return set()
    text = _decode_text_file(path)
    words = {line.strip() for line in text.splitlines()
             if line.strip() and not line.startswith("#")}
    return words


def read_text_decoded(path: str) -> str:
    with open(path, "rb") as handle:
        raw = handle.read()
    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: not decodable as utf-8/gb18030/big5")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Approximate sentence windows for evidence anchors (contentless):
    split on 。！？；.!?; newlines are hard boundaries. Good enough to open
    the file at the right spot - the human reads the actual sentence."""
    spans: list[tuple[int, int]] = []
    start = 0
    for index, ch in enumerate(text):
        if ch in "。！？；.!?;\n":
            if index > start:
                spans.append((start, index))
            start = index + 1
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


# ---------------------------------------------------------------------------
# TF-IDF keywords
# ---------------------------------------------------------------------------

def build_keyword_candidates(docs: list[dict], top: int, min_df: int,
                             stopwords: set[str], max_report: int = 3
                             ) -> tuple[list[list], list[dict]]:
    """docs: [{rel_path, text}] -> rows [term, df, n_docs, tfidf_mean,
    top_document, top_line, second_document, second_line]."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    def _tokenize_filter(text: str) -> list[str]:
        tokens = tokenize(text)
        return [token for token in tokens
                if token not in stopwords
                and (len(token) > 1 or _is_cjk(token))]

    def _is_cjk(token: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in token)

    vectorizer = TfidfVectorizer(tokenizer=_tokenize_filter,
                                 token_pattern=None, lowercase=False,
                                 min_df=min_df)
    try:
        matrix = vectorizer.fit_transform([doc["text"] for doc in docs])
    except ValueError as exc:
        # empty vocabulary: nothing survived the tokenizer + stopwords
        raise MineEmpty(f"no terms survive the tokenizer and stopword "
                        f"list (min_df={min_df}); TfidfVectorizer: {exc}"
                        ) from exc
    vocab = vectorizer.get_feature_names_out()
    scores = matrix.mean(axis=0).tolist()[0]
    doc_freq = ((matrix > 0).sum(axis=0)).tolist()[0]

    # evidence: for each term, the doc with its highest tf-idf weight
    term_rows = []
    for term_index, term in enumerate(vocab):
        # getcol() on the CSR matrix returns a single-column CSR whose
        # .indices are COLUMN indices (all zeros) - the row indices only
        # become readable after .tocsc(). Sorting stays by
        # (-weight, doc row) so ties break deterministically.
        column = matrix.getcol(term_index).tocsc()
        best_docs = sorted(zip(column.indices.tolist(),
                                column.data.tolist()),
                           key=lambda pair: (-pair[1], pair[0])
                           )[:max_report]
        evidence = []
        for doc_index, weight in best_docs:
            doc = docs[doc_index]
            hits = _term_offsets(doc["text"], term)
            if not hits:
                # the term has a tf-idf weight but is not a plain
                # substring of the text (tokenizer artifact): there is
                # no honest anchor - drop this doc as evidence instead
                # of inventing a line
                continue
            line = line_of_offset(doc["text"], hits[0])
            evidence.append((doc["rel_path"], line))
        if not evidence:
            continue
        top_doc, top_line = evidence[0]
        second_doc = evidence[1][0] if len(evidence) > 1 else ""
        second_line = evidence[1][1] if len(evidence) > 1 else ""
        term_rows.append([term, int(doc_freq[term_index]), len(docs),
                          f"{scores[term_index]:.6f}",
                          top_doc, top_line, second_doc, second_line])
    term_rows.sort(key=lambda row: (-float(row[3]), row[0]))
    return term_rows[:top], []


def _term_offsets(text: str, term: str) -> list[int]:
    offsets: list[int] = []
    start = text.find(term)
    while start != -1:
        offsets.append(start)
        start = text.find(term, start + len(term))
    return offsets


# ---------------------------------------------------------------------------
# Co-occurrence pairs (within sentence spans, PMI)
# ---------------------------------------------------------------------------

def build_pair_candidates(docs: list[dict], top: int, min_count: int,
                          stopwords: set[str], window: str = "sentence"
                          ) -> list[list]:
    pair_count: Counter = Counter()
    single_count: Counter = Counter()
    n_units = 0
    pair_evidence: dict[tuple[str, str], list[tuple[str, int]]] = {}

    for doc in docs:
        text = doc["text"]
        for start, end in sentence_spans(text):
            tokens = [token for token in tokenize(text[start:end])
                      if token not in stopwords and len(token) > 1]
            tokens = sorted(set(tokens))
            n_units += 1
            single_count.update(tokens)
            for i in range(len(tokens)):
                for j in range(i + 1, len(tokens)):
                    pair = (tokens[i], tokens[j])
                    pair_count[pair] += 1
                    slot = pair_evidence.setdefault(pair, [])
                    if len(slot) < 3:
                        line = line_of_offset(text, start)
                        if (doc["rel_path"], line) not in slot:
                            slot.append((doc["rel_path"], line))

    total_pairs = max(1, sum(pair_count.values()))
    rows = []
    for (left, right), count in pair_count.items():
        if count < min_count:
            continue
        # PMI with add-one smoothing on singles
        p_left = (single_count[left] + 1) / (n_units + 1)
        p_right = (single_count[right] + 1) / (n_units + 1)
        p_pair = (count + 1) / (total_pairs + 1)
        pmi = math.log2(p_pair / (p_left * p_right))
        evidence = pair_evidence[(left, right)]
        top_doc, top_line = evidence[0] if evidence else ("", "")
        second_doc = evidence[1][0] if len(evidence) > 1 else ""
        second_line = evidence[1][1] if len(evidence) > 1 else ""
        rows.append([left, right, count, f"{pmi:.4f}",
                     top_doc, top_line, second_doc, second_line])
    rows.sort(key=lambda row: (-int(row[2]), -float(row[3]), row[0], row[1]))
    return rows[:top]


# ---------------------------------------------------------------------------
# Topics (NMF, K declared by the human)
# ---------------------------------------------------------------------------

def build_topics(docs: list[dict], k: int, top_terms: int, seed: int,
                 stopwords: set[str], min_df: int) -> dict:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import NMF

    def _tokenize_filter(text: str) -> list[str]:
        tokens = tokenize(text)
        return [token for token in tokens
                if token not in stopwords
                and (len(token) > 1 or _is_cjk(token))]

    def _is_cjk(token: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in token)

    vectorizer = TfidfVectorizer(tokenizer=_tokenize_filter,
                                 token_pattern=None, lowercase=False,
                                 min_df=min_df)
    try:
        matrix = vectorizer.fit_transform([doc["text"] for doc in docs])
    except ValueError as exc:
        raise MineEmpty(f"no terms survive the tokenizer and stopword "
                        f"list (min_df={min_df}); TfidfVectorizer: {exc}"
                        ) from exc
    model = NMF(n_components=k, init="nndsvda", random_state=seed,
                max_iter=800)
    doc_topic = model.fit_transform(matrix)
    topic_word = model.components_
    vocab = vectorizer.get_feature_names_out()

    topics = []
    for topic_index in range(k):
        order = topic_word[topic_index].argsort()[::-1][:top_terms]
        terms = [vocab[index] for index in order
                 if topic_word[topic_index][index] > 0]
        topics.append(terms)

    assignments = []
    for doc_index, doc in enumerate(docs):
        topic_index = int(doc_topic[doc_index].argmax())
        weight = float(doc_topic[doc_index][topic_index])
        assignments.append([doc["rel_path"], topic_index + 1,
                            f"{weight:.4f}"])
    return {"topics": topics, "assignments": assignments,
            "n_docs": len(docs), "k": k, "seed": seed}


def scan_k(docs: list[dict], k_values: list[int], seed: int,
           stopwords: set[str], min_df: int) -> list[list]:
    """Silhouette over NMF document-topic vectors for each K - a curve the
    researcher reads, not a machine decision."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import NMF
    from sklearn.metrics import silhouette_score

    def _tokenize_filter(text: str) -> list[str]:
        tokens = tokenize(text)
        return [token for token in tokens
                if token not in stopwords
                and (len(token) > 1 or _is_cjk(token))]

    def _is_cjk(token: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in token)

    vectorizer = TfidfVectorizer(tokenizer=_tokenize_filter,
                                 token_pattern=None, lowercase=False,
                                 min_df=min_df)
    try:
        matrix = vectorizer.fit_transform([doc["text"] for doc in docs])
    except ValueError as exc:
        raise MineEmpty(f"no terms survive the tokenizer and stopword "
                        f"list (min_df={min_df}); TfidfVectorizer: {exc}"
                        ) from exc
    rows = []
    for k in k_values:
        if k < 2 or k >= len(docs):
            rows.append([k, "", "skipped (k must be 2..n_docs-1)"])
            continue
        try:
            model = NMF(n_components=k, init="nndsvda", random_state=seed,
                        max_iter=800)
            doc_topic = model.fit_transform(matrix)
        except ValueError as exc:
            # nndsvda needs k <= min(n_docs, vocabulary): a corpus with
            # a smaller vocabulary than K is a row-level skip, not a
            # crash - the curve stays readable
            rows.append([k, "",
                         f"skipped (K exceeds this corpus: {exc})"])
            continue
        labels = doc_topic.argmax(axis=1)
        if len(set(labels.tolist())) < 2:
            rows.append([k, "", "skipped (degenerate single cluster)"])
            continue
        score = silhouette_score(doc_topic, labels)
        rows.append([k, f"{score:.4f}", ""])
    return rows


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

def write_csv(path: str, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="material mining: candidates with evidence anchors, "
                    "for the researcher to adjudicate")
    parser.add_argument("--root", default=".",
                        help="project root the corpus paths resolve "
                             "against (default .)")
    parser.add_argument("--corpus", required=True,
                        help="corpus listing, resolved against --root: "
                             "audit_corpus.py's corpus_files.csv, or a "
                             "plain TSV of rel_path[\\tsha256] lines")
    parser.add_argument("--out", required=True,
                        help="output directory for candidate tables and "
                             "the receipt, resolved against the current "
                             "working directory (created unless it is an "
                             "existing file, which is refused)")
    parser.add_argument("--stopwords", default=None,
                        help="optional stopword file, one term per line "
                             "(# comments); the engine itself only drops "
                             "punctuation, digits, single ASCII letters")
    parser.add_argument("--top", type=int, default=30,
                        help="rows kept per candidate table (default 30)")
    parser.add_argument("--min-df", type=int, default=2,
                        help="a term must appear in at least this many "
                             "documents (default 2)")
    parser.add_argument("--min-count", type=int, default=2,
                        help="a pair must co-occur at least this often "
                             "(default 2)")
    parser.add_argument("--topics", type=int, default=None,
                        help="topic count K - the researcher declares it; "
                             "omit to skip topics")
    parser.add_argument("--topic-terms", type=int, default=8,
                        help="top terms listed per topic (default 8)")
    parser.add_argument("--scan-k", default=None,
                        help="comma-separated K values to profile with "
                             "silhouette (a curve to read, not a machine "
                             "decision); omit to skip")
    parser.add_argument("--seed", type=int, default=None,
                        help="seed for topic modeling; required when "
                             "--topics or --scan-k is used "
                             "(determinism is part of the receipt)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    corpus_path = Path(args.corpus)
    if not corpus_path.is_absolute():
        corpus_path = root / corpus_path
    if not corpus_path.is_file():
        return _fail(f"corpus listing not found: {args.corpus}")
    listing = read_corpus_listing(str(corpus_path))
    if listing is None:
        return 2
    entries, listing_meta = listing

    if args.top < 1 or args.min_df < 1 or args.min_count < 1 \
            or args.topic_terms < 1:
        return _fail("--top/--min-df/--min-count/--topic-terms must be "
                     "at least 1")
    if args.topics is not None and args.topics < 2:
        return _fail("--topics must be at least 2")
    if (args.topics is not None or args.scan_k) and args.seed is None:
        return _fail("--seed is required for topic modeling determinism; "
                     "declare the seed in the recipe of record")
    # parse --scan-k up front: a bad spec must refuse before any table
    # is built or written (no orphan CSVs)
    k_values = None
    if args.scan_k:
        k_values = _parse_k_values(args.scan_k)
        if k_values is None:
            return _fail("--scan-k must be comma-separated integers >= 2")

    try:
        stopwords = load_stopwords(args.stopwords) if args.stopwords \
            else set()
    except (OSError, ValueError) as exc:
        return _fail(f"cannot read stopwords file ({exc})")

    # documents
    docs: list[dict] = []
    skipped_missing: list[str] = []
    skipped_undecodable: list[str] = []
    skipped_hash: list[str] = []
    skipped_status: list[str] = []
    skipped_dedupe: list[str] = []
    corpus_bytes = 0
    hash_kinds: set[str] = set()
    for entry in entries:
        # CSV listings carry the audit's own machine facts: trust them
        # instead of re-reading files the audit already rejected
        status = entry.get("status", "")
        if status and status != "valid":
            skipped_status.append(f"{entry['rel_path']} ({status})")
            continue
        if entry.get("dedupe_role") == "duplicate":
            skipped_dedupe.append(entry["rel_path"])
            continue
        path = root / entry["rel_path"]
        if not path.is_file():
            skipped_missing.append(entry["rel_path"])
            continue
        try:
            text = read_text_decoded(str(path))
        except ValueError:
            skipped_undecodable.append(entry["rel_path"])
            continue
        sha = entry.get("sha256", "")
        md5 = entry.get("md5", "")
        if sha:
            hash_kinds.add("sha256")
            if sha256_file(str(path)) != sha:
                skipped_hash.append(entry["rel_path"])
                continue
        elif md5:
            hash_kinds.add("md5")
            if md5_file(str(path)) != md5:
                skipped_hash.append(entry["rel_path"])
                continue
        corpus_bytes += os.path.getsize(str(path))
        docs.append({"rel_path": entry["rel_path"], "text": text})
    if not docs:
        return _fail("no readable documents remain; refusing to mine "
                     "an empty corpus")

    # K must fit the corpus before anything is written: nndsvda needs
    # n_components <= min(n_docs, vocabulary)
    if args.topics is not None and args.topics >= len(docs):
        return _fail(f"--topics K={args.topics} must stay below the "
                     f"document count ({len(docs)} readable documents)")

    # all refusals are done - only now is anything created on disk, so
    # a refused run leaves no output directory behind either
    if os.path.exists(args.out) and not os.path.isdir(args.out):
        return _fail(f"--out exists and is not a directory: {args.out}")
    try:
        os.makedirs(args.out, exist_ok=True)
    except OSError as exc:
        return _fail(f"cannot create output directory {args.out} ({exc})")

    # build everything in memory first: a late failure (topics K above
    # the vocabulary, an empty term set) must not leave orphan tables
    try:
        keyword_rows, _ = build_keyword_candidates(
            docs, args.top, args.min_df, stopwords)
    except ImportError:
        print("ERROR: scikit-learn is required for TF-IDF/NMF mining; "
              "install scikit-learn to use this tool", file=sys.stderr)
        return 3
    except MineEmpty as exc:
        return _fail(str(exc))

    pair_rows = build_pair_candidates(docs, args.top, args.min_count,
                                      stopwords)

    topics = None
    if args.topics is not None:
        try:
            topics = build_topics(docs, args.topics, args.topic_terms,
                                  args.seed, stopwords, args.min_df)
        except MineEmpty as exc:
            return _fail(str(exc))
        except ImportError:
            # pathological half-install: the vectorizer import worked
            # but the decomposition module does not - same contract as
            # the keyword stage
            print("ERROR: scikit-learn is required for TF-IDF/NMF "
                  "mining; install scikit-learn to use this tool",
                  file=sys.stderr)
            return 3
        except ValueError as exc:
            return _fail(f"--topics K={args.topics} exceeds what this "
                         f"corpus supports ({exc}); lower K")

    scan_rows = None
    if k_values is not None:
        try:
            scan_rows = scan_k(docs, k_values, args.seed, stopwords,
                               args.min_df)
        except MineEmpty as exc:
            return _fail(str(exc))
        except ImportError:
            print("ERROR: scikit-learn is required for TF-IDF/NMF "
                  "mining; install scikit-learn to use this tool",
                  file=sys.stderr)
            return 3

    receipt = {
        "tool": "mine_candidates.py",
        "version": SCRIPT_VERSION,
        "generated_at": now_iso(),
        "inputs": {
            "corpus": str(Path(args.corpus)),
            "corpus_sha256": sha256_file(str(corpus_path)),
            "listing_format": listing_meta["format"],
            "hash_algorithm": "+".join(sorted(hash_kinds)) or "none",
            "n_listed": len(entries),
            "n_documents": len(docs),
            "corpus_bytes": corpus_bytes,
            "skipped_missing": skipped_missing,
            "skipped_undecodable": skipped_undecodable,
            "skipped_hash_mismatch": skipped_hash,
            "skipped_audit_status": skipped_status,
            "skipped_audit_dedupe": skipped_dedupe,
            "skipped_duplicate": listing_meta["duplicates"],
            "stopwords": args.stopwords or "",
            "stopwords_sha256": (sha256_file(args.stopwords)
                                 if args.stopwords else ""),
            "tokenizer": "jieba" if _jieba_available() else "fallback",
        },
        "params": {
            "top": args.top, "min_df": args.min_df,
            "min_count": args.min_count,
            "topics": args.topics, "topic_terms": args.topic_terms,
            "scan_k": args.scan_k, "seed": args.seed,
        },
        "outputs": [],
        "note": "candidates, not findings: every row names rel_path and "
                "line for the researcher to open and adjudicate; adopting "
                "a candidate into a field or codebook is a decision the "
                "human records elsewhere",
    }

    keyword_header = ["term", "doc_freq", "n_docs", "tfidf_mean",
                      "top_document", "top_line", "second_document",
                      "second_line"]
    write_csv(os.path.join(args.out, "keyword_candidates.csv"),
              keyword_header, keyword_rows)
    receipt["outputs"].append({"file": "keyword_candidates.csv",
                               "n_rows": len(keyword_rows)})

    pair_header = ["term_a", "term_b", "cooccurrence", "pmi",
                   "top_document", "top_line", "second_document",
                   "second_line"]
    write_csv(os.path.join(args.out, "pair_candidates.csv"),
              pair_header, pair_rows)
    receipt["outputs"].append({"file": "pair_candidates.csv",
                               "n_rows": len(pair_rows)})

    if topics is not None:
        write_csv(os.path.join(args.out, "topic_assignments.csv"),
                  ["rel_path", "topic", "weight"],
                  topics["assignments"])
        receipt["topics"] = topics["topics"]
        receipt["outputs"].append(
            {"file": "topic_assignments.csv",
             "n_rows": len(topics["assignments"])})

    if scan_rows is not None:
        write_csv(os.path.join(args.out, "k_profile.csv"),
                  ["k", "silhouette", "note"], scan_rows)
        receipt["outputs"].append({"file": "k_profile.csv",
                                   "n_rows": len(scan_rows)})

    receipt_path = os.path.join(args.out, "mine_receipt.json")
    with open(receipt_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"mining candidates: {len(docs)} documents -> "
          f"{args.out} ({len(receipt['outputs'])} tables + "
          "mine_receipt.json)")
    return 0


def _jieba_available() -> bool:
    try:
        import jieba  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def _parse_k_values(spec: str) -> list[int] | None:
    values: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            return None
        if value < 2:
            return None
        values.append(value)
    return values or None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
