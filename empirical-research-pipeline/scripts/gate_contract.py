"""Portable gate protocol primitives. No research decision is made here."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import tempfile
from datetime import datetime, timezone

SCHEMA = 'dsa.gates/1'
STATUSES = ('pass', 'fail', 'unjudged', 'na')
FEATURES = {'coverage-v1','relative-roots-v1','project-aliases-v1','package-closure-v1'}


def validate_schema(value, name):
    from jsonschema import Draft202012Validator
    schema=read_json(Path(__file__).resolve().parent.parent/'contracts/gates'/f'{name}.schema.json')
    Draft202012Validator(schema).validate(value)
    return value


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def digest(path):
    if Path(path).stat().st_size > 2 * 1024 ** 3:
        raise ValueError('file exceeds verification budget')
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key: ' + key)
        out[key] = value
    return out


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=_pairs,
                      parse_float=finite_float,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def finite_float(value):
    result=float(value)
    if not math.isfinite(result):raise ValueError('nonfinite JSON number')
    return result


def relative_path(relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative or '\0' in relative:
        raise ValueError('unsafe relative path')
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or str(p) != relative:
        raise ValueError('unsafe relative path')
    return p


def resolve(root, relative):
    p=relative_path(relative)
    root = Path(root).resolve()
    target = (root / relative).resolve()
    target.relative_to(root)
    return target


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def implementation_members(package,declared):
    """Check the full shipped directories, including newly added importable code."""
    package=Path(package).resolve()
    prefixes={p.split('/',1)[0] for p in declared if '/' in p}
    actual={p for p in declared if '/' not in p and resolve(package,p).is_file()}
    seen=set()
    def unreadable(error):raise error
    for prefix in prefixes:
        for current,dirs,files in os.walk(resolve(package,prefix),followlinks=True,onerror=unreadable):
            relative=Path(current).relative_to(package).as_posix()
            physical=resolve(package,relative)
            if physical in seen:raise ValueError('implementation directory cycle')
            seen.add(physical)
            if len(seen)>5000:raise ValueError('implementation directory budget exceeded')
            dirs[:]=[d for d in dirs if d!='__pycache__']
            for name in files:
                rel=(Path(current)/name).relative_to(package).as_posix()
                if name=='package-manifest.json' or Path(name).suffix in ('.pyc','.pyo'):continue
                resolve(package,rel)
                actual.add(rel)
                if len(actual)>5000:raise ValueError('implementation budget exceeded')
    return actual


def validate_report(report):
    validate_schema(report, 'report')
    required = {'schema','protocolVersion','reportId','attemptId','generation','stage','checkpoint',
                'scopeKey','generatedAt','producer','productionRuns','skill','catalogSha256',
                'policySha256','environment','resources','collections','thresholds','gates','summary','requiredFeatures'}
    if not required <= report.keys() or report['schema'] != SCHEMA:
        raise ValueError('unsupported or incomplete gate report')
    if set(report['requiredFeatures']) - FEATURES:
        raise ValueError('unsupported required feature')
    resource_ids = [r['id'] for r in report['resources']]
    collection_ids = [c['id'] for c in report['collections']]
    if len(set(collection_ids)) != len(collection_ids):
        raise ValueError('duplicate collection')
    if len(set(resource_ids)) != len(resource_ids):
        raise ValueError('duplicate resource')
    for r in report['resources']:
        relative_path(r['path'])
        for alias in r.get('projectPaths',[]):relative_path(alias)
        if r['rootId'] not in ('project', 'skill') and not r['rootId'].startswith('material:'):
            raise ValueError('unregistered resource root')
    counts = dict.fromkeys(STATUSES, 0)
    seen = set()
    for g in report['gates']:
        if g['id'] in seen or g['status'] not in counts:
            raise ValueError('duplicate gate or unknown status')
        seen.add(g['id'])
        counts[g['status']] += 1
        if not set(g['inputRefs']) <= set(resource_ids) or not g['evidence']:
            raise ValueError('missing evidence or unresolved reference')
        if any(e.get('resourceRef') not in resource_ids for e in g['evidence']):
            raise ValueError('unresolved evidence reference')
        if not set(g['collectionRefs']) <= set(collection_ids):
            raise ValueError('unresolved collection reference')
        c = g['coverage']
        if any(type(c[k]) is not int or c[k] < 0 for k in ('expected','checked','failed','unjudged')):
            raise ValueError('invalid coverage')
        if c['expected'] != c['checked'] + c['unjudged'] or c['failed'] > c['checked']:
            raise ValueError('inconsistent coverage')
        if g['status'] == 'pass' and (not c['expected'] or c['unjudged'] or c['failed']):
            raise ValueError('incomplete pass')
        if g['status'] == 'unjudged' and not g.get('reason'):
            raise ValueError('unjudged without reason')
        if g['status'] == 'na' and not g.get('applicability'):
            raise ValueError('na without applicability')
    if counts != report['summary']:
        raise ValueError('inconsistent summary')
    return report


class Inputs:
    """Capture every file read; re-read all hashes before publication."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.resources = {}
        self.collections = {}
        self.aliases = {}
        self.collection_aliases = {}
        from gate_roots import roots_for
        self.material_roots = roots_for(self.root)
        self.file('.workbench/gates/roots.json')

    def collection(self, relative):
        from gate_roots import members as enumerate_members, absolute_reference
        raw=str(relative)
        if Path(raw).is_absolute():
            root_id,base_path,_=absolute_reference(self.root,raw,self.material_roots)
            base=self.root if root_id=='project' else self.material_roots[root_id]
            ident=root_id+':'+base_path
        else:
            root_id,base_path,base,ident='project',raw,self.root,raw
        members = enumerate_members(base,base_path,self.material_roots if root_id=='project' else {})
        self.collection_aliases[raw]=ident
        record=dict(id=ident,rootId=root_id,basePath=base_path,
                    selector={'recursive':True},members=members,complete=True)
        if ident in self.collections and self.collections[ident]!=record:
            raise ValueError('input collection changed during inspection')
        self.collections.setdefault(ident,record)
        for member in members:
            self.file(member if root_id=='project' else str(base/member))
        return members

    def file(self, relative):
        from gate_roots import reference, absolute_reference
        relative=str(relative)
        if Path(relative).is_absolute():
            root_id,resource_path,path=absolute_reference(self.root,relative,self.material_roots)
            ident=root_id+':'+resource_path
        else:
            root_id,resource_path,path = reference(self.root,relative,self.material_roots)
            ident=relative
        project_path=None
        if Path(relative).is_absolute():
            try:project_path=Path(os.path.abspath(relative)).relative_to(self.root).as_posix()
            except ValueError:pass
        else:project_path=relative
        self.aliases[relative]=ident
        if ident in self.resources:
            previous=self.resources[ident]
            if (previous['rootId'],previous['path'])!=(root_id,resource_path):
                raise ValueError('project resource alias changed during inspection')
        if ident not in self.resources:
            record = {'id':ident, 'rootId':root_id, 'path':resource_path, 'exists':path.is_file()}
            if record['exists']:
                st = path.stat()
                record.update(bytes=st.st_size, sha256=digest(path), mtimeMs=int(st.st_mtime_ns // 1000000))
            self.resources[ident] = record
        if project_path is not None:
            aliases=self.resources[ident].setdefault('projectPaths',[])
            if project_path not in aliases:aliases.append(project_path)
        return path

    def unchanged(self):
        from gate_roots import roots_for,reference
        if roots_for(self.root)!=self.material_roots:return False
        for c in self.collections.values():
            from gate_roots import members as enumerate_members
            base=self.root if c['rootId']=='project' else self.material_roots[c['rootId']]
            members=enumerate_members(base,c['basePath'],self.material_roots if c['rootId']=='project' else {})
            if members != c['members']:
                return False
        for record in self.resources.values():
            base = self.root if record['rootId'] == 'project' else Path(__file__).resolve().parent.parent if record['rootId']=='skill' else self.material_roots[record['rootId']]
            for alias in record.get('projectPaths',[]):
                ident,relative,_=reference(self.root,alias,self.material_roots)
                if (ident,relative)!=(record['rootId'],record['path']):return False
            path = reference(self.root,record['path'],self.material_roots)[2] if record['rootId']=='project' else resolve(base, record['path'])
            if path.is_file() != record['exists']:
                return False
            if record['exists'] and digest(path) != record['sha256']:
                return False
        return True
