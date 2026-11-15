"""Record verified delivery evidence; refuses to infer test success from files."""
from pathlib import Path
import csv
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'empirical-research-pipeline'
WORKBENCH=Path('F:/deepseek-data-analysis/dsh-data-analysis')
OUT=ROOT/'docs/gate-report-implementation'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo,*args):
    result=subprocess.run(['git',*args],cwd=repo,capture_output=True)
    return result.stdout.decode('utf-8',errors='replace').strip()


def source_bindings():
    files=set(PACKAGE.rglob('*.py'))|set((PACKAGE/'contracts').rglob('*.json'))|set((PACKAGE/'references').glob('*.md'))|{PACKAGE/'SKILL.md'}
    files|=set((ROOT/'tests').glob('*.py'))|set((ROOT/'tools').glob('*.py'))|{ROOT/'requirements.txt',ROOT/'requirements-dev.txt'}
    files|=set((WORKBENCH/'src').glob('*.js'))|set((WORKBENCH/'assets').rglob('*'))|{WORKBENCH/'client.js',WORKBENCH/'index.js',WORKBENCH/'package.json',WORKBENCH/'README.md'}
    files|=set((WORKBENCH/'tests').glob('*.mjs'))
    return [{'path':str(p),'sha256':sha(p)} for p in sorted(files) if p.is_file() and '__pycache__' not in p.parts]


def main():
    observed=json.loads((OUT/'verification-results.json').read_text(encoding='utf-8'))
    required=['skillFull','skillTargeted','workbenchFull','crossRuntime','archiveBuild','cleanPackage','installedPackage','skillValidate','pluginPackage','protocolFixtures']
    for key in required:
        result=observed[key]
        if result['exitCode']!=0:raise ValueError('failed delivery check: '+key)
        log=Path(result['log'])
        if not log.is_file() or sha(log)!=result['logSha256']:raise ValueError('evidence changed: '+key)
    catalog=json.loads((PACKAGE/'contracts/gates/catalog.json').read_text(encoding='utf-8'))
    import sys
    sys.path.insert(0,str(PACKAGE/'scripts'))
    import gate_facts,gates,gate_checks
    import inspect
    rows=[]
    for definition in catalog['gates']:
        ident=definition['id']
        if definition['owner']=='skill':
            function=gate_facts.HANDLERS.get(ident) or {'dataset-in-analysis':gate_checks.dataset,'qa-numbers':gate_checks.numbers,'fig-dpi':gate_checks.layout,'fig-font':gate_checks.layout}.get(ident)
            if function is None:raise ValueError('missing dispatch: '+ident)
            file=Path(inspect.getfile(function));line=inspect.getsourcelines(function)[1]
            source=f'{file}:{line} ({function.__name__})'
        else:
            source=str(WORKBENCH/'src/gate-host.js')+' (evaluateHostProject)'
        rows.append({**definition,'source':source,'testEvidence':'skillFull/crossRuntime; see verification-results.json','coverageMeaning':'actual evaluator, not a project pass'})
    (OUT/'source-map.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (OUT/'gate-inventory.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['id','owner','reportStage','displayStage','blockingAt','required','allowNa','source'])
        writer.writeheader();writer.writerows({k:r.get(k) for k in writer.fieldnames} for r in rows)
    bindings=source_bindings()
    groups={
      'T00':['skillFull','workbenchFull'],'T01':['skillFull','crossRuntime'],'T02':['skillFull','crossRuntime'],
      'T03':['skillFull','crossRuntime'],'T04':['crossRuntime'],'T05':['crossRuntime','workbenchFull'],
      'T06':['workbenchFull'],'T07':['skillFull','crossRuntime'],'T08':['skillFull','crossRuntime'],
      'T09':['crossRuntime','workbenchFull'],'T10':['skillFull','workbenchFull','cleanPackage'],
      'T11':['archiveBuild','cleanPackage','installedPackage','skillValidate']}
    state={'planVersion':'1.0','status':'completed','releaseReady':True,'currentTask':'T11',
      'scope':'implementation and synthetic technical acceptance; no research signoff',
      'historicalGateCount':70,'addedGateCount':6,'gateCount':len(rows),
      'owners':{owner:sum(r['owner']==owner for r in rows) for owner in ['skill','workbench']},
      'defaultNewProjectMode':'skill','existingProjectMigration':'explicit, default compare',
      'tasks':[{'id':key,'status':'passed','evidence':values} for key,values in groups.items()],
      'evidence':observed,'sourceBindings':bindings,
      'limitations':['Technical acceptance uses explicitly synthetic projects; no real research was approved or signed.',
        'Old artifacts without production-time content bindings require minimal production reruns.',
        'Unsupported opaque claim references remain unjudged; neither missing evidence nor limited v2 release is full delivery readiness.',
        'Current implementation uses project-wide serialization and strong synchronous content validation; large projects can make refresh slower.',
        'No automatic history deletion; installed extras are preserved and the prior active package is backed up.']}
    (OUT/'implementation-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    snapshot={'kind':'delivery-worktree-snapshot','repositories':[{'root':str(repo),'head':git(repo,'rev-parse','HEAD'),'status':git(repo,'status','--short'),'diffSha256':hashlib.sha256(git(repo,'diff','--binary').encode()).hexdigest()} for repo in [ROOT,WORKBENCH]],'sourceBindings':bindings}
    (OUT/'delivery-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':state['status'],'gateCount':len(rows),'owners':state['owners']}))


if __name__=='__main__':main()
