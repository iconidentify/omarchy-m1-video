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

    def test_peak_allocation_is_explicit(self):
        text = (HERE / "kernel/cmd-core.h").read_text()
        self.assertIn("#define CMD_CONTROL 1392", text)
        self.assertIn("#define TRACE_CAPTURE_BYTES 1261568u", text)
        self.assertIn("PEAK_ALLOC_BYTES", text)
        self.assertNotIn("sizeof(struct cmd_capture) + 1261568u <= 2097152u",
                         (HERE / "kernel/avd-cmdtrace.c").read_text())


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
        from parser import classify_weights, CMD_SITE_WT_SKIP
        self.assertEqual(classify_weights({"inactive": 1 << (CMD_SITE_WT_SKIP % 32),
                                           "nwords": 0}), "skipped")
        self.assertNotEqual(classify_weights({"inactive": 1 << 22, "nwords": 1,
                                              "sites": [22], "words": [0x2dd00000]}),
                            "skipped")

    def test_unpack_rejects_short_and_predicts_from_named_fields(self):
        from parser import unpack_controls, predict_qp, MissingInput, CMD_PACKED
        with self.assertRaises(MissingInput):
            unpack_controls(bytes(10))
        buf = bytearray(CMD_PACKED)
        buf[34 + 4] = (-26) & 0xff  # init_qp_minus26 in PPS
        ctrl = unpack_controls(buf)
        self.assertEqual(ctrl["init_qp_minus26"], -26)
        self.assertEqual(predict_qp({
            "init_qp_minus26": -26, "slice_qp_delta": 0,
            "pps_cb_qp_offset": 0, "pps_cr_qp_offset": 0,
            "slice_cb_qp_offset": 0, "slice_cr_qp_offset": 0,
        }) >> 20, 0x2d9)

    def test_snapshot_parser_requires_version_and_300_history(self):
        from parser import parse_snapshot, MissingInput
        with self.assertRaises(MissingInput):
            parse_snapshot("H 2 0\n")
        with self.assertRaises(MissingInput):
            parse_snapshot("H 1 0 0 0 0 0 0 0 0 0 0 0 0\n")

    def test_reserved_pps_byte_is_not_in_packed_length(self):
        from parser import pack_le, CMD_PACKED
        fields = ([("u8", 0)] * 10 + [("bytes", bytes(20))] +
                  [("bytes", bytes(22))] + [("s8", 0), ("s8", 0), ("u8", 0),
                                            ("u64", 0)])
        pps = pack_le(fields)
        self.assertEqual(len(pps), 63)
        poison = bytes([0xaa])
        self.assertNotIn(poison, pps)
        self.assertEqual(CMD_PACKED, 34 + 63 + 1000 + 275 + 8)


class Docs(unittest.TestCase):
    def test_capture_plan_and_limits(self):
        cap = (HERE / "CAPTURE.md").read_text()
        readme = (HERE / "README.md").read_text()
        self.assertIn("eight", cap.lower())
        self.assertIn("#71", cap)
        self.assertIn("does not authorize module load", readme.lower())
        self.assertIn("PEAK_ALLOC", readme)
        self.assertNotIn("Fixes https://github.com/iconidentify/libva-v4l2_request/issues/42", readme)


if __name__ == "__main__":
    unittest.main()
