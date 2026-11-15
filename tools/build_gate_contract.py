"""Generate the gate catalog baseline and bind all skill code and rules."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PACKAGE=ROOT/'empirical-research-pipeline'
DEST=PACKAGE/'contracts/gates'


def build():
    DEST.mkdir(parents=True,exist_ok=True)
    # The checked-in catalog, not a design document or another repository, is
    # authoritative. Builds never regenerate definitions from prose.
    records=json.loads((DEST/'catalog.json').read_text(encoding='utf-8'))['gates']
    assert len({r['id'] for r in records})==len(records)
    def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    write(DEST/'catalog.json',{'schema':'dsa.gate-catalog/1','gates':sorted(records,key=lambda g:g['id'])})
    write(DEST/'policy-template.json',dict(schema='dsa.gate-policy/1',mode='skill',scopeKey='project',researchContract='v1',
        catalogSha256=hashlib.sha256((DEST/'catalog.json').read_bytes()).hexdigest(),
        thresholds=dict(minEffectiveDpi=597,minFontPt=7.2,figureWidthCm=15),
        requirements=[dict(gateId=g['id'],definitionVersion=g['definitionVersion'],reportStage=g['reportStage'],displayStage=g['displayStage'],blockingAt=g['blockingAt'],source=g['owner'],allowNa=g.get('allowNa',False),required=g.get('required',True)) for g in sorted(records,key=lambda g:g['id'])]))
    members=[]
    for directory in ['scripts','references','contracts/gates','profiles','assets']:
        for path in sorted((PACKAGE/directory).rglob('*')):
            if not path.is_file() or path.suffix in ('.pyc','.pyo') or '__pycache__' in path.parts or path.name=='package-manifest.json':continue
            members.append(dict(path=path.relative_to(PACKAGE).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    path=PACKAGE/'SKILL.md';members.append(dict(path='SKILL.md',sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    write(DEST/'package-manifest.json',{'schema':'dsa.package-manifest/1','members':sorted(members,key=lambda r:r['path'])})


if __name__=='__main__':build()
