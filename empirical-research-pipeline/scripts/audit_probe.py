#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zero-trust audit primitives.

The stage auditor must not trust anything the audited step reported about
itself: not its exit codes, not its evidence strings, not its intermediate
CSVs, not even the fact that its outputs are still the bytes that were audited.
This module supplies the mechanical re-derivation the auditor performs itself:

* bind an audit to the exact bytes it audited (sha256 snapshot, re-checked);
* RE-RUN a declared verification command and capture the real exit code;
* RE-READ a raw source and check a span/quote against it (quote must be a
  substring of the span, never the other way round -- a quote wider than the
  span could wrap a real core in fabricated context);
* recompute funnel monotonicity and key uniqueness from the tables themselves;
* re-walk the corpus and reconcile against the audit fingerprint (freshness);
* replay a cleaning recipe and enumerate EVERY dropped id (not a 20-row sample);
* check declared cross-dataset relations (orphans / fan-out / row accounting);
* check declared temporal rules (date bounds / per-key interval overlap).

Every function returns a structured result; none calls sys.exit. The CLI
wrappers (stage_audit.py, evidence_replay.py, relation_conformance.py,
rescan_corpus.py, cleaning_replay.py) turn results into exit codes. No
discipline-specific vocabulary lives here.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))

# Only genuinely plain text is read raw. HTML/XML/RTF and every binary format
# go through text_extract.extract_text, because the extraction layer anchors
# offsets on the *extracted* text (HTML tags stripped, PDF text layer, ...).
# Reading raw markup here would make every span miss the source it claims.
PLAIN_EXTS = {".txt", ".md", ".csv", ".tsv", ".log", ".json", ".jsonl"}

# Verification scripts the auditor is allowed to RE-RUN. The ledger is untrusted
# input; only these idempotent checkers may be executed. Production scripts
# (clean_data/make_coding_sheet/auto_stats/audit_corpus...) are deliberately
# excluded -- re-running them would rewrite outputs, not verify them.
CHECKER_ALLOWLIST = {
    "scope_conformance.py", "verify_numbers.py", "qa_outputs.py",
    "layout_conformance.py", "stage_audit.py", "report_tables.py",
    "relation_conformance.py", "evidence_replay.py", "cleaning_replay.py",
    "rescan_corpus.py", "check_decisions.py", "sample_review.py",
    "compute_kappa.py", "gate_canary.py", "research_gate.py",
    "verify_dataset.py",
}


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve(path: str, root: str) -> str:
    return path if os.path.isabs(path) else os.path.join(root or ".", path)


def collapse(text: str) -> str:
    return " ".join((text or "").split())


def normalize_newlines(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def read_source_text(path: str) -> str:
    """Re-read a source EXACTLY as the extraction layer anchored offsets.

    Always goes through text_extract.extract_text (the same function the
    extractor used) so HTML tags, PDF text layers, DOCX paragraphs and encoding
    handling are identical; then CRLF-normalised per references/09 §4. A raw
    read is only a fallback for plain-text files the extractor cannot open.
    """
    import text_extract as TX
    try:
        return normalize_newlines(TX.extract_text(path))
    except Exception:                                      # noqa: BLE001
        ext = os.path.splitext(path)[1].lower()
        if ext not in PLAIN_EXTS:
            raise
        raw = open(path, "rb").read()
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
            try:
                return normalize_newlines(raw.decode(encoding))
            except UnicodeDecodeError:
                continue
        return normalize_newlines(raw.decode("utf-8", errors="replace"))


def verify_span_quote(text: str, span, quote=None) -> tuple[bool, str]:
    """Check a span against re-read text; quote (if given) must sit INSIDE it.

    Direction matters: ``collapse(quote) in collapse(text[s:e])``. Allowing the
    reverse (span inside quote) would let a fabricated paragraph that happens
    to contain the real span pass as a verbatim quote.
    """
    if not isinstance(span, (list, tuple)) or len(span) != 2:
        return False, "span must be [start, end]"
    try:
        start, end = int(span[0]), int(span[1])
    except (TypeError, ValueError):
        return False, "span bounds must be integers"
    if start < 0 or end <= start or end > len(text):
        return False, f"span out of range (text length {len(text)})"
    span_text = collapse(text[start:end])
    if not span_text:
        return False, "span is empty after whitespace collapse"
    if quote is not None:
        quote_text = collapse(str(quote))
        if not quote_text:
            return False, "quote is empty"
        if quote_text not in span_text:
            return False, "quote is not contained in the span (fabricated context?)"
    return True, ""


def verify_artifacts(artifacts: dict, root: str) -> tuple[list[str], dict]:
    """Re-hash every artifact an audit pass claims to have audited.

    A mismatch means the audited bytes changed after the audit -- the pass no
    longer describes the current outputs and must be redone. This is what makes
    an audit a statement about *these* bytes rather than a free-floating claim.
    """
    errors: list[str] = []
    verified: dict = {}
    if not isinstance(artifacts, dict) or not artifacts:
        return ["artifacts snapshot is empty; an audit must bind to >=1 artifact"], verified
    for rel, claimed in artifacts.items():
        full = resolve(str(rel), root)
        if not os.path.isfile(full):
            errors.append(f"audited artifact missing: {rel}")
            continue
        actual = sha256_file(full)
        verified[str(rel)] = actual
        if str(claimed).lower() != actual:
            errors.append(f"audited artifact changed after audit: {rel} "
                          f"(claimed {str(claimed)[:12]}…, now {actual[:12]}…)")
    return errors, verified


def rerun_command(cmd: str, cwd: str, timeout: int = 600) -> dict:
    """Actually execute a declared verification command; capture the real exit.

    The ledger's claimed exit code is treated as a claim to be tested, not a
    fact. ZERO TRUST applies to the command itself: the ledger is untrusted
    input from the audited step, so re-running arbitrary strings would let a
    fabricated ledger weaponise the auditor (``python -c "..."`` runs any code).
    Only invocations of known verification scripts are re-run; ``-c``/``-m``
    and non-checker scripts are refused. Commands are parsed with shlex and
    executed without a shell.
    """
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        return {"exit": None, "stdout_sha256": None,
                "stderr_tail": f"command not parseable: {exc}", "timed_out": False}
    if not argv:
        return {"exit": None, "stdout_sha256": None,
                "stderr_tail": "empty command", "timed_out": False}
    exe = os.path.basename(argv[0]).lower()
    if exe not in ("python", "python3", "py", "python.exe", "python3.exe", "py.exe"):
        return {"exit": None, "stdout_sha256": None,
                "stderr_tail": "command must invoke python", "timed_out": False}
    if "-c" in argv or "-m" in argv:
        return {"exit": None, "stdout_sha256": None,
                "stderr_tail": "arbitrary code (-c/-m) is not a verification command",
                "timed_out": False}
    if len(argv) < 2 or os.path.basename(argv[1]) not in CHECKER_ALLOWLIST:
        return {"exit": None, "stdout_sha256": None,
                "stderr_tail": f"not an allowed verification script: {argv[1:2]}",
                "timed_out": False}
    try:
        proc = subprocess.run(argv, shell=False, cwd=cwd or ".",
                              capture_output=True, text=True, timeout=timeout)
        return {"exit": proc.returncode,
                "stdout_sha256": sha256_bytes((proc.stdout or "").encode("utf-8")),
                "stderr_tail": (proc.stderr or "")[-400:],
                "timed_out": False}
    except subprocess.TimeoutExpired:
        return {"exit": None, "stdout_sha256": None,
                "stderr_tail": f"timeout after {timeout}s", "timed_out": True}
    except OSError as exc:
        return {"exit": None, "stdout_sha256": None,
                "stderr_tail": str(exc), "timed_out": False}


FUNNEL_RE = re.compile(r"funnel\s*[=＝:：]\s*([^;；,，。．.]+)")
STAGE_REF_RE = re.compile(r"stage\s*[=＝:：]\s*([^;；,，。．.]+)")


def _funnel_name(note) -> str:
    match = FUNNEL_RE.search(str(note or ""))
    return match.group(1).strip() if match else ""


def read_table(path: str) -> list[dict]:
    last = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            with io.open(path, encoding=encoding, newline="") as fh:
                return list(csv.DictReader(fh))
        except UnicodeDecodeError as exc:
            last = exc
    raise last


def funnel_recompute(flow_path: str) -> list[str]:
    """Recompute funnel monotonicity from sample_flow.csv itself.

    kind=stage rows (the default when kind is absent) must be non-increasing
    within each declared funnel; kind=excluded/model rows are bounded by their
    stage but do not join the monotone sequence. The auditor does this instead
    of trusting a QA report the audited step wrote about its own funnel.
    """
    errors: list[str] = []
    rows = read_table(flow_path)
    if not rows:
        return ["sample_flow.csv has no rows"]
    has_kind = "kind" in (rows[0].keys())
    last_seen: dict[str, tuple[int, str]] = {}
    stage_ns: dict[tuple[str, str], int] = {}
    for i, row in enumerate(rows, start=1):
        stage = (row.get("stage") or "").strip()
        note = row.get("note") or ""
        kind = (row.get("kind") or "stage").strip() if has_kind else "stage"
        try:
            n = int(str(row.get("n") or "").replace(",", "").strip())
        except ValueError:
            errors.append(f"sample_flow row {i} ({stage}): n is not an integer")
            continue
        if kind == "stage":
            key = (_funnel_name(note), stage)
            stage_ns[key] = n
            funnel = _funnel_name(note)
            prev = last_seen.get(funnel)
            if prev is not None and n > prev[0]:
                errors.append(f"funnel '{funnel or 'default'}' grows at row {i} "
                              f"({stage}): {prev[0]} -> {n}")
            last_seen[funnel] = (n, stage)
        elif kind in ("excluded", "model"):
            funnel = _funnel_name(note)
            if n < 0:
                errors.append(f"sample_flow row {i}: negative {kind} n={n}")
            if kind == "excluded":
                prev = last_seen.get(funnel)
                if prev is not None and n > prev[0]:
                    errors.append(f"sample_flow row {i}: excluded n={n} exceeds "
                                  f"preceding stage {prev[1]!r} n={prev[0]}")
            else:
                m = STAGE_REF_RE.search(note)
                if not m:
                    errors.append(f"sample_flow row {i}: model row needs note 'stage=<阶段名>'")
                else:
                    st = m.group(1).strip()
                    bound = stage_ns.get((funnel, st))
                    if bound is None:
                        errors.append(f"sample_flow row {i}: model references unknown stage {st!r}")
                    elif n > bound:
                        errors.append(f"sample_flow row {i}: model n={n} exceeds stage {st!r} n={bound}")
        else:
            errors.append(f"sample_flow row {i}: illegal kind {kind!r}")
    return errors


def key_uniqueness(data_path: str, key_cols: list[str]) -> dict:
    """Recompute primary-key uniqueness from the table; report duplicate keys."""
    rows = read_table(data_path)
    header = set(rows[0].keys()) if rows else set()
    missing = [c for c in key_cols if c not in header]
    if missing:
        return {"rows": len(rows), "missing_key_columns": missing,
                "duplicates": [], "ok": False}
    counts = Counter(tuple((r.get(c) or "").strip() for c in key_cols) for r in rows)
    dupes = {k: n for k, n in counts.items() if n > 1}
    return {"rows": len(rows), "missing_key_columns": [],
            "duplicates": [{"key": list(k), "n": n} for k, n in list(dupes.items())[:50]],
            "duplicate_count": len(dupes), "ok": not dupes}


# ---------------------------------------------------------------------------
# heavier re-derivation (lazy imports keep the basic primitives light)
# ---------------------------------------------------------------------------

def rescan_corpus(root: str, audit_out: str, scratch: str,
                  frame_args: list[str] | None = None) -> dict:
    """Re-audit the corpus into a scratch dir and reconcile against the ledger.

    Freshness cannot be proven from the ledger alone: the auditor walks the
    directory again with the same sampling frame and compares the corpus
    fingerprint and the per-file rel_path/bytes/md5 set. New, vanished or
    content-changed files are reported. This reuses audit_corpus so the method
    is identical to the original audit, not a second drifting implementation.
    """
    import audit_corpus as AC
    summary_path = os.path.join(audit_out, "corpus_summary.json")
    ledger_path = os.path.join(audit_out, "corpus_files.csv")
    if not os.path.isfile(summary_path) or not os.path.isfile(ledger_path):
        return {"ok": False, "errors": ["audit ledger/summary missing; cannot rescan"]}
    old_summary = json.loads(open(summary_path, encoding="utf-8").read())
    frame = old_summary.get("sampling_frame") or {}
    args = ["--root", root, "--out-dir", scratch]
    for ext in frame.get("ext") or []:
        args += ["--ext", ext]
    for skip in frame.get("skip_dir") or []:
        if skip:
            args += ["--skip-dir", skip]
    if frame.get("min_chars") is not None:
        args += ["--min-chars", str(frame["min_chars"])]
    if old_summary.get("hash_disabled"):
        args += ["--no-hash"]
    if frame_args:
        args += frame_args
    code = AC.main(args)
    if code != 0:
        return {"ok": False, "errors": [f"rescan audit exited {code}"]}
    new_summary = json.loads(open(os.path.join(scratch, "corpus_summary.json"),
                                  encoding="utf-8").read())
    old_fp = (old_summary.get("corpus_fingerprint") or {}).get("sha256")
    new_fp = (new_summary.get("corpus_fingerprint") or {}).get("sha256")
    old_rows = {r["rel_path"]: r for r in read_table(ledger_path)}
    new_rows = {r["rel_path"]: r for r in
                read_table(os.path.join(scratch, "corpus_files.csv"))}
    added = sorted(set(new_rows) - set(old_rows))
    vanished = sorted(set(old_rows) - set(new_rows))
    changed = sorted(rel for rel in set(old_rows) & set(new_rows)
                     if (old_rows[rel].get("md5") or "") != (new_rows[rel].get("md5") or "")
                     or str(old_rows[rel].get("bytes") or "") != str(new_rows[rel].get("bytes") or ""))
    errors = []
    if added:
        errors.append(f"{len(added)} new file(s) since audit: {added[:10]}")
    if vanished:
        errors.append(f"{len(vanished)} file(s) vanished since audit: {vanished[:10]}")
    if changed:
        errors.append(f"{len(changed)} file(s) changed content since audit: {changed[:10]}")
    warnings: list[str] = []
    if old_summary.get("hash_disabled"):
        warnings.append("audit ran with --no-hash: content-change detection is size-only "
                        "(md5 unavailable); a same-size edit cannot be proven absent — "
                        "rerun the audit with hashes for ironclad freshness")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "fingerprint_match": old_fp == new_fp,
            "added": added, "vanished": vanished, "changed": changed,
            "old_fingerprint": old_fp, "new_fingerprint": new_fp}


def replay_cleaning(dataset: str, recipe: str, audited_out: str,
                    scratch: str) -> dict:
    """Re-run the cleaning recipe and compare the fingerprint chain + output.

    Also enumerates EVERY dropped id (input ids minus output ids), not the
    20-row sample the cleaning log keeps -- so a reviewer can see the full
    discard set without trusting the log's sampling.
    """
    import clean_data as CD
    code = CD.main(["--dataset", dataset, "--recipe", recipe, "--out", scratch])
    if code != 0:
        return {"ok": False, "errors": [f"cleaning replay exited {code}"]}
    errors = []
    a_clean = os.path.join(audited_out, "clean_dataset.csv")
    b_clean = os.path.join(scratch, "clean_dataset.csv")
    if not os.path.isfile(a_clean):
        errors.append("audited clean_dataset.csv missing")
    elif sha256_file(a_clean) != sha256_file(b_clean):
        errors.append("replayed clean_dataset.csv differs from audited output")
    a_log = os.path.join(audited_out, "cleaning_log.jsonl")
    b_log = os.path.join(scratch, "cleaning_log.jsonl")
    if os.path.isfile(a_log) and os.path.isfile(b_log):
        if _fingerprint_chain(a_log) != _fingerprint_chain(b_log):
            errors.append("replayed fingerprint chain differs from audited log")
    dropped = _full_dropped_ids(dataset, b_clean, recipe)
    return {"ok": not errors, "errors": errors,
            "dropped_ids_full": dropped, "n_dropped": len(dropped)}


def _fingerprint_chain(log_path: str) -> list:
    chain = []
    with io.open(log_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("record") == "step":
                chain.append((rec.get("step_index"), rec.get("sha_in"), rec.get("sha_out")))
    return chain


def _full_dropped_ids(dataset: str, clean_csv: str, recipe_path: str) -> list:
    """Enumerate the FULL discard set: by declared id, else by whole-row content.

    Without id_columns the cleaning log cannot name dropped rows, so the replay
    enumerates dropped rows by all-cell content instead of returning nothing.
    """
    recipe = json.loads(open(recipe_path, encoding="utf-8").read())
    id_cols = recipe.get("id_columns") or []
    rows_in = read_table(dataset)
    rows_out = read_table(clean_csv)
    if id_cols:
        before = {tuple((r.get(c) or "") for c in id_cols) for r in rows_in}
        after = {tuple((r.get(c) or "") for c in id_cols) for r in rows_out}
        return [list(k) for k in sorted(before - after)]
    cols = list(rows_in[0].keys()) if rows_in else []
    before = {tuple((r.get(c) or "") for c in cols) for r in rows_in}
    after = {tuple((r.get(c) or "") for c in cols) for r in rows_out}
    return [dict(zip(cols, k)) for k in sorted(before - after)]


def check_relations(registry: dict, root: str) -> dict:
    """Check declared units/keys/joins from the registry against the tables.

    A relation is a claim, not a foreign key the engine invents. The registry
    declares each dataset's key and each join's expected cardinality; this
    recomputes key uniqueness, orphan keys, fan-out and the resulting row
    accounting so a fabricated or granularity-shifting join cannot pass silently.
    """
    errors: list[str] = []
    warnings: list[str] = []
    datasets = {d["id"]: d for d in registry.get("datasets") or []}
    tables: dict[str, list[dict]] = {}

    def load(ident: str) -> list[dict] | None:
        if ident in tables:
            return tables[ident]
        ds = datasets.get(ident)
        if not ds:
            errors.append(f"join references unknown dataset {ident!r}")
            return None
        path = resolve(ds["path"], root)
        if not os.path.isfile(path):
            errors.append(f"dataset {ident}: file missing {ds['path']}")
            return None
        tables[ident] = read_table(path)
        return tables[ident]

    for ident, ds in datasets.items():
        rows = load(ident)
        if rows is None:
            continue
        key = ds.get("key")
        key_cols = [key] if isinstance(key, str) else list(key or [])
        if not key_cols:
            warnings.append(f"dataset {ident}: no key declared")
            continue
        res = key_uniqueness(resolve(ds["path"], root), key_cols)
        if res["missing_key_columns"]:
            errors.append(f"dataset {ident}: key columns missing {res['missing_key_columns']}")
        elif not res["ok"]:
            errors.append(f"dataset {ident}: key {key_cols} not unique "
                          f"({res['duplicate_count']} duplicate key(s)); unit={ds.get('unit')!r}")

    for join in registry.get("joins") or []:
        left, right = join.get("left"), join.get("right")
        lrows, rrows = load(left), load(right)
        if lrows is None or rrows is None:
            continue
        on = join.get("on")
        pairs = [[c, c] for c in on] if isinstance(on, list) and on and isinstance(on[0], str) \
            else [list(p) for p in on] if isinstance(on, list) else [[on, on]]
        how = join.get("how", "left")
        if how not in ("left", "inner"):
            errors.append(f"join {left}->{right}: unsupported how {how!r} (use left|inner)")
            continue
        expect = join.get("expect", "1:N")
        if expect not in ("1:1", "1:N", "N:1"):
            errors.append(f"join {left}->{right}: unknown expect {expect!r} (use 1:1|1:N|N:1)")
            continue
        lheader = set(lrows[0].keys()) if lrows else set()
        rheader = set(rrows[0].keys()) if rrows else set()
        bad_cols = [(lc, rc) for lc, rc in pairs
                    if lc not in lheader or rc not in rheader]
        if bad_cols:
            errors.append(f"join {left}->{right}: join column(s) missing {bad_cols}; "
                          "a missing key would match every row as empty")
            continue
        rindex: dict[tuple, int] = Counter(
            tuple((r.get(rc) or "").strip() for _, rc in pairs) for r in rrows)
        orphans = 0
        max_fanout = 0
        result_rows = 0
        for lr in lrows:
            key = tuple((lr.get(lc) or "").strip() for lc, _ in pairs)
            matches = rindex.get(key, 0)
            max_fanout = max(max_fanout, matches)
            if matches == 0:
                orphans += 1
                if how == "inner":
                    continue
            result_rows += max(matches, 1) if how != "inner" else matches
        if orphans and how == "inner":
            warnings.append(f"join {left}->{right}: {orphans} left row(s) dropped by inner join")
        if expect in ("1:1", "N:1") and max_fanout > 1:
            errors.append(f"join {left}->{right}: expected {expect} but a left key matches "
                          f"{max_fanout} right rows (fan-out inflates N)")
        if expect == "1:1" and orphans:
            errors.append(f"join {left}->{right}: expected 1:1 but {orphans} orphan left key(s)")
        # the "1" side of the declared cardinality must be unique on the join key
        if expect in ("1:N", "1:1"):
            lkc = Counter(tuple((r.get(lc) or "").strip() for lc, _ in pairs) for r in lrows)
            dup = sum(1 for v in lkc.values() if v > 1)
            if dup:
                errors.append(f"join {left}->{right}: expect {expect} but left join key has "
                              f"{dup} duplicate value(s); the 1-side must be unique")
        if expect in ("N:1", "1:1"):
            rkc = Counter(tuple((r.get(rc) or "").strip() for _, rc in pairs) for r in rrows)
            dup = sum(1 for v in rkc.values() if v > 1)
            if dup:
                errors.append(f"join {left}->{right}: expect {expect} but right join key has "
                              f"{dup} duplicate value(s); the 1-side must be unique")
        declared_n = join.get("result_n")
        if declared_n is not None and int(declared_n) != result_rows:
            errors.append(f"join {left}->{right}: declared result_n={declared_n} "
                          f"but recomputed {result_rows} (row accounting mismatch)")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _parse_date(value: str) -> tuple | None:
    value = (value or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$", value)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    day = int(m.group(3)) if m.group(3) else 1
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return (year, month, day)


def _parse_bound(value, is_max: bool) -> tuple | None:
    """Parse a temporal bound, expanding month precision to the whole month.

    A max of ``2021-12`` means through 2021-12-31, not 2021-12-01; a min of
    ``2021-01`` means from 2021-01-01. Day-precision bounds are taken as-is.
    """
    if not value:
        return None
    s = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return None
        day = calendar.monthrange(year, month)[1] if is_max else 1
        return (year, month, day)
    return _parse_date(s)


def check_temporal(scope: dict, data_path: str) -> dict:
    """Check declared temporal rules: date bounds and per-key interval overlap.

    Generic SCD/state validity hook: a project declares date columns with
    min/max and/or per-key effective intervals; the auditor recomputes bounds
    violations and overlapping intervals (two records claiming the same key
    valid at once) instead of trusting a categorical-only scope check.
    """
    errors: list[str] = []
    warnings: list[str] = []
    rows = read_table(data_path)
    header = set(rows[0].keys()) if rows else set()
    for rule in scope.get("temporal") or []:
        col = rule.get("col")
        if col not in header:
            errors.append(f"temporal column {col!r} not in data")
            continue
        lo = _parse_bound(rule.get("min"), False)
        hi = _parse_bound(rule.get("max"), True)
        bad = 0
        unparsed = 0
        for r in rows:
            val = (r.get(col) or "").strip()
            if not val:
                continue
            d = _parse_date(val)
            if d is None:
                unparsed += 1
                continue
            if (lo and d < lo) or (hi and d > hi):
                bad += 1
        if bad:
            errors.append(f"temporal {col}: {bad} row(s) outside [{rule.get('min')}, {rule.get('max')}]")
        if unparsed:
            warnings.append(f"temporal {col}: {unparsed} unparseable date(s)")
    for rule in scope.get("intervals") or []:
        key, start, end = rule.get("key"), rule.get("start"), rule.get("end")
        if not all(c in header for c in (key, start, end)):
            errors.append(f"interval columns {key}/{start}/{end} not all in data")
            continue
        by_key: dict[str, list] = defaultdict(list)
        bad_dates = 0
        invalid = 0
        for r in rows:
            k = (r.get(key) or "").strip()
            s = _parse_date(r.get(start))
            e_raw = (r.get(end) or "").strip()
            e = _parse_date(e_raw) if e_raw else None
            if s is None or (e_raw and e is None):
                bad_dates += 1
                continue
            if e is not None and e < s:
                invalid += 1
                continue
            by_key[k].append((s, e or (9999, 12, 31)))
        overlaps = 0
        for k, spans in by_key.items():
            spans.sort()
            for i in range(1, len(spans)):
                if spans[i][0] < spans[i - 1][1]:
                    overlaps += 1
        if invalid:
            errors.append(f"intervals {key}: {invalid} interval(s) with end before start")
        if bad_dates:
            warnings.append(f"intervals {key}: {bad_dates} unparseable interval date(s)")
        if overlaps:
            errors.append(f"intervals {key}: {overlaps} overlapping effective interval(s) "
                          "(same key valid twice at once)")
    return {"ok": not errors, "errors": errors, "warnings": warnings}