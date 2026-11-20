"""阶段双遍审计台账：每阶段>=2遍、角度互异、有证据、无未解决 finding；通用不写死学科。"""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from stage_audit import check, main


def _pass(stage, angle, **kw):
    rec = {"stage": stage, "angle": angle,
           "evidence": {"commands": [{"cmd": "python scripts/x.py", "exit": 0}]},
           "findings": []}
    rec.update(kw)
    return rec


def main_test():
    good = [_pass("dataset", "machine"), _pass("dataset", "independent",
            evidence={"samples": ["a.pdf"], "checks": ["scope-drift", "n-reconcile"]})]
    assert check(good, ["dataset"])["error_count"] == 0

    # single pass -> error
    assert check([good[0]], ["dataset"])["error_count"] >= 1
    # two passes same angle -> error
    same = [_pass("dataset", "machine"), _pass("dataset", "machine")]
    assert any("angle" in e for e in check(same, ["dataset"])["errors"])
    # missing required stage -> error
    assert check(good, ["dataset", "figures"])["error_count"] >= 1
    # unresolved finding -> error
    unres = [_pass("dataset", "machine", findings=[{"detail": "x", "resolved": False}]), good[1]]
    assert any("unresolved" in e for e in check(unres, ["dataset"])["errors"])
    # empty evidence -> error
    noev = [_pass("dataset", "machine", evidence={}), good[1]]
    assert any("evidence" in e for e in check(noev, ["dataset"])["errors"])

    with tempfile.TemporaryDirectory() as root:
        led = os.path.join(root, "stage_audit.jsonl")
        with io.open(led, "w", encoding="utf-8") as fh:
            for r in good:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        assert main(["--ledger", led, "--require", "dataset"]) == 0
        assert main(["--ledger", led, "--require", "dataset,figures"]) == 2
    print("stage audit ok")


if __name__ == "__main__":
    main_test()