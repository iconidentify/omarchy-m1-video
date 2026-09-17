#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline rejection tests against copies of the public capture metadata."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import report

ROOT = Path(__file__).parent / 'captures' / '2026-09-17'
CHECKER = os.environ.get('HEVC_REFTRACE_CHECKER')


@unittest.skipUnless(CHECKER, 'set HEVC_REFTRACE_CHECKER to run capture evidence checks')
class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'capture'
        shutil.copytree(ROOT, self.root)

    def change(self, name, mutate):
        path = self.root / name
        obj = json.loads(path.read_text())
        mutate(obj)
        path.write_text(json.dumps(obj))

    def rejected(self):
        with self.assertRaises((ValueError, KeyError)):
            report.summarize(self.root, CHECKER)

    def test_published_summary(self):
        self.assertEqual(report.summarize(self.root, CHECKER), report.read(self.root / 'summary.json'))

    def test_wrong_hash_with_adjusted_wrong_set(self):
        def edit(obj):
            # A locally consistent run must still fail its trace-off/on comparison.
            obj['runs'][1]['frame_md5'][0] = '0' * 32
            obj['runs'][1]['wrong_indices'] = [0]
        self.change('results.json', edit)
        self.rejected()

    def test_duplicate_run_cannot_replace_missing_capture(self):
        self.change('results.json', lambda o: o['runs'].__setitem__(1, o['runs'][0]))
        self.rejected()

    def test_guard_failure(self):
        path = self.root / 'guards' / 'guard-B-va-off.jsonl'
        rows = [json.loads(s) for s in path.read_text().splitlines()]
        rows[-1]['status'] = 'aborted'
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        self.rejected()

    def test_swapped_output_association(self):
        def swap(rows):
            rows[0]['pic'], rows[1]['pic'] = rows[1]['pic'], rows[0]['pic']
        self.change('associations/E-gst.json', swap)
        self.rejected()

    def test_unselected_capture_cannot_supply_association(self):
        self.change('results.json', lambda o: o['selected'].__setitem__('E-gst', 'E-gst-on'))
        self.rejected()

    def test_mismatched_input(self):
        self.change('results.json', lambda o: o['runs'][0].__setitem__('input_sha256', '0' * 64))
        self.rejected()

    def test_optimized_python_does_not_skip_validation(self):
        self.change('results.json', lambda o: o['runs'][0].__setitem__('tracee_status', 1))
        result = subprocess.run([sys.executable, '-O', str(Path(report.__file__)),
                                 str(self.root), '--verify'], capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
