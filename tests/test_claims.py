# -*- coding: utf-8 -*-
"""Claims, manuscript blocks and support relations (plan R08).

Covers the acceptance scenarios this module is responsible for:

* A32 - a sentence whose numbers are right but whose direction, extremum,
  denominator/unit or association-vs-causation reading is wrong must be caught;
* A33 - a real reference that was only read as an abstract must not be
  presented as full-text support (and an unavailable one stays pending);
* A53 - editing a block invalidates the old support markers: the claim is
  ``stale`` until it is re-registered against the new text, and the text
  extracted from the final DOCX/PDF is compared with the reviewed text.

Expected values are computed here, independently of the module under test:
the fingerprint test re-implements the documented normalisation, the ranking
tests spell out the comparison set by hand.
"""
import hashlib
import json
import os
import re
import unicodedata

from _helpers import SCRIPTS, TempCase, run

import claims
import contract_v2 as C
import depgraph

PRODUCER = C.producer_for("test.claims", version="0",
                          module_file=os.path.join(SCRIPTS, "claims.py"))


# ---------------------------------------------------------------------------
# independent expectations / fixtures
# ---------------------------------------------------------------------------
def expected_fingerprint(text):
    """The documented normalisation (NFKC, no punctuation, single spaces)."""
    s = unicodedata.normalize("NFKC", text)
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("P"))
    s = re.sub(r"\s+", " ", s).strip()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def result_record(rid, estimate, *, result_type="ols_coefficient",
                  unit="coefficient", target_parameter="beta",
                  denominator=None, time_scope=None):
    payload = {
        "model": "M1",
        "result_type": result_type,
        "payload": {"estimate": estimate},
        "target_parameter": target_parameter,
        "unit": unit,
        "sample_scope": {"n": 64},
    }
    if estimate is not None:
        payload["estimate"] = estimate
    if denominator is not None:
        payload["denominator"] = denominator
    if time_scope is not None:
        payload["time_scope"] = time_scope
    return C.make_record("model_result", rid, payload, producer=PRODUCER)


def reference_record(rid, level, *, year="2020"):
    payload = {"cite_id": rid, "authors": "Smith J.", "title": "A study of X",
               "year": year, "venue": "Journal of X",
               "access": {"level": level}}
    return C.make_record("reference", rid, payload, producer=PRODUCER)


def finding(result, name):
    hits = [f for f in result["findings"] if f["check"] == name]
    assert hits, ("no %r finding; got %r"
                  % (name, [f["check"] for f in result["findings"]]))
    return hits[0]


def failing_checks(result):
    return [f["check"] for f in result["findings"] if not f["ok"]]


class ClaimsCase(TempCase):
    def setUp(self):
        super().setUp()
        self.project = C.Project(self.tmp)

    # -- fixtures ----------------------------------------------------------
    def make_block(self, text, block_id="b1", section="results"):
        return claims.register_block(self.project, block_id=block_id,
                                     section=section, text=text, claims=[])

    def make_claim(self, text, support, *, claim_id, claim_type="result",
                   block_id="b1", section="results", scope=None):
        return claims.register_claim(self.project, claim_type=claim_type,
                                     text=text, block_id=block_id,
                                     section=section, support=support,
                                     scope=scope, claim_id=claim_id)

    def status_of(self, kind, rid):
        rec = self.project.latest(kind, rid)
        return rec["status"] if rec else None


# ---------------------------------------------------------------------------
# A32: direction
# ---------------------------------------------------------------------------
class TestDirection(ClaimsCase):
    def test_direction_written_backwards_is_contradicted(self):
        text = "干预使得分提高了 0.32 分。"
        self.make_block(text)
        self.make_claim("干预使得分提高了 0.32 分",
                        [{"kind": "result", "id": "r1",
                          "target_parameter": "beta"}],
                        claim_id="cl_dir")

        negative = result_record("r1", "-0.32")
        res = claims.check_claim(self.project, "cl_dir", results=[negative])
        self.assertEqual(res["status"], "contradicted", failing_checks(res))
        self.assertFalse(finding(res, "direction")["ok"])
        # the printed magnitude is right; only the sign is wrong
        self.assertIn("-0.32", json.dumps(finding(res, "direction")["detail"],
                                          ensure_ascii=False))

        positive = result_record("r1", "0.32")
        ok = claims.check_claim(self.project, "cl_dir", results=[positive])
        self.assertEqual(ok["status"], "supported", failing_checks(ok))
        self.assertTrue(finding(ok, "direction")["ok"])


# ---------------------------------------------------------------------------
# A32: association described as causation
# ---------------------------------------------------------------------------
class TestCausation(ClaimsCase):
    def test_association_written_as_causation_is_contradicted(self):
        self.make_block("干预导致了得分的提高。")
        self.make_claim("干预导致了得分的提高",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_cause")

        ols = result_record("r1", "0.32", result_type="ols_coefficient")
        res = claims.check_claim(self.project, "cl_cause", results=[ols])
        self.assertEqual(res["status"], "contradicted", failing_checks(res))
        causal = finding(res, "causal")
        self.assertFalse(causal["ok"])
        self.assertIn("ols_coefficient",
                      json.dumps(causal["detail"], ensure_ascii=False))

        rct = result_record("r1", "0.32", result_type="rct")
        ok = claims.check_claim(self.project, "cl_cause", results=[rct])
        self.assertEqual(ok["status"], "supported", failing_checks(ok))


# ---------------------------------------------------------------------------
# A33: reference access
# ---------------------------------------------------------------------------
class TestReferenceAccess(ClaimsCase):
    def test_abstract_only_reference_cannot_claim_full_text(self):
        self.project.append("reference", reference_record("ref1", "abstract"))
        text = "既有研究已经检验过该项目。"
        self.make_block(text)

        self.make_claim("既有研究已经检验过该项目",
                        [{"kind": "reference", "id": "ref1"}],
                        claim_id="cl_ref_over", claim_type="literature",
                        scope={"access": "full_text"})
        over = claims.check_claim(self.project, "cl_ref_over")
        self.assertEqual(over["status"], "contradicted", failing_checks(over))
        self.assertFalse(finding(over, "reference_access")["ok"])

        self.make_claim("既有研究已经检验过该项目",
                        [{"kind": "reference", "id": "ref1"}],
                        claim_id="cl_ref_honest", claim_type="literature",
                        scope={"access": "abstract"})
        honest = claims.check_claim(self.project, "cl_ref_honest")
        self.assertEqual(honest["status"], "supported",
                         failing_checks(honest))

        self.project.append("reference", reference_record("ref2", "unavailable"))
        self.make_claim("既有研究已经检验过该项目",
                        [{"kind": "reference", "id": "ref2"}],
                        claim_id="cl_ref_gone", claim_type="literature",
                        scope={"access": "full_text"})
        gone = claims.check_claim(self.project, "cl_ref_gone")
        self.assertEqual(gone["status"], "pending", failing_checks(gone))


# ---------------------------------------------------------------------------
# A32: denominator and unit
# ---------------------------------------------------------------------------
class TestDenominatorAndUnit(ClaimsCase):
    def test_missing_denominator_is_unsupported(self):
        self.make_block("干预组占 62%（40/64）。")
        self.make_claim("干预组占 62%（40/64）",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_den_missing")
        res = claims.check_claim(
            self.project, "cl_den_missing",
            results=[result_record("r1", "0.62", denominator="N=64")])
        self.assertEqual(res["status"], "unsupported", failing_checks(res))
        self.assertFalse(finding(res, "denominator")["ok"])

    def test_denominator_and_unit_mismatch_are_contradicted(self):
        self.make_block("干预组占 62%（40/64）。")
        self.make_claim("干预组占 62%（40/64）",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_den_bad",
                        scope={"denominator": "N=100"})
        res = claims.check_claim(
            self.project, "cl_den_bad",
            results=[result_record("r1", "0.62", denominator="N=64")])
        self.assertEqual(res["status"], "contradicted", failing_checks(res))
        self.assertFalse(finding(res, "denominator")["ok"])

        self.make_claim("干预组得分更高",
                        [{"kind": "result", "id": "r2"}],
                        claim_id="cl_unit_bad", scope={"unit": "person"})
        res2 = claims.check_claim(
            self.project, "cl_unit_bad",
            results=[result_record("r2", "0.32", unit="coefficient")])
        self.assertEqual(res2["status"], "contradicted", failing_checks(res2))
        self.assertFalse(finding(res2, "unit")["ok"])


# ---------------------------------------------------------------------------
# A32: highest/lowest against the comparison set
# ---------------------------------------------------------------------------
class TestExtremum(ClaimsCase):
    def test_extremum_must_match_the_comparison_set(self):
        pool = [result_record("r1", "0.90"),
                result_record("r2", "0.50"),
                result_record("r3", "0.20")]
        self.make_block("模型一的系数最高。")

        self.make_claim("模型一的系数最高",
                        [{"kind": "result", "id": "r1",
                          "target_parameter": "beta"}],
                        claim_id="cl_max_ok",
                        scope={"rank_of": 1, "rank_total": 3})
        ok = claims.check_claim(self.project, "cl_max_ok", results=pool)
        self.assertEqual(ok["status"], "supported", failing_checks(ok))
        self.assertTrue(finding(ok, "extremum")["ok"])

        self.make_claim("模型二的系数最高",
                        [{"kind": "result", "id": "r2",
                          "target_parameter": "beta"}],
                        claim_id="cl_max_bad",
                        scope={"rank_of": 1, "rank_total": 3})
        bad = claims.check_claim(self.project, "cl_max_bad", results=pool)
        self.assertEqual(bad["status"], "contradicted", failing_checks(bad))
        self.assertFalse(finding(bad, "extremum")["ok"])

        self.make_claim("模型三的系数最低",
                        [{"kind": "result", "id": "r3",
                          "target_parameter": "beta"}],
                        claim_id="cl_min_ok",
                        scope={"rank_of": 3, "rank_total": 3})
        low = claims.check_claim(self.project, "cl_min_ok", results=pool)
        self.assertEqual(low["status"], "supported", failing_checks(low))
        self.assertTrue(finding(low, "extremum")["ok"])

        self.make_claim("模型一的系数最高",
                        [{"kind": "result", "id": "r1",
                          "target_parameter": "beta"}],
                        claim_id="cl_max_norank")
        norank = claims.check_claim(self.project, "cl_max_norank",
                                    results=pool)
        self.assertEqual(norank["status"], "unsupported",
                         failing_checks(norank))
        self.assertFalse(finding(norank, "extremum")["ok"])


# ---------------------------------------------------------------------------
# A32: time scope (extrapolation is a warning, not a contradiction)
# ---------------------------------------------------------------------------
class TestTimeScope(ClaimsCase):
    def test_time_scope_extrapolation_is_a_warning(self):
        self.make_block("2015—2023 年间干预效应持续提高。")
        self.make_claim("2015—2023 年间干预效应持续提高",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_time_wide",
                        scope={"time_scope": "2015-2023"})
        wide = claims.check_claim(
            self.project, "cl_time_wide",
            results=[result_record("r1", "0.32", time_scope="2019-2021")])
        self.assertEqual(wide["status"], "unsupported", failing_checks(wide))
        time_finding = finding(wide, "time_scope")
        self.assertFalse(time_finding["ok"])
        self.assertEqual(time_finding["severity"], "warning")
        self.assertEqual(wide["warnings"], 1)

        self.make_claim("2020 年间干预效应持续提高",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_time_inside",
                        scope={"time_scope": "2020-2020"})
        inside = claims.check_claim(
            self.project, "cl_time_inside",
            results=[result_record("r1", "0.32", time_scope="2019-2021")])
        self.assertEqual(inside["status"], "supported", failing_checks(inside))
        self.assertTrue(finding(inside, "time_scope")["ok"])


# ---------------------------------------------------------------------------
# support presence
# ---------------------------------------------------------------------------
class TestSupportPresence(ClaimsCase):
    def test_factual_claim_needs_support_but_connection_does_not(self):
        self.make_block("样本量为 2713。下一节报告模型结果。")

        self.make_claim("样本量为 2713。", [], claim_id="cl_bare")
        res = claims.check_claim(self.project, "cl_bare")
        self.assertEqual(res["status"], "unsupported", failing_checks(res))
        self.assertFalse(finding(res, "support_missing")["ok"])

        self.make_claim("下一节报告模型结果。", [], claim_id="cl_conn",
                        claim_type="connection")
        conn = claims.check_claim(self.project, "cl_conn")
        self.assertEqual(conn["status"], "supported", failing_checks(conn))
        self.assertTrue(finding(conn, "support_missing")["ok"])
        self.assertFalse(finding(conn, "support_missing")["applicable"])


# ---------------------------------------------------------------------------
# A53: block edits invalidate the old support markers
# ---------------------------------------------------------------------------
class TestBlockIdentity(ClaimsCase):
    original = "干预组的得分显著提高了 12.5 分（N = 64）。"
    edited = "对照组的得分显著提高了 12.5 分（N = 64）。"

    def test_editing_block_text_without_reregistering_claims_makes_them_stale(self):
        block = self.make_block(self.original)
        self.make_claim("干预组的得分显著提高了 12.5 分",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_edit")

        first = claims.review_block(self.project, block)
        self.assertEqual(first["status"], "reviewed", failing_checks(first))

        second = claims.review_block(
            self.project,
            {"block_id": "b1", "text": self.edited, "claims": ["cl_edit"]})
        self.assertEqual(second["status"], "stale")
        self.assertFalse(finding(second, "claim_not_reregistered")["ok"])
        self.assertEqual(self.status_of("claim", "cl_edit"), "stale")
        self.assertEqual(self.status_of("manuscript_block", "b1"), "stale")

    def test_printed_text_mismatch_makes_block_stale(self):
        block = self.make_block(self.original)
        self.make_claim("干预组的得分显著提高了 12.5 分",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_print")

        printed = self.original.replace("12.5", "12.7")
        bad = claims.review_block(self.project, block, printed_text=printed)
        self.assertEqual(bad["status"], "stale")
        self.assertFalse(finding(bad, "printed_text_mismatch")["ok"])
        self.assertEqual(self.status_of("manuscript_block", "b1"), "stale")

        # typographic noise (width/wrapping) is not a content difference
        cosmetic = (self.original.replace("（", "(").replace("）", ")")
                    + "   ")
        good = claims.review_block(self.project, block, printed_text=cosmetic)
        self.assertEqual(good["status"], "reviewed", failing_checks(good))
        self.assertEqual(self.status_of("manuscript_block", "b1"), "reviewed")


# ---------------------------------------------------------------------------
# A53: propagation through the dependency graph
# ---------------------------------------------------------------------------
class TestPropagate(ClaimsCase):
    def test_propagate_stales_claims_and_blocks_after_result_change(self):
        text = ("干预组的得分显著提高了 12.5 分（N = 64）。"
                "对照组的得分下降了 3.1 分。")
        self.make_block(text)
        self.make_claim("干预组的得分显著提高了 12.5 分",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_prop")
        self.make_claim("对照组的得分下降了 3.1 分",
                        [{"kind": "result", "id": "r2"}],
                        claim_id="cl_other")

        graph = depgraph.DependencyGraph(self.project)
        graph.register("result", "r1", "sha256:aaa")
        graph.register("claim", "cl_prop", "sha256:bbb")
        graph.register("manuscript_block", "b1", "sha256:ccc")
        graph.add_edge("result:r1", "claim:cl_prop", "cites")
        graph.add_edge("claim:cl_prop", "manuscript_block:b1", "presents")

        report = claims.propagate(self.project, ["result:r1"])
        self.assertIn("cl_prop", report["claims"])
        self.assertIn("b1", report["blocks"])
        self.assertNotIn("cl_other", report["claims"])
        self.assertEqual(self.status_of("claim", "cl_prop"), "stale")
        self.assertEqual(self.status_of("claim", "cl_other"), "draft")
        self.assertEqual(self.status_of("manuscript_block", "b1"), "stale")
        self.assertTrue(any(r["kind"] == "claim" and r["id"] == "cl_prop"
                            and r["to"] == "stale" for r in report["records"]))


# ---------------------------------------------------------------------------
# ledger / fingerprint
# ---------------------------------------------------------------------------
class TestLedger(ClaimsCase):
    def test_claim_records_land_in_the_v2_ledger_and_validate(self):
        text = "干预组的得分显著提高了 12.5 分（N = 64）。"
        fragment = "干预组的得分显著提高了 12.5 分"
        self.make_block(text)
        self.make_claim(fragment,
                        [{"kind": "result", "id": "r1",
                          "target_parameter": "beta"}],
                        claim_id="cl_ledger")

        path = os.path.join(self.tmp, "output", "v2", "claim.jsonl")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(rows), 1)
        rec = rows[0]
        C.validate_record(rec)
        self.assertEqual(rec["kind"], "claim")
        self.assertEqual(rec["id"], "cl_ledger")
        self.assertEqual(rec["status"], "draft")
        self.assertEqual(rec["revision"], 1)
        self.assertEqual(rec["data"]["text_fingerprint"],
                         expected_fingerprint(fragment))
        self.assertEqual(rec["data"]["support"],
                         [{"kind": "result", "id": "r1",
                           "target_parameter": "beta"}])
        self.assertEqual(rec["data"]["section"], "results")
        self.assertEqual(rec["data"]["block_id"], "b1")
        self.assertEqual(rec["producer"]["program"], "claims")
        self.assertEqual(len(rec["producer"]["code_sha256"]), 64)
        self.assertIn("claim-support", rec["requires_features"])

        block_path = os.path.join(self.tmp, "output", "v2",
                                  "manuscript_block.jsonl")
        with open(block_path, encoding="utf-8") as fh:
            block_rows = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(block_rows), 1)
        C.validate_record(block_rows[0])
        self.assertEqual(block_rows[0]["status"], "draft")
        self.assertEqual(block_rows[0]["data"]["fingerprint"],
                         expected_fingerprint(text))

    def test_fingerprint_ignores_punctuation_and_whitespace_only(self):
        self.assertEqual(claims.fingerprint("均值 上升了 12.5%。"),
                         claims.fingerprint("均值 上升了 12.5%"))
        self.assertEqual(claims.fingerprint("均值 上升了 12.5%。"),
                         expected_fingerprint("均值 上升了 12.5%。"))
        self.assertNotEqual(claims.fingerprint("上升"), claims.fingerprint("下降"))


# ---------------------------------------------------------------------------
# support links / invalidation
# ---------------------------------------------------------------------------
class TestSupportLinks(ClaimsCase):
    def test_link_support_bumps_revision_dedupes_and_invalidate_stales(self):
        self.make_block("干预组的得分显著提高了 12.5 分。")
        claim = self.make_claim("干预组的得分显著提高了 12.5 分",
                                [{"kind": "result", "id": "r1"}],
                                claim_id="cl_link")
        self.assertEqual(claim["revision"], 1)

        linked = claims.link_support(self.project, claim,
                                     {"kind": "reference", "id": "ref1"})
        self.assertEqual(linked["revision"], 2)
        self.assertEqual([s["id"] for s in linked["data"]["support"]],
                         ["r1", "ref1"])
        self.assertEqual(linked["status"], "pending")

        again = claims.link_support(self.project, linked,
                                    {"kind": "reference", "id": "ref1"})
        self.assertEqual(len(again["data"]["support"]), 2)
        self.assertEqual(again["revision"], 3)

        stale = claims.invalidate(self.project, again,
                                  "upstream result withdrawn")
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["extensions"]["transition_reason"],
                         "upstream result withdrawn")
        self.assertEqual(self.status_of("claim", "cl_link"), "stale")


# ---------------------------------------------------------------------------
# numbers
# ---------------------------------------------------------------------------
class TestNumbers(ClaimsCase):
    def test_untraceable_numbers_are_unsupported(self):
        self.make_block("干预组 N={table1_n}，β={beta}。")
        self.make_claim("干预组 N={table1_n}，β={beta}",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_num")
        result = [result_record("r1", "0.32")]

        missing = claims.check_claim(self.project, "cl_num", results=result)
        self.assertEqual(missing["status"], "unsupported",
                         failing_checks(missing))
        self.assertFalse(finding(missing, "numbers")["ok"])

        ok = claims.check_claim(self.project, "cl_num", results=result,
                                numbers={"table1_n": 64, "beta": 0.32})
        self.assertEqual(ok["status"], "supported", failing_checks(ok))

    def test_printed_percentage_must_match_the_supplied_number(self):
        self.make_block("干预组有效率为 62%。")
        self.make_claim("干预组有效率为 62%",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_pct", scope={"denominator": "N=64"})
        result = [result_record("r1", "0.62", denominator="N=64")]

        wrong = claims.check_claim(self.project, "cl_pct", results=result,
                                  numbers={"rate": 0.71})
        self.assertEqual(wrong["status"], "unsupported",
                         failing_checks(wrong))
        self.assertFalse(finding(wrong, "numbers")["ok"])

        right = claims.check_claim(self.project, "cl_pct", results=result,
                                   numbers={"rate": 0.62})
        self.assertEqual(right["status"], "supported", failing_checks(right))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCli(ClaimsCase):
    def test_cli_blocks_check_and_propagate(self):
        text = "干预组的得分显著提高了 12.5 分（N = 64）。"
        self.make_block(text)
        self.make_claim("干预组的得分显著提高了 12.5 分",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_cli")
        self.project.append("model_result", result_record("r1", "12.5"))

        listed = run("claims.py", "--root", self.tmp, "blocks")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        payload = json.loads(listed.stdout)
        self.assertEqual([b["block_id"] for b in payload["blocks"]], ["b1"])
        self.assertEqual(payload["blocks"][0]["claims"], [])

        checked = run("claims.py", "--root", self.tmp, "check",
                      "--claim", "cl_cli")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["status"], "supported")
        self.assertEqual(self.status_of("claim", "cl_cli"), "supported")

        moved = run("claims.py", "--root", self.tmp, "propagate",
                    "--changed", "r1")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        report = json.loads(moved.stdout)
        self.assertIn("cl_cli", report["claims"])
        self.assertIn("b1", report["blocks"])
        self.assertEqual(self.status_of("claim", "cl_cli"), "stale")

    def test_cli_review_records_and_refuses_cleanly(self):
        text = "干预组的得分显著提高了 12.5 分（N = 64）。"
        self.make_block(text)
        self.make_claim("干预组的得分显著提高了 12.5 分",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_rev")
        self.project.append("model_result", result_record("r1", "12.5"))
        checked = run("claims.py", "--root", self.tmp, "check",
                      "--claim", "cl_rev")
        self.assertEqual(checked.returncode, 0, checked.stderr)

        scopes_path = os.path.join(self.tmp, "scopes.json")
        material = os.path.join(self.tmp, "materials")
        os.makedirs(material, exist_ok=True)
        source = os.path.join(material, "a1.txt")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("干预组的得分显著提高了 12.5 分（N = 64）。\n")
        import hashlib
        with open(source, "rb") as handle:
            source_sha = hashlib.sha256(handle.read()).hexdigest()
        with open(scopes_path, "w", encoding="utf-8") as handle:
            json.dump([{"path": "materials/a1.txt",
                        "sha256": source_sha,
                        "locator": "p1:c0-120"}], handle,
                      ensure_ascii=False)
        reviewed = run("claims.py", "--root", self.tmp, "review",
                       "--claim", "cl_rev", "--decision", "supported",
                       "--reviewer", "reviewer-1",
                       "--note", "re-read the source span",
                       "--scopes", scopes_path)
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        self.assertIn("semantic_review", reviewed.stdout)

        # a machine-contradicted claim cannot be overridden: FAIL + 2
        self.make_block("干预使得分提高了 0.32 分。")
        self.make_claim("干预使得分提高了 0.32 分",
                        [{"kind": "result", "id": "r2"}],
                        claim_id="cl_rev_bad")
        self.project.append("model_result", result_record("r2", "-0.32"))
        run("claims.py", "--root", self.tmp, "check",
            "--claim", "cl_rev_bad")
        blocked = run("claims.py", "--root", self.tmp, "review",
                      "--claim", "cl_rev_bad", "--decision", "supported",
                      "--reviewer", "reviewer-1", "--note", "no",
                      "--scopes", scopes_path)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("FAIL:", blocked.stderr)
        self.assertNotIn("Traceback", blocked.stderr)

        # a missing scopes file is a clean CLI error, not a traceback
        missing = run("claims.py", "--root", self.tmp, "review",
                      "--claim", "cl_rev", "--decision", "supported",
                      "--reviewer", "reviewer-1", "--note", "x",
                      "--scopes", os.path.join(self.tmp, "nope.json"))
        self.assertEqual(missing.returncode, 2)
        self.assertIn("FAIL: cannot read --scopes", missing.stderr)
        self.assertNotIn("Traceback", missing.stderr)

        # a malformed scopes file is also a clean CLI error
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        malformed = run("claims.py", "--root", self.tmp, "review",
                        "--claim", "cl_rev", "--decision", "supported",
                        "--reviewer", "reviewer-1", "--note", "x",
                        "--scopes", bad)
        self.assertEqual(malformed.returncode, 2)
        self.assertIn("not valid JSON", malformed.stderr)
        self.assertNotIn("Traceback", malformed.stderr)


# ---------------------------------------------------------------------------
# batch 2: clause-level negation and anaphora the machine cannot resolve
# ---------------------------------------------------------------------------
def findings_named(result, name):
    return [f for f in result["findings"] if f["check"] == name]


class TestCueNegation(ClaimsCase):
    def test_adjacent_negation_still_resolves_on_its_own(self):
        # the four-character window handles this classic shape: the cue is
        # skipped, nothing is ambiguous, and no warning fires
        self.make_block("得分不再上升。")
        self.make_claim("得分不再上升",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg1")
        res = claims.check_claim(
            self.project, "cl_neg1",
            results=[result_record("r1", "-3.1")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertEqual(findings_named(res, "cue_negation"), [])
        self.assertTrue(finding(res, "direction")["applicable"] is False)

    def test_long_range_negation_is_a_warning_not_a_false_contradiction(self):
        # the negator sits beyond the adjacent window; the old logic
        # trusted the cue and fired a false contradiction against the
        # negative estimate - now the cue is pulled out of the verdict and
        # the sentence is routed to a human read
        self.make_block("并没有因此出现明显的上升。")
        self.make_claim("并没有因此出现明显的上升",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg2")
        res = claims.check_claim(
            self.project, "cl_neg2",
            results=[result_record("r1", "-3.1")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertEqual(res["warnings"], 1)
        neg = finding(res, "cue_negation")
        self.assertFalse(neg["ok"])
        self.assertEqual(neg["severity"], "warning")
        self.assertIn("上升", neg["detail"]["families"]["direction"])
        self.assertTrue(finding(res, "direction")["applicable"] is False)

    def test_contrast_marker_keeps_the_cue_clean(self):
        # the comma splits the clauses; the cue clause carries no negator
        # and the rise is asserted exactly as before
        self.make_block("增速没有回落，反而出现上升。")
        self.make_claim("增速没有回落，反而出现上升",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg3")
        res = claims.check_claim(
            self.project, "cl_neg3",
            results=[result_record("r1", "0.4")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertTrue(finding(res, "direction")["ok"])
        self.assertEqual(findings_named(res, "cue_negation"), [])

    def test_unresolved_negation_does_not_touch_true_contradictions(self):
        # a clean cue with no clause negator still contradicts a negative
        # estimate exactly as before (the extra failing finding is the
        # numbers check: the printed 0.32 is a different token than the
        # supplied estimate -0.32)
        self.make_block("干预使得分提高了 0.32 分。")
        self.make_claim("干预使得分提高了 0.32 分",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg4")
        res = claims.check_claim(
            self.project, "cl_neg4",
            results=[result_record("r1", "-0.32")])
        self.assertEqual(res["status"], "contradicted", failing_checks(res))
        self.assertFalse(finding(res, "direction")["ok"])
        self.assertEqual(finding(res, "direction")["severity"], "error")

    def test_negated_causal_cue_is_not_a_causal_claim(self):
        # the causal cue sits behind an unresolved negator, so the
        # association-vs-causation check must not treat the sentence as
        # asserting causation
        self.make_block("不能说该政策导致了改善。")
        self.make_claim("不能说该政策导致了改善",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg5")
        res = claims.check_claim(
            self.project, "cl_neg5",
            results=[result_record("r1", "0.32",
                                    result_type="ols_coefficient")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        causal = finding(res, "causal")
        self.assertTrue(causal["ok"])
        neg = finding(res, "cue_negation")
        self.assertIn("导致", neg["detail"]["families"]["causal"])

    def test_governed_contrast_inside_one_clause_keeps_the_cue(self):
        # "增速没有下降反而扩大" keeps the negation on 下降 and the
        # contrast rescues 扩大: the growth cue stays clean
        self.make_block("增速没有下降反而扩大。")
        self.make_claim("增速没有下降反而扩大",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg6")
        res = claims.check_claim(
            self.project, "cl_neg6",
            results=[result_record("r1", "0.2")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertTrue(finding(res, "direction")["ok"])
        self.assertEqual(findings_named(res, "cue_negation"), [])

    def test_english_long_range_negation_warns(self):
        self.make_block("The effect showed no significant increase.")
        self.make_claim("The effect showed no significant increase",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg7")
        res = claims.check_claim(
            self.project, "cl_neg7",
            results=[result_record("r1", "-1.2")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        neg = finding(res, "cue_negation")
        self.assertIn("increase", neg["detail"]["families"]["direction"])
        self.assertEqual(res["warnings"], 1)

    def test_contracted_english_negation_is_never_decided(self):
        # "didn't increase": the adjacent window once missed the
        # contraction, the cue fired a false contradiction against a
        # negative estimate, and no warning was raised - now the cue is
        # pulled out and the sentence is routed to a human read
        self.make_block("The model didn't show any increase.")
        self.make_claim("The model didn't show any increase",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg8")
        res = claims.check_claim(
            self.project, "cl_neg8",
            results=[result_record("r1", "-1.2")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertEqual(res["errors"], 0)
        self.assertEqual(res["warnings"], 1)
        neg = finding(res, "cue_negation")
        self.assertIn("increase", neg["detail"]["families"]["direction"])
        self.assertTrue(finding(res, "direction")["applicable"] is False)

    def test_contracted_english_negation_cannot_falsely_support(self):
        # the mirror bug: "didn't increase" with a positive estimate used
        # to read as a clean supported rise; now the cue is pulled out of
        # the verdict entirely and the sentence still needs a human read
        self.make_block("The group's scores didn't increase.")
        self.make_claim("The group's scores didn't increase",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg9")
        res = claims.check_claim(
            self.project, "cl_neg9",
            results=[result_record("r1", "0.5")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertEqual(res["errors"], 0)
        self.assertEqual(res["warnings"], 1)
        self.assertTrue(finding(res, "direction")["applicable"] is False)

    def test_contracted_english_causal_negation_warns(self):
        self.make_block("The program didn't cause any improvement.")
        self.make_claim("The program didn't cause any improvement",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg10")
        res = claims.check_claim(
            self.project, "cl_neg10",
            results=[result_record("r1", "0.32",
                                    result_type="ols_coefficient")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertEqual(res["errors"], 0)
        self.assertEqual(res["warnings"], 1)
        causal = finding(res, "causal")
        self.assertTrue(causal["ok"])
        neg = finding(res, "cue_negation")
        self.assertIn("cause", neg["detail"]["families"]["causal"])

    def test_contracted_negation_with_contrast_keeps_the_cue(self):
        # "didn't decrease but increased": the contrast marker rescues
        # the clean cue after the negator, and the increase contradicts a
        # negative estimate exactly as a clean rise would
        self.make_block("The scores didn't decrease but increased.")
        self.make_claim("The scores didn't decrease but increased",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_neg11")
        res = claims.check_claim(
            self.project, "cl_neg11",
            results=[result_record("r1", "-0.3")])
        self.assertEqual(res["status"], "contradicted", failing_checks(res))
        self.assertTrue(finding(res, "direction")["ok"] is False)
        # the negated half is warned, the rescued half fires
        neg = finding(res, "cue_negation")
        self.assertIn("decrease", neg["detail"]["families"]["direction"])


class TestAnaphora(ClaimsCase):
    def test_pronoun_subject_on_cue_clause_warns(self):
        self.make_block("该效应显著上升。")
        self.make_claim("该效应显著上升",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_ana1")
        res = claims.check_claim(
            self.project, "cl_ana1",
            results=[result_record("r1", "0.4")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertEqual(res["warnings"], 1)
        ana = finding(res, "anaphora")
        self.assertFalse(ana["ok"])
        self.assertEqual(ana["severity"], "warning")
        self.assertIn("该效应", json.dumps(ana["detail"],
                                           ensure_ascii=False))

    def test_named_subject_does_not_warn(self):
        self.make_block("干预组的均值显著上升。")
        self.make_claim("干预组的均值显著上升",
                        [{"kind": "result", "id": "r1"}],
                        claim_id="cl_ana2")
        res = claims.check_claim(
            self.project, "cl_ana2",
            results=[result_record("r1", "0.4")])
        self.assertEqual(res["status"], "supported", failing_checks(res))
        self.assertEqual(findings_named(res, "anaphora"), [])
