#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Mutate public evidence past the digest layer to exercise semantic checks."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import report


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'capture';shutil.copytree(report.DEFAULT,self.root)

    def alter(self,name,mutate,lines=False):
        p=self.root/name;data=report.read(p,lines);mutate(data)
        p.write_text(''.join(json.dumps(x)+'\n' for x in data) if lines else json.dumps(data)+'\n')
        files=report.read(self.root/'files.json');files[name]=report.digest(p)
        (self.root/'files.json').write_text(json.dumps(files)+'\n')

    def rejected(self):
        with self.assertRaises((ValueError,KeyError,TypeError)):report.summarize(self.root)

    def test_complete_campaign(self):
        self.assertEqual(report.summarize(self.root),report.read(self.root/'summary.json'))

    def test_guard_failure(self):
        self.alter('runs.json',lambda rows:rows[-1]['guard'][-1].update(timed_out=True));self.rejected()

    def test_wrong_pixels(self):
        self.alter('runs.json',lambda rows:rows[0]['frames_md5'].__setitem__(0,'0'*32));self.rejected()

    def test_mixed_raw_source(self):
        self.alter('runs.json',lambda rows:rows[-1].update(raw_sha256=rows[1]['raw_sha256']));self.rejected()

    def test_future_reference(self):
        self.alter('E-gst-controls.jsonl',lambda rows:rows[28]['controls']['DECODE_PARAMS']['dpb'][0].update(timestamp_writer=300),True);self.rejected()

    def test_returned_correction_mismatch(self):
        self.alter('E-va-controls.jsonl',lambda rows:rows[28]['input_changes'][0].update(returned=99),True);self.rejected()

    def test_different_encoded_input(self):
        self.alter('E-gst-input.json',lambda data:data['encoded_inputs'][28].update(sha256='0'*64));self.rejected()

    def test_additional_control_difference(self):
        self.alter('E-gst-controls.jsonl',lambda rows:rows[28]['controls']['SLICE_PARAMS'].update(slice_qp_delta=17),True);self.rejected()


if __name__=='__main__':unittest.main(verbosity=2)
