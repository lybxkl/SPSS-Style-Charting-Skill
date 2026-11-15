"""Stage quality checks over actual artifacts and the existing research engines.

Missing evidence is not an empty list of violations. Each check either reads its
entire required scope, identifies a concrete violation, or explains the gap.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re

from gate_contract import digest, read_json, resolve
from gate_checks import structure, verdict


class MissingEvidence(ValueError):
    pass


class Facts:
    def __init__(self, inputs, policy):
        self.inputs = inputs
        self.policy = policy
        self.cache = {}

    def file(self, rel):
        path = self.inputs.file(rel)
        if not path.is_file():
            raise MissingEvidence(rel)
        return path

    def json(self, rel):
        return read_json(self.file(rel))

    def csv(self, rel, required=(), allow_empty=False):
        path=self.file(rel)
        dialect={}
        registry=self.inputs.file('research_registry.json')
        if registry.is_file():
            matches=[spec for spec in read_json(registry).get('datasets',[]) if self.inputs.file(spec['path'])==path]
            if matches:
                dialects={(s.get('encoding','utf-8-sig'),s.get('delimiter',',')) for s in matches}
                if len(dialects)!=1:raise MissingEvidence('unambiguous registered CSV dialect')
                encoding,delimiter=dialects.pop();dialect={'encoding':encoding,'delimiter':delimiter}
        with path.open(encoding=dialect.get('encoding','utf-8-sig'), newline='') as stream:
            reader = csv.DictReader(stream,delimiter=dialect.get('delimiter',','))
            header = reader.fieldnames or []
            if not set(required) <= set(header):
                raise MissingEvidence(f'{rel}: missing columns {sorted(set(required)-set(header))}')
            if not header or any(not h.strip() for h in header) or len(header) != len(set(header)):
                raise ValueError('duplicate CSV columns')
            rows = []
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError('CSV row width differs from its header')
                rows.append(row)
                if len(rows)>1000000:
                    raise MissingEvidence('CSV exceeds row verification budget')
        if not rows and not allow_empty:
            raise MissingEvidence(f'{rel}: no data rows')
        return rows

    def jsonl(self, rel, *, exact_numbers=False):
        from gate_contract import _pairs,finite_float
        from decimal import Decimal

        rows = []
        for line in self.file(rel).read_text(encoding='utf-8-sig').splitlines():
            if line.strip():
                rows.append(json.loads(line, object_pairs_hook=_pairs,parse_float=Decimal if exact_numbers else finite_float,
                                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite'))))
        if not rows:
            raise MissingEvidence(f'{rel}: no records')
        return rows

    def artifact(self, *candidates):
        for relative in candidates:
            if self.inputs.file(relative).is_file():
                return relative
        raise MissingEvidence(' or '.join(candidates))

    def datasets(self):
        registry = self.json('research_registry.json')
        rows = registry.get('datasets')
        if not isinstance(rows, list) or not rows:
            raise MissingEvidence('research_registry.json: nonempty datasets')
        if len({r['id'] for r in rows}) != len(rows):
            raise ValueError('duplicate dataset identities')
        return rows

    def optional_index(self,relative,key):
        if not self.inputs.file(relative).is_file():return None
        rows=self.json(relative).get(key)
        if not isinstance(rows,list) or not rows or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) or not r['id'].strip() for r in rows):
            raise MissingEvidence('nonempty indexed identities in '+relative)
        if len({r['id'] for r in rows})!=len(rows):raise MissingEvidence('unique identities in '+relative)
        return rows

    def model_index(self,actual):
        rows=self.optional_index('output/models/index.json','models')
        if rows is None:return []
        bad=[]
        datasets={s['id']:s for s in self.datasets()}
        if set(r['id'] for r in rows)!=set(actual):bad.append('model-identities')
        for row in rows:
            expected=actual.get(row['id'])
            if expected is None:continue
            if row.get('n') is not None and (type(row['n']) is not int or row['n']!=expected['n']):bad.append(row['id']+':n')
            if row.get('dataset'):
                spec=datasets.get(row['dataset'])
                if spec is None or (expected.get('data') and self.file(spec['path'])!=self.file(expected['data'])):bad.append(row['id']+':dataset')
            for key in ('coef','fit'):
                if row.get(key):self.file(row[key])
        return bad

    def source_root(self):
        registry = self.inputs.file('research_registry.json')
        if registry.is_file():
            rel = read_json(registry).get('source_root')
            if rel:
                return rel
        summary = self.json('output/audit/corpus_summary.json')
        raw = Path(summary.get('root', 'data'))
        if raw.is_absolute():
            from gate_roots import absolute_reference
            absolute_reference(self.inputs.root,raw,self.inputs.material_roots)
            return str(raw.resolve())
        return raw.as_posix()

    def bind_external(self, path):
        # One tracker owns every observation, including repeated external reads.
        self.file(str(path))

    def final(self):
        if 'final' not in self.cache:
            from verify_dataset import validate_final_report

            rel = self.artifact('output/data_verification/dataset_verification.json',
                                'output/dataset/dataset_verification.json')
            verifier, report = validate_final_report(
                str(self.file('research_registry.json')), str(self.inputs.root),
                str(self.file(rel)))
            for path in verifier.bindings:
                self.bind_external(path)
            self.bind_external(report['snapshot_path'])
            for path in report['review_bindings']:
                self.bind_external(path)
            self.cache['final'] = (verifier, report)
        return self.cache['final']

    def research(self):
        if 'research' not in self.cache:
            from research_gate import ResearchGate

            gate = ResearchGate(str(self.file('research_registry.json')), str(self.inputs.root))
            self.inputs.collection(self.source_root())
            gate.source_coverage()
            gate.verifier, gate.verified = self.final()
            gate.verification_path = self.artifact('output/data_verification/dataset_verification.json',
                                                  'output/dataset/dataset_verification.json')
            gate.models()
            for path in gate.bindings:
                self.bind_external(path)
            self.cache['research'] = gate
        return self.cache['research']

    def coverage(self):
        """Source coverage is an atomic fact; it does not require fitted models."""
        from research_gate import ResearchGate
        gate = ResearchGate(str(self.file('research_registry.json')), str(self.inputs.root))
        self.inputs.collection(self.source_root())
        gate.source_coverage()
        for path in gate.bindings:
            self.bind_external(path)
        return gate

    def models(self):
        if not (self.inputs.root / 'output/v2').is_dir():
            raise MissingEvidence('version-bound model_spec and model_result records')
        import contract_v2 as C

        self.inputs.collection('output/v2')
        project = C.Project(self.inputs.root, create=False)
        specs = latest(project.read('model_spec'))
        results = latest(project.read('model_result'))
        if not specs:
            raise MissingEvidence('no registered model specifications')
        return specs, results

    def freshness(self, stage):
        """Compare current files with a production-time receipt, never timestamps."""
        receipt = self.json(f'output/gates/production/{stage}.json')
        if receipt.get('status') != 'completed' or not receipt.get('inputs') or not receipt.get('outputs') or not receipt.get('implementation'):
            raise MissingEvidence('completed production receipt with inputs and outputs')
        from gates import environment
        if not receipt.get('environment'):raise MissingEvidence('production-time Python and dependency versions')
        if receipt['environment']!=environment():return False,{'reason':'production-environment-changed','runId':receipt['runId']}
        failures = []
        for entry in receipt['implementation']:
            self.bind_external(entry['path'])
            if digest(entry['path'])!=entry['sha256']:failures.append(entry['path'])
        for entry in receipt['inputs'] + receipt['outputs']:
            path = self.inputs.file(entry['path'])
            if not path.is_file() or digest(path) != entry['sha256']:
                failures.append(entry['path'])
        for collection in receipt.get('collections', []):
            if self.inputs.collection(collection['basePath']) != collection['members']:
                failures.append(collection['basePath'])
        return not failures, {'changed': failures, 'runId': receipt['runId']}

    def figures(self):
        candidates = ['output/chart_pack/chart_manifest.csv', 'output/figures/paper_figures_manifest.csv']
        rows = []
        for rel in candidates:
            if self.inputs.file(rel).is_file():
                for row in self.csv(rel, ('id',), allow_empty=True):
                    rows.append({**row, '_manifest': rel})
        if not rows:
            raise MissingEvidence('nonempty chart manifest')
        return rows

    def figure_path(self, row, key):
        raw = row.get(key)
        if not raw:
            raise MissingEvidence(f"{row['id']}: {key}")
        path = Path(raw)
        if path.is_absolute():
            relative = path.resolve().relative_to(self.inputs.root).as_posix()
        else:
            direct = self.inputs.file(path.as_posix())
            relative = path.as_posix() if direct.is_file() else (Path(row['_manifest']).parent / path).as_posix()
        return self.file(relative)

    def manifest_figure(self, image):
        target=self.file(image)
        matches=[row for row in self.figures() if row.get('png') and row.get('status','ok')=='ok'
                 and self.figure_path(row,'png')==target]
        if len(matches)!=1:raise MissingEvidence('unique manifest identity for the actual figure source')
        return matches[0]


def figure_tag_pattern(tag):
    parts=[re.escape(p.strip()) for p in re.split(r'(\d+)',tag) if p.strip()]
    return r'\s*'.join(parts)+r'(?!\d)'


def caption_index(paragraphs,figure,row=None):
    """Locate the printed caption, accepting the producer's '图 1' spacing."""
    pattern=r'^\s*'+figure_tag_pattern(figure['tag'])
    candidates=[i for i,p in enumerate(paragraphs) if re.match(pattern,p.text)]
    normalize=lambda text:re.sub(r'\s+','',text)
    title=figure.get('title') or figure.get('caption') or (row or {}).get('title') or (row or {}).get('caption')
    if title:
        title=re.sub(pattern,'',title)
        matching=[i for i in candidates if normalize(re.sub(pattern,'',paragraphs[i].text)).startswith(normalize(title))]
        if matching:candidates=matching
    styled=[i for i in candidates if paragraphs[i].alignment==1 or 'caption' in paragraphs[i].style.name.lower()]
    if styled:candidates=styled
    numbered=[i for i in candidates if re.search(r'(?i)N\s*[=＝]\s*\d',paragraphs[i].text)]
    if len(candidates)>1 and numbered:candidates=numbered
    if len(candidates)!=1:raise MissingEvidence('unique printed caption for '+figure['tag'])
    return candidates[0]


def latest(records):
    result = {}
    for record in records:
        old = result.get(record['id'])
        if old is None or record['revision'] > old['revision']:
            result[record['id']] = record
    return result


def flow(facts, rel):
    rows = facts.csv(rel, ('stage', 'n'))
    stages = {}
    previous = None
    failures = []
    for index, row in enumerate(rows, 2):
        kind = row.get('kind') or 'stage'
        try:
            n = int(row['n'])
            if n < 0 or str(n) != row['n'].strip():
                raise ValueError('N must be a nonnegative integer')
            if kind == 'stage':
                if row['stage'] in stages or (previous is not None and n > previous):
                    failures.append(index)
                stages[row['stage']] = n
                previous = n
            elif kind == 'excluded':
                if previous is None or n > previous:
                    failures.append(index)
            elif kind == 'model':
                match = re.search(r'(?:^|\s)stage=(.+)', row.get('note', ''))
                if not match or match[1].strip() not in stages or n > stages[match[1].strip()]:
                    failures.append(index)
            else:
                failures.append(index)
        except (TypeError, ValueError):
            failures.append(index)
    return not failures, {'rows': len(rows), 'invalidRows': failures}


def audit(facts, ident):
    if ident == 'audit-monotonic':
        return flow(facts, 'output/audit/sample_flow.csv')
    summary = facts.json('output/audit/corpus_summary.json')
    if ident == 'audit-summary':
        rows = facts.csv('output/audit/corpus_files.csv', ('status',))
        expected = summary.get('total_files', summary.get('files_total'))
        if expected is None:
            # Historical summaries use total_files_scanned.
            expected = summary.get('total_files_scanned')
        if expected is None:
            raise MissingEvidence('audited file count in corpus_summary')
        return expected == len(rows), {'declared': expected, 'actual': len(rows)}
    if ident == 'audit-truncated':
        if 'truncated' not in summary:
            raise MissingEvidence('explicit audit truncation state')
        return not summary['truncated'], {'truncated': summary['truncated']}
    if ident == 'audit-dedupe':
        rows = facts.csv('output/audit/dedupe_plan.csv', ('role',), allow_empty=True)
        inventory=facts.csv('output/audit/corpus_files.csv',('status',))
        expected={(r.get('dup_group'),r.get('rel_path') or r.get('relpath'),r.get('dup_role')) for r in inventory if r.get('dup_group')}
        actual=[(r.get('group'),r.get('rel_path') or r.get('relpath'),r['role']) for r in rows]
        bad = [i for i, row in enumerate(rows, 2) if row['role'] not in ('keeper', 'duplicate') or not row.get('reason','').strip()]
        groups={r[0] for r in expected}
        invalid_groups=[g for g in groups if sum(item[0]==g and item[2]=='keeper' for item in expected)!=1 or not any(item[0]==g and item[2]=='duplicate' for item in expected)]
        return not bad and not invalid_groups and len(actual)==len(set(actual)) and set(actual)==expected, {'invalidRows': bad,'invalidGroups':invalid_groups,'entries':len(rows),'expected':len(expected)}
    rows = facts.csv('output/audit/corpus_files.csv', ('md5',))
    excluded={'metadata','hidden','quarantined','zero_byte','unreadable','unsupported'}
    bad = [i for i, row in enumerate(rows, 2) if row.get('status') not in excluded and not re.fullmatch(r'[a-fA-F0-9]{32}', row.get('md5', ''))]
    if ident == 'audit-hash':
        return not bad and not summary.get('hash_disabled', False), {'unhashedRows': bad}
    if bad:
        raise MissingEvidence('complete per-file content hashes')
    root = facts.source_root()
    members = facts.inputs.collection(root)
    collection=facts.inputs.collections[facts.inputs.collection_aliases[root]]
    expected = set()
    changed = []
    for row in rows:
        relative = row.get('rel_path') or row.get('relpath')
        if not relative:
            raise MissingEvidence('audited relative path')
        rel = (Path(root) / relative).as_posix()
        expected.add((Path(collection['basePath'])/relative).as_posix())
        path = facts.inputs.file(rel)
        if not path.is_file():
            changed.append(rel)
            continue
        md5 = hashlib.md5()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                md5.update(chunk)
        if row.get('status') not in excluded and md5.hexdigest() != row['md5'].lower():
            changed.append(rel)
    return not changed and len(expected)==len(rows) and expected == set(members), {
        'changed': changed, 'new': sorted(set(members)-expected), 'missing': sorted(expected-set(members))}


def coding(facts, ident):
    inventory = facts.csv('output/audit/corpus_files.csv', ('status',))
    valid = [r for r in inventory if r['status'] == 'valid']
    if not valid:
        raise MissingEvidence('nonempty valid material scope')
    paths = {r.get('rel_path') or r.get('relpath') for r in valid}
    if None in paths:
        raise MissingEvidence('source identities')
    tabular = all(Path(p).suffix.lower() in ('.csv', '.tsv', '.xlsx', '.xls') for p in paths)
    project_file=facts.inputs.file('project.json')
    declaration=read_json(project_file).get('stages',{}).get('coding',{}).get('applicability','auto') if project_file.is_file() else 'auto'
    if declaration=='required':tabular=False
    if declaration in ('not_applicable','na') and not tabular:
        raise MissingEvidence('coding applicability conflicts with the actual material scope')
    if tabular:
        return 'na', {'rule': 'all-valid-materials-tabular', 'sources': sorted(paths)}
    if ident == 'coding-applicable':
        return True, {'rule': 'non-tabular-materials-present', 'sources': sorted(paths)}
    if ident == 'coding-flow':
        return flow(facts, 'output/coding/sample_flow.csv')
    skipped_rel = 'output/coding/skipped_documents.csv'
    skipped = facts.csv(skipped_rel, allow_empty=True)
    missing_reasons = [i for i, r in enumerate(skipped, 2) if not r.get('reason','').strip() or not (r.get('rel_path') or r.get('relpath'))]
    if ident == 'coding-skipped':
        return not missing_reasons, {'invalidRows': missing_reasons, 'skipped': len(skipped)}
    sheet = facts.csv('output/coding/coding_sheet.csv')
    coded = {r.get('rel_path') or r.get('relpath') for r in sheet}
    excluded = {r.get('rel_path') or r.get('relpath') for r in skipped}
    return not missing_reasons and None not in coded and coded <= paths and not coded & excluded and len(excluded)==len(skipped) and paths == coded | excluded, {
        'extra': sorted(str(p) for p in (coded|excluded)-paths), 'overlap':sorted(str(p) for p in coded&excluded),'missing': sorted(str(p) for p in paths-coded-excluded)}


def data(facts, ident):
    specs = facts.datasets()
    if ident in ('registry-present', 'datasets-index'):
        for spec in specs:
            facts.file(spec['path'])
        rows=facts.optional_index('output/datasets/index.json','datasets')
        bad=[]
        if rows is not None:
            registered={s['id']:s for s in specs}
            if set(r['id'] for r in rows)!=set(registered):bad.append('dataset-identities')
            for row in rows:
                spec=registered.get(row['id'])
                if spec is None:continue
                if not row.get('file') or facts.file(row['file'])!=facts.file(spec['path']):bad.append(row['id']+':path');continue
                actual=facts.csv(spec['path'])
                if row.get('rows') is not None and (type(row['rows']) is not int or row['rows']!=len(actual)):bad.append(row['id']+':rows')
                if row.get('columns') and [c['name'] for c in row['columns']]!=list(actual[0]):bad.append(row['id']+':columns')
                selection=row.get('inAnalysis') or row.get('in_analysis') or {}
                if selection.get('column') and selection['column'] not in actual[0]:bad.append(row['id']+':selection-column')
                if selection.get('n') is not None:
                    column=selection.get('column')
                    if column!='in_analysis' or type(selection['n']) is not int or selection['n']!=sum(r[column].strip()=='1' for r in actual):bad.append(row['id']+':selection-n')
        return not bad, {'datasets': [s['id'] for s in specs],'indexPresent':rows is not None,'conflicts':bad}
    bad = []
    details = []
    source_root = None
    if ident == 'dataset-path':
        from gate_roots import reference, absolute_reference
        raw=facts.source_root()
        source_root = (absolute_reference(facts.inputs.root,raw,facts.inputs.material_roots)
                       if Path(raw).is_absolute() else reference(facts.inputs.root,raw,facts.inputs.material_roots))[2]
    for spec in specs:
        path = facts.file(spec['path'])
        if ident == 'dataset-path':
            if path == source_root or source_root in path.parents:
                bad.append(spec['id'])
            continue
        rows = facts.csv(spec['path'])
        if ident == 'dataset-csv':
            details.append({'dataset': spec['id'], 'rows': len(rows), 'columns': list(rows[0])})
        elif ident == 'dataset-flag':
            if 'in_analysis' not in rows[0]:
                from gate_checks import all_included
                if all_included(facts.inputs,spec):
                    continue
                raise MissingEvidence(f"{spec['id']}: in_analysis column or evidenced all-included selection rule")
            if any(r['in_analysis'].strip() not in ('0', '1') for r in rows):
                bad.append(spec['id'])
        elif ident == 'dataset-key':
            keys = spec.get('key')
            keys = [keys] if isinstance(keys, str) else keys
            if not keys or not set(keys) <= rows[0].keys():
                raise MissingEvidence(f"{spec['id']}: declared key columns")
            values = [tuple(r[k] for k in keys) for r in rows]
            if any(any(not v.strip() for v in key) for key in values) or len(set(values)) != len(values):
                bad.append(spec['id'])
    return not bad, {'invalidDatasets': bad, 'datasets': details or [s['id'] for s in specs]}


def verification(facts, ident):
    if ident == 'source-coverage':
        gate = facts.coverage()
        errors = gate.issues
        return not errors, {'errors': errors, 'sources': len(gate.sources)}
    verifier, report = facts.final()
    count = len(verifier.cells)
    if not count:
        raise MissingEvidence('nonempty verified cell scope')
    return True, {'stage': report['stage'], 'status': report['status'], 'cells': count,
                  'fingerprint': report['fingerprint']}


def figures(facts, ident):
    if ident == 'fig-fresh':
        return facts.freshness('figures')
    rows = facts.figures()
    delivered = [r for r in rows if r.get('status', 'ok') == 'ok']
    errors = [r['id'] for r in rows if r.get('status') == 'error']
    unknown = [r['id'] for r in rows if r.get('status', 'ok') not in ('ok', 'error', 'skipped')]
    if unknown:
        raise MissingEvidence('known manifest statuses')
    if ident == 'fig-status':
        return not errors, {'errors': errors, 'skipped': [r['id'] for r in rows if r.get('status') == 'skipped']}
    if not delivered:
        raise MissingEvidence('at least one delivered chart')
    if ident == 'fig-manifest':
        identities = [(r['_manifest'], r['id']) for r in rows]
        return len(set(identities)) == len(identities), {'delivered': len(delivered), 'entries': len(rows)}
    if ident == 'fig-paper':
        if not facts.inputs.file('paper.json').is_file():
            return 'na', {'rule': 'no-paper-figure-configuration', 'configuration': 'paper.json'}
        paper = facts.json('paper.json')
        actual = facts.csv('output/figures/paper_figures_manifest.csv', ('id',))
        configured=paper.get('figures') if isinstance(paper,dict) else None
        if not isinstance(configured,list) or not configured:raise MissingEvidence('nonempty paper figure configuration')
        expected=[r['id'] for r in configured];produced=[r['id'] for r in actual]
        return len(expected)==len(set(expected)) and len(produced)==len(set(produced)) and set(expected)==set(produced) and all(r.get('status')=='ok' for r in actual), {'entries':len(actual),'missing':sorted(set(expected)-set(produced)),'unexpected':sorted(set(produced)-set(expected))}
    if ident == 'fig-files':
        from PIL import Image
        failures = []
        for row in delivered:
            path = facts.figure_path(row, 'png')
            try:
                with Image.open(path) as image:
                    image.verify()
            except (OSError, ValueError):
                failures.append(row['id'])
        return not failures, {'unreadableImages': failures, 'checked': len(delivered)}
    if ident == 'fig-palette':
        from qa_outputs import check_palette
        observed = []
        for row in delivered:
            raw = row.get('palette')
            if not raw:
                raise MissingEvidence(f"{row['id']}: declared palette")
            colors = re.findall(r'#[a-fA-F0-9]{6}', raw)
            if not colors:
                raise MissingEvidence('machine-readable palette colors')
            result = check_palette(colors)
            observed.append({'id': row['id'], 'errors': result.get('errors', [])})
        return not any(r['errors'] for r in observed), {'palettes': observed}
    if ident == 'fig-title':
        bad = [r['id'] for r in delivered if not (r.get('caption') or r.get('title') or '').strip()]
        return not bad, {'missingTitles': bad}
    # This is a real manuscript check, even though the UI groups it with figures.
    return manuscript(facts, 'fig-cited')


def manuscript(facts, ident):
    if ident == 'manuscript-fresh':
        return facts.freshness('manuscript')
    from docx import Document

    doc = Document(facts.file('output/manuscript.docx'))
    paragraphs = [p.text for p in doc.paragraphs]
    if ident == 'manuscript-body':
        substantive = [p.text for p in doc.paragraphs if p.text.strip() and 'caption' not in p.style.name.lower() and not (p.alignment==1 and re.match(r'^\s*[图表]\s*\d+',p.text))]
        spec=facts.json('manuscript.json')
        declared=[b['text'] for b in spec.get('blocks',[]) if b.get('type') in ('para','heading') and b.get('text')]
        numbers={}
        if any(re.search(r'\{[^{}]+\}',text) for text in declared):
            numbers={r['key']:r['value'] for r in facts.csv('output/manuscript_numbers.csv',('key','value'))}
        from assemble_manuscript import resolve_text
        from collections import Counter
        normalize=lambda text:re.sub(r'\s+','',text)
        required=Counter(normalize(resolve_text(text,numbers,'declared body')) for text in declared)
        actual=Counter(normalize(text) for text in paragraphs if text.strip())
        missing=list((required-actual).elements())
        return bool(substantive) and not missing, {'paragraphs':len(substantive),'characters':sum(map(len,substantive)),'declaredBlocks':len(declared),'missingBlocks':len(missing)}
    if ident == 'tbl-present':
        spec = facts.json('manuscript.json')
        tables = [b for b in spec.get('blocks', []) if b.get('type') == 'table']
        if not tables:
            raise MissingEvidence('declared table scope or explicit table-free applicability')
        from assemble_manuscript import read_table,format_cell
        conflicts=[]
        for index,(block,table) in enumerate(zip(tables,doc.tables),1):
            if not block.get('csv'):raise MissingEvidence('declared source CSV for table '+str(index))
            source=facts.file(block['csv'])
            rows,columns,_=read_table({**block,'csv':str(source)},str(facts.inputs.root))
            expected=[[c.get('label') or c['col'] for c in columns]]+[[format_cell(r.get(c['col']),c) for c in columns] for r in rows]
            normalize=lambda text:re.sub(r'\s+','',text)
            actual=[[cell.text for cell in row.cells] for row in table.rows]
            if [[normalize(v) for v in row] for row in actual]!=[[normalize(v) for v in row] for row in expected]:conflicts.append(index)
        return len(doc.tables)==len(tables) and not conflicts, {'declared':len(tables),'actual':len(doc.tables),'contentOrStructureConflicts':conflicts}
    mapping = facts.json('output/figure_map.json')
    rows = mapping.get('figures', []) if isinstance(mapping, dict) else mapping
    if not rows:
        raise MissingEvidence('nonempty figure map or explicit figure-free applicability')
    if ident == 'manuscript-figures':
        from qa_outputs import check_docx
        from collections import Counter
        info = check_docx(str(facts.file('output/manuscript.docx')))
        expected=Counter()
        for row in rows:
            raw = row.get('image') or row.get('png')
            if not raw:
                raise MissingEvidence('figure map source image')
            path = Path(raw)
            relative = path.resolve().relative_to(facts.inputs.root).as_posix() if path.is_absolute() else path.as_posix()
            sha = digest(facts.file(relative))
            expected[sha]+=1
        actual=Counter(p['sha256'] for p in info['placements'])
        return expected==actual, {'boundFigures':len(rows),'actualPlacements':sum(actual.values()),
                                  'missingPlacements':sum((expected-actual).values()),'undeclaredPlacements':sum((actual-expected).values())}
    captions={caption_index(doc.paragraphs,{**row,'tag':row.get('tag') or f'图{i}'},facts.manifest_figure(row.get('image') or row.get('png')))
              for i,row in enumerate(rows,1)}
    body = '\n'.join(p for i,p in enumerate(paragraphs) if i not in captions)
    missing = []
    for i, row in enumerate(rows, 1):
        tag = row.get('tag') or f'图{i}'
        if not re.search(figure_tag_pattern(tag),body):
            missing.append(tag)
    return not missing, {'uncited': missing, 'figures': len(rows)}


def legacy_models(facts, ident):
    """Use arbitrary-engine receipts; no dependency on auto_stats file names."""
    gate = facts.research()
    failures = [i for i in gate.issues if i['where'].startswith(('model', 'dataset'))]
    registry = facts.json('research_registry.json')
    models = facts.jsonl(registry['model_plan'])
    completed = [m for m in models if m.get('status') == 'completed']
    if failures:
        return False, {'errors': failures, 'models': gate.model_count}
    if ident=='models-index':
        conflicts=facts.model_index({m['id']:{'n':len(facts.csv(m['sample'])),'data':next(d['path'] for d in facts.datasets() if d['id']==m['dataset'])} for m in completed})
        return not conflicts,{'models':gate.model_count,'indexConflicts':conflicts}
    if ident == 'stats-flow':
        findings = []
        for model in completed:
            spec = next(d for d in facts.datasets() if d['id'] == model['dataset'])
            sample = facts.csv(model['sample'])
            rows = facts.csv(spec['path'])
            keys = spec['key'] if isinstance(spec['key'], list) else [spec['key']]
            selected = {tuple(r[k] for k in keys) for r in sample}
            included = {tuple(r[k] for k in keys) for r in rows
                        if r.get('in_analysis', '1').strip() == '1'}
            findings.append({'model': model['id'], 'n': len(selected),
                             'available': len(included), 'outside': len(selected-included)})
        if not findings:
            return 'na', {'rule': 'all-planned-models-have-terminal-non-execution-assessments',
                          'models': [m['id'] for m in models]}
        return not any(r['outside'] for r in findings), {'samples': findings}
    return True, {'models': gate.model_count, 'completed': [m['id'] for m in completed],
                  'engine': 'registered-production-receipts'}


def stats(facts, ident):
    if ident == 'stats-fresh':
        return facts.freshness('stats')
    if ident == 'methods-report':
        path = facts.file('output/methods/methods_report.md')
        rows = facts.csv('output/methods/methods_manifest.csv', ('status',))
        return bool(path.read_text(encoding='utf-8').strip()) and not any(r['status']=='error' for r in rows), {'methods': len(rows)}
    if ident == 'models-sweep':
        survey = facts.json('output/models/sweep.json')
        outcomes = survey.get('outcomes')
        if not outcomes:
            raise MissingEvidence('nonempty model-family survey')
        failures = []
        for outcome in outcomes:
            if not outcome.get('name') or not outcome.get('families'):
                failures.append(outcome.get('name'))
            for family in outcome.get('families',[]):
                status=family.get('status')
                if (not family.get('family') or status not in ('estimated','available','blocked','not_needed')
                    or status in ('blocked','not_needed') and not family.get('why')
                    or status == 'estimated' and not family.get('model')):
                    failures.append(outcome.get('name'))
        return not failures, {'outcomes':len(outcomes),'incomplete':failures}
    if ident == 'models-plan':
        gate = facts.research()
        failures = [i for i in gate.issues if i['where'].startswith(('model', 'dataset'))]
        return not failures, {'errors': failures, 'models': gate.model_count}
    if not (facts.inputs.root / 'output/v2').is_dir():
        if not facts.inputs.file('output/models/model_meta.json').is_file():
            return legacy_models(facts, ident)
        meta = facts.json('output/models/model_meta.json')
        rows = facts.csv('output/models/fit.csv', ('model','n'))
        bindings = meta.get('input_bindings')
        receipts = meta.get('sample_receipts')
        if not bindings or not receipts:
            raise MissingEvidence('production-time model inputs and actual sample identities')
        for path, sha in bindings.items():
            facts.bind_external(path)
            if digest(facts.file(path)) != sha:
                raise MissingEvidence('current model inputs')
        expected = set(meta.get('models', []))
        fitted = {r['model']: r for r in rows}
        observed = {r['model']: r for r in receipts}
        missing = sorted(expected-set(fitted) | expected-set(observed))
        if missing:
            return False, {'missingModels': missing}
        if not expected or len(fitted) != len(rows) or len(observed) != len(receipts):
            raise MissingEvidence('nonempty unique model identities')
        bad = []
        source=Path(meta['data'])
        source_rel=str(source) if source.is_absolute() else source.as_posix()
        if facts.file(source_rel) not in {facts.file(s['path']) for s in facts.datasets()}:
            raise MissingEvidence('model input registered for source verification')
        source_rows=facts.csv(source_rel)
        if set(fitted)!=expected or set(observed)!=expected:bad.append('model-identities')
        for mid in expected:
            used = observed[mid]['used_rows']
            if not isinstance(used,list):raise MissingEvidence('CSV-row sample identities for '+mid)
            if type(observed[mid]['n']) is not int or int(fitted[mid]['n']) != observed[mid]['n'] or len(used) != observed[mid]['n'] or len(set(used)) != len(used) or any(type(i) is not int or i<1 or i>len(source_rows) for i in used):
                bad.append(mid)
        if ident == 'stats-flow':
            checks = meta.get('flow_checks')
            bad += [r['model'] for r in checks or [] if r.get('match') is not True]
            for mid in expected:
                sample=observed[mid]
                if not all(k in sample for k in ('n_before','n_dropna','n_removed_separation')):
                    raise MissingEvidence('per-model attrition accounting')
                if not (0<sample['n']<=sample['n_before']<=meta['n']) or sample['n_before']-sample['n_dropna']-sample['n_removed_separation']!=sample['n']:
                    bad.append(mid)
        if ident=='models-index':bad+=facts.model_index({mid:{'n':observed[mid]['n'],'data':source_rel} for mid in expected})
        return not bad and meta.get('failures') == 0, {'models': sorted(expected), 'invalidModels': bad}
    specs, results = facts.models()
    # Model identities are explicitly stored in the model_result data.
    by_model = {}
    for record in results.values():
        mid = record['data'].get('model_id') or record['data'].get('model')
        if isinstance(mid, str):
            by_model[mid] = record
    missing = sorted(set(specs)-set(by_model))
    if missing:
        raise MissingEvidence('model results for ' + ', '.join(missing))
    if ident in ('stats-models', 'models-index'):
        import contract_v2 as C
        import models
        project = C.Project(facts.inputs.root, create=False)
        bad = [mid for mid, record in by_model.items()
               if record['status'] not in ('produced','validated')
               or record['data'].get('computation',{}).get('status')!='checked'
               or not models.current_result(project,record)]
        if ident=='models-index':bad+=facts.model_index({mid:{'n':r['data'].get('sample_scope',{}).get('n')} for mid,r in by_model.items()})
        return not bad, {'models': len(by_model), 'nonCompleted': bad}
    import execution
    import contract_v2 as C
    project=C.Project(facts.inputs.root,create=False)
    bad=[]; measured=[]
    for mid,record in by_model.items():
        spec=specs[mid]['data'];computation=record['data'].get('computation',{})
        if not execution.current(project,spec,computation):raise MissingEvidence('current model execution for '+mid)
        for mapping in ('inputs','code'):
            for file in computation.get(mapping,{}):facts.bind_external(file)
        sample=record['data'].get('sample_scope',{})
        if sample.get('kind')=='none':continue
        used=sample.get('used_keys');n=sample.get('n')
        inputs=[i for i in spec['inputs'] if i['role'] in ('fit','train')]
        if not used or type(n) is not int or len(inputs)!=1:raise MissingEvidence('role-specific sample identities for '+mid)
        source=inputs[0];rows=facts.csv(source['dataset'],source['keys'])
        actual=[tuple(str(v) for v in key) for key in used]
        available={tuple(row[k] for k in source['keys']) for row in rows}
        if len(set(actual))!=n or len(actual)!=n or not set(actual)<=available:bad.append(mid)
        measured.append({'model':mid,'n':n,'inputRows':len(rows),'role':source['role']})
    if not measured:return 'na',{'rule':'all-current-models-have-explicit-no-observation-N','models':sorted(by_model)}
    return not bad, {'invalidModels':bad,'samples':measured}


def qa(facts, ident):
    if ident == 'qa-fresh':
        return facts.freshness('qa')
    if ident == 'qa-pdf':
        import fitz

        with fitz.open(facts.file('output/manuscript.pdf')) as document:
            pages = len(document)
            encrypted = document.is_encrypted
        return pages > 0 and not encrypted, {'pages': pages, 'encrypted': encrypted}
    if ident == 'qa-report':
        report = facts.json('output/qa/qa_report.json')
        checks = report.get('checks')
        if not checks or 'error_count' not in report:
            raise MissingEvidence('completed QA checks and explicit error count')
        actual = sum(len(c.get('errors', [])) for c in checks.values())
        return actual == report['error_count'] == 0, {'reportedErrors': report['error_count'], 'actualErrors': actual, 'checks': sorted(checks)}
    if ident == 'qa-review':
        report = facts.file('output/review/review_pack.md')
        return bool(report.read_text(encoding='utf-8').strip()), {'bytes': report.stat().st_size, 'scope': 'review pack exists; not proof of human review'}
    if ident in ('provenance-cells', 'provenance-claims'):
        if ident == 'provenance-cells':
            return verification(facts, 'verification-cells')
        if facts.policy.get('researchContract') == 'v1' and not (facts.inputs.root/'output/v2').is_dir():
            from gate_claims import evaluate_claims
            return evaluate_claims(facts)
        ready, proof = v2(facts, 'v2.release-ready')
        if ready is not True:
            raise MissingEvidence('current claim support and printed-number validation')
        return ready, proof
    if ident == 'qa-v05':
        from gate_checks import numbers
        if numbers(facts.inputs, facts.policy)['status'] == 'unjudged':
            raise MissingEvidence('current complete numerical check and bound outputs')
        rows = facts.csv('output/verify/number_issues.csv', ('severity','check'), allow_empty=True)
        receipt = facts.json('output/verify/run.json').get('producers', {}).get('verify_numbers.py', {})
        if receipt.get('check') not in ('all', 'tables') or not receipt.get('bindings'):
            raise MissingEvidence('current model-N check receipt')
        for relative, sha in receipt['bindings'].items():
            if digest(facts.file(relative)) != sha:
                raise MissingEvidence('current model-N inputs')
        return not any(r['check']=='V-05' and r['severity']=='error' for r in rows), {'issues': [r for r in rows if r['check']=='V-05']}
    gate = facts.research()
    return not gate.issues, {'errors': gate.issues, 'sources': len(gate.sources), 'models': gate.model_count}


def v2(facts, ident):
    directory = facts.inputs.root / 'output/v2'
    if not directory.is_dir():
        facts.inputs.collection('output/v2')
        if facts.policy.get('researchContract')=='v1':
            return 'na', {'rule':'explicit-v1-research-contract-without-v2-records','scope':'project'}
        raise MissingEvidence('v2 release evidence')
    import contract_v2 as C
    import release

    facts.inputs.collection('output/v2')
    current = release.current(C.Project(facts.inputs.root, create=False))
    evaluation = current.get('evaluation')
    if not evaluation:
        raise MissingEvidence('current published release evaluation')
    if current.get('project_ready') is False:
        return False, {'reason': 'published release bindings changed'}
    for file in evaluation.get('bindings', {}).get('files', {}):
        facts.bind_external(file)
    return evaluation.get('project_ready') is True, {
        'projectReady': evaluation.get('project_ready', False),
        'hardFailed': evaluation.get('hard_failed', []), 'status': current['status']}


def source_figure(facts, ident):
    from qa_outputs import check_figures
    rows = [r for r in facts.figures() if r.get('status', 'ok') == 'ok']
    if not rows:
        raise MissingEvidence('nonempty delivered source figure scope')
    observations = []
    for row in rows:
        source = facts.figure_path(row, 'png')
        folder = source.parent.relative_to(facts.inputs.root).as_posix()
        facts.inputs.collection(folder)
        result = check_figures(str(source.parent), min_dpi=600,
                               width_cm=facts.policy['thresholds']['figureWidthCm'],
                               min_fontsize=facts.policy['thresholds']['minFontPt'])
        if ident == 'fig-source-dpi':
            measured = [r for r in result['files'] if r['file'] == source.name]
            if not measured or measured[0].get('dpi_at_width') is None:
                raise MissingEvidence('readable source pixel dimensions')
            observed = measured[0]['dpi_at_width']
            observations.append((row['id'], observed, observed >= facts.policy['thresholds']['minEffectiveDpi']))
        else:
            measured = [r for r in result.get('pdfs', []) if Path(r['file']).stem == source.stem]
            if not measured or measured[0].get('min_fontsize_effective') is None:
                raise MissingEvidence('measurable source vector text')
            observed = measured[0]['min_fontsize_effective']
            observations.append((row['id'], observed, observed >= facts.policy['thresholds']['minFontPt']))
    return all(r[2] for r in observations), {'scope': 'source-at-planned-width', 'measurements': observations}


def extra(facts, ident):
    if ident == 'audit-flow':
        return flow(facts, 'output/audit/sample_flow.csv')
    if ident == 'coding-sheet':
        applicability, proof = coding(facts, 'coding-applicable')
        if applicability == 'na':
            return applicability, proof
        rows = facts.csv('output/coding/coding_sheet.csv')
        return bool(rows), {'rows': len(rows)}
    if ident == 'manuscript-docx':
        from docx import Document
        document = Document(facts.file('output/manuscript.docx'))
        return bool(document.paragraphs or document.tables), {'paragraphs': len(document.paragraphs), 'tables': len(document.tables)}
    if ident == 'qa-decision-facts':
        rows = facts.csv('output/qa/decision_issues.csv', ('severity',), allow_empty=True)
        # Decisions and their machine validation must belong to the current run.
        current, proof = facts.freshness('qa')
        return current and not any(r['severity']=='error' for r in rows), {'errors': sum(r['severity']=='error' for r in rows), 'production': proof}
    raise MissingEvidence(ident)


def caption_sample(facts, ident):
    from docx import Document
    from qa_outputs import parse_n
    paragraphs = Document(facts.file('output/manuscript.docx')).paragraphs
    mapping = facts.json('output/figure_map.json')
    mapping = mapping.get('figures', []) if isinstance(mapping, dict) else mapping
    if not mapping:
        raise MissingEvidence('declared actual figure captions')
    failures = []
    no_n = []
    manifest = facts.figures()
    fit = None
    for index, figure in enumerate(mapping, 1):
        tag = figure.get('tag') or f'图{index}'
        source = figure.get('image') or figure.get('png')
        row=facts.manifest_figure(source)
        caption=paragraphs[caption_index(paragraphs,{**figure,'tag':tag},row)].text
        if row and row.get('sample_kind')=='none':
            import contract_v2 as C
            import models
            specs,results=facts.models()
            mid=row.get('model_id')
            result=next((r for r in results.values() if r['data'].get('model')==mid),None)
            if (mid not in specs or result is None or specs[mid]['data'].get('sample_accounting',{}).get('kind')!='none'
                    or result['data'].get('sample_scope',{}).get('kind')!='none'
                    or not models.current_result(C.Project(facts.inputs.root,create=False),result)):
                raise MissingEvidence('current non-observational model proof for '+tag)
            for mapping_name in ('inputs','code'):
                for file in result['data']['computation'].get(mapping_name,{}):facts.bind_external(file)
            if re.search(r'(?i)N\s*[=＝]\s*\d',caption):failures.append(tag)
            no_n.append(tag)
            continue
        matches = re.findall(r'(?i)N\s*[=＝]\s*([0-9][0-9,]*)', caption)
        if not matches:
            failures.append(tag)
            continue
        if ident == 'recheck.caption-n-present':
            continue
        if row is None:
            raise MissingEvidence('manifest identity for printed caption ' + tag)
        expected, _ = parse_n(row.get('n',''))
        if row.get('model_id'):
            if fit is None:
                fit = {r['model']:int(r['n']) for r in facts.csv('output/models/fit.csv', ('model','n'))}
            expected = fit.get(row['model_id'])
        if expected is None:
            raise MissingEvidence('declared denominator for ' + tag)
        if len(set(int(n.replace(',','')) for n in matches)) != 1 or int(matches[0].replace(',','')) != expected:
            failures.append(tag)
    if not failures and len(no_n)==len(mapping):
        return 'na',{'rule':'all-figures-bound-to-current-non-observational-models','figures':no_n}
    return not failures, {'invalidCaptions': failures, 'figures': len(mapping),'noObservationN':no_n}


HANDLERS = {
    **{i: audit for i in ['audit-dedupe','audit-freshness','audit-hash','audit-monotonic','audit-summary','audit-truncated']},
    **{i: coding for i in ['coding-applicable','coding-cross','coding-flow','coding-skipped']},
    **{i: data for i in ['dataset-csv','dataset-flag','dataset-key','dataset-path','datasets-index','registry-present']},
    **{i: verification for i in ['verification-cells','verification-final','verification-fresh','source-coverage']},
    **{i: figures for i in ['fig-cited','fig-files','fig-fresh','fig-manifest','fig-palette','fig-paper','fig-status','fig-title']},
    **{i: manuscript for i in ['manuscript-body','manuscript-figures','manuscript-fresh','tbl-present']},
    **{i: stats for i in ['methods-report','models-index','models-plan','models-sweep','stats-fit-n','stats-flow','stats-fresh','stats-models']},
    **{i: qa for i in ['provenance-cells','provenance-claims','qa-fresh','qa-pdf','qa-report','qa-review','qa-v05','research-gate']},
    'v2.release-ready': v2,
    **{i: extra for i in ['audit-flow','coding-sheet','manuscript-docx','qa-decision-facts']},
    **{i: source_figure for i in ['fig-source-dpi','fig-source-font']},
    **{i: caption_sample for i in ['recheck.caption-n-present','recheck.caption-n-consistent']},
}


def evaluate_artifacts(inputs, policy, definitions):
    facts = Facts(inputs, policy)
    out = []
    for definition in definitions:
        ident = definition['id']
        if ident not in HANDLERS:
            continue
        before = set(inputs.resources)
        try:
            result, observed = HANDLERS[ident](facts, ident)
            status = result if result == 'na' else 'pass' if result is True else 'fail'
            reason = None
        except MissingEvidence as exc:
            status, reason = 'unjudged', 'missing-input'
            observed = {'missing': str(exc)}
        except Exception as exc:
            status, reason = 'unjudged', 'unreadable' if not isinstance(exc, ImportError) else 'engine-missing'
            # Exception strings may contain absolute paths and source content.
            observed = {'errorType': type(exc).__name__, 'check': ident}
        refs = sorted(inputs.resources)
        anchors = {
            'audit-flow':'output/audit/sample_flow.csv', 'audit-monotonic':'output/audit/sample_flow.csv',
            'audit-dedupe':'output/audit/dedupe_plan.csv', 'audit-freshness':'output/audit/corpus_files.csv',
            'audit-hash':'output/audit/corpus_files.csv', 'audit-summary':'output/audit/corpus_summary.json',
            'audit-truncated':'output/audit/corpus_summary.json', 'coding-flow':'output/coding/sample_flow.csv',
            'coding-sheet':'output/coding/coding_sheet.csv', 'coding-cross':'output/coding/coding_sheet.csv',
            'coding-skipped':'output/coding/skipped_documents.csv', 'coding-applicable':'output/audit/corpus_files.csv',
            'qa-pdf':'output/manuscript.pdf', 'qa-report':'output/qa/qa_report.json',
            'qa-v05':'output/verify/number_issues.csv', 'qa-review':'output/review/review_pack.md',
            'v2.release-ready':'output/v2/release/manifest.json',
        }
        new_refs = [ref for ref in inputs.resources if ref not in before]
        evidence_rel = anchors.get(ident)
        if evidence_rel not in inputs.resources:
            evidence_rel = new_refs[-1] if new_refs else next((r for r in refs if r!='.workbench/gates/policy.json'), '.workbench/gates/policy.json')
        # Avoid leaking absolute paths from legacy issue payloads.
        def portable(value):
            if isinstance(value, dict):
                return {portable(str(k)): portable(v) for k, v in value.items()}
            if isinstance(value, list):
                return [portable(v) for v in value]
            if isinstance(value, str):
                text=value
                bases=[(inputs.root,'.'),(Path(__file__).resolve().parent.parent,'<skill>')]
                bases.extend((base,f'<{key}>') for key,base in inputs.material_roots.items())
                for base,label in sorted(bases,key=lambda row:len(str(row[0])),reverse=True):
                    for spelling in {str(base),base.as_posix()}:text=text.replace(spelling,label)
                return text
            return value
        gate = verdict(ident, status, definition['label'], refs,
                       [structure(evidence_rel, definition['label'], portable(observed))], reason)
        gate['collectionRefs'] = sorted(inputs.collections)
        gate['label'] = definition['label']
        gate['level'] = definition['defaultLevel']
        if status == 'na':
            gate['applicability'] = {'rule': observed['rule'], 'evidenceRefs': refs, 'scope': observed}
        out.append(gate)
    return out
