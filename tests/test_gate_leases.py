import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'empirical-research-pipeline/scripts'))
from gate_contract import atomic_json, read_json
from gate_lock import ProjectLease, LeaseConflict, recover


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_live_owner_never_stolen(self):
        with ProjectLease(self.root):
            with self.assertRaises(LeaseConflict):recover(self.root)

    def test_inherited_lease_remains_owned_by_host(self):
        with ProjectLease(self.root) as lease:
            with ProjectLease(self.root,lease.token):pass
            self.assertTrue(lease.path.exists())
        self.assertFalse(lease.path.exists())

    def test_wrong_token_rejected(self):
        with ProjectLease(self.root):
            with self.assertRaises(LeaseConflict):
                with ProjectLease(self.root,'wrong'):pass

    def test_dead_owner_with_live_child_not_recovered(self):
        lock=self.root/'output/gates/publication.lock'
        atomic_json(lock,{'pid':99999999,'hostname':socket.gethostname(),'children':[os.getpid()],'token':'old'})
        with self.assertRaises(LeaseConflict):recover(self.root)

    def test_dead_owner_marks_active_attempt_interrupted(self):
        atomic_json(self.root/'output/gates/publication.lock',{'pid':99999999,'hostname':socket.gethostname(),'children':[],'token':'old'})
        file=self.root/'output/gates/state/qa.json'
        atomic_json(file,{'stage':'qa','phase':'running','generation':4})
        self.assertEqual(['qa'],recover(self.root)['recovered'])
        self.assertEqual('interrupted',read_json(file)['phase'])

    def test_other_host_not_recovered(self):
        atomic_json(self.root/'output/gates/publication.lock',{'pid':99999999,'hostname':'another-host','children':[],'token':'old'})
        with self.assertRaises(LeaseConflict):recover(self.root)


if __name__=='__main__':unittest.main()
