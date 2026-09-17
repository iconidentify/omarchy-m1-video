#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""No-device layout and identity tests for HEVC compressed-reference memory."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CAPTURE = REPO / "experiments/hevc-avd-command-capture/capture-2026-09-17"


def run_layout(defines=None):
    with tempfile.TemporaryDirectory() as tmp:
        binary = Path(tmp) / "layout"
        cmd = ["cc", "-O0", "-Wall", "-Werror"]
        for d in defines or []:
            cmd.append("-D" + d)
        cmd += ["-o", str(binary), str(HERE / "layout-extracted.c")]
        subprocess.run(cmd, check=True, timeout=30)
        out = subprocess.check_output([str(binary)], text=True, timeout=10)
    vals = {}
    for line in out.splitlines():
        parts = line.split()
        vals[parts[0]] = parts[1:] if len(parts) > 2 else parts[1]
    return vals, out


class Layout(unittest.TestCase):
    def test_extracted_fill_comp_matches_published_records(self):
        vals, _ = run_layout()
        self.assertEqual(int(vals["start"]), 161280)
        self.assertEqual(int(vals["comp"]), 177152)
        self.assertEqual([int(vals[k]) for k in ("off0", "off1", "off2", "off3")],
                         [114688, 0, 176128, 118784])
        self.assertEqual(int(vals["mv"]), 7168)
        self.assertEqual(int(vals["gst_len"]), 345600)
        self.assertEqual(int(vals["gst_mv"]), 338432)
        self.assertEqual(int(vals["va_len"]), 368128)
        self.assertEqual(int(vals["va_mv"]), 360960)

    def test_picture28_records(self):
        for name, length, mv in (("E-va-on-reference.json", 368128, 360960),
                                 ("E-gst-on-reference.json", 345600, 338432)):
            recs = json.loads((CAPTURE / name).read_text())["records"]
            pic = next(r for r in recs if r["picture"] == 28 and r.get("kind") == 1)
            self.assertEqual(pic["poc"], 32)
            self.assertEqual(pic["width"], 448)
            self.assertEqual(pic["height"], 240)
            self.assertEqual(pic["comp_start"], 161280)
            self.assertEqual(pic["comp_size"], 177152)
            self.assertEqual(pic["length"], length)
            self.assertEqual(pic["mv_offset"], mv)
            self.assertEqual(pic["mv_size"], 7168)

    def test_mutating_tile_size_misses_published_offsets(self):
        vals, _ = run_layout(["TILE_Y=16"])
        self.assertNotEqual(int(vals["comp"]), 177152)
        self.assertNotEqual(int(vals["off0"]), 114688)

    def test_va_gap_is_plane_length_not_fill_comp(self):
        vals, _ = run_layout()
        self.assertEqual(int(vals["driver_mv_from_start_comp"]), 338432)
        self.assertGreater(int(vals["gap"]), 0)


class Docs(unittest.TestCase):
    def test_pins_and_decision(self):
        src = json.loads((HERE / "source-map.json").read_text())
        self.assertEqual(src["kernel_revision"], "94fb23346d522edf53722357c426a3e58030beea")
        self.assertTrue(src["patches_concatenated_sha256"].startswith("029f57377a00"))
        readme = (HERE / "README.md").read_text().lower()
        self.assertIn("not a proved bug", readme)
        self.assertIn("firmware", readme)
        self.assertNotIn("fixes https://github.com/iconidentify/libva-v4l2_request/issues/42", readme)


if __name__ == "__main__":
    unittest.main()
