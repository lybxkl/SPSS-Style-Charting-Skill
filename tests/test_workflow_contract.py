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
    def test_gate_catalog_references_are_checked_when_present(self):
        shutil.copytree(PACKAGE/'contracts/gates',self.package/'contracts/gates')
        self.value['stages'][0]['admission']['gates']=['missing-gate'];self.invalid(self.value)
        self.value['stages'][0]['admission']['gates']=[]
        self.value['stages'][0]['inspectionStages']=['missing-report'];self.invalid(self.value)
    def test_report_filters_cannot_disable_admission_with_typos_or_empty_lists(self):
        shutil.copytree(PACKAGE/'contracts/gates',self.package/'contracts/gates')
        for selected in [[],['unknown-report']]:
            self.value['stages'][0]['admission']={'checkpoint':'data-ready','reportStages':selected};self.invalid(self.value)
    def test_paths_have_the_same_canonical_form_in_both_runtimes(self):
        self.value['stages'][0]['artifacts']=['output/trailing/'];self.invalid(self.value)

    def test_script_specific_rerun_rules_precede_the_generic_prefix(self):
        """Engine semantics are first-match-wins, so the exact rules must sit
        above the scripts/ prefix or they would never fire."""
        rules=self.value['rerunRules']
        prefix=next(i for i,rule in enumerate(rules) if rule['pattern']=='scripts/')
        exact=[rule for rule in rules[:prefix] if rule['match']=='exact'
               and rule['pattern'].startswith('scripts/')]
        self.assertGreaterEqual(len(exact),30)
        # and they must actually win: the engine's lookup order is the array
        for rule in exact:
            self.assertTrue(rule['stages'])

    def test_rerun_rules_refine_script_change_blast_radius(self):
        """Changing pubfig must not re-audit the corpus; changing an advisory
        tool must not re-run the dataset."""
        def stages_for(pattern):
            rule=next(r for r in self.value['rerunRules'] if r['pattern']==pattern)
            return set(rule['stages'])
        self.assertEqual(stages_for('scripts/pubfig.py'),
                         {'stats','figures','manuscript','qa'})
        self.assertEqual(stages_for('scripts/mine_candidates.py'),{'coding'})
        self.assertEqual(stages_for('scripts/qa_outputs.py'),{'qa'})
        self.assertEqual(stages_for('scripts/auto_chart_pack.py'),
                         {'figures','manuscript','qa'})
        self.assertEqual(stages_for('scripts/assemble_manuscript.py'),
                         {'manuscript','qa'})
        # the generic fallback still covers everything a step touches
        self.assertEqual(stages_for('scripts/'),set(self.value['rerunRules'][0]['stages']))
        self.assertEqual(stages_for('data/'),
                         {'audit','coding','dataset','verify','stats','figures',
                          'manuscript','qa'})
        # advisory tools keep their stage-local mapping even though their
        # outputs live under output/ directories with no machine consumer
        self.assertNotIn('dataset',stages_for('scripts/mine_candidates.py'))
        # late stages are never named by any rule (engine drives them itself)
        named=set()
        for rule in self.value['rerunRules']:
            named.update(rule['stages'])
        self.assertNotIn('recheck',named)
        self.assertNotIn('publish',named)

    def test_rerun_rules_match_the_owning_steps(self):
        """Every exact script rule is either a script some step/action runs
        (stages must cover its owners), a library imported by mapped scripts,
        or one of the pinned advisory tools; nothing invented."""
        import re
        owners={}
        for owner in self.value['stages']+self.value['actions']:
            for step in [owner]+owner.get('steps',[]):
                script=step.get('script')
                if script:
                    owners.setdefault(script,set()).add(
                        owner.get('stage') or owner['id'])
        advisory={'scripts/mine_candidates.py','scripts/suggest_profiles.py',
                  'scripts/check_decisions.py','scripts/sample_review.py',
                  'scripts/compute_kappa.py'}
        # imported libraries: no owning step, but mapped scripts import them
        imports={}
        for path in (PACKAGE/'scripts').glob('*.py'):
            text=path.read_text(encoding='utf-8',errors='replace')
            imports[path.name]=set(re.findall(r'^\s*(?:from|import)\s+([a-zA-Z_][\w]*)',
                                              text,re.M))
        libraries=set()
        for mapped in owners:
            key=Path(mapped).name
            seen,stack=set(),list(imports.get(key,()))
            while stack:
                dep=stack.pop()
                if dep in seen:
                    continue
                seen.add(dep)
                stack.extend(imports.get(f'{dep}.py',()))
                libraries.add(f'scripts/{dep}.py')
        for rule in self.value['rerunRules']:
            if rule['match']=='exact' and rule['pattern'].startswith('scripts/'):
                path=rule['pattern']
                self.assertTrue((PACKAGE/path).is_file(),f"{path} does not exist")
                if path in owners:
                    self.assertTrue(owners[path]<=set(rule['stages']),
                                    f"{path} drops an owning stage")
                elif path not in advisory and path not in libraries:
                    self.fail(f"{path} has no owning step and is not a "
                              f"documented advisory tool or imported library")

if __name__=='__main__':unittest.main()
