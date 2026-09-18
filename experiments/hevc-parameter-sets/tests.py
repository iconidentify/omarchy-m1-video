#!/usr/bin/env python3
"""Unit tests for hevcnal.py. No FFmpeg, encoder, media or device needed."""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import hevcnal as nal  # noqa: E402

# Parameter sets written by x265 4.3 for a 176x144 Main stream (synthetic).
VPS = bytes.fromhex("40010c01ffff01600000030090000003000003003c959809")
SPS = bytes.fromhex("42010101600000030090000003000003003ca0162024596566924caf"
                    "016808000003000800000300c840")
PPS = bytes.fromhex("4401c172b42240")


def hand_sps(vps_id, sps_id):
    """Build an SPS prefix by hand: ids, one sub-layer, all-zero PTL, then filler."""
    bits = nal.u_bits(vps_id, 4) + nal.u_bits(0, 3) + [1] + [0] * 96
    bits += nal.ue_bits(sps_id) + nal.ue_bits(1) + [1, 0, 1, 1, 0]
    b = nal.Bits(b"\x80")
    b.bits = bits
    return b"\x42\x01" + nal.escape(b.to_rbsp())


class Escaping(unittest.TestCase):
    def test_round_trip(self):
        for rbsp in (b"\x00\x00\x00", b"\x00\x00\x01\x00\x00\x02", b"\x00\x00\x03\x00",
                     bytes(range(8)) * 3, b"\x00" * 9 + b"\x01"):
            ebsp = nal.escape(rbsp)
            self.assertNotIn(b"\x00\x00\x00", ebsp)
            self.assertNotIn(b"\x00\x00\x01", ebsp)
            self.assertNotIn(b"\x00\x00\x02", ebsp)
            self.assertEqual(nal.unescape(ebsp), rbsp)

    def test_annexb_split_join(self):
        stream = nal.join_annexb([VPS, SPS, PPS])
        self.assertEqual(nal.split_annexb(stream), [VPS, SPS, PPS])
        three_byte = b"\x00\x00\x01" + VPS + b"\x00\x00\x01" + PPS
        self.assertEqual(nal.split_annexb(three_byte), [VPS, PPS])


class Ids(unittest.TestCase):
    def test_encoder_ids(self):
        self.assertEqual(nal.nal_type(VPS), nal.HEVC_NAL_VPS)
        self.assertEqual(nal.vps_ids(VPS), {"vps_id": 0})
        self.assertEqual(nal.sps_ids(SPS), {"vps_id": 0, "sps_id": 0})
        self.assertEqual(nal.pps_ids(PPS), {"pps_id": 0, "sps_id": 0})

    def test_exp_golomb(self):
        for v in (0, 1, 2, 3, 6, 7, 15, 63, 1000):
            b = nal.Bits(b"\x80")
            b.bits = nal.ue_bits(v) + [1]
            self.assertEqual(b.ue(), v)

    def test_rewrites_change_only_ids(self):
        for vps_id, sps_id in ((3, 5), (15, 15), (1, 0), (0, 9)):
            new = nal.set_sps_ids(SPS, vps_id=vps_id, sps_id=sps_id)
            self.assertEqual(nal.sps_ids(new), {"vps_id": vps_id, "sps_id": sps_id})
            back = nal.set_sps_ids(new, vps_id=0, sps_id=0)
            self.assertEqual(back, SPS)
        self.assertEqual(nal.vps_ids(nal.set_vps_id(VPS, 7)), {"vps_id": 7})
        self.assertEqual(nal.set_vps_id(nal.set_vps_id(VPS, 7), 0), VPS)
        pps = nal.set_pps_id(nal.set_pps_sps_id(PPS, 12), 40)
        self.assertEqual(nal.pps_ids(pps), {"pps_id": 40, "sps_id": 12})
        self.assertEqual(nal.set_pps_id(nal.set_pps_sps_id(pps, 0), 0), PPS)

    def test_invalid_field_rewrites(self):
        sps = nal.set_sps_chroma_format_idc(nal.set_sps_ids(SPS, sps_id=9), 4)
        self.assertEqual(nal.sps_ids(sps), {"vps_id": 0, "sps_id": 9})
        self.assertEqual(nal.set_sps_chroma_format_idc(
            nal.set_sps_chroma_format_idc(SPS, 4), 1), SPS)
        pps = nal.set_pps_num_ref_idx_l0_minus1(nal.set_pps_sps_id(PPS, 9), 15)
        self.assertEqual(nal.pps_ids(pps), {"pps_id": 0, "sps_id": 9})
        b = nal._payload(pps)
        b.ue(), b.ue(), b.u(7)
        self.assertEqual(b.ue(), 15)

    def test_payload_bit_edits(self):
        cut = nal.drop_payload_bits(SPS, 1)
        self.assertEqual(len(nal._payload(cut).bits), len(nal._payload(SPS).bits) - 1)
        self.assertEqual(nal.sps_ids(cut), nal.sps_ids(SPS))
        padded = nal.pad_payload(PPS, 100)
        self.assertEqual(len(nal._payload(padded).bits), len(nal._payload(PPS).bits) + 800)
        self.assertEqual(nal.pps_ids(padded), nal.pps_ids(PPS))
        with self.assertRaises(ValueError):
            nal.drop_payload_bits(PPS, 1000)

    def test_empty_extensions(self):
        ext = nal.set_sps_empty_extensions(SPS)
        self.assertEqual(nal._payload(ext).bits[-9:], [1] + [0] * 8)
        self.assertEqual(nal._payload(ext).bits[:-9], nal._payload(SPS).bits[:-1])

    def test_hand_built_sps(self):
        for vps_id, sps_id in ((0, 0), (9, 14)):
            self.assertEqual(nal.sps_ids(hand_sps(vps_id, sps_id)),
                             {"vps_id": vps_id, "sps_id": sps_id})

    def test_truncation_keeps_stop_bit(self):
        cut = nal.truncate_rbsp(SPS, 14)
        self.assertEqual(cut[:2], SPS[:2])
        self.assertEqual(nal.unescape(cut[2:])[-1], 0x80)
        self.assertEqual(nal.sps_ids(cut), {"vps_id": 0, "sps_id": 0})

    def test_rejects_malformed(self):
        with self.assertRaises(ValueError):
            nal.Bits(b"\x00\x00")
        with self.assertRaises(ValueError):
            nal.sps_ids(SPS[:6])
        with self.assertRaises(ValueError):
            nal.set_vps_id(VPS, 16)
        with self.assertRaises(ValueError):
            nal.ue_bits(-1)
        multi_layer = b"\x42\x01" + nal.escape(bytes([0x0E, 0x80]))
        with self.assertRaises(ValueError):
            nal.sps_ids(multi_layer)


class SuiteGate(unittest.TestCase):
    def test_crashed_decoder_is_not_a_pass(self):
        import hashlib
        import os
        import tempfile
        import run

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "S" / "V").mkdir(parents=True)
            (tmp / "S" / "V" / "v.bin").write_bytes(b"input")
            suite = {"name": "S", "test_vectors": [{
                "name": "V", "input_file": "v.bin", "output_format": "yuv420p",
                "result": hashlib.md5(b"frame").hexdigest()}]}
            (tmp / "suite.json").write_text(json.dumps(suite))
            scripts = {}
            for name, tail in (("ok", "exit 0"), ("crash", "kill -SEGV $$")):
                path = tmp / name
                path.write_text('#!/bin/sh\nfor a; do out=$a; done\n'
                                f'printf frame > "$out"\n{tail}\n')
                os.chmod(path, 0o755)
                scripts[name] = str(path)
            report, failures = run.run_suite(scripts["ok"], scripts["crash"],
                                             tmp / "suite.json", tmp, ["single"])
        row = report["vectors"]["V"]
        self.assertTrue(row["base_single"]["pass"])
        self.assertNotEqual(row["fixed_single"]["rc"], 0)
        self.assertFalse(row["fixed_single"]["pass"])
        self.assertEqual(report["summary"]["single"]["regressions"], ["V"])
        self.assertTrue(failures)


class Pins(unittest.TestCase):
    def test_source_json(self):
        import hashlib
        src = json.loads((HERE / "source.json").read_text())
        patch = (HERE / src["patch"]["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(patch).hexdigest(), src["patch"]["sha256"])
        self.assertRegex(src["ffmpeg"]["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(len(src["vector"]["dims"]), 6)
        build = (HERE / "build-ffmpeg.sh").read_text()
        self.assertIn(src["ffmpeg"]["commit"], build)

    def test_patch_scope(self):
        src = json.loads((HERE / "source.json").read_text())
        patch = (HERE / src["patch"]["file"]).read_text()
        files = sorted(l.split(" b/")[1] for l in patch.splitlines() if l.startswith("diff --git"))
        self.assertEqual(files, ["libavcodec/hevc/hevcdec.c", "libavcodec/hevc/hevcdec.h",
                                 "libavcodec/hevc/parser.c", "libavcodec/hevc/ps.c",
                                 "libavcodec/hevc/ps.h"])
        build = (HERE / "build-ffmpeg.sh").read_text()
        for flag in ("--enable-vaapi", "--enable-libdrm", "hwaccel"):
            self.assertNotIn(flag, build)


if __name__ == "__main__":
    unittest.main(verbosity=2)
