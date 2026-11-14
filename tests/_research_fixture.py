"""Known-answer synthetic projects with actual source reread, never blanket signing."""
from pathlib import Path
import contextlib
import csv
import io
import json

import contract_v2 as C
import designcheck as DC
import discovery as D
import models as M
import review_workbench as WB
import source_units as SU
import validation as V
import verify_dataset as VD


def csv_write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def reread(root, dataset_id="person"):
    root = Path(root)
    project = C.Project(root)
    registry = json.loads((root / "research_registry.json").read_text(encoding="utf-8"))
    entry = next(d for d in registry["datasets"] if d["id"] == dataset_id)
    exported = WB.export_html(project, entry)
    rows = WB.blind_template(project, entry, snapshot=exported)
    # Open original sources after prepare. Do not copy extracted first-pass
    # values into review lines; compare the newly read fields via the workbench.
    originals = {}
    proofs = {(VD.key_tuple(r["key"]), r["column"]): r for r in
              (json.loads(line) for line in (root / entry["provenance"]).read_text(encoding="utf-8").splitlines())}
    for row in rows:
        source = row["first_pass_sources"][0]
        path = root / source["path"]
        if path not in originals:
            with open(path, encoding="utf-8-sig", newline="") as stream:
                originals[path] = list(csv.DictReader(stream))
        locator = source["locator"]
        value = originals[path][locator["row"]-1][locator["column"]]
        proof = proofs[(tuple(row["key"]), row["column"])]
        if proof.get("rule", {}).get("op") == "map":
            value = proof["rule"]["mapping"][value]
        if proof["kind"] == "missing":
            value = ""
        row.update(value_here=value, reviewer="synthetic-fixture:second-pass", checked_at=VD.stamp(),
                   note=f"Reopened {source['path']}, data row {locator['row']}, column {locator['column']}; checked context and value.",
                   reread_scope={"path": source["path"], "sha256": C.file_sha256(path), "locator": locator})
    imported = WB.import_second_pass(project, entry, rows, snapshot=exported)
    if imported["conflicts"]:
        raise ValueError(f"fixture second pass disagrees: {imported['conflicts']}")
    WB.write_review_file(project, entry, imported["review_lines"])
    return exported


def final_review(root):
    root = Path(root)
    registry = json.loads((root / "research_registry.json").read_text(encoding="utf-8"))
    snapshot = None
    for entry in registry["datasets"]:
        exported = reread(root, entry["id"])
        snapshot = snapshot or exported["snapshot_path"]
    with contextlib.redirect_stdout(io.StringIO()):
        exit_code = VD.main(["--registry", "research_registry.json", "--root", str(root), "--out", str(root / "output/dataset"),
                             "--stage", "final", "--snapshot", snapshot])
    if exit_code:
        raise ValueError((root / "output/dataset/dataset_verification.json").read_text(encoding="utf-8"))
    return "output/dataset/dataset_verification.json"


def known_project(root, *, n=120, slope=0.42, second_dataset=False, fit=True):
    root = Path(root)
    project = C.Project(root)
    header = ["id", "treatment", "y"]
    rows = [[f"P{i:04d}", str(i % 2), f"{0.1+slope*(i%2):.8f}"] for i in range(n)]
    source = root / "materials/raw.csv"
    csv_write(source, header, rows)
    datasets = []
    for ident in (["person", "events"] if second_dataset else ["person"]):
        csv_write(root / f"data/{ident}.csv", header, rows)
        (root / f"data/{ident}.md").write_text("Synthetic fixture: one record per id; treatment is a recorded indicator; y is a synthetic score.", encoding="utf-8")
        proof = []
        for i, row in enumerate(rows, 1):
            for col,value in zip(header, row):
                proof.append({"key": row[0], "column": col, "value": value, "kind": "observed",
                              "sources": [{"path": "materials/raw.csv", "sha256": C.file_sha256(source),
                                           "locator": {"type": "csv", "row": i, "column": col}, "raw": value}]})
        (root / f"data/{ident}.prov.jsonl").write_text("".join(json.dumps(r) + "\n" for r in proof), encoding="utf-8")
        datasets.append({"id": ident, "path": f"data/{ident}.csv", "unit": "one synthetic participant", "key": ["id"],
                         "codebook": f"data/{ident}.md", "provenance": f"data/{ident}.prov.jsonl", "review": f"data/{ident}.review.jsonl"})
    registry = {"schema_version": 1, "source_root": "materials", "source_inventory": "output/audit/corpus_files.csv",
                "discovery_report": "output/discovery_report.json",
                "source_coverage": "output/source_coverage.jsonl", "datasets": datasets}
    (root / "research_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    csv_write(root / "output/audit/corpus_files.csv", ["rel_path", "status"], [["raw.csv", "valid"]])
    (root / "output/source_coverage.jsonl").write_text(json.dumps({"source": "raw.csv", "sha256": C.file_sha256(source),
        "status": "included", "reason": "all fixture values are traced to this synthetic original", "datasets": [d["id"] for d in datasets]}) + "\n", encoding="utf-8")
    units = SU.SourceUnits(project, root=root)
    units.build(root / "materials")
    discovery = D.Discovery(project, units)
    discovery.from_materials()
    for candidate in project.read("discovery_candidate"):
        discovery.dispose(candidate["id"], "adopted", dataset="person", reason="the synthetic source column is included with every cell traced")
    (root / "output/discovery_report.json").write_text(json.dumps(discovery.report()), encoding="utf-8")
    final_review(root)
    if fit:
        spec = {"id": "M1", "family": "ols", "purpose": "known synthetic slope",
                "variables": {"y": "y", "x": ["treatment"]},
                "inputs": [{"role": "fit", "dataset": "data/person.csv", "sha256": C.file_sha256(root / "data/person.csv"), "keys": ["id"]}],
                "n_semantics": {"kind": "observation", "unit": "one synthetic participant"},
                "result": {"type": "coefficient_table", "target_parameter": "treatment", "unit": "score points", "scale": "linear"}}
        M.register(project, spec)
        fitted = M.fit(project, "M1")
        if fitted["status"] != "estimated":
            raise ValueError(f"known fit failed: {fitted}")
        checked = V.independent_ols(project, "M1")
        if checked["status"] != "passed":
            raise ValueError(f"known slope arithmetic mismatch: {checked}")
        assessed = DC.record_linkage(project, M.load_spec(project, "M1")["data"])
        if assessed["status"] != "passed":
            raise ValueError(f"known design mismatch: {assessed}")
    return project
