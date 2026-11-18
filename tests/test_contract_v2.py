# -*- coding: utf-8 -*-
"""v2 record contract: schema, feature negotiation, status machine.

Covers acceptance scenarios A02, A03 (contract half), A44 (precision/rules
surface), A47.
"""
import json
import os
import subprocess
import sys

from _helpers import PYTHON, SCRIPTS, TempCase, run

import contract_v2 as C


def prod(**kw):
    return C.producer_for("test", module_file=os.path.join(SCRIPTS,
                                                          "contract_v2.py"),
                          **kw)


def claim(**over):
    payload = {"claim_type": "fact", "text": "the mean is 4.2",
               "block_id": "b001", "text_fingerprint": "abc", "support": []}
    payload.update(over)
    return C.make_record("claim", "c1", payload, producer=prod())


class TestEnvelope(TempCase):
    def test_hash_covers_payload_and_detects_edit(self):
        rec = claim()
        C.validate_record(rec)
        rec["data"]["text"] = "the mean is 4.3"
        with self.assertRaises(C.IntegrityError):
            C.validate_record(rec)

    def test_canonical_form_keeps_unicode_and_is_order_stable(self):
        a = {"b": 1, "a": "中文"}
        b = {"a": "中文", "b": 1}
        self.assertEqual(C.canonical_json(a), C.canonical_json(b))
        self.assertIn("中文", C.canonical_json(a))
        self.assertNotIn("\\u", C.canonical_json(a))

    def test_missing_envelope_field_rejected(self):
        rec = claim()
        del rec["producer"]
        with self.assertRaises(C.SchemaError):
            C.validate_record(rec)

    def test_wrong_schema_version_is_refused_not_degraded(self):
        rec = claim()
        rec["schema_version"] = 1
        rec["content_hash"] = C._content_hash(rec["kind"], rec["id"],
                                              rec["revision"], rec["data"])
        with self.assertRaises(C.FeatureError):
            C.validate_record(rec)

    def test_unknown_kind_and_status(self):
        rec = claim()
        rec["kind"] = "imaginary"
        with self.assertRaises(C.SchemaError):
            C.validate_record(rec)
        rec2 = claim()
        rec2["status"] = "verified"          # not a claim status
        with self.assertRaises(C.SchemaError):
            C.validate_record(rec2)

    def test_required_payload_field_missing(self):
        payload = {"claim_type": "fact", "text": "x"}
        rec = C.make_record("claim", "c1", payload, producer=prod())
        with self.assertRaises(C.SchemaError):
            C.validate_record(rec)

    def test_strict_mode_flags_undeclared_field(self):
        rec = claim(smuggled="value")
        C.validate_record(rec)                     # tolerated (extension space)
        with self.assertRaises(C.SchemaError):
            C.validate_record(rec, strict=True)

    def test_created_at_needs_offset(self):
        rec = claim()
        rec["created_at"] = "2026-11-14 10:00:00"
        with self.assertRaises(C.SchemaError):
            C.validate_record(rec)


class TestFeatures(TempCase):
    def test_unknown_required_feature_is_a_schema_error(self):
        with self.assertRaises(C.SchemaError):
            C.make_record("claim", "c1", claim()["data"], producer=prod(),
                          requires_features=["telepathy"])

    def test_reader_without_feature_refuses_record(self):
        rec = claim()
        reader = C.Reader(name="old-gate", features=frozenset({"record-v2"}))
        with self.assertRaises(C.FeatureError):
            C.validate_record(rec, reader=reader)
        reader2 = C.Reader(name="old-gate", schema_version=1)
        with self.assertRaises(C.FeatureError):
            C.validate_record(rec, reader=reader2)

    def test_optional_extensions_survive(self):
        rec = C.make_record("claim", "c1", claim()["data"], producer=prod(),
                            extensions={"future": {"x": 1}})
        C.validate_record(rec)
        self.assertEqual(rec["extensions"]["future"], {"x": 1})

    def test_per_kind_required_features_auto_applied(self):
        rec = C.make_record("figure_spec", "f1", {
            "figure_id": "F1", "question": "q", "inputs": [], "denominator": "N=3",
            "unit": "person", "series_declared": [], "elements_observed": {},
            "checks": [], "png": "f1.png", "pdf": "f1.pdf"}, producer=prod())
        self.assertIn("figure-elements", rec["requires_features"])


class TestStatusMachine(TempCase):
    def test_prepared_cannot_jump_to_verified(self):
        rec = C.make_record("cell_evidence", "d1", {
            "dataset": "d", "key": ["k1"], "column": "c", "value": "1",
            "kind": "observed", "sources": []}, producer=prod(),
            status="prepared")
        with self.assertRaises(C.StatusTransitionError):
            C.transition(rec, "verified")

    def test_review_pending_can_verify_and_stale_cannot(self):
        rec = C.make_record("cell_evidence", "d1", {
            "dataset": "d", "key": ["k1"], "column": "c", "value": "1",
            "kind": "observed", "sources": []}, producer=prod(),
            status="review_pending")
        verified = C.transition(rec, "verified", producer=prod())
        self.assertEqual(verified["status"], "verified")
        stale = C.transition(verified, "stale", producer=prod())
        with self.assertRaises(C.StatusTransitionError):
            C.transition(stale, "verified")

    def test_same_status_rerecord_allowed(self):
        rec = C.make_record("claim", "c1", claim()["data"], producer=prod(),
                            status="supported")
        again = C.transition(rec, "supported", producer=prod())
        self.assertEqual(again["revision"], 2)

    def test_ledger_rejects_illegal_transition_and_old_revision(self):
        proj = C.Project(self.tmp)
        r1 = C.make_record("cell_evidence", "d1", {
            "dataset": "d", "key": ["k"], "column": "c", "value": "1",
            "kind": "observed", "sources": []}, producer=prod(),
            status="prepared")
        proj.append("cell_evidence", r1)
        bad = C.make_record("cell_evidence", "d1", r1["data"], producer=prod(),
                            status="verified", revision=2)
        with self.assertRaises(C.StatusTransitionError):
            proj.append("cell_evidence", bad)
        dup = C.make_record("cell_evidence", "d1", r1["data"], producer=prod(),
                            status="prepared", revision=1)
        with self.assertRaises(C.ContractError):
            proj.append("cell_evidence", dup)

    def test_dependency_event_status_vocabulary_is_single(self):
        rec = C.make_record("dependency_event", "e1", {
            "node": "source:a", "event": "created", "detail": {}}, producer=prod())
        with self.assertRaises(C.SchemaError):
            C.transition(rec, "active")      # not a dependency_event status


class TestCli(TempCase):
    def test_v1_registry_is_not_migrated_automatically(self):
        # the v1->v2 migration machinery was removed with the dual-version
        # compat layer: there is no --migrate-v1 entry point any more
        reg = {"schema_version": 1, "datasets": [
            {"id": "d1", "path": "data/d1.csv", "key": ["id"], "unit": "person"}]}
        with open(self.p("research_registry.json"), "w", encoding="utf-8") as fh:
            json.dump(reg, fh)
        out = run("contract_v2.py", "--migrate-v1", "--root", self.tmp)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("nothing was marked verified", out.stdout)
        self.assertFalse(os.path.exists(
            self.p("output", "v2", "migration", "v1_to_v2.json")))

    def test_schema_dump_is_machine_readable(self):
        out = run("contract_v2.py", "--dump-schema",
                  self.p("schema.json"))
        self.assertEqual(out.returncode, 0, out.stderr)
        schema = json.load(open(self.p("schema.json"), encoding="utf-8"))
        self.assertEqual(schema["schema_version"], 2)
        self.assertIn("cell_evidence", schema["kinds"])
        self.assertIn("payload_required", schema["kinds"]["claim"])
        # every declared status must appear in the transition table or be initial
        for kind, spec in schema["kinds"].items():
            self.assertIn(spec["initial"], spec["statuses"])

    def test_validate_cli_rejects_tampered_record(self):
        rec = claim()
        path = self.p("rec.json")
        json.dump(rec, open(path, "w", encoding="utf-8"))
        ok = run("contract_v2.py", "--validate", path)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        rec["data"]["text"] = "tampered"
        json.dump(rec, open(path, "w", encoding="utf-8"))
        bad = run("contract_v2.py", "--validate", path)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("content_hash", bad.stdout + bad.stderr)


class TestProducerBinding(TempCase):
    def test_producer_hashes_actual_code_file(self):
        p = prod(config={"a": 1})
        self.assertEqual(len(p["code_sha256"]), 64)
        self.assertEqual(len(p["config_sha256"]), 64)
        changed = prod(config={"a": 2})
        self.assertNotEqual(p["config_sha256"], changed["config_sha256"])

    def test_producer_for_missing_module_keeps_explicit_null(self):
        p = C.producer_for("does.not.exist")
        self.assertIsNone(p["code_sha256"])
