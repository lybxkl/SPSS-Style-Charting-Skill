"""Validate the package-owned workflow without executing research or altering a project."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import jsonschema

FEATURES={'dag-v1','bindings-v1','actions-v1','gate-admission-v1','ui-v1'}
PANELS={'corpus','analysis','models','figures','numbers','qa','manuscript','manuscriptSpec','recheck'}

def read(file):
    if file.stat().st_size>2*1024*1024:raise ValueError('workflow budget')
    def pairs(rows):
        result={}
        for key,value in rows:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    return json.loads(file.read_text(encoding='utf-8'),object_pairs_hook=pairs)

def relative(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or '\0' in value or PurePosixPath(value).is_absolute() or '..' in value.split('/') or str(PurePosixPath(value))!=value:
        raise ValueError('unsafe workflow path')

def validate(package):
    package=Path(package).resolve()
    file=package/'contracts/workflow/workflow.json'
    file.resolve().relative_to(package)
    file.with_name('workflow.schema.json').resolve().relative_to(package)
    spec=read(file)
    jsonschema.Draft202012Validator(read(file.with_name('workflow.schema.json'))).validate(spec)
    if set(spec['requiredFeatures'])-FEATURES:raise ValueError('unsupported workflow features')
    if not 0<len(spec['stages'])<=200 or len(spec['actions'])>400:raise ValueError('workflow budget')
    ids=[s['id'] for s in spec['stages']]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate stage ID')
    seen=set()
    for stage in spec['stages']:
        if any(dep not in seen for dep in stage['dependsOn']):raise ValueError('unknown, cyclic or out-of-order dependency')
        seen.add(stage['id'])
        if set(stage['ui']['panels'])-PANELS:raise ValueError('unsupported UI panel')
        for value in stage['artifacts']+stage['ui'].get('requiredFiles',[])+[p.rstrip('/') for p in stage['ui'].get('artifactPrefixes',[])]:relative(value)
        if stage['ui'].get('legacySkipWhenMissing'):relative(stage['ui']['legacySkipWhenMissing'])
    actions=set();tools=set()
    for action in spec['actions']:
        if action['id'] in actions or action['stage'] not in seen:raise ValueError('invalid action reference')
        actions.add(action['id'])
        if action.get('tool'):
            key=(action['tool'],action.get('variant',''))
            if key in tools:raise ValueError('duplicate action tool binding')
            tools.add(key)
        if action.get('outFile'):relative(action['outFile'])
    tasks=set()
    for task in spec['draftTasks']:
        if task['stage'] not in seen or task['id'] in tasks:raise ValueError('invalid draft task')
        tasks.add(task['id']);relative(task['file'])
        for value in task.get('contextFiles',[]):relative(value)
    for stage in spec['stages']:
        if stage['ui'].get('draftTask') and stage['ui']['draftTask'] not in tasks:raise ValueError('unknown draft task')
    for rule in spec['rerunRules']:
        relative(rule['pattern'].rstrip('/'))
        if any(stage not in seen for stage in rule['stages']):raise ValueError('unknown rerun stage')
    for directory in spec['workspace']['directories']:relative(directory)
    for owner in spec['stages']+spec['actions']:
        for key in ['admission','afterRun','legacyAdmission']:
            if owner.get(key,{}).get('whenFile'):relative(owner[key]['whenFile'])
        for step in [owner]+owner.get('steps',[]):
            for key in ['script','whenFile']:
                if step.get(key):relative(step[key])
            for value in step.get('produces',[]):relative(value)
            for option in step.get('optionalArgs',[])+step.get('optionalFlags',[]):
                for key in ['file','whenFile']:
                    if option.get(key):relative(option[key])
    tokens=set()
    for binding in spec['argumentBindings']:
        if binding['token'] in tokens:raise ValueError('duplicate argument binding')
        if binding['select']=='directory-of' and binding.get('from') not in tokens:raise ValueError('invalid binding dependency')
        tokens.add(binding['token'])
        for value in binding.get('paths',[]):relative(value if isinstance(value,str) else value['json'])
        if binding.get('fallback'):relative(binding['fallback'])
        for value in binding.get('cases',{}).values():relative(value)
    return {**spec,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['validate','describe'])
    parser.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    try:
        value=validate(args.package)
        print(json.dumps(value if args.action=='describe' else {'ok':True,'id':value['id'],'stages':len(value['stages']),'sha256':value['sha256']},ensure_ascii=False))
        return 0
    except (OSError,ValueError,jsonschema.ValidationError) as error:
        print('Invalid workflow: '+str(error),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
