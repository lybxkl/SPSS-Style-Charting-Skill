# -*- coding: utf-8 -*-
"""Versioned research-record contract (v2) with capability negotiation.

This module is the single place that defines what a *v2 research record* is:
the envelope fields, the per-kind payload schema, the status vocabulary and the
legal status transitions.  Every new capability module writes its output
through :class:`Project`, so "the generator must write it and the consumer must
check it" is enforced in one place instead of being re-implemented per script.

Design rules (see ``references/13-v2-record-contract.md``):

* A record carries ``requires_features``: semantics a consumer *must*
  understand before it may use the record.  An unknown *required* feature is a
  hard refusal; unknown *optional* extensions survive untouched.
* ``content_hash`` covers kind/id/revision/payload, so a hand-edited value is
  detectable.  ``signature()`` additionally binds status and producer for
  review/commit receipts; it deliberately ignores ``created_at``.
* Status changes are checked against an explicit transition table.  A jump the
  table forbids (``prepared`` -> ``verified``) is an error, not a warning.
* Original values are never normalised away: payload values that matter for
  evidence are stored as strings (see ``cell_evidence``), and the canonical
  form used for hashing is a *separate* view.

CLI::

    python contract_v2.py --dump-schema assets/contracts-v2.json
    python contract_v2.py --validate path/to/record.json
    python contract_v2.py --validate-ledger output/v2/claim.jsonl
    python contract_v2.py --migrate-v1 --root .
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------
#: Features a *reader* may declare.  A record that requires a feature the
#: reader does not declare is refused (never silently degraded).
FEATURES: dict[str, str] = {
    "current-evidence-binding": "revalidates exact result/input/code and real search/review scopes before consumption",
    "record-v2": "understands the v2 record envelope at all",
    "status-machine": "understands explicit status transitions",
    "visual-evidence": "can consume OCR/bbox/crop visual evidence",
    "table-structure": "can consume recovered table headers/units/footnotes",
    "transcript-timing": "can consume ASR segments and word timings",
    "audit-view": "can consume native->audit view structural checks",
    "structure-coverage": "can consume per-structure disposition coverage",
    "search-receipts": "can consume executed-search receipts and index versions",
    "review-events": "can consume second-pass review events and patches",
    "entity-relations": "can consume entity/alias/relation records",
    "multi-input-model": "can consume role-mapped multi-input model specs",
    "typed-result": "can consume non-coefficient result payloads",
    "numeric-validation": "can consume independent numeric validation records",
    "dependency-graph": "can consume dependency nodes/edges/events",
    "negative-evidence": "can consume 'judged absent/excluded' dependencies",
    "transactions": "can consume staged commit manifests and publish pointers",
    "claim-support": "can consume claims and their support relations",
    "figure-elements": "can consume figure element/data mapping checks",
    "layout-placement": "can consume final DOCX/PDF placement checks",
    "release-scopes": "can distinguish complete/limited/not_ready/failed release",
    "legal-empty-table": "can consume range evidence for an empty table",
    "no-sample-n": "can consume inputs with no statistical sample N",
    "generated-value-kinds": "can distinguish observed/derived/estimated/imputed",
    "open-adapters": "can consume records produced by external adapters",
    "cache-runtime-binding": "revalidates cache code, inputs, rules, outputs and actual runtime",
    "active-source-generation":"distinguishes active source recovery generations from preserved history",
    "source-representation-binding":"checks recovered representation identity, recovery revisions and whole-unit scope reports",
    "validation-field-coverage":"distinguishes checked numeric fields from unchecked outputs",
    "release-current-closure":"checks transitive dependencies and current published readiness",
}


class ContractError(Exception):
    """Base class for every contract violation."""


class SchemaError(ContractError):
    """Envelope or payload field is missing/ill-typed/unknown."""


class FeatureError(ContractError):
    """A consumer lacks a feature the record requires."""


class StatusTransitionError(ContractError):
    """A status change is not allowed by the transition table."""


class IntegrityError(ContractError):
    """Record content no longer matches its recorded hash."""


# ---------------------------------------------------------------------------
# status vocabulary + transitions
# ---------------------------------------------------------------------------
STATUSES: dict[str, tuple[str, ...]] = {
    "source_unit": ("pending", "recovered", "partial", "failed",
                    "unsupported", "excluded"),
    "container": ("pending", "enumerated", "partial", "failed", "unsupported"),
    "recovery_receipt": ("recorded", "superseded"),
    "audit_view": ("verified", "mismatch", "partial", "unsupported"),
    "discovery_candidate": ("candidate", "adopted", "excluded", "unresolved",
                            "blocked"),
    "structure_coverage": ("covered", "not_used", "unrecovered", "unknown"),
    "search_index": ("current", "stale", "failed"),
    "search_run": ("planned", "executed", "failed", "stale"),
    "data_gap": ("open", "searching", "resolved", "unavailable", "blocked",
                 "exhausted"),
    "review_patch": ("proposed", "applied", "rejected", "stale", "conflict"),
    "review_event": ("recorded", "superseded", "rejected"),
    "entity": ("proposed", "active", "merged", "split", "rejected"),
    "relation": ("proposed", "active", "rejected", "disputed"),
    "join_audit": ("passed", "failed", "unassessed"),
    "cell_evidence": ("candidate", "prepared", "review_pending", "verified",
                      "disputed", "stale"),
    "model_spec": ("candidate", "needs_data", "ready", "completed",
                   "insufficient_data", "not_applicable", "unsupported",
                   "failed"),
    "model_result": ("produced", "validated", "failed", "unvalidated"),
    "validation_result": ("passed", "failed", "unassessed", "not_applicable"),
    "claim": ("draft", "supported", "contradicted", "unsupported", "pending",
              "stale"),
    "reference": ("verified", "partial_access", "unverifiable", "retracted",
                  "corrected", "stale"),
    "figure_spec": ("declared", "checked", "failed", "stale"),
    "layout_check": ("passed", "failed", "unassessed", "not_applicable"),
    "manuscript_block": ("draft", "reviewed", "stale"),
    "dependency_node": ("active", "stale", "retired"),
    "dependency_edge": ("active", "stale"),
    "dependency_event": ("recorded",),
    "workflow_step": ("planned", "running", "completed", "failed", "blocked",
                      "cancelled", "stale"),
    "checkpoint": ("valid", "invalid"),
    "environment_snapshot": ("recorded", "drifted"),
    "cache_entry": ("valid", "stale"),
    "release_snapshot": ("complete", "limited", "not_ready", "failed"),
}

#: ``from -> allowed next``.  ``X -> X`` (a re-record) is always allowed: the
#: revision number is what distinguishes the two records.
TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "source_unit": {
        "pending": ("recovered", "partial", "failed", "unsupported", "excluded"),
        "recovered": ("partial", "failed", "excluded"),
        "partial": ("recovered", "failed", "unsupported", "excluded"),
        "failed": ("recovered", "partial", "unsupported", "excluded"),
        "unsupported": ("recovered", "partial", "failed", "excluded"),
        "excluded": ("recovered", "partial"),
    },
    "container": {
        "pending": ("enumerated", "partial", "failed", "unsupported"),
        "enumerated": ("partial", "failed"),
        "partial": ("enumerated", "failed", "unsupported"),
        "failed": ("enumerated", "partial", "unsupported"),
        "unsupported": ("enumerated", "partial"),
    },
    "recovery_receipt": {"recorded": ("superseded",)},
    "audit_view": {
        "verified": ("mismatch", "partial"),
        "mismatch": ("verified", "partial", "unsupported"),
        "partial": ("verified", "mismatch", "unsupported"),
        "unsupported": ("verified", "partial", "mismatch"),
    },
    "discovery_candidate": {
        "candidate": ("adopted", "excluded", "unresolved", "blocked"),
        "blocked": ("candidate", "adopted", "excluded", "unresolved"),
        "unresolved": ("candidate", "adopted", "excluded", "blocked"),
        "adopted": ("excluded", "unresolved"),
        "excluded": ("candidate", "adopted"),
    },
    "structure_coverage": {
        "unknown": ("covered", "not_used", "unrecovered"),
        "covered": ("not_used", "unrecovered"),
        "not_used": ("covered", "unrecovered"),
        "unrecovered": ("covered", "not_used"),
    },
    "search_index": {"current": ("stale", "failed"), "stale": ("current", "failed"),
                     "failed": ("current", "stale")},
    "search_run": {"planned": ("executed", "failed"),
                   "executed": ("stale", "failed"),
                   "failed": ("executed", "planned"),
                   "stale": ("executed", "failed")},
    "data_gap": {
        "open": ("searching", "resolved", "unavailable", "blocked", "exhausted"),
        "searching": ("resolved", "unavailable", "blocked", "open", "exhausted"),
        "resolved": ("open", "blocked"),
        "unavailable": ("open", "searching", "resolved", "exhausted"),
        "blocked": ("open", "searching", "resolved", "unavailable"),
        "exhausted": ("open", "resolved"),
    },
    "review_patch": {
        "proposed": ("applied", "rejected", "stale", "conflict"),
        "conflict": ("proposed", "rejected", "stale", "applied"),
        "applied": ("stale",),
        "rejected": ("proposed",),
        "stale": ("proposed",),
    },
    "review_event": {"recorded": ("superseded", "rejected"),
                     "superseded": ("recorded",),
                     "rejected": ("recorded",)},
    "entity": {"proposed": ("active", "merged", "split", "rejected"),
               "active": ("merged", "split", "rejected"),
               "merged": ("split", "active", "rejected"),
               "split": ("active", "merged", "rejected"),
               "rejected": ("proposed", "active")},
    "relation": {"proposed": ("active", "rejected", "disputed"),
                 "active": ("rejected", "disputed"),
                 "disputed": ("active", "rejected"),
                 "rejected": ("proposed", "active")},
    "join_audit": {"unassessed": ("passed", "failed"),
                   "passed": ("failed", "unassessed"),
                   "failed": ("passed", "unassessed")},
    "cell_evidence": {
        "candidate": ("prepared", "disputed", "stale"),
        "prepared": ("review_pending", "disputed", "stale"),
        # prepared -> verified is deliberately absent: a machine pass is not a
        # human/agent re-read.
        "review_pending": ("verified", "disputed", "stale"),
        "verified": ("disputed", "stale"),
        "disputed": ("review_pending", "prepared", "stale"),
        "stale": ("prepared", "candidate"),
    },
    "model_spec": {
        "candidate": ("ready", "needs_data", "insufficient_data",
                      "not_applicable", "unsupported"),
        "needs_data": ("ready", "candidate", "insufficient_data",
                       "unsupported", "failed"),
        "ready": ("completed", "failed", "insufficient_data", "unsupported",
                  "not_applicable"),
        "completed": ("ready", "failed"),
        "insufficient_data": ("ready", "candidate", "needs_data"),
        "not_applicable": ("candidate", "ready"),
        "unsupported": ("ready", "candidate", "failed"),
        "failed": ("ready", "candidate"),
    },
    "model_result": {"produced": ("validated", "failed", "unvalidated"),
                     "unvalidated": ("validated", "failed"),
                     "validated": ("failed", "unvalidated"),
                     "failed": ("produced",)},
    "validation_result": {
        "unassessed": ("passed", "failed", "not_applicable"),
        "passed": ("failed", "unassessed"),
        "failed": ("passed", "unassessed"),
        "not_applicable": ("passed", "failed", "unassessed"),
    },
    "claim": {"draft": ("supported", "contradicted", "unsupported", "pending",
                        "stale"),
              "pending": ("supported", "contradicted", "unsupported", "stale"),
              "supported": ("contradicted", "pending", "stale"),
              "contradicted": ("draft", "pending", "stale"),
              "unsupported": ("draft", "pending", "stale"),
              "stale": ("draft", "pending", "supported", "unsupported")},
    "reference": {"verified": ("partial_access", "unverifiable", "retracted",
                               "corrected", "stale"),
                  "partial_access": ("verified", "unverifiable", "retracted",
                                     "corrected", "stale"),
                  "unverifiable": ("verified", "partial_access", "stale"),
                  "retracted": ("stale", "corrected"),
                  "corrected": ("verified", "partial_access", "stale"),
                  "stale": ("verified", "partial_access", "unverifiable")},
    "figure_spec": {"declared": ("checked", "failed", "stale"),
                    "checked": ("failed", "stale"),
                    "failed": ("checked", "declared", "stale"),
                    "stale": ("declared", "checked")},
    "layout_check": {"unassessed": ("passed", "failed", "not_applicable"),
                     "passed": ("failed", "unassessed"),
                     "failed": ("passed", "unassessed"),
                     "not_applicable": ("passed", "failed")},
    "manuscript_block": {"draft": ("reviewed", "stale"),
                         "reviewed": ("stale", "draft"),
                         "stale": ("draft", "reviewed")},
    "dependency_node": {"active": ("stale", "retired"),
                        "stale": ("active", "retired"),
                        "retired": ("active",)},
    "dependency_edge": {"active": ("stale",), "stale": ("active",)},
    "dependency_event": {"recorded": ()},
    "workflow_step": {
        "planned": ("running", "cancelled", "blocked", "stale"),
        "running": ("completed", "failed", "cancelled", "blocked"),
        "failed": ("planned", "running", "blocked", "cancelled"),
        "blocked": ("planned", "running", "cancelled", "failed"),
        "cancelled": ("planned", "running"),
        "completed": ("stale", "planned"),
        "stale": ("planned", "running", "blocked"),
    },
    "checkpoint": {"valid": ("invalid",), "invalid": ("valid",)},
    "environment_snapshot": {"recorded": ("drifted",), "drifted": ("recorded",)},
    "cache_entry": {"valid": ("stale",), "stale": ("valid",)},
    "release_snapshot": {
        "not_ready": ("complete", "limited", "failed"),
        "limited": ("complete", "failed", "not_ready"),
        "complete": ("limited", "failed"),
        "failed": ("not_ready", "limited", "complete"),
    },
}

INITIAL_STATUS: dict[str, str] = {k: v[0] for k, v in STATUSES.items()}

# ---------------------------------------------------------------------------
# payload schemas
# ---------------------------------------------------------------------------
# Minimal but real: every object the plan requires has its core fields typed.
# ``required=False`` fields may be absent; ``nullable`` allows None.  Unknown
# payload keys are preserved (never silently dropped) and reported by
# ``strict=True`` validation so a schema lag is visible instead of silent.
_SCHEMAS: dict[str, dict[str, Any]] = {
    "source_unit": {
        "required": {
            "source": "string",            # physical file rel path
            "source_sha256": "string",
            "unit_type": "string",         # page|region|table|row|cell|paragraph|sheet|cell_range|image|segment|member|object
            "parent_source": "string",
            "locator": "object",
            "representation": "string",
            "representation_sha256": "string",
            "engine": "object",
            "recovered_scope": "object",
            "unrecovered": "array",
        },
        "optional": {
            "bbox": "array",               # [x0,y0,x1,y1] in the declared unit
            "coord_unit": "string",        # pt|px|char|second
            "rotation": "number",
            "scale": "number",
            "page": "integer",
            "preview": "string",
            "physical_index": "integer",
            "logical_index": "integer",
            "observation_index": "integer",
            "container_path": "string",
            "notes": "string",
        },
    },
    "container": {
        "required": {
            "source": "string",
            "source_sha256": "string",
            "container_type": "string",    # zip|pdf_attachment|office_embedded|directory
            "members": "array",
            "counts": "object",
        },
        "optional": {"password_protected": "boolean", "notes": "string"},
    },
    "recovery_receipt": {
        "required": {
            "source": "string",
            "source_sha256": "string",
            "attempts": "array",
            "outcome": "string",
        },
        "optional": {"failure_class": "string", "notes": "string"},
    },
    "audit_view": {
        "required": {
            "native_path": "string",
            "native_sha256": "string",
            "view_path": "string",
            "view_sha256": "string",
            "checks": "array",
            "mismatches": "array",
        },
        "optional": {"adapter": "object", "row_count": "integer",
                     "column_count": "integer", "notes": "string"},
    },
    "discovery_candidate": {
        "required": {
            "origin": "string",            # source_first|question_first|user_supplied
            "kind": "string",              # entity|field|dataset|measure|relation|time_point
            "name": "string",
            "sources": "array",
            "disposition": "string",
        },
        "optional": {
            "unit": "string", "value_range": "string", "keys": "array",
            "research_use": "string", "ambiguity": "string",
            "suggested_shape": "string", "data_gap": "string",
            "reason": "string", "quote": "string",
        },
    },
    "structure_coverage": {
        "required": {"source": "string", "source_sha256": "string",
                     "structure": "string", "disposition": "string"},
        "optional": {"unit_ids": "array", "reason": "string",
                     "enumeration_method": "string"},
    },
    "search_index": {
        "required": {"sources": "array", "built_at": "string",
                     "entry_count": "integer"},
        "optional": {"path": "string", "builder": "object"},
    },
    "search_run": {
        "required": {
            "goal": "object",
            "query": "object",
            "sources": "array",
            "hits": "array",
            "executed": "boolean",
        },
        "optional": {"index": "object", "context": "string",
                     "notes": "string", "gap_ids": "array"},
    },
    "data_gap": {
        "required": {
            "model_or_dataset": "string",
            "requirement": "string",
            "status_detail": "string",
            "searches": "array",
        },
        "optional": {"resolution": "string", "conclusion": "string",
                     "blocked_reason": "string", "impact": "string"},
    },
    "review_patch": {
        "required": {
            "dataset": "string", "key": "array", "column": "string",
            "new_value": "string", "parent_snapshot": "string",
            "operations": "array",
        },
        "optional": {"reason": "string", "operator": "string",
                     "conflict": "string", "applied_at": "string"},
    },
    "review_event": {
        "required": {
            "dataset": "string", "key": "array", "column": "string",
            "value_under_review": "string", "record_sha256": "string",
            "method": "string", "reviewer": "string",
            "independence": "string", "reread_scope": "object",
            "second_pass": "object", "outcome": "string",
            "checked_at": "string",
        },
        "optional": {"candidates": "array", "adopted": "string",
                     "reason": "string", "supersedes": "string",
                     "note": "string"},
    },
    "entity": {
        "required": {
            "entity_type": "string",
            "canonical_name": "string",
            "aliases": "array",
            "sources": "array",
        },
        "optional": {"stable_ids": "array", "candidate_links": "array",
                     "conflicts": "array", "merge_of": "array",
                     "split_into": "array", "notes": "string"},
    },
    "relation": {
        "required": {
            "relation_type": "string", "from_ref": "object", "to_ref": "object",
            "cardinality": "string", "evidence": "array",
        },
        "optional": {"valid_from": "string", "valid_to": "string",
                     "unit_rule": "object", "disputed": "boolean",
                     "notes": "string"},
    },
    "join_audit": {
        "required": {
            "left": "object", "right": "object", "keys": "array",
            "before": "object", "after": "object", "checks": "array",
        },
        "optional": {"expanded_rows": "integer", "dropped_rows": "integer",
                     "notes": "string"},
    },
    "cell_evidence": {
        "required": {
            "dataset": "string", "key": "array", "column": "string",
            "value": "string", "kind": "string", "sources": "array",
        },
        "optional": {"rule": "object", "inputs": "array", "compare": "string",
                     "tolerance": "string", "tolerance_reason": "string",
                     "reason": "string", "origin": "string",
                     "method": "string", "uncertainty": "string"},
    },
    "model_spec": {
        "required": {
            "family": "string", "engine": "object", "question": "string",
            "inputs": "array", "requirements": "object",
            "execution": "object", "numerical_validation": "object",
            "method_assessment": "object", "claim_scope": "object",
        },
        "optional": {"target_parameter": "string", "unit": "string",
                     "scale": "string", "sample_accounting": "object",
                     "diagnostics_expected": "array", "reason": "string",
                     "assessment": "object", "gaps": "array",
                     "spec_variants": "array", "result_id": "string"},
    },
    "model_result": {
        "required": {
            "model": "string", "result_type": "string", "payload": "object",
            "target_parameter": "string", "unit": "string",
            "sample_scope": "object",
        },
        "optional": {"estimate": "string", "interval": "object",
                     "denominator": "string", "time_scope": "string",
                     "group": "string", "native_path": "string",
                     "native_sha256": "string", "notes": "string"},
    },
    "validation_result": {
        "required": {
            "target": "object", "method": "string", "independent": "object",
            "tolerance": "object", "observed": "object",
        },
        "optional": {"known_answer": "object", "code": "object",
                     "reason": "string", "layers": "array"},
    },
    "claim": {
        "required": {
            "claim_type": "string", "text": "string", "block_id": "string",
            "text_fingerprint": "string", "support": "array",
        },
        "optional": {"scope": "object", "checks": "array",
                     "disposition": "string", "reason": "string",
                     "revised_text": "string", "section": "string"},
    },
    "reference": {
        "required": {
            "cite_id": "string", "authors": "string", "title": "string",
            "year": "string", "venue": "string", "access": "object",
        },
        "optional": {"doi": "string", "url": "string", "isbn": "string",
                     "report_no": "string", "raw_citation": "string",
                     "retraction": "object", "correction": "object",
                     "support_claims": "array", "notes": "string"},
    },
    "figure_spec": {
        "required": {
            "figure_id": "string", "question": "string", "inputs": "array",
            "denominator": "string", "unit": "string",
            "series_declared": "array", "elements_observed": "object",
            "checks": "array", "png": "string", "pdf": "string",
        },
        "optional": {"transform": "string", "sorting": "string",
                     "error_type": "string", "reference_line": "string",
                     "palette": "object", "labels": "object",
                     "caption": "string", "placement": "object",
                     "notes": "string"},
    },
    "layout_check": {
        "required": {
            "docx": "string", "pdf": "string", "images": "array",
            "checks": "array", "pages_reviewed": "array",
        },
        "optional": {"font_report": "object", "notes": "string"},
    },
    "manuscript_block": {
        "required": {
            "block_id": "string", "section": "string", "text": "string",
            "fingerprint": "string", "claims": "array",
        },
        "optional": {"printed_text": "string", "draft_state": "string",
                     "word_count": "integer", "notes": "string"},
    },
    "dependency_node": {
        "required": {"stable_id": "string", "node_type": "string",
                     "content_version": "string"},
        "optional": {"label": "string", "path": "string"},
    },
    "dependency_edge": {
        "required": {"from": "string", "to": "string", "edge_type": "string"},
        "optional": {"evidence": "string", "note": "string"},
    },
    "dependency_event": {
        "required": {"node": "string", "event": "string", "detail": "object"},
        "optional": {"old_version": "string", "new_version": "string"},
    },
    "workflow_step": {
        "required": {
            "step": "string", "scope": "object", "inputs": "array",
            "outputs": "array", "run_state": "object", "check_state": "object",
        },
        "optional": {"blocked_by": "array", "resume": "object",
                     "command": "array", "notes": "string"},
    },
    "checkpoint": {
        "required": {
            "step": "string", "inputs": "object", "code": "object",
            "rules": "object", "environment": "object", "review_version": "string",
        },
        "optional": {"resume_token": "string", "partial_outputs": "array",
                     "notes": "string"},
    },
    "environment_snapshot": {
        "required": {
            "phase": "string", "python": "object", "packages": "object",
            "engines": "object", "fonts": "array", "seeds": "object",
            "system": "object",
        },
        "optional": {"external_inputs": "array", "limits": "array",
                     "notes": "string"},
    },
    "cache_entry": {
        "required": {
            "key": "string", "inputs": "object", "code": "object",
            "environment": "object", "origin_run": "string",
            "reuse": "object",
        },
          "optional": {"outputs": "array", "notes": "string", "runtime_environment": "object"},
    },
    "release_snapshot": {
        "required": {
            "scope": "object", "coverage": "object", "checks": "array",
            "unfinished": "array", "status_detail": "string",
            "artifacts": "array",
        },
        "optional": {"partial_scope": "object", "gate": "object",
                     "notes": "string"},
    },
}

REQUIRED_FEATURES: dict[str, tuple[str, ...]] = {
    "source_unit": ("record-v2", "visual-evidence", "table-structure",
                    "transcript-timing", "audit-view", "active-source-generation", "source-representation-binding"),
    "container": ("record-v2", "audit-view"),
    "recovery_receipt": ("record-v2",),
    "audit_view": ("record-v2", "audit-view"),
    "discovery_candidate": ("record-v2", "structure-coverage"),
    "structure_coverage": ("record-v2", "structure-coverage"),
    "search_index": ("record-v2", "search-receipts", "source-representation-binding"),
    "search_run": ("record-v2", "search-receipts", "current-evidence-binding", "source-representation-binding"),
    "data_gap": ("record-v2", "search-receipts"),
    "review_patch": ("record-v2", "review-events"),
    "review_event": ("record-v2", "review-events", "current-evidence-binding"),
    "entity": ("record-v2", "entity-relations"),
    "relation": ("record-v2", "entity-relations"),
    "join_audit": ("record-v2", "entity-relations"),
    "cell_evidence": ("record-v2", "generated-value-kinds"),
    "model_spec": ("record-v2", "multi-input-model", "typed-result"),
    "model_result": ("record-v2", "typed-result", "current-evidence-binding"),
    "validation_result": ("record-v2", "numeric-validation", "current-evidence-binding", "validation-field-coverage"),
    "claim": ("record-v2", "claim-support"),
    "reference": ("record-v2", "claim-support"),
    "figure_spec": ("record-v2", "figure-elements"),
    "layout_check": ("record-v2", "layout-placement"),
    "manuscript_block": ("record-v2", "claim-support"),
    "dependency_node": ("record-v2", "dependency-graph"),
    "dependency_edge": ("record-v2", "dependency-graph"),
    "dependency_event": ("record-v2", "dependency-graph", "negative-evidence"),
    "workflow_step": ("record-v2", "transactions", "release-scopes"),
    "checkpoint": ("record-v2", "transactions"),
    "environment_snapshot": ("record-v2",),
    "cache_entry": ("record-v2", "transactions", "cache-runtime-binding"),
    "release_snapshot": ("record-v2", "release-scopes", "claim-support",
                         "figure-elements", "layout-placement",
                           "numeric-validation", "current-evidence-binding", "release-current-closure"),
}

# Maintained additive payload fields. Required semantics are negotiated above;
# optional metadata is still typed and appears in schema dumps/strict reads.
for _kind, _fields in {
    "search_index": {"root": "string", "inventory": "array", "index_sha256": "string"},
    "search_run": {"scan_complete": "boolean", "materials_root": "string", "inventory": "array", "scanned_units": "array"},
    "data_gap": {"resolved_dataset": "string", "integration": "object", "coverage": "object"},
    "review_event": {"target_type": "string", "source_sha256": "string", "unit_revision": "integer", "unit_signature": "string"},
    "model_spec": {"spec_sha256": "string"},
    "model_result": {"computation": "object", "scale": "string"},
    "reference": {"doi_check": "object", "supports": "array", "publication_status": "object"},
    "claim": {"semantic_review": "object"},
    "figure_spec": {"png_sha256": "string", "pdf_sha256": "string"},
}.items():
    _SCHEMAS[_kind].setdefault("optional", {}).update(_fields)

KINDS = tuple(sorted(STATUSES))
PER_KIND_FEATURES: dict[str, tuple[str, ...]] = {
    "source_unit": ("visual-evidence", "table-structure", "transcript-timing",
                    "audit-view"),
    "container": ("audit-view",),
    "audit_view": ("audit-view",),
    "discovery_candidate": ("structure-coverage",),
    "structure_coverage": ("structure-coverage",),
    "search_index": ("search-receipts",),
    "search_run": ("search-receipts",),
    "data_gap": ("search-receipts", "negative-evidence"),
    "review_patch": ("review-events", "transactions"),
    "review_event": ("review-events",),
    "entity": ("entity-relations",),
    "relation": ("entity-relations",),
    "join_audit": ("entity-relations",),
    "cell_evidence": ("generated-value-kinds",),
    "model_spec": ("multi-input-model", "typed-result", "no-sample-n"),
    "model_result": ("typed-result",),
    "validation_result": ("numeric-validation",),
    "claim": ("claim-support",),
    "reference": ("claim-support",),
    "figure_spec": ("figure-elements",),
    "layout_check": ("layout-placement",),
    "manuscript_block": ("claim-support",),
    "dependency_node": ("dependency-graph",),
    "dependency_edge": ("dependency-graph", "negative-evidence"),
    "dependency_event": ("dependency-graph", "negative-evidence"),
    "workflow_step": ("transactions", "release-scopes"),
    "checkpoint": ("transactions",),
    "environment_snapshot": ("record-v2",),
    "cache_entry": ("transactions",),
    "release_snapshot": ("release-scopes", "claim-support", "figure-elements",
                         "layout-placement", "numeric-validation"),
}

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$")


# ---------------------------------------------------------------------------
# canonical form / hashing
# ---------------------------------------------------------------------------
def canonical_json(obj: Any) -> str:
    """Deterministic serialisation used for hashing.

    ``ensure_ascii=False`` keeps real Unicode (no ``\\uXXXX`` escapes), which
    matters because two visually different values must not hash the same and a
    value must not change identity by being escaped.
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(
        timespec="microseconds")


def file_sha256(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def producer_for(program: str, *, version: str = "", module_file: str | None = None,
                 config: Any = None, command: Iterable[str] | None = None) -> dict:
    """Bind a producer to the *actual* code and configuration.

    ``program`` is the module name a human reads; ``code_sha256`` is computed
    from the real source file, so a producer block cannot be faked by writing a
    brand name into JSON.
    """
    code = None
    if module_file is None:
        try:
            module_file = sys.modules[program].__file__
        except Exception:
            module_file = None
    if module_file and os.path.isfile(module_file):
        code = file_sha256(module_file)
    out = {"program": program, "version": version or "0", "code_sha256": code}
    if config is not None:
        out["config_sha256"] = canonical_hash(config)
    if command:
        out["command"] = [str(c) for c in command]
    return out


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "any": lambda v: True,
}


def _fail(path: str, msg: str) -> None:
    raise SchemaError(f"{path}: {msg}")


def _check_value(path: str, value: Any, spec: str) -> None:
    if isinstance(spec, dict):
        base = spec.get("type", "any")
        if value is None and spec.get("nullable"):
            return
        _check_value(path, value, base)
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            _fail(path, f"{value!r} not in {list(enum)}")
        if base == "array":
            item = spec.get("items")
            if item:
                for i, v in enumerate(value):
                    _check_value(f"{path}[{i}]", v, item)
            if spec.get("min_items") is not None and len(value) < spec["min_items"]:
                _fail(path, f"needs >= {spec['min_items']} items, got {len(value)}")
        if base == "object" and spec.get("required"):
            for k in spec["required"]:
                if k not in value:
                    _fail(path, f"missing required key {k!r}")
        return
    check = _TYPE_CHECKS.get(spec)
    if check is None:
        _fail(path, f"schema declares unknown type {spec!r}")
    if not check(value):
        _fail(path, f"expected {spec}, got {type(value).__name__} ({value!r})")


def validate_record(rec: Mapping, *, reader: "Reader | None" = None,
                    strict: bool = False) -> dict:
    """Validate one record; raise :class:`ContractError` on any violation."""
    if not isinstance(rec, Mapping):
        raise SchemaError(f"record must be an object, got {type(rec).__name__}")
    for key in ("schema_version", "kind", "id", "revision", "producer",
                "input_refs", "content_hash", "status", "created_at", "data"):
        if key not in rec:
            _fail("<record>", f"missing envelope field {key!r}")
    if rec["schema_version"] != SCHEMA_VERSION:
        raise FeatureError(
            f"schema_version {rec['schema_version']!r} unsupported; this reader "
            f"implements {SCHEMA_VERSION} (older readers must refuse, not degrade)")
    kind = rec["kind"]
    if kind not in STATUSES:
        raise SchemaError(f"unknown kind {kind!r}")
    if not isinstance(rec["id"], str) or not rec["id"].strip():
        _fail("id", "must be a non-empty string")
    if not isinstance(rec["revision"], int) or isinstance(rec["revision"], bool) \
            or rec["revision"] < 1:
        _fail("revision", "must be an integer >= 1")
    if rec["status"] not in STATUSES[kind]:
        _fail("status", f"{rec['status']!r} not in {STATUSES[kind]} for {kind}")
    if not _ISO.match(str(rec["created_at"])):
        _fail("created_at", "must be an ISO-8601 instant with a UTC offset")
    _check_value("producer", rec["producer"], {
        "type": "object", "required": ["program"]})
    if not isinstance(rec["input_refs"], list):
        _fail("input_refs", "must be an array")
    for i, ref in enumerate(rec["input_refs"]):
        _check_value(f"input_refs[{i}]", ref, {"type": "object",
                                               "required": ["kind", "id"]})
    feats = rec.get("requires_features", [])
    if not isinstance(feats, list) or any(not isinstance(f, str) for f in feats):
        _fail("requires_features", "must be an array of strings")
    for feat in feats:
        if feat not in FEATURES:
            raise SchemaError(f"requires_features: unknown feature {feat!r} "
                              f"(declare it in FEATURES before using it)")
    payload = rec["data"]
    if not isinstance(payload, dict):
        _fail("data", "must be an object")
    schema = _SCHEMAS[kind]
    for name, spec in schema["required"].items():
        if name not in payload:
            _fail(f"data.{name}", "required field missing")
        _check_value(f"data.{name}", payload[name], spec)
    for name, spec in schema.get("optional", {}).items():
        if name in payload:
            _check_value(f"data.{name}", payload[name], spec)
    if strict:
        allowed = set(schema["required"]) | set(schema.get("optional", {}))
        extra = sorted(set(payload) - allowed)
        if extra:
            raise SchemaError(f"data: undeclared field(s) {extra} for {kind}; "
                              f"add them to the schema instead of smuggling them")
    expected = _content_hash(kind, rec["id"], rec["revision"], payload)
    if rec["content_hash"] != expected:
        raise IntegrityError(
            f"content_hash mismatch for {kind} {rec['id']} r{rec['revision']}: "
            f"record says {rec['content_hash'][:12]}, payload hashes to "
            f"{expected[:12]}")
    if reader is not None:
        negotiate(rec, reader)
    return dict(rec)


def _content_hash(kind: str, rid: str, revision: int, payload: Mapping) -> str:
    return canonical_hash({"kind": kind, "id": rid, "revision": revision,
                           "data": payload})


def field_parts(path: str) -> tuple[str, ...]:
    """JSON Pointer for arbitrary keys; dotted paths remain a compatibility form."""
    if path.startswith("/"):
        if re.search(r"~(?![01])",path):raise ValueError("invalid JSON Pointer escape")
        return tuple(part.replace("~1","/").replace("~0","~") for part in path[1:].split("/"))
    return tuple(path.split(".")) if path else ()


def field_pointer(*parts) -> str:
    return "/"+"/".join(str(p).replace("~","~0").replace("/","~1") for p in parts)


def field_value(value, path):
    for part in field_parts(path):
        if isinstance(value,(list,tuple)):
            if not re.fullmatch(r"0|[1-9][0-9]*",part):raise ValueError("invalid array index")
            value=value[int(part)]
        else:value=value[part]
    return value


def signature(rec: Mapping) -> str:
    """Review/commit signature: everything except ``created_at``.

    Two re-records of the same content therefore sign identically, while any
    status or producer change is visible.
    """
    clone = {k: v for k, v in rec.items() if k != "created_at"}
    return canonical_hash(clone)


# ---------------------------------------------------------------------------
# capability negotiation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Reader:
    """A consumer's declared capabilities."""

    name: str = "reader"
    version: str = "0"
    schema_version: int = SCHEMA_VERSION
    features: frozenset[str] = field(
        default_factory=lambda: frozenset(FEATURES))

    def supports(self, feature: str) -> bool:
        return feature in self.features

    def with_features(self, *features: str) -> "Reader":
        return Reader(self.name, self.version, self.schema_version,
                      self.features | frozenset(features))

    def without_features(self, *features: str) -> "Reader":
        return Reader(self.name, self.version, self.schema_version,
                      self.features - frozenset(features))


def negotiate(rec: Mapping, reader: Reader) -> None:
    """Refuse a record whose *required* semantics the reader lacks."""
    if reader.schema_version < SCHEMA_VERSION:
        raise FeatureError(
            f"{reader.name} v{reader.version} speaks schema "
            f"{reader.schema_version} but the record is v{SCHEMA_VERSION}")
    missing = sorted(set(rec.get("requires_features", [])) -
                     set(reader.features))
    if missing:
        raise FeatureError(
            f"{reader.name} v{reader.version} cannot consume {rec['kind']} "
            f"{rec['id']}: required feature(s) {missing} undeclared. Refusing "
            f"rather than ignoring semantics it does not understand.")


# ---------------------------------------------------------------------------
# building records
# ---------------------------------------------------------------------------
def make_record(kind: str, rid: str, payload: Mapping, *, producer: Mapping,
                status: str | None = None, revision: int = 1,
                input_refs: Iterable[Mapping] = (),
                requires_features: Iterable[str] | None = None,
                optional_features: Iterable[str] = (),
                created_at: str | None = None,
                extensions: Mapping | None = None,
                supersedes: str | None = None) -> dict:
    if kind not in STATUSES:
        raise SchemaError(f"unknown kind {kind!r}")
    status = status or INITIAL_STATUS[kind]
    if status not in STATUSES[kind]:
        raise SchemaError(f"status {status!r} not in {STATUSES[kind]} for {kind}")
    base = set(REQUIRED_FEATURES.get(kind, ("record-v2",)))
    extra = set(requires_features or ())
    unknown = sorted((base | extra | set(optional_features)) - set(FEATURES))
    if unknown:
        raise SchemaError(f"unknown feature(s) {unknown}")
    rec = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "id": str(rid),
        "revision": int(revision),
        "producer": dict(producer),
        "input_refs": [dict(r) for r in input_refs],
        "content_hash": _content_hash(kind, str(rid), int(revision), payload),
        "status": status,
        "requires_features": sorted(base | extra),
        "optional_features": sorted(set(optional_features)),
        "created_at": created_at or _now(),
        "data": dict(payload),
    }
    if extensions:
        rec["extensions"] = dict(extensions)
    if supersedes:
        rec["supersedes"] = supersedes
    return rec


def check_transition(kind: str, old: str, new: str) -> None:
    if old not in STATUSES.get(kind, ()):
        raise SchemaError(f"unknown current status {old!r} for {kind}")
    if new not in STATUSES.get(kind, ()):
        raise SchemaError(f"unknown target status {new!r} for {kind}")
    if new == old:
        return
    allowed = TRANSITIONS.get(kind, {}).get(old, ())
    if new not in allowed:
        raise StatusTransitionError(
            f"{kind}: {old} -> {new} is not allowed "
            f"(allowed: {sorted(allowed) or 'none'})")


def transition(rec: Mapping, new_status: str, *, producer: Mapping | None = None,
               reason: str | None = None,
               patch: Mapping | None = None,
               created_at: str | None = None) -> dict:
    """Return a new revision of ``rec`` with a checked status change."""
    validate_record(rec)
    check_transition(rec["kind"], rec["status"], new_status)
    payload = dict(rec["data"])
    if patch:
        payload.update(patch)
    new = make_record(rec["kind"], rec["id"], payload,
                      producer=producer or rec["producer"],
                      status=new_status, revision=int(rec["revision"]) + 1,
                      input_refs=rec["input_refs"],
                      requires_features=[f for f in rec["requires_features"]
                                         if f not in
                                         REQUIRED_FEATURES.get(rec["kind"], ())],
                      optional_features=rec.get("optional_features", ()),
                      created_at=created_at,
                      extensions=rec.get("extensions"),
                      supersedes=f"{rec['kind']}:{rec['id']}@r{rec['revision']}")
    if reason:
        new.setdefault("extensions", {})["transition_reason"] = reason
    return new


# ---------------------------------------------------------------------------
# project ledger
# ---------------------------------------------------------------------------
def protect_output(project: "Project", target: str | os.PathLike) -> Path:
    """Reject original-file destinations, including symlink and hardlink aliases."""
    path = Path(target)
    path = (path if path.is_absolute() else project.root / path).resolve()
    registry_path = project.root / "research_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
    source = Path(registry.get("source_root") or "materials")
    source = (source if source.is_absolute() else project.root / source).resolve()
    if path == source or source in path.parents:
        raise IntegrityError(f"output overlaps original materials: {path}")
    if path.is_file() and source.is_dir():
        identity = path.stat()
        for original in source.rglob("*"):
            if original.is_file():
                other = original.stat()
                if (identity.st_dev, identity.st_ino) == (other.st_dev, other.st_ino):
                    raise IntegrityError(f"output is an alias of original material: {path}")
    return path


class Project:
    """File layout for v2 records under ``<root>/output/v2``.

    One JSONL ledger per kind keeps the layout obvious and crash-friendly:
    appends are line-buffered and fsync'ed, so an interrupted write can only
    leave one torn trailing line (which :meth:`read` reports, not swallows).
    """

    def __init__(self, root: str | os.PathLike, *, create: bool = True,
                 subdir: str = os.path.join("output", "v2")):
        self.root = Path(root).resolve()
        self.dir = self.root / subdir
        self._create = create
        if create:
            self.dir.mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------
    def path(self, *parts: str) -> Path:
        p = self.dir.joinpath(*parts)
        resolved = p.resolve()
        base = self.dir.resolve()
        if resolved != base and base not in resolved.parents:
            raise IntegrityError(f"project output path escapes v2 directory: {p}")
        if self._create:
            p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def ledger_path(self, kind: str) -> Path:
        if kind not in STATUSES:
            raise SchemaError(f"unknown kind {kind!r}")
        return self.path(f"{kind}.jsonl")

    # -- io ----------------------------------------------------------------
    def append(self, kind: str, rec: Mapping, *, enforce_transition: bool = True,
               reader: Reader | None = None) -> dict:
        from txn import Lock
        with Lock(self, f"ledger-{kind}", timeout=60):
            return self._append_locked(kind, rec, enforce_transition=enforce_transition,
                                       reader=reader)

    def _append_locked(self, kind: str, rec: Mapping, *, enforce_transition: bool = True,
                       reader: Reader | None = None) -> dict:
        validate_record(rec, reader=reader)
        if rec["kind"] != kind:
            raise SchemaError(f"record kind {rec['kind']!r} != ledger {kind!r}")
        path = self.ledger_path(kind)
        previous = self.latest(kind, rec["id"])
        if previous is not None:
            if rec["revision"] <= previous["revision"]:
                raise ContractError(
                    f"{kind} {rec['id']}: revision {rec['revision']} does not "
                    f"advance past stored r{previous['revision']} (idempotent "
                    f"re-append of the same revision is not a new record)")
            if enforce_transition:
                check_transition(kind, previous["status"], rec["status"])
        elif enforce_transition and rec["revision"] != 1:
            raise ContractError(f"{kind} {rec['id']}: first record must be r1, "
                                f"got r{rec['revision']}")
        stored = dict(rec)
        stored["_ledger_sha256"] = canonical_hash(rec)
        line = canonical_json(stored) + "\n"
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return dict(rec)

    def write(self, kind: str, rec: Mapping, **kw) -> dict:
        return self.append(kind, rec, **kw)

    def append_many(self, kind: str, records: Iterable[Mapping], *, enforce_transition=True) -> list[dict]:
        """Validate one review batch once and atomically replace its ledger.

        This removes the quadratic reread/fsync cost of thousands of cell events
        and prevents a failed row near the end from leaving a half-imported batch.
        """
        import shutil
        from txn import Lock
        records = [dict(r) for r in records]
        with Lock(self, f"ledger-{kind}", timeout=60):
            previous = {r["id"]: r for r in self.read(kind)}
            for rec in records:
                validate_record(rec, reader=Reader("Project.append_many"))
                old = previous.get(rec["id"])
                if rec["kind"] != kind or rec["revision"] <= (old["revision"] if old else 0):
                    raise IntegrityError("batch contains wrong kind or non-increasing revision")
                if old and enforce_transition:
                    check_transition(kind, old["status"], rec["status"])
                previous[rec["id"]] = rec
            path = self.ledger_path(kind)
            fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as stream:
                    if path.is_file():
                        with open(path, "rb") as current:
                            shutil.copyfileobj(current, stream)
                    for rec in records:
                        stored = {**rec, "_ledger_sha256": canonical_hash(rec)}
                        stream.write((canonical_json(stored) + "\n").encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return records

    def read(self, kind: str, *, tolerant: bool = False,
             reader: Reader | None = None) -> list[dict]:
        path = self.ledger_path(kind)
        if not path.is_file():
            return []
        out: list[dict] = []
        revisions = {}
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ledger_hash = rec.pop("_ledger_sha256", None)
                    if ledger_hash is not None and ledger_hash != canonical_hash(rec):
                        raise IntegrityError(f"ledger envelope changed: {path.name}:{lineno}")
                    validate_record(rec, reader=reader or Reader("Project.read"))
                    if rec["kind"] != kind:
                        raise IntegrityError(f"wrong record kind in {path.name}:{lineno}")
                    if rec["revision"] <= revisions.get(rec["id"], 0):
                        raise IntegrityError(f"non-increasing revision in {path.name}:{lineno}")
                    revisions[rec["id"]] = rec["revision"]
                    out.append(rec)
                except json.JSONDecodeError as exc:
                    # Recovery is explicit: callers may inspect a prefix but
                    # formal consumers never silently fall back to old records.
                    if tolerant:
                        raise IntegrityError(f"incomplete ledger requires explicit recovery: {path.name}:{lineno}") from exc
                    raise IntegrityError(
                        f"{path.name}:{lineno} is not valid JSON: {exc}") from exc
        return out

    def latest(self, kind: str, rid: str | None = None) -> dict | None:
        # A torn last line is the expected residue of a crash mid-append; the
        # rest of the ledger is still valid, so reads tolerate it.
        rows = self.read(kind)
        if rid is not None:
            rows = [r for r in rows if r.get("id") == rid]
        if not rows:
            return None
        rows.sort(key=lambda r: (r.get("revision", 0), r.get("created_at", "")))
        return rows[-1]

    def revisions(self, kind: str, rid: str) -> list[dict]:
        rows = [r for r in self.read(kind) if r.get("id") == rid]
        rows.sort(key=lambda r: r["revision"])
        return rows

    # -- generic snapshots -------------------------------------------------
    def write_snapshot(self, rel: str, obj: Any) -> Path:
        path = self.path(rel)
        atomic_write_json(path, obj)
        return path

    def read_snapshot(self, rel: str, default: Any = None) -> Any:
        path = self.dir / rel
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    # -- counts ------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        return {k: len(self.read(k)) for k in KINDS if self.ledger_path(k).is_file()}


def atomic_write_json(path: str | os.PathLike, obj: Any) -> None:
    """Write JSON through a temp file + ``os.replace`` (never a torn file)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# migration (v1 -> v2) - never inherits "verified"
# ---------------------------------------------------------------------------
MIGRATION_LIMITS = {
    "verified": "review_pending",
    "prepared": "prepared",
}


def migrate_v1_dataset_entry(entry: Mapping, *, producer: Mapping) -> dict:
    """Build a ``cell_evidence`` skeleton for a v1 registry dataset entry.

    The v1 registry describes *datasets*, not cells; migration can only carry
    the dataset identity forward.  Status is ``candidate`` and every cell must
    be re-prepared and re-reviewed - a v1 ``verified`` receipt is never
    inherited (see A02/A47).
    """
    missing = [k for k in ("id", "path", "key", "unit") if k not in entry]
    if missing:
        raise SchemaError(f"v1 dataset entry missing {missing}")
    payload = {
        "dataset": entry["id"],
        "key": ["<composite-key>"] if isinstance(entry["key"], list) else ["<key>"],
        "column": "<migrated-dataset>",
        "value": "",
        "kind": "structural",
        "sources": [{"path": entry["path"], "sha256": entry.get("sha256", "")}],
        "origin": "v1-migration",
        "reason": "dataset identity only; cells must be re-prepared and re-read",
    }
    rec = make_record(
        "cell_evidence", f"migrated:{entry['id']}", payload, producer=producer,
        status="candidate", optional_features=("open-adapters",),
        extensions={"v1_entry": dict(entry)})
    return rec


def migration_diff(v1: Mapping, v2_records: Iterable[Mapping]) -> dict:
    """Human/machine readable report of what migration did *not* carry over."""
    recs = list(v2_records)
    inherited_verified = [
        r["id"] for r in recs
        if (r.get("extensions", {}).get("v1_status") == "verified"
            and r["status"] == "verified")
    ]
    return {
        "records": len(recs),
        "kinds": sorted({r["kind"] for r in recs}),
        "v1_status_inherited_as_verified": inherited_verified,
        "not_carried": [
            "per-cell provenance (v1 provenance.jsonl stays authoritative "
            "until re-prepared)",
            "review receipts (v1 record_sha256 bindings are recomputed, never "
            "reused)",
            "verified status (downgraded to review_pending/candidate)",
        ],
        "requires": ["re-run prepare", "re-read every cell", "re-run final"],
        "v1_keys": sorted(v1.keys()) if isinstance(v1, Mapping) else [],
    }


# ---------------------------------------------------------------------------
# schema dump
# ---------------------------------------------------------------------------
def dump_schema() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kinds": {
            kind: {
                "statuses": list(STATUSES[kind]),
                "initial": INITIAL_STATUS[kind],
                "transitions": {k: list(v) for k, v in
                                TRANSITIONS.get(kind, {}).items()},
                "required_features": list(REQUIRED_FEATURES.get(kind, ())),
                "kind_features": list(PER_KIND_FEATURES.get(kind, ())),
                "payload_required": _SCHEMAS[kind]["required"],
                "payload_optional": _SCHEMAS[kind].get("optional", {}),
            }
            for kind in KINDS
        },
        "features": FEATURES,
        "envelope": {
            "required": ["schema_version", "kind", "id", "revision", "producer",
                         "input_refs", "content_hash", "status", "created_at",
                         "data"],
            "optional": ["requires_features", "optional_features",
                         "extensions", "supersedes"],
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="v2 research record contract")
    ap.add_argument("--dump-schema")
    ap.add_argument("--validate")
    ap.add_argument("--validate-ledger")
    ap.add_argument("--migrate-v1", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    if args.dump_schema:
        atomic_write_json(args.dump_schema, dump_schema())
        print(f"wrote {args.dump_schema}")
        return 0
    if args.validate:
        rec = json.loads(Path(args.validate).read_text(encoding="utf-8"))
        validate_record(rec)
        print(f"OK: {rec['kind']} {rec['id']} r{rec['revision']} "
              f"status={rec['status']}")
        return 0
    if args.validate_ledger:
        path = Path(args.validate_ledger)
        n = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            validate_record(json.loads(line))
            n += 1
        print(f"OK: {n} record(s) in {path.name}")
        return 0
    if args.migrate_v1:
        proj = Project(args.root, create=False)
        registry_path = Path(args.root) / "research_registry.json"
        if not registry_path.is_file():
            print("no research_registry.json to migrate")
            return 2
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
        prod = producer_for("contract_v2.migrate_v1", version="2.0",
                            module_file=__file__, config={"registry": str(
                                registry_path)})
        recs = [migrate_v1_dataset_entry(e, producer=prod)
                for e in reg.get("datasets", [])]
        out = proj.write_snapshot("migration/v1_to_v2.json",
                                  migration_diff(reg, recs))
        print(f"migration report: {out}")
        print(f"records prepared: {len(recs)} (nothing was marked verified)")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":            # pragma: no cover - CLI
    try:
        sys.exit(_main(sys.argv[1:]))
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
