#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Mutated published-evidence tests; no hardware, raw trace or media input."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('campaign', HERE / 'campaign-report.py')
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'capture'
        shutil.copytree(campaign.DEFAULT, self.root)

    def alter(self, name, change, jsonl=False):
        path = self.root / name
        if jsonl:
            data = campaign.rows(path); change(data)
            path.write_text(''.join(json.dumps(r) + '\n' for r in data))
        else:
            data = campaign.read(path); change(data)
            path.write_text(json.dumps(data) + '\n')
        # Deliberately recompute the digest: tests must reach semantic checks.
        index = campaign.read(self.root / 'data-files.json')
        index[name] = campaign.digest(path)
        (self.root / 'data-files.json').write_text(json.dumps(index) + '\n')

    def reject(self):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            campaign.summarize(self.root)

    def test_complete_campaign_reproduces_summary(self):
        self.assertEqual(campaign.summarize(self.root), campaign.read(self.root / 'summary.json'))

    def test_missing_workload(self):
        self.alter('runs.json', lambda runs: runs.pop())
        self.reject()

    def test_tracing_changed_pixel(self):
        self.alter('frames/B-va-on.json', lambda rows: rows[0].__setitem__(1, '0' * 32))
        self.reject()

    def test_guard_timeout_is_not_a_postprocessing_exception(self):
        self.alter('guards/B-va-on.jsonl', lambda rows: rows[-1].__setitem__('timed_out', True), True)
        self.reject()

    def test_original_failure_cannot_be_erased(self):
        self.alter('guards/B-va-on.jsonl', lambda rows: rows[-1].update(status='ok', returncode=0), True)
        self.reject()

    def test_other_child_errors_are_not_excused(self):
        self.alter('guards/B-gst-on.jsonl', lambda rows: rows[-1].update(status='child-error', returncode=1), True)
        self.reject()

    def test_incomplete_kernel_history(self):
        self.alter('kernel/E-gst-on.jsonl', lambda rows: rows.pop(), True)
        self.reject()

    def test_changed_emitted_command(self):
        def mutate(rows):
            row = next(r for r in rows if r['kind'] == 5 and r['picture'] == 29)
            row['word'] ^= 1 << 18
        self.alter('kernel/E-gst-on.jsonl', mutate, True)
        self.reject()

    def test_future_normalized_reference(self):
        def mutate(rows):
            row = next(r for r in rows if r['kind'] == 3 and r['picture'] == 29)
            row['requested_timestamp_writer'] = 300
            row['requested_timestamp_writer_candidates'] = [300]
        self.alter('kernel/E-gst-on.jsonl', mutate, True)
        self.reject()

    def test_wrong_output_association(self):
        self.alter('associations/E-gst-on.json', lambda rows: rows[26].__setitem__('poc', 999))
        self.reject()

    def test_wrong_same_run_source(self):
        self.alter('kernel-meta.json', lambda data: data['E-gst-on'].__setitem__('raw_sha256', data['B-gst-on']['raw_sha256']))
        self.reject()

    def test_failed_restoration(self):
        self.alter('provenance.json', lambda data: data['restoration'].__setitem__('loaded_build_id_matches', False))
        self.reject()


if __name__ == '__main__':
    unittest.main(verbosity=2)
