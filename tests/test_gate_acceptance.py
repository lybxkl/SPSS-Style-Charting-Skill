"""Known-answer acceptance: real files, real receipts and deliberate mutations.

All reread attestations are synthetic fixtures, never research approvals.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from _helpers import run, write_csv, make_png
from test_research_integrity import IntegrityCase
from gate_contract import Inputs, digest, read_json
from gate_facts import Facts, stats, qa, figures, manuscript, caption_sample, verification
import gates


class LegacyReceiptAcceptance(IntegrityCase):
    def check(self, final=False, *extra):
        self.json('research_registry.json',self.registry)
        args=['--registry',self.p('research_registry.json'),'--root',self.tmp,'--out',self.p('output/data_verification')]
        if final:args+=['--stage','final','--snapshot',self.p('output/data_verification/verification_snapshot.json')]
        return run('verify_dataset.py',*args,*extra)

    def approve_fixture(self):
        from datetime import datetime,timezone
        self.assertEqual(0,self.check().returncode)
        from verify_dataset import load_jsonl
        tasks=load_jsonl(next(Path(self.p('output/data_verification')).glob('review_template_*.jsonl')))
        for row in tasks:
            row.update(status='verified',source_reread=True,reviewer='synthetic-test-reviewer',method='source_reread',
                       note='Synthetic independent known-answer fixture',checked_at=datetime.now(timezone.utc).isoformat())
        self.jsonl('reviews.jsonl',tasks)
        final=self.check(True);self.assertEqual(0,final.returncode,final.stdout+final.stderr)

    def test_arbitrary_engine_receipt_and_claim_truth(self):
        self.approve_fixture()
        self.put('analysis.py',"import csv,json\nrows=list(csv.DictReader(open('data.csv',encoding='utf-8-sig')))\n"
                 "with open('sample.csv','w',newline='') as f:\n w=csv.writer(f);w.writerow(['id']);w.writerows([[r['id']] for r in rows])\n"
                 "json.dump({'n':len(rows)},open('diagnostics.json','w'))\n")
        result=run('run_model.py','--id','M1','--root',self.tmp,'--registry','research_registry.json',
                   '--verification','output/data_verification/dataset_verification.json','--input','data.csv',
                   '--code','analysis.py','--output','sample.csv','--output','diagnostics.json',
                   '--receipt',self.p('run.json'),'--',sys.executable,'analysis.py')
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        root=Path(self.tmp);policy=gates.init_policy(root)
        facts=lambda:Facts(Inputs(root),policy)
        for ident in ['stats-models','stats-fit-n','models-index','models-plan','stats-flow']:
            self.assertTrue(stats(facts(),ident)[0],ident)
        from docx import Document
        doc=Document();doc.add_paragraph('There are two people in this synthetic analysis.')
        doc.save(self.p('output/manuscript.docx'))
        self.jsonl('output/claims/claims.jsonl',[{'id':'C1','text':'There are two people in this synthetic analysis.',
                    'assert':{'op':'eq','left':'M1.n','right':2}}])
        self.assertTrue(qa(facts(),'provenance-claims')[0])
        self.jsonl('output/claims/claims.jsonl',[{'id':'C1','text':'There are two people in this synthetic analysis.',
                    'assert':{'op':'eq','left':'M1.n','right':3}}])
        self.assertFalse(qa(facts(),'provenance-claims')[0])
        self.put('analysis.py','changed execution code')
        self.assertFalse(stats(facts(),'stats-models')[0])

    def test_source_coverage_does_not_depend_on_model_completion(self):
        self.json('research_registry.json',self.registry)
        Path(self.p('models.jsonl')).unlink()
        policy=gates.init_policy(self.tmp)
        self.assertTrue(verification(Facts(Inputs(self.tmp),policy),'source-coverage')[0])


class ArtifactAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.policy=gates.init_policy(self.root)

    def write(self,rel,value):
        path=self.root/rel;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value,(dict,list)) else value,encoding='utf-8');return path

    def facts(self):return Facts(Inputs(self.root),self.policy)

    def fixture(self):
        from docx import Document
        from docx.shared import Cm
        png=make_png(str(self.root/'output/figures/chart.png'),3600,2400)
        self.write('output/chart_pack/chart_manifest.csv','id,status,png,title,n\nF1,ok,output/figures/chart.png,Synthetic chart,2\n')
        self.write('output/figure_map.json',{'figures':[{'id':'F1','tag':'图1','png':'output/figures/chart.png'}]})
        self.write('table.csv','term,n\nSynthetic,2\n')
        self.write('manuscript.json',{'blocks':[{'type':'table','csv':'table.csv'}]})
        doc=Document();doc.add_paragraph('正文引用图1，说明合成夹具的结果。');doc.add_picture(png,width=Cm(15));doc.add_paragraph('图1 Synthetic chart N=2')
        table=doc.add_table(rows=2,cols=2)
        for row,values in zip(table.rows,[['term','n'],['Synthetic','2']]):
            for cell,value in zip(row.cells,values):cell.text=value
        doc.save(str(self.root/'output/manuscript.docx'))

    def test_real_images_docx_tables_citations_and_captions(self):
        self.fixture()
        for ident in ['fig-manifest','fig-status','fig-title','fig-files','fig-cited','fig-paper']:
            self.assertIn(figures(self.facts(),ident)[0],(True,'na'),ident)
        for ident in ['manuscript-body','manuscript-figures','tbl-present']:
            self.assertTrue(manuscript(self.facts(),ident)[0],ident)
        for ident in ['recheck.caption-n-present','recheck.caption-n-consistent']:
            self.assertTrue(caption_sample(self.facts(),ident)[0],ident)
        self.write('output/chart_pack/chart_manifest.csv','id,status,png,title,n\nF1,ok,output/figures/chart.png,Synthetic chart,3\n')
        self.assertFalse(caption_sample(self.facts(),'recheck.caption-n-consistent')[0])
        (self.root/'output/figures/chart.png').write_bytes(b'not an image')
        self.assertFalse(figures(self.facts(),'fig-files')[0])

    def test_freshness_is_content_and_collection_bound(self):
        source=self.write('data/input.csv','id\n001\n');output=self.write('output/models/result.csv','n\n1\n')
        self.write('output/gates/production/stats.json',{'status':'completed','runId':'real-fixture-run','environment':gates.environment(),
            'implementation':[{'path':str(Path(__file__).resolve().parents[1]/'empirical-research-pipeline/scripts/gates.py'),
                               'sha256':digest(Path(__file__).resolve().parents[1]/'empirical-research-pipeline/scripts/gates.py')}],
            'inputs':[{'path':'data/input.csv','sha256':digest(source)}],
            'outputs':[{'path':'output/models/result.csv','sha256':digest(output)}],
            'collections':[{'basePath':'data','members':['data/input.csv']}]})
        self.assertTrue(stats(self.facts(),'stats-fresh')[0])
        self.write('data/new.csv','id\n002\n')
        self.assertFalse(stats(self.facts(),'stats-fresh')[0])

    def test_math_caption_na_requires_actual_current_model(self):
        self.fixture()
        from test_models_entities import TestMathModels
        import contract_v2 as C
        import models
        helper=TestMathModels();helper.tmp=str(self.root)
        project=C.Project(self.root)
        helper._lp_spec(project,c=[-1,-2],A_ub=[[1,1]],b_ub=[4],bounds=[[0,3],[0,3]])
        models.solve(project,'OPT1',budget_seconds=20)
        self.write('output/chart_pack/chart_manifest.csv','id,status,png,title,n,model_id,sample_kind\nF1,ok,output/figures/chart.png,LP optimum,,OPT1,none\n')
        from docx import Document
        path=self.root/'output/manuscript.docx';doc=Document(path);doc.paragraphs[-1].text='图1 LP optimum';doc.save(path)
        self.assertEqual('na',caption_sample(self.facts(),'recheck.caption-n-present')[0])
        self.assertEqual('na',caption_sample(self.facts(),'recheck.caption-n-consistent')[0])
        doc=Document(path);doc.paragraphs[-1].text='图1 LP optimum N=2';doc.save(path)
        self.assertFalse(caption_sample(self.facts(),'recheck.caption-n-present')[0])

    def test_explicit_all_included_requires_evidence(self):
        self.write('research_registry.json',{'datasets':[{'id':'x','path':'data/x.csv','key':'id',
            'analysis_selection':{'kind':'all','reason':'All enumerated records are eligible','evidence':['docs/scope.md']}}]})
        self.write('data/x.csv','id,x\n001,2\n002,3\n')
        self.write('docs/scope.md','Synthetic fixture includes both records, without exclusions.')
        report=gates.evaluate(self.root,'dataset','analysis-ready')
        self.assertEqual('pass',next(g for g in report['gates'] if g['id']=='dataset-in-analysis')['status'])
        (self.root/'docs/scope.md').unlink()
        report=gates.evaluate(self.root,'dataset','analysis-ready')
        self.assertEqual('unjudged',next(g for g in report['gates'] if g['id']=='dataset-in-analysis')['status'])


if __name__=='__main__':unittest.main()
