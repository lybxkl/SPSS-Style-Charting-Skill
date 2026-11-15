"""Quality facts, kept beside the production implementations they inspect."""
from __future__ import annotations
import csv
from gate_contract import read_json


def verdict(ident, status, detail, refs, evidence, reason=None, expected=1, checked=None, failed=None):
    checked = (0 if status == 'unjudged' else expected) if checked is None else checked
    out = dict(id=ident, definitionVersion='2.0', level='error',status=status,detail=detail,
               inputRefs=sorted(set(refs)),collectionRefs=[],
               coverage=dict(expected=expected,checked=checked,failed=(int(status=='fail') if failed is None else failed),unjudged=expected-checked),
               evidence=evidence,advice='补齐当前输入和证据后重新运行体检' if status=='unjudged' else '修复实测不合格对象后重新体检' if status=='fail' else '')
    if reason: out['reason']=reason
    return out


def structure(ref, expected, actual):
    return dict(kind='structure',resourceRef=ref,locator={'scope':'file'},expected=expected,actual=actual)


def all_included(inputs, spec):
    """No invented flag column: require an explicit, evidenced selection rule."""
    rule = spec.get('analysis_selection', {})
    if rule.get('kind') != 'all' or not str(rule.get('reason', '')).strip():
        return False
    evidence = rule.get('evidence')
    return isinstance(evidence,list) and bool(evidence) and all(
        isinstance(rel,str) and inputs.file(rel).is_file() and inputs.file(rel).stat().st_size > 0
        for rel in evidence)


def dataset(inputs, policy):
    from analysis_utils import read_csv_auto, apply_filter
    registry = inputs.file('research_registry.json')
    paths = ['output/dataset/analysis.csv']
    entries = []
    if registry.is_file():
        data = read_json(registry)
        entries = data.get('datasets', [])
        if isinstance(entries, dict): entries=list(entries.values())
        paths=[e.get('path') or e.get('csv') or e.get('data') for e in entries]
        if not paths or not all(isinstance(x,str) and x for x in paths):
            return verdict('dataset-in-analysis','unjudged','数据集注册表没有可解析的数据路径',['research_registry.json'],[structure('research_registry.json','dataset path','missing')],'ambiguous')
    cfg_path=inputs.file('chart_config.json')
    cfg=read_json(cfg_path) if cfg_path.is_file() else {}
    refs=['research_registry.json','chart_config.json']
    statuses=[]; evidence=[]
    for rel in sorted(set(paths)):
        p=inputs.file(rel);refs.append(rel)
        if not p.is_file():
            statuses.append('unjudged');evidence.append(structure(rel,'readable dataset','missing'));continue
        spec=next((e for e in entries if (e.get('path') or e.get('csv') or e.get('data'))==rel),{})
        if 'encoding' in spec or 'delimiter' in spec:
            import pandas as pd
            df=pd.read_csv(p,encoding=spec.get('encoding','utf-8-sig'),sep=spec.get('delimiter',','))
        else:df=read_csv_auto(str(p))
        if 'in_analysis' not in df.columns and all_included(inputs,spec) and not cfg.get('filter_query') and not cfg.get('keep_out_of_scope'):
            # Local sentinel is used only to validate identity membership; no file is modified.
            df['in_analysis']=1
        if 'in_analysis' not in df.columns or not len(df):
            statuses.append('unjudged');evidence.append(structure(rel,'nonempty in_analysis column',list(df.columns)));continue
        flags=df['in_analysis'].astype(str).str.strip()
        if not flags.isin(['0','1']).all() or cfg.get('keep_out_of_scope'):
            statuses.append('unjudged');evidence.append(structure(rel,'0/1 flags and enforced selection','invalid flags or keep_out_of_scope'));continue
        if not flags.eq('1').any():
            statuses.append('fail');evidence.append(structure(rel,'at least one included observation',0));continue
        # Use production filter on identity strings; never infer filtering from text.
        selected,_=apply_filter(df.copy(),cfg)
        selected_flags=selected['in_analysis'].astype(str).str.strip()
        ok=len(selected)>0 and selected_flags.eq('1').all()
        meta_path=inputs.file('output/models/model_meta.json')
        refs.append('output/models/model_meta.json')
        if meta_path.is_file():
            from pathlib import Path
            from gate_contract import digest
            meta=read_json(meta_path)
            model_data=Path(meta.get('data',''))
            model_data=model_data if model_data.is_absolute() else inputs.root/model_data
            if model_data.resolve()==p.resolve():
                bindings=meta.get('input_bindings',{})
                receipts=meta.get('sample_receipts')
                if not bindings or not receipts or set(r['model'] for r in receipts)!=set(meta.get('models',[])):
                    statuses.append('unjudged');evidence.append(structure('output/models/model_meta.json','bound actual sample receipts','missing'));continue
                for file,sha in bindings.items():
                    bound=Path(file).resolve()
                    relative=bound.relative_to(inputs.root).as_posix()
                    refs.append(relative)
                    if digest(inputs.file(relative))!=sha:
                        raise ValueError('model inputs changed')
                for receipt in receipts:
                    used=receipt.get('used_rows')
                    if not isinstance(used,list):
                        statuses.append('unjudged');evidence.append(structure(rel,'actual row identities',receipt.get('model')));continue
                    if (not used or len(set(used))!=len(used) or receipt['n']!=len(used)
                            or any(type(i) is not int or i<1 or i>len(df) or flags.iloc[i-1]!='1' for i in used)):
                        ok=False
        inputs.collection('output/v2')
        if (inputs.root/'output/v2').is_dir():
            import contract_v2 as C
            import execution
            project=C.Project(inputs.root,create=False)
            for kind in ['model_spec','model_result']:
                inputs.file(f'output/v2/{kind}.jsonl');refs.append(f'output/v2/{kind}.jsonl')
            from gate_facts import latest
            specs=latest(project.read('model_spec'))
            results=latest(project.read('model_result'))
            for result in results.values():
                mid=result['data'].get('model_id') or result['data'].get('model')
                if mid not in specs:continue
                spec=specs[mid]['data']
                fit_inputs=[item for item in spec['inputs'] if item['role'] in ('fit','train')
                            and (inputs.root/item['dataset']).resolve()==p.resolve()]
                if not fit_inputs:continue
                computation=result['data'].get('computation',{})
                for mapping in ('inputs','code'):
                    for file in computation.get(mapping,{}):
                        inputs.file(file);refs.append(file)
                if not execution.current(project,spec,computation):
                    statuses.append('unjudged');evidence.append(structure(rel,'current execution binding',mid));break
                sample=result['data'].get('sample_scope',{})
                if sample.get('kind')=='none':continue
                used=sample.get('used_keys');keys=fit_inputs[0].get('keys')
                if not used or not keys or len(fit_inputs)!=1:
                    statuses.append('unjudged');evidence.append(structure(rel,'role-specific used keys',mid));break
                from gate_facts import Facts
                raw=Facts(inputs,policy).csv(rel)
                declared_all=all_included(inputs,spec=next((e for e in entries if e.get('path')==rel),{}))
                included={tuple(row[key] for key in keys) for row in raw if row.get('in_analysis','1' if declared_all else '').strip()=='1'}
                selected_keys=[tuple(str(v) for v in key) for key in used]
                if len(set(selected_keys))!=len(selected_keys) or not set(selected_keys)<=included or sample.get('n')!=len(selected_keys):
                    ok=False
            else:
                statuses.append('pass' if ok else 'fail')
                evidence.append(structure(rel,'only included rows',{'inputRows':len(df),'selectedRows':len(selected),'excludedSelected':int(selected_flags.ne('1').sum())}))
                continue
            # An execution with insufficient role bindings is unknown, even if
            # the configured pre-filter would have selected the right rows.
            continue
        statuses.append('pass' if ok else 'fail')
        evidence.append(structure(rel,'only included rows',{'inputRows':len(df),'selectedRows':len(selected),'excludedSelected':int(selected_flags.ne('1').sum())}))
    status='fail' if 'fail' in statuses else 'unjudged' if 'unjudged' in statuses else 'pass'
    result=verdict('dataset-in-analysis',status,'逐数据集实际调用生产筛选规则',sorted(set(refs)|set(inputs.resources)),evidence,
                   'missing-column' if status=='unjudged' else None,expected=len(statuses),checked=sum(x!='unjudged' for x in statuses),failed=statuses.count('fail'))
    result['collectionRefs']=sorted(inputs.collections)
    return result


def numbers(inputs, policy):
    refs=['output/verify/run.json','output/verify/number_issues.csv','output/verify/number_trace.csv']
    files=[inputs.file(r) for r in refs]
    if not all(p.is_file() for p in files):
        return verdict('qa-numbers','unjudged','缺数字检查运行回执或完整输出',refs,[structure(r,'current verification output','missing' if not p.is_file() else 'present') for r,p in zip(refs,files)],'missing-input')
    # A legacy receipt does not bind current inputs. It cannot attest freshness.
    receipt=read_json(files[0])
    receipt=receipt.get('producers',{}).get('verify_numbers.py',receipt)
    bindings=receipt.get('bindings')
    if receipt.get('check')!='all':
        return verdict('qa-numbers','unjudged','当前回执未覆盖完整数字检查',refs,[structure(refs[0],'check=all',receipt.get('check'))],'partial-coverage')
    if not bindings or not isinstance(bindings,dict):
        return verdict('qa-numbers','unjudged','旧数字回执没有输入绑定，不能证明当前数字已检查',refs,[structure(refs[0],'current input bindings','missing')],'binding-mismatch')
    for relative,members in receipt.get('collections',{}).items():
        if inputs.collection(relative)!=members:
            return verdict('qa-numbers','unjudged','数字检查输入集合改变',refs,[structure(refs[0],'unchanged input collection',relative)],'binding-mismatch')
    from gate_contract import digest
    for file,relative in zip(files[1:],refs[1:3]):
        expected=receipt.get('output_sha256',{}).get(file.name)
        if expected!=digest(file):
            return verdict('qa-numbers','unjudged','数字检查输出与原运行回执不一致',refs,[structure(relative,expected,'changed or unbound')],'binding-mismatch')
    for rel,expected in sorted(bindings.items()):
        p=inputs.file(rel);refs.append(rel)
        from gate_contract import digest
        if not p.is_file() or digest(p)!=expected:
            return verdict('qa-numbers','unjudged','数字检查输入已改变',refs,[structure(rel,expected,'changed')],'binding-mismatch')
    from gate_facts import Facts
    rows=Facts(inputs,policy).csv(refs[1],('severity',),allow_empty=True)
    if any(r['severity'] not in ('error','warning','info') for r in rows):
        return verdict('qa-numbers','unjudged','数字问题表包含无法识别的级别',refs,[structure(refs[1],'known issue severities','invalid')],'unreadable')
    errors=[{'row':i+2,**r} for i,r in enumerate(rows) if r.get('severity')=='error']
    out=verdict('qa-numbers','fail' if errors else 'pass','数字检查存在错误' if errors else '当前数字检查无 error',refs,[structure(refs[1],'zero errors',errors)])
    out['collectionRefs']=sorted(receipt.get('collections',{}))
    return out


def layout(inputs, policy):
    from layout_check import check_placement
    refs=['output/manuscript.docx','output/manuscript.pdf','output/figure_map.json']
    files=[inputs.file(r) for r in refs]
    if not all(p.is_file() for p in files):
        return [verdict(i,'unjudged','缺成稿或图像位置映射，无法测量最终安置',refs,[structure(r,'final artifact','missing' if not p.is_file() else 'present') for r,p in zip(refs,files)],'missing-input') for i in ['fig-dpi','fig-font']]
    mapping=read_json(files[2]);figures=mapping.get('figures',[]) if isinstance(mapping,dict) else mapping
    if not isinstance(figures,list) or not figures:
        return [verdict(i,'unjudged','没有登记待测图表',refs,[structure(refs[2],'nonempty figure list','empty')],'empty-scope') for i in ['fig-dpi','fig-font']]
    resolved=[]
    for i,item in enumerate(figures):
        entry=dict(item)
        if 'image' in entry and 'png' not in entry:
            from pathlib import Path
            image=Path(entry['image'])
            entry['png']=image.resolve().relative_to(inputs.root).as_posix() if image.is_absolute() else entry['image']
        entry.setdefault('caption',entry.get('tag','')+' '+entry.get('title',''))
        entry.setdefault('figure_id',entry.get('id',str(i+1)))
        for key in ['png','pdf']:
            if entry.get(key):
                rel=entry[key];entry[key]=str(inputs.file(rel));refs.append(rel)
        resolved.append(entry)
    result=check_placement(files[0],files[1],figures=resolved,min_dpi=policy['thresholds']['minEffectiveDpi']/0.995,min_fontsize=policy['thresholds']['minFontPt'])
    out=[]
    for ident,key in [('fig-dpi','placed_dpi'),('fig-font','min_fontsize')]:
        checks=[c for c in result['checks'] if c.get('check')==key]
        if any(c.get('check') in ['docx_file','pdf_file','figure_source'] and c.get('status')!='passed' for c in result['checks']):
            checks=[]
        # Names are structured check ids in layout_check; unknown shape fails closed.
        if not checks:
            out.append(verdict(ident,'unjudged','未得到完整安置测量',refs,[structure(refs[2],key,'no measurement')],'partial-coverage'));continue
        fail=[c for c in checks if c.get('status')=='failed']
        known=[c for c in checks if c.get('status') in ['passed','failed']]
        n=len(figures)
        status='fail' if fail else 'pass' if len(known)==n else 'unjudged'
        # Evidence excludes raw absolute paths returned by underlying layout inspection.
        ev=[structure(refs[2],key,{k:v for k,v in c.items() if k in ['figure_id','status','observed','effective_dpi','min_fontsize','page']}) for c in checks]
        out.append(verdict(ident,status,'最终安置实测结果',refs,ev,'partial-coverage' if status=='unjudged' else None,expected=max(n,len(known)),checked=len(known),failed=len(fail)))
    return out


def evaluate(inputs,policy,stage):
    if stage=='dataset':return [dataset(inputs,policy)]
    if stage=='qa':return [*layout(inputs,policy),numbers(inputs,policy)]
    return []
