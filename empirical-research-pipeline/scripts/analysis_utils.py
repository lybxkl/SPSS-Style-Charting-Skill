# -*- coding: utf-8 -*-
"""Shared helpers for the automatic screening and chart-pack scripts.

Keeping filtering, outcome typing, and binary-label encoding in one place means
the two scripts cannot silently disagree about what N or what outcome is.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

POSITIVE_LABELS = {
    "是": 1, "否": 0, "有": 1, "无": 0, "发生": 1, "未发生": 0,
    "支持": 1, "不支持": 0, "明确支持": 1, "未明确支持": 0,
    "阳性": 1, "阴性": 0, "同意": 1, "不同意": 0,
    "yes": 1, "no": 0, "true": 1, "false": 0, "y": 1, "n": 0,
}

ID_PATTERN = re.compile(r"(^id$|^file$|^path$|^relpath$|_id$|^case_?no$)", re.I)
CSV_ENCODINGS = ("utf-8-sig", "gb18030", "big5")


def read_csv_auto(path: str, **kwargs):
    """Read a CSV, trying the encodings common in Chinese research data."""
    last_error = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return pd.read_csv(path, **kwargs)


def apply_filter(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, str | None]:
    """Apply filter_query, then filter dict, then the in_analysis default."""
    query = cfg.get("filter_query")
    filt = cfg.get("filter")
    try:
        if query:
            return df.query(query).copy(), query
        if filt:
            missing = [key for key in filt if key not in df.columns]
            if missing:
                raise ValueError(f"filter column(s) not found: {missing}")
            out = df
            for key, value in filt.items():
                out = out[out[key] == value]
            return out.copy(), str(filt)
        if "in_analysis" in df.columns:
            return df[df["in_analysis"] == 1].copy(), "in_analysis == 1"
    except Exception as exc:
        raise ValueError(f"filter failed ({query or filt}): {exc}") from exc
    return df.copy(), None


def encode_binary(series: pd.Series, mapping: dict | None = None):
    """Return (numeric 0/1 Series with NaN preserved, mapping) or (None, {}).

    Numeric 0/1 always works. Explicit `outcome_map` wins. Common Chinese
    labels (是/否, 有/无, 支持/不支持) are recognized; unrecognized two-level
    labels require an explicit map so the positive class is never guessed.
    """
    s = series.copy()
    if mapping:
        table = {str(k).strip(): int(v) for k, v in mapping.items()}
        as_str = s.astype(str).str.strip()
        mapped = as_str.map(table)
        # Preserve missing values instead of turning them into NaN by design.
        mapped[s.isna()] = np.nan
        if mapped.notna().sum() == s.notna().sum() and set(mapped.dropna().unique()) <= {0, 1}:
            return mapped.astype(float), table
        return None, {}

    numeric = pd.to_numeric(s, errors="coerce")
    if numeric.notna().sum() == s.notna().sum():
        if set(numeric.dropna().unique()) <= {0, 1}:
            return numeric.astype(float), {"0": 0, "1": 1}
        return None, {}

    as_str = s.astype(str).str.strip()
    levels = list(dict.fromkeys(as_str.dropna()))
    if len(levels) != 2:
        return None, {}
    table = {}
    for level in levels:
        key = level.strip().lower()
        if key in POSITIVE_LABELS:
            table[level] = POSITIVE_LABELS[key]
    if len(table) == 2 and set(table.values()) == {0, 1}:
        mapped = as_str.map(table)
        mapped[s.isna()] = np.nan
        return mapped.astype(float), table
    return None, {}


def outcome_kind(series: pd.Series, max_categories: int = 12, mapping: dict | None = None):
    """Return (kind, encoded_series_or_original, mapping, message)."""
    encoded, used = encode_binary(series, mapping)
    if encoded is not None:
        return "binary", encoded, used, ""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == series.notna().sum():
        levels = int(numeric.nunique(dropna=True))
        if 2 <= levels <= max_categories:
            return "categorical", numeric, {}, f"outcome has {levels} levels"
        return "continuous", numeric, {}, ""
    levels = int(series.nunique(dropna=True))
    if levels == 2:
        return "unsupported", series, {}, (
            "outcome has two text levels but the positive class is ambiguous; "
            "provide outcome_map, e.g. {\"是\": 1, \"否\": 0}"
        )
    if 3 <= levels <= max_categories:
        return "categorical", series, {}, f"outcome has {levels} text levels"
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
    if an.notna().sum() == a.notna().sum() and bn.notna().sum() == b.notna().sum():
        if an.notna().sum() != bn.notna().sum():
            return False
        return bool((an.fillna(-9.87654321) == bn.fillna(-9.87654321)).all())
    return bool(a.fillna("__NA__").astype(str).equals(b.fillna("__NA__").astype(str)))


def fmt(value, digits: int = 3) -> str:
    try:
        if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
            return ""
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_p(value) -> str:
    try:
        if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
            return ""
        return f"{float(value):.3g}"
    except (TypeError, ValueError):
        return str(value)
