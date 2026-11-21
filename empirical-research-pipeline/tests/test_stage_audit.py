"""零信任阶段审计：产物哈希绑定、命令实际重跑（白名单校验脚本）、原文回读、
quote⊆span、方法互异、独立回源、resolution 证据、漏斗重算。通用不写死学科。"""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import audit_probe as AP
from stage_audit import check, main

PY = sys.executable.replace("\\", "/")
SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")).replace("\\", "/")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _scope_cmd(scope="scope.json", out="output/qa/s.csv"):
    return (f'"{PY}" "{SCRIPTS}/scope_conformance.py" '
            f'--data output/dataset/analysis.csv --scope {scope} --out {out}')


def _root_fixture(root):
    _write(os.path.join(root, "materials", "a.txt"), "alpha beta gamma delta")
    data = os.path.join(root, "output", "dataset", "analysis.csv")
    _write(data, "rel_path,x\nmaterials/a.txt,v\n")
    _write(os.path.join(root, "scope.json"), '{"columns":{"x":{"include":["v"]}}}')
    _write(os.path.join(root, "scope_bad.json"), '{"columns":{"x":{"include":["OTHER"]}}}')
    return data


def _pass(stage, angle, method, data_sha, **kw):
    rec = {"stage": stage, "angle": angle, "method": method,
           "artifacts": {"output/dataset/analysis.csv": data_sha},
           "evidence": {"commands": [{"cmd": _scope_cmd(), "exit": 0}]},
           "findings": []}
    rec.update(kw)
    return rec


def _sample(rel="materials/a.txt", span=(0, 5), quote="alpha", **kw):
    s = {"rel_path": rel, "span": list(span), "quote": quote}
    s.update(kw)
    return s


def main_test():
    with tempfile.TemporaryDirectory() as root:
        data = _root_fixture(root)
        sha = AP.sha256_file(data)
        good = [
            _pass("dataset", "machine", "recompute", sha),
            _pass("dataset", "independent", "reread", sha,
                  evidence={"samples": [_sample(field="x", value="v")]}),
        ]
        opts = {"data": "output/dataset/analysis.csv", "no_recompute": True}
        res = check(good, ["dataset"], root, opts)
        assert res["error_count"] == 0, res["errors"]

        # single pass
        assert check([good[0]], ["dataset"], root, opts)["error_count"] >= 1
        # same angle
        same_angle = [_pass("dataset", "machine", "recompute", sha),
                      _pass("dataset", "machine", "reread", sha,
                            evidence={"samples": [_sample()]})]
        assert any("angle" in e for e in check(same_angle, ["dataset"], root, opts)["errors"])
        # same method (independence)
        same_method = [_pass("dataset", "machine", "recompute", sha),
                       _pass("dataset", "independent", "recompute", sha,
                             evidence={"samples": [_sample()]})]
        assert any("method" in e for e in check(same_method, ["dataset"], root, opts)["errors"])
        # claimed exit mismatch: real checker exits 2 (bad scope), claimed 0
        bad_exit = [_pass("dataset", "machine", "recompute", sha,
                          evidence={"commands": [{"cmd": _scope_cmd("scope_bad.json", "output/qa/sb.csv"), "exit": 0}]}),
                    good[1]]
        assert any("re-run gave" in e for e in check(bad_exit, ["dataset"], root, opts)["errors"])
        # arbitrary code command is refused (zero-trust allowlist)
        arb = [_pass("dataset", "machine", "recompute", sha,
                     evidence={"commands": [{"cmd": f'"{PY}" -c "import sys; sys.exit(0)"', "exit": 0}]}),
               good[1]]
        assert any("allowed verification" in e or "arbitrary" in e
                   for e in check(arb, ["dataset"], root, opts)["errors"])
        # artifact changed after audit
        bad_art = [_pass("dataset", "machine", "recompute", "0" * 64), good[1]]
        assert any("changed after audit" in e for e in check(bad_art, ["dataset"], root, opts)["errors"])
        # fabricated quote wider than span
        fab = [_pass("dataset", "machine", "recompute", sha),
               _pass("dataset", "independent", "reread", sha,
                     evidence={"samples": [_sample(quote="alpha FABRICATED CONTEXT")]})]
        assert any("fabricated" in e for e in check(fab, ["dataset"], root, opts)["errors"])
        # free-text sample is not evidence
        freetext = [_pass("dataset", "machine", "recompute", sha),
                    _pass("dataset", "independent", "reread", sha,
                          evidence={"samples": ["materials/a.txt"]})]
        assert any("structured" in e for e in check(freetext, ["dataset"], root, opts)["errors"])
        # method reread without samples is inconsistent
        nosample = [_pass("dataset", "machine", "recompute", sha),
                    _pass("dataset", "independent", "reread", sha,
                          evidence={"commands": [{"cmd": _scope_cmd(), "exit": 0}]})]
        assert any("requires structured samples" in e for e in check(nosample, ["dataset"], root, opts)["errors"])
        # no raw-source re-read (sample under output/)
        _write(os.path.join(root, "output", "note.txt"), "alpha beta")
        noraw = [_pass("dataset", "machine", "recompute", sha),
                 _pass("dataset", "independent", "reread", sha,
                       evidence={"samples": [_sample(rel="output/note.txt")]})]
        assert any("raw source" in e for e in check(noraw, ["dataset"], root, opts)["errors"])
        # unresolved finding
        unres = [_pass("dataset", "machine", "recompute", sha,
                       findings=[{"detail": "x", "resolved": False}]), good[1]]
        assert any("unresolved" in e for e in check(unres, ["dataset"], root, opts)["errors"])
        # resolved without resolution evidence
        nores = [_pass("dataset", "machine", "recompute", sha,
                       findings=[{"detail": "x", "resolved": True}]), good[1]]
        assert any("resolution evidence" in e for e in check(nores, ["dataset"], root, opts)["errors"])
        # sample value mismatch against dataset cell
        valmis = [_pass("dataset", "machine", "recompute", sha),
                  _pass("dataset", "independent", "reread", sha,
                        evidence={"samples": [_sample(field="x", value="WRONG")]})]
        assert any("dataset cell" in e for e in check(valmis, ["dataset"], root, opts)["errors"])

        # funnel re-derivation catches a growing funnel
        _write(os.path.join(root, "output", "coding", "sample_flow.csv"),
               "stage,n,note\nraw,10,\nclean,12,\n")
        assert any("funnel" in e for e in check(good, ["dataset"], root, {"data": "output/dataset/analysis.csv"})["errors"])
        _write(os.path.join(root, "output", "coding", "sample_flow.csv"),
               "stage,n,note\nraw,12,\nclean,10,\n")
        assert check(good, ["dataset"], root, {"data": "output/dataset/analysis.csv"})["error_count"] == 0

        # debug --no-rerun downgrades to structural (bad exit no longer caught)
        dbg = check(bad_exit, ["dataset"], root, {**opts, "no_rerun": True})
        assert not any("re-run gave" in e for e in dbg["errors"])

        # CLI end-to-end
        led = os.path.join(root, "stage_audit.jsonl")
        with io.open(led, "w", encoding="utf-8") as fh:
            for r in good:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        assert main(["--ledger", led, "--require", "dataset", "--root", root,
                     "--data", "output/dataset/analysis.csv", "--no-recompute"]) == 0
        assert main(["--ledger", led, "--require", "dataset,figures", "--root", root, "--no-recompute"]) == 2
    print("zero-trust stage audit ok")


if __name__ == "__main__":
    main_test()