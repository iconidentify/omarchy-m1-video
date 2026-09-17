#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
import copy
import json
from pathlib import Path
import unittest
import report

HERE=Path(__file__).resolve().parent


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.e=json.loads((HERE/'evidence.json').read_text())
        self.i=json.loads((HERE/'identities.json').read_text())
    def test_accepted_evidence(self):
        self.assertEqual(report.check(self.e,self.i)['decoded_frames'],5112)
    def test_semantic_mutations_fail(self):
        def output(e): e['results']['candidate']['E-va'][31]='0'*32
        def missing(e): del e['results']['restored']['vp9-10']
        def count(e): e['events'][-1]['frame_comparisons']=9999
        def fault(e): next(r for r in e['events'] if r['event']=='health')['faults']=['new fault']
        def transition(e): next(r for r in e['events'] if r['event']=='transition-result')['returncode']=1
        def note(e): e['final_loaded_note_hex']='00'
        def claim(e): e['retained_historical_wrong_indices']['E-va']=[]
        def guard(e): e['guard_result']['status']='abort'
        def early(e): e['early_export_checks']['candidate']=0
        def lease(e): e['events'][-1]['lease']='another-run'
        def stage(e): next(r for r in e['events'] if r['event']=='job-exit')['returncode']=1
        def pin(e): e['config_sha256']='0'*64
        for fn in (output,missing,count,fault,transition,note,claim,guard,early,lease,stage,pin):
            with self.subTest(mutation=fn.__name__):
                e=copy.deepcopy(self.e);fn(e)
                with self.assertRaises(AssertionError):report.check(e,self.i)


if __name__=='__main__':unittest.main(verbosity=2)
