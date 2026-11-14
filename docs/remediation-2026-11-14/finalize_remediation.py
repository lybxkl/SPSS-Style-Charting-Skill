"""Replace historical self-reports with current, actual repair execution evidence.

No historical batch ordering is fabricated. Run only after accepted-run passed.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def read(path):return json.loads(path.read_text(encoding="utf-8"))
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    path=HERE/"accepted-final/execution.json";receipt=read(path)
    assert receipt["result"]=="passed" and receipt["sources_unchanged"],"No current full passing execution"
    for rel,digest in {**receipt["production_after"],**receipt["oracle_files"]}.items():
        assert sha(ROOT/rel)==digest,rel
    mapping=read(HERE/"acceptance-test-map.json")
    original=read(HERE/"historical-implementation/ACCEPTANCE-RESULTS.json")
    designs=read(ROOT/"docs/plan-audit-2026-11-14/acceptance_cards.json")["cases"]
    audit=read(ROOT/"docs/audit-implementation-2026-11-14/audit-matrix.json")
    last_write=max((ROOT/p).stat().st_mtime for p in receipt["production_before"])
    implemented=datetime.fromtimestamp(last_write,timezone.utc).isoformat()
    command=subprocess.list2cmdline(receipt["command"])
    relative=path.relative_to(ROOT).as_posix()
    cases={}
    for design in designs:
        cid=design["id"];ids=mapping["cases"][cid]["test_ids"]
        assert all(receipt["tests"][i]["status"]=="passed" for i in ids),cid
        details=[]
        for ident in ids[:4]:
            observed=receipt["tests"][ident]
            details.append({"test":ident,"status":observed["status"],"seconds":observed["elapsed_seconds"],"assertions":observed["observations"][:3]})
        case={"id":cid,"scenario":design["scenario"],"primary_task":design["primary_acceptance_task"],"linked_tasks":design["linked_tasks"],
              "fixture":"synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed",
              "fixture_spec":design["fixture_and_procedure_spec"],"expectation":design["independent_expected_observation"],"negative_control":design["negative_control"],
              "expectation_recorded_at":audit["audited_at"],"implemented_at":implemented,
              "timing_scope":"Current repair: pre-fix independent audit vs current implementation snapshot. These fields do not prove original implementation batch ordering.",
              "expectation_sha256":mapping["cases"][cid]["expectation_sha256"],"steps":[command],"command":command,
              "observed":f"Current execution: {len(ids)} mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs.",
              "observations_sample":details,"environment":receipt["environment"],"result":"passed","gap":None,
              "test_ids":ids,"execution_receipts":[{"path":relative,"sha256":sha(path)}],
              "evidence":[relative,relative.replace("execution.json","execution.log"),"docs/remediation-2026-11-14/acceptance-test-map.json"],
              "observed_at":receipt["finished_at"],"runs":[{"at":receipt["finished_at"],"command":command,"result":"passed"}],
              "note":"Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof."}
        if cid in ("A34","A36","A38","A39"):
            case["evidence"] += ["docs/remediation-2026-11-14/validation-example-v3/visual-review.json","docs/remediation-2026-11-14/validation-example-v3/example-summary.json"]
        if cid=="A60":
            case.update(result="unassessed",gap="Original implementation's per-batch pre-implementation gates have no independently verifiable historical execution chain. Current guard tests and integrated tests passed, but cannot retroactively establish that history.",
                        note="The original all-passed claim is withdrawn for this historical component. The current executable gate and its negative controls are implemented and tested.")
        cases[cid]=case
    write(ROOT/"docs/implementation/ACCEPTANCE-RESULTS.json",{"schema_version":1,"kind":"actual_repair_acceptance_results","created_at":receipt["finished_at"],
          "note":"Supersedes historical self-reported cards, preserved in docs/remediation-2026-11-14/historical-implementation. Current tests and original historical process claims are separate.","cases":cases})
    tasks=read(HERE/"historical-implementation/TASK-STATUS.json")
    for ident,task in tasks["tasks"].items():
        linked=task["acceptance_cases"]
        task["historical_state_claim"]=task["state"]
        task["state"]="implemented"
        task["verification"]=[{"at":receipt["finished_at"],"command":command,"evidence":[relative],"cases":linked,
                               "test_ids":sorted({i for cid in linked for i in cases[cid]["test_ids"]})}]
        task["acceptance_status"]="historical_component_unassessed" if "A60" in linked else "passed_in_measured_scope"
        task["gaps"]=[cases["A60"]["gap"]] if "A60" in linked else []
        task["changes"].append({"at":receipt["finished_at"],"note":"Independent audit fixes integrated and regression-tested against actual mapped producer/consumer behavior; prior self-report is preserved, not used as proof."})
    tasks["updated_at"]=receipt["finished_at"]
    tasks["note"]="Current implementation is tested; historical pre-batch execution cannot be reconstructed. Read acceptance_status/gaps and current execution receipts, not state alone."
    write(ROOT/"docs/implementation/TASK-STATUS.json",tasks)
    repro_map={1:[9],2:[4],3:[5],4:[1,2,14],5:[17],6:[3],7:[8],8:[21],9:[12],10:[18],11:[13],12:[15],13:[16],14:[6,7],15:[10],16:[19],17:[11],18:[20],19:[23],20:[22]}
    fixed=[]
    for finding in audit["findings"]:
        n=int(finding["id"][1:])
        prefixes=[f"test_remediation.AuditFixes.test_c{i:02d}" for i in repro_map.get(n,[])]
        ids=[i for i in receipt["tests"] if any(i.startswith(prefix) for prefix in prefixes)] if n<21 else [i for i in receipt["tests"] if i.startswith("test_acceptance_cards.")]
        if n==7:
            ids.append("test_remediation.AuditFixes.test_new_dispute_overrides_previous_approval_across_timezones")
        assert ids and all(receipt["tests"][i]["status"]=="passed" for i in ids)
        fixed.append({"id":finding["id"],"title":finding["title"],"runtime_status":"fixed_and_regression_passed","test_ids":ids,
                      "historical_evidence_limit":cases["A60"]["gap"] if n==21 else None})
    requirements=[]
    for req in audit["requirements"]:
        relevant=[t for t in tasks["tasks"].values() if req["id"] in t.get("requirements",[])]
        requirements.append({"id":req["id"],"title":req["title"],"tasks":[t["id"] for t in relevant],"state":"implemented_and_regression_tested_in_measured_scope"})
    env={name:importlib.metadata.version(name) for name in ["numpy","pandas","scipy","statsmodels","matplotlib","PyMuPDF","python-docx","openpyxl","vosk","rapidocr_onnxruntime"]}
    write(HERE/"repair-evidence.json",{"generated_at":receipt["finished_at"],"execution":relative,"execution_sha256":sha(path),"findings":fixed,"requirements":requirements,
          "environment_versions":env,"acceptance_summary":{"passed":59,"historical_component_unassessed":1},"scope":"Synthetic fixtures and named actual local providers; no real empirical research claim."})
    before=read(HERE/"before.json")["sha256"]
    write(HERE/"preservation-after.json",{"deleted":[p for p in before if not (ROOT/p).is_file()],"changed":[p for p,h in before.items() if (ROOT/p).is_file() and sha(ROOT/p)!=h],
         "original_audit_preserved":True,"frozen_before":"before.json"})
    print(json.dumps({"tests":receipt["tests_run"],"findings_fixed":len(fixed),"cards_passed":59,"historical_card_unassessed":"A60"}))


if __name__=="__main__":main()
