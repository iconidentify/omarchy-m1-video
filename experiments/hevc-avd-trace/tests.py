#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic recorder snapshots. No values generated here are measurements."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import check as c

ROOT = Path(__file__).resolve().parent
CAPTURES = ROOT.parent / 'hevc-controls/captures/2026-09-17/refs'


def synthetic(vector='E', client='gst'):
    inputs = [json.loads(line) for line in (CAPTURES / f'{vector}-{client}.jsonl').read_text().splitlines()]
    expected = c.model.map_records(inputs, 300)
    records, buffers = [], {}
    for p, source in enumerate(inputs, 1):
        sl = source['slices'][0]
        typ = {'B': 0, 'P': 1, 'I': 2}[sl['type']]
        target = source['target']
        prev = buffers.get(target, {}).get('writer', 0)
        b = dict(zip(c.BUFFER, [target, 9000000000+p*1000, 1, typ == 2, p, 0,
                                target+1, 256000, 150000, 50000, 0, 16384, 32768, 40000,
                                7168, 248832, 1, 1]))
        # bools are encoded as numeric C scalars.
        b['intra'] = int(b['intra'])
        buffers[target] = b
        start = dict(kind=1, picture=p, previous_writer=prev, poc=source['poc'],
                     slice_poc=source['poc'], type=typ, slices=1, entry_capacity=1, slice_entries=0,
                     dpb_count=len(source['dpb']), width=416, height=240, **b)
        records.append(start)
        if 24 <= p <= 34:
            if typ != 2:
                for slot, dpb in enumerate(source['dpb']):
                    ref = buffers[dpb['buf']].copy()
                    header = c.model.ref_header(len(source['dpb']), dpb['lt'], source['poc'], dpb['poc'])
                    row = dict(kind=3, picture=p, slot=slot, poc=dpb['poc'], flags=dpb['lt'],
                               requested_timestamp=ref['timestamp'], word=int(header['value'],16), matched=1, **ref)
                    for i in range(4):row['emitted_comp'+str(i)] = ref['comp_start'] + ref['off'+str(i)]
                    records.append(row)
                for li in (0, 1):
                    for i, slot in enumerate(sl['l'+str(li)]):
                        records.append(dict(kind=4, picture=p, list=li, position=i, slot=slot,
                                            word=int(c.model.ref_list_word(li,i,slot),16)))
            m = dict.fromkeys(c.MOTION, 0)
            m.update(kind=5, picture=p, type=typ, first=1, quirks=1)
            m['flags'] = int(bool(sl['tmvp'])) * c.TMVP | int(bool(sl.get('col_l0',0))) * c.COL_L0
            m['l0_minus1'] = max(0, len(sl['l0'])-1)
            m['l1_minus1'] = max(0, len(sl['l1'])-1)
            m['col_index'] = sl.get('col', 0)
            for li in (0, 1):
                for i, slot in enumerate(sl['l'+str(li)]): m[f'l{li}_{i}'] = slot
            if typ != 2:
                li = 0 if typ == 1 or m['flags'] & c.COL_L0 else 1
                slot = m[f'l{li}_{m["col_index"]}']
                ref = buffers[source['dpb'][slot]['buf']].copy()
                m.update(ref)
                gate = int(bool(sl['tmvp'] and not ref['intra']))
                m.update(lookup=1, matched=1, slot=slot, requested_timestamp=ref['timestamp'],
                         valid=gate, emitted=gate, emitted_mv=ref['mv_offset'] if gate else 0)
            m['word'] = c.motion_word(m)
            records.append(m)
        b['completed'] = 1
        records.append(dict(kind=2, picture=p, result=5, **b))
    return dict(run=107, context=23, records=records, count=len(records)), expected


def encode(capture):
    rows = capture['records']
    lines = [f'H 2 {capture["run"]} {capture["context"]} 4 0 {len(rows)} {len(rows)} 300 300 2048 24 34 {c.RECORD_SIZE}']
    for seq, row in enumerate(rows, 1):
        vals = [row[k] & 0xffffffff if k in ('poc','slice_poc') else row[k] for k in c.FIELDS[row['kind']]]
        vals += [0] * (c.VALUES-len(vals))
        lines.append(' '.join(map(str,['R',capture['run'],capture['context'],seq,row['kind'],row['picture'],*vals])))
    return '\n'.join(lines)+'\n'


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.trace, self.expected = synthetic()

    def result(self):
        return c.validate(c.read_capture(encode(self.trace), 107), self.expected)

    def row(self, kind, picture=29):
        return next(r for r in self.trace['records'] if r['kind']==kind and r['picture']==picture)

    def rejected(self):
        with self.assertRaises((c.Reject, c.model.Reject)):
            self.result()

    def finding(self, code):
        self.assertIn(code, [f['code'] for f in self.result()['findings']])

    def test_four_full_synthetic_histories(self):
        for vector in ('B','E'):
            for client in ('va','gst'):
                with self.subTest(vector=vector,client=client):
                    trace, expected=synthetic(vector,client)
                    result=c.validate(c.read_capture(encode(trace),107),expected)
                    self.assertEqual(result['findings'], [])
                    self.assertTrue(all('timestamp' not in r and 'requested_timestamp' not in r for r in result['records']))
                    self.assertTrue('9000001000' not in json.dumps(result))
                    self.assertTrue(result['userspace_correlated'])

    def test_missing_duplicate_and_reordered_records(self):
        for mutation in ('missing_start','missing_done','missing_table','duplicate_table','reorder'):
            with self.subTest(mutation=mutation):
                self.trace,_=synthetic()
                rows=self.trace['records']
                r=self.row(3)
                if mutation=='missing_start': rows.remove(self.row(1,10))
                if mutation=='missing_done': rows.remove(self.row(2,10))
                if mutation=='missing_table': rows.remove(r)
                if mutation=='duplicate_table': rows.insert(rows.index(r),r.copy())
                if mutation=='reorder': rows[0],rows[1]=rows[1],rows[0]
                self.rejected()

    def test_header_sequence_context_and_loss(self):
        raw=encode(self.trace)
        for field,value in ((1,'1'),(2,'108'),(4,'2'),(5,'2'),(6,'1'),(8,'299'),(10,'4096'),(13,'8')):
            lines=raw.splitlines(); h=lines[0].split(); h[field]=value;lines[0]=' '.join(h)
            with self.subTest(header_field=field), self.assertRaises(c.Reject):
                c.read_capture('\n'.join(lines),107)
        for field in (1,2,3):
            lines=raw.splitlines(); r=lines[8].split();r[field]='999';lines[8]=' '.join(r)
            with self.subTest(record_field=field),self.assertRaises(c.Reject):
                c.read_capture('\n'.join(lines),107)

    def test_missing_inputs_padding_and_noncanonical_numbers(self):
        raw=encode(self.trace)
        for mutation in ('short','padding','negative','leadingzero','overflow'):
            lines=raw.splitlines();r=lines[1].split()
            if mutation=='short':r.pop()
            if mutation=='padding':r[-1]='1'
            if mutation=='negative':r[1]='-1'
            if mutation=='leadingzero':r[1]='0107'
            if mutation=='overflow':r[1]=str(2**64)
            lines[1]=' '.join(r)
            with self.subTest(mutation=mutation),self.assertRaises(c.Reject):
                c.read_capture('\n'.join(lines),107)

    def test_extra_slice_or_extent(self):
        self.row(1)['slices']=2;self.rejected()
        self.trace,_=synthetic();self.row(1)['slice_entries']=1;self.rejected()
        self.trace,_=synthetic();self.trace['records']+=self.trace['records'][-2:];self.rejected()

    def test_unused_entry_array_capacity_is_not_slice_usage(self):
        # Hardware schema 1 rejected a one-element control array. Schema 2
        # records both counts; these are synthetic histories, not a repaired run.
        for capacity in (1, 256):
            for row in self.trace['records']:
                if row['kind'] == 1:
                    row['entry_capacity'] = capacity
            self.assertEqual(self.result()['findings'], [])
        for capacity in (0, 257, 2**32):
            self.row(1)['entry_capacity'] = capacity
            self.rejected()
        self.trace, _ = synthetic()
        self.row(1)['slice_entries'] = 1
        self.rejected()

    def test_stale_writer_and_intra(self):
        self.row(3)['writer']=299;self.finding('stale-or-unknown-writer')
        self.trace,_=synthetic();self.row(5)['intra']=0;self.finding('writer-intra-mismatch')

    def test_fallback_is_preserved_as_finding(self):
        self.row(5)['matched']=0;self.finding('motion-lookup-fallback')
        self.trace,_=synthetic();self.row(3)['matched']=0;self.finding('reference-lookup-fallback')

    def test_copied_timestamp_and_completion(self):
        self.row(3)['copied']=0;self.finding('copied-timestamp-invalid')
        self.trace,_=synthetic();self.row(3)['completed']=0;self.finding('reference-writer-not-completed')
        self.trace,_=synthetic();self.row(2)['result']=6;self.rejected()

    def test_words_and_emitted_addresses(self):
        for kind,field,code in ((3,'word','reference-header-word-mismatch'),
                              (4,'word','reference-list-word-mismatch'),
                              (5,'word','full-motion-word-mismatch'),
                              (3,'emitted_comp0','compressed-address-mismatch'),
                              (5,'emitted_mv','motion-address-mismatch')):
            with self.subTest(field=field,kind=kind):
                self.trace,_=synthetic();self.row(kind)[field]^=1;self.finding(code)
        self.trace,_=synthetic();self.row(5)['word']^=1<<18
        self.finding('userspace-known-motion-bit-mismatch')

    def test_i_early_return(self):
        m=self.row(5,28);self.assertEqual(m['type'],2)
        m['col_index']=255;m['merge']=255
        self.assertEqual(self.result()['findings'],[])
        m['lookup']=1;self.rejected()

    def test_tmvp_disabled_still_requires_lookup(self):
        m=self.row(5);m['flags'] &= ~c.TMVP;m['valid']=m['emitted']=m['emitted_mv']=0
        m['word']=c.motion_word(m)
        result=c.validate(c.read_capture(encode(self.trace),107))
        self.assertEqual(result['findings'],[])
        m['lookup']=0;self.rejected()

    def test_dependent_flag_suppresses_motion(self):
        m=self.row(5,31);m['flags'] |= c.DEPENDENT
        m['valid']=m['emitted']=m['emitted_mv']=0;m['word']=c.motion_word(m)
        self.assertEqual(c.validate(c.read_capture(encode(self.trace),107))['findings'],[])

    def test_allocation_identity_and_layout(self):
        r=self.row(3);r['allocation']=self.row(1)['allocation'];self.rejected()
        self.trace,_=synthetic();self.row(3)['mv_size']+=256;self.rejected()
        self.trace,_=synthetic();self.row(1)['previous_writer']+=1
        self.finding('destination-previous-writer-mismatch')
        self.trace,_=synthetic()
        self.row(1,300)['allocation']=999
        self.row(2,300)['allocation']=999
        self.row(1,300)['previous_writer']=0
        self.assertEqual(self.result()['findings'],[])
        self.trace,_=synthetic();self.row(3)['allocation']=999
        self.finding('stale-or-unwritten-allocation')

    def test_actual_slice_poc_used(self):
        start=self.row(1);start['slice_poc']+=1
        self.finding('slice-decode-poc-difference')
        self.finding('reference-header-word-mismatch')

    def test_userspace_mismatch(self):
        self.expected[28]['motion']['word']['known_value']='0x2d008880'
        self.finding('userspace-known-motion-bit-mismatch')

    def remap_timestamps(self, mapping):
        for row in self.trace['records']:
            for field in ('timestamp', 'requested_timestamp'):
                if field in row and row[field] in mapping:
                    row[field] = mapping[row[field]]

    def test_buffer_timestamp_reuse_preserves_each_writer(self):
        for vector in ('B', 'E'):
            for client in ('va', 'gst'):
                self.trace, self.expected = synthetic(vector, client)
                mapping = {r['timestamp']: 8000000000 + r['buffer'] * 1000
                           for r in self.trace['records'] if r['kind'] == 1}
                self.remap_timestamps(mapping)
                result = self.result()
                self.assertEqual(result['findings'], [])
                for row in result['records']:
                    if 'timestamp' not in c.FIELDS[row['kind']]:
                        continue
                    if row['kind'] == 5 and not row['lookup']:
                        self.assertIsNone(row['timestamp_writer'])
                    else:
                        self.assertEqual(row['timestamp_writer'], row['writer'])
                        self.assertEqual(row['timestamp_writer_candidates'], [row['writer']])
                # Latest writer must not rewrite an earlier record's identity.
                self.assertEqual(result['records'][0]['timestamp_writer'], 1)

    def test_future_timestamp_is_not_a_current_writer(self):
        self.row(3)['requested_timestamp'] = self.row(1, 300)['timestamp']
        result = self.result()
        row = next(r for r in result['records'] if r['kind'] == 3 and r['picture'] == 29)
        self.assertIsNone(row['requested_timestamp_writer'])
        self.assertEqual(row['requested_timestamp_writer_candidates'], [])
        self.finding('lookup-timestamp-mismatch')

    def test_retired_timestamp_is_not_a_current_writer(self):
        start = self.row(1)
        previous = self.row(1, start['previous_writer'])
        self.row(3)['requested_timestamp'] = previous['timestamp']
        result = self.result()
        row = next(r for r in result['records'] if r['kind'] == 3 and r['picture'] == 29)
        self.assertIsNone(row['requested_timestamp_writer'])
        self.assertEqual(row['requested_timestamp_writer_candidates'], [])
        self.finding('lookup-timestamp-mismatch')

    def test_simultaneous_timestamp_alias_is_an_explicit_finding(self):
        self.remap_timestamps({self.row(1, 2)['timestamp']: self.row(1, 1)['timestamp']})
        result = self.result()
        row = next(r for r in result['records'] if r['kind'] == 1 and r['picture'] == 2)
        self.assertIsNone(row['timestamp_writer'])
        self.assertEqual(row['timestamp_writer_candidates'], [1, 2])
        self.finding('timestamp-ambiguous-current-writers')

    def test_i_absent_lookup_is_not_a_real_zero_timestamp(self):
        self.remap_timestamps({self.row(1, 28)['timestamp']: 0})
        result = self.result()
        start = next(r for r in result['records'] if r['kind'] == 1 and r['picture'] == 28)
        motion = next(r for r in result['records'] if r['kind'] == 5 and r['picture'] == 28)
        self.assertEqual(start['timestamp_writer'], 28)
        self.assertIsNone(motion['timestamp_writer'])
        self.assertIsNone(motion['requested_timestamp_writer'])
        self.assertEqual(motion['timestamp_writer_candidates'], [])
        self.assertEqual(motion['requested_timestamp_writer_candidates'], [])

    def test_full_motion_words_against_upstream_c_macros(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary=str(Path(tmp)/'motion-vectors')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(ROOT/'motion-vectors.c'),'-o',binary],check=True)
            lines=subprocess.check_output([binary],text=True,timeout=30).splitlines()
            self.assertEqual(len(lines),5760)
            for line in lines:
                typ,flags,merge,l0,l1,valid,word=map(int,line.split())
                actual=c.motion_word(dict(type=typ,flags=flags,merge=merge,l0_minus1=l0,l1_minus1=l1,valid=valid))
                self.assertEqual(actual,word)

    def test_supervisor_keeps_child_status_and_stops_on_trace_errors(self):
        import capture
        class Fake:
            def __init__(self,error=0):self.phase=0;self.error=error;self.calls=[]
            def control(self,text):
                self.calls.append(text)
                self.phase={'arm':1,'seal':4,'off':0}[text.split()[0]]
            def status(self):return dict(run=7,context=1,phase=self.phase,errors=self.error)
            def snapshot(self):return b'synthetic private snapshot\n'
        backend=Fake()
        result,raw=capture.supervise(['/bin/sh','-c','exit 23'],7,True,5,backend)
        self.assertEqual(result['child_exit'],23)
        self.assertTrue(result['child_reaped'])
        self.assertEqual(raw,b'synthetic private snapshot\n')
        self.assertEqual([x.split()[0] for x in backend.calls],['arm','seal'])
        backend=Fake(error=2)
        result,raw=capture.supervise(['/bin/sleep','5'],7,True,5,backend)
        self.assertIsNotNone(result['trace_error'])
        self.assertTrue(result['child_reaped'])
        self.assertLess(result['child_exit'],0)
        backend=Fake()
        result,raw=capture.supervise(['/bin/true'],7,False,5,backend)
        self.assertEqual(result['child_exit'],0);self.assertIsNone(raw)
        self.assertEqual(backend.calls,['off'])
        result,_=capture.supervise(['/bin/sleep','5'],7,True,1,Fake())
        self.assertIn('deadline',result['trace_error']);self.assertTrue(result['child_reaped'])

    def test_shared_c_recorder_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary=str(Path(tmp)/'state-tests')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                            '-I'+str(ROOT/'kernel'),str(ROOT/'state-tests.c'),'-o',binary],check=True)
            subprocess.run([binary],check=True,timeout=30)


if __name__=='__main__':unittest.main(verbosity=2)
