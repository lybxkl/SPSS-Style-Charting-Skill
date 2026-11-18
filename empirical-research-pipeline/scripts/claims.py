# -*- coding: utf-8 -*-
"""Claims, manuscript blocks and support relations (plan R08).

A *claim* is one sentence of the manuscript that asserts something: a computed
result, a fact taken from the material, a statement about the literature, a
method description, an interpretation, or connective prose.  A *manuscript
block* is the container the sentence lives in (a paragraph, the abstract, a
table or figure caption).  Claims cite *support*: a model result, a reference,
or a dataset, and they declare the scope they are allowed to cover (unit,
denominator, time range, comparison rank, access level).

This module is the layer that ``verify_numbers.py`` cannot be: a number can be
digit-perfect and still be wrong when the sentence says "rose" for a negative
coefficient, "highest" for the second-largest estimate, "62 %" without a
denominator, or "caused" for an OLS association.  It therefore keeps three
things apart:

* **semantic checks** - direction / extremum / denominator / unit / time scope /
  association vs causation / reference access / unresolved numbers, plus two
  honest limits reported as human-read warnings: ``cue_negation`` (a
  clause-level negator before a direction/causal cue that the adjacent
  window cannot resolve, Chinese or English - contracted "didn't" forms
  included) and ``anaphora`` (a cue-bearing clause whose subject is a
  pronoun that may resolve to a different result);
* **identity** - a text fingerprint, so an edited sentence can never inherit the
  old support markers (``review_block`` re-computes it and also compares the
  *printed* text extracted from the final DOCX/PDF);
* **invalidation** - ``propagate`` walks :class:`depgraph.DependencyGraph`
  downstream of a changed result/reference/dataset and marks the affected
  claims and blocks ``stale``.

Rules:

* every write goes through :class:`contract_v2.Project` as a v2 ``claim`` /
  ``manuscript_block`` record; status changes are checked against the
  transition table, and a status that is not directly reachable (for example
  ``stale -> contradicted``) is walked through the shortest legal path;
* a check never upgrades a record by itself: :func:`check_claim` *reports* the
  status and only writes it with ``persist=True``;
* the fingerprint normalises NFKC, drops punctuation and collapses whitespace
  before hashing; the original string stays in the payload untouched, because
  the normalised form is a comparison view, not the value;
* warnings (time-scope extrapolation) are reported with ``ok=False`` but do not
  by themselves change the status - they are review flags, the same way
  ``qa_outputs.py`` warnings never move its exit code (only errors do);
* an unverifiable link is never "pass": a dangling reference/result is
  ``unsupported``, an inaccessible reference is ``pending``.

CLI::

    python claims.py --root . blocks
    python claims.py --root . check --claim cl_0123456789abcdef
    python claims.py --root . check --claim cl_0123456789abcdef --numbers n.json
    python claims.py --root . propagate --changed result:r1 reference:ref1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import deque
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C
import depgraph

# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------
CLAIM_TYPES = ("result", "material_fact", "literature", "method",
               "interpretation", "connection")
SUPPORT_KINDS = ("result", "reference", "dataset")
#: Prose that carries the argument forward does not cite a source; every other
#: type must.  A "connection" sentence is "the next section reports the model";
#: an "interpretation" may rest on the argument, not on one citable item.
SUPPORT_EXEMPT_TYPES = frozenset({"connection", "interpretation"})

#: ``metadata < abstract < full_text``.  Claiming a stronger access level than
#: the reference actually has is an overclaim (A33).
ACCESS_RANK = {"metadata": 1, "abstract": 2, "full_text": 3}

#: Result types that may carry a causal sentence.  Anything else - notably
#: ``ols_coefficient`` - is an association and must not be written as
#: "causes"/"leads to" (A32).
CAUSAL_RESULT_TYPES = frozenset({
    "experiment", "randomized_experiment", "randomised_experiment",
    "randomized_controlled_trial", "rct", "field_experiment",
    "natural_experiment", "instrumental_variable", "iv", "2sls",
    "two_stage_least_squares", "difference_in_differences", "did",
    "event_study", "regression_discontinuity", "rdd", "sharp_rdd",
    "fuzzy_rdd", "synthetic_control", "propensity_score_matching",
    "matching", "encouragement_design", "fixed_effects",
})

UP_CUES = (
    "上升", "增加", "提高", "增长", "增高", "升高", "上调", "上涨", "更高",
    "较强", "更强", "正向", "促进", "增大", "扩大",
    "increase", "increases", "increased", "increasing", "higher", "positive",
    "rise", "rises", "rose", "rising", "upward", "grew", "grow", "grows",
)
DOWN_CUES = (
    "下降", "减少", "降低", "减低", "下调", "更低", "较弱", "更弱", "负向",
    "抑制", "减弱", "减小", "缩小", "下跌",
    "decrease", "decreases", "decreased", "decreasing", "lower", "negative",
    "decline", "declines", "declined", "fall", "falls", "fell", "reduced",
    "reduce", "reduces", "downward", "smaller",
)
CAUSAL_CUES = (
    "导致", "引起", "因为", "由于", "造成", "促使", "归因于", "因果",
    "cause", "causes", "caused", "causing", "leads to", "lead to", "led to",
    "due to", "because of", "results in", "result in", "drives", "driving",
)
MAX_CUES = ("最高", "最大", "最强", "最多", "highest", "largest", "greatest",
            "most", "maximum", "max")
MIN_CUES = ("最低", "最小", "最弱", "最少", "lowest", "smallest", "least",
            "minimum", "min")

_NEGATORS = ("不", "未", "无", "没", "非")

#: Clause-level negation.  ``_negated`` only looks at the four characters
#: immediately before a cue, which resolves "不再上升" but misses
#: "并没有因此出现明显的上升" (the negator sits five-plus characters away)
#: and every English negator longer than the window ("didn't", "never"):
#: the cue still reads as asserted.  A cue that passes the adjacent
#: filter while its clause carries an unresolved negation *before* it
#: cannot be machine-decided - the direction verdict would either miss
#: the negation (false contradiction) or over-apply it ("不高的地区也有
#: 增长" negates 高, not 增长).  Such hits are reported as
#: ``cue_negation`` warnings for a human read instead of silently
#: deciding either way.
_CLAUSE_NEGATORS_ZH = ("不", "未", "无", "没", "非", "别", "莫", "难以",
                       "无法", "未能", "并非", "排除", "未见", "缺乏",
                       "缺少", "拒绝", "而不是")
_EN_NEGATOR_RE = re.compile(
    r"(?<![a-z])(?:[a-z]+n't|not|no|never|cannot|without|absent"
    r"|lack(?:s|ed|ing)?|fail(?:s|ed|ing)?|instead of|rather than)"
    r"(?![a-z0-9])", re.IGNORECASE)
#: Contrast markers break an earlier negator's governance: a cue after
#: 反而/但/却 is asserted even when the clause carries a negator before it
#: ("增速没有回落，反而出现上升" - the rise is asserted).  Only a contrast
#: *after the last negator* clears the cue; 反而没有上升 keeps the negation.
_CLAUSE_CONTRASTS_ZH = ("反而", "但是", "却", "而是", "但", "不过", "然而",
                        "倒是", "而是说")
_EN_CONTRAST_RE = re.compile(
    r"(?<![a-z])(?:however|but|yet|though|whereas|instead"
    r"|in contrast)(?![a-z])", re.IGNORECASE)
_CLAUSE_SPLIT_RE = re.compile(r"[。！？；!?;\n]|[，,]")

#: Anaphoric subjects ("该效应显著上升", "it increased") - the pronoun may
#: resolve to a different result than the cited one, so cue checks that
#: depend on which result the sentence is about get a human-read warning.
_ANAPHOR_RE = re.compile(
    r"^(?:该|此|其|上述|前述|这(?:一|两|几)?个?|两者|二者|"
    r"(?:the\s+)?above\b|this\b|it\b|they\b|both\b)", re.IGNORECASE)

_RATIO_RE = re.compile(
    r"(?<![\d.])\d{1,3}(?:\.\d+)?\s*[/／]\s*\d{1,3}(?:\.\d+)?(?![\d.])")
_PERCENT_RE = re.compile(
    r"(?<![\d.])\d+(?:\.\d+)?\s*[%％]"
    r"|百分之[零一二三四五六七八九十百点]+"
    r"|\d+\s*percent\b", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
_NUMBER_RE = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)*)(\s*[%％])?")
_YEAR_RE = re.compile(r"(1[89]\d{2}|20\d{2})")

_UNIT_SYNONYMS = {
    "人": "person", "人员": "person", "persons": "person", "people": "person",
    "受访者": "person", "个案": "case", "案例": "case", "cases": "case",
    "户": "household", "家庭": "household", "households": "household",
    "年": "year", "years": "year", "月": "month", "months": "month",
    "元": "cny", "人民币": "cny", "yuan": "cny", "rmb": "cny",
    "%": "percent", "％": "percent", "百分比": "percent", "百分之": "percent",
    "分": "point", "points": "point", "point": "point",
    "%点": "percent_point", "百分点": "percent_point",
}

#: Severity a check would have *if it failed*; ``ok`` says whether it did.
_SEVERITY = {
    "text_fingerprint": "error",
    "claim_type": "error",
    "support_missing": "error",
    "support_unresolved": "error",
    "direction": "error",
    "extremum": "error",
    "denominator": "error",
    "unit": "error",
    "time_scope": "warning",
    "causal": "error",
    "cue_negation": "warning",
    "anaphora": "warning",
    "reference_access": "error",
    "numbers": "error",
}


class ClaimError(Exception):
    """A claim/block operation was asked to do something unsound."""


# ---------------------------------------------------------------------------
# text identity
# ---------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """Comparison view of a sentence: NFKC, no punctuation, single spaces.

    Full-width and half-width forms collapse (NFKC), so do "。" / "." / "，"
    differences, and line wrapping becomes one space.  Case and word order are
    *not* touched - they carry meaning.
    """
    s = unicodedata.normalize("NFKC", str(text))
    s = "".join(ch for ch in s
                if not unicodedata.category(ch).startswith("P"))
    return re.sub(r"\s+", " ", s).strip()


def fingerprint(text: str) -> str:
    """SHA-256 of :func:`normalize_text`; the identity of a sentence."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _producer() -> dict:
    return C.producer_for("claims", version="2.0", module_file=__file__)


def _claim_id(block_id: str, claim_type: str, text: str) -> str:
    digest = C.canonical_hash({"block": str(block_id),
                               "type": str(claim_type),
                               "fingerprint": fingerprint(text)})
    return "cl_" + digest[:16]


# ---------------------------------------------------------------------------
# small value helpers
# ---------------------------------------------------------------------------
def _as_payload(obj: Mapping) -> dict:
    if isinstance(obj, Mapping) and "data" in obj and "kind" in obj:
        if not isinstance(obj.get("data"), Mapping):
            raise ClaimError(f"record {obj.get('id')!r} has a non-object payload")
        return dict(obj["data"])
    if isinstance(obj, Mapping):
        return dict(obj)
    raise ClaimError(f"expected a record or payload object, got {type(obj).__name__}")


def _record_id(obj) -> str | None:
    if isinstance(obj, Mapping) and "data" in obj and "kind" in obj and "id" in obj:
        return str(obj["id"])
    return None


def _num(value) -> float | None:
    """Parse an estimate/denominator-ish value; ``None`` when it is not a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = unicodedata.normalize("NFKC", str(value)).strip()
    if not s:
        return None
    pct = s.endswith("%") or s.endswith("％")
    if pct:
        s = s[:-1].strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    s = (s.replace(",", "").replace("−", "-")
         .replace("–", "-").replace("—", "-"))
    try:
        n = float(s)
    except ValueError:
        return None
    if neg:
        n = -abs(n)
    if pct:
        n = n / 100.0
    return n


def _as_int(value) -> int | None:
    n = _num(value)
    if n is None:
        return None
    if abs(n - round(n)) > 1e-9:
        return None
    return int(round(n))


def _estimate(payload: Mapping) -> float | None:
    inner = payload.get("payload")
    inner = inner if isinstance(inner, Mapping) else {}
    for candidate in (payload.get("estimate"), inner.get("estimate"),
                      inner.get("coef"), payload.get("coef"),
                      inner.get("value"), payload.get("value")):
        n = _num(candidate)
        if n is not None:
            return n
    return None


def _norm_unit(unit) -> str:
    if unit is None:
        return ""
    s = unicodedata.normalize("NFKC", str(unit)).strip().lower()
    s = re.sub(r"\s+", "", s)
    return _UNIT_SYNONYMS.get(s, s)


def _norm_denominator(value) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).strip().lower()
    s = re.sub(r"^(?:n|n=|样本量|分母)[\s:=＝]*", "", s)
    s = s.replace(",", "").replace("，", "")
    return re.sub(r"\s+", "", s)


def _norm_compact(value) -> str:
    """Whitespace-free comparison form (used for non-year time scopes)."""
    s = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return re.sub(r"\s+", "", s)


def _time_range(value) -> tuple[int, int] | None:
    if value is None:
        return None
    years = [int(m.group(1)) for m in _YEAR_RE.finditer(str(value))]
    if not years:
        return None
    return min(years), max(years)


def _cue_hits(text: str, cue: str) -> list[int]:
    """Positions of ``cue`` in ``text``, with word boundaries for ASCII cues."""
    low = text.lower()
    if cue.isascii():
        pattern = r"(?<![a-z])" + re.escape(cue) + r"(?![a-z])"
    else:
        pattern = re.escape(cue)
    return [m.start() for m in re.finditer(pattern, low)]


def _negated(text: str, start: int) -> bool:
    """Adjacent-negation window: the four characters before the cue.

    Resolves Chinese negators and the English words not/no right before
    the cue.  English contracted forms (didn't/wasn't) are deliberately
    NOT resolved here - "n't" plus at most one letter cannot see the
    verb - so they fall through to the clause-level filter and surface as
    cue_negation warnings instead of a silent skip.  Longer negators like
    "never" (six characters) also exceed the window and take the same
    route.
    """
    head = text[max(0, start - 4):start]
    if any(neg in head for neg in _NEGATORS):
        return True
    return bool(re.search(r"(^|[^a-z])(not|no)\s*$", head))


def _segments(text: str) -> list[tuple[int, int]]:
    """Clause spans (start, end) - split at sentence *and comma* level."""
    bounds = [0]
    for m in _CLAUSE_SPLIT_RE.finditer(text):
        bounds.append(m.start())
        bounds.append(m.end())
    bounds.append(len(text))
    spans = [(bounds[i], bounds[i + 1])
             for i in range(0, len(bounds) - 1, 2)]
    return [(s, e) for s, e in spans if e > s]


def _segment_of(spans: list[tuple[int, int]], pos: int
                ) -> tuple[int, int]:
    for s, e in spans:
        if s <= pos < e:
            return s, e
    return pos, pos + 1


def _clause_negated(text: str, pos: int,
                    spans: list[tuple[int, int]]) -> bool:
    """True when a clause-level negator sits before the cue with no
    contrast marker after it - a cue the machine cannot resolve."""
    start, _end = _segment_of(spans, pos)
    head = text[start:pos]
    if not head.strip():
        return False
    neg_positions = [head.rfind(neg) for neg in _CLAUSE_NEGATORS_ZH]
    en = list(_EN_NEGATOR_RE.finditer(head))
    if en:
        neg_positions.append(en[-1].start())
    neg_positions = [p for p in neg_positions if p >= 0]
    if not neg_positions:
        return False
    last_neg = max(neg_positions)
    tail = head[last_neg:]
    if any(con in tail for con in _CLAUSE_CONTRASTS_ZH):
        return False
    if _EN_CONTRAST_RE.search(tail):
        return False
    return True


def _cues(text: str, words: Iterable[str]) -> tuple[list[str], dict[str, int]]:
    """Clean cue list plus the hits the machine cannot resolve.

    Returns ``(clean, ambiguous)``: ``clean`` lists cues with at least one
    hit that survives both the adjacent filter and the clause filter;
    ``ambiguous`` counts, per cue, the hits a clause-level negator puts
    beyond mechanical reach (``{"上升": 1}``) so the caller can warn instead
    of silently deciding.
    """
    spans = _segments(text)
    clean: list[str] = []
    ambiguous: dict[str, int] = {}
    for cue in words:
        n_clean = 0
        n_ambiguous = 0
        for pos in _cue_hits(text, cue):
            if _negated(text, pos):
                continue
            if _clause_negated(text, pos, spans):
                n_ambiguous += 1
                continue
            n_clean += 1
        if n_clean:
            clean.append(cue)
        if n_ambiguous:
            ambiguous[cue] = n_ambiguous
    return clean, ambiguous


def _finding(check: str, ok: bool, detail, *, severity: str | None = None,
             outcome: str = "supported", applicable: bool = True) -> dict:
    return {
        "check": check,
        "severity": severity or _SEVERITY.get(check, "error"),
        "ok": bool(ok),
        "detail": detail,
        "outcome": outcome,
        "applicable": bool(applicable),
    }


def _result_index(project, results) -> tuple[dict, list[str]]:
    """Merge the ``model_result`` ledger with explicitly supplied results.

    Returns ``(index, pool)``: ``pool`` is the comparison set for extremum
    claims - the explicit ``results`` when given, otherwise the whole ledger.
    """
    index: dict[str, dict] = {}
    if project is not None:
        for rec in project.read("model_result"):
            index[rec["id"]] = _as_payload(rec)
    if results is None:
        return index, list(index)

    pool: list[str] = []
    if isinstance(results, Mapping) and not ("data" in results and "kind" in results):
        for key, value in results.items():
            index[str(key)] = _as_payload(value)
            pool.append(str(key))
        return index, pool
    seq = [results] if isinstance(results, Mapping) else list(results or ())
    for obj in seq:
        payload = _as_payload(obj)
        rid = (_record_id(obj) or payload.get("result_id")
               or payload.get("id") or f"r{len(pool) + 1}")
        index[str(rid)] = payload
        pool.append(str(rid))
    return index, pool


def _reference_index(project, references) -> dict[str, dict]:
    index: dict[str, dict] = {}
    if project is not None:
        for rec in project.read("reference"):
            index[rec["id"]] = _as_payload(rec)
    if references is None:
        return index
    if isinstance(references, Mapping) and not ("data" in references
                                                and "kind" in references):
        for key, value in references.items():
            index[str(key)] = _as_payload(value)
        return index
    seq = [references] if isinstance(references, Mapping) else list(references or ())
    for obj in seq:
        payload = _as_payload(obj)
        rid = (_record_id(obj) or payload.get("cite_id")
               or payload.get("id") or f"ref{len(index) + 1}")
        index[str(rid)] = payload
    return index


# ---------------------------------------------------------------------------
# status writing
# ---------------------------------------------------------------------------
def _status_path(kind: str, current: str, target: str) -> list[str]:
    """Shortest legal transition path (≤3 hops) from ``current`` to ``target``.

    The contract's table deliberately forbids jumps such as
    ``stale -> contradicted``; walking through ``draft`` is the legal way to
    re-dispose a record instead of hand-editing its status.
    """
    if current == target:
        return [target]
    known = C.STATUSES.get(kind, ())
    if current not in known or target not in known:
        raise ClaimError(f"{kind}: {current!r} -> {target!r} is not a known "
                         f"status pair")
    seen = {current}
    queue: deque[tuple[str, list[str]]] = deque([(current, [])])
    while queue:
        node, path = queue.popleft()
        if len(path) >= 3:
            continue
        for nxt in C.TRANSITIONS.get(kind, {}).get(node, ()):
            if nxt in seen:
                continue
            new_path = path + [nxt]
            if nxt == target:
                return new_path
            seen.add(nxt)
            queue.append((nxt, new_path))
    raise ClaimError(f"{kind}: no legal transition {current} -> {target} "
                     f"(the record must be re-registered first)")


def _write_status(project, previous: Mapping, target: str, *, patch=None,
                  reason: str | None = None, input_refs=None,
                  producer: Mapping | None = None) -> dict:
    """Append ``previous`` re-disposed as ``target``, one legal hop at a time.

    Each hop goes through :func:`contract_v2.transition`, so the status table is
    the only authority; ``input_refs`` is refreshed on the written record (it is
    not part of the content hash).
    """
    path = _status_path(previous["kind"], previous["status"], target)
    rec = previous
    for i, step in enumerate(path):
        last = i == len(path) - 1
        hop_patch = patch if last else None
        if not last and step == "draft" and rec["kind"] == "claim":
            # The forced intermediate hop is not a disposition; an old
            # ``checks``/``disposition`` must not look current on it.
            hop_patch = {"checks": [], "disposition": ""}
        rec = C.transition(rec, step,
                           producer=producer or _producer(),
                           reason=reason if last else None,
                           patch=hop_patch)
        if input_refs is not None:
            rec["input_refs"] = [dict(ref) for ref in input_refs]
        project.append(rec["kind"], rec)
    return rec


# ---------------------------------------------------------------------------
# support items
# ---------------------------------------------------------------------------
def _support_item(item) -> dict:
    if not isinstance(item, Mapping):
        raise ClaimError(f"support item must be an object, got {type(item).__name__}")
    kind = str(item.get("kind") or "").strip()
    if kind not in SUPPORT_KINDS:
        raise ClaimError(f"support kind {kind!r} not in {SUPPORT_KINDS}")
    rid = str(item.get("id") or "").strip()
    if not rid:
        raise ClaimError(f"support item of kind {kind} needs a non-empty id")
    out = dict(item)
    out["kind"] = kind
    out["id"] = rid
    return out


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------
def register_claim(project, *, claim_type: str, text: str, block_id: str,
                   section: str, support, scope: Mapping | None = None,
                   producer: Mapping | None = None,
                   claim_id: str | None = None) -> dict:
    """Register (or re-register) one sentence and its support relations.

    Re-registering an existing claim with a *changed* text or support returns
    the claim to ``draft`` - the previous checks described the previous
    sentence and must not survive the edit (A53).
    """
    if project is None:
        raise ClaimError("register_claim needs a contract_v2.Project")
    if claim_type not in CLAIM_TYPES:
        raise ClaimError(f"claim_type {claim_type!r} not in {CLAIM_TYPES}")
    text = str(text or "")
    if not normalize_text(text):
        raise ClaimError("claim text is empty after normalisation")
    block_id = str(block_id or "").strip()
    if not block_id:
        raise ClaimError("claim needs the id of the block it lives in")
    items = [_support_item(item) for item in (support or ())]

    block = project.latest("manuscript_block", block_id)
    declared_scope = dict(scope or {})
    declared_scope["block_fingerprint"] = (block["data"].get("fingerprint")
                                           if block else None)

    payload = {
        "claim_type": claim_type,
        "text": text,
        "block_id": block_id,
        "text_fingerprint": fingerprint(text),
        "support": items,
        "scope": declared_scope,
    }
    if section:
        payload["section"] = str(section)

    rid = claim_id or _claim_id(block_id, claim_type, text)
    input_refs = [{"kind": item["kind"], "id": item["id"]} for item in items]
    prod = producer or _producer()
    previous = project.latest("claim", rid)
    if previous is None:
        rec = C.make_record("claim", rid, payload, producer=prod,
                            status="draft", input_refs=input_refs)
        project.append("claim", rec)
        return rec

    if previous["data"] == payload:
        if previous["status"] in ("draft", "pending"):
            return previous
        if previous["status"] == "stale":
            return _write_status(project, previous, "draft",
                                 reason="re-registered from a stale record",
                                 producer=prod)
        return previous

    return _write_status(
        project, previous, "draft", patch=payload,
        reason=("claim text/support changed; earlier checks described the "
                "earlier sentence and no longer apply"),
        input_refs=input_refs, producer=prod)


def link_support(project, claim, support_item) -> dict:
    """Append one support relation; the previous disposition becomes ``pending``."""
    if project is None:
        raise ClaimError("link_support needs a contract_v2.Project")
    item = _support_item(support_item)
    previous = _latest_claim(project, claim)
    support = list(previous["data"].get("support") or [])
    if C.canonical_hash(item) not in {C.canonical_hash(s) for s in support}:
        support.append(item)
    input_refs = [{"kind": s["kind"], "id": s["id"]} for s in support]
    return _write_status(
        project, previous, "pending", patch={"support": support},
        reason=f"support relation added: {item['kind']}:{item['id']}",
        input_refs=input_refs)


def invalidate(project, claim, reason: str) -> dict:
    """Mark a claim ``stale`` (upstream result/reference/dataset changed)."""
    if project is None:
        raise ClaimError("invalidate needs a contract_v2.Project")
    previous = _latest_claim(project, claim)
    return _write_status(project, previous, "stale", reason=str(reason))


def register_block(project, *, block_id: str, section: str, text: str,
                   claims) -> dict:
    """Register a manuscript block and the claims that live in it."""
    if project is None:
        raise ClaimError("register_block needs a contract_v2.Project")
    block_id = str(block_id or "").strip()
    if not block_id:
        raise ClaimError("block_id is required")
    text = str(text or "")
    if not normalize_text(text):
        raise ClaimError("block text is empty after normalisation")
    claim_ids: list[str] = []
    for cid in claims or ():
        cid = str(cid)
        if cid and cid not in claim_ids:
            claim_ids.append(cid)
    payload = {
        "block_id": block_id,
        "section": str(section or ""),
        "text": text,
        "fingerprint": fingerprint(text),
        "claims": claim_ids,
    }
    previous = project.latest("manuscript_block", block_id)
    input_refs = [{"kind": "claim", "id": cid} for cid in claim_ids]
    if previous is None:
        rec = C.make_record("manuscript_block", block_id, payload,
                            producer=_producer(), status="draft",
                            input_refs=input_refs)
        project.append("manuscript_block", rec)
        return rec
    if previous["data"] == payload and previous["status"] != "stale":
        return previous
    target = "draft"
    return _write_status(
        project, previous, target, patch=payload,
        reason="block re-registered; its claims must be checked again",
        input_refs=input_refs)


# ---------------------------------------------------------------------------
# block review (text identity + printed text)
# ---------------------------------------------------------------------------
def _block_view(block) -> dict:
    if isinstance(block, str):
        return {"block_id": block, "text": None, "claims": []}
    if not isinstance(block, Mapping):
        raise ClaimError(f"block must be a record, a mapping or a block id, "
                         f"got {type(block).__name__}")
    if block.get("kind") == "manuscript_block" and isinstance(block.get("data"),
                                                              Mapping):
        payload = dict(block["data"])
        return {"block_id": str(payload.get("block_id") or block.get("id")),
                "text": payload.get("text"),
                "claims": list(payload.get("claims") or []),
                "record": block}
    block_id = block.get("block_id") or block.get("id")
    if not block_id:
        raise ClaimError("block mapping needs a block_id")
    claims = block.get("claims")
    return {"block_id": str(block_id),
            "text": block.get("text"),
            "claims": list(claims or []),
            "record": None}


def review_block(project, block, *, printed_text: str | None = None, context_text=None, persist=True) -> dict:
    """Review a block: re-hash its text, re-fingerprint its claims, compare print.

    The block passed in may carry the *edited* text; if that text is not the
    text its claims were registered against, both the block and those claims
    become ``stale`` - an edited sentence never keeps its old support markers.
    """
    if project is None:
        raise ClaimError("review_block needs a contract_v2.Project")
    view = _block_view(block)
    block_id = view["block_id"]
    stored = project.latest("manuscript_block", block_id)
    if stored is None:
        raise ClaimError(f"manuscript block {block_id!r} is not registered")
    text = view["text"] if view["text"] is not None else stored["data"]["text"]
    current_fp = fingerprint(text)
    stored_fp = stored["data"].get("fingerprint")

    findings: list[dict] = []
    stale = False

    def flag(check: str, detail, *, severity: str = "error",
             outcome: str = "unsupported") -> None:
        nonlocal stale
        findings.append(_finding(check, False, detail, severity=severity,
                                 outcome=outcome))
        if severity == "error":
            stale = True

    if stored_fp == current_fp:
        findings.append(_finding("block_text_changed", True,
                                 {"fingerprint": current_fp}))
    else:
        flag("block_text_changed",
             {"registered": stored_fp, "current": current_fp,
              "note": "the reviewed text is not the registered text; "
                      "re-register the block"})

    claim_ids = _collect_claim_ids(project, block_id,
                                   list(view["claims"]),
                                   list(stored["data"].get("claims") or []))
    claim_states: dict[str, str] = {}
    context = normalize_text(text if context_text is None else context_text)
    for cid in claim_ids:
        rec = project.latest("claim", cid)
        if rec is None:
            flag("claim_missing", {"claim": cid})
            claim_states[cid] = "missing"
            continue
        data = rec["data"]
        if str(data.get("block_id")) != block_id:
            flag("claim_block_mismatch",
                 {"claim": cid, "claim_block": data.get("block_id"),
                  "block": block_id})
        if data.get("text_fingerprint") != fingerprint(data.get("text") or ""):
            flag("claim_fingerprint_mismatch",
                 {"claim": cid,
                  "note": "claim text was edited without re-registering the "
                          "claim; its support no longer describes the text"})
        declared_against = (data.get("scope") or {}).get("block_fingerprint")
        if declared_against is None:
            findings.append(_finding(
                "claim_reregistration", True,
                {"claim": cid, "note": "registered before the block existed; "
                                       "no block version to compare"},
                applicable=False))
        elif declared_against != current_fp:
            flag("claim_not_reregistered",
                 {"claim": cid,
                  "registered_against": declared_against,
                  "current": current_fp,
                  "note": "block text changed but this claim was not "
                          "re-registered against the new text"})
            if rec["status"] != "stale" and persist:
                _write_status(project, rec, "stale",
                              reason=f"block {block_id} text changed; claim "
                                     f"was not re-registered")
                claim_states[cid] = "stale"
            else:
                claim_states[cid] = "stale"
        if normalize_text(data.get("text") or "") not in context:
            flag(
                "claim_text_missing",
                {"claim": cid,
                 "note": "the registered claim text no longer occurs in the "
                         "block text"})
        claim_states.setdefault(cid, rec["status"])

    if printed_text is not None:
        if normalize_text(printed_text) == normalize_text(text):
            findings.append(_finding("printed_text_mismatch", True,
                                     {"note": "printed text matches after "
                                              "normalisation"}))
        else:
            flag("printed_text_mismatch",
                 {"reviewed": normalize_text(text)[:200],
                  "printed": normalize_text(printed_text)[:200],
                  "note": "the text extracted from the final DOCX/PDF is not "
                          "the text that was reviewed"})

    target = "stale" if stale else "reviewed"
    failing = [f["check"] for f in findings if not f["ok"]]
    patch = {
        "text": text,
        "fingerprint": current_fp,
        "claims": claim_ids,
        "notes": ("review: " + ("; ".join(failing) if failing else "clean")),
    }
    if printed_text is not None:
        patch["printed_text"] = printed_text

    if not persist:
        new_block={**stored,"status":target}
    elif target == "reviewed" and stored["status"] == "reviewed" \
            and all(stored["data"].get(k) == v for k, v in patch.items()):
        new_block = stored
    else:
        new_block = _write_status(
            project, stored, target, patch=patch,
            reason=("block review: " + ("; ".join(failing) if failing
                                        else "text identity confirmed")),
            input_refs=[{"kind": "claim", "id": cid} for cid in claim_ids])

    return {
        "block_id": block_id,
        "status": new_block["status"],
        "revision": new_block["revision"],
        "fingerprint": current_fp,
        "findings": findings,
        "claims": claim_states,
        "failing": failing,
    }


def _collect_claim_ids(project, block_id: str, *groups) -> list[str]:
    ordered: list[str] = []
    for group in groups:
        for cid in group or ():
            cid = str(cid)
            if cid and cid not in ordered:
                ordered.append(cid)
    if project is not None:
        for rec in project.read("claim"):
            if str(rec["data"].get("block_id")) == block_id:
                if rec["id"] not in ordered:
                    ordered.append(rec["id"])
    return ordered


# ---------------------------------------------------------------------------
# propagation
# ---------------------------------------------------------------------------
def _latest_records(project, kind: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for rec in project.read(kind):
        rid = rec["id"]
        if rid not in out or rec["revision"] > out[rid]["revision"]:
            out[rid] = rec
    return out


def link_dependencies(project) -> dict:
    """Register claim/block nodes and their support edges, idempotently.

    The claim layer deliberately does not create graph nodes behind the caller's
    back (a graph that quietly grows itself is hard to audit), so this explicit
    step exists: run it once after claims are registered, and again after adding
    claims.  It registers ``claim``/``manuscript_block`` nodes plus ``supplies``
    edges from each support item to its claim, and a ``presents`` edge from each
    block to its claims, which is what lets :func:`propagate` follow the graph
    instead of falling back to a scan.
    """
    if project is None:
        raise ClaimError("link_dependencies needs a contract_v2.Project")
    graph = depgraph.DependencyGraph(project)
    claims = _latest_records(project, "claim")
    blocks = _latest_records(project, "manuscript_block")
    nodes = 0
    edges = 0
    for cid, rec in claims.items():
        key = f"claim:{cid}"
        if graph.get(key) is None:
            graph.register("claim", cid, rec["revision"], label=cid[:12],
                           status=rec["status"])
            nodes += 1
        for item in rec["data"].get("support") or ():
            target = str(item.get("id") or "")
            if not target:
                continue
            source = f"{item.get('kind')}:{target}"
            if source not in {n["key"] for n in graph.nodes()}:
                graph.register(str(item.get("kind")), target, 1,
                               label=target[:12])
                nodes += 1
            existing = {(e["src"], e["dst"], e["type"]) for e in graph.edges()}
            if (source, key, "supplies") not in existing:
                graph.add_edge(source, key, "supplies",
                               evidence=[{"claim": cid, "support": item}])
                edges += 1
    for bid, rec in blocks.items():
        key = f"manuscript_block:{bid}"
        if graph.get(key) is None:
            graph.register("manuscript_block", bid, rec["revision"],
                           label=bid[:12], status=rec["status"])
            nodes += 1
        for cid in rec["data"].get("claims") or ():
            source = f"claim:{cid}"
            existing = {(e["src"], e["dst"], e["type"]) for e in graph.edges()}
            if source in {n["key"] for n in graph.nodes()} and \
                    (key, source, "presents") not in existing:
                graph.add_edge(key, source, "presents",
                               evidence=[{"block": bid, "claim": cid}])
                edges += 1
    return {"nodes": nodes, "edges": edges, "claims": len(claims),
            "blocks": len(blocks)}


def propagate(project, changed_ids) -> dict:
    """Stale every claim/block downstream of a changed result/reference/dataset.

    The walk uses :meth:`depgraph.DependencyGraph.impact` when nodes and edges
    are registered, and always also scans the ``support`` relations, because a
    citation that was never wired into the graph must still be invalidated.
    """
    if project is None:
        raise ClaimError("propagate needs a contract_v2.Project")
    changed = [str(c) for c in (changed_ids or ()) if str(c)]
    if not changed:
        raise ClaimError("propagate needs at least one changed id")

    graph = depgraph.DependencyGraph(project)
    impact = graph.impact(changed)

    claim_ids: set[str] = set()
    block_ids: set[str] = set()
    for key in impact.get("affected", []):
        node_type, _, stable_id = key.partition(":")
        if node_type in ("claim", "claims"):
            claim_ids.add(stable_id)
        elif node_type in ("manuscript_block", "block", "blocks"):
            block_ids.add(stable_id)

    wanted = set(changed)
    for cid in changed:
        if ":" in cid:
            wanted.add(cid.split(":", 1)[1])

    latest_claims = _latest_records(project, "claim")
    for rid, rec in latest_claims.items():
        for item in rec["data"].get("support") or ():
            if (str(item.get("id")) in wanted
                    or f"{item.get('kind')}:{item.get('id')}" in wanted):
                claim_ids.add(rid)
                break

    for rid in list(claim_ids):
        rec = latest_claims.get(rid)
        if rec is not None:
            bid = str(rec["data"].get("block_id") or "")
            if bid:
                block_ids.add(bid)

    latest_blocks = _latest_records(project, "manuscript_block")
    for rid, rec in latest_blocks.items():
        if set(rec["data"].get("claims") or ()) & claim_ids:
            block_ids.add(rid)
    block_ids = {bid for bid in block_ids if bid in latest_blocks}

    reason = "upstream change: " + ", ".join(changed)
    records: list[dict] = []
    for rid in sorted(claim_ids):
        rec = latest_claims.get(rid)
        if rec is None or rec["status"] == "stale":
            continue
        new = _write_status(project, rec, "stale", reason=reason)
        latest_claims[rid] = new
        records.append({"kind": "claim", "id": rid,
                        "from": rec["status"], "to": new["status"],
                        "revision": new["revision"]})
    for rid in sorted(block_ids):
        rec = latest_blocks.get(rid)
        if rec is None or rec["status"] == "stale":
            continue
        new = _write_status(project, rec, "stale", reason=reason)
        records.append({"kind": "manuscript_block", "id": rid,
                        "from": rec["status"], "to": new["status"],
                        "revision": new["revision"]})

    return {
        "changed": changed,
        "claims": sorted(claim_ids),
        "blocks": sorted(block_ids),
        "records": records,
        "impact": {
            "affected": impact.get("affected", []),
            "by_type": impact.get("by_type", {}),
            "rejudge_negative": impact.get("rejudge_negative", []),
        },
    }


# ---------------------------------------------------------------------------
# checking
# ---------------------------------------------------------------------------
def _claim_payload(project, claim) -> tuple[dict, str | None]:
    if isinstance(claim, str):
        if project is None:
            raise ClaimError("a project is required to resolve a claim id")
        rec = project.latest("claim", claim)
        if rec is None:
            raise ClaimError(f"claim {claim!r} is not in the ledger")
        return dict(rec["data"]), rec["id"]
    if isinstance(claim, Mapping) and claim.get("kind") == "claim" \
            and isinstance(claim.get("data"), Mapping):
        return dict(claim["data"]), (str(claim["id"]) if claim.get("id") else None)
    if isinstance(claim, Mapping):
        payload = dict(claim)
        rid = payload.get("id") or payload.get("claim_id")
        return payload, (str(rid) if rid else None)
    raise ClaimError(f"claim must be a record, a payload mapping or a claim "
                     f"id, got {type(claim).__name__}")


def check_claim(project, claim, *, numbers: Mapping | None = None,
                results=None, references=None, persist: bool = False) -> dict:
    """Check a claim against its cited results/references.

    Returns ``{"findings": [...], "status": "supported"|"contradicted"|
    "unsupported"|"pending"}``.  Every finding carries ``check``, ``severity``
    (the weight it *would* have), ``ok``, ``detail``, ``outcome`` and
    ``applicable``.  Warnings are reported but do not change the status;
    contradictions dominate "could not verify", which dominates "pending".
    """
    payload, claim_id = _claim_payload(project, claim)
    claim_type = payload.get("claim_type")
    text = str(payload.get("text") or "")
    scope = dict(payload.get("scope") or {})
    support = [dict(item) for item in (payload.get("support") or ())
               if isinstance(item, Mapping)]
    findings: list[dict] = []

    # -- record identity ---------------------------------------------------
    computed_fp = fingerprint(text)
    stored_fp = payload.get("text_fingerprint")
    if not stored_fp:
        findings.append(_finding("text_fingerprint", True,
                                 "no fingerprint stored", applicable=False))
    elif stored_fp != computed_fp:
        findings.append(_finding(
            "text_fingerprint", False,
            {"stored": stored_fp, "recomputed": computed_fp,
             "note": "claim text no longer matches its registered "
                     "fingerprint; re-register before trusting the support"},
            outcome="unsupported"))
    else:
        findings.append(_finding("text_fingerprint", True,
                                 {"fingerprint": computed_fp}))

    if claim_type not in CLAIM_TYPES:
        findings.append(_finding("claim_type", False,
                                 f"unknown claim_type {claim_type!r}",
                                 outcome="unsupported"))
    else:
        findings.append(_finding("claim_type", True, claim_type))

    result_index, pool = _result_index(project, results)
    reference_index = _reference_index(project, references)
    result_items = [s for s in support if s.get("kind") == "result"]
    reference_items = [s for s in support if s.get("kind") == "reference"]
    dataset_items = [s for s in support if s.get("kind") == "dataset"]

    # -- 8. support presence ----------------------------------------------
    if not support:
        if claim_type in SUPPORT_EXEMPT_TYPES:
            findings.append(_finding(
                "support_missing", True,
                {"note": f"{claim_type} prose does not need a cited source"},
                applicable=False))
        else:
            findings.append(_finding(
                "support_missing", False,
                {"claim_type": claim_type,
                 "note": "a factual claim with no support: cite a result, a "
                         "reference or a dataset, or reclassify the sentence"},
                outcome="unsupported"))
    else:
        findings.append(_finding("support_missing", True,
                                 {"support": len(support)}))

    # -- dangling support --------------------------------------------------
    unresolved: list[dict] = []
    for item in result_items:
        if str(item.get("id")) not in result_index:
            unresolved.append({"kind": "result", "id": item.get("id")})
    for item in reference_items:
        if str(item.get("id")) not in reference_index:
            unresolved.append({"kind": "reference", "id": item.get("id")})
    if unresolved:
        findings.append(_finding(
            "support_unresolved", False,
            {"missing": unresolved,
             "note": "cited support does not exist in the ledger; the claim "
                     "cannot be verified"},
            outcome="unsupported"))
    elif dataset_items:
        findings.append(_finding(
            "support_unresolved", True,
            {"datasets": [i.get("id") for i in dataset_items],
             "note": "datasets are not resolved by this module"}, applicable=False))

    # -- 1. direction ------------------------------------------------------
    ups, up_amb = _cues(text, UP_CUES)
    downs, down_amb = _cues(text, DOWN_CUES)
    if not result_items:
        findings.append(_finding(
            "direction", True,
            {"cues": {"up": ups, "down": downs},
             "note": "no result support; direction is not machine-checkable"},
            applicable=False))
    elif ups and downs:
        findings.append(_finding(
            "direction", True,
            {"cues": {"up": ups, "down": downs},
             "note": "mixed direction cues; the sentence must be read by a human"},
            applicable=False))
    elif not ups and not downs:
        findings.append(_finding("direction", True,
                                 {"note": "no direction cue in the text"},
                                 applicable=False))
    else:
        polarity = 1 if ups else -1
        checked: list[dict] = []
        conflicts: list[dict] = []
        for item in result_items:
            rid = str(item.get("id"))
            cited = result_index.get(rid)
            if cited is None:
                continue
            est = _estimate(cited)
            if est is None or est == 0:
                continue
            checked.append({"result": rid, "estimate": est})
            if (est > 0) != (polarity > 0):
                conflicts.append({"result": rid, "estimate": est,
                                  "text_says": "up" if polarity > 0 else "down"})
        if conflicts:
            findings.append(_finding(
                "direction", False,
                {"cues": ups or downs, "checked": checked,
                 "conflicts": conflicts,
                 "note": "the sentence's direction contradicts the cited "
                         "estimate's sign"},
                outcome="contradicted"))
        elif checked:
            findings.append(_finding("direction", True,
                                     {"cues": ups or downs, "checked": checked}))
        else:
            findings.append(_finding(
                "direction", True,
                {"note": "no cited result has a numeric estimate"},
                applicable=False))

    # -- 2. extremum -------------------------------------------------------
    max_hits, max_amb = _cues(text, MAX_CUES)
    min_hits, min_amb = _cues(text, MIN_CUES)
    if not max_hits and not min_hits:
        findings.append(_finding("extremum", True,
                                 {"note": "no extremum cue"}, applicable=False))
    elif max_hits and min_hits:
        findings.append(_finding("extremum", True,
                                 {"cues": {"max": max_hits, "min": min_hits},
                                  "note": "both highest and lowest are claimed"},
                                 applicable=False))
    else:
        wants_max = bool(max_hits)
        rank_of = _as_int(scope.get("rank_of"))
        rank_total = _as_int(scope.get("rank_total"))
        if rank_of is None or rank_total is None:
            findings.append(_finding(
                "extremum", False,
                {"rank_of": scope.get("rank_of"),
                 "rank_total": scope.get("rank_total"),
                 "note": "an extremum claim must declare scope.rank_of and "
                         "scope.rank_total so the comparison set is explicit"},
                outcome="unsupported"))
        else:
            ref_id, ref_est = None, None
            for item in result_items:
                rid = str(item.get("id"))
                cited = result_index.get(rid)
                est = _estimate(cited) if cited is not None else None
                if est is not None:
                    ref_id, ref_est = rid, est
                    break
            if ref_id is None:
                findings.append(_finding(
                    "extremum", False,
                    {"note": "the extremum claim cites no result with a "
                             "numeric estimate"},
                    outcome="unsupported"))
            else:
                ref_payload = result_index.get(ref_id) or {}
                target = ref_payload.get("target_parameter")
                values = []
                for rid in pool:
                    cited = result_index.get(rid)
                    est = _estimate(cited) if cited is not None else None
                    if est is None:
                        continue
                    if target is not None \
                            and cited.get("target_parameter") != target:
                        continue
                    values.append((rid, est))
                if not values:
                    findings.append(_finding(
                        "extremum", False,
                        {"result": ref_id,
                         "note": "no comparison set: results must be supplied "
                                 "with the same target_parameter"},
                        outcome="unsupported"))
                else:
                    higher = sum(1 for _, est in values if est > ref_est)
                    lower = sum(1 for _, est in values if est < ref_est)
                    desc_rank = higher + 1      # 1 = largest
                    asc_rank = lower + 1        # 1 = smallest
                    detail = {
                        "result": ref_id,
                        "estimate": ref_est,
                        "comparison_set": [{"result": r, "estimate": v}
                                           for r, v in sorted(values,
                                                              key=lambda t: -t[1])],
                        "descending_rank": desc_rank,
                        "declared_rank_of": rank_of,
                        "declared_rank_total": rank_total,
                    }
                    if rank_total != len(values):
                        findings.append(_finding(
                            "extremum", False,
                            dict(detail, note=(
                                f"the comparison set has {len(values)} "
                                f"result(s) but the claim declares "
                                f"rank_total={rank_total}; the ranking cannot "
                                f"be verified")),
                            outcome="unsupported"))
                    elif wants_max:
                        if desc_rank == 1 and rank_of == 1:
                            findings.append(_finding("extremum", True, detail))
                        else:
                            findings.append(_finding(
                                "extremum", False,
                                dict(detail, note=(
                                    "the cited result is not the highest in the "
                                    "comparison set, or the declared rank does "
                                    "not match the computed one")),
                                outcome="contradicted"))
                    else:
                        if asc_rank == 1 and desc_rank == rank_total \
                                and rank_of == rank_total:
                            findings.append(_finding("extremum", True, detail))
                        else:
                            findings.append(_finding(
                                "extremum", False,
                                dict(detail, note=(
                                    "the cited result is not the lowest in the "
                                    "comparison set, or the declared rank does "
                                    "not match the computed one")),
                                outcome="contradicted"))

    # -- 3. denominator ----------------------------------------------------
    ratio = _RATIO_RE.search(text)
    percent = _PERCENT_RE.search(text)
    if not ratio and not percent:
        findings.append(_finding("denominator", True,
                                 {"note": "no ratio or percentage in the text"},
                                 applicable=False))
    else:
        denominator = scope.get("denominator")
        printed = ratio.group(0) if ratio else percent.group(0)
        if not denominator:
            findings.append(_finding(
                "denominator", False,
                {"printed": printed,
                 "note": "the text prints a ratio/percentage but the claim "
                         "declares no denominator; the share cannot be traced"},
                outcome="unsupported"))
        else:
            conflicts = []
            for item in result_items:
                cited = result_index.get(str(item.get("id")))
                if cited is None or not cited.get("denominator"):
                    continue
                if _norm_denominator(denominator) != \
                        _norm_denominator(cited["denominator"]):
                    conflicts.append({"result": item.get("id"),
                                      "claim": _norm_denominator(denominator),
                                      "result_denominator":
                                          _norm_denominator(cited["denominator"])})
            if conflicts:
                findings.append(_finding(
                    "denominator", False,
                    {"printed": printed, "conflicts": conflicts,
                     "note": "the claimed denominator is not the denominator "
                             "the cited result was computed on"},
                    outcome="contradicted"))
            else:
                findings.append(_finding(
                    "denominator", True,
                    {"printed": printed, "denominator": denominator}))

    # -- 4. unit -----------------------------------------------------------
    declared_units = []
    if scope.get("unit"):
        declared_units.append(("scope", str(scope["unit"])))
    for item in result_items:
        if item.get("unit"):
            declared_units.append((str(item.get("id")), str(item["unit"])))
    if not declared_units:
        findings.append(_finding("unit", True,
                                 {"note": "no unit declared"}, applicable=False))
    else:
        mismatches = []
        compared = 0
        for origin, declared in declared_units:
            for item in result_items:
                cited = result_index.get(str(item.get("id")))
                if cited is None or not cited.get("unit"):
                    continue
                compared += 1
                if _norm_unit(declared) != _norm_unit(cited["unit"]):
                    mismatches.append({"result": item.get("id"),
                                       "declared_from": origin,
                                       "declared": declared,
                                       "result_unit": cited["unit"]})
        if mismatches:
            findings.append(_finding(
                "unit", False,
                {"mismatches": mismatches,
                 "note": "the claimed unit is not the unit of the cited result"},
                outcome="contradicted"))
        elif compared:
            findings.append(_finding("unit", True,
                                     {"declared": declared_units[0][1]}))
        else:
            findings.append(_finding(
                "unit", True,
                {"note": "no cited result declares a unit to compare"},
                applicable=False))

    # -- 5. time scope -----------------------------------------------------
    declared_time = scope.get("time_scope")
    if not declared_time:
        findings.append(_finding("time_scope", True,
                                 {"note": "no time scope declared"},
                                 applicable=False))
    else:
        warned = []
        for item in result_items:
            cited = result_index.get(str(item.get("id")))
            if cited is None:
                continue
            result_time = cited.get("time_scope")
            if not result_time:
                warned.append({"result": item.get("id"),
                               "claim_time": declared_time,
                               "result_time": None})
                continue
            claim_range = _time_range(declared_time)
            result_range = _time_range(result_time)
            if claim_range and result_range:
                if claim_range[0] < result_range[0] \
                        or claim_range[1] > result_range[1]:
                    warned.append({"result": item.get("id"),
                                   "claim_time": declared_time,
                                   "result_time": result_time})
            elif _norm_compact(declared_time) != _norm_compact(result_time):
                warned.append({"result": item.get("id"),
                               "claim_time": declared_time,
                               "result_time": result_time})
        if warned:
            findings.append(_finding(
                "time_scope", False,
                {"extrapolated": warned,
                 "note": "the claim's time scope is wider than the cited "
                         "result's; this is an extrapolation"},
                outcome="supported"))
        else:
            findings.append(_finding("time_scope", True,
                                     {"time_scope": declared_time}))

    # -- 6. association vs causation --------------------------------------
    causal, causal_amb = _cues(text, CAUSAL_CUES)
    if not causal:
        findings.append(_finding("causal", True,
                                 {"note": "no causal cue"}, applicable=False))
    elif not result_items:
        findings.append(_finding(
            "causal", True,
            {"cues": causal,
             "note": "no result support; whether the cited literature supports "
                     "a causal reading is a human judgement"},
            applicable=False))
    else:
        bad_types = []
        inspected = 0
        for item in result_items:
            cited = result_index.get(str(item.get("id")))
            if cited is None:
                continue
            inspected += 1
            result_type = str(cited.get("result_type") or "").strip().lower()
            if result_type not in CAUSAL_RESULT_TYPES:
                bad_types.append({"result": item.get("id"),
                                  "result_type": result_type or "<missing>"})
        if bad_types:
            findings.append(_finding(
                "causal", False,
                {"cues": causal, "results": bad_types,
                 "note": "the sentence asserts causation but the cited result "
                         "is not a causal design (an association is not a "
                         "cause)"},
                outcome="contradicted"))
        elif inspected:
            findings.append(_finding("causal", True, {"cues": causal}))
        else:
            findings.append(_finding("causal", True,
                                     {"note": "no resolvable result"},
                                     applicable=False))

    # -- 6b. cue semantics the machine cannot resolve ----------------------
    # Direction/extremum/causal verdicts are only machine-meaningful with a
    # result behind them; without one they already route to a human read.
    if result_items:
        ambiguous_families = {
            "direction": {k: v for k, v in
                          {**up_amb, **down_amb}.items()},
            "extremum": {**max_amb, **min_amb},
            "causal": causal_amb,
        }
        ambiguous_families = {family: hits for family, hits
                              in ambiguous_families.items() if hits}
        if ambiguous_families:
            findings.append(_finding(
                "cue_negation", False,
                {"families": ambiguous_families,
                 "note": "a clause-level negator sits before these cues; the "
                         "machine cannot resolve the negation's scope, so "
                         "the verdict ignores them - read the sentence "
                         "before trusting the clean cues that remain"},
                severity="warning", outcome="supported"))
        # an anaphoric subject on a cue-bearing clause: the pronoun may
        # resolve to a different result than the cited one
        spans = _segments(text)
        anaphoric: list[str] = []
        seen: set[tuple[int, int]] = set()
        for words in (UP_CUES, DOWN_CUES, CAUSAL_CUES, MAX_CUES, MIN_CUES):
            for cue in words:
                for pos in _cue_hits(text, cue):
                    if _negated(text, pos):
                        continue
                    s, e = _segment_of(spans, pos)
                    if (s, e) in seen:
                        continue
                    seen.add((s, e))
                    clause_head = text[s:e].lstrip()
                    if _ANAPHOR_RE.match(clause_head):
                        anaphoric.append(clause_head[:40])
        if anaphoric:
            findings.append(_finding(
                "anaphora", False,
                {"clauses": anaphoric,
                 "note": "the cue-bearing clause starts with an anaphoric "
                         "subject; confirm the pronoun resolves to the "
                         "cited result before trusting the verdict"},
                severity="warning", outcome="supported"))

    # -- 7. reference access ----------------------------------------------
    if not reference_items:
        findings.append(_finding("reference_access", True,
                                 {"note": "no reference support"},
                                 applicable=False))
    else:
        problems: list[dict] = []
        pendings: list[dict] = []
        accepted: list[dict] = []
        for item in reference_items:
            ref_id = str(item.get("id"))
            ref = reference_index.get(ref_id)
            if ref is None:
                continue                       # covered by support_unresolved
            access = ref.get("access")
            if isinstance(access, Mapping):
                level = str(access.get("level") or "").strip().lower()
            elif access:
                level = str(access).strip().lower()
            else:
                level = ""
            claimed = ""
            for source in (scope.get("access"), scope.get("access_level"),
                           item.get("access"), item.get("access_level")):
                if isinstance(source, Mapping):
                    source = source.get("level")
                if source:
                    claimed = str(source).strip().lower()
                    break
            if level == "unavailable" or not level:
                pendings.append({"reference": ref_id, "actual": level or None,
                                 "claimed": claimed or None,
                                 "note": "the reference cannot be accessed; "
                                         "the claim stays unverified"})
                continue
            if not claimed:
                accepted.append({"reference": ref_id, "actual": level,
                                 "note": "no access level claimed by the text"})
                continue
            if ACCESS_RANK.get(claimed, 0) > ACCESS_RANK.get(level, 0):
                problems.append({"reference": ref_id, "claimed": claimed,
                                 "actual": level})
            else:
                accepted.append({"reference": ref_id, "claimed": claimed,
                                 "actual": level})
        if problems:
            findings.append(_finding(
                "reference_access", False,
                {"overclaims": problems,
                 "note": "the text claims a deeper access level than the "
                         "reference actually has"},
                outcome="contradicted"))
        elif pendings:
            findings.append(_finding(
                "reference_access", False,
                {"unavailable": pendings,
                 "note": "an unavailable reference is not a pass"},
                outcome="pending"))
        elif accepted:
            findings.append(_finding("reference_access", True,
                                     {"references": accepted}))
        else:
            findings.append(_finding(
                "reference_access", True,
                {"note": "no cited reference could be resolved"},
                applicable=False))

    # -- 9. numbers --------------------------------------------------------
    if numbers is None:
        # Derive permitted numbers from actual cited support, not arbitrary
        # literals in the sentence or an unrelated model elsewhere in the pool.
        automatic_numbers = {}
        def collect(value, path):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                automatic_numbers[path] = value
            elif isinstance(value, Mapping):
                for key, item in value.items():
                    collect(item, f"{path}.{key}")
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    collect(item, f"{path}.{index}")
            elif isinstance(value, str):
                candidate = _num(value)
                if candidate is not None:
                    automatic_numbers[path] = candidate
                elif path.endswith("time_scope"):
                    actual_range = _time_range(value)
                    claimed_range = _time_range(scope.get("time_scope"))
                    if actual_range:
                        automatic_numbers[path+".start"], automatic_numbers[path+".end"] = actual_range
                        if claimed_range and actual_range[0] <= claimed_range[0] <= claimed_range[1] <= actual_range[1]:
                            automatic_numbers[path+".claimed_start"], automatic_numbers[path+".claimed_end"] = claimed_range
        for item in support:
            if item.get("kind") in ("result", "model_result"):
                collect(result_index.get(item.get("id"), {}), str(item.get("id")))
        numbers = automatic_numbers
    findings.extend(_check_numbers(text, numbers))

    # -- verdict -----------------------------------------------------------
    failing = [f for f in findings if not f["ok"]]
    outcomes = {f["outcome"] for f in failing}
    if "contradicted" in outcomes:
        status = "contradicted"
    elif "unsupported" in outcomes:
        status = "unsupported"
    elif "pending" in outcomes:
        status = "pending"
    else:
        status = "supported"
    summary = ("check: " + status)
    if failing:
        summary += " (" + ", ".join(sorted({f["check"] for f in failing})) + ")"

    result = {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "status": status,
        "findings": findings,
        "errors": sum(1 for f in failing if f["severity"] == "error"),
        "warnings": sum(1 for f in failing if f["severity"] == "warning"),
        "text_fingerprint": stored_fp or computed_fp,
    }
    if persist:
        if project is None or not claim_id:
            raise ClaimError("persist=True needs a claim that lives in the ledger")
        previous = project.latest("claim", claim_id)
        if previous is None:
            raise ClaimError(f"claim {claim_id!r} is not in the ledger")
        result["record"] = _write_status(
            project, previous, status,
            patch={"checks": findings, "disposition": status,
                   "reason": summary},
            reason=summary)
    return result


def _check_numbers(text: str, numbers: Mapping | None) -> list[dict]:
    """Placeholders and printed numbers must be traceable to ``numbers``."""
    placeholders = [m.group(1).strip() for m in _PLACEHOLDER_RE.finditer(text)]
    tokens = []
    # Placeholders are substituted later; a "1" inside {table1_n} is not a
    # printed number and must not be demanded from --numbers.
    outside_placeholders = _PLACEHOLDER_RE.sub(" ", text)
    for match in _NUMBER_RE.finditer(outside_placeholders):
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tokens.append({"printed": match.group(0).strip(), "value": value,
                       "decimals": decimals,
                       "percent": bool(match.group(2))})

    if numbers is None:
        if placeholders:
            return [_finding(
                "numbers", False,
                {"placeholders": placeholders,
                 "note": "the text still carries {key} placeholders and no "
                         "numbers were supplied"},
                outcome="unsupported")]
        return [_finding("numbers", True,
                         {"note": "no placeholder and no numbers supplied"},
                         applicable=False)]

    supplied = {str(k): v for k, v in numbers.items()}
    missing_keys = [key for key in placeholders if key not in supplied]
    allowed = []
    for value in supplied.values():
        n = _num(value)
        if n is not None:
            allowed.append(n)
    missing_numbers = []
    for token in tokens:
        candidates = list(allowed)
        if token["percent"]:
            candidates += [v * 100 for v in allowed if abs(v) <= 1]
        tolerance = 0.5 * (10 ** -token["decimals"]) + 1e-12
        if not any(abs(c - token["value"]) <= tolerance for c in candidates):
            missing_numbers.append(token["printed"])
    if missing_keys or missing_numbers:
        return [_finding(
            "numbers", False,
            {"missing_placeholders": missing_keys,
             "missing_numbers": missing_numbers,
             "supplied_keys": sorted(supplied),
             "note": "a factual number that cannot be traced to --numbers "
                     "must not be printed"},
            outcome="unsupported")]
    return [_finding("numbers", True,
                     {"placeholders": placeholders,
                      "numbers": [t["printed"] for t in tokens]})]


# ---------------------------------------------------------------------------
# read helpers (CLI)
# ---------------------------------------------------------------------------
def _latest_claim(project, claim) -> dict:
    payload, claim_id = _claim_payload(project, claim)
    if claim_id:
        rec = project.latest("claim", claim_id) if project is not None else None
        if rec is not None:
            return rec
    if isinstance(claim, Mapping) and claim.get("kind") == "claim":
        if claim.get("revision", 1) > 1:
            raise ClaimError(f"claim {claim_id!r} is not in the ledger; only "
                             f"r1 records can be checked without one")
        return claim
    raise ClaimError(f"claim {claim_id!r} is not in the ledger")


def list_blocks(project) -> list[dict]:
    rows = []
    for rid, rec in _latest_records(project, "manuscript_block").items():
        data = rec["data"]
        rows.append({
            "block_id": data.get("block_id") or rid,
            "section": data.get("section"),
            "status": rec["status"],
            "revision": rec["revision"],
            "fingerprint": data.get("fingerprint"),
            "claims": list(data.get("claims") or []),
            "has_printed_text": "printed_text" in data,
        })
    rows.sort(key=lambda r: r["block_id"])
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="claims, manuscript blocks and "
                                             "their support relations")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="check one claim")
    p_check.add_argument("--claim", required=True)
    p_check.add_argument("--numbers", help="JSON file with {key: value}")
    p_check.add_argument("--no-persist", action="store_true")
    p_review = sub.add_parser("review", help="record actual contextual support reread")
    p_review.add_argument("--claim", required=True)
    p_review.add_argument("--decision", required=True, choices=["supported", "unsupported", "pending"])
    p_review.add_argument("--reviewer", required=True)
    p_review.add_argument("--note", required=True)
    p_review.add_argument("--scopes", required=True, help="JSON array of reopened path/sha256/locator records")

    sub.add_parser("blocks", help="list manuscript blocks")

    p_prop = sub.add_parser("propagate", help="stale claims/blocks downstream")
    p_prop.add_argument("--changed", nargs="+", required=True)

    args = ap.parse_args(argv)
    project = C.Project(args.root)
    if args.cmd == "review":
        from support_review import review
        try:
            with open(args.scopes, encoding="utf-8") as fh:
                scopes = json.load(fh)
        except OSError as exc:
            print(f"FAIL: cannot read --scopes {args.scopes}: {exc}",
                  file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"FAIL: --scopes {args.scopes} is not valid JSON: {exc}",
                  file=sys.stderr)
            return 2
        try:
            record = review(project, args.claim,
                            decision=args.decision,
                            reviewer=args.reviewer, note=args.note,
                            reread_scopes=scopes)
        except ValueError as exc:
            # support_review refuses, among others, when a semantic review
            # tries to override a machine-contradicted claim
            print(f"FAIL: {exc}", file=sys.stderr)
            return 2
        _print(record)
        return 0

    if args.cmd == "check":
        rec = project.latest("claim", args.claim)
        if rec is None:
            print(f"FAIL: claim {args.claim!r} is not in the ledger",
                  file=sys.stderr)
            return 2
        numbers = None
        if args.numbers:
            with open(args.numbers, encoding="utf-8") as fh:
                numbers = json.load(fh)
        result = check_claim(project, rec, numbers=numbers,
                             persist=not args.no_persist)
        _print(result)
        return 0 if result["status"] == "supported" else 2

    if args.cmd == "blocks":
        _print({"blocks": list_blocks(project)})
        return 0

    if args.cmd == "propagate":
        result = propagate(project, args.changed)
        _print(result)
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":            # pragma: no cover - CLI
    try:
        sys.exit(_main(sys.argv[1:]))
    except ClaimError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
