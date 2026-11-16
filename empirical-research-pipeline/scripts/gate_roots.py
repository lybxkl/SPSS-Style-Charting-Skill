"""Resolve only explicitly registered material roots; reports keep logical ids."""
from pathlib import Path, PurePosixPath
import os

from gate_contract import read_json, resolve


def source_path(project, scope, relative, registered=None):
    """Read a lexical source identity, including explicitly registered mounts."""
    from gate_contract import relative_path
    relative_path(relative)
    base = Path(scope).resolve()
    target = (Path(scope) / relative).resolve()
    if target.is_relative_to(base):
        return target
    if any(target.is_relative_to(root) for root in (roots_for(project) if registered is None else registered).values()):
        return target
    raise ValueError('source inventory path escapes source_root (unregistered mount)')


def source_members(project, scope):
    """Keep lexical paths while traversing registered directory junctions."""
    scope = Path(scope).absolute()
    registered = roots_for(project)
    seen, result = set(), []
    def unreadable(error): raise error
    for current, dirs, files in os.walk(scope, followlinks=True, onerror=unreadable):
        actual = Path(current).resolve()
        relative = Path(current).relative_to(scope).as_posix()
        if relative != '.': source_path(project, scope, relative, registered)
        if actual in seen: raise ValueError('cycle or duplicate directory in source scope')
        seen.add(actual)
        for name in files:
            relative = (Path(current) / name).relative_to(scope).as_posix()
            source_path(project, scope, relative, registered)
            result.append(relative)
    return sorted(result)


def roots_for(root):
    file=resolve(root,'.workbench/gates/roots.json')
    if not file.is_file():return {}
    value=read_json(file)
    if value.get('schema')!='dsa.gate-roots/1' or not isinstance(value.get('roots'),dict):
        raise ValueError('invalid material roots declaration')
    result={}
    for key,path in value['roots'].items():
        if not key.startswith('material:') or not isinstance(path,str) or not Path(path).is_absolute():
            raise ValueError('invalid material root identity')
        result[key]=Path(path).resolve()
    return result


def reference(root,relative,roots):
    if not isinstance(relative,str) or not relative or '\\' in relative or ':' in relative or '\0' in relative:
        raise ValueError('unsafe resource path')
    parsed=PurePosixPath(relative)
    if parsed.is_absolute() or '..' in parsed.parts or str(parsed)!=relative:
        raise ValueError('unsafe resource path')
    target=(Path(root)/relative).resolve()
    try:return 'project',target.relative_to(Path(root).resolve()).as_posix(),target
    except ValueError:pass
    for key,base in sorted(roots.items(),key=lambda x:len(str(x[1])),reverse=True):
        try:return key,target.relative_to(base).as_posix(),target
        except ValueError:continue
    raise ValueError('unregistered external resource')


def absolute_reference(root,path,roots):
    target=Path(path).resolve()
    bases={'project':Path(root).resolve(),'skill':Path(__file__).resolve().parent.parent,**roots}
    for key,base in sorted(bases.items(),key=lambda x:len(str(x[1])),reverse=True):
        try:return key,target.relative_to(base).as_posix(),target
        except ValueError:continue
    raise ValueError('unregistered absolute resource')


def members(root,relative,roots):
    _,_,base=reference(root,relative,roots)
    if not base.is_dir():return []
    lexical=Path(root)/relative
    visited=set();result=[]
    def unreadable(error):raise error
    for current,dirs,files in os.walk(lexical,followlinks=True,onerror=unreadable):
        actual=Path(current).resolve()
        reference(root,Path(current).relative_to(root).as_posix(),roots)
        if actual in visited:raise ValueError('cycle or duplicate directory in source collection')
        visited.add(actual)
        for name in files:
            rel=(Path(current)/name).relative_to(root).as_posix()
            reference(root,rel,roots)
            result.append(rel)
    return sorted(result)
