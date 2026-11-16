"""Real mounted-material failures reduced to small known-answer fixtures."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'empirical-research-pipeline/scripts'
sys.path.insert(0, str(SCRIPTS))
from gate_contract import Inputs, atomic_json, read_json
from gate_facts import Facts, audit
from gate_roots import source_members
from research_gate import ResearchGate
from verify_dataset import Verifier
from dedupe_corpus import build_plan, safe_relpath
from review_pack import _figure_section, _verify_section


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'project'
        self.root.mkdir()

    def write(self, relative, value):
        file = self.root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(value) if isinstance(value, (dict, list)) else value, encoding='utf-8')
        return file

    def mount(self):
        external = self.base / 'external'
        external.mkdir()
        self.write('data/.keep', '')
        (self.root / 'data/.keep').unlink()
        link = self.root / 'data/mounted'
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(external)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(external, target_is_directory=True)
        self.write('.workbench/gates/roots.json', {'schema': 'dsa.gate-roots/1', 'roots': {'material:fixture': str(external)}})
        return external

    def test_mounted_read_plan_preserves_write_boundary(self):
        external = self.mount()
        for name in ['a.txt', 'b.txt']: (external / name).write_text('same', encoding='utf-8')
        digest = hashlib.md5(b'same').hexdigest()
        rows = [{'rel_path': 'mounted/' + name, 'dup_role': role, 'md5': digest}
                for name, role in [('a.txt', 'keeper'), ('b.txt', 'duplicate')]]
        plan, skipped = build_plan({'D1': rows}, str(self.root / 'data'), '_duplicates', False)
        self.assertEqual(skipped, 0)
        self.assertTrue(all(row['exists'] == 'yes' for row in plan))
        self.assertIsNone(safe_relpath('mounted/a.txt', str(self.root / 'data')))
        self.assertEqual((external / 'a.txt').read_text(), 'same')

    def test_unregistered_mount_and_traversal_are_still_detected(self):
        external = self.mount()
        (external / 'a.txt').write_text('raw')
        (self.root / '.workbench/gates/roots.json').unlink()
        with self.assertRaises(ValueError): source_members(self.root, self.root / 'data')

    def test_research_coverage_follows_registered_mount_and_detects_new_files(self):
        external = self.mount()
        source = external / 'a.txt'
        source.write_text('raw')
        self.write('output/audit/corpus_files.csv', 'rel_path,status\nmounted/a.txt,valid\n')
        self.write('output/coverage.jsonl', json.dumps({'source': 'mounted/a.txt', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'status': 'excluded', 'reason': 'outside research question'}) + '\n')
        self.write('output/discovery.md', 'Actual source reviewed; excluded.')
        registry = self.write('research_registry.json', {'datasets': [], 'source_root': 'data', 'source_inventory': 'output/audit/corpus_files.csv', 'source_coverage': 'output/coverage.jsonl', 'discovery_report': 'output/discovery.md'})
        gate = ResearchGate(registry, self.root)
        gate.source_coverage()
        self.assertEqual(gate.issues, [])
        (external / 'new.txt').write_text('new')
        gate = ResearchGate(registry, self.root)
        gate.source_coverage()
        self.assertTrue(any(issue['where'] == 'source_inventory' for issue in gate.issues))

    def test_dedupe_gate_uses_the_same_group_identity_as_producer(self):
        self.write('output/audit/corpus_summary.json', {'root': 'data'})
        self.write('output/audit/corpus_files.csv', 'rel_path,status,dup_group,dup_role,dedupe_group,dedupe_role\na,valid,G1,keeper,D1,keeper\nb,valid,G1,duplicate,D1,duplicate\n')
        self.write('output/audit/dedupe_plan.csv', 'group,rel_path,role,reason,action\nD1,a,keeper,kept,keep\nD1,b,duplicate,same,move\n')
        facts = Facts(Inputs(self.root), {})
        self.assertTrue(audit(facts, 'audit-dedupe')[0])
        self.write('output/audit/dedupe_plan.csv', 'group,rel_path,role,reason,action\nD1,a,keeper,missing,skip\nD1,b,duplicate,missing,skip\n')
        self.assertFalse(audit(Facts(Inputs(self.root), {}), 'audit-dedupe')[0])

    def test_custom_artifact_paths_bind_actual_resources_and_members(self):
        self.write('research_registry.json', {'artifact_paths': {'output/models': 'output/custom', 'output/qa/qa_report.json': 'output/quality'}})
        actual = self.write('output/custom/a.csv', 'id,value\na,2\n')
        self.write('output/quality', {'error_count': 0})
        inputs = Inputs(self.root)
        self.assertEqual(inputs.file('output/models/a.csv'), actual)
        self.assertEqual(inputs.collection('output/models'), ['output/custom/a.csv'])
        self.assertEqual(inputs.aliases['output/models/a.csv'], 'output/custom/a.csv')
        self.assertTrue(inputs.unchanged())
        actual.write_text('id,value\na,3\n')
        self.assertFalse(inputs.unchanged())

    def test_adapter_imported_project_code_is_bound_and_registry_selects_adapter(self):
        helper = self.write('local_recheck_helper.py', 'def read(): return 2\n')
        self.write('adapter.py', f'import sys\nsys.path.insert(0, {str(self.root)!r})\nimport local_recheck_helper\ndef read_source(path, loc): return local_recheck_helper.read()\n')
        registry = self.write('research_registry.json', {'verification': {'adapters': {'chosen': 'adapter.py'}}})
        verifier = Verifier(registry, self.root)
        self.assertIn('chosen', verifier.adapters)
        self.assertIn(str(helper.resolve()), verifier.bindings)
        old = verifier.bindings[str(helper.resolve())]
        helper.write_text('def read(): return 9\n')
        self.assertNotEqual(old, hashlib.sha256(helper.read_bytes()).hexdigest())
        sys.modules.pop('local_recheck_helper', None)

    def test_review_pack_accepts_directories_and_exposes_stale_final(self):
        self.write('figures/chart_manifest.csv', 'id,n,status\nF1,3,ok\n')
        source = self.write('codebook.md', 'old')
        snapshot = self.write('verification/snapshot.json', {'bindings': {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}})
        self.write('verification/dataset_verification.json', {'status': 'verified', 'cell_count': 3, 'error_count': 0, 'snapshot_path': str(snapshot)})
        self.assertEqual(_figure_section(str(self.root / 'figures'))['count'], 1)
        self.assertTrue(_verify_section(str(self.root / 'verification'))['current'])
        source.write_text('changed')
        self.assertFalse(_verify_section(str(self.root / 'verification'))['current'])

    def test_compact_report_preserves_all_evidence(self):
        file = self.root / 'report.json'
        value = {'resources': [{'path': '材料/' + str(i), 'value': i} for i in range(6000)]}
        atomic_json(file, value, compact=True)
        self.assertEqual(read_json(file), value)


if __name__ == '__main__': unittest.main()
