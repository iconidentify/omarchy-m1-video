#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline regression of actual qualification sequencing; no device or sudo."""
import tempfile
import subprocess
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import json
from qualify import Campaign, frames


class Simulated(Campaign):
    # Substitute host services only; execute the actual run/restore control flow.
    def __init__(self, root, failure=None):
        self.root=Path(root); self.c={'candidate':'candidate'}
        self.changed=False; self.restored=False; self.module='original'
        self.events=[]; self.calls=[]; self.failure=failure; self.fault=False
    def validate(self):
        self.calls.append('validate')
    def record(self,event,**data):
        self.events.append((event,data))
    def healthy(self,present=True):
        if self.fault: raise RuntimeError('hardware fault; no recovery')
        if present and self.module is None: raise RuntimeError('missing module')
        return SimpleNamespace(module_loaded=self.module is not None)
    def identity(self,which):
        if self.module!=which: raise RuntimeError('identity mismatch')
    def transition(self,*argv):
        self.calls.append(tuple(argv))
        if self.failure=='unload' and argv==('rmmod','apple_avd') and not self.changed:
            raise RuntimeError('unload refused')
        if self.failure=='load' and argv[0]=='insmod':
            raise RuntimeError('load failed')
        if argv[0]=='rmmod':self.module=None
        elif argv[0]=='insmod':self.module='candidate'
        elif argv[0]=='modprobe':self.module='original'
    def stage(self,name,module):
        self.identity(module);self.calls.append(name)
        if self.failure==name:raise RuntimeError('output mismatch')
        if self.failure=='fault' and name=='candidate':
            self.fault=True;raise RuntimeError('new fault')
        if self.failure=='identity' and name=='candidate':
            self.module='unknown';raise RuntimeError('identity changed')


class Sequencing(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def run_case(self,failure):
        c=Simulated(self.tmp.name,failure)
        if failure:
            with self.assertRaises(RuntimeError):c.run()
            self.assertFalse((c.root/'complete').exists())
        else:c.run()
        return c
    def test_success_exact_order(self):
        c=self.run_case(None)
        self.assertEqual(c.calls,['validate','baseline',('rmmod','apple_avd'),('insmod','candidate'),'candidate',('rmmod','apple_avd'),('modprobe','apple_avd'),'restored'])
        self.assertTrue(c.restored)
    def test_baseline_failure_never_changes_module(self):
        c=self.run_case('baseline');self.assertEqual(c.calls,['validate','baseline'])
    def test_unload_refusal_is_not_retried(self):
        c=self.run_case('unload');self.assertEqual(c.module,'original');self.assertFalse(c.changed)
        self.assertEqual(len([a for a in c.calls if isinstance(a,tuple)]),1)
    def test_absent_after_load_failure_restores_original_once(self):
        c=self.run_case('load');self.assertTrue(c.restored)
        self.assertEqual(c.calls.count(('modprobe','apple_avd')),1)
        self.assertNotIn('restored',c.calls)
    def test_mismatch_stops_jobs_but_restores_healthy_candidate(self):
        c=self.run_case('candidate');self.assertTrue(c.restored)
        self.assertNotIn('restored',c.calls)
    def test_fault_never_unloads_candidate(self):
        c=self.run_case('fault');self.assertEqual(c.module,'candidate');self.assertFalse(c.restored)
        self.assertEqual(c.calls.count(('rmmod','apple_avd')),1)
        self.assertNotIn(('modprobe','apple_avd'),c.calls)
    def test_unrecognized_module_is_never_unloaded(self):
        c=self.run_case('identity');self.assertEqual(c.module,'unknown')
        self.assertEqual(c.calls.count(('rmmod','apple_avd')),1)
    def test_restored_output_failure_cannot_report_complete(self):
        c=self.run_case('restored');self.assertTrue(c.restored)
        self.assertEqual(c.calls.count(('modprobe','apple_avd')),1)
    def test_fault_guard_source_mutation_is_rejected(self):
        src=Path(__file__).with_name('qualify.py').read_text()
        old='state = self.healthy(present=False)'
        self.assertEqual(src.count(old),1)
        root=Path(self.tmp.name)
        (root/'qualify.py').write_text(src.replace(old,"state = type('State', (), {'module_loaded': True})()"))
        (root/'tests.py').write_bytes(Path(__file__).read_bytes())
        p=subprocess.run(['python3',str(root/'tests.py'),'Sequencing.test_fault_never_unloads_candidate'],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('FAILED (failures=1)',p.stderr)
    def test_actual_output_comparison_rejects_wrong_hash(self):
        c=Simulated(self.tmp.name)
        c.c['environment']={}
        job=dict(name='wrong-output',kind='frames',argv=['mock-decoder'],count=1,expected=['a'*32])
        def fake_run(argv,**kw):
            kw['stdout'].write('frame 0 416x240 yuv420p '+'b'*32+'\nMD5='+'c'*32+'\n')
            kw['stdout'].flush()
            return SimpleNamespace(returncode=0)
        with patch('qualify.subprocess.run',side_effect=fake_run):
            with self.assertRaisesRegex(ValueError,'selected exact output changed'):
                c.execute('candidate',job)
        report=json.loads((c.root/'candidate/wrong-output/comparison.json').read_text())
        self.assertEqual(report['differences'],[0])
        self.assertFalse(any(e=='job-accepted' for e,_ in c.events))
    def test_frame_parser_rejects_partial_or_reordered_output(self):
        good='frame 0 416x240 yuv420p '+'a'*32+'\nMD5='+'b'*32+'\n'
        self.assertEqual(len(frames(good)),1)
        for bad in ('',good.replace('frame 0','frame 1'),good.split('MD5')[0],good+'MD5='+'c'*32+'\n'):
            with self.assertRaises(ValueError):frames(bad)


if __name__=='__main__':unittest.main(verbosity=2)
