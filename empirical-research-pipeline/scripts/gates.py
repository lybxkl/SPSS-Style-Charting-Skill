"""Read-only research quality inspection and generation-safe report publication."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
from gate_contract import SCHEMA, STATUSES, FEATURES, Inputs, atomic_json, digest, now, read_json, resolve, validate_report, validate_schema
from gate_lock import ProjectLease, recover

PACKAGE=Path(__file__).resolve().parent.parent
CONTRACT=PACKAGE/'contracts/gates'
CHECKPOINTS=['data-ready','analysis-ready','figures-ready','manuscript-ready','delivery-ready']
PILOT={'dataset-in-analysis','fig-dpi','fig-font','qa-numbers'}


def environment():
    from importlib.metadata import version, PackageNotFoundError
    modules={}
    for name in ['pandas','numpy','scipy','statsmodels','matplotlib','PyMuPDF','python-docx','openpyxl','Pillow','jsonschema']:
        try:modules[name]=version(name)
        except PackageNotFoundError:modules[name]=None
    return {'python':sys.version.split()[0],'modules':modules}


def catalog():
    return read_json(CONTRACT/'catalog.json')


def validate_policy(policy):
    validate_schema(policy,'policy')
    requirements={r['gateId']:r for r in policy['requirements']}
    definitions={g['id']:g for g in catalog()['gates']}
    if len(requirements)!=len(policy['requirements']) or set(requirements)!=set(definitions):
        raise ValueError('policy must account for every catalog definition exactly once')
    for ident,definition in definitions.items():
        req=requirements[ident]
        expected=dict(definitionVersion=definition['definitionVersion'],reportStage=definition['reportStage'],
                      displayStage=definition['displayStage'],source=definition['owner'])
        if any(req[k]!=value for k,value in expected.items()):
            raise ValueError('policy definition mismatch')
        if CHECKPOINTS.index(req['blockingAt'])>CHECKPOINTS.index(definition['blockingAt']):
            raise ValueError('cannot postpone a required checkpoint')
        if definition.get('required',True) and req.get('required') is not True:
            raise ValueError('cannot remove a required rule')
        if req['allowNa'] and not definition.get('allowNa',False):
            raise ValueError('cannot widen applicability')
    return policy


def manifest_valid():
    from gate_contract import implementation_members
    value=read_json(CONTRACT/'package-manifest.json')
    declared=[entry['path'] for entry in value['members']]
    if len(declared)!=len(set(declared)) or implementation_members(PACKAGE,declared)!=set(declared):
        raise ValueError('skill implementation membership changed; rebuild package manifest')
    for entry in value['members']:
        if digest(resolve(PACKAGE,entry['path']))!=entry['sha256']:
            raise ValueError('skill implementation changed; rebuild package manifest')
    return digest(CONTRACT/'package-manifest.json')


def validate_current(root, relative):
    root=Path(root).resolve()
    report=validate_report(read_json(resolve(root,relative)))
    state=read_json(root/'output/gates/state'/f"{report['stage']}.json")
    validate_schema(state,'attempt')
    if state.get('phase')!='completed' or state.get('stage')!=report['stage'] or state.get('attemptId')!=report['attemptId'] or state.get('generation')!=report['generation']:
        raise ValueError('report is not the current completed attempt')
    base=f"output/gates/runs/{report['attemptId']}/"
    if not state['requestPath'].startswith(base) or not state['resultPath'].startswith(base):
        raise ValueError('attempt paths do not belong to current attempt')
    request_path=resolve(root,state['requestPath']);result_path=resolve(root,state['resultPath'])
    if digest(request_path)!=state['requestSha256'] or digest(result_path)!=state['resultSha256']:
        raise ValueError('attempt control hash mismatch')
    request=validate_schema(read_json(request_path),'attempt')
    result=validate_schema(read_json(result_path),'attempt')
    for item in (request,result):
        if item['attemptId']!=report['attemptId'] or item['generation']!=report['generation']:
            raise ValueError('attempt generation mismatch')
    if result.get('outcome')!='completed' or result.get('checkerExitCode')!=0 or not result['reportPath'].startswith(base):
        raise ValueError('attempt did not complete successfully')
    if digest(resolve(root,result['reportPath']))!=result['reportSha256'] or digest(resolve(root,relative))!=result['reportSha256']:
        raise ValueError('current report hash mismatch')
    policy=validate_policy(read_json(root/'.workbench/gates/policy.json'))
    expected=sorted(g['id'] for g in catalog()['gates'] if g['owner']=='skill' and g['reportStage']==report['stage'])
    if sorted(request['requestedGateIds'])!=expected or sorted(g['id'] for g in report['gates'])!=expected:
        raise ValueError('report omitted required gate instances')
    if any(request[key]!=report[key] for key in ('stage','checkpoint','scopeKey','catalogSha256','policySha256')):
        raise ValueError('attempt context mismatch')
    if report['catalogSha256']!=digest(CONTRACT/'catalog.json') or report['catalogSha256']!=policy['catalogSha256'] or report['scopeKey']!=policy['scopeKey'] or report['thresholds']!=policy['thresholds']:
        raise ValueError('current catalog or policy mismatch')
    if digest(root/'.workbench/gates/policy.json')!=report['policySha256']:
        raise ValueError('policy changed')
    if manifest_valid()!=report['skill']['manifestSha256']:
        raise ValueError('implementation changed')
    if report['environment']!=environment():
        raise ValueError('interpreter changed')
    for resource in report['resources']:
        from gate_roots import roots_for
        base=root if resource['rootId']=='project' else PACKAGE if resource['rootId']=='skill' else roots_for(root)[resource['rootId']]
        for alias in resource.get('projectPaths',[]):
            from gate_roots import reference
            ident,relative_path,_=reference(root,alias,roots_for(root))
            if (ident,relative_path)!=(resource['rootId'],resource['path']):raise ValueError('project alias changed')
        from gate_roots import reference
        path=reference(root,resource['path'],roots_for(root))[2] if resource['rootId']=='project' else resolve(base,resource['path'])
        if path.is_file()!=resource['exists'] or (resource['exists'] and digest(path)!=resource['sha256']):
            raise ValueError('resource changed')
    for collection in report['collections']:
        from gate_roots import members, roots_for
        roots=roots_for(root)
        base=root if collection['rootId']=='project' else roots[collection['rootId']]
        if members(base,collection['basePath'],roots if collection['rootId']=='project' else {})!=collection['members']:
            raise ValueError('input collection changed')
    return report


def _init_policy(root, *, mode='compare'):
    """Explicit opt-in migration. Existing projects are never silently switched."""
    root=Path(root).resolve()
    path=resolve(root,'.workbench/gates/policy.json')
    if path.exists():
        raise ValueError('policy already exists; explicit migration required')
    if mode not in ('legacy','shadow','compare','skill'):
        raise ValueError('unsupported migration mode')
    value=read_json(CONTRACT/'policy-template.json')
    value.update(mode=mode,researchContract='v2' if (root/'output/v2').is_dir() else 'v1')
    atomic_json(resolve(root,'.workbench/gates/required.json'),{'schema':'dsa.gate-policy-required/1','required':True})
    atomic_json(path,value)
    return value


def _migrate_policy(root, mode=None):
    """Versioned, explicit migration; never delete a required old rule silently."""
    root=Path(root).resolve()
    path=resolve(root,'.workbench/gates/policy.json')
    old=read_json(path)
    definitions={g['id']:g for g in catalog()['gates']}
    missing=[r['gateId'] for r in old['requirements'] if r['gateId'] not in definitions]
    if missing:
        raise ValueError('catalog removed existing project requirements')
    mode=mode or old['mode']
    if mode not in ('legacy','shadow','compare','skill'):
        raise ValueError('unsupported migration mode')
    requirements=[]
    for definition in definitions.values():
        ident=definition['id']
        previous=next((r for r in old['requirements'] if r['gateId']==ident),None)
        requirements.append(dict(gateId=ident,definitionVersion=definition['definitionVersion'],
            reportStage=definition['reportStage'],displayStage=definition['displayStage'],
            blockingAt=definition['blockingAt'],source=definition['owner'],
            allowNa=definition.get('allowNa',False),required=bool((previous or {}).get('required')) or definition.get('required',True)))
    new={**old,'mode':mode,'requirements':requirements,'catalogSha256':digest(CONTRACT/'catalog.json'),
         'researchContract':'v2' if (root/'output/v2').is_dir() else old.get('researchContract','v1')}
    migration='migration-'+secrets.token_hex(12)
    atomic_json(resolve(root,f'.workbench/gates/migrations/{migration}.json'),
                dict(schema='dsa.gate-migration/1',at=now(),before=old,after=new))
    atomic_json(resolve(root,'.workbench/gates/required.json'),{'schema':'dsa.gate-policy-required/1','required':True})
    atomic_json(path,new)
    return new


def init_policy(root, *, mode='compare'):
    with ProjectLease(root,os.environ.get('DSA_GATE_LEASE_TOKEN')):
        return _init_policy(root,mode=mode)


def migrate_policy(root, mode=None):
    with ProjectLease(root,os.environ.get('DSA_GATE_LEASE_TOKEN')):
        return _migrate_policy(root,mode)


def next_generation(root,stage):
    """A damaged current pointer must not prevent a fresh immutable attempt."""
    maximum=0
    candidates=[resolve(root,f'output/gates/state/{stage}.json')]
    history=resolve(root,'output/gates/runs')
    directories=list(history.iterdir()) if history.exists() else []
    if len(directories)>5000:raise ValueError('attempt history exceeds verification budget')
    for directory in directories:
        for name in ('request.json','report.json'):
            candidates.append(resolve(root,(directory/name).relative_to(root).as_posix()))
    for file in candidates:
        if not file.is_file():continue
        try:value=read_json(file)
        except (ValueError,UnicodeError):continue
        if isinstance(value,dict) and value.get('stage')==stage and type(value.get('generation')) is int:
            maximum=max(maximum,value['generation'])
    if maximum>=2**53-1:raise ValueError('generation exceeds consumer precision')
    return maximum+1


def evaluate(root,stage,checkpoint,run_id=None):
    from gate_checks import evaluate as checks, verdict, structure
    root=Path(root).resolve()
    policy_path=resolve(root,'.workbench/gates/policy.json')
    policy=read_json(policy_path)
    validate_policy(policy)
    if any(type(policy['thresholds'].get(k)) not in (int,float) or policy['thresholds'][k]<=0
           for k in ['minEffectiveDpi','minFontPt','figureWidthCm']):
        raise ValueError('invalid thresholds')
    if policy['catalogSha256']!=digest(CONTRACT/'catalog.json'):
        raise ValueError('policy/catalog mismatch; migrate explicitly')
    if checkpoint not in CHECKPOINTS:raise ValueError('unknown checkpoint')
    definitions=[g for g in catalog()['gates'] if g['reportStage']==stage and g['owner']=='skill']
    if not definitions:raise ValueError('stage has no skill gates')
    directory=resolve(root,'output/gates');directory.mkdir(parents=True,exist_ok=True)
    lease = ProjectLease(root, os.environ.get('DSA_GATE_LEASE_TOKEN'))
    lease.__enter__()
    attempt='attempt-'+secrets.token_hex(12)
    state_path=directory/'state'/f'{stage}.json'
    state={};generation=1
    try:
        state_path=resolve(root,f'output/gates/state/{stage}.json')
        base=f'output/gates/runs/{attempt}'
        generation=next_generation(root,stage)
        if state_path.exists():
            previous=resolve(root,base+'/previous-state.bin');previous.parent.mkdir(parents=True,exist_ok=True)
            previous.write_bytes(state_path.read_bytes())
        request=dict(schema='dsa.gate-attempt/1',attemptId=attempt,generation=generation,stage=stage,checkpoint=checkpoint,scopeKey=policy['scopeKey'],requestedAt=now(),requestedGateIds=[g['id'] for g in definitions],catalogSha256=policy['catalogSha256'],policySha256=digest(policy_path),producerContext=[run_id] if run_id else [])
        atomic_json(resolve(root,base+'/request.json'),request)
        state=dict(schema='dsa.gate-state/1',stage=stage,attemptId=attempt,generation=generation,phase='running',requestPath=base+'/request.json',requestSha256=digest(root/base/'request.json'))
        atomic_json(state_path,state)
        inputs=Inputs(root)
        inputs.file('.workbench/gates/policy.json')
        manifest=manifest_valid()
        runtime=environment()
        actual={g['id']:g for g in checks(inputs,policy,stage)}
        from gate_facts import evaluate_artifacts
        actual.update({g['id']: g for g in evaluate_artifacts(inputs, policy, definitions)})
        gates=[]
        for definition in definitions:
            ident=definition['id']
            gates.append(actual.get(ident) or verdict(ident,'unjudged','本版本尚未实现此判据',[],[structure('.workbench/gates/policy.json','implemented evaluator',ident)],'not-supported'))
        for gate in gates:
            gate['inputRefs']=sorted({inputs.aliases.get(ref,ref) for ref in gate['inputRefs']}|{'.workbench/gates/policy.json','.workbench/gates/roots.json'})
            gate['collectionRefs']=sorted(inputs.collection_aliases.get(ref,ref) for ref in gate['collectionRefs'])
            for evidence in gate['evidence']:
                evidence['resourceRef']=inputs.aliases.get(evidence['resourceRef'],evidence['resourceRef'])
            if gate.get('applicability'):
                gate['applicability']['evidenceRefs']=[inputs.aliases.get(ref,ref) for ref in gate['applicability']['evidenceRefs']]
        report=dict(schema=SCHEMA,protocolVersion='1.0',reportId='report-'+attempt,attemptId=attempt,generation=generation,stage=stage,checkpoint=checkpoint,scopeKey=policy['scopeKey'],generatedAt=now(),producer=dict(entry='scripts/gates.py',version='1.0.0',argv=['evaluate','--stage',stage,'--checkpoint',checkpoint],exitCode=0),productionRuns=[{'runId':run_id}] if run_id else [],skill=dict(name='empirical-research-pipeline',manifestSha256=manifest),catalogSha256=request['catalogSha256'],policySha256=request['policySha256'],environment=environment(),resources=sorted(inputs.resources.values(),key=lambda r:r['id']),collections=sorted(inputs.collections.values(),key=lambda c:c["id"]),thresholds=policy['thresholds'],gates=gates,summary={s:sum(g['status']==s for g in gates) for s in STATUSES},requiredFeatures=sorted(FEATURES))
        validate_report(report)
        if not inputs.unchanged() or manifest_valid()!=manifest or environment()!=runtime:
            raise ValueError('inputs or implementation changed during evaluation')
        atomic_json(resolve(root,base+'/report.json'),report)
        result=dict(schema='dsa.gate-result/1',attemptId=attempt,generation=generation,outcome='completed',finishedAt=now(),checkerExitCode=0,reportPath=base+'/report.json',reportSha256=digest(root/base/'report.json'))
        atomic_json(resolve(root,base+'/result.json'),result)
        current=read_json(state_path)
        if current['attemptId']!=attempt or current['generation']!=generation:raise ValueError('publication generation conflict')
        state.update(phase='completed',resultPath=base+'/result.json',resultSha256=digest(root/base/'result.json'),updatedAt=now())
        atomic_json(state_path,state)
        atomic_json(directory/f'{stage}.json',report)
        return report
    except Exception as exc:
        if state:
            error=dict(schema='dsa.gate-error/1',attemptId=attempt,generation=generation,reason=type(exc).__name__,detail='体检未完成，请查看本地运行日志',finishedAt=now())
            atomic_json(resolve(root,base+'/error.json'),error)
            atomic_json(directory/f'{stage}.error.json',error)
            state.update(phase='crashed',updatedAt=now())
            atomic_json(state_path,state)
        raise
    finally:
        lease.__exit__()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['catalog','environment','init-policy','migrate-policy','evaluate','validate-report','recover'])
    parser.add_argument('--mode',choices=['legacy','shadow','compare','skill'])
    parser.add_argument('--root',default='.')
    parser.add_argument('--stage',default='dataset')
    parser.add_argument('--checkpoint',default='data-ready',choices=CHECKPOINTS)
    parser.add_argument('--run-id')
    parser.add_argument('--report')
    args=parser.parse_args(argv)
    try:
        if args.action=='environment':
            print(json.dumps(environment(),sort_keys=True));return 0
        if args.action=='catalog':result=catalog()
        elif args.action=='init-policy':result=init_policy(args.root,mode=args.mode or 'compare')
        elif args.action=='migrate-policy':result=migrate_policy(args.root,args.mode)
        elif args.action=='validate-report':result=validate_current(args.root,args.report)
        elif args.action=='recover':result=recover(args.root)
        else:result=evaluate(args.root,args.stage,args.checkpoint,args.run_id)
        print(json.dumps({'ok':True,'summary':result.get('summary'),'schema':result['schema']},ensure_ascii=False))
        return 0
    except FileExistsError:
        print(json.dumps({'ok':False,'reason':'conflict'}));return 3
    except Exception as exc:
        print(json.dumps({'ok':False,'reason':type(exc).__name__}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
