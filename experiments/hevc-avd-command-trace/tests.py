#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""No-device shared-core and strict input-domain tests."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import fixtures
import parser

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent

class Core(unittest.TestCase):
    def test_sanitized_state_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'state'
            subprocess.run(['cc','-O0','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                            '-Wall','-Werror','-I',str(HERE/'kernel'),str(HERE/'kernel/state-tests.c'),'-o',str(binary)],
                           check=True,timeout=30)
            subprocess.run([str(binary)],check=True,timeout=10)

    def test_accepted_sources_unchanged(self):
        pins=json.loads((HERE/'sources.json').read_text())
        self.assertEqual(hashlib.sha256((HERE.parent/'hevc-avd-trace/hooks.patch').read_bytes()).hexdigest(),pins['trace_hooks_sha256'])
        manifest=json.loads((HERE.parent/'hevc-avd-trace/sources.json').read_text())
        blobs=b''.join((REPO/item['path']).read_bytes() for item in manifest['patches']['files'])
        self.assertEqual(hashlib.sha256(blobs).hexdigest(),pins['patches_concatenated_sha256'])

class Controls(unittest.TestCase):
    def test_layout_and_roundtrip(self):
        self.assertEqual(sum(size for _,_,size in parser.LAYOUT),1380)
        for seed in range(32):
            raw=fixtures.row(seed)['controls'];ctrl=parser.unpack_controls(raw)
            self.assertEqual(parser.pack_controls(ctrl),raw)
            parser.validate_controls(ctrl)
        self.assertEqual(parser.unpack_controls(fixtures.row(0)['controls'])['pps_cb_qp_offset'],-6)

    def test_extent_and_padding(self):
        raw=fixtures.row()['controls']
        for bad in (raw[:-1],raw+bytes(1),raw[:-1]+b'\x01',list(raw)):
            with self.assertRaises(ValueError):parser.unpack_controls(bad)

    def test_unknown_missing_and_scalar_overflow(self):
        c=parser.unpack_controls(fixtures.row()['controls'])
        for bad in ({},dict(c,unknown=1),dict(c,pps_cb_qp_offset=-129),dict(c,bit_size=1<<32),dict(c,sps_flags=True)):
            with self.assertRaises(ValueError):parser.pack_controls(bad)

    def test_unsafe_source_execution_domains(self):
        c=parser.unpack_controls(fixtures.row()['controls'])
        for name,value in [('sps_flags',512),('pps_flags',1<<11),('slice_flags',1024),('decode_flags',8),
                           ('slice_type',3),('chroma_format_idc',3),('bit_depth_chroma_minus8',2),
                           ('pic_width_in_luma_samples',0),('num_ref_idx_l0_active_minus1',16),
                           ('luma_log2_weight_denom',31),('delta_chroma_log2_weight_denom',-1),
                           ('num_entry_point_offsets',1),('bit_size',1<<31),('data_byte_offset',1<<30),
                           ('slice_segment_addr',1<<31),('slice_tc_offset_div2',7)]:
            with self.subTest(name=name),self.assertRaises(ValueError):parser.validate_controls(dict(c,**{name:value}))

    def test_weight_states(self):
        self.assertEqual(parser.classify_weights(dict(sites=[],words=[],inactive=1<<27)),'skipped')
        self.assertEqual(parser.classify_weights(dict(sites=[22],words=[0x2dd00000],inactive=1<<19)),'default-header')
        for r in [dict(sites=[],words=[],inactive=1<<19),dict(sites=[22],words=[0x2dd00000],inactive=1<<27)]:
            with self.assertRaises(ValueError):parser.classify_weights(r)

class Binding(unittest.TestCase):
    def test_complete_history_and_wrong_job(self):
        own=dict(run=7,context=3,pictures=[dict(picture=i,poc=i,type=2,target=i%16,intra=1) for i in range(1,301)])
        ref=dict(run=7,context=3,records=[dict(kind=1,picture=i,poc=i,type=2,buffer=i%16,intra=1) for i in range(1,301)])
        parser.bind_history(own,ref)
        for mode in ('run','context','missing','writer'):
            bad=copy.deepcopy(ref)
            if mode in ('run','context'):bad[mode]+=1
            if mode=='missing':bad['records'].pop()
            if mode=='writer':bad['records'][28]['buffer']=99
            with self.subTest(mode=mode),self.assertRaises(ValueError):parser.bind_history(own,bad)

    def test_original_fail_open_reproducer(self):
        bad='H 1\n'+''.join('P 1 0 0 0 0 0\n' for _ in range(300))+'GARBAGE\n'
        with self.assertRaises(ValueError):parser.parse_snapshot(bad,7)

if __name__=='__main__':unittest.main()
