"""Isolated verification of the built .skill archive (no repo imports)."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
dist = os.path.join(ROOT, "dist", "empirical-research-pipeline.skill")
target = tempfile.mkdtemp(prefix="skill-install-")
with zipfile.ZipFile(dist) as zf:
    names = zf.namelist()
    zf.extractall(target)
print(json.dumps({
    "files": len(names),
    "has_tests": any(n.startswith("tests/") for n in names),
    "has_docs": any(n.startswith("docs/") for n in names),
    "has_pycache": any("__pycache__" in n for n in names),
    "sha256": hashlib.sha256(open(dist, "rb").read()).hexdigest(),
}, ensure_ascii=False))

script = r"""
import json, sys, tempfile, os
sys.path.insert(0, r"%s/empirical-research-pipeline/scripts")
sys.path.insert(0, r"%s/empirical-research-pipeline")
import contract_v2, source_units, models, validation, claims, refs
import manuscript, designcheck, figsemantics, faults, release, txn
print(json.dumps({
  "contract": contract_v2.SCHEMA_VERSION,
  "kinds": len(contract_v2.STATUSES),
  "providers": {k: v.available() for k, v in
                __import__("ocr_provider").providers().items()},
  "asr": list(__import__("asr_provider").providers()),
  "manuscript_sections": list(manuscript.REQUIRED_SECTIONS),
  "design_features": len(designcheck.LINKAGE),
}, ensure_ascii=False))
proj = contract_v2.Project(tempfile.mkdtemp())
units = source_units.SourceUnits(proj, root=tempfile.mkdtemp())
print("ok", units.summary()["logical_units"])
""" % (target, target)
proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                      text=True, timeout=300)
print("rc", proc.returncode)
print(proc.stdout.strip()[:800])
print(proc.stderr.strip()[-400:])



