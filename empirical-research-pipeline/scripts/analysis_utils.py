# -*- coding: utf-8 -*-
"""Shared helpers for the automatic screening and chart-pack scripts.

Keeping filtering, outcome typing, and binary-label encoding in one place means
the two scripts cannot silently disagree about what N or what outcome is.

Contract notes (docs/CONTRACTS.md):
- a missing value is never a zero, and never a category;
- a filter that matches no row is an error, not an empty success;
- integer code columns (province codes, ID-like measures) must never be fed to
  a continuous model just because they are numeric.
"""
from __future__ import annotations

import re
import sys

import numpy as np
import pandas as pd

POSITIVE_LABELS = {
    "是": 1, "否": 0, "有": 1, "无": 0, "发生": 1, "未发生": 0,
    "支持": 1, "不支持": 0, "明确支持": 1, "未明确支持": 0,
    "阳性": 1, "阴性": 0, "同意": 1, "不同意": 0,
    "yes": 1, "no": 0, "true": 1, "false": 0, "y": 1, "n": 0,
}

# Prefixes that turn a positive label into its negative counterpart. Used to
# expand POSITIVE_LABELS on demand (支持/不予支持, 已发生/未发生, 修复/未修复)
# instead of enumerating every variant by hand.
NEGATION_PREFIXES = ("不予", "不应", "不宜", "未", "没有", "无", "非", "不")

# Missing-value sentinels that must be normalised to NaN before a column is
# typed. One "N/A" must not push a whole numeric column into text.
MISSING_SENTINELS = {
    "", "NA", "N/A", "n/a", "na", "null", "NULL", "None", "none",
    "nan", "NaN", "NAN", "-", "—", "－", "缺失",
}

# Columns that are identifiers, provenance or evidence, never model variables.
ID_PATTERN = re.compile(
    r"(^id$|^file$|^path$|^rel_path$|^relpath$|_id$|^case_?no$"
    r"|_src$|_ev$|_note$|_memo$)",
    re.I,
)
CSV_ENCODINGS = ("utf-8-sig", "gb18030", "big5")

# The most frequent Chinese characters, used only to tell a correct legacy
# decoding from mojibake (both decode without error, only one reads as Chinese).
_COMMON_HAN = set(
    "的一是不了人我在有他这为之大来以个中上们到说国和地也子时道出而要于就下得可你年生"
    "自会那后能对着事其里所去行过家十用发天如然作方成者多日都三小军二无同么经法当起与"
    "好看学进种将还分此心前面又定见只主没公从知全现情明力间样已开美再感最利比或但质气"
    "第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员"
    "革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角"
    "期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领"
    "七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打"
    "白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米"
    "整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿"
    "须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消"
    "构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状"
    "育厂京识适属圆包火住调满县局照参红细引听该铁价严龙飞"
)


def _is_missing(value) -> bool:
    """NaN/NaT/pd.NA/None aware scalar check that never raises."""
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(result, (bool, np.bool_)):
        return bool(result)
    return False


def _normalize_missing(series: pd.Series) -> pd.Series:
    """Map common missing-value sentinels to NaN before typing a column."""
    if series.dtype.kind in "biufcMmV":
        return series
    try:
        text = series.astype(object).map(
            lambda value: value.strip() if isinstance(value, str) else value
        )
        return text.mask(text.isin(MISSING_SENTINELS))
    except (TypeError, ValueError):
        return series


def _han_score(df: pd.DataFrame) -> float:
    """Fraction of characters that are frequent Chinese characters.

    Correct Chinese text scores well above mojibake, which decodes into rare
    ideographs or private-use glyphs. ASCII-only files score 0.0.
    """
    total = 0
    common = 0
    texts = [str(column) for column in df.columns]
    for column in df.columns:
        if df[column].dtype == object:
            texts.extend(df[column].dropna().astype(str).head(200).tolist())
    for text in texts:
        for char in text:
            total += 1
            if "\u4e00" <= char <= "\u9fff" and char in _COMMON_HAN:
                common += 1
    return common / total if total else 0.0


def read_csv_auto(path: str, **kwargs):
    """Read a CSV, trying the encodings common in Chinese research data.

    UTF-8 is self-validating and trusted when it decodes. The legacy encodings
    (gb18030, big5) both "succeed" on each other's bytes, so each candidate is
    scored by how much of it reads as frequent Chinese text and the best one
    wins -- otherwise the big5 fallback was unreachable in practice.
    """
    last_error = None
    candidates: list[tuple[float, str, pd.DataFrame]] = []
    for index, encoding in enumerate(CSV_ENCODINGS):
        try:
            frame = pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        if index == 0:
            return frame
        candidates.append((_han_score(frame), encoding, frame))
    if candidates:
        score, encoding, frame = max(candidates, key=lambda item: item[0])
        if score < 0.05 and len(candidates) > 1:
            print(
                f"warning: could not confirm the encoding of {path}; "
                f"using {encoding} (score {score:.3f})",
                file=sys.stderr,
            )
        return frame
    if last_error is not None:
        raise last_error
    return pd.read_csv(path, **kwargs)


def _coerce_filter_value(column: pd.Series, value):
    """Cast a configured filter value to the column dtype (int 1 vs "1")."""
    if isinstance(value, (list, tuple, set, dict)):
        return value
    non_null = column.dropna()
    if non_null.empty:
        return value
    sample = non_null.iloc[0]
    text = str(value).strip()
    try:
        if isinstance(sample, (bool, np.bool_)):
            if text.lower() in {"1", "true", "yes", "y"}:
                return True
            if text.lower() in {"0", "false", "no", "n"}:
                return False
        elif isinstance(sample, (np.integer, int)):
            return int(float(text))
        elif isinstance(sample, (np.floating, float)):
            return float(text)
        elif isinstance(sample, str):
            # Text column: compare as text so 2021 and "2021" agree.
            return text
    except (TypeError, ValueError):
        return value
    return value


def _suggest_columns(name: str, columns) -> list[str]:
    """Columns that look like the one a broken query asked for.

    A config copied from another project fails on a column that does not exist;
    the useful answer is "did you mean in_analysis", not a bare NameError.
    """
    lowered = str(name).lower()
    scored = []
    for col in columns:
        low = str(col).lower()
        if low == lowered:
            score = 0
        elif low.startswith(lowered) or lowered.startswith(low):
            score = 1
        elif lowered in low or low in lowered:
            score = 2
        else:
            continue
        scored.append((score, str(col)))
    return [col for _, col in sorted(scored)[:5]]


def _query_with_hint(df, query):
    """Run ``df.query`` and turn an unknown name into a readable error."""
    try:
        return df.query(query)
    except Exception as exc:
        text = str(exc)
        unknown = re.search(r"name '([^']+)' is not defined", text)
        if unknown:
            name = unknown.group(1)
            hint = _suggest_columns(name, df.columns)
            where = f"did you mean: {', '.join(hint)}" if hint else "no similar column"
            raise ValueError(
                f"filter_query 用到了数据里没有的列 {name!r}（{where}）；"
                f"可用列见数据表头，或删掉该条件"
            ) from exc
        raise


def apply_filter(df: pd.DataFrame, cfg: dict,
                 keep_out_of_scope: bool | None = None
                 ) -> tuple[pd.DataFrame, str | None]:
    """Apply the in_analysis gate, then filter_query / filter, in that order.

    Returns ``(filtered_df, description)``. The description always records the
    row counts before and after, so a report can prove how N was reached.
    A filter that matches zero rows raises ``ValueError`` instead of silently
    returning an empty frame.

    The gate comes first on purpose. Applying a condition such as
    ``{"case_type": "刑事"}`` to the whole file quietly puts out-of-scope rows
    back into the analysis sample (in one real corpus that meant 129 procedural
    rulings, +5%), and nothing in the output said so. ``keep_out_of_scope: true``
    disables the gate; a ``filter_query`` that mentions ``in_analysis`` is
    treated as addressing the flag itself and therefore also skips the gate.
    """
    before = len(df)
    query = cfg.get("filter_query")
    filt = cfg.get("filter")
    has_default = "in_analysis" in df.columns
    keep_out = bool(cfg.get("keep_out_of_scope") if keep_out_of_scope is None
                    else keep_out_of_scope)
    label: str | None = None
    out = df
    gate_rows = None
    if has_default and not keep_out:
        if query and "in_analysis" in str(query):
            pass  # the query addresses the flag, so it is the gate
        elif not query and not filt:
            pass  # the plain default below already does it
        else:
            out = df[df["in_analysis"] == 1]
            gate_rows = len(out)
            if gate_rows == 0:
                raise ValueError(
                    "in_analysis gate left 0 rows: every row is marked out of "
                    "scope (in_analysis != 1); set keep_out_of_scope to analyse "
                    "the whole file"
                )
    try:
        if query:
            out = _query_with_hint(out, query)
            label = str(query)
        elif filt:
            missing = [key for key in filt if key not in df.columns]
            if missing:
                raise ValueError(f"filter column(s) not found: {missing}")
            for key, value in filt.items():
                cast = _coerce_filter_value(out[key], value)
                if isinstance(cast, (list, tuple, set)):
                    out = out[out[key].isin(list(cast))]
                else:
                    out = out[out[key] == cast]
            label = str(filt)
        elif has_default and gate_rows is None:
            out = df[df["in_analysis"] == 1]
            label = "in_analysis == 1"
        elif gate_rows is not None:
            label = "in_analysis == 1"
        else:
            return df.copy(), None
        out = out.copy()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"filter failed ({query or filt}): {exc}") from exc

    if query or filt:
        gate = f"in_analysis gate {before}→{gate_rows}; " if gate_rows is not None else (
            "in_analysis kept (keep_out_of_scope); " if keep_out else ""
        )
        print(f"filter: {gate}{label} → {len(out)} rows", file=sys.stderr)
    if len(out) == 0:
        raise ValueError(
            f"filter {label} matched 0 of {before} rows; "
            "check the column dtype and the filter values "
            "(e.g. an int column filtered with the string '1')"
        )
    desc = f"{label} ({before}→{len(out)} rows)"
    if gate_rows is not None:
        desc = (f"in_analysis==1 ({before}→{gate_rows}) then "
                f"{label} ({gate_rows}→{len(out)} rows)")
    elif keep_out and has_default and (query or filt):
        # Out-of-scope rows were admitted on purpose; the report must say so, or
        # every downstream N looks like it was drawn from the analysis sample.
        desc += "; in_analysis NOT applied (keep_out_of_scope)"
    return out, desc


def _label_value(label: str) -> int | None:
    """Resolve a binary label to 0/1, expanding the negation prefixes."""
    key = (label or "").strip().lower()
    if key in POSITIVE_LABELS:
        return POSITIVE_LABELS[key]
    for prefix in NEGATION_PREFIXES:
        if key.startswith(prefix) and len(key) > len(prefix):
            base = key[len(prefix):]
            if POSITIVE_LABELS.get(base) == 1:
                return 0
    return None


def _binary_pair(first: str, second: str) -> dict | None:
    """Return {first: 0/1, second: 0/1} for a positive/negative label pair."""
    left, right = first.strip(), second.strip()
    left_value, right_value = _label_value(left), _label_value(right)
    if left_value is not None and right_value is not None:
        if {left_value, right_value} == {0, 1}:
            return {first: left_value, second: right_value}
        return None
    # Generic pair expansion: 修复/未修复, 已发生/未发生, 支持/不予支持, 合规/不合规.
    for positive, negative in ((left, right), (right, left)):
        for prefix in NEGATION_PREFIXES:
            if negative.lower() == prefix + positive.lower() and positive:
                return {positive: 1, negative: 0}
        if positive.startswith("已") and negative.lower() == "未" + positive[1:].lower():
            return {positive: 1, negative: 0}
    return None


def encode_binary(series: pd.Series, mapping: dict | None = None):
    """Return (numeric 0/1 Series with NaN preserved, mapping) or (None, {}).

    Numeric 0/1 always works. Explicit `outcome_map` wins. Common Chinese
    labels (是/否, 有/无, 支持/不支持) and their negation-prefixed variants
    (不予支持, 未修复, 已发生/未发生) are recognized; unrecognized two-level
    labels require an explicit map so the positive class is never guessed.
    An entirely missing column returns ``(None, {})`` -- never a fabricated
    {'0': 0, '1': 1} mapping.
    """
    s = _normalize_missing(series)
    if s.dropna().empty:
        return None, {}

    if mapping:
        table: dict[str, int] = {}
        for key, value in mapping.items():
            try:
                code = int(value)
            except (TypeError, ValueError):
                continue  # ignore unusable map entries instead of crashing
            if code not in (0, 1):
                continue
            table[str(key).strip()] = code
        if not table:
            return None, {}
        as_str = s.astype(str).str.strip()
        mapped = as_str.map(table)
        # Preserve missing values instead of turning them into NaN by design.
        mapped[s.isna()] = np.nan
        if mapped.notna().sum() == s.notna().sum():
            return mapped.astype(float), table
        return None, {}

    numeric = pd.to_numeric(s, errors="coerce")
    if numeric.notna().sum() == s.notna().sum():
        if set(numeric.dropna().unique()) <= {0, 1}:
            return numeric.astype(float), {"0": 0, "1": 1}
        return None, {}

    as_str = s.astype(str).str.strip()
    # Keep missing cells missing: astype(str) would turn NaN into the text "nan"
    # and make a binary column look like it has three levels.
    as_str = as_str.where(s.notna())
    levels = list(dict.fromkeys(as_str.dropna()))
    if len(levels) != 2:
        return None, {}
    table = _binary_pair(levels[0], levels[1])
    if table is None:
        return None, {}
    mapped = as_str.map(table)
    mapped[s.isna()] = np.nan
    if mapped.notna().sum() != s.notna().sum():
        return None, {}
    return mapped.astype(float), table


def is_code_like(series: pd.Series) -> bool:
    """True for an integer code column that must not be treated as continuous.

    Cardinality decides, not the value span, so one and the same column keeps
    the same verdict whatever the sample size: more than 12 levels is not a
    usable categorical variable, and a column whose levels approach one value
    per row is an identifier (province codes 1-31, questionnaire item codes).
    A column carrying real decimals is a measure and is never a code column,
    so genuine continuous variables are unaffected.
    """
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    n = int(len(numeric))
    if n == 0:
        return False
    if not bool((numeric == numeric.round()).all()):
        return False
    levels = int(numeric.nunique())
    if levels > 12:
        return True
    if levels >= 5 and levels >= 0.5 * n:
        return True
    return False


def outcome_kind(
    series: pd.Series,
    max_categories: int = 12,
    mapping: dict | None = None,
    normalize_dtype: bool = False,
):
    """Return (kind, encoded_series_or_original, mapping, message).

    ``normalize_dtype`` is opt-in: when true every categorical outcome is
    returned as text, so two calls of the same kind return the same dtype.
    """
    series = _normalize_missing(series)
    if series.dropna().empty:
        return "unsupported", series, {}, "outcome entirely missing"

    encoded, used = encode_binary(series, mapping)
    if encoded is not None:
        return "binary", encoded, used, ""

    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == series.notna().sum():
        levels = int(numeric.nunique(dropna=True))
        if is_code_like(numeric):
            low, high = int(numeric.min()), int(numeric.max())
            return "unsupported", numeric, {}, (
                f"outcome has {levels} integer code levels in {low}-{high} "
                "(categorical_high_cardinality); a code column is not a "
                "continuous measure - recode it or pass outcome_map"
            )
        if 2 <= levels <= max_categories:
            result = series.astype(str) if normalize_dtype else numeric
            return "categorical", result, {}, f"outcome has {levels} levels"
        return "continuous", numeric, {}, ""

    levels = int(series.nunique(dropna=True))
    if mapping:
        return "unsupported", series, {}, (
            "outcome_map did not cover every non-missing value with a 0/1 "
            f"code; values seen: {sorted(map(str, series.dropna().unique()))}"
        )
    if levels == 2:
        return "unsupported", series, {}, (
            "outcome has two text levels but the positive class is ambiguous; "
            "provide outcome_map, e.g. {\"是\": 1, \"否\": 0}"
        )
    if 3 <= levels <= max_categories:
        result = series.astype(str) if normalize_dtype else series
        return "categorical", result, {}, f"outcome has {levels} text levels"
    return "unsupported", series, {}, (
        f"outcome is non-numeric with {levels} levels; provide outcome_map "
        "or code the outcome numerically"
    )


def is_constant(series: pd.Series) -> bool:
    values = series.dropna()
    return values.empty or values.nunique() <= 1


def is_id_like(name: str, series: pd.Series) -> bool:
    if ID_PATTERN.search(name):
        return True
    non_null = series.dropna()
    if non_null.empty:
        return False
    if series.dtype == object:
        return len(non_null) >= 50 and non_null.nunique() / len(non_null) > 0.95
    numeric = pd.to_numeric(non_null, errors="coerce").dropna()
    if len(numeric) >= 50 and numeric.nunique() / len(numeric) > 0.95:
        rounded = numeric.round()
        if bool((numeric == rounded).all()):
            span = float(rounded.max() - rounded.min() + 1)
            # A dense integer sequence from 0/1 to N is an index, not a measure.
            if span <= len(numeric) * 1.05 and float(rounded.min()) in (0.0, 1.0):
                return True
    return False


def same_values(a: pd.Series, b: pd.Series) -> bool:
    """True when two columns encode the same non-missing values (numeric-aware)."""
    an = pd.to_numeric(a, errors="coerce")
    bn = pd.to_numeric(b, errors="coerce")
    a_numeric = an.notna().sum() == a.notna().sum()
    b_numeric = bn.notna().sum() == b.notna().sum()
    if a_numeric and b_numeric:
        if an.notna().sum() != bn.notna().sum():
            return False
        equal = (an == bn) | (an.isna() & bn.isna())
        return bool(equal.all())
    left = a.astype(object).map(lambda v: "" if _is_missing(v) else str(v))
    right = b.astype(object).map(lambda v: "" if _is_missing(v) else str(v))
    return bool(left.equals(right))


def fmt(value, digits: int = 3) -> str:
    if _is_missing(value):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return ""
    return f"{number:.{digits}f}"


def fmt_p(value) -> str:
    if _is_missing(value):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return ""
    return f"{number:.3g}"
