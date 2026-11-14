#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reopen sources and verify every cell of any number of CSV audit views.

Native datasets may have any shape/format; the registry supplies lossless CSV
views and hashes their native artifacts. No model or dataset count is imposed.
Prepare writes pending review tasks, never approvals. Final also requires a
post-build, per-cell source reread attestation bound to the current snapshot.
Semantic truth is not established by a matching quote or an attestation alone.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

VERSION = "1.0.0"


class VerificationError(ValueError):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise VerificationError(f"duplicate JSON key: {k}")
        out[k] = v
    return out


def load_json(path, precise=False, encoding="utf-8-sig"):
    with open(path, encoding=encoding) as stream:
        return json.load(stream, object_pairs_hook=_pairs, parse_float=Decimal if precise else float,
                         parse_constant=lambda x: (_ for _ in ()).throw(
                             VerificationError(f"non-finite JSON number: {x}")))


def load_jsonl(path, precise=False, encoding="utf-8-sig"):
    rows = []
    with open(path, encoding=encoding) as stream:
        for i, line in enumerate(stream, 1):
            if line.strip():
                value = json.loads(line, object_pairs_hook=_pairs, parse_float=Decimal if precise else float,
                                   parse_constant=lambda x: (_ for _ in ()).throw(VerificationError(f"non-finite JSON number: {x}")))
                if not isinstance(value, dict):
                    raise VerificationError(f"{path}:{i}: expected object")
                rows.append(value)
    return rows


def read_csv(path, encoding="utf-8-sig", delimiter=","):
    with open(path, encoding=encoding, newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter)
        header = next(reader, [])
        if not header or any(not c.strip() for c in header) or len(set(header)) != len(header):
            raise VerificationError(f"{path}: empty/duplicate CSV column names")
        rows = []
        for i, values in enumerate(reader, 1):
            if len(values) != len(header):
                raise VerificationError(f"{path}: data row {i} has {len(values)} cells, expected {len(header)}")
            rows.append(dict(zip(header, values)))
    return header, rows


def decimal(value):
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise VerificationError(f"not a decimal: {value!r}") from exc
    if not result.is_finite():
        raise VerificationError(f"non-finite decimal: {value!r}")
    return result


def render(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Fraction):
        denominator = value.denominator
        a = b = 0
        while denominator % 2 == 0:
            denominator //= 2
            a += 1
        while denominator % 5 == 0:
            denominator //= 5
            b += 1
        if denominator == 1:
            places = max(a, b)
            numerator = value.numerator * 2 ** (places - a) * 5 ** (places - b)
            sign = "-" if numerator < 0 else ""
            digits = str(abs(numerator)).zfill(places + 1)
            return sign + (digits[:-places] + "." + digits[-places:] if places else digits)
    return str(value)


def key_tuple(value):
    return tuple(render(v) for v in value) if isinstance(value, list) else (render(value),)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise VerificationError("review timestamp must include a timezone")
    return result


def source_equal(actual, declared):
    """Preserve JSON decimal precision instead of comparing rounded floats."""
    if isinstance(actual, bool) or isinstance(declared, bool):
        return type(actual) is type(declared) and actual == declared
    if isinstance(actual, (int, float, Decimal)) and isinstance(declared, (int, float, Decimal)):
        return decimal(actual) == decimal(declared)
    if isinstance(actual, dict) and isinstance(declared, dict):
        return actual.keys() == declared.keys() and all(source_equal(v, declared[k]) for k, v in actual.items())
    if isinstance(actual, list) and isinstance(declared, list):
        return len(actual) == len(declared) and all(source_equal(a, b) for a, b in zip(actual, declared))
    return type(actual) is type(declared) and actual == declared


class Verifier:
    def __init__(self, registry_path, root, adapters=()):
        self.root = Path(root).resolve()
        self.registry_path = self.path(registry_path)
        self.registry = load_json(self.registry_path)
        self.issues, self.traces, self.datasets = [], [], {}
        self.records, self.cells, self.done, self.active = {}, {}, {}, set()
        self.cache, self.bindings, self.adapters = {}, {}, {}
        self.bind(self.registry_path)
        self.bind(Path(__file__).resolve())
        for item in adapters:
            name, sep, path = item.partition("=")
            if not sep or not name or name in self.adapters:
                raise VerificationError("--adapter must be a unique name=path.py")
            full = self.path(path)
            spec = importlib.util.spec_from_file_location(f"research_adapter_{name}", full)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.adapters[name] = module
            self.bind(full)

    def path(self, path):
        p = Path(path)
        return p.resolve() if p.is_absolute() else (self.root / p).resolve()

    def bind(self, path, expected=None):
        full = self.path(path)
        actual = self.bindings.get(str(full)) or sha256(full)
        if expected is not None and (not isinstance(expected, str) or actual != expected):
            raise VerificationError(f"source/artifact SHA256 changed or missing: {path}")
        self.bindings[str(full)] = actual
        return full

    def issue(self, check, where, detail):
        self.issues.append({"severity": "error", "check": check, "where": where, "detail": str(detail)})

    def cached(self, key, fn):
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]

    def source(self, source):
        if not isinstance(source, dict) or not source.get("sha256"):
            raise VerificationError("each source needs path, SHA256, locator and exact raw value")
        full = self.bind(source["path"], source["sha256"])
        loc = source["locator"]
        kind = loc["type"]
        if kind == "csv":
            encoding, delimiter = loc.get("encoding", "utf-8-sig"), loc.get("delimiter", ",")
            header, rows = self.cached((str(full), kind, encoding, delimiter),
                                       lambda: read_csv(full, encoding, delimiter))
            row = loc["row"]
            if isinstance(row, bool) or not isinstance(row, int) or row < 1 or row > len(rows):
                raise VerificationError("CSV locator row must be a 1-based data row")
            if loc["column"] not in header:
                raise VerificationError(f"source column missing: {loc['column']}")
            value = rows[row - 1][loc["column"]]
        elif kind in {"json", "jsonl"}:
            if kind == "json":
                value = self.cached((str(full), kind,loc.get("encoding")), lambda: load_json(full, precise=True,encoding=loc.get("encoding","utf-8-sig")))
            else:
                data = self.cached((str(full), kind,loc.get("encoding")), lambda: load_jsonl(full, precise=True,encoding=loc.get("encoding","utf-8-sig")))
                row = loc["row"]
                if isinstance(row, bool) or not isinstance(row, int) or row < 1 or row > len(data):
                    raise VerificationError("JSONL locator row out of range")
                value = data[row - 1]
            pointer = loc["pointer"]
            if pointer and not pointer.startswith("/"):
                raise VerificationError("JSON pointer must be empty or start with /")
            for token in pointer.split("/")[1:]:
                token = token.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    if not token.isdigit() or int(token) >= len(value):
                        raise VerificationError("JSON array pointer out of range")
                    value = value[int(token)]
                else:
                    value = value[token]
        elif kind == "text":
            def get_text():
                if "page" in loc:
                    import fitz
                    with fitz.open(full) as pdf:
                        page = loc["page"]
                        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= len(pdf):
                            raise VerificationError("PDF page out of range")
                        return pdf[page - 1].get_text()
                if loc.get("encoding"):
                    return full.read_bytes().decode(loc["encoding"],errors="strict")
                from text_extract import extract_text
                import text_extract
                self.bind(text_extract.__file__)
                return extract_text(str(full))
            text = self.cached((str(full), kind, loc.get("page"),loc.get("encoding")), get_text)
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            start, end = loc["start"], loc["end"]
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end)) or not 0 <= start < end <= len(text):
                raise VerificationError("text span out of range")
            value = text[start:end]
        elif kind == "ooxml":
            import zipfile
            import xml.etree.ElementTree as ET
            W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            with zipfile.ZipFile(full) as package:
                root = ET.fromstring(package.read(loc["part"]))
            if loc.get("element_id") is not None:
                candidates = [node for node in root.iter() if node.tag == loc["element"] and node.get(W+"id") == str(loc["element_id"])]
                if len(candidates) != 1:
                    raise VerificationError("OOXML native ID is absent or ambiguous")
                element = candidates[0]
            else:
                element = root if root.tag == loc.get("element") else list(root)[loc["index"]]
            value = "".join(node.text or "" for node in element.iter() if node.tag.endswith("}t"))
        elif kind == "xlsx":
            import openpyxl
            workbook = openpyxl.load_workbook(full, read_only=True, data_only=False)
            try:
                cell = workbook[loc["sheet"]][loc["cell"]]
                if cell.data_type == "f":
                    raise VerificationError("formula source requires independent recomputation, not a cached Excel value")
                value = cell.value
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
            finally:
                workbook.close()
        elif kind == "metadata":
            if loc["field"] == "name":
                value = full.name
            elif loc["field"] == "relative_path":
                value = full.relative_to(self.root).as_posix()
            else:
                raise VerificationError("metadata locator field must be name or relative_path")
        elif kind == "custom":
            module = self.adapters.get(loc.get("adapter"))
            if module is None:
                raise VerificationError("custom locator needs an explicitly supplied --adapter")
            value = module.read_source(full, loc)
        else:
            raise VerificationError(f"unknown locator type: {kind}; supply an adapter for other formats")
        if loc.get("number_as_text") and isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            value = str(value)
        if "raw" not in source or not source_equal(value, source["raw"]):
            raise VerificationError(f"raw evidence differs from reopened source: {source['path']} {loc}")
        return value

    def transform(self, rule, values):
        op = rule.get("op", "identity")
        if op == "identity":
            if len(values) != 1:
                raise VerificationError("identity needs exactly one source")
            return values[0]
        if op == "strip":
            if len(values) != 1:
                raise VerificationError("strip needs one source")
            return render(values[0]).strip()
        if op == "map":
            if len(values) != 1 or render(values[0]) not in rule["mapping"]:
                raise VerificationError("map needs one source and an explicit matching key; no default")
            return rule["mapping"][render(values[0])]
        if op == "join":
            return rule.get("separator", "").join(render(v) for v in values)
        if op == "count":
            return len(values)
        if op == "custom":
            module = self.adapters.get(rule.get("adapter"))
            if module is None:
                raise VerificationError("custom transform needs an explicitly supplied --adapter")
            return module.recompute(rule, values)
        nums = [Fraction(decimal(v)) for v in values]
        if not nums:
            raise VerificationError(f"{op} needs nonempty inputs")
        if op == "number" and len(nums) == 1:
            return nums[0]
        if op == "sum":
            return sum(nums, Fraction(0))
        if op == "mean":
            return sum(nums, Fraction(0)) / len(nums)
        if op == "product":
            return math.prod(nums)
        if op == "difference" and len(nums) == 2:
            return nums[0] - nums[1]
        if op == "ratio" and len(nums) == 2:
            return nums[0] / nums[1]
        if op == "scale" and len(nums) == 1:
            return nums[0] * Fraction(decimal(rule["factor"])) + Fraction(decimal(rule.get("offset", 0)))
        raise VerificationError(f"unknown/invalid transformation: {op}")

    def load(self):
        datasets = self.registry.get("datasets")
        if not isinstance(datasets, list) or not datasets:
            raise VerificationError("registry needs a nonempty datasets list")
        for spec in datasets:
            ident = spec["id"]
            if not isinstance(ident, str) or not ident or ident in self.datasets:
                raise VerificationError(f"duplicate/empty dataset id: {ident}")
            if not str(spec.get("unit", "")).strip():
                raise VerificationError(f"{ident}: specify its own observation unit")
            full = self.bind(spec["path"])
            self.bind(spec["codebook"])
            self.bind(spec["provenance"])
            for artifact in spec.get("artifacts", []):
                self.bind(artifact["path"], artifact.get("sha256", ""))
            header, rows = read_csv(full, spec.get("encoding", "utf-8-sig"), spec.get("delimiter", ","))
            if not rows:
                # A legally empty table is allowed only with range evidence:
                # window, denominator, source hash and an actual re-read.
                evidence = self._empty_evidence(ident)
                if evidence is None and not self.v2_enabled():
                    raise VerificationError(f"{ident}: empty dataset")
                self.datasets[ident] = {"spec": spec, "rows": 0,
                                        "columns": len(header),
                                        "empty_evidence": (evidence or {}).get("id")}
                continue
            keys = spec["key"] if isinstance(spec["key"], list) else [spec["key"]]
            if not keys or len(set(keys)) != len(keys) or any(k not in header for k in keys):
                raise VerificationError(f"{ident}: invalid key columns")
            seen = set()
            for row_no, row in enumerate(rows, 1):
                key = tuple(row[k] for k in keys)
                if any(not x.strip() for x in key) or key in seen:
                    raise VerificationError(f"{ident}: empty/duplicate key {key}")
                seen.add(key)
                for column in header:
                    self.cells[(ident, key, column)] = (row[column], row_no)
            self.datasets[ident] = {"spec": spec, "rows": len(rows), "columns": len(header)}
            for record in load_jsonl(self.path(spec["provenance"])):
                target = (ident, key_tuple(record["key"]), record["column"])
                if record.get("dataset", ident) != ident or target not in self.cells:
                    raise VerificationError(f"{ident}: provenance targets a nonexistent cell: {target}")
                if target in self.records:
                    raise VerificationError(f"duplicate provenance cell: {target}")
                self.records[target] = record

    def verify_cell(self, target):
        if target in self.done:
            if not self.done[target]:
                raise VerificationError(f"dependency failed: {target}")
            return self.cells[target][0]
        if target in self.active:
            raise VerificationError(f"derived-value cycle: {target}")
        self.active.add(target)
        try:
            actual, row_no = self.cells[target]
            record = self.records.get(target)
            if record is None:
                raise VerificationError("cell has no provenance (missing values and identifiers also need records)")
            if "value" not in record or render(record["value"]) != actual:
                raise VerificationError("provenance value differs from dataset cell")
            kind = record["kind"]
            if kind == "observed" and actual == "":
                raise VerificationError("empty observations must be kind=missing with a reason and source context")
            sources = record.get("sources", [])
            values = [self.source(s) for s in sources]
            inputs = record.get("inputs", [])
            generated = kind in {"estimated", "imputed", "simulated"}
            if generated:
                import audit_view
                obligation = audit_view.value_kind_obligations(kind, record)
                if not obligation["ok"] or record.get("rule", {}).get("op") != "custom":
                    raise VerificationError("generated values need method, uncertainty and an explicit recomputation adapter")
            if kind == "derived" or (generated and inputs):
                if not inputs or sources:
                    raise VerificationError("derived cells need input cells, not a replacement raw quote")
                values = []
                for ref in inputs:
                    cell = (ref["dataset"], key_tuple(ref["key"]), ref["column"])
                    if cell not in self.cells:
                        raise VerificationError(f"derived input missing: {cell}")
                    self.verify_cell(cell)
                    if self.records[cell]["kind"] == "missing":
                        raise VerificationError("missing input cannot silently become a computed value")
                    values.append(self.cells[cell][0])
            elif inputs and not generated:
                raise VerificationError("only derived cells may declare inputs")
            if kind in {"observed", "missing", "structural"} and not sources:
                raise VerificationError(f"{kind} cells need at least one source/context anchor")
            if kind == "missing":
                if actual != "" or not str(record.get("reason", "")).strip():
                    raise VerificationError("missing requires an empty cell and an explicit reason")
                expected = ""
            elif kind == "structural":
                if record.get("rule", {}).get("op") != "row_number":
                    raise VerificationError("structural row IDs use row_number; other rules use derived/observed")
                expected = str(row_no)
            elif kind in {"observed", "encoded", "derived", "estimated", "imputed", "simulated", "image_approx"}:
                if kind == "image_approx":
                    import audit_view
                    if not audit_view.value_kind_obligations(kind, record)["ok"]:
                        raise VerificationError("image approximation needs source, calibration method and uncertainty")
                expected = self.transform(record.get("rule", {}), values)
            else:
                raise VerificationError(f"unknown cell kind: {kind}")
            compare = record.get("compare", "exact")
            if compare == "numeric":
                tolerance = decimal(record.get("tolerance", "0"))
                if tolerance < 0 or (tolerance > 0 and not record.get("tolerance_reason")):
                    raise VerificationError("nonzero tolerance needs a recorded rounding/precision reason")
                exact_expected = expected if isinstance(expected, Fraction) else Fraction(decimal(expected))
                matched = abs(Fraction(decimal(actual)) - exact_expected) <= Fraction(tolerance)
            elif compare == "exact":
                matched = actual == render(expected)
            else:
                raise VerificationError("compare must be exact or numeric")
            if not matched:
                raise VerificationError(f"reopened/recomputed value {render(expected)!r} != cell {actual!r}")
            self.done[target] = True
            return actual
        except Exception as exc:
            self.done[target] = False
            self.issue("cell", repr(target), exc)
            raise VerificationError(str(exc)) from exc
        finally:
            self.active.discard(target)

    def prepare(self):
        for name in ("source_unit.jsonl", "audit_view.jsonl", "cell_evidence.jsonl", "units/materials.json"):
            path = self.root / "output/v2" / name
            if path.is_file():
                self.bind(path)
        self.load()
        for target in self.cells:
            try:
                self.verify_cell(target)
            except VerificationError:
                pass
        # Re-hash after opening every source: a file changed during verification
        # cannot receive a successful snapshot.
        for path, old in list(self.bindings.items()):
            if sha256(path) != old:
                self.issue("changed_during_run", path, "input changed during verification")
        if self.v2_enabled():
            self.v2_cells()
        context = digest({"version": VERSION, "bindings": self.bindings})
        for target, (value, _) in self.cells.items():
            ident, key, column = target
            key_out = key[0] if len(key) == 1 else list(key)
            self.traces.append({"dataset": ident, "key": key_out, "column": column,
                                "value": value, "machine_status": "verified" if self.done.get(target) else "error",
                                "evidence": self.records.get(target),
                                "record_sha256": digest({"context": context, "target": [ident, list(key), column],
                                                         "record": self.records.get(target)})})
        return {"schema_version": 1, "created_at": stamp(), "fingerprint": context,
                "bindings": self.bindings, "cells": len(self.cells),
                "datasets": {k: {"rows": v["rows"], "columns": v["columns"]}
                             for k, v in self.datasets.items()}}

    def review(self, snapshot_path, current):
        snapshot = load_json(self.path(snapshot_path))
        if snapshot.get("fingerprint") != current["fingerprint"] or snapshot.get("cells") != len(self.cells):
            self.issue("stale_snapshot", str(snapshot_path), "dataset, sources, codebook, provenance or adapter changed; prepare again")
            return
        started = parse_time(snapshot["created_at"])
        if started > datetime.now(timezone.utc):
            raise VerificationError("snapshot timestamp is in the future")
        expected = {(r["dataset"], key_tuple(r["key"]), r["column"]): r for r in self.traces}
        for ident, info in self.datasets.items():
            reviews = load_jsonl(self.path(info["spec"]["review"]))
            seen = set()
            for record in reviews:
                target = (ident, key_tuple(record["key"]), record["column"])
                if record.get("dataset", ident) != ident or target not in expected or target in seen:
                    self.issue("review_target", repr(target), "duplicate/nonexistent/wrong-dataset review")
                    continue
                seen.add(target)
                try:
                    if record.get("record_sha256") != expected[target]["record_sha256"]:
                        raise VerificationError("review belongs to different data/evidence")
                    if record.get("status") != "verified" or record.get("source_reread") is not True:
                        raise VerificationError("each cell needs a source reread; pending/rejected is not approved")
                    if not str(record.get("reviewer", "")).strip() or not str(record.get("note", "")).strip():
                        raise VerificationError("reviewer and source/context check note are required")
                    if record.get("method") not in {"source_reread", "independent_reextract"}:
                        raise VerificationError("review method must reopen sources or independently reextract")
                    checked = parse_time(record["checked_at"])
                    if checked < started or checked > datetime.now(timezone.utc):
                        raise VerificationError("review must occur after prepare and not in the future")
                except Exception as exc:
                    self.issue("review", repr(target), exc)
            for target in expected:
                if target[0] == ident and target not in seen:
                    self.issue("review_missing", repr(target), "cell was not individually reviewed")
        if self.v2_enabled():
            self.v2_review_bound(expected, started)

    # -- optional v2 contract checks -------------------------------------
    def v2_enabled(self):
        """v2 checks run only when a v2 ledger exists (old projects unaffected)."""
        return any((self.root / "output/v2" / name).is_file() for name in
                   ("source_unit.jsonl", "audit_view.jsonl", "cell_evidence.jsonl", "review_event.jsonl"))

    def _v2(self):
        import contract_v2
        return contract_v2.Project(self.root)

    def _empty_evidence(self, dataset: str):
        if not self.v2_enabled():
            return None
        try:
            for rec in self._v2().read("audit_view"):
                data = rec["data"]
                if data.get("dataset") == dataset and \
                        data.get("cell_coverage") == "not_applicable":
                    return rec
        except Exception:                            # noqa: BLE001
            return None
        return None

    def v2_cells(self):
        """Kind obligations, evidence currency and legal-empty-table evidence."""
        import audit_view
        project = self._v2()
        units = {r["id"]: r for r in project.read("source_unit")}
        for target in self.cells:
            ident, key, column = target
            provenance = self.records.get(target)
            if provenance is None:
                self.issue("v2_missing_provenance", repr(target),
                           "cell has no provenance record")
                continue
            where = repr(target)
            kind = provenance.get("kind")
            if kind not in audit_view.VALUE_KINDS:
                self.issue("v2_kind", where,
                           f"unknown cell kind {kind!r}; declare observed/encoded/"
                           f"derived/structural/missing/estimated/imputed/"
                           f"simulated/image_approx")
                continue
            status = audit_view.value_kind_obligations(kind, provenance)
            if not status["ok"]:
                self.issue("v2_obligation", where,
                           f"{kind} cell lacks {', '.join(status['missing'])}; a "
                           f"generated value needs method, uncertainty and inputs")
            for src in provenance.get("sources") or []:
                unit_id = src.get("unit")
                if not unit_id:
                    continue
                unit = units.get(unit_id)
                if unit is None:
                    self.issue("v2_evidence_unit", where,
                               f"source unit {unit_id} does not exist")
                    continue
                if unit["data"].get("source_sha256") != src.get("sha256"):
                    self.issue("v2_evidence_unit", where,
                               f"source unit {unit_id} was built from a different "
                               f"revision than the cell claims")
                if unit["status"] == "partial":
                    if kind != "image_approx":
                        self.issue("v2_partial_evidence", where,
                                   f"unit {unit_id} is only partial (OCR/ASR or a "
                                   f"scan) but the cell is declared {kind}; reread "
                                   f"the original or declare image_approx")
                    elif not src.get("reread"):
                        self.issue("v2_partial_evidence", where,
                                   f"image_approx cell backed by partial unit "
                                   f"{unit_id} without a recorded re-read")
        for ident, info in self.datasets.items():
            if info["rows"]:
                continue
            evidence = project.read("audit_view")
            scoped = [e for e in evidence
                      if e["data"].get("dataset") == ident
                      and e["data"].get("cell_coverage") == "not_applicable"]
            if not scoped:
                self.issue("v2_empty_table", ident,
                           "0-row dataset without range evidence "
                           "(window, denominator, source hash, re-read); an empty "
                           "table is not automatically 'nothing happened'")
                continue
            for rec in scoped:
                data = rec["data"]
                if not data.get("window") or not data.get("denominator"):
                    self.issue("v2_empty_table", ident,
                               "range evidence lacks window/denominator")
                if "%" in str(data.get("cell_coverage")):
                    self.issue("v2_empty_table", ident,
                               "an empty table cannot be reported as 0/0=100%")

    def v2_review_bound(self, expected, started):
        """A review event must belong to this cell and really go back to a source."""
        try:
            import contract_v2
        except Exception as exc:                        # pragma: no cover
            self.issue("v2_contract", "output/v2", exc)
            return
        project = self._v2()
        events = {}
        for rec in project.read("review_event"):
            data = rec["data"]
            if data["dataset"] == "<source-unit>":
                # Source rereads precede integration; they are not cell reviews
                # and cannot discharge the post-integration second pass.
                try:
                    contract_v2.validate_record(rec)
                    unit_id = data["key"][0]
                    unit = project.latest("source_unit", unit_id)
                    if unit is None or not data.get("reviewer") or not data.get("reread_scope"):
                        raise VerificationError("source reread lacks an existing source unit/reviewer/locator")
                    if data.get("source_sha256") and data["source_sha256"] != unit["data"]["source_sha256"]:
                        # Historical source events remain auditable but do not
                        # support the current unit version.
                        continue
                except Exception as exc:
                    self.issue("v2_source_review", rec["id"], exc)
                continue
            key = (data["dataset"], key_tuple(data["key"]), data["column"])
            if parse_time(data["checked_at"]) < started:
                # Historical rows/keys may have been removed. They are retained
                # in the immutable ledger, but cannot discharge this snapshot.
                # The current review file still has to cover every current cell.
                continue
            if key not in events or (parse_time(data["checked_at"]), parse_time(rec["created_at"]), rec["revision"]) > (parse_time(events[key]["data"]["checked_at"]), parse_time(events[key]["created_at"]), events[key]["revision"]):
                events[key] = rec
        for target, rec in events.items():
            if target not in expected:
                self.issue("v2_review_event", repr(target),
                           "review event points at a cell that does not exist")
                continue
            try:
                contract_v2.validate_record(
                    rec, reader=contract_v2.Reader(
                        "verify_dataset", VERSION, contract_v2.SCHEMA_VERSION,
                        set(contract_v2.FEATURES)))
            except Exception as exc:
                self.issue("v2_review_event", repr(target), exc)
                continue
            if rec["data"]["record_sha256"] != expected[target]["record_sha256"]:
                self.issue("v2_review_event", repr(target),
                           "review event belongs to a different revision of the cell")
            if (rec["data"].get("outcome") != "confirmed" or
                    str(rec["data"].get("second_pass", {}).get("value")) != str(self.cells[target][0])):
                self.issue("v2_review_event", repr(target),
                           "latest second pass is disputed or does not confirm the current value; an older verified line cannot override it")
            if parse_time(rec["data"]["checked_at"]) < started:
                self.issue("v2_review_event", repr(target),
                           "review event precedes the verification snapshot")
            if rec["data"].get("independence") not in (
                    "independent_of_first_pass", "same_agent_reread",
                    "independent_of_ocr", "independent_of_asr"):
                self.issue("v2_review_event", repr(target),
                           f"declared independence {rec['data'].get('independence')!r} "
                           f"does not show how a shared error was avoided")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_final_report(registry_path, root, report_path, adapters=()):
    """Revalidate a final receipt against current sources AND current reviews."""
    verifier = Verifier(registry_path, root, adapters)
    current = verifier.prepare()
    report = load_json(verifier.path(report_path))
    if (verifier.issues or report.get("stage") != "final" or report.get("status") != "verified"
            or report.get("error_count") != 0 or report.get("fingerprint") != current["fingerprint"]):
        raise VerificationError("dataset final review is missing, failed or stale")
    snapshot_path = verifier.path(report["snapshot_path"])
    if sha256(snapshot_path) != report.get("snapshot_sha256"):
        raise VerificationError("verification snapshot changed")
    verifier.review(snapshot_path, current)
    expected_reviews = {str(verifier.path(v["spec"]["review"])) for v in verifier.datasets.values()}
    recorded = report.get("review_bindings", {})
    if expected_reviews != set(recorded):
        raise VerificationError("final report lacks exact review file bindings")
    for path, expected in recorded.items():
        if sha256(path) != expected:
            raise VerificationError("review changed after final verification")
    if verifier.issues:
        raise VerificationError(f"cell reviews no longer pass: {verifier.issues[:3]}")
    v2_reviews = verifier.root / "output/v2/review_event.jsonl"
    if v2_reviews.is_file() and report.get("v2_review_sha256") != sha256(v2_reviews):
        raise VerificationError("source/cell review events changed after final review")
    return verifier, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--stage", choices=["prepare", "final"], default="prepare")
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--adapter", action="append", default=[], help="explicit trusted name=path.py; hashed into the snapshot")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    verifier = None
    try:
        verifier = Verifier(args.registry, args.root, args.adapter)
        snapshot = verifier.prepare()
        if args.stage == "final":
            if not args.snapshot:
                raise VerificationError("--stage final requires the earlier --snapshot")
            verifier.review(args.snapshot, snapshot)
        else:
            write_json(out / "verification_snapshot.json", snapshot)
            # Separate templates by dataset. Never overwrite a user's completed review.
            for ident in verifier.datasets:
                safe = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:16]
                tasks = [dict(r, status="pending", source_reread=False, reviewer="", method="",
                              checked_at="", note="") for r in verifier.traces if r["dataset"] == ident]
                with open(out / f"review_template_{safe}.jsonl", "w", encoding="utf-8") as stream:
                    for task in tasks:
                        stream.write(json.dumps(task, ensure_ascii=False) + "\n")
        issues = verifier.issues
    except Exception as exc:
        issues = (verifier.issues if verifier else []) + [
            {"severity": "error", "check": "input", "where": args.registry, "detail": str(exc)}]
        snapshot = None
    with open(out / "cell_issues.csv", "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["severity", "check", "where", "detail"])
        writer.writeheader()
        writer.writerows(issues)
    if verifier:
        with open(out / "cell_trace.jsonl", "w", encoding="utf-8") as stream:
            for record in verifier.traces:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    report = {"script_version": VERSION, "stage": args.stage, "generated_at": stamp(),
              "status": "verified" if not issues and args.stage == "final" else "prepared" if not issues else "error",
              "error_count": len(issues), "cell_count": len(verifier.cells) if verifier else 0,
              "fingerprint": snapshot["fingerprint"] if snapshot else None,
              "datasets": snapshot.get("datasets", {}) if snapshot else {},
              "limitations": "Machine matching and review attestations do not establish semantic truth; source context must actually be reread."}
    if verifier and verifier.v2_enabled():
        checks: dict[str, int] = {}
        for item in issues:
            if item["check"].startswith("v2_") or item["check"] in ("review", "review_missing"):
                checks[item["check"]] = checks.get(item["check"], 0) + 1
        report["contract_v2"] = {"enabled": True, "issues_by_check": checks,
                                 "cells_checked": len(verifier.cells)}
        v2_reviews = verifier.root / "output/v2/review_event.jsonl"
        if v2_reviews.is_file():
            report["v2_review_sha256"] = sha256(v2_reviews)
    if verifier and args.stage == "final" and args.snapshot:
        try:
            report["snapshot_path"] = str(verifier.path(args.snapshot))
            report["snapshot_sha256"] = sha256(report["snapshot_path"])
            report["review_bindings"] = {str(verifier.path(v["spec"]["review"])):
                                        sha256(verifier.path(v["spec"]["review"]))
                                        for v in verifier.datasets.values()}
        except (KeyError, OSError):
            pass  # the input/review error is already in cell_issues.csv
    write_json(out / "dataset_verification.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
