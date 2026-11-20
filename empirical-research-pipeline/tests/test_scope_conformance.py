"""通用范围符合性：分析表类别分布必须对照声明的 include 白名单；不写死任何学科。"""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from scope_conformance import check, main


def _write(root, name, text):
    path = os.path.join(root, name)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def main_test():
    with tempfile.TemporaryDirectory() as root:
        data = _write(root, "analysis.csv",
                      "id,cat,year,y\n1,A,2020,1\n2,A,2020,0\n3,B,2021,1\n4,OUT,2021,1\n5,,2021,0\n")
        scope = _write(root, "scope.json", json.dumps(
            {"columns": {"cat": {"include": ["A", "B"]}}, "min_cell_n": 3}))
        res = check(data, scope, ["cat", "year"], None)
        # named out-of-scope category "OUT" is an error; missing value is a warning
        assert res["error_count"] == 1, res["errors"]
        assert any("OUT" in e for e in res["errors"]), res["errors"]
        assert res["columns"]["cat"]["na"] == 1
        assert res["warning_count"] >= 1
        assert res["small_cells"], "tiny cells should be surfaced"
        assert main(["--data", data, "--scope", scope, "--out", os.path.join(root, "r.csv")]) == 2

        clean = _write(root, "clean.csv", "id,cat\n1,A\n2,B\n3,A\n")
        res2 = check(clean, scope, None, None)
        assert res2["error_count"] == 0, res2["errors"]
        assert main(["--data", clean, "--scope", scope, "--out", os.path.join(root, "r2.csv")]) == 0

        # a declared column absent from the data is an error, not a silent pass
        res3 = check(clean, _write(root, "bad.json", json.dumps(
            {"columns": {"nope": {"include": ["x"]}}})), None, None)
        assert res3["error_count"] == 1, res3["errors"]

    print("scope conformance ok")


if __name__ == "__main__":
    main_test()