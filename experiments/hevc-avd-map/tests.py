#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic counterexamples and independent upstream C macro parity; no device."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import model as m
import report

ROOT = Path(__file__).resolve().parent


def fixture():
    records = []
    # Decode POC 0,2,1,3,4; target 4 reused on picture 4 from I to B.
    for i, (poc, target, typ, refs) in enumerate([
            (0, 4, 'I', []), (2, 5, 'I', [(4, 0)]),
            (1, 6, 'B', [(4, 0), (5, 2)]), (3, 4, 'B', [(5, 2), (6, 1)]),
            (4, 7, 'B', [(4, 3), (6, 1)])], 1):
        s = dict(i=0, type=typ, nal=21 if typ == 'I' else 1, tmvp=1,
                 l0=[] if typ == 'I' else [0, 1], l1=[] if typ == 'I' else [1, 0],
                 col_l0=0, col=0)
        if i == 4:s.update(col_l0=1, col=1)
        if i == 5:s.update(col_l0=1, col=0)
        records.append(dict(schema=m.SCHEMA, run='0000000000000001', seq=i, ctx=1, pic=i,
                            req=i, first=1, last=1, target=target, poc=poc,
                            dpb=[dict(i=j, buf=b, poc=p, lt=1, field=0) for j,(b,p) in enumerate(refs)],
                            st_before=[], st_after=[], lt_curr=list(range(len(refs))), slices=[s]))
    return records


def logical(record):
    return {k: [(e['writer']['picture'],e['writer']['poc']) for e in v]
            for k,v in record['lists'].items()}


def permute(records, remap=True):
    out=copy.deepcopy(records)
    r=out[2]; r['dpb'].reverse()
    for i,e in enumerate(r['dpb']):e['i']=i
    r['lt_curr']=[1-i for i in r['lt_curr']]
    if remap:
        for k in ('l0','l1'):r['slices'][0][k]=[1-i for i in r['slices'][0][k]]
    return out


class ModelTests(unittest.TestCase):
    def test_permuted_dpb_correctly_remapped_lists_preserve_identity(self):
        a=m.map_records(fixture(),5)[2]; b=m.map_records(permute(fixture()),5)[2]
        self.assertEqual(logical(a),logical(b))
        self.assertNotEqual(a['lists']['l0'][0]['word'],b['lists']['l0'][0]['word'])
        self.assertEqual(a['motion']['collocated'],b['motion']['collocated'])

    def test_wrong_remap_changes_picture_and_collocated_selection(self):
        a=m.map_records(fixture(),5)[2]; b=m.map_records(permute(fixture(),False),5)[2]
        self.assertNotEqual(logical(a),logical(b))
        self.assertNotEqual(a['motion']['collocated'],b['motion']['collocated'])

    def test_reused_target_updates_intra_history(self):
        rows=m.map_records(fixture(),5)
        self.assertTrue(rows[3]['previous_destination_writer']['is_intra'])
        self.assertFalse(rows[4]['motion']['collocated']['is_intra'])
        self.assertEqual(rows[4]['motion']['collocated']['picture'],4)
        self.assertEqual(rows[4]['motion']['collocated']['generation'],2)

    def test_stale_buffer_writer_is_rejected(self):
        rows=fixture();rows[4]['dpb'][0]['poc']=0
        with self.assertRaisesRegex(m.Reject,'stale'):m.map_records(rows,5)

    def test_unresolved_and_destination_alias_rejected(self):
        for buffer in (99,6):
            rows=fixture();rows[2]['dpb'][0]['buf']=buffer
            with self.subTest(buffer=buffer),self.assertRaises(m.Reject):m.map_records(rows,5)

    def test_unknown_inputs_are_not_zero_filled(self):
        row=m.map_records(fixture(),5)[2]
        self.assertIsNone(row['dpb'][0]['header']['value'])
        self.assertEqual(row['dpb'][0]['header']['known_mask'],'0xfffe0000')
        self.assertIsNone(row['motion']['word']['value'])
        self.assertIsNone(row['motion']['address_if_enabled']['value'])
        self.assertEqual(row['motion']['expected_ref_valid'],False)
        self.assertEqual(row['motion']['address_emission'],'absent')
        self.assertIsNone(m.map_records(fixture(),5)[3]['motion']['expected_ref_valid'])

    def test_i_slice_early_return_ignores_unused_col(self):
        rows=fixture();rows[0]['slices'][0]['col']=255
        row=m.map_records(rows,5)[0]
        self.assertFalse(row['reference_table_emitted'])
        self.assertEqual(row['motion']['word']['value'],'0x2d020000')
        self.assertIsNone(row['motion']['collocated'])

    def test_tmvp_disabled_lookup_remains_unknown(self):
        rows=fixture();s=rows[2]['slices'][0];s['tmvp']=0
        del s['col'];del s['col_l0']
        row=m.map_records(rows,5)[2]['motion']
        self.assertFalse(row['expected_ref_valid'])
        self.assertIsNone(row['collocated'])
        self.assertIn('unavailable',row['lookup'])

    def test_p_implicitly_selects_l0_and_unused_l1_count_stays_unknown(self):
        rows=fixture();s=rows[2]['slices'][0];s.update(type='P', l1=[], col_l0=0)
        row=m.map_records(rows,5)[2]['motion']
        self.assertEqual(row['collocated']['poc'],0)
        self.assertIn('num_ref_idx_l1_active_minus1',row['word']['unknown_inputs'])

    def test_bounded_domain_rejects_partial_or_ambiguous_capture(self):
        mutations=[lambda r:r.pop(),lambda r:r[1].update(poc=0),
                   lambda r:r[1].update(ctx=2),lambda r:r[1].update(first=0),
                   lambda r:r[1]['slices'].append(r[1]['slices'][0]),
                   lambda r:r[2]['slices'][0].update(col=99),
                   lambda r:r[2]['dpb'][0].update(field=1)]
        for change in mutations:
            rows=fixture();change(rows)
            with self.subTest(change=change),self.assertRaises(m.Reject):m.map_records(rows,5)

    def test_kernel_timestamp_zero_requires_copied_metadata(self):
        buffers=[dict(index=0,timestamp=0,copied_timestamp=False),
                 dict(index=1,timestamp=0,copied_timestamp=True),
                 dict(index=2,timestamp=3000,copied_timestamp=True)]
        self.assertEqual(m.kernel_lookup(buffers,0,2),dict(index=1,fallback=False))
        self.assertEqual(m.kernel_lookup(buffers,5000,2),dict(index=2,fallback=True))
        buffers[0]['copied_timestamp']=True
        self.assertEqual(m.kernel_lookup(buffers,0,2),dict(index=0,fallback=False))

    def test_signed_poc_encoding_and_ranges(self):
        self.assertEqual(m.ref_header(2,1,10,6)['value'],'0x11020004')
        self.assertEqual(m.ref_header(2,1,6,10)['value'],'0x1103fffc')
        for args in ((0,1),(17,1),(1,2)):
            with self.assertRaises(m.Reject):m.ref_header(*args)
        with self.assertRaises(m.Reject):m.ref_header(1,0,2**31-1,-1)

    def test_duplicate_json_and_nonfinite_values_reject(self):
        for text in ('{"poc":1,"poc":2}', '{"poc":NaN}', '{"poc":Infinity}'):
            with self.subTest(text=text),self.assertRaises(m.Reject):report.parse(text)

    def test_untrusted_checker_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            stub=Path(temp)/'checker.py';stub.write_text('raise RuntimeError("must not execute")')
            with mock.patch.dict(os.environ,HEVC_REFTRACE_CHECKER=str(stub)):
                with self.assertRaisesRegex(m.Reject,'immutable reviewed pin'):report.checker_path()

    def test_modified_public_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'experiments/hevc-avd-map';root.mkdir(parents=True)
            source=json.loads((ROOT/'source-map.json').read_text())
            shutil.copyfile(ROOT/'source-map.json',root/'source-map.json')
            for row in source['capture_inputs']:
                target=root.parent/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT.parent/row['path'],target)
            for row in source['patches']['files']:
                target=root.parent.parent/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT.parent.parent/row['path'],target)
            victim=root.parent/'hevc-controls/captures/2026-09-17/refs/E-gst.jsonl'
            victim.write_bytes(victim.read_bytes().replace(b'"poc":28',b'"poc":99',1))
            with mock.patch.object(report,'ROOT',root):
                with self.assertRaisesRegex(m.Reject,'public capture changed'):report.check_inputs()

    def test_upstream_c_macro_parity(self):
        compiler=shutil.which('cc')
        self.assertIsNotNone(compiler,'portable C compiler required for macro parity')
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/'bitfield-vectors'
            subprocess.run([compiler,'-std=c11','-Wall','-Wextra','-Werror',
                            str(ROOT/'bitfield_vectors.c'),'-o',str(exe)],check=True,timeout=30)
            lines=subprocess.check_output([str(exe)],text=True,timeout=10).splitlines()
        counts={k:0 for k in ('H','L','I','M')}
        mv=m.map_records(fixture(),5)[2]['motion']['word']
        for line in lines:
            parts=line.split();kind=parts[0];expected='0x'+parts[-1];counts[kind]+=1
            with self.subTest(line=line):
                if kind=='H':
                    n,lt,delta=map(int,parts[1:4]);self.assertEqual(m.ref_header(n,lt,delta,0)['value'],expected)
                elif kind=='L':self.assertEqual(m.ref_list_word(*map(int,parts[1:4])),expected)
                elif kind=='I':self.assertEqual(m.map_records(fixture(),5)[0]['motion']['word']['value'],expected)
                else:self.assertEqual(int(expected,16)&int(mv['known_mask'],16),int(mv['known_value'],16))
        self.assertEqual(counts,dict(H=288,L=512,I=1,M=20))


if __name__=='__main__':unittest.main()
