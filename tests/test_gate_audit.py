"""Independent audit counterexamples over real files and existing producers."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'empirical-research-pipeline/scripts'))
import gate_contract as C
import gates
from gate_facts import Facts,caption_sample,manuscript
from gate_facts import data,audit,coding,figures,stats,MissingEvidence
import test_gate_acceptance as acceptance


class InputAudit(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'project';self.root.mkdir()
        self.outside=Path(self.temp.name)/'material';self.outside.mkdir()

    def test_second_collection_scan_cannot_erase_an_addition(self):
        folder=self.root/'data';folder.mkdir();(folder/'a.csv').write_text('a')
        inputs=C.Inputs(self.root);inputs.collection('data');(folder/'b.csv').write_text('b')
        try:inputs.collection('data')
        except ValueError:pass
        self.assertFalse(inputs.unchanged())

    def test_external_rebind_preserves_first_observation(self):
        C.atomic_json(self.root/'.workbench/gates/roots.json',{'schema':'dsa.gate-roots/1','roots':{'material:x':str(self.outside)}})
        source=self.outside/'a.csv';source.write_text('first')
        inputs=C.Inputs(self.root);inputs.file(str(source));source.write_text('later')
        try:Facts(inputs,{}).bind_external(source)
        except ValueError:pass
        self.assertFalse(inputs.unchanged())

    def test_json_exponent_overflow_is_not_a_finite_number(self):
        path=self.root/'bad.json';path.write_text('{"nested":{"x":1e400}}')
        with self.assertRaises(ValueError):C.read_json(path)

    def test_corrupt_current_pointer_can_be_reinspected_without_generation_reuse(self):
        gates.init_policy(self.root)
        first=gates.evaluate(self.root,'dataset','data-ready')
        state=self.root/'output/gates/state/dataset.json';state.write_text('{broken')
        second=gates.evaluate(self.root,'dataset','data-ready')
        self.assertGreater(second['generation'],first['generation'])
        archived=self.root/'output/gates/runs'/second['attemptId']/'previous-state.bin'
        self.assertEqual('{broken',archived.read_text())


class DocumentAudit(unittest.TestCase):
    def setUp(self):
        self.fixture=acceptance.ArtifactAcceptance();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.fixture();self.root=self.fixture.root

    def facts(self):return self.fixture.facts()

    def test_real_producer_caption_spacing(self):
        from docx import Document
        path=self.root/'output/manuscript.docx';doc=Document(path)
        doc.paragraphs[-1].text='图 1  Synthetic chart（N=2）';doc.save(path)
        self.assertTrue(caption_sample(self.facts(),'recheck.caption-n-present')[0])

    def test_body_reference_at_paragraph_start_is_not_a_caption(self):
        from docx import Document
        path=self.root/'output/manuscript.docx';doc=Document(path)
        doc.paragraphs[0].text='图1显示合成样本的结果。';doc.save(path)
        self.assertTrue(manuscript(self.facts(),'fig-cited')[0])

    def test_one_picture_cannot_satisfy_two_declared_placements(self):
        self.fixture.write('output/figure_map.json',{'figures':[
            {'id':'F1','tag':'图1','png':'output/figures/chart.png'},
            {'id':'F2','tag':'图2','png':'output/figures/chart.png'}]})
        self.assertFalse(manuscript(self.facts(),'manuscript-figures')[0])

    def test_same_basename_cannot_choose_another_figures_denominator(self):
        from _helpers import make_png
        make_png(str(self.root/'output/other/chart.png'),1200,800)
        self.fixture.write('output/chart_pack/chart_manifest.csv',
            'id,status,png,title,n\nOTHER,ok,output/other/chart.png,Other,2\nF1,ok,output/figures/chart.png,Synthetic chart,3\n')
        self.assertFalse(caption_sample(self.facts(),'recheck.caption-n-consistent')[0])

    def test_same_table_count_cannot_hide_changed_cells(self):
        from docx import Document
        path=self.root/'output/manuscript.docx';doc=Document(path)
        doc.tables[0].cell(1,1).text='999';doc.save(path)
        self.assertFalse(manuscript(self.facts(),'tbl-present')[0])

    def test_declared_body_paragraphs_must_exist_in_delivered_document(self):
        self.fixture.write('manuscript.json',{'blocks':[{'type':'para','text':'This required paragraph is absent.'}]})
        self.assertFalse(manuscript(self.facts(),'manuscript-body')[0])


class ClaimAudit(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        C.atomic_json(self.root/'research_registry.json',{'model_plan':'models.jsonl','datasets':[{'id':'x','path':'data.csv','key':'id'}]})
        (self.root/'data.csv').write_text('id,in_analysis\na,1\nb,1\n')
        (self.root/'models.jsonl').write_text('{"id":"unused"}\n')
        from docx import Document
        doc=Document();doc.add_paragraph('Synthetic claim under audit.')
        (self.root/'output').mkdir();doc.save(self.root/'output/manuscript.docx')

    def evaluate(self,assertion):
        from gate_claims import evaluate_claims
        path=self.root/'output/claims/claims.jsonl';path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'id':'C1','text':'Synthetic claim under audit.','assert':assertion})+'\n')
        return evaluate_claims(Facts(C.Inputs(self.root),{}))

    def test_interval_does_not_require_an_unused_right_operand(self):
        self.assertTrue(self.evaluate({'op':'in_range','left':'dataset:x.rows','from':1,'to':3})[0])

    def test_old_ref_value_assertion_aliases_remain_supported(self):
        self.assertTrue(self.evaluate({'op':'eq','ref':'dataset:x.rows','value':2})[0])

    def test_large_integer_comparison_is_exact(self):
        self.assertFalse(self.evaluate({'op':'eq','left':'9007199254740993','right':'9007199254740992'})[0])

    def test_tautology_without_a_data_reference_is_not_provenance(self):
        with self.assertRaises(MissingEvidence):self.evaluate({'op':'eq','left':2,'right':2})


class RegistrationAudit(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.write('research_registry.json',{'datasets':[{'id':'x','path':'data.csv','key':'id'}]})
        self.write('data.csv','id,in_analysis\na,1\nb,0\n')

    def write(self,rel,value):
        file=self.root/rel;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(value) if isinstance(value,(dict,list)) else value,encoding='utf-8')

    def facts(self):return Facts(C.Inputs(self.root),{})

    def test_disagreeing_workbench_dataset_index_cannot_pass(self):
        self.write('output/datasets/index.json',{'datasets':[{'id':'x','file':'data.csv','rows':99}]})
        self.assertFalse(data(self.facts(),'datasets-index')[0])

    def test_matching_workbench_dataset_index_can_pass(self):
        self.write('output/datasets/index.json',{'datasets':[{'id':'x','file':'data.csv','rows':2,'columns':[{'name':'id'},{'name':'in_analysis'}],'inAnalysis':{'column':'in_analysis','n':1}}]})
        self.assertTrue(data(self.facts(),'datasets-index')[0])

    def test_registered_encoding_and_delimiter_are_honoured(self):
        self.write('research_registry.json',{'datasets':[{'id':'x','path':'data.csv','key':'id','encoding':'gb18030','delimiter':';'}]})
        (self.root/'data.csv').write_bytes('id;in_analysis;类别\na;1;样本\n'.encode('gb18030'))
        self.assertTrue(data(self.facts(),'dataset-key')[0])

    def test_empty_dedupe_plan_cannot_cover_existing_duplicates(self):
        self.write('output/audit/corpus_summary.json',{'total_files':2})
        self.write('output/audit/corpus_files.csv','rel_path,status,dup_group,dup_role\na.txt,valid,G1,keeper\nb.txt,valid,G1,duplicate\n')
        self.write('output/audit/dedupe_plan.csv','group,role,rel_path,reason\n')
        self.assertFalse(audit(self.facts(),'audit-dedupe')[0])

    def test_native_audit_metadata_exclusions_are_not_missing_hashes(self):
        self.write('output/audit/corpus_summary.json',{'total_files':2,'hash_disabled':False})
        self.write('output/audit/corpus_files.csv','rel_path,status,md5\na.txt,valid,0cc175b9c0f1b6a831c399e269772661\n.DS_Store,metadata,\n')
        self.assertTrue(audit(self.facts(),'audit-hash')[0])

    def test_coded_and_excluded_scopes_cannot_overlap(self):
        self.write('output/audit/corpus_files.csv','rel_path,status\na.txt,valid\n')
        self.write('output/coding/coding_sheet.csv','rel_path,code\na.txt,X\n')
        self.write('output/coding/skipped_documents.csv','rel_path,reason\na.txt,excluded\n')
        self.assertFalse(coding(self.facts(),'coding-cross')[0])

    def test_partial_paper_figure_manifest_cannot_pass(self):
        self.write('paper.json',{'figures':[{'id':'F1'},{'id':'F2'}]})
        self.write('output/figures/paper_figures_manifest.csv','id,status\nF1,ok\n')
        self.assertFalse(figures(self.facts(),'fig-paper')[0])

    def test_model_data_must_be_registered_for_verification(self):
        self.write('other.csv','id,in_analysis\na,1\n')
        self.write('output/models/fit.csv','model,n\nM1,1\n')
        self.write('output/models/model_meta.json',{'data':'other.csv','models':['M1'],'failures':0,'input_bindings':{str(self.root/'other.csv'):C.digest(self.root/'other.csv')},'sample_receipts':[{'model':'M1','n':1,'used_rows':[1]}]})
        with self.assertRaises(MissingEvidence):stats(self.facts(),'stats-models')

    def test_model_index_denominator_must_match_execution(self):
        self.write('output/models/fit.csv','model,n\nM1,1\n')
        self.write('output/models/model_meta.json',{'data':'data.csv','models':['M1'],'failures':0,'input_bindings':{str(self.root/'data.csv'):C.digest(self.root/'data.csv')},'sample_receipts':[{'model':'M1','n':1,'used_rows':[1]}]})
        self.write('output/models/index.json',{'models':[{'id':'M1','dataset':'x','n':999}]})
        self.assertFalse(stats(self.facts(),'models-index')[0])

    def test_production_environment_change_invalidates_freshness(self):
        script=self.root/'analysis.py';self.write('analysis.py','# executed code\n')
        self.write('output/result.csv','n\n1\n')
        environment={**gates.environment(),'python':'0.0.0'}
        self.write('output/gates/production/stats.json',{'status':'completed','runId':'fixture','environment':environment,
            'implementation':[{'path':'analysis.py','sha256':C.digest(script)}],
            'inputs':[{'path':'data.csv','sha256':C.digest(self.root/'data.csv')}],
            'outputs':[{'path':'output/result.csv','sha256':C.digest(self.root/'output/result.csv')}]})
        self.assertFalse(stats(self.facts(),'stats-fresh')[0])


if __name__=='__main__':unittest.main()
