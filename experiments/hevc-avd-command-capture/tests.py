#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual subprocess lifecycle tests with fake recorder backends; no device."""
import copy
import json
import os
from pathlib import Path
import signal
import select
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from types import SimpleNamespace
import importlib.util

import capture
import compare
import campaign

class Fake:
    def __init__(self,name,events,marker,fail=None,context=55):
        self.name=name;self.events=events;self.marker=marker;self.fail=fail;self.context=context
        self.st=dict(run=0,context=0,phase=0,errors=0,pictures=0,completions=0,opens=0)
        self.calls=0
    def control(self,op):
        self.events.append((self.name,op.split()[0],self.marker.exists()))
        if op.startswith('arm '):
            assert not self.marker.exists(),'decoder ran before arm'
            if self.fail=='arm':raise OSError('injected arm failure')
            self.st.update(run=int(op.split()[1]),phase=1)
        elif op.startswith('seal '):
            if self.fail=='seal':raise OSError('injected seal failure')
            self.st.update(phase=4,context=self.context,pictures=300,completions=300,
                           errors=1 if self.fail=='late' else 0)
        elif op=='off':self.st=dict(run=0,context=0,phase=0,errors=0,pictures=0,completions=0,opens=0)
        else:raise ValueError(op)
    def status(self):
        self.calls+=1
        out=copy.deepcopy(self.st)
        if self.fail=='monitor' and self.calls==3:out['errors']=1
        return out
    def snapshot(self):
        if self.fail=='read':raise OSError('injected read failure')
        return ('synthetic '+self.name+' snapshot\n').encode()

class Supervision(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.marker=self.root/'decoder-started';self.events=[]
        self.backends={n:Fake(n,self.events,self.marker) for n in capture.PATHS}
        self.store=capture.Store(self.root/'run')
    def tearDown(self):self.tmp.cleanup()
    def cmd(self,extra=''):
        return [sys.executable,'-c',f'from pathlib import Path;import time,sys,os,signal;Path({str(self.marker)!r}).write_text("yes");'+extra]
    def run_it(self,extra='',enabled=True,deadline=3):
        return capture.supervise(self.cmd(extra),7,enabled,deadline,self.backends,self.store)
    def test_both_armed_before_exec_and_durable_before_clear(self):
        r=self.run_it('time.sleep(.05)')
        self.assertEqual(r['child_exit'],0);self.assertTrue(r['child_reaped']);self.assertFalse(r['errors'])
        self.assertTrue(self.marker.exists())
        self.assertTrue(all(not ran for _,op,ran in self.events if op=='arm'))
        stages=[e['stage'] for e in r['events']]
        self.assertLess(max(i for i,s in enumerate(stages) if s=='snapshot-persisted'),min(i for i,s in enumerate(stages) if s=='cleared'))
        self.assertEqual(set(r['snapshots']),set(capture.PATHS))
        self.assertEqual(json.loads((self.root/'run/execution.json').read_text()),r)
    def test_actual_nonzero_status_preserved(self):
        r=self.run_it('sys.exit(23)')
        self.assertEqual(r['child_exit'],23);self.assertTrue(r['child_reaped']);self.assertFalse(r['errors'])
        self.assertTrue(all(b.st['phase']==4 for b in self.backends.values()))
    def test_partial_arm_never_executes_or_clears_evidence(self):
        self.backends['command'].fail='arm';r=self.run_it()
        self.assertFalse(r['child_released']);self.assertFalse(self.marker.exists());self.assertTrue(r['child_reaped'])
        self.assertTrue(r['errors']);self.assertIn('reference',r['snapshots'])
        self.assertFalse(any(op=='off' for _,op,_ in self.events))
    def test_timeout_kills_and_reaps(self):
        r=self.run_it('time.sleep(10)',deadline=1)
        self.assertTrue(r['errors']);self.assertTrue(r['child_reaped']);self.assertLess(r['elapsed_seconds'],5)
        self.assertLess(r['child_exit'],0)
    def test_sticky_monitor_error_kills_child(self):
        self.backends['reference'].fail='monitor';r=self.run_it('time.sleep(10)')
        self.assertTrue(r['errors']);self.assertTrue(r['child_reaped']);self.assertLess(r['child_exit'],0)
    def test_late_error_keeps_both_snapshots(self):
        self.backends['command'].fail='late';r=self.run_it()
        self.assertEqual(r['child_exit'],0);self.assertTrue(r['errors']);self.assertEqual(len(r['snapshots']),2)
        self.assertFalse(any(op=='off' for _,op,_ in self.events))
    def test_one_reader_failure_preserves_other(self):
        self.backends['reference'].fail='read';r=self.run_it()
        self.assertTrue(r['errors']);self.assertIn('command',r['snapshots'])
    def test_paired_context_mismatch(self):
        self.backends['command'].context=56;r=self.run_it()
        self.assertTrue(r['errors']);self.assertFalse(any(op=='off' for _,op,_ in self.events))
    def test_off_mode_does_not_arm_or_snapshot(self):
        r=self.run_it(enabled=False)
        self.assertFalse(r['errors']);self.assertFalse(r['snapshots']);self.assertEqual(r['child_exit'],0)
        self.assertFalse(any(op=='arm' for _,op,_ in self.events))
    def test_existing_capture_is_not_overwritten(self):
        self.backends['reference'].st.update(run=6,phase=4);r=self.run_it()
        self.assertTrue(r['errors']);self.assertIsNone(r['child_pid']);self.assertFalse(self.marker.exists());self.assertEqual(self.events,[])
    def test_supervisor_signal_is_not_success(self):
        r=self.run_it('os.kill(os.getppid(),signal.SIGTERM);time.sleep(.05)')
        self.assertTrue(r['errors']);self.assertTrue(r['child_reaped'])
    def test_persistence_failure_after_fork_still_reaps(self):
        class BrokenStore:
            def event(self,result):
                if result['child_pid']:raise OSError('injected full disk')
            def snapshot(self,name,raw):raise OSError('injected full disk')
        r=capture.supervise(self.cmd(),7,True,3,self.backends,BrokenStore())
        self.assertTrue(r['errors']);self.assertTrue(r['child_reaped']);self.assertFalse(r['child_released'])
        self.assertFalse(self.marker.exists())

    def test_invalid_limits_before_fork(self):
        for deadline in (0,91):
            with self.assertRaises(ValueError):self.run_it(deadline=deadline)
        self.assertFalse(self.marker.exists())

    @unittest.skipUnless(hasattr(os,'pidfd_open'),'Linux pidfd lifecycle assertion')
    def test_parent_death_kills_released_decoder(self):
        script='''import capture,tests,pathlib,sys
root=pathlib.Path(sys.argv[1]);marker=root/'marker';events=[]
backends={n:tests.Fake(n,events,marker) for n in capture.PATHS}
capture.supervise([sys.executable,'-c',"import time;time.sleep(30)"],7,True,40,backends,capture.Store(root/'parent-death'))
'''
        p=subprocess.Popen([sys.executable,'-c',script,str(self.root)],cwd=Path(__file__).parent)
        child=None;fd=None
        try:
            until=time.monotonic()+5
            while time.monotonic()<until:
                path=self.root/'parent-death/execution.json'
                r=json.loads(path.read_text()) if path.exists() else {}
                if r.get('child_released'):
                    child=r['child_pid'];fd=os.pidfd_open(child);break
                time.sleep(.01)
            self.assertIsNotNone(fd,'decoder was not released')
            p.kill();p.wait(timeout=3)
            self.assertTrue(select.select([fd],[],[],3)[0],'decoder survived supervisor death')
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=3)
            if child:
                try:os.kill(child,signal.SIGKILL)
                except ProcessLookupError:pass
            if fd is not None:os.close(fd)

class ControlBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        here=Path(__file__).resolve().parent
        cls.flags=json.loads((here/'uapi-flags.json').read_text())
        cls.rows=[json.loads(line) for line in (here.parent/'hevc-full-controls/capture/E-va-controls.jsonl').read_text().splitlines()]
        cls.fixture=dict(pictures=[dict(picture=r['picture'],poc=r['poc'],target=r['target'],type=r['controls']['SLICE_PARAMS']['slice_type']) for r in cls.rows],
                         windows=[dict(picture=r['picture'],poc=r['poc'],controls=compare.parser.pack_controls(compare.copied_fields(r,cls.flags))) for r in cls.rows[23:34]])
    def test_full_window_binding(self):
        self.assertEqual(compare.compare(self.fixture,self.rows,self.flags),[])
    def test_every_copied_field_difference_is_visible(self):
        for kind,name,count in compare.parser.LAYOUT:
            fixture=copy.deepcopy(self.fixture);window=fixture['windows'][0]
            fields=compare.parser.unpack_controls(window['controls'])
            if kind=='BYTES':fields[name][0]^=1
            else:fields[name]^=1
            window['controls']=compare.parser.pack_controls(fields)
            findings=compare.compare(fixture,self.rows,self.flags)
            self.assertEqual([f['field'] for f in findings],[name])
    def test_history_and_missing_fields_fail_closed(self):
        for key in ('poc','target','picture'):
            rows=copy.deepcopy(self.rows);rows[250][key]+=1
            with self.assertRaises(ValueError):compare.compare(self.fixture,rows,self.flags)
        rows=copy.deepcopy(self.rows);rows[23]['controls']['SPS'].pop('flags')
        with self.assertRaises(KeyError):compare.compare(self.fixture,rows,self.flags)
    def test_unknown_flag_fails_closed(self):
        row=copy.deepcopy(self.rows[23]);row['controls']['SPS']['flags'].append('unknown')
        with self.assertRaises(ValueError):compare.copied_fields(row,self.flags)

class FailureEvidence(unittest.TestCase):
    def test_preserved_incident_and_false_restoration_mutation(self):
        here=Path(__file__).resolve().parent
        spec=importlib.util.spec_from_file_location('incident',here/'incident-report.py')
        report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)
        source=here/'failed-attempt-2026-09-17'
        result=report.summarize(source)
        self.assertEqual(result['decoder_workloads_started'],0)
        self.assertFalse(result['original_loaded_module_restored'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for p in source.iterdir():
                if p.is_file():(root/p.name).write_bytes(p.read_bytes())
            with (root/'campaign-events.jsonl').open('a') as f:f.write('{"event":"original-restored"}\n')
            with self.assertRaises(ValueError):report.summarize(root)

    def test_faulted_or_unloading_module_never_retried(self):
        for faults,initstate in ((['kernel Oops'],'live'),([], 'going')):
            c=campaign.Campaign.__new__(campaign.Campaign)
            c.record=mock.Mock();c.command=mock.Mock();c.identity=mock.Mock()
            state=SimpleNamespace(faults=faults,busy=False,wedged=False,module_loaded=True)
            c.backend=SimpleNamespace(state=lambda:state)
            with mock.patch.object(campaign.dataclasses,'asdict',return_value={}),mock.patch.object(Path,'read_text',return_value=initstate):
                with self.assertRaises(RuntimeError):c.restore()
            c.command.assert_not_called();c.identity.assert_not_called()

if __name__=='__main__':unittest.main()
