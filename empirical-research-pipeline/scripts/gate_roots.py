"""Resolve only explicitly registered material roots; reports keep logical ids."""
from pathlib import Path, PurePosixPath
import os

from gate_contract import read_json, resolve


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
        if len(visited)>5000:raise ValueError('collection directory budget exceeded')
        for name in files:
            rel=(Path(current)/name).relative_to(root).as_posix()
            reference(root,rel,roots)
            result.append(rel)
            if len(result)>5000:raise ValueError('collection exceeds verification budget')
    return sorted(result)
