"""零信任独立复核器：关系/单位符合性、时间规则、证据全量回验、清洗重放、语料重扫。"""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import audit_probe as AP
import extract_lib as EL
import evidence_replay as ER
import clean_data as CD
import audit_corpus as AC
import text_extract as TX


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _json(path, obj):
    _write(path, json.dumps(obj, ensure_ascii=False))


def test_relations(root):
    _write(os.path.join(root, "data", "person.csv"), "person_id,name\nP1,a\nP2,b\n")
    _write(os.path.join(root, "data", "wave.csv"),
           "person_id,wave,score\nP1,1,10\nP1,2,12\nP2,1,9\n")
    reg = {"datasets": [
        {"id": "person", "path": "data/person.csv", "key": "person_id", "unit": "一个人"},
        {"id": "wave", "path": "data/wave.csv", "key": ["person_id", "wave"], "unit": "人-轮"}],
        "joins": [{"left": "person", "right": "wave", "on": "person_id",
                   "how": "left", "expect": "1:N", "result_n": 3}]}
    assert AP.check_relations(reg, root)["ok"]
    # fan-out violates declared 1:1
    reg["joins"][0]["expect"] = "1:1"
    assert any("fan-out" in e for e in AP.check_relations(reg, root)["errors"])
    # row accounting mismatch
    reg["joins"][0]["expect"] = "1:N"
    reg["joins"][0]["result_n"] = 99
    assert any("row accounting" in e for e in AP.check_relations(reg, root)["errors"])
    # duplicate primary key
    _write(os.path.join(root, "data", "person.csv"), "person_id,name\nP1,a\nP1,b\n")
    assert any("not unique" in e for e in AP.check_relations(reg, root)["errors"])


def test_temporal(root):
    data = os.path.join(root, "data", "panel.csv")
    _write(data, "id,date,start,end\nP1,2021-03-01,2021-01-01,2021-06-01\n"
                 "P1,2025-09-01,2021-05-01,2021-12-01\n")
    scope = {"temporal": [{"col": "date", "min": "2021-01-01", "max": "2021-12-31"}],
             "intervals": [{"key": "id", "start": "start", "end": "end"}]}
    res = AP.check_temporal(scope, data)
    assert any("outside" in e for e in res["errors"])
    assert any("overlapping" in e for e in res["errors"])
    _write(data, "id,date,start,end\nP1,2021-03-01,2021-01-01,2021-06-01\n"
                 "P1,2021-09-01,2021-07-01,2021-12-01\n")
    assert AP.check_temporal(scope, data)["ok"]


def test_evidence_replay(root):
    _write(os.path.join(root, "materials", "a.txt"), "alpha beta gamma delta")
    ev = os.path.join(root, "output", "coding", "evidence.jsonl")
    line = EL.evidence_line("x", "alpha beta", (0, 10))
    _write(ev, json.dumps({"rel_path": "materials/a.txt",
                           "fields": {"x": {"value": "v", "raw": "alpha", "span": [0, 5]}},
                           "evidence": [line]}, ensure_ascii=False) + "\n")
    ds = os.path.join(root, "output", "coding", "dataset.csv")
    _write(ds, "rel_path,x\nmaterials/a.txt,v\n")
    assert ER.replay(ev, root, ds)["ok"]
    # tampered span out of range
    _write(ev, json.dumps({"rel_path": "materials/a.txt",
                           "evidence": ["x=alpha@100-105"]}, ensure_ascii=False) + "\n")
    res = ER.replay(ev, root, None)
    assert not res["ok"] and res["lines_failed"] >= 1


def test_cleaning_replay(root):
    ds = os.path.join(root, "output", "coding", "dataset.csv")
    _write(ds, "id,x\n1,a\n2,\n3,b\n")
    recipe = os.path.join(root, "draft", "cleaning.json")
    _json(recipe, {"recipe_version": 1, "id_columns": ["id"], "max_drop_fraction": 0.5,
                   "na_values": [""], "steps": [
                       {"op": "drop_rows_if_missing", "columns": ["x"],
                        "mode": "any", "reason": "missing x"}]})
    audited = os.path.join(root, "output", "cleaning")
    assert CD.main(["--dataset", ds, "--recipe", recipe, "--out", audited]) == 0
    scratch = os.path.join(root, "output", "qa", "scratch")
    res = AP.replay_cleaning(ds, recipe, audited, scratch)
    assert res["ok"], res["errors"]
    assert res["dropped_ids_full"] == [["2"]], res["dropped_ids_full"]
    # tamper audited output -> divergence
    with io.open(os.path.join(audited, "clean_dataset.csv"), "a", encoding="utf-8") as fh:
        fh.write("9,z\n")
    assert not AP.replay_cleaning(ds, recipe, audited, scratch)["ok"]


def test_rescan(root):
    corpus = os.path.join(root, "materials")
    _write(os.path.join(corpus, "a.txt"), "hello research material text")
    audit_out = os.path.join(root, "output", "audit")
    assert AC.main(["--root", corpus, "--out-dir", audit_out, "--min-chars", "1"]) == 0
    scratch = os.path.join(root, "output", "qa", "rescan_scratch")
    res = AP.rescan_corpus(corpus, audit_out, scratch)
    assert res["ok"] and res["fingerprint_match"], res
    _write(os.path.join(corpus, "b.txt"), "a newly added material file")
    res2 = AP.rescan_corpus(corpus, audit_out, scratch)
    assert not res2["ok"] and res2["added"], res2


def test_fixes(root):
    # A: HTML evidence anchored on extracted (tag-stripped) text verifies
    html = os.path.join(root, "materials", "h.html")
    _write(html, "<html><body><p>alpha beta</p></body></html>")
    text = TX.extract_text(html)
    s = text.index("alpha beta")
    line = EL.evidence_line("x", "alpha beta", (s, s + len("alpha beta")))
    ev = os.path.join(root, "output", "coding", "evidence_html.jsonl")
    _write(ev, json.dumps({"rel_path": "materials/h.html", "evidence": [line]},
                          ensure_ascii=False) + "\n")
    assert ER.replay(ev, root, None)["ok"], "HTML anchor must match extracted text"

    # B: month-precision max bound covers the whole month
    data = os.path.join(root, "data", "month.csv")
    _write(data, "id,date\nP1,2021-12-15\n")
    scope = {"temporal": [{"col": "date", "min": "2021-01", "max": "2021-12"}]}
    assert AP.check_temporal(scope, data)["ok"], "2021-12-15 is within max 2021-12"
    _write(data, "id,date\nP1,2022-01-01\n")
    assert not AP.check_temporal(scope, data)["ok"]

    # C: missing join column must error even under 1:N (no silent empty-key match)
    _write(os.path.join(root, "data", "ja.csv"), "id\n1\n2\n")
    _write(os.path.join(root, "data", "jb.csv"), "id\n1\n2\n")
    reg = {"datasets": [{"id": "ja", "path": "data/ja.csv", "key": "id"},
                        {"id": "jb", "path": "data/jb.csv", "key": "id"}],
           "joins": [{"left": "ja", "right": "jb", "on": "NOPE", "expect": "1:N"}]}
    res = AP.check_relations(reg, root)
    assert not res["ok"] and any("missing" in e for e in res["errors"])
    reg["joins"][0]["on"] = "id"
    reg["joins"][0]["how"] = "outer"
    assert any("how" in e for e in AP.check_relations(reg, root)["errors"])

    # G: funnel excluded/model bounds
    flow = os.path.join(root, "output", "coding", "flow_bounds.csv")
    _write(flow, "stage,n,kind,note\nraw,10,stage,\nexcl,12,excluded,\n")
    assert any("excluded" in e for e in AP.funnel_recompute(flow))
    _write(flow, "stage,n,kind,note\nraw,10,stage,\nm,12,model,stage=raw\n")
    assert any("model" in e for e in AP.funnel_recompute(flow))
    _write(flow, "stage,n,kind,note\nraw,10,stage,\nm,5,model,\n")
    assert any("stage=" in e for e in AP.funnel_recompute(flow))
    _write(flow, "stage,n,kind,note\nraw,10,stage,\nm,8,model,stage=raw\n")
    assert AP.funnel_recompute(flow) == []

    # J: cleaning replay enumerates full rows even without id_columns
    ds = os.path.join(root, "output", "coding", "ds_noid.csv")
    _write(ds, "id,x\n1,a\n2,\n3,b\n")
    recipe = os.path.join(root, "draft", "clean_noid.json")
    _json(recipe, {"recipe_version": 1, "id_columns": [], "max_drop_fraction": 0.5,
                   "na_values": [""], "steps": [{"op": "drop_rows_if_missing",
                                                 "columns": ["x"], "mode": "any", "reason": "m"}]})
    audited = os.path.join(root, "output", "clean_noid")
    assert CD.main(["--dataset", ds, "--recipe", recipe, "--out", audited]) == 0
    res = AP.replay_cleaning(ds, recipe, audited, os.path.join(root, "output", "qa", "sc2"))
    assert res["ok"] and res["dropped_ids_full"] == [{"id": "2", "x": ""}], res["dropped_ids_full"]

    # E: rescan with --no-hash discloses size-only limitation
    corpus = os.path.join(root, "materials_nohash")
    _write(os.path.join(corpus, "c.txt"), "some research material text")
    audit_out = os.path.join(root, "output", "audit_nohash")
    assert AC.main(["--root", corpus, "--out-dir", audit_out, "--min-chars", "1", "--no-hash"]) == 0
    res = AP.rescan_corpus(corpus, audit_out, os.path.join(root, "output", "qa", "rs2"))
    assert res["ok"] and res["warnings"], res


def test_r3(root):
    # evidence coverage: a dataset row with no evidence record is a gap
    _write(os.path.join(root, "materials", "c.txt"), "alpha beta gamma")
    ev = os.path.join(root, "output", "coding", "ev_cov.jsonl")
    _write(ev, json.dumps({"rel_path": "materials/c.txt",
                           "evidence": ["x=alpha beta@0-10"]}, ensure_ascii=False) + "\n")
    ds = os.path.join(root, "output", "coding", "ds_cov.csv")
    _write(ds, "rel_path,x\nmaterials/c.txt,v\nmaterials/d.txt,w\n")
    res = ER.replay(ev, root, ds)
    assert not res["ok"] and any("coverage gap" in e for e in res["errors"]), res["errors"]

    # temporal interval with end before start is invalid
    iv = os.path.join(root, "data", "iv.csv")
    _write(iv, "id,start,end\nP1,2021-06-01,2021-01-01\n")
    res = AP.check_temporal({"intervals": [{"key": "id", "start": "start", "end": "end"}]}, iv)
    assert any("end before start" in e for e in res["errors"]), res

    # relation: the 1-side join key must be unique (left id dup under 1:N)
    _write(os.path.join(root, "data", "ra.csv"), "id,name\n1,a\n1,b\n")
    _write(os.path.join(root, "data", "rb.csv"), "id,score\n1,10\n")
    reg = {"datasets": [{"id": "ra", "path": "data/ra.csv", "key": "name"},
                        {"id": "rb", "path": "data/rb.csv", "key": "id"}],
           "joins": [{"left": "ra", "right": "rb", "on": "id", "expect": "1:N"}]}
    res = AP.check_relations(reg, root)
    assert any("1-side must be unique" in e for e in res["errors"]), res

    # allowlist: arbitrary -c command is refused by the auditor
    r = AP.rerun_command(f'"{sys.executable}" -c "print(1)"', root)
    assert r["exit"] is None and "arbitrary" in r["stderr_tail"], r


def main_test():
    with tempfile.TemporaryDirectory() as root:
        test_relations(root)
        test_temporal(root)
        test_evidence_replay(root)
        test_cleaning_replay(root)
        test_rescan(root)
        test_fixes(root)
        test_r3(root)
    print("zero-trust re-derivation checkers ok")


if __name__ == "__main__":
    main_test()