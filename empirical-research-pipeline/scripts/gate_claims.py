"""Bound declarative claim comparisons. Never execute expressions from a claim."""
import operator
import re
from decimal import Decimal,InvalidOperation


def evaluate_claims(facts):
    from gate_facts import MissingEvidence
    from docx import Document
    claims = facts.jsonl('output/claims/claims.jsonl',exact_numbers=True)
    if not claims or any(not c.get('id') for c in claims) or len({c.get('id') for c in claims}) != len(claims):
        raise MissingEvidence('nonempty unique claim identities')
    document = Document(facts.file('output/manuscript.docx'))
    text = ' '.join([p.text for p in document.paragraphs] +
                    [c.text for t in document.tables for r in t.rows for c in r.cells])
    normalize = lambda value: re.sub(r'\s+', '', value)
    printed = normalize(text)
    datasets = {d['id']: d for d in facts.datasets()}
    registry = facts.json('research_registry.json')
    models = {m['id']: m for m in facts.jsonl(registry['model_plan'])}
    gate = None
    anchored = False

    def number(value):
        if isinstance(value, bool):
            raise MissingEvidence('boolean is not a numeric operand')
        try:
            result = Decimal(str(value))
        except (InvalidOperation,ValueError, TypeError):
            raise MissingEvidence('finite numerical operand')
        if not result.is_finite():
            raise MissingEvidence('finite numerical operand')
        return result

    def resolve(value):
        nonlocal gate,anchored
        if isinstance(value, (int, float,Decimal)) and not isinstance(value, bool):
            return number(value)
        raw = str(value).strip()
        if re.fullmatch(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', raw):
            return number(raw)
        if raw.startswith('dataset:'):
            anchored=True
            ident, _, field = raw[8:].partition('.')
            if ident not in datasets:
                raise MissingEvidence('registered dataset '+ident)
            rows = facts.csv(datasets[ident]['path'])
            if field == 'rows': return len(rows)
            if field == 'columns.length': return len(rows[0])
            if field == 'inAnalysis.n':
                if 'in_analysis' not in rows[0]:
                    raise MissingEvidence('actual analysis selection')
                return sum(r['in_analysis'].strip() == '1' for r in rows)
            match = re.fullmatch(r'count\[([^\]=]+)=([^\]]*)\]', field)
            if match and match[1].strip() in rows[0]:
                return sum(r[match[1].strip()].strip() == match[2].strip() for r in rows)
            raise MissingEvidence('supported actual dataset field '+raw)
        ident, _, field = raw.partition('.')
        if ident not in models:
            raise MissingEvidence('registered actual model '+ident)
        anchored=True
        if gate is None:
            gate = facts.research()
            if gate.issues: raise MissingEvidence('current validated model execution receipts')
        model = models[ident]
        if model.get('status') != 'completed':
            raise MissingEvidence('executed model '+ident)
        if field == 'n': return len(facts.csv(model['sample']))
        if field.startswith('coef.'):
            term, _, column = field[5:].rpartition('.')
            aliases = {'beta':['beta','coef','estimate','Estimate','Coef.'],
                       'se':['se','std_err','std.error','Std. Err.'], 'p':['p','pvalue','p_value','P>|t|','P>|z|']}
            if column not in aliases or not model.get('coef'):
                raise MissingEvidence('bound coefficient reference '+raw)
            path = facts.file(model['coef'])
            receipt = facts.json(model['receipt'])
            if path.resolve() not in {facts.file(r['path']).resolve() for r in receipt['outputs']}:
                raise MissingEvidence('coefficient output bound to execution')
            rows = facts.csv(model['coef'])
            hits = [r for r in rows if any(r.get(k) == term for k in ('term','variable','name','predictor','label'))]
            if len(hits) != 1: raise MissingEvidence('unique coefficient term '+term)
            values = [hits[0][k] for k in aliases[column] if k in hits[0]]
            if len(values) != 1: raise MissingEvidence('unambiguous coefficient value '+raw)
            return number(values[0])
        raise MissingEvidence('supported execution-backed reference '+raw)

    comparisons = {'gt':operator.gt, 'lt':operator.lt, 'gte':operator.ge,
                   'lte':operator.le, 'eq':operator.eq, 'ne':operator.ne,
                   'abs_gt':lambda a,b:abs(a)>b}
    results = []
    for claim in claims:
        anchored=False
        if not claim.get('text') or normalize(claim['text']) not in printed:
            raise MissingEvidence('claim text in the delivered manuscript: '+str(claim.get('id')))
        assertion = claim.get('assert') or {}
        left=resolve(assertion.get('left',assertion.get('ref')))
        op = assertion.get('op')
        right=None
        if op == 'in_range':
            low, high = number(assertion.get('from')), number(assertion.get('to'))
            if low > high: raise MissingEvidence('ordered numeric interval')
            passed = low <= left <= high
        elif op in comparisons:
            right=resolve(assertion.get('right',assertion.get('value')))
            passed = comparisons[op](left,right)
        else:
            raise MissingEvidence('supported comparison operator')
        if passed and not anchored:raise MissingEvidence('numeric claim needs an actual registered data or model reference')
        results.append({'claim':claim['id'], 'op':op, 'left':str(left),'right':str(right) if right is not None else None,'pass':passed})
    return all(r['pass'] for r in results), {'claims':results, 'printedTextChecked':True}
