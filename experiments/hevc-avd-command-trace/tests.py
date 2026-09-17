#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline command-trace tests. No device, no module load."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


class Core(unittest.TestCase):
    def test_sanitized_state_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "state"
            subprocess.run(
                ["cc", "-O0", "-g", "-fsanitize=address,undefined", "-Wall", "-Werror",
                 "-I", str(HERE / "kernel"),
                 str(HERE / "kernel/state-tests.c"), "-o", str(binary)],
                check=True, timeout=30)
            out = subprocess.check_output([str(binary)], text=True, timeout=10)
            self.assertIn("PASS:", out)


class Pins(unittest.TestCase):
    def test_trace_hooks_unchanged(self):
        src = json.loads((HERE / "sources.json").read_text())
        hooks = HERE.parent / "hevc-avd-trace" / "hooks.patch"
        self.assertEqual(hashlib.sha256(hooks.read_bytes()).hexdigest(),
                         src["trace_hooks_sha256"])
        manifest = json.loads((HERE.parent / "hevc-avd-trace" / "sources.json").read_text())
        blobs = b"".join((REPO / item["path"]).read_bytes() for item in manifest["patches"]["files"])
        self.assertEqual(hashlib.sha256(blobs).hexdigest(),
                         src["patches_concatenated_sha256"])

    def test_core_fits_2mib_with_history(self):
        text = (HERE / "kernel/cmd-core.h").read_text()
        self.assertIn("#define CMD_CONTROL 1392", text)
        self.assertIn("#define CMD_WORDS 1024", text)
        self.assertIn("#define CMD_WINDOW 11", text)


class Predictor(unittest.TestCase):
    def test_unknown_is_not_default_zero(self):
        from parser import predict_qp, MissingInput
        with self.assertRaises(MissingInput):
            predict_qp({})
        self.assertEqual(predict_qp({"init_qp_minus26": 0, "slice_qp_delta": 0,
                                     "pps_cb_qp_offset": 0, "pps_cr_qp_offset": 0,
                                     "slice_cb_qp_offset": 0, "slice_cr_qp_offset": 0}) >> 20,
                         0x2d9)

    def test_interior_scaling_corruption_is_visible(self):
        from parser import window_ok
        words = [{"site": 15, "word": 1}] * 10
        words[4] = {"site": 15, "word": 99}
        self.assertFalse(window_ok({"nwords": 10, "words": [w["word"] for w in words],
                                    "sites": [w["site"] for w in words],
                                    "expected": [1] * 10}))

    def test_skipped_weight_record_is_not_zero_word(self):
        from parser import classify_weights
        self.assertEqual(classify_weights({"inactive": 1 << 22, "nwords": 0}), "skipped")
        self.assertNotEqual(classify_weights({"inactive": 0, "nwords": 1,
                                              "sites": [22], "words": [0x2dd00000]}),
                            "skipped")


class Docs(unittest.TestCase):
    def test_capture_plan_and_limits(self):
        cap = (HERE / "CAPTURE.md").read_text()
        readme = (HERE / "README.md").read_text()
        self.assertIn("eight", cap.lower())
        self.assertIn("#71", cap)
        self.assertIn("does not authorize module load", readme.lower())
        self.assertNotIn("Fixes https://github.com/iconidentify/libva-v4l2_request/issues/42", readme)


if __name__ == "__main__":
    unittest.main()
