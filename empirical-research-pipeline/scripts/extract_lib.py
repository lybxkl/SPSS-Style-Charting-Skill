#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic field-extraction primitives.

Everything here is domain-free on purpose. Field knowledge lives in a profile
JSON (see ``references/09-field-extraction.md`` and ``profiles/``); this module only
provides the ten operations every text-based study needs: numbers, quantities,
dates, key/value blocks, sections, enumerations, evidence windows, negation
scope, vocabulary normalisation and de-duplicated counting.

The rule that makes the split meaningful: this file must not know what a
document is about. ``tests/test_extract_lib.py`` enforces that with a
greplist of subject-matter words, and it is part of the acceptance
criteria, not a stylistic preference.

All functions are pure: no I/O, no globals mutated, and every one of them is
unit-testable with a string literal.

Public API
----------
num / quantity / date / kv_block / section / items / window / negate / canon /
count_unique, plus pattern / contains for the two trivial field kinds, and
apply_profile() which runs a validated profile over one document.

Version: 1.0.0
"""
from __future__ import annotations

import json
import os
import re

__version__ = "1.0.0"

# --------------------------------------------------------------------------
# numerals
# --------------------------------------------------------------------------

CN_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2,
    "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
    "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}
CN_SMALL_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
CN_BIG_UNITS = {"万": 10000, "萬": 10000, "亿": 100000000, "億": 100000000}
CN_NUM_CHARS = "".join(CN_DIGITS) + "".join(CN_SMALL_UNITS) + "".join(CN_BIG_UNITS) + "点點"

_THOUSANDS = ",，\u00a0'’ "
_THOUSANDS_CLASS = r"[,\u00a0'’ ]"
_THOUSANDS_RE = re.compile(_THOUSANDS_CLASS)
_MAGNITUDE = (("亿", 100000000), ("億", 100000000),
              ("万", 10000), ("萬", 10000))
_ARABIC_NUMBER = re.compile(
    r"(\d{1,3}(?:" + _THOUSANDS_CLASS + r"\d{3})+(?:[.．]\d+)?|\d+(?:[.．]\d+)?)"
    r"\s*(亿|億|万|萬)?"
)
_CN_RUN = re.compile(r"[" + CN_NUM_CHARS + r"]{1,}")


def _clean_arabic(raw: str, magnitude: str = None) -> float:
    value = float(_THOUSANDS_RE.sub("", raw).replace("．", "."))
    if magnitude:
        for char, factor in _MAGNITUDE:
            if char == magnitude:
                value *= factor
                break
    return value


_ARABIC_ATOM = (r"(?:\d{1,3}(?:" + _THOUSANDS_CLASS + r"\d{3})+(?:[.．]\d+)?"
                r"|\d+(?:[.．]\d+)?)")
_MAGNITUDE_WORD = r"(?:万亿|千亿|千万|百万|亿|億|万|萬|千|仟|百|佰|十|拾)"
_NUM_UNIT_FORWARD = re.compile(r"(" + _ARABIC_ATOM + r")\s*(" + _MAGNITUDE_WORD + r")")
_ARABIC_PLAIN_FORWARD = re.compile(r"(" + _ARABIC_ATOM + r")")
# Digits may be written in Chinese inside an otherwise Arabic chain ("1亿零五万").
_CN_UNIT_FORWARD = re.compile(r"([零〇○一壹二贰两三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟]+)"
                              r"\s*(" + _MAGNITUDE_WORD + r")")
_FILLER_ZEROS = "零〇○"


def _read_arabic_chain(text: str, start: int):
    """Read ``1亿2千万`` / ``3万5千`` / ``1,234.56`` starting exactly at *start*.

    Returns ``(value, end)``; ``(None, start)`` when nothing numeric is there.
    Magnitudes must shrink left-to-right, so ``万5亿`` stops at the 万 instead of
    summing a number nobody wrote.

    A filler 零 after a magnitude means "and": ``1亿零五万`` is 1e8 + 5e4. It is
    skipped rather than ending the chain, and the digit group after it may be
    written in Chinese — both shapes occur in the same sentence.
    """
    total = 0.0
    parts = 0
    last = 0.0
    pos = start
    while True:
        if parts:
            # PDF extraction sprinkles spaces inside a numeral ("1亿 5万") and
            # `零` is a connector, not a terminator; neither ends the chain.
            while pos < len(text) and (text[pos] in _FILLER_ZEROS
                                       or text[pos] in " \t\u00a0"):
                pos += 1
        m = _NUM_UNIT_FORWARD.match(text, pos)
        number = None
        if m:
            try:
                number = _clean_arabic(m.group(1))
            except ValueError:
                number = None
        else:
            m = _CN_UNIT_FORWARD.match(text, pos)
            if m:
                number = _cn_integer(m.group(1))
                if number is not None:
                    number = float(number)
        if number is None:
            break
        scale = _CHAIN_SCALE[m.group(2)]
        # Read left to right, so magnitudes must *shrink*: `1亿2千万` is 1e8 + 2e7.
        if parts and scale >= last:
            break
        total += number * scale
        parts += 1
        last = scale
        pos = m.end()
    if parts:
        return total, pos
    m = _ARABIC_PLAIN_FORWARD.match(text, start)
    if m:
        try:
            return _clean_arabic(m.group(1)), m.end()
        except ValueError:
            return None, start
    return None, start


def _cn_integer(token: str):
    """Parse a Chinese integer written in any of the usual shapes.

    Handles both positional runs (二〇二一 -> 2021) and unit notation
    (十五万 -> 150000), including the mixed case (一万五千 -> 15000).
    Returns None when the token holds no recognisable digit.
    """
    if not token:
        return None
    total = 0        # accumulated above the current 万/亿 group
    section = 0      # accumulated inside the current section
    number = 0       # current run of digits
    seen = False
    for ch in token:
        if ch in CN_DIGITS:
            number = number * 10 + CN_DIGITS[ch]
            seen = True
        elif ch in CN_SMALL_UNITS:
            if number == 0:
                number = 1
            section += number * CN_SMALL_UNITS[ch]
            number = 0
            seen = True
        elif ch in CN_BIG_UNITS:
            if number == 0 and section == 0:
                number = 1
            total += (section + number) * CN_BIG_UNITS[ch]
            section = 0
            number = 0
            seen = True
        else:
            return None
    if not seen:
        return None
    return total + section + number


def _cn_decimal(token: str):
    """Parse 十五点五 -> 15.5 (digits after 点 are read positionally)."""
    if "点" in token or "點" in token:
        sep = "点" if "点" in token else "點"
        left, _, right = token.partition(sep)
        base = _cn_integer(left) if left else 0
        if base is None:
            return None
        digits = ""
        for ch in right:
            if ch in CN_DIGITS:
                digits += str(CN_DIGITS[ch])
            else:
                return None
        if not digits:
            return float(base)
        return float(f"{base}.{digits}")
    return None


def _to_float(text: str):
    return float(text.replace("．", "."))


def num(s: str):
    """First plain number in *s*, or None.

    Accepts Arabic with thousands separators (``1,358`` / ``1 358``), Arabic
    fractions, the 万/亿 suffix (``1.2万`` -> 12000) and Chinese numerals
    (``二〇二一`` / ``十五万`` / ``九千`` / ``零点五``). A Chinese numeral
    already carries its own magnitude, so the suffix rule is applied only to
    the Arabic form — doubling it was the bug that turned 十五万 into 1.5e9.
    """
    if s is None:
        return None
    text = str(s)
    arabic = _ARABIC_NUMBER.search(text)
    chinese = _CN_RUN.search(text)
    use_arabic = arabic is not None and (
        chinese is None or arabic.start() <= chinese.start())
    if use_arabic:
        # Read the whole magnitude chain: `1亿2千万` is 120000000, and reading
        # only the first group gives 1e8 — wrong by a factor of 1.2, silently.
        value, _end = _read_arabic_chain(text, arabic.start())
        if value is not None:
            return int(value) if float(value).is_integer() else value
    if chinese is not None:
        token = chinese.group(0)
        # A lone decimal point ("地点", "网点") is punctuation, not zero.
        # Reading it as 0 is how a missing age became a numeric 0.
        if not any(ch not in "点點" for ch in token):
            return None
        cn = _cn_decimal(token)
        if cn is None:
            cn = _cn_integer(chinese.group(0))
        if cn is not None:
            return int(cn) if float(cn).is_integer() else cn
    return None


def num_find(s: str):
    """Like :func:`num` but returns ``(value, (start, end))``."""
    if s is None:
        return None
    text = str(s)
    arabic = _ARABIC_NUMBER.search(text)
    chinese = _CN_RUN.search(text)
    use_arabic = arabic is not None and (
        chinese is None or arabic.start() <= chinese.start())
    if use_arabic:
        value, end = _read_arabic_chain(text, arabic.start())
        if value is not None:
            value = int(value) if float(value).is_integer() else value
            return (value, (arabic.start(), end))
    if chinese is not None:
        token = chinese.group(0)
        # A lone decimal point ("地点", "网点") is punctuation, not zero.
        # Reading it as 0 is how a missing age became a numeric 0.
        if not any(ch not in "点點" for ch in token):
            return None
        cn = _cn_decimal(token)
        if cn is None:
            cn = _cn_integer(chinese.group(0))
        if cn is not None:
            cn = int(cn) if float(cn).is_integer() else cn
            return (cn, chinese.span())
    return None


# --------------------------------------------------------------------------
# quantities
# --------------------------------------------------------------------------

DEFAULT_UNITS = {
    "元": {"factor": 1, "unit": "元", "aliases": ["元", "块", "圆"]},
    "万元": {"factor": 10000, "unit": "元", "aliases": ["万元"]},
    "亿元": {"factor": 100000000, "unit": "元", "aliases": ["亿元"]},
    "分钟": {"factor": 1, "unit": "分钟", "aliases": ["分钟", "分"]},
    "小时": {"factor": 60, "unit": "分钟", "aliases": ["小时", "钟头"]},
    "月": {"factor": 1, "unit": "月", "aliases": ["个月", "月"]},
    "年": {"factor": 12, "unit": "月", "aliases": ["年"]},
    "岁": {"factor": 1, "unit": "岁", "aliases": ["岁", "周岁"]},
    "亩": {"factor": 1, "unit": "亩", "aliases": ["亩"]},
    "公顷": {"factor": 15, "unit": "亩", "aliases": ["公顷"]},
    "天": {"factor": 1, "unit": "天", "aliases": ["天", "日"]},
}


def _unit_table(unit_table):
    table = dict(DEFAULT_UNITS)
    if unit_table:
        if isinstance(unit_table, str):
            key = unit_table
            if key in DEFAULT_UNITS:
                table = {key: DEFAULT_UNITS[key]}
        elif isinstance(unit_table, dict):
            table = {}
            for key, spec in unit_table.items():
                if isinstance(spec, dict):
                    table[key] = {
                        "factor": spec.get("factor", 1),
                        "unit": spec.get("unit", key),
                        "aliases": spec.get("aliases") or [key],
                    }
                else:
                    table[key] = {"factor": float(spec), "unit": key,
                                  "aliases": [key]}
    pairs = []
    for key, spec in table.items():
        for alias in spec["aliases"]:
            pairs.append((alias, spec))
    pairs.sort(key=lambda item: -len(item[0]))
    return pairs


def quantity_find(s: str, unit_table=None, want: str = None):
    """Like :func:`quantity` but returns ``(value, unit, (start, end))``.

    The span covers the numeral and the unit word together, which is what the
    evidence snippet needs; a bare value with a zero-width span cannot be
    re-checked against the source.
    """
    if s is None:
        return None
    text = str(s)
    pairs = _unit_table(unit_table)
    if not pairs:
        return None
    # Earliest mention wins, longest alias breaking ties. Scanning alias by
    # alias instead would let a distant "40分钟" beat the "半小时" that sits
    # right after the anchor, purely because "分钟" was tried first.
    best = None
    for alias, spec in pairs:
        if want and spec["unit"] != want and alias != want:
            continue
        for m in re.finditer(re.escape(alias), text):
            head = text[: m.start()]
            # An alias that itself carries a magnitude (`万元`) has already been
            # applied while reading the numeral, so its factor must NOT be
            # applied again — doing that turned 2万元 into 2e8 and 十五万元 into
            # 1.5e9. _num_ending_at re-attaches the magnitude and reads the run
            # once, so its result is already in the base unit.
            carries = bool(re.search(r"[亿億万萬千仟]", alias))
            raw = _num_ending_at(
                head, trailing_scale=spec.get("factor") if carries else None)
            if raw is None:
                continue
            value = raw if carries else raw * spec["factor"]
            probe = m.start()
            while probe > 0 and (text[probe - 1].isdigit()
                                 or text[probe - 1] in _THOUSANDS
                                 or text[probe - 1] in CN_NUM_CHARS
                                 or text[probe - 1] in ".． "):
                probe -= 1
            cand = (probe, m.end(), -len(alias), round(value, 6), spec["unit"])
            if best is None or cand[:3] < best[:3]:
                best = cand
            break                     # first sighting of this alias is enough
    if best is None:
        return None
    return (best[3], best[4], (best[0], best[1]))


def quantity(s: str, unit_table=None, want: str = None):
    """First ``number + unit`` pair, normalised to its standard unit.

    Returns ``(value, standard_unit)`` or None. ``want`` restricts the search to
    one unit family (e.g. ``"元"``), which matters when a sentence carries
    several numbers.
    """
    hit = quantity_find(s, unit_table, want)
    return (hit[0], hit[1]) if hit else None


_ARABIC_AT_END = re.compile(
    r"(?<![\d.,．．])(\d{1,3}(?:" + _THOUSANDS_CLASS + r"\d{3})+(?:[.．]\d+)?"
    r"|\d+(?:[.．]\d+)?)\s*$")
_CN_AT_END = re.compile("[" + CN_NUM_CHARS + r"]+\s*$")
_SUFFIX_SCALE = {"亿": 100000000, "億": 100000000, "万": 10000, "萬": 10000,
                 "千": 1000, "仟": 1000, "百": 100, "佰": 100,
                 "十": 10, "拾": 10}


_CHAIN_SCALE = dict(_SUFFIX_SCALE)
_CHAIN_SCALE.update({"千万": 1e7, "百万": 1e6, "千亿": 1e11, "万亿": 1e12})


_SCALE_CHAR = {1e8: "亿", 1e4: "万", 1e3: "千", 1e2: "百", 10: "十"}


def _chain_ending_at(text: str, window: int = 40):
    """Longest number produced by the forward chain that ends at ``text[-1]``.

    One reader for every shape: reading a numeral backwards with a second set of
    rules is what made ``1亿零5万`` come out as 50000 in one place and 1e8 in
    another — two parsers agree with themselves and disagree with the document.
    """
    n = len(text)
    for start in range(max(0, n - window), n):
        value, end = _read_arabic_chain(text, start)
        if value is not None and end == n:
            return value
    return None


def _num_ending_at(head: str, trailing_scale: float = None):
    """Read a number that ends exactly at the end of *head*.

    ``9千`` must read as 9000, not as the bare 千 that follows it — the
    Arabic-then-magnitude shape is checked before the bare Chinese one.
    Magnitudes chain and must *shrink* going left: ``3万5千`` is 35000,
    ``1亿2千万`` is 120000000, ``1亿2000万`` is 120000000.

    ``trailing_scale`` is the magnitude carried by the unit that was consumed
    *after* the number (``万元`` = 1e4). It is re-attached to the numeral and the
    whole run is read once, so ``1亿2000万元`` is 1.2e8 rather than 1e8 + 2000
    and ``1200万元`` is 1.2e7 rather than 1200.
    """
    text = (head or "").rstrip(" \t\u00a0")
    if not text:
        return None
    probe = text
    if trailing_scale and trailing_scale > 1:
        char = _SCALE_CHAR.get(trailing_scale)
        if char:
            probe = text + char
    value = _chain_ending_at(probe)
    if value is not None:
        return value
    m = _ARABIC_AT_END.search(text)
    if m:
        try:
            return _clean_arabic(m.group(1))
        except ValueError:
            return None
    m = _CN_AT_END.search(text)
    if m:
        cn = _cn_decimal(m.group(0)) or _cn_integer(m.group(0))
        return float(cn) if cn is not None else None
    # `半小时` / `半个` — Chinese drops the "one" in front of 半.
    if text.endswith("半"):
        return 0.5
    return None


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------

_DATE_ARABIC = re.compile(
    r"(?<!\d)(\d{4})\s*[年./\-．]\s*(\d{1,2})\s*[月./\-．]\s*(\d{1,2})\s*日?"
)
_DATE_MONTH = re.compile(r"(?<!\d)(\d{4})\s*[年./\-．]\s*(\d{1,2})\s*月?")
_DURATION_PART = re.compile(
    r"((?:\d+(?:[.．]\d+)?)|[〇○零一二三四五六七八九十百千两兩]+)\s*"
    r"(个月|年|月|日|天|周|星期|小时|分钟)")
_DATE_CN = re.compile(
    r"([〇○零一二三四五六七八九]{4})\s*年\s*"
    r"([〇○零一二三四五六七八九十]{1,3})\s*月\s*"
    r"([〇○零一二三四五六七八九十]{1,3})\s*日?"
)
# A redacted date: the year is printed, the rest is masked (2021********).
# Reading it as "no date here" made the field fall back to a *different* event's
# date buried in the body — a 33-year error that looks like a data problem.
_DATE_REDACTED = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[*＊×﹡]{2,}")


def _valid(y, m, d=None):
    if y is None or m is None:
        return False
    if not (1000 <= y <= 2999) or not (1 <= m <= 12):
        return False
    if d is not None and not (1 <= d <= 31):
        return False
    return True


def date(s: str):
    """Normalise the first date in *s*.

    Full dates become ``YYYY-MM-DD``; a year+month without a day becomes
    ``YYYY-MM`` (no invented day); a redacted date whose day is masked to
    ``2021********`` becomes ``YYYY`` — the year is what the document actually
    says, and inventing the rest would be worse than keeping the precision.
    Supports Arabic separators, Chinese numerals and the positional form
    二〇二一年三月五日.
    """
    hit = date_find(s)
    return hit[0] if hit else None


def date_find(s: str, anchor: int | None = None):
    """Like :func:`date` but returns ``(value, (start, end))``.

    ``anchor`` is a character index (a hint or label position). The match
    closest to it wins over a *more complete* match far away: a header reading
    ``2021.03****`` next to 裁判日期 is the judgment date even though the body
    later mentions a full ``1988 年7 月11 日``. Ranking by completeness first
    silently returned the wrong year, which then looks like a data problem.
    """
    if s is None:
        return None
    text = str(s)
    hits = []
    for pattern, kind in ((_DATE_ARABIC, "full"), (_DATE_CN, "full"),
                          (_DATE_MONTH, "month")):
        for m in pattern.finditer(text):
            value = None
            if kind == "full":
                if pattern is _DATE_CN:
                    y, mo, d = (_cn_integer(m.group(i)) for i in (1, 2, 3))
                    if None not in (y, mo, d) and _valid(y, mo, d):
                        value = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
                else:
                    y, mo, d = (int(m.group(i)) for i in (1, 2, 3))
                    if _valid(y, mo, d):
                        value = f"{y:04d}-{mo:02d}-{d:02d}"
            else:
                y, mo = int(m.group(1)), int(m.group(2))
                if _valid(y, mo):
                    value = f"{y:04d}-{mo:02d}"
            if value:
                hits.append((value, m.span()))
    for m in _DATE_REDACTED.finditer(text):
        year = int(m.group(1))
        if 1000 <= year <= 2999:
            hits.append((f"{year:04d}", m.span()))
    if not hits:
        return None
    # Deterministic order before any selection: the three patterns are scanned
    # one after another, so without this a "month" hit found in pass 3 would
    # outrank an earlier full date in the document.
    hits.sort(key=lambda h: h[1][0])
    if anchor is None:
        return hits[0]
    return min(hits, key=lambda h: (abs(h[1][0] - anchor), -len(h[1])))[:2]


# --------------------------------------------------------------------------
# key / value blocks
# --------------------------------------------------------------------------

_SEP_CHARS = "：:"


def _label_pattern(label: str) -> str:
    """Label with optional whitespace between its characters.

    A form may be printed one character per line (案\\n号：...), so every gap
    must be allowed. The colon is required immediately after, which is what
    keeps a stray character elsewhere in the page from matching.
    """
    return r"\s*".join(re.escape(ch) for ch in label if not ch.isspace())


def kv_block(text: str, labels, max_lines: int = 40, sep: str = _SEP_CHARS):
    """First ``label: value`` hit, value taken from one line only.

    Returns ``(value, (start, end), meta)`` or None. ``meta`` carries
    ``label`` and ``redacted``. Values are never joined across a newline: a
    header block prints one field per line, so crossing the line would swallow
    the next field (this was the most expensive bug of the first round).
    """
    if text is None:
        return None
    if isinstance(labels, str):
        labels = [labels]
    for label in labels or []:
        pattern = _label_pattern(label) + r"\s*[" + sep + r"]"
        m = re.search(pattern, text)
        if not m:
            continue
        rest = text[m.end():]
        line_end = rest.find("\n")
        raw = rest if line_end < 0 else rest[:line_end]
        start = m.end()
        if not raw.strip():
            # Form style with the value on the following line — but only when
            # that line is a value. If it opens with another `label：`, the
            # field is blank and taking the next line would report the next
            # field's text as this field's value (a blank field directly above another
            # one came back holding the second one's text).
            nxt = re.match(r"[ \t]*\n\s*([^\n]+)", rest)
            if not nxt or _LOOKS_LIKE_LABEL.match(nxt.group(1)):
                return ("", (start, start), {"label": label, "redacted": False})
            raw = nxt.group(1)
            start = m.end() + nxt.start(1)
        lead = len(raw) - len(raw.lstrip())
        value = raw.strip()
        start += lead
        end = start + len(value)
        return (value, (start, end),
                {"label": label, "redacted": bool(REDACT_RE.search(value))})
    return None


REDACT_RE = re.compile(r"[*＊×]{2,}")
# `<short label>：…` at the start of a line — a new field, not a value.
_LOOKS_LIKE_LABEL = re.compile(r"^[^\s：:]{1,16}\s*[：:]")


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def _marker_spans(text: str, markers, start: int = 0):
    """All ``(start, end)`` hits for a marker set, whitespace tolerant.

    A marker may be printed one character per line (``判\\n决\\n如\\n下``), so the
    characters are joined by ``\\s*`` instead of being searched literally —
    otherwise every section on such a document silently yields None.
    """
    spans = []
    for marker in markers or []:
        if not marker:
            continue
        for m in re.finditer(_label_pattern(marker), text[start:]):
            spans.append((start + m.start(), start + m.end()))
    spans.sort()
    return spans


def _first_index(text: str, markers, start: int):
    spans = _marker_spans(text, markers, start)
    return spans[0][0] if spans else -1


def section(text: str, start, end=None, after=None, last: bool = True):
    """Slice a section between marker sets.

    ``start`` is matched from the **last** occurrence by default: documents
    often repeat a heading in a running header, and the body is the later one.
    Returns ``(subtext, offset)``; ``(None, -1)`` when the start marker is
    absent.
    """
    if text is None:
        return (None, -1)
    starts = [start] if isinstance(start, str) else list(start)
    cursor = 0
    if after:
        afters = [after] if isinstance(after, str) else list(after)
        idx = _first_index(text, afters, 0)
        if idx >= 0:
            cursor = idx + 1
    spans = [sp for sp in _marker_spans(text, starts, cursor) if sp[0] >= cursor]
    if not spans:
        return (None, -1)
    pos, offset = (spans[-1] if last else spans[0])
    stop = len(text)
    if end:
        ends = [end] if isinstance(end, str) else list(end)
        idx = _first_index(text, ends, offset)
        if idx >= 0:
            stop = idx
    body = text[offset:stop]
    lead = len(body) - len(body.lstrip(" \t\r\n：:"))
    return (body.lstrip(" \t\r\n：:"), offset + lead)


# --------------------------------------------------------------------------
# enumerations
# --------------------------------------------------------------------------

_ITEM_STYLES = {
    "cn_num": re.compile(
        r"(?:^|\n)\s*([一二三四五六七八九十]{1,3})\s*[、.．]"),

    "paren": re.compile(r"(?:^|\n)\s*[（(]\s*([一二三四五六七八九十]+|\d{1,2})\s*[）)]"),
    "dot": re.compile(r"(?:^|\n)\s*(\d{1,2})\s*[.．、](?!\d)"),
    "bullet": re.compile(r"(?:^|\n)\s*[•·▪◦*\-]\s*"),
}


def items(text: str, style: str = "auto"):
    """Split an enumerated list into ``(label, item_text, (start, end))``.

    ``style`` is one of cn_num / paren / dot / bullet, or ``auto`` which tries
    them in that order and keeps the one with the most matches.
    """
    if not text:
        return []
    if style != "auto":
        return _items_with(text, style)
    best = []
    for candidate in ("cn_num", "paren", "dot", "bullet"):
        found = _items_with(text, candidate)
        if len(found) > len(best):
            best = found
    return best


def _items_with(text: str, style: str):
    pattern = _ITEM_STYLES[style]
    marks = list(pattern.finditer(text))
    if not marks:
        return []
    out = []
    for i, m in enumerate(marks):
        start = m.end()
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        label = m.group(1) if m.groups() else str(i + 1)
        out.append((label, text[start:stop].strip(), (start, stop)))
    return out


# --------------------------------------------------------------------------
# evidence window
# --------------------------------------------------------------------------

_SENT_END = "。！？；!?;\n"
_SENT_START = "。！？；!?;\n"


def window(text: str, span, before: int = 80, after: int = 120,
           cap: int = 200):
    """Expand a span to a sentence-bounded, reviewer-checkable snippet.

    Returns ``{"snippet": str, "span": (s, e), "truncated": bool}``. The
    returned span always covers the **whole sentence**, even when the snippet
    itself had to be shortened with an ellipsis, so a reviewer can re-read the
    original text at exactly those offsets.
    """
    if text is None or not span:
        return {"snippet": "", "span": (0, 0), "truncated": False}
    s, e = int(span[0]), int(span[1])
    s = max(0, min(s, len(text)))
    e = max(s, min(e, len(text)))
    lo = max(0, s - before)
    for i in range(s - 1, lo - 1, -1):
        if text[i] in _SENT_START:
            lo = i + 1
            break
    hi = min(len(text), e + after)
    for i in range(e, hi):
        if text[i] in _SENT_END:
            hi = i + 1
            break
    snippet = text[lo:hi]
    truncated = False
    if len(snippet) > cap:
        truncated = True
        keep_from = max(lo, s - cap // 3)
        keep_to = min(hi, keep_from + cap)
        snippet = text[keep_from:keep_to]
        if keep_from > lo:
            snippet = "…" + snippet
        if keep_to < hi:
            snippet = snippet + "…"
    return {"snippet": snippet, "span": (lo, hi), "truncated": truncated}


# --------------------------------------------------------------------------
# negation scope
# --------------------------------------------------------------------------

NEGATION_CUES = ("不予", "不得", "禁止", "尚未", "未曾", "没有", "并非", "未",
                 "无", "非", "驳回", "不")
MULTI_CUES = tuple(c for c in NEGATION_CUES if len(c) > 1)
# A single-character cue inside one of these words is not a negation.  `非法`
# is a charge name and `无偿` is "free of charge": treating them as negation
# silently voids the amount in the very clause that states it.
NON_NEGATING = ("非法", "无偿", "不法", "不断", "不少", "不仅", "不同", "无疑",
                "无论", "非常", "非但", "并非真", "未知", "无数")


def negate(text: str, span, within: int = 12) -> bool:
    """True when the span sits inside a negation scope.

    Only text **before** the span counts: a cue that is the first character of
    the value belongs to the value (``非法占用农用地罪`` must not read as "not").
    The window stops at a clause boundary, because a charge name in the same
    sentence carries "非" and would otherwise poison every amount beside it —
    that leak silently voided 60 % of the fields in the first measurement.
    A clause-opening cue may butt against the span (``不予支持``), so
    multi-character cues are also tested at the span start. Two cues in a row
    cancel (``没有不满意`` is an affirmation).
    """
    if text is None or not span:
        return False
    s = max(0, int(span[0]))
    lo = max(0, s - within)
    head = text[lo:s]
    for cut in "。；;\n，,、":
        idx = head.rfind(cut)
        if idx >= 0:
            head = head[idx + 1:]
            break
    for cue in NEGATION_CUES:
        idx = head.rfind(cue)
        if idx < 0:
            continue
        word = head[idx:idx + len(cue) + 2]
        if any(word.startswith(ok) for ok in NON_NEGATING):
            continue
        tail = head[idx + len(cue):]
        if any(tail.startswith(other) for other in NEGATION_CUES):
            return False
        if any(text.startswith(other, s) for other in NEGATION_CUES):
            return False
        return True
    for cue in MULTI_CUES:
        if text.startswith(cue, s):
            return True
    return False


# --------------------------------------------------------------------------
# vocabulary normalisation and counting
# --------------------------------------------------------------------------

def canon(hits, vocab):
    """Map raw hits onto canonical labels, longest alias first.

    ``hits`` is a sequence of ``(raw, (start, end))``; ``vocab`` maps alias to
    canonical label. Overlapping aliases are resolved by length, then position,
    so ``非法捕捞水产品罪`` never degrades to ``非法捕捞``.
    """
    if not hits or not vocab:
        return []
    if isinstance(vocab, dict):
        pairs = list(vocab.items())
    else:
        pairs = [(str(a), str(b)) for a, b in vocab]
    seen = {}
    for alias, label in pairs:
        if alias in seen and seen[alias] != label:
            # Two categories claiming the same alias would make the answer
            # depend on dict order — silently, and differently per run.
            raise ValueError(f"alias {alias!r} maps to both {seen[alias]!r} and {label!r}")
        seen[alias] = label
    aliases = sorted(pairs, key=lambda kv: -len(kv[0]))
    found = []
    for raw, span in hits:
        text = raw if isinstance(raw, str) else str(raw)
        best = None
        for alias, label in aliases:
            if alias and alias in text:
                pos = text.find(alias)
                if best is None or len(alias) > len(best[0]):
                    best = (alias, label, pos)
        if best:
            alias, label, pos = best
            start = (span[0] + pos) if span else pos
            found.append((label, alias, (start, start + len(alias))))
    return found


def count_unique(text: str, pattern: str) -> int:
    """Number of distinct matches of *pattern* in *text*."""
    if not text:
        return 0
    hits = re.findall(pattern, text)
    seen = set()
    for hit in hits:
        if isinstance(hit, tuple):
            hit = next((h for h in hit if h), "")
        seen.add(hit)
    return len(seen)


# --------------------------------------------------------------------------
# two trivial field kinds
# --------------------------------------------------------------------------

def pattern(text: str, regex: str, group: int = 0):
    """First regex match; returns ``(value, (start, end))`` or None.

    A capture group that did not participate in the match falls back to the
    whole match instead of silently returning None.
    """
    m = re.search(regex, text or "")
    if not m:
        return None
    try:
        value = m.group(group)
        start, end = m.span(group)
    except (IndexError, re.error):
        value = m.group(0)
        start, end = m.span(0)
    if value is None:
        value = m.group(0)
        start, end = m.span(0)
    return (value.strip(), (start, end))


def contains(text: str, needle, exclude: str = None):
    """Substring search as a boolean field with its span.

    *needle* may be a list, or a single string whose alternatives are separated
    by ``|`` — that is how a person writes "any of these words" in a profile,
    and treating the whole string as one literal makes such a field answer
    False for every document while looking perfectly healthy.

    *exclude* is a regex over the whole **line** the match sits on: an
    interviewer's question repeats the respondent's vocabulary, so counting the
    question would make every interview look like a complaint.
    """
    if isinstance(needle, (list, tuple, set)):
        needles = [str(n) for n in needle if str(n)]
    else:
        needles = [part for part in re.split(r"[|｜]", str(needle or "")) if part]
    if not needles:
        return None
    best = None
    for item in needles:
        for m in re.finditer(re.escape(item), text or ""):
            if exclude and _line_hits(text or "", m.start(), exclude):
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), m.end())
            break
    return (True, best) if best else None


# --------------------------------------------------------------------------
# profile handling
# --------------------------------------------------------------------------

RESERVED_COLUMNS = {"rel_path", "file", "doc_type", "title", "chars",
                    "han_chars", "profile", "_row_id"}
FIELD_FUNCS = {"num", "quantity", "date", "duration", "kv_block", "section",
               "items", "window", "negate", "canon", "count_unique",
               "pattern", "contains"}
FIELD_TYPES = {"numeric", "categorical", "text", "date", "count", "bool"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Keys every field may carry, and the extra keys each func actually reads.
# Anything else is a typo that would otherwise be ignored without a word.
_FIELD_KEYS = {"name", "func", "type", "scope", "na", "label", "labels", "hint",
               "start", "fallback", "window", "negate", "redacted_is_na",
               "exclude", "description", "na_negated", "na_redacted",
               "drop_negated"}
_FUNC_KEYS = {
    "num": {"pattern"},
    "quantity": {"unit", "unit_table", "pattern"},
    "date": set(),
    "duration": {"unit", "pattern"},
    "kv_block": set(),
    "section": {"max_items"},
    "items": {"style", "max_items"},
    "window": {"pattern"},
    "negate": {"pattern"},
    "canon": {"vocab", "pattern"},
    "count_unique": {"pattern"},
    "pattern": {"pattern", "group"},
    "contains": {"pattern", "needle"},
}


class ProfileError(ValueError):
    """Raised when a profile JSON does not satisfy the contract."""


def load_profile(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        profile = json.load(fh)
    return validate_profile(profile, path)


def validate_profile(profile: dict, path: str = "<memory>") -> dict:
    if not isinstance(profile, dict):
        raise ProfileError(f"{path}: profile must be a JSON object")
    name = profile.get("profile")
    if not isinstance(name, str) or not name.strip():
        raise ProfileError(f"{path}: missing 'profile' name")
    fields = profile.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ProfileError(f"{path}: 'fields' must be a non-empty list")
    seen = set()
    for i, field in enumerate(fields):
        where = f"{path}: fields[{i}]"
        if not isinstance(field, dict):
            raise ProfileError(f"{where} must be an object")
        fname = field.get("name")
        if not isinstance(fname, str) or not NAME_RE.match(fname):
            raise ProfileError(f"{where}: bad name {fname!r} (want ^[a-z][a-z0-9_]*$)")
        if fname in RESERVED_COLUMNS:
            raise ProfileError(f"{where}: {fname!r} is a reserved column")
        if fname in seen:
            raise ProfileError(f"{where}: duplicate field name {fname!r}")
        seen.add(fname)
        func = field.get("func")
        if func not in FIELD_FUNCS:
            raise ProfileError(f"{where}: func must be one of {sorted(FIELD_FUNCS)}")
        if field.get("type") not in FIELD_TYPES:
            raise ProfileError(f"{where}: type must be one of {sorted(FIELD_TYPES)}")
        if not field.get("na"):
            raise ProfileError(
                f"{where}: 'na' phrase is required — an empty string cannot "
                f"distinguish 'not mentioned' from 'not applicable'")
        scope = field.get("scope", "full")
        sections = profile.get("sections") or {}
        if scope != "full" and scope != "head" and scope not in sections:
            raise ProfileError(
                f"{where}: scope {scope!r} is not a declared section "
                f"({sorted(sections)})")
        if func == "kv_block" and not (field.get("labels") or field.get("label")):
            raise ProfileError(f"{where}: kv_block needs 'labels' or 'label'")
        if func == "pattern" and not field.get("pattern"):
            raise ProfileError(f"{where}: pattern needs 'pattern'")
        if func == "canon" and not field.get("vocab"):
            raise ProfileError(f"{where}: canon needs 'vocab'")
        if func == "quantity" and not field.get("unit"):
            raise ProfileError(f"{where}: quantity needs 'unit'")
        stray = sorted(set(field) - _FIELD_KEYS - _FUNC_KEYS.get(func, set()))
        if stray:
            # A key the chosen func never reads is a typo or a leftover: the
            # field then silently ignores what the author obviously meant
            # (`pattern` on a kv_block field). Refuse instead of guessing.
            raise ProfileError(
                f"{where}: key(s) {stray} are not used by func {func!r} "
                f"(allowed: {sorted(_FIELD_KEYS | _FUNC_KEYS.get(func, set()))})")
    return profile


def profile_sha256(path: str) -> str:
    import hashlib
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _scope_text(text: str, scope: str, sections: dict):
    if scope in (None, "full"):
        return text, 0
    spec = (sections or {}).get(scope) or {}
    if scope == "head":
        lines = spec.get("lines", 40) if spec else 40
        if spec and spec.get("start"):
            return section(text, spec["start"], spec.get("end"))
        out, idx = [], 0
        for line in text.splitlines(keepends=True):
            if len(out) >= lines:
                break
            out.append(line)
            idx += len(line)
        return "".join(out), 0
    if spec.get("start"):
        body, offset = section(text, spec["start"], spec.get("end"),
                               after=spec.get("after"),
                               last=spec.get("last", True))
        if body is None:
            return None, -1
    elif spec.get("lines"):
        body, offset = text, 0
    else:
        return text, 0
    limit = spec.get("lines")
    if limit:
        kept = body.splitlines(keepends=True)[: int(limit)]
        body = "".join(kept)
    return body, offset


def _coerce(value, ftype: str):
    if value is None:
        return None
    if ftype in ("numeric",):
        number = float(value) if not isinstance(value, bool) else float(value)
        if number.is_integer() and abs(number) < 1e15:
            return int(number)
        return number
    if ftype == "count":
        return int(value)
    if ftype == "bool":
        return bool(value)
    return str(value)


def _vocab_for(field: dict, base_dir: str):
    vocab = field.get("vocab")
    if isinstance(vocab, dict):
        return vocab
    if not isinstance(vocab, str):
        return {}
    candidates = []
    if base_dir:
        candidates.append(os.path.join(base_dir, vocab))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "..", "profiles", vocab))
    candidates.append(os.path.join("profiles", vocab))
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
    raise ProfileError(f"vocab not found: {vocab} (looked in {candidates})")


def _na_phrases(na):
    """Normalise the profile's ``na`` into a list of phrases."""
    if na is None:
        return []
    if isinstance(na, str):
        return [na] if na else []
    return [p for p in na if p]


def _line_hits(text: str, pos: int, pattern: str) -> bool:
    """True when the line containing *pos* matches *pattern*."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    line = text[start:end if end >= 0 else len(text)].strip()
    return bool(re.search(pattern, line))


def _hint_of(field: dict):
    """The anchor a value-finding func searches near.

    ``hint`` is explicit; ``labels``/``label``/``start`` are the natural
    fallbacks, because a profile that names a field ``受访者年龄`` should not
    have to repeat the same words as a hint.
    """
    hint = field.get("hint")
    if hint:
        return hint
    names = field.get("labels") or field.get("label") or field.get("start")
    if isinstance(names, str):
        names = [names]
    names = [n for n in (names or []) if n]
    return "|".join(names) or None


def _hint_regex(hint: str) -> str:
    """Compile an ``a|b`` hint into one regex, tolerating per-character lines."""
    alt = []
    for part in str(hint).split("|"):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9]+", part):
            alt.append(_label_pattern(part))     # tolerant of per-char lines
        else:
            alt.append(part)
    return "|".join(alt) or re.escape(str(hint))


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    """Start/end offsets of the line containing *pos* (end excludes newline)."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, (end if end >= 0 else len(text))


def _hinted(finder, scope_text: str, hint: str, *args, anchor: bool = False,
            line_only: bool = False):
    """Run a span-aware finder inside the windows that match *hint*.

    A document carries many numbers; ``hint`` says which sentence the field is
    about, so ``wait_minutes`` does not pick up the interview duration and
    ``fine_yuan`` does not pick up the amount of the loss. The returned span
    stays absolute inside *scope_text*.

    ``line_only`` keeps the search on the line that carries the label.  A
    header value never lives on the next line; letting it cross that boundary
    is how a missing age picked up the interview date.
    """
    if not hint:
        return finder(scope_text, *args)
    pattern = _hint_regex(hint)
    n = len(scope_text)
    for m in re.finditer(pattern, scope_text):
        # Forward first: the number normally follows the noun ("修复费1250元").
        # Reaching backwards first would grab the amount of the preceding
        # item — in a structured order that is often the unpaid balance.
        if line_only:
            windows = (_line_bounds(scope_text, m.start()),)
        else:
            windows = ((m.start(), min(n, m.end() + 160)),
                       (max(0, m.start() - 160), m.end()))
        for lo, hi in windows:
            if anchor:
                # The hint position *is* the anchor the finder needs: a header
                # line 裁判日期：2021.03**** must win over a full date far away.
                hit = finder(scope_text[lo:hi], *args,
                             anchor=max(0, m.start() - lo))
            else:
                hit = finder(scope_text[lo:hi], *args)
            if hit:
                span = hit[-1]
                shifted = list(hit[:-1]) + [(lo + span[0], lo + span[1])]
                return tuple(shifted)
    return None


def _hinted_all(finder, scope_text: str, hint: str, *args, anchor: bool = False,
                limit: int = 8):
    """Distinct finder hits near every hint occurrence, line hits first.

    Returns ``value..., (start, end), same_line`` tuples.  A caller uses this
    to keep the primary hit and to hand every other plausible reading to the
    review file, instead of silently choosing one.
    """
    if not hint:
        hit = finder(scope_text, *args)
        return [tuple(hit) + (True,)] if hit else []
    pattern = _hint_regex(hint)
    n = len(scope_text)
    out, seen = [], set()
    # Line first, then forward, then backward.  A header value follows its
    # label; a number *before* the label is usually another field (a case
    # number's digits, the previous line's amount), so it is the last resort.
    for mode in ("line", "forward", "backward"):
        for m in re.finditer(pattern, scope_text):
            if mode == "line":
                windows = (_line_bounds(scope_text, m.start()),)
            elif mode == "forward":
                windows = ((m.start(), min(n, m.end() + 160)),)
            else:
                windows = ((max(0, m.start() - 160), m.end()),)
            for lo, hi in windows:
                if anchor:
                    hit = finder(scope_text[lo:hi], *args,
                                 anchor=max(0, m.start() - lo))
                else:
                    hit = finder(scope_text[lo:hi], *args)
                if not hit:
                    continue
                span = hit[-1]
                absolute = (lo + span[0], lo + span[1])
                key = (absolute, repr(hit[:-1]))
                if key in seen:
                    continue
                seen.add(key)
                out.append(tuple(list(hit[:-1]) + [absolute, mode == "line"]))
        if out:
            break       # a nearer pass found readings: farther ones are noise
    return out[:limit]


def _na_on_anchor(scope_text: str, field: dict):
    """First NA phrase on a line that carries one of the field's labels."""
    phrases = _na_phrases(field.get("na"))
    if not phrases:
        return None
    hint = _hint_of(field)
    if not hint:
        return _na_in_scope(scope_text, field)
    pattern = _hint_regex(hint)
    for m in re.finditer(pattern, scope_text):
        lo, hi = _line_bounds(scope_text, m.start())
        line = scope_text[lo:hi]
        for phrase in phrases:
            k = line.find(phrase)
            if k >= 0:
                return phrase, (lo + k, lo + k + len(phrase))
    return None


def _na_in_scope(scope_text: str, field: dict):
    """First NA phrase anywhere in the scope (for body-text fields)."""
    for phrase in _na_phrases(field.get("na")):
        k = scope_text.find(phrase)
        if k >= 0:
            return phrase, (k, k + len(phrase))
    return None


def _na_for_field(scope_text: str, field: dict):
    """NA phrase anchored to the label when there is one, else in the scope."""
    if _hint_of(field):
        return _na_on_anchor(scope_text, field)
    return _na_in_scope(scope_text, field)


def _value_key(value):
    """Identity of a candidate value: 67 and 67.0 are the same reading."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        try:
            return ("num", round(float(value), 10))
        except (TypeError, ValueError):
            pass
    return ("text", str(value))


# How many months one `unit` is worth, for the public `duration` wrapper.
_MONTHS_PER_UNIT = {"月": 1.0, "个月": 1.0, "年": 12.0, "日": 1 / 30.0,
                   "天": 1 / 30.0, "周": 7 / 30.0, "星期": 7 / 30.0,
                   "小时": 1 / 720.0, "分钟": 1 / 43200.0}


def duration_find(s: str, unit: str = "月"):
    """Sum a compound duration into one unit.

    ``二年九个月`` is 33 months, not "9" — reading only the last match is the
    classic silent error for sentences and tenancy. Composite runs are joined
    only when two matches are separated by nothing but spaces or punctuation.
    Returns ``(months, (start, end))`` or None.
    """
    if s is None:
        return None
    text = str(s)
    factor = {"月": 1.0, "个月": 1.0, "年": 12.0, "日": 1 / 30.0,
              "天": 1 / 30.0, "周": 7 / 30.0, "星期": 7 / 30.0,
              "小时": 1 / 720.0, "分钟": 1 / 43200.0}
    parts = list(_DURATION_PART.finditer(text))
    if not parts:
        return None
    total = 0.0
    start, end = parts[0].span()
    for i, m in enumerate(parts):
        head = m.group(1)
        value = _to_float(head) if head[0].isdigit() else _cn_integer(head)
        if value is None:
            continue
        suffix = m.group(2)
        total += float(value) * factor[suffix]
        if i + 1 < len(parts):
            gap = text[m.end():parts[i + 1].start()]
            if gap.strip(" \t、,，零"):
                end = m.end()
                break
            end = parts[i + 1].end()
    return (round(total, 4), (start, end))


def duration(s: str, unit: str = "月"):
    """Compound duration expressed in `unit` (default months).

    `duration_find` always sums into months internally; the `unit` argument
    used to be accepted and ignored, so `duration("三年", unit="年")` returned
    36 (months) while claiming to be years.  Convert here, not in the finder.
    """
    hit = duration_find(s, unit)
    if not hit:
        return None
    months = hit[0]
    per_unit = _MONTHS_PER_UNIT.get(unit)
    if per_unit is None:
        return months
    return round(months / per_unit, 4)


def _apply_one_raw(field: dict, text: str, scope_text: str, offset: int,
                   base_dir: str):
    """Run one field against the scoped text. Returns an un-finalised result."""
    func = field["func"]
    na = field.get("na")
    ftype = field.get("type")
    win_before, win_after = (field.get("window") or [80, 120])[:2]
    result = {"value": None, "raw": None, "span": None,
              "source": "none", "na": na, "negated": False,
              "fallback_used": 0, "truncated": False,
              "candidates": [], "flags": [], "needs_review": False,
              "cross_line": False, "na_hit": False}

    def candidate(value, raw, span, source, note="", same_line=None):
        """Record one plausible reading.  Never overwrites the chosen value."""
        span_abs = None if span is None else [offset + max(0, span[0]),
                                              offset + max(0, span[1])]
        key = (_value_key(value), tuple(span_abs) if span_abs else None)
        for item in result["candidates"]:
            old_key = (_value_key(item["value"]),
                       tuple(item["span"]) if item["span"] else None)
            if old_key == key:
                return item
        item = {"value": value, "raw": raw, "span": span_abs,
                "source": source, "note": note, "same_line": same_line}
        result["candidates"].append(item)
        return item

    def finish(value, raw, span, source, same_line=None):
        result["raw"] = raw
        if span is None:
            result["span"] = None
            result["source"] = source
            if isinstance(value, str) and not value:
                result["value"] = None
                candidate(None, raw, None, source, same_line=same_line)
                return result
            result["value"] = _coerce(value, ftype)
            candidate(result["value"], raw, None, source, same_line=same_line)
            return result
        local = (max(0, span[0]), max(0, span[1]))
        result["span"] = (offset + local[0], offset + local[1])
        result["source"] = source
        if span:
            absolute = result["span"]
            result["negated"] = negate(text, absolute,
                                       int(field.get("negate") or 12))
        if result["negated"] and field.get("drop_negated", True):
            result["value"] = None
            result["na"] = field.get("na_negated") or na
            result["na_hit"] = True
            candidate(None, raw, span, "na", "negated", same_line=same_line)
            return result
        if isinstance(value, str):
            for phrase in _na_phrases(na):
                if phrase and phrase in value:
                    result["value"] = None
                    result["na"] = phrase
                    result["na_hit"] = True
                    candidate(None, raw, span, "na", "na_phrase",
                              same_line=same_line)
                    return result
        result["value"] = _coerce(value, ftype)
        result["truncated"] = bool(span) and (
            result["span"][1] - result["span"][0]) > (win_before + win_after)
        candidate(result["value"], raw, span, source, same_line=same_line)
        return result

    if func == "kv_block":
        hit = kv_block(scope_text, field.get("labels") or [field["label"]])
        if hit:
            value, span, meta = hit
            if meta.get("redacted") and field.get("redacted_is_na", False):
                result["source"] = "kv_block"
                result["span"] = (offset + span[0], offset + span[1])
                result["na"] = field.get("na_redacted") or na
                result["na_hit"] = True
                candidate(None, value, span, "kv_block", "redacted")
                return result
            return finish(value, value, span, "kv_block")
        return result

    if func == "pattern":
        group = int(field.get("group") or 0)
        hit = pattern(scope_text, field["pattern"], group)
        if hit:
            out = finish(hit[0], hit[0], hit[1], "pattern")
            seen = 0
            for m in re.finditer(field["pattern"], scope_text):
                if seen >= 5:
                    break
                span_group = group if group <= (m.lastindex or 0) else 0
                value = m.group(span_group)
                if value is None:
                    continue
                seen += 1
                candidate(value, value, m.span(span_group),
                          "pattern", "alternative")
            return out
        na_hit = _na_for_field(scope_text, field)
        if na_hit:
            result["na_hit"] = True
            return finish(None, na_hit[0], na_hit[1], "na")
        return result

    if func == "contains":
        needle = field.get("needle") or field.get("pattern")
        hit = contains(scope_text, needle, field.get("exclude"))
        if hit:
            return finish(hit[0], needle, hit[1], "contains")
        if scope_text:
            # A declared NA phrase outranks "absent": "未提及" is a missing
            # answer, not a measured False.  Only a real hit outranks NA.
            na_hit = _na_for_field(scope_text, field)
            if na_hit:
                result["na_hit"] = True
                return finish(None, na_hit[0], na_hit[1], "na")
            # The section exists and the phrase is absent: that is a measured
            # False, not a missing value. Returning None here would erase the
            # difference between "no complaint" and "section not found".
            return finish(False, "", None, "absent")
        return result

    if func == "num":
        hint = _hint_of(field)
        hit = _hinted(num_find, scope_text, hint, line_only=True)
        same = True
        if not hit:
            na_hit = _na_for_field(scope_text, field)
            if na_hit:
                result["na_hit"] = True
                out = finish(None, na_hit[0], na_hit[1], "na")
                for alt in _hinted_all(num_find, scope_text, hint):
                    if len(alt) == 3:
                        value, span, line_hit = alt
                        candidate(value, scope_text[span[0]:span[1]], span,
                                  "num", "rejected_by_na", line_hit)
                return out
            hit = _hinted(num_find, scope_text, hint)
            same = False
        if hit:
            result["cross_line"] = (not same) and bool(hint)
            out = finish(hit[0], scope_text[hit[1][0]:hit[1][1]], hit[1],
                         "pattern", same_line=same if hint else None)
            for alt in _hinted_all(num_find, scope_text, hint):
                if len(alt) == 3:
                    value, span, line_hit = alt
                    candidate(value, scope_text[span[0]:span[1]], span,
                              "num", "alternative", line_hit)
            return out
        return result

    if func == "quantity":
        hint = _hint_of(field)
        qargs = (field.get("unit_table"), field.get("unit"))
        hit = _hinted(quantity_find, scope_text, hint, *qargs, line_only=True)
        kind = "quantity"
        same = True
        if not hit:
            bare = _hinted(num_find, scope_text, hint, line_only=True)
            if bare:
                hit, kind = bare, "num"
                result["unit_inferred"] = True
        if not hit:
            na_hit = _na_for_field(scope_text, field)
            if na_hit:
                result["na_hit"] = True
                out = finish(None, na_hit[0], na_hit[1], "na")
                for alt in _hinted_all(quantity_find, scope_text, hint, *qargs):
                    if len(alt) == 4:
                        value, unit, sp, line_hit = alt
                        candidate(value, scope_text[sp[0]:sp[1]], sp,
                                  "quantity", "rejected_by_na", line_hit)
                for alt in _hinted_all(num_find, scope_text, hint):
                    if len(alt) == 3:
                        value, sp, line_hit = alt
                        candidate(value, scope_text[sp[0]:sp[1]], sp,
                                  "num", "rejected_by_na", line_hit)
                return out
            hit = _hinted(quantity_find, scope_text, hint, *qargs)
            kind, same = "quantity", False
            if not hit:
                bare = _hinted(num_find, scope_text, hint)
                if bare:
                    hit, kind, same = bare, "num", False
                    result["unit_inferred"] = True
        if hit:
            span = hit[2] if kind == "quantity" else hit[1]
            result["cross_line"] = (not same) and bool(hint)
            out = finish(hit[0], scope_text[span[0]:span[1]], span,
                         "pattern" if kind == "quantity" else "label",
                         same_line=same if hint else None)
            for alt in _hinted_all(quantity_find, scope_text, hint, *qargs):
                if len(alt) == 4:
                    value, unit, sp, line_hit = alt
                    candidate(value, scope_text[sp[0]:sp[1]], sp, "quantity",
                              "alternative", line_hit)
            for alt in _hinted_all(num_find, scope_text, hint):
                if len(alt) == 3:
                    value, sp, line_hit = alt
                    candidate(value, scope_text[sp[0]:sp[1]], sp, "num",
                              "alternative", line_hit)
            return out
        return result

    if func == "date":
        hint = _hint_of(field)
        hit = _hinted(date_find, scope_text, hint, anchor=True, line_only=True)
        same = True
        if not hit:
            na_hit = _na_for_field(scope_text, field)
            if na_hit:
                result["na_hit"] = True
                out = finish(None, na_hit[0], na_hit[1], "na")
                for alt in _hinted_all(date_find, scope_text, hint, anchor=True):
                    if len(alt) == 3:
                        value, span, line_hit = alt
                        candidate(value, scope_text[span[0]:span[1]], span,
                                  "date", "rejected_by_na", line_hit)
                return out
            hit = _hinted(date_find, scope_text, hint, anchor=True)
            same = False
        if hit:
            result["cross_line"] = (not same) and bool(hint)
            out = finish(hit[0], scope_text[hit[1][0]:hit[1][1]], hit[1],
                         "pattern", same_line=same if hint else None)
            for alt in _hinted_all(date_find, scope_text, hint, anchor=True):
                if len(alt) == 3:
                    value, span, line_hit = alt
                    candidate(value, scope_text[span[0]:span[1]], span,
                              "date", "alternative", line_hit)
            return out
        return result

    if func == "duration":
        hint = _hint_of(field)
        unit = field.get("unit") or "月"
        hit = _hinted(duration_find, scope_text, hint, unit, line_only=True)
        same = True
        if not hit:
            na_hit = _na_for_field(scope_text, field)
            if na_hit:
                result["na_hit"] = True
                out = finish(None, na_hit[0], na_hit[1], "na")
                for alt in _hinted_all(duration_find, scope_text, hint, unit):
                    if len(alt) == 3:
                        value, span, line_hit = alt
                        candidate(value, scope_text[span[0]:span[1]], span,
                                  "duration", "rejected_by_na", line_hit)
                return out
            hit = _hinted(duration_find, scope_text, hint, unit)
            same = False
        if hit:
            result["cross_line"] = (not same) and bool(hint)
            out = finish(hit[0], scope_text[hit[1][0]:hit[1][1]], hit[1],
                         "pattern", same_line=same if hint else None)
            for alt in _hinted_all(duration_find, scope_text, hint, unit):
                if len(alt) == 3:
                    value, span, line_hit = alt
                    candidate(value, scope_text[span[0]:span[1]], span,
                              "duration", "alternative", line_hit)
            return out
        return result

    if func == "count_unique":
        value = count_unique(scope_text, field["pattern"])
        if value is not None and scope_text:
            m = re.search(field["pattern"], scope_text)
            span = m.span() if m else (0, min(1, len(scope_text)))
            return finish(value, str(value), span, "count")
        return result

    if func == "canon":
        vocab = _vocab_for(field, base_dir)
        exclude = field.get("exclude")
        hits = []
        for alias in sorted(vocab, key=len, reverse=True):
            if not alias:
                continue
            for m in re.finditer(re.escape(alias), scope_text):
                if exclude and _line_hits(scope_text, m.start(), exclude):
                    # An interviewer's question repeats the vocabulary of the
                    # answer; counting the question scores the asker, not the
                    # respondent.
                    continue
                hits.append((alias, m.span()))
        # "不满意" contains "满意": the longer span is the reading, the
        # substring is not a second opinion.  Without this filter every
        # negated answer looked like an ambiguity between two categories.
        hits.sort(key=lambda item: (item[1][0], -(item[1][1] - item[1][0])))
        kept_hits = []
        for alias, span in hits:
            if any(start <= span[0] and span[1] <= end
                   for _alias, (start, end) in kept_hits):
                continue
            kept_hits.append((alias, span))
        found = canon(kept_hits, vocab)
        if found:
            label, raw, span = found[0]
            out = finish(label, raw, span, "vocab")
            for other_label, other_raw, other_span in found[1:]:
                candidate(other_label, other_raw, other_span, "vocab",
                          "alternative")
            return out
        na_hit = _na_for_field(scope_text, field)
        if na_hit:
            result["na_hit"] = True
            return finish(None, na_hit[0], na_hit[1], "na")
        return result

    if func == "items":
        parsed = items(scope_text, field.get("style") or "auto")
        if parsed:
            limit = int(field.get("max_items") or 0)
            kept = parsed[:limit] if limit else parsed
            value = len(kept)
            start, end = kept[0][2]
            return finish(value, str(value), (start, end), "count")
        return result

    if func == "section":
        body, offset = section(scope_text, field.get("start") or field.get("label"),
                               field.get("end"), after=field.get("after"))
        if body:
            return finish(body, body[:80], (offset, offset + len(body)), "pattern")
        return result

    if func == "window":
        win = window(scope_text, (0, len(scope_text)),
                     int(field.get("before") or 80),
                     int(field.get("after") or 120))
        if win["snippet"]:
            return finish(win["snippet"], win["snippet"], win["span"], "pattern")
        return result

    return result


#: Parameters a func cannot run without; used to reject impossible fallbacks.
def _finalize(result: dict) -> dict:
    """Derive review flags from the candidate set.  Never changes the value."""
    values = []
    for item in result.get("candidates") or []:
        value = item.get("value")
        if value is None:
            continue
        key = _value_key(value)
        if key not in values:
            values.append(key)
    flags = result.setdefault("flags", [])
    if result.get("cross_line") and (result.get("scope") or "full") == "header":
        flags.append("cross_line_header")
    if result.get("na_hit") and values:
        flags.append("na_conflict")
    if len(values) > 1:
        flags.append("multiple_values")
    if result.get("value") is None and values:
        flags.append("value_withheld")
    result["needs_review"] = bool(flags)
    return result


def _apply_one(field: dict, text: str, scope_text: str, offset: int,
               base_dir: str):
    """Run one field and attach the review flags derived from its candidates."""
    result = _apply_one_raw(field, text, scope_text, offset, base_dir)
    result["scope"] = field.get("scope", "full")
    return _finalize(result)


_REQUIRED_ARGS = {
    "kv_block": ("labels",),
    "pattern": ("pattern",),
    "contains": ("pattern",),
    "canon": ("vocab",),
    "count_unique": ("pattern",),
    "quantity": ("unit",),
}


def _collapse(snippet: str) -> str:
    """Fold all whitespace runs into one space, so one hit stays one line."""
    return " ".join((snippet or "").split())


def _covers(text: str, span, snippet: str) -> bool:
    """True when *snippet* still contains the text at *span*."""
    if not span:
        return False
    start, end = int(span[0]), int(span[1])
    if end > len(text):
        return False
    inner = _collapse(text[start:end])
    return not inner or inner in _collapse(snippet)


def evidence_line(name: str, snippet: str, span) -> str:
    return f"{name}={_collapse(snippet)}@{int(span[0])}-{int(span[1])}"


def verify_evidence(text: str, line: str) -> bool:
    """True when one ``name=snippet@start-end`` line really points at *text*.

    Whitespace is normalised on both sides before comparing, because the
    snippet is folded onto one line. This is the single implementation: tests
    and auditors must call it instead of re-deriving a check that drifts.
    """
    if not line or "@" not in line:
        return False
    rest = line.split("=", 1)[-1]
    snippet, _, rng = rest.rpartition("@")
    try:
        start, end = (int(x) for x in rng.split("-", 1))
    except ValueError:
        return False
    if start < 0 or end < start or end > len(text):
        return False
    span = _collapse(text[start:end])
    return bool(span) and span in _collapse(snippet)


def apply_profile(profile: dict, text: str, base_dir: str = None) -> dict:
    """Run a validated profile over one document.

    Returns ``{"fields": {name: result}, "evidence": [str]}`` where the
    evidence strings follow the ``name=snippet@start-end`` contract.
    """
    sections = profile.get("sections") or {}
    fields_out = {}
    evidence = []
    for field in profile["fields"]:
        scope = field.get("scope", "full")
        scope_text, offset = _scope_text(text or "", scope, sections)
        if scope_text is None:
            scope_text, offset = "", 0
        result = _apply_one(field, text or "", scope_text, offset, base_dir)
        for attempt, fallback in enumerate(field.get("fallback") or [], start=1):
            if result["value"] is not None:
                break
            if isinstance(fallback, str):
                fallback = {"func": fallback}
            merged = dict(field)
            merged.update(fallback)
            merged.setdefault("na", field["na"])
            merged.setdefault("type", field["type"])
            merged.setdefault("name", field["name"])
            missing = [k for k in _REQUIRED_ARGS.get(merged.get("func"), ())
                       if not merged.get(k)]
            if missing:
                # A fallback that just names a func ("pattern") inherits the
                # original field's parameters; if the original never had one,
                # the retry cannot run — skip it instead of raising KeyError.
                result["fallback_skipped"] = result.get("fallback_skipped", 0) + 1
                continue
            # The fallback may declare its own scope (`charge` looks in the body
            # after failing on the header). Reusing the primary scope_text made
            # such a fallback search the wrong half of the document and return a
            # value from the wrong place — silently.
            retry_scope = merged.get("scope", scope)
            if retry_scope != scope:
                retry_text, retry_offset = _scope_text(text or "", retry_scope,
                                                       sections)
                if retry_text is None:
                    retry_text, retry_offset = "", 0
            else:
                retry_text, retry_offset = scope_text, offset
            retry = _apply_one(merged, text or "", retry_text, retry_offset,
                               base_dir)
            if retry["value"] is not None:
                retry["fallback_used"] = attempt
                result = retry
        fields_out[field["name"]] = result
        if result["value"] is not None and result["span"]:
            win_before, win_after = (field.get("window") or [80, 120])[:2]
            cap = int(win_before or 80) + int(win_after or 120)
            start, stop = result["span"]
            if stop - start > cap:
                # Clip the *evidence* span, not just the snippet, so that
                # text[start:stop] stays a literal substring of the snippet.
                stop = start + cap
                result["span"] = (start, stop)
                result["truncated"] = True
            if result["truncated"]:
                snippet = (text or "")[start:stop] + "…"
            else:
                win = window(text or "", result["span"],
                             int(win_before or 80), int(win_after or 120))
                snippet = win["snippet"] or str(result["raw"])
            # One evidence entry is one line: a raw newline inside a snippet
            # turns a JSONL row into several, and every downstream parser then
            # sees fields it cannot attribute.
            snippet = _collapse(snippet)
            if not _covers(text or "", result["span"], snippet):
                # window() shortens an over-long sentence; when that cut lands
                # inside the span the snippet no longer contains the offset it
                # claims. Fall back to the span itself so the invariant holds:
                # an emitted evidence line always verifies.
                snippet = _collapse((text or "")[start:stop]) + "…"
                result["truncated"] = True
            evidence.append(
                f"{field['name']}={snippet}@{result['span'][0]}-{result['span'][1]}")
    return {"fields": fields_out, "evidence": evidence}