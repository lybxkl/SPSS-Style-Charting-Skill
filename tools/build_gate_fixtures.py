"""Persist explicit synthetic protocol examples and verify their known outcomes."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
from jsonschema import ValidationError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'empirical-research-pipeline/scripts'))
import gates
import gate_contract as C


def main():
    out=ROOT/'docs/gate-report-implementation/evidence/fixtures'
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dsa-synthetic-protocol-') as temp:
        root=Path(temp)
        gates.init_policy(root)
        data=root/'output/dataset/analysis.csv';data.parent.mkdir(parents=True,exist_ok=True)
        data.write_text('id,in_analysis\nsynthetic-a,1\nsynthetic-b,0\n',encoding='utf-8')
        report=gates.evaluate(root,'dataset','data-ready')
        project=out/('synthetic-project-'+uuid.uuid4().hex[:8])
        shutil.copytree(root,project)
        assert gates.validate_current(project,'output/gates/dataset.json')==report
    C.atomic_json(out/'valid-report.json',report)
    cases={}
    candidate=copy.deepcopy(report);candidate['summary']['pass']+=1;cases['wrong-summary']=candidate
    candidate=copy.deepcopy(report);candidate['requiredFeatures'].append('unknown-required-capability');cases['unknown-capability']=candidate
    candidate=copy.deepcopy(report);candidate['resources'][0]['path']='../outside';cases['outside-root']=candidate
    candidate=copy.deepcopy(report);candidate['gates'][0]['collectionRefs']=['unresolved'];cases['dangling-collection']=candidate
    candidate=copy.deepcopy(report);candidate['gates'][0]['inputRefs']=['unresolved'];cases['dangling-resource']=candidate
    for name,value in cases.items():
        C.atomic_json(out/(name+'.json'),value)
        try:C.validate_report(value)
        except (ValueError,ValidationError):pass
        else:raise AssertionError(name+' unexpectedly passed')
    duplicate=out/'duplicate-keys.json';duplicate.write_text('{"mode":"skill","mode":"legacy"}',encoding='utf-8')
    try:C.read_json(duplicate)
    except ValueError:pass
    else:raise AssertionError('duplicate keys unexpectedly accepted')
    C.atomic_json(out/'fixture-index.json',{'synthetic':True,'project':str(project),'accepted':['valid-report.json'],
        'rejected':[name+'.json' for name in cases]+['duplicate-keys.json'],'movedProjectValidated':True})
    print(json.dumps({'accepted':1,'rejected':len(cases)+1,'movedProjectValidated':True,'project':str(project)},ensure_ascii=False))


if __name__=='__main__':main()
