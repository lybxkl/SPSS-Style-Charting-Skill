"""Workflow declarations remain portable and reject invalid execution graphs."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

PACKAGE=Path(__file__).resolve().parents[1]/'empirical-research-pipeline'
spec=importlib.util.spec_from_file_location('workflow_contract',PACKAGE/'scripts/workflow_contract.py')
workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(workflow)

class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.package=Path(self.temp.name)
        shutil.copytree(PACKAGE/'contracts/workflow',self.package/'contracts/workflow')
        self.file=self.package/'contracts/workflow/workflow.json'
        self.value=json.loads(self.file.read_text(encoding='utf-8'))
    def tearDown(self):self.temp.cleanup()
    def write(self,value):self.file.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    def invalid(self,value):
        self.write(value)
        with self.assertRaises((ValueError,workflow.jsonschema.ValidationError)):workflow.validate(self.package)
    def test_actual_published_workflow_is_valid(self):
        result=workflow.validate(PACKAGE)
        self.assertEqual(result['id'],'empirical-research-pipeline')
        self.assertGreater(len(result['stages']),0)
        self.assertTrue(result['sha256'])
    def test_an_unknown_stage_can_be_added_reordered_and_removed(self):
        added=copy.deepcopy(self.value['stages'][0]);added.update(id='new-stage',dependsOn=[])
        self.value['stages'].insert(0,added);self.write(self.value)
        self.assertEqual(workflow.validate(self.package)['stages'][0]['id'],'new-stage')
        self.value['stages'].pop(0);self.write(self.value)
        self.assertNotIn('new-stage',[stage['id'] for stage in workflow.validate(self.package)['stages']])
    def test_unknown_capability_requires_explicit_host_support(self):
        self.value['requiredFeatures'].append('future-engine');self.invalid(self.value)
    def test_duplicate_stage_and_missing_dependency_are_rejected(self):
        duplicate=copy.deepcopy(self.value);duplicate['stages'].append(duplicate['stages'][0]);self.invalid(duplicate)
        self.value['stages'][0]['dependsOn']=['unknown'];self.invalid(self.value)
    def test_dependency_cycle_and_reversed_order_are_rejected(self):
        self.value['stages'][0]['dependsOn']=[self.value['stages'][1]['id']];self.invalid(self.value)
    def test_actions_and_draft_tasks_cannot_reference_removed_stages(self):
        self.value['actions'][0]['stage']='unknown';self.invalid(self.value)
        self.value['actions'][0]['stage']='verify';self.value['draftTasks'][0]['stage']='unknown';self.invalid(self.value)
    def test_unsafe_output_and_script_paths_are_rejected(self):
        bad=copy.deepcopy(self.value);bad['stages'][0]['artifacts']=['../outside'];self.invalid(bad)
        self.value['stages'][1]['steps'][0]['script']='C:/outside.py';self.invalid(self.value)
    def test_rerun_routes_cannot_silently_keep_deleted_stage_ids(self):
        self.value['rerunRules'][0]['stages'].append('deleted-stage');self.invalid(self.value)
    def test_duplicate_json_keys_are_not_accepted(self):
        self.file.write_text('{"schema":"dsa.workflow/1","schema":"ignored"}',encoding='utf-8')
        with self.assertRaises(ValueError):workflow.validate(self.package)

if __name__=='__main__':unittest.main()
