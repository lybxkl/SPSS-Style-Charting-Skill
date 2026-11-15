"""Known-answer tests for the complete stage evaluator dispatch."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'empirical-research-pipeline/scripts'
sys.path.insert(0,str(SCRIPTS))
import gates
from gate_contract import Inputs, read_json
from gate_facts import Facts, HANDLERS, audit, coding, data, flow, verification


class GateFactsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.policy=gates.init_policy(self.root)

    def write(self,rel,text):
        p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(text) if isinstance(text,(dict,list)) else text,encoding='utf-8')
        return p

    def facts(self):return Facts(Inputs(self.root),self.policy)

    def test_every_skill_id_has_actual_dispatch(self):
        expected={g['id'] for g in gates.catalog()['gates'] if g['owner']=='skill'}
        self.assertFalse(expected-set(HANDLERS)-gates.PILOT)

    def test_missing_artifacts_never_pass_for_any_stage(self):
        for stage in ['audit','coding','dataset','verify','stats','figures','manuscript','qa']:
            with self.subTest(stage=stage):
                result=gates.evaluate(self.root,stage,'delivery-ready')
                self.assertTrue(result['gates'])
                self.assertFalse(any(g['status']=='pass' for g in result['gates']))
                self.assertFalse(any(g.get('reason')=='not-supported' for g in result['gates']))

    def test_actual_source_hash_and_member_changes(self):
        import hashlib
        self.write('data/a.txt','alpha')
        md5=hashlib.md5(b'alpha').hexdigest()
        self.write('output/audit/corpus_summary.json',{'root':'data','total_files':1,'truncated':False,'hash_disabled':False})
        self.write('output/audit/corpus_files.csv',f'rel_path,status,md5\na.txt,valid,{md5}\n')
        self.assertTrue(audit(self.facts(),'audit-freshness')[0])
        self.write('data/b.txt','new')
        self.assertFalse(audit(self.facts(),'audit-freshness')[0])
        (self.root/'data/b.txt').unlink();self.write('data/a.txt','omega')
        self.assertFalse(audit(self.facts(),'audit-freshness')[0])

    def test_flow_kinds_and_model_reference(self):
        rel='output/audit/sample_flow.csv'
        self.write(rel,'stage,n,kind,note\nstart,10,stage,\nremoved,2,excluded,\nfit,9,model,stage=start\nend,8,stage,\n')
        self.assertTrue(flow(self.facts(),rel)[0])
        self.write(rel,'stage,n,kind,note\nstart,10,stage,\nfit,11,model,stage=start\n')
        self.assertFalse(flow(self.facts(),rel)[0])

    def test_coding_tabular_na_has_real_scope(self):
        self.write('output/audit/corpus_files.csv','rel_path,status\nsource.csv,valid\n')
        result,proof=coding(self.facts(),'coding-applicable')
        self.assertEqual('na',result);self.assertEqual(['source.csv'],proof['sources'])

    def test_dataset_composite_identity(self):
        self.write('research_registry.json',{'datasets':[{'id':'x','path':'data/x.csv','key':['person','wave']}]})
        self.write('data/x.csv','person,wave,in_analysis\n001,1,1\n001,2,1\n')
        self.assertTrue(data(self.facts(),'dataset-key')[0])
        self.write('data/x.csv','person,wave,in_analysis\n001,1,1\n001,1,1\n')
        self.assertFalse(data(self.facts(),'dataset-key')[0])

    def test_existing_final_engine_is_reused_without_writes(self):
        from _research_fixture import known_project, final_review
        known_project(self.root,fit=False)
        final_review(self.root)
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        ok,proof=verification(self.facts(),'verification-final')
        self.assertTrue(ok);self.assertGreater(proof['cells'],0)
        after={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)


if __name__=='__main__':unittest.main()
