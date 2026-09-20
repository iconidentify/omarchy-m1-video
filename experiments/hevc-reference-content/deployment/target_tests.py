#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""No-device tests for deterministic target and capacity derivation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import derive_targets as d

HERE = Path(__file__).resolve().parent
ASSOCIATIONS = HERE.parent.parent / "hevc-controls/captures/2026-09-17/associations"


def trace(pool_size: int) -> list[dict]:
    return [{
        "ioctl": "VIDIOC_CREATE_BUFS",
        "from_userspace": {"v4l2_create_buffers": {"count": 1}},
        "from_driver": {"v4l2_create_buffers": {
            "count": 1, "index": index,
            "format": {"type": "V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE"},
        }},
    } for index in range(pool_size)]


def stream(*nal_types: int) -> bytes:
    return b"".join(b"\x00\x00\x00\x01" + bytes((value << 1, 1))
                    for value in nal_types)


class Targets(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hevc-targets-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.traces = {}
        self.streams = {}
        for vector in ("B", "E"):
            path = root / f"{vector}.json"
            path.write_text(json.dumps(trace(19)))
            self.traces[vector] = path
            bitstream = root / f"{vector}.bit"
            bitstream.write_bytes(stream(32, 33, 34, 19, 1, 1))
            self.streams[vector] = bitstream

    def test_locked_targets_and_reserve_capacity(self):
        value = d.derive(ASSOCIATIONS, self.traces, self.streams)
        targets = {(row["client"], row["vector"]): row for row in value["targets"]}
        self.assertEqual(targets[("gst", "B")]["selectors"], [24])
        self.assertEqual(targets[("gst", "B")]["gst_pool_size"], 20)
        self.assertEqual(targets[("gst", "E")]["selectors"], [31, 28, 32])
        self.assertEqual(targets[("gst", "E")]["gst_pool_size"], 22)
        self.assertEqual(targets[("va", "B")]["selectors"], [20])
        self.assertEqual(targets[("va", "E")]["selectors"], [31, 73, 74])
        self.assertEqual(targets[("va", "E")]["last_input"], 80)

    def test_noncontiguous_pool_is_refused(self):
        value = trace(19)
        value[-1]["from_driver"]["v4l2_create_buffers"]["index"] = 20
        self.traces["E"].write_text(json.dumps(value))
        with self.assertRaisesRegex(d.TargetError, "contiguous"):
            d.derive(ASSOCIATIONS, self.traces, self.streams)

    def test_association_drift_is_refused(self):
        root = Path(self.temporary.name) / "associations"
        root.mkdir()
        for path in ASSOCIATIONS.iterdir():
            if path.suffix == ".json":
                (root / path.name).write_bytes(path.read_bytes())
        changed = root / "E-gst.json"
        value = json.loads(changed.read_text())
        value[0] = copy.deepcopy(value[0])
        value[0]["pic"] += 1
        changed.write_text(json.dumps(value))
        with self.assertRaisesRegex(d.TargetError, "hash drift"):
            d.derive(root, self.traces, self.streams)

    def test_in_band_parameter_set_is_refused(self):
        self.streams["E"].write_bytes(stream(32, 33, 34, 19, 33, 1))
        with self.assertRaisesRegex(d.TargetError, "in-band parameter-set"):
            d.derive(ASSOCIATIONS, self.traces, self.streams)


if __name__ == "__main__":
    unittest.main(verbosity=2)
