#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline admission tests. Full ffmpeg link is build.py."""
from pathlib import Path
import subprocess
import unittest

HERE = Path(__file__).resolve().parent


class Patch(unittest.TestCase):
    def test_no_baseline_extended_map(self):
        patch = (HERE / 'ffmpeg-n9.0.1-h264-vaapi-admission.patch').read_text()
        self.assertNotIn('H264_BASELINE', patch)
        self.assertNotIn('H264_EXTENDED', patch)
        self.assertIn('ff_h264_vaapi_admit_reject', patch)
        self.assertIn('internal.h', (HERE / 'h264_vaapi_admit.c').read_text())

    def test_dpa_uses_real_nal_macros(self):
        patch = (HERE / 'ffmpeg-n9.0.1-h264-vaapi-admission.patch').read_text()
        self.assertIn('H264_NAL_DPB', patch)
        self.assertIn('H264_NAL_DPC', patch)
        self.assertIn('ff_h264_vaapi_admit_reject', patch)

    def test_end_gate(self):
        subprocess.run(['python3', str(HERE / 'end-gate-test.py')], check=True, timeout=30)

    def test_readme_keeps_remap_disabled(self):
        text = (HERE / 'README.md').read_text().lower()
        self.assertIn('remap stays disabled', text)
        self.assertIn('explicit stop', text)
        self.assertNotIn('fixes https://github.com/iconidentify/libva-v4l2_request/issues/37', text)


if __name__ == '__main__':
    unittest.main()
