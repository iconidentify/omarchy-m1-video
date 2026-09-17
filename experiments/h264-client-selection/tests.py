#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build and run extracted H.264 VA selection callbacks. No device."""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cc(out, srcs, defines=None):
    cmd = ["cc", "-O0", "-Wall", "-Werror", "-o", str(out)]
    for d in defines or []:
        cmd.append("-D" + d)
    cmd += [str(HERE / s) for s in srcs]
    subprocess.run(cmd, check=True, timeout=30)


class Callbacks(unittest.TestCase):
    def test_extracted_callbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "tests"
            cc(binary, ["h264_vaapi_select.c", "tests.c"])
            out = subprocess.check_output([str(binary)], text=True, timeout=10)
            self.assertIn("PASS:", out)

    def test_removing_fmo_gate_submits_fmo(self):
        src = r'''
#include "h264_vaapi_select.h"
int main(void) {
    struct h264_va_session s = {0};
    struct h264_va_picture p = {.profile_idc=66,.frame_mbs_only=1,.chroma_format_idc=1,
        .slice_groups=2,.nal_unit_type=5,.slice_type=2,.parse_ok=1};
    if (h264_va_start_frame(&s, &p) || h264_va_end_frame(&s))
        return 2;
    return s.submitted == 1 ? 0 : 3;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "fmo.c").write_text(src)
            gated = t / "gated"
            ungated = t / "ungated"
            subprocess.run(["cc", "-O0", "-Wall", "-Werror", "-I", str(HERE),
                            str(HERE / "h264_vaapi_select.c"), str(t / "fmo.c"),
                            "-o", str(gated)], check=True, timeout=30)
            subprocess.run(["cc", "-O0", "-Wall", "-Werror", "-DH264_VA_SKIP_FMO",
                            "-I", str(HERE),
                            str(HERE / "h264_vaapi_select.c"), str(t / "fmo.c"),
                            "-o", str(ungated)], check=True, timeout=30)
            self.assertNotEqual(subprocess.run([str(gated)]).returncode, 0)
            self.assertEqual(subprocess.run([str(ungated)]).returncode, 0)


class Pins(unittest.TestCase):
    def test_source_map(self):
        text = (HERE / "source-map.json").read_text()
        self.assertIn("bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa", text)
        self.assertIn("b5deb8c319f4e53b5243bc0583fee1800e8faa42", text)
        self.assertTrue((HERE / "ffmpeg-n9.0.1-h264-vaapi-select.patch").exists())

    def test_prepare_applies_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ffmpeg"
            subprocess.run(["python3", str(HERE / "prepare.py"), str(dest)],
                           check=True, timeout=60)
            self.assertTrue((dest / "ident.json").exists())
            patched = (dest / "libavcodec/vaapi_h264.c").read_text()
            self.assertIn("h264_gate_sticky", patched)

    def test_decision_separates_oracle_and_hardware(self):
        d = (HERE / "README.md").read_text().lower()
        self.assertIn("explicit stop", d)
        self.assertIn("73/135", d)
        self.assertNotIn("fixes https://github.com/iconidentify/libva-v4l2_request/issues/37", d)


if __name__ == "__main__":
    unittest.main()
