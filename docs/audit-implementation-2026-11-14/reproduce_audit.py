"""Independent adversarial audit. Synthetic fixtures only; no production edits.

Each case asserts the required safe behavior. A failed assertion confirms the
reported counterexample, not a failure of the fixture runner. Unexpected fixture
exceptions are reported separately and do not count as confirmed findings.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "empirical-research-pipeline/scripts"), str(ROOT / "tests")]
import contract_v2 as C
import claims as CL
import designcheck as DC
import gaps as G
import manuscript as MS
import models as M
import ocr_provider as OCR
import release as R
import review_workbench as WB
import search_index as SI
import source_units as SU
import txn as T
import validation as V
import verify_dataset as VD
from test_discovery_review import build_project
from test_models_entities import make_linear_data, spec_for

CASES = []


def case(ident, expected):
    def decorate(fn):
        CASES.append((ident, expected, fn))
        return fn
    return decorate


def math_spec(root, family, params):
    source = root / "problem.json"
    source.write_text(json.dumps(params), encoding="utf-8")
    return {"id": "OPT", "family": family, "purpose": "synthetic audit",
            "inputs": [{"role": "constraints", "dataset": "problem.json",
                        "sha256": C.file_sha256(source), "keys": ["constraint"]}],
            "n_semantics": {"kind": "none"}, "dimensions": 1,
            "constraints": ["as declared in problem.json"], "parameters": params,
            "result": {"type": "optimum", "target_parameter": "objective",
                       "unit": "synthetic", "scale": "linear"}}


@case("C01", "An unbound status-only JSON cannot prove dataset verification.")
def fake_report(root, p, out):
    (root / "fake.json").write_text(json.dumps({"status": "verified", "error_count": 0,
                                    "datasets": {"nonexistent": {"status": "verified"}}}))
    result = R.evaluate(p, {"datasets": ["nonexistent"], "verification": "fake.json"})
    out.update(status=result["status"], errors=result["errors"], dataset_exists=False)
    assert result["status"] != "complete", "nonexistent dataset released as complete"


@case("C02", "A model without any source review or method assessment cannot be complete.")
def unreviewed_model(root, p, out):
    make_linear_data(str(root))
    M.register(p, spec_for(str(root)))
    M.fit(p, "M1")
    V.independent_ols(p, "M1")
    spec = p.latest("model_spec", "M1")
    release = R.evaluate(p, {"models": ["M1"]})
    out.update(status=release["status"], method_assessment=spec["data"].get("method_assessment"),
               verification_exists=(root / "output/dataset/dataset_verification.json").exists(),
               errors=release["errors"])
    assert release["status"] != "complete", "unreviewed input and unassessed model released"


@case("C03", "Normal ledger reads must reject content whose stored digest was not updated.")
def tampered_claim(root, p, out):
    data = {"claim_type": "descriptive", "text": "synthetic claim", "block_id": "B1",
            "text_fingerprint": "a" * 64, "support": []}
    rec = C.make_record("claim", "C1", data, producer=C.producer_for("audit"), status="draft")
    p.append("claim", rec)
    rec["status"] = "supported"
    rec["data"]["text"] = "edited unsupported synthetic claim"
    p.ledger_path("claim").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    rejected = False
    try:
        rows = p.read("claim")
        release = R.evaluate(p, {"claims": ["C1"]})
        out.update(read_status=rows[0]["status"], release_status=release["status"])
    except C.ContractError as exc:
        rejected = True
        out["rejected"] = str(exc)
    try:
        C.validate_record(rec)
    except C.ContractError as exc:
        out["explicit_validator"] = str(exc)
    assert rejected, "read/release consumed digest-tampered supported claim"


@case("C04", "MILP min x with x >= 0.5 and integer x has optimum x=1, objective=1.")
def milp(root, p, out):
    spec = math_spec(root, "milp", {"c": [1], "A_ub": [[-1]], "b_ub": [-0.5],
                                    "bounds": [[0, None]], "integrality": [1]})
    M.register(p, spec)
    M.solve(p, "OPT")
    result = p.latest("model_result", "OPT")["data"]["payload"]
    out.update(result)
    assert abs(result["solution"][0] - 1) < 1e-8, "integer requirement silently dropped"


@case("C05", "For min x^2 subject to x >= 2, a reported optimum must satisfy x >= 2.")
def nonlinear_bounds(root, p, out):
    objective = root / "objective.py"
    objective.write_text("def objective(x):\n    return float(x[0] ** 2)\n", encoding="utf-8")
    spec = math_spec(root, "nonlinear", {"objective": str(objective) + ":objective",
                                        "dimensions": 1, "x0": [2], "bounds": [[2, None]]})
    M.register(p, spec)
    M.solve(p, "OPT")
    result = p.latest("model_result", "OPT")["data"]["payload"]
    out.update(result)
    assert result["solution"][0] >= 2 - 1e-8, "bound-violating solution called local optimum"


@case("C06", "A user-specified model family with a custom executor is registerable.")
def open_family(root, p, out):
    make_linear_data(str(root))
    spec = spec_for(str(root), family="cox")
    spec["runner"] = "user_runner.py:fit"
    accepted = False
    try:
        M.register(p, spec)
        accepted = True
    except M.ModelError as exc:
        out["error"] = str(exc)
    assert accepted, "fixed family whitelist rejects extension"


@case("C07", "The public fit(runner=...) argument must invoke the supplied executor.")
def custom_runner(root, p, out):
    make_linear_data(str(root))
    M.register(p, spec_for(str(root), family="gee"))
    called = []
    def runner(*args, **kwargs):
        called.append(True)
        return {}
    result = M.fit(p, "M1", runner=runner)
    out.update(result, runner_calls=len(called))
    assert called, "custom runner ignored even for family that requests one"


@case("C08", "Workbench export/import reviews of unchanged data are accepted by the final verifier.")
def workbench_signature(root, p, out):
    info = build_project(str(root))
    (root / "data/person_codebook.md").write_text("Synthetic: id, age, score, group", encoding="utf-8")
    entry = info["entry"]
    # This workbench test fixture uses kinds absent from the legacy verifier.
    # Normalize them to its supported observed+explicit-transform contract.
    provenance = root / entry["provenance"]
    proofs = [json.loads(line) for line in provenance.read_text(encoding="utf-8").splitlines()]
    for proof in proofs:
        if proof["kind"] in ("structural", "encoded"):
            proof["kind"] = "observed"
    provenance.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in proofs), encoding="utf-8")
    verifier = VD.Verifier("research_registry.json", root)
    snapshot = verifier.prepare()
    if verifier.issues:
        raise RuntimeError(f"fixture prepare errors: {verifier.issues}")
    (root / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    snap = {"stamp": snapshot["created_at"], "dataset_sha256": C.file_sha256(root / entry["path"])}
    rows = WB.blind_template(p, entry, snapshot=snap)
    # Independent second read of the synthetic original, including declared map.
    import csv
    with open(info["source"], encoding="utf-8-sig", newline="") as fh:
        original = {r["id"]: r for r in csv.DictReader(fh)}
    mapping = {"id": "id", "age": "年龄", "score": "得分", "group": "组别"}
    for row in rows:
        raw = original[row["key"][0]][mapping[row["column"]]]
        row["value_here"] = {"处理组": "treatment", "对照组": "control"}.get(raw, raw)
        row.update(reviewer="audit:second-read", checked_at=VD.stamp(),
                   note=f"Reopened original CSV for {row['key']}/{row['column']} and checked printed value.")
    imported = WB.import_second_pass(p, entry, rows, snapshot=snap)
    WB.write_review_file(p, entry, imported["review_lines"])
    final = VD.Verifier("research_registry.json", root)
    current = final.prepare()
    final.review("snapshot.json", current)
    out.update(confirmed=imported["confirmed"], complete=imported["complete"],
               errors=final.issues, workbench_signature=rows[0]["record_sha256"],
               verifier_signature=final.traces[0]["record_sha256"])
    assert not final.issues, "every workbench review rejected as different data/evidence"


@case("C09", "stage() must reject absolute or escaping paths before writing any source file.")
def stage_escape(root, p, out):
    original = root / "materials/original.txt"
    original.parent.mkdir()
    original.write_text("ORIGINAL", encoding="utf-8")
    tx = T.Transaction(p)
    rejected = False
    try:
        tx.stage(str(original), "OVERWRITTEN")
    except (T.TxnError, ValueError):
        rejected = True
    out.update(rejected=rejected, source_after_stage=original.read_text(encoding="utf-8"),
               committed=False)
    assert rejected and original.read_text(encoding="utf-8") == "ORIGINAL", "staging overwrote original before commit"


@case("C10", "A changed bound code file must stop publication.")
def code_drift(root, p, out):
    code = root / "analysis.py"
    code.write_text("old implementation", encoding="utf-8")
    tx = T.Transaction(p)
    tx.bind_code([code])
    tx.stage("report.txt", "result")
    code.write_text("new implementation", encoding="utf-8")
    rejected = False
    try:
        result = tx.commit()
        out.update(published=True, code_hash_recorded=result["code"], actual_hash=C.file_sha256(code))
    except T.TxnError as exc:
        rejected = True
        out["error"] = str(exc)
    assert rejected, "commit published despite code changing after binding"


@case("C11", "A live lock holder must not be evicted because its operation is long.")
def live_lock(root, p, out):
    first = T.Lock(p, "audit", timeout=0)
    first.acquire()
    meta = json.loads(first.path.read_text(encoding="utf-8"))
    meta["at"] = time.time() - 7200
    first.path.write_text(json.dumps(meta), encoding="utf-8")
    second = T.Lock(p, "audit", timeout=0)
    acquired = False
    try:
        second.acquire()
        acquired = True
    except T.LockError:
        pass
    finally:
        second.release()
        first.release()
    out.update(owner_pid=os.getpid(), owner_alive=True, second_acquired=acquired)
    assert not acquired, "second writer stole lock held by live process"


def indexed(root, p):
    materials = root / "materials"
    materials.mkdir()
    (materials / "a.txt").write_text("alpha: 7", encoding="utf-8")
    (materials / "b.txt").write_text("secret_value: 42", encoding="utf-8")
    units = SU.SourceUnits(p, root=root)
    units.build(materials)
    index = SI.SearchIndex(p, units)
    index.build(materials)
    inventory = [{"source": f.name, "sha256": C.file_sha256(f)} for f in materials.iterdir()]
    return index, inventory


@case("C12", "Searching only a.txt cannot certify coverage of b.txt.")
def filtered_coverage(root, p, out):
    index, inventory = indexed(root, p)
    run = index.search("secret_value", sources=["a.txt"])
    coverage = SI.searches_cover(p, [run["run"]], inventory)
    out.update(run=run, coverage=coverage, actual_filter=["a.txt"], answer_present_in="b.txt")
    assert not coverage["complete"], "unsearched source counted as searched"


@case("C13", "A zero-hit search plus a nonexistent dataset cannot resolve a data gap.")
def false_gap_resolution(root, p, out):
    index, _ = indexed(root, p)
    gap = G.open_gap(p, target="model:M1", requirement="missing count", status_detail="synthetic")
    run = index.search("ABSENT_TERM")
    rejected = False
    try:
        G.attach_search(p, gap["id"], run["run"], conclusion="found", note="synthetic incorrect declaration")
        result = G.resolve(p, gap["id"], dataset="does-not-exist", resolution="synthetic incorrect integration")
        out.update(search_hits=run["hits"], status=result["status"],
                   resolved_dataset=result["data"]["resolved_dataset"], completeness=G.completeness(p))
    except (ValueError, C.ContractError) as exc:
        rejected = True
        out["error"] = str(exc)
    assert rejected, "missing value/dataset accepted as found and integrated"


@case("C14", "A required, unsearched open gap cannot pass the gaps_closed release check.")
def open_gap(root, p, out):
    G.open_gap(p, target="dataset:D1", requirement="required event count", status_detail="not searched")
    evaluation = R.evaluate(p, {})
    check = next(c for c in evaluation["checks"] if c["check"] == "gaps_closed")
    out.update(check=check, completeness=G.completeness(p))
    assert not check["ok"], "open unsearched gap reported as gaps_closed"


@case("C15", "A trace must be semantically resolved, not an arbitrary nonempty value.")
def unbound_number(root, p, out):
    for section in MS.REQUIRED_SECTIONS:
        text = "Synthetic audit content without empirical support. " * 12
        if section == "results":
            text += "estimate={beta}"
        CL.register_block(p, block_id=section, section=section, text=text, claims=[])
    numbers = {"beta": 999999}
    trace = {"beta": {"model": "DOES_NOT_EXIST", "parameter": "x", "unit": "u"}}
    built = MS.build_docx(p, docx_path=root / "paper.docx", title="Synthetic audit",
                         authors="audit", numbers=numbers, trace=trace)
    checked = MS.verify_printed(p, docx_path=root / "paper.docx", spans=built["spans"],
                                numbers=numbers, trace=trace)
    printed = MS.printed_text_docx(root / "paper.docx", built["spans"])["full"]
    out.update(printed_unbound_value="999999" in printed, verified=checked["ok"],
               number_traces=built["numbers_used"], model_exists=False)
    assert not checked["ok"], "unbound number printed in DOCX and verify_printed returned ok"


@case("C16", "A registered custom section must be printed or explicitly rejected, never silently dropped.")
def dropped_section(root, p, out):
    for section in MS.REQUIRED_SECTIONS:
        CL.register_block(p, block_id=section, section=section,
                          text="Synthetic main text for manuscript audit. " * 15, claims=[])
    sentinel = "UNIQUE_REGISTERED_APPENDIX_CONTENT"
    CL.register_block(p, block_id="appendix", section="appendix", text=sentinel, claims=[])
    built = MS.build_docx(p, docx_path=root / "paper.docx", title="Synthetic audit",
                         authors="audit", numbers={}, trace={})
    checked = MS.verify_printed(p, docx_path=root / "paper.docx", spans=built["spans"])
    printed = MS.printed_text_docx(root / "paper.docx", built["spans"])["full"]
    out.update(registered_blocks=built["blocks"], printed_block_ids=list(built["spans"]),
               appendix_printed=sentinel in printed, verified=checked["ok"])
    assert sentinel in printed, "appendix dropped while block count includes it and verification passes"


@case("C17", "Numeric validation of slope=3 cannot validate a new model result with slope=7.")
def stale_validation(root, p, out):
    make_linear_data(str(root), slope=3)
    M.register(p, spec_for(str(root)))
    M.fit(p, "M1")
    V.independent_ols(p, "M1")
    old = p.latest("validation_result", "val:M1:x")
    make_linear_data(str(root), slope=7)
    M.register(p, spec_for(str(root)))
    M.fit(p, "M1")
    current = p.latest("model_result", "M1")
    release = R.evaluate(p, {"models": ["M1"]})
    out.update(old_validation_reference=old["data"]["observed"]["reference"],
               old_data_sha=old["data"]["observed"]["data_sha256"],
               new_estimate=current["data"]["estimate"], new_data_sha=C.file_sha256(root / "data/linear.csv"),
               current_result_revision=current["revision"], release_status=release["status"])
    check = next(c for c in release["checks"] if c["check"] == "results_validated")
    out["validation_release_check"] = check
    assert not check["ok"], "old validation accepted for a different data version and estimate"


@case("C18", "A recovered full-text source cannot silently lose its tail in a complete search index.")
def truncated_index(root, p, out):
    materials = root / "materials"
    materials.mkdir()
    text = "x" * 200001 + "\nTAIL_MEASUREMENT: 42\n"
    (materials / "long.txt").write_text(text, encoding="utf-8")
    units = SU.SourceUnits(p, root=root)
    units.build(materials)
    index = SI.SearchIndex(p, units)
    index.build(materials)
    run = index.search("TAIL_MEASUREMENT")
    entries = index.load()["entries"]
    out.update(source_chars=len(text), indexed_chars=len(entries[0]["text"]),
               search_hits=run["hits"], sources_declared=p.latest("search_run", run["run"])["data"]["sources"],
               stale=index.stale())
    assert run["hits"] > 0, "source tail silently omitted while source declared searched"


@case("C19", "Only one concurrent transaction may replace a given expected parent version.")
def concurrent_parents(root, p, out):
    import threading
    seed = T.Transaction(p, run_id="seed")
    seed.stage("result.txt", "v1")
    initial = seed.commit()
    parent_hash = initial["entries"][0]["sha256"]
    barrier = threading.Barrier(2, timeout=15)
    successful, rejected, failures = [], [], []
    txs = [T.Transaction(p, run_id=name) for name in ("left", "right")]
    for i, tx in enumerate(txs):
        tx.stage("result.txt", "v2-" + str(i))
        tx.expect_parent("result.txt", parent_hash)
        original_check = tx._check_parents
        # Deterministic scheduling: both checks see v1 before either publishes.
        def synchronized_check(check=original_check):
            check()
            barrier.wait()
        tx._check_parents = synchronized_check
    def commit(tx):
        try:
            successful.append(tx.commit()["commit"])
        except T.ParentVersionError as exc:
            rejected.append(str(exc))
        except BaseException:
            failures.append(traceback.format_exc())
    threads = [threading.Thread(target=commit, args=(tx,)) for tx in txs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    if failures or any(thread.is_alive() for thread in threads):
        raise RuntimeError(f"fixture concurrency error: {failures}")
    out.update(successful_commits=successful, parent_rejections=rejected,
               published_pointer=T.read_pointer(p))
    assert len(successful) == 1, "both different successor writes passed the same parent guard"


@case("C20", "A diagnostic explicitly saying cluster correction was not performed cannot pass linkage.")
def false_diagnostic(root, p, out):
    spec = {"design_features": {"clustered": True}}
    result = {"diagnostics": {"cluster_count": 2, "cluster_robust_or_mixed": False}}
    linkage = DC.linkage(spec, result)
    out.update(linkage=linkage, diagnostics=result["diagnostics"])
    assert not linkage["ok"], "mere presence of a False diagnostic accepted as satisfied"


@case("C21", "A source-unit reread event is not an invalid dataset-cell review.")
def ocr_event(root, p, out):
    from PIL import Image
    materials = root / "materials"
    materials.mkdir()
    Image.new("RGB", (20, 20), "white").save(materials / "page.png")
    units = SU.SourceUnits(p, root=root)
    units.build(materials)
    unit = units.units()[0]
    reread = OCR.adjudicate(p, units, unit, "synthetic reread", reviewer="audit", note="Opened synthetic original page.")
    # Isolate review-event consumer from unrelated cell preparation obligations.
    verifier = object.__new__(VD.Verifier)
    verifier.root = root
    verifier.issues = []
    verifier.v2_review_bound({}, VD.parse_time(VD.stamp()))
    out.update(event=reread["event"], errors=verifier.issues)
    assert not verifier.issues, "valid OCR reread event rejected as a nonexistent dataset cell"


@case("C22", "Requested but unimplemented cluster/lag variants cannot disappear into a passed stability result.")
def empty_stability(root, p, out):
    make_linear_data(str(root))
    M.register(p, spec_for(str(root)))
    M.fit(p, "M1")
    V.independent_ols(p, "M1")
    result = V.stability(p, "M1", variants=["cluster", "lag"])
    record = p.latest("validation_result", "stability:M1")
    out.update(result, recorded_status=record["status"], requested=["cluster", "lag"],
               actual_variants=record["data"]["independent"]["variants"])
    assert record["status"] != "passed", "zero variants executed yet stability status passed"


@case("C23", "The design consumer must accept the project-relative input paths produced by the model registry.")
def relative_role_path(root, p, out):
    make_linear_data(str(root))
    M.register(p, spec_for(str(root)))
    registered = M.load_spec(p, "M1")["data"]
    accepted = False
    try:
        out["accounting"] = DC.role_accounting(registered)
        accepted = True
    except DC.DesignError as exc:
        out.update(input_path=registered["inputs"][0]["dataset"], error=str(exc))
    assert accepted, "design consumer rejects the model producer's valid input paths"


def main():
    results = []
    for ident, expected, fn in CASES:
        item = {"id": ident, "expected": expected, "observed": {}}
        with tempfile.TemporaryDirectory(prefix="skill-independent-audit-") as folder:
            root = Path(folder)
            p = C.Project(root)
            try:
                fn(root, p, item["observed"])
                item["verdict"] = "counterexample_not_reproduced"
            except AssertionError as exc:
                item["verdict"] = "counterexample_confirmed"
                item["assertion"] = str(exc)
            except BaseException:
                item["verdict"] = "fixture_error_not_evidence"
                item["traceback"] = traceback.format_exc()
        results.append(item)
        print(ident, item["verdict"], item.get("assertion", item.get("traceback", "")), flush=True)
    output = {"synthetic_only": True, "run_at": C._now(), "python": sys.version,
              "source_files": {name: C.file_sha256(ROOT / "empirical-research-pipeline/scripts" / name)
                               for name in ("models.py", "release.py", "contract_v2.py", "review_workbench.py",
                                            "verify_dataset.py", "txn.py", "search_index.py", "gaps.py", "manuscript.py")},
              "cases": results}
    Path(__file__).with_name("repro-results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"confirmed": sum(r["verdict"] == "counterexample_confirmed" for r in results),
                      "fixture_errors": sum(r["verdict"] == "fixture_error_not_evidence" for r in results),
                      "total": len(results)}))


if __name__ == "__main__":
    main()
