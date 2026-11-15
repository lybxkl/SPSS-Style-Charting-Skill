import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'empirical-research-pipeline/scripts'
sys.path.insert(0,str(SCRIPTS))
import gate_contract as C
import gates


class GateReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        gates.init_policy(self.root)
        self.write('output/dataset/analysis.csv','id,in_analysis\na,1\nb,0\n')

    def write(self,rel,text):
        p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');return p

    def report(self):return gates.evaluate(self.root,'dataset','data-ready')

    def gate(self):return next(g for g in self.report()['gates'] if g['id']=='dataset-in-analysis')

    def test_default_filter(self):self.assertEqual('pass',self.gate()['status'])
    def test_required_rule_cannot_be_removed_or_postponed(self):
        policy=C.read_json(self.root/'.workbench/gates/policy.json')
        for change in ['remove','disable','postpone']:
            candidate=copy.deepcopy(policy)
            req=next(r for r in candidate['requirements'] if r['gateId']=='dataset-in-analysis')
            if change=='remove':candidate['requirements'].remove(req)
            elif change=='disable':req['required']=False
            else:req['blockingAt']='delivery-ready'
            with self.subTest(change=change),self.assertRaises(ValueError):gates.validate_policy(candidate)
    def test_unknown_collection_reference_is_rejected(self):
        report=self.report();report['gates'][0]['collectionRefs']=['unknown']
        with self.assertRaises(ValueError):C.validate_report(report)
    def test_valid_shape_cannot_replace_the_published_report_bytes(self):
        report=self.report();report['gates'][0]['detail']='rewritten after publication'
        C.atomic_json(self.root/'output/gates/dataset.json',report)
        with self.assertRaises(ValueError):gates.validate_current(self.root,'output/gates/dataset.json')
    def test_current_pointer_requires_unchanged_request_and_result(self):
        self.report();state=C.read_json(self.root/'output/gates/state/dataset.json')
        result=C.read_json(self.root/state['resultPath']);result['checkerExitCode']=1
        C.atomic_json(self.root/state['resultPath'],result)
        with self.assertRaises(ValueError):gates.validate_current(self.root,'output/gates/dataset.json')
    def test_published_json_schema(self):
        import jsonschema
        schema=C.read_json(SCRIPTS.parent/'contracts/gates/report.schema.json')
        jsonschema.validate(self.report(),schema)
    def test_missing_column(self):
        self.write('output/dataset/analysis.csv','id,value\na,1\n')
        self.assertEqual('unjudged',self.gate()['status'])
    def test_zero_included(self):
        self.write('output/dataset/analysis.csv','id,in_analysis\na,0\n')
        self.assertEqual('fail',self.gate()['status'])
    def test_invalid_flags(self):
        self.write('output/dataset/analysis.csv','id,in_analysis\na,maybe\n')
        self.assertEqual('unjudged',self.gate()['status'])
    def test_reverse_filter(self):
        self.write('chart_config.json',json.dumps({'filter_query':'in_analysis == 0'}))
        self.assertEqual('fail',self.gate()['status'])
    def test_keep_out(self):
        self.write('chart_config.json',json.dumps({'keep_out_of_scope':True}))
        self.assertEqual('unjudged',self.gate()['status'])
    def test_empty_table(self):
        self.write('output/dataset/analysis.csv','id,in_analysis\n')
        self.assertEqual('unjudged',self.gate()['status'])
    def test_multi_dataset_missing(self):
        self.write('research_registry.json',json.dumps({'datasets':[{'path':'output/dataset/analysis.csv'},{'path':'output/absent.csv'}]}))
        self.assertEqual('unjudged',self.gate()['status'])
    def test_attempt_generation(self):
        a=self.report();b=self.report();self.assertEqual(a['generation']+1,b['generation'])
        self.assertNotEqual(a['attemptId'],b['attemptId'])
    def test_validator_rejects_historical_report(self):
        a=self.report()
        rel=f"output/gates/runs/{a['attemptId']}/report.json"
        self.assertEqual(a,gates.validate_current(self.root,rel))
        self.report()
        with self.assertRaises(ValueError):gates.validate_current(self.root,rel)
    def test_validator_rejects_changed_bytes(self):
        self.report()
        self.write('output/dataset/analysis.csv','id,in_analysis\na,0\n')
        with self.assertRaises(ValueError):gates.validate_current(self.root,'output/gates/dataset.json')
    def test_failure_invalidates_previous(self):
        self.report();self.write('chart_config.json','{broken')
        with self.assertRaises(ValueError):self.report()
        state=C.read_json(self.root/'output/gates/state/dataset.json')
        self.assertEqual('crashed',state['phase'])
        self.assertTrue((self.root/'output/gates/dataset.error.json').exists())
        self.write('chart_config.json','{}')
        current=self.report()
        self.assertEqual('completed',C.read_json(self.root/'output/gates/state/dataset.json')['phase'])
        self.assertEqual(current,gates.validate_current(self.root,'output/gates/dataset.json'))
    def test_lock_does_not_steal(self):
        self.write('output/gates/publication.lock',json.dumps({'pid':os.getpid(),'token':'other'}))
        with self.assertRaises(FileExistsError):self.report()
        self.assertTrue((self.root/'output/gates/publication.lock').exists())
    def test_no_absolute_paths(self):
        self.assertNotIn(str(self.root),json.dumps(self.report()))
    def test_duplicate_keys(self):
        with self.assertRaises(ValueError):C.read_json(self.write('bad.json','{"a":1,"a":2}'))
    def test_path_escape(self):
        for path in ['../outside','C:/outside','/outside','a\\b']:
            with self.assertRaises(ValueError):C.resolve(self.root,path)
    def test_summary_and_empty_pass_rejected(self):
        r=self.report();r['summary']['pass']+=1
        with self.assertRaises(ValueError):C.validate_report(r)
        r=self.report();g=r['gates'][0];g.update(status='pass');g['coverage']={k:0 for k in ['expected','checked','failed','unjudged']}
        with self.assertRaises(ValueError):C.validate_report(r)
    def test_inputs_same_size_same_time(self):
        p=self.root/'output/dataset/analysis.csv';inputs=C.Inputs(self.root);inputs.file('output/dataset/analysis.csv');stamp=p.stat()
        p.write_text(p.read_text().replace('a,1','a,0'),encoding='utf-8');os.utime(p,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertFalse(inputs.unchanged())
    def test_missing_final_artifacts(self):
        r=gates.evaluate(self.root,'qa','delivery-ready')
        self.assertTrue(all(g['status'] in ('unjudged','na') for g in r['gates']))
    def test_legacy_number_receipt_not_pass(self):
        self.write('output/verify/run.json','{}');self.write('output/verify/number_issues.csv','severity\n');self.write('output/verify/number_trace.csv','value\n')
        r=gates.evaluate(self.root,'qa','delivery-ready')
        self.assertEqual('unjudged',next(g for g in r['gates'] if g['id']=='qa-numbers')['status'])

    def test_final_dpi_uses_actual_placement(self):
        from test_layout import make_png, make_docx, make_pdf
        png=self.root/'output/source.png'
        make_png(str(png),width=1200,height=800)
        make_docx(str(self.root/'output/manuscript.docx'),str(png),width_cm=15,caption='图1')
        make_pdf(str(self.root/'output/manuscript.pdf'),[{'png':str(png),'width_cm':15,'x_pt':40,'y_pt':70}])
        self.write('output/figure_map.json',json.dumps([{'tag':'图1','title':'','image':str(png)}]))
        r=gates.evaluate(self.root,'qa','delivery-ready')
        dpi=next(g for g in r['gates'] if g['id']=='fig-dpi')
        self.assertEqual('fail',dpi['status'])
        font=next(g for g in r['gates'] if g['id']=='fig-font')
        self.assertEqual('unjudged',font['status'])
        self.assertNotIn(str(self.root),json.dumps(r))

    def test_collection_addition_invalidates(self):
        inputs=C.Inputs(self.root);inputs.collection('output/dataset')
        self.write('output/dataset/new.csv','id\nnew\n')
        self.assertFalse(inputs.unchanged())

    def test_semantic_determinism(self):
        a=self.report();b=self.report()
        for report in [a,b]:
            for key in ['generatedAt','attemptId','reportId','generation']:
                report.pop(key)
        self.assertEqual(a,b)

    def test_changed_helper_invalidates_manifest(self):
        from unittest.mock import patch
        fake=self.root/'package-manifest.json'
        fake.write_text(json.dumps({'members':[{'path':'scripts/gates.py','sha256':'0'*64}]}),encoding='utf-8')
        with patch.object(gates,'CONTRACT',self.root):
            with self.assertRaises(ValueError):gates.manifest_valid()

    def test_valid_numeric_receipt_and_binding_change(self):
        rel='output/dataset/analysis.csv'
        self.write('output/verify/number_issues.csv','severity,detail\n')
        self.write('output/verify/number_trace.csv','number\n')
        self.write('output/verify/run.json',json.dumps({'producers':{'verify_numbers.py':{'check':'all','bindings':{rel:C.digest(self.root/rel)},'output_sha256':{name:C.digest(self.root/'output/verify'/name) for name in ['number_issues.csv','number_trace.csv']}}}}))
        r=gates.evaluate(self.root,'qa','delivery-ready')
        self.assertEqual('pass',next(g for g in r['gates'] if g['id']=='qa-numbers')['status'])
        self.write(rel,'id,in_analysis\na,0\n')
        r=gates.evaluate(self.root,'qa','delivery-ready')
        self.assertEqual('unjudged',next(g for g in r['gates'] if g['id']=='qa-numbers')['status'])


if __name__=='__main__':unittest.main()
