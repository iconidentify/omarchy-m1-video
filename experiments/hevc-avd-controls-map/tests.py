#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic coverage and packing regressions; no device."""
from __future__ import annotations

import hashlib
import json
import os
import copy
import tempfile
import unittest
from pathlib import Path

import inventory as inv
import scan
import validate

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


class Inventory(unittest.TestCase):
    def setUp(self):
        self.doc = inv.document()
        self.committed = json.loads((HERE / "inventory.json").read_text())

    def test_inventory_has_function_local_coverage(self):
        validate.check_inventory()

    def test_ids_unique_and_classes_known(self):
        ids = [f["id"] for f in self.doc["fields"]]
        self.assertEqual(len(ids), len(set(ids)))
        for row in self.doc["fields"]:
            self.assertIn(row["klass"], inv.CLASSES)
            self.assertIn(row["function"], scan.TARGETS)

    def test_does_not_treat_unknown_as_zero_measured(self):
        unknown = [f for f in self.doc["fields"] if f["klass"] == "missing_runtime_input"]
        self.assertGreater(len(unknown), 10)
        for row in unknown:
            note = (row.get("note") or "") + row["derivation"]
            self.assertNotIn("measured zero", note.lower())

    def test_already_measured_is_only_the_reference_subset(self):
        measured = {f["id"] for f in self.doc["fields"] if f["klass"] == "already_measured"}
        self.assertTrue(measured >= {
            "slice0.type_intra", "dqtblk.ref_lists", "entry_points", "run.num_slices",
            "slice.dependent",
        })
        self.assertNotIn("qp.slice", measured)
        self.assertNotIn("scaling.list_4x4", measured)
        self.assertNotIn("weights.enable", measured)
        self.assertNotIn("header.decomp", measured)
        self.assertNotIn("sps.width_height", measured)


class SourceScan(unittest.TestCase):
    def source(self):
        path=os.environ.get('HEVC_AVD_HEVC_C')
        if not path:self.skipTest('source verification runs this in CI')
        return Path(path)

    def test_optional_patched_source_has_no_unaccounted_reads(self):
        leftover = validate.compare_source(self.source(), inv.document()["fields"])
        self.assertEqual(leftover, {}, leftover)

    def test_same_member_in_other_function_cannot_cover_missing_use(self):
        fields=[r for r in inv.document()['fields'] if not
                (r['function']=='set_header' and r['member']=='pic_width_in_luma_samples')]
        self.assertIn('set_header',validate.compare_source(self.source(),fields))

    def test_changed_source_hash_and_added_read_or_call_fail(self):
        source=self.source().read_text()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'changed.c'
            for extra in ('sps->unexpected_control;', 'new_helper(ctx);',
                          'sl->pred_weight_table.unexpected_nested;', 'pps->flags;'):
                # Alter just the named set_header body; known flags elsewhere
                # cannot excuse another control owner appearing here.
                text=source.replace('u32 bytesperline;','u32 bytesperline;\n'+extra,1)
                p.write_text(text)
                with self.assertRaises(ValueError):validate.compare_source(p,inv.FIELDS)
                self.assertTrue(validate.compare_source(p,inv.FIELDS,check_hash=False))

    def test_function_boundary_does_not_consume_next_public_definition(self):
        source=self.source().read_text()+'\nint unrelated(void) { return sps->invented; }\n'
        self.assertEqual(scan.coverage(source),scan.coverage(self.source().read_text()))


class Packing(unittest.TestCase):
    def setUp(self):
        self.out = validate.compile_packing()

    def test_scaling_dims_literal(self):
        self.assertIn("SCL 0127ffff", self.out)

    def test_qp_zero_offsets_are_not_a_measured_default(self):
        line = [ln for ln in self.out.splitlines() if ln.startswith("QPZERO ")][0]
        word = int(line.split()[1], 16)
        self.assertEqual(word, 0x2d906800)
        self.assertEqual(word >> 20, 0x2d9)
        self.assertEqual((word >> 10) & 0xff, 26)

    def test_signed_qp_offsets_use_field_prep_low_bits(self):
        lines = {int(ln.split()[1]): int(ln.split()[2], 16)
                 for ln in self.out.splitlines() if ln.startswith("QPOFF ")}
        self.assertIn(-12, lines)
        self.assertIn(12, lines)
        # Negative values must not vanish to the unsigned 26/0/0 word.
        for off,word in lines.items():
            self.assertEqual(word,0x2d900000 | (26<<10) | ((off&31)<<5) | ((-off)&31))

    def test_deblock_flag_en_overlaps_off1_bit16(self):
        line = [ln for ln in self.out.splitlines() if ln.startswith("DBLK_OVERLAP_MASK ")][0]
        mask = int(line.split()[1], 16)
        self.assertEqual(mask, 1 << 16)
        for line in self.out.splitlines():
            if line.startswith('DBLK '):
                _,value,word=line.split();off=int(value)
                self.assertEqual(int(word,16),0x2da00000|((off&15)<<8)|((off&31)<<12)|(1<<16))

    def test_weight_and_offset_signed_values_survive_pack(self):
        wts = {int(ln.split()[1]): int(ln.split()[2], 16)
               for ln in self.out.splitlines() if ln.startswith("WT ")}
        for delta,word in wts.items():self.assertEqual(word,0x2de04000|((delta+64)&511))
        # Signed offsets use all 16 low bits, not the 9-bit weight field.
        offs = {int(ln.split()[1]): int(ln.split()[2], 16)
                for ln in self.out.splitlines() if ln.startswith("OFF ")}
        for offset,word in offs.items():self.assertEqual(word,0x2df00000|(offset&65535))


class Pins(unittest.TestCase):
    def test_source_map_pins(self):
        doc = json.loads((HERE / "source-map.json").read_text())
        self.assertEqual(doc["kernel_revision"], "94fb23346d522edf53722357c426a3e58030beea")
        self.assertTrue(doc["patches"]["concatenated_sha256"].startswith("029f57377a00"))
        self.assertEqual(doc["patched_avd_hevc_c"]["sha256"],
                         "417cd4c0d39957ab6a281b706acb298c08e5132888e8cad2a6edf5d2673824f9")
        self.assertEqual(doc["campaign"]["summary_sha256"],
                         "f6fbc2f5c3bf0337d8279d7e3a60cf8e1c3fcab50b3dce6d2963e2d101a9ca9e")

    def test_repo_patch_concat_still_matches(self):
        manifest = json.loads((REPO / "experiments/hevc-avd-trace/sources.json").read_text())
        blobs = b"".join((REPO / item["path"]).read_bytes() for item in manifest["patches"]["files"])
        self.assertEqual(hashlib.sha256(blobs).hexdigest(),
                         manifest["patches"]["concatenated_sha256"])

    def test_public_window_does_not_invent_qp(self):
        facts = validate.public_window_facts()
        self.assertEqual(facts["E28"]["type"], "I")
        self.assertIn("qp", facts["unknown"])
        self.assertIn("scaling", facts["unknown"])


class Decision(unittest.TestCase):
    def test_readme_and_next_observation(self):
        readme = (HERE / "README.md").read_text()
        nxt = (HERE / "next-observation.md").read_text()
        self.assertIn("#67", readme + nxt)
        self.assertIn("ioctl", readme.lower() + nxt.lower())
        self.assertIn("CRA", nxt)
        self.assertIn("RPS_E", nxt)
        self.assertNotIn("Fixes https://github.com/iconidentify/libva-v4l2_request/issues/42", readme)
        self.assertIn("decoded_frame_evidence=false", readme)
