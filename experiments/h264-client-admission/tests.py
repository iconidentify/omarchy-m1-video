#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline admission tests. Full ffmpeg link and parser harness are build.py."""
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
SELECTION = HERE.parent / 'h264-client-selection'


class Patch(unittest.TestCase):
    def test_no_baseline_extended_map(self):
        patch = (HERE / 'ffmpeg-n9.0.1-h264-vaapi-admission.patch').read_text()
        self.assertNotIn('H264_BASELINE', patch)
        self.assertNotIn('H264_EXTENDED', patch)
        self.assertIn('ff_h264_vaapi_admit_reject', patch)
        self.assertIn('internal.h', (HERE / 'h264_vaapi_admit.c').read_text())

    def test_dpa_uses_real_nal_macros(self):
        patch = (HERE / 'ffmpeg-n9.0.1-h264-vaapi-admission.patch').read_text()
        self.assertIn('ff_h264_vaapi_admit_nal', patch)
        self.assertIn('ff_h264_vaapi_admit_is_active', patch)
        self.assertIn('ff_h264_vaapi_admit_reject', patch)

    def test_readme_keeps_remap_disabled(self):
        text = (HERE / 'README.md').read_text().lower()
        self.assertIn('remap stays disabled', text)
        self.assertIn('explicit stop', text)
        self.assertNotIn('fixes https://github.com/iconidentify/libva-v4l2_request/issues/37', text)

    def test_parser_harness_uses_actual_dispatch(self):
        harness = (HERE / 'parser-harness.c').read_text()
        self.assertIn('decode_nal.inc', harness)
        self.assertNotIn('h264_va_on_nal', harness)
        patch = (HERE / 'ffmpeg-n9.0.1-h264-vaapi-admission.patch').read_text()
        self.assertIn('ff_h264_vaapi_admit_nal', patch)
        self.assertIn('#include "config_components.h"', harness)

    def test_slice_queue_harness_executes_real_queue(self):
        harness = (HERE / 'slice-queue-harness.c').read_text()
        self.assertIn('queue.inc', harness)
        self.assertIn('header_parse.inc', harness)
        self.assertIn('field_end.inc', harness)
        self.assertIn('end_frame.inc', harness)
        self.assertIn('flush.inc', harness)
        self.assertIn('decode_frame.inc', harness)
        self.assertNotIn('static int finish_frame(', harness)
        self.assertNotIn('(void)nal; /* Deliberately does not parse', harness)
        patch = (HERE / 'ffmpeg-n9.0.1-h264-vaapi-admission.patch').read_text()
        self.assertIn('FF_HW_SIMPLE_CALL(avctx, end_frame)', patch)
        readme = (HERE / 'README.md').read_text().lower()
        self.assertIn('config/thread', readme)
        self.assertIn('remap stays disabled', readme)

    def test_rejected_pr74_reproductions_still_block(self):
        for script in ('tests.py', 'actual-gate-test.py'):
            result = subprocess.run([sys.executable, str(SELECTION / script)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
