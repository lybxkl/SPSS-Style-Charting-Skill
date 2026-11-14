"""Check the actual archive in an isolated directory, using installed dependencies.

This does not claim a fresh Python environment or any uninstalled engine.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[2]
archive=ROOT/"dist/empirical-research-pipeline.skill"
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
assert (ROOT/"dist/empirical-research-pipeline.skill.sha256").read_text().split()[0]==digest
with tempfile.TemporaryDirectory(prefix="research-skill-install-") as temporary:
    dest=Path(temporary)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        assert z.testzip() is None
        assert not any("__pycache__" in n or "/tests/" in n or "/docs/" in n for n in names)
        for name in names:
            target=(dest/name).resolve()
            assert dest.resolve() in target.parents
        z.extractall(dest)
    scripts=dest/"empirical-research-pipeline/scripts"
    code=r'''
from pathlib import Path
import importlib,json,sys
scripts=Path(sys.argv[1]);sys.path.insert(0,str(scripts))
modules=sorted(p.stem for p in scripts.glob('*.py'))
for name in modules:importlib.import_module(name)
import contract_v2 as C,models as M
project=C.Project(Path.cwd()/'project');path=project.root/'problem.json'
parameters={'c':[1],'A_ub':[[-1]],'b_ub':[-1.5],'bounds':[[0,4]],'integrality':[1]}
path.write_text(json.dumps(parameters),encoding='utf-8')
spec={'id':'ISOLATED-MILP','family':'milp','purpose':'integer known-answer package check',
      'inputs':[{'role':'constraints','dataset':'problem.json','sha256':C.file_sha256(path),'keys':[]}],
      'n_semantics':{'kind':'none'},'dimensions':1,'constraints':['x >= 1.5','x integer'],
      'parameters':parameters,'result':{'type':'optimum','target_parameter':'objective','unit':'synthetic units','scale':'linear'}}
M.register(project,spec);run=M.solve(project,spec['id']);result=project.latest('model_result',spec['id'])['data']['payload']
assert result['solution']==[2.0],(run,result)
assert result['n'] is None
assert result['solve_quality']=='certified_global',result
print(json.dumps({'imported_modules':modules,'known_answer':result,'run':run},ensure_ascii=False))
'''
    env=dict(os.environ,PYTHONUTF8="1",MPLBACKEND="Agg")
    result=subprocess.run([sys.executable,"-c",code,str(scripts)],cwd=dest,capture_output=True,text=True,encoding="utf-8",env=env,timeout=180)
    (ROOT/"docs/remediation-2026-11-14/isolated-package.log").write_text(result.stdout+"\n"+result.stderr,encoding="utf-8")
    assert result.returncode==0,result.stdout+result.stderr
    observed=json.loads(result.stdout.strip().splitlines()[-1])
    record={"status":"passed","archive":str(archive.relative_to(ROOT)),"archive_sha256":digest,"archive_files":len(names),
            "bytes":archive.stat().st_size,"dependency_scope":"isolated unpack directory; existing configured Python/dependencies; no fresh-environment or uninstalled-engine claim",
            "observed":observed}
    (ROOT/"docs/remediation-2026-11-14/isolated-package.json").write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in record.items() if k!="observed"},ensure_ascii=False))
