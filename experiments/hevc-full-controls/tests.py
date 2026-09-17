#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic control/lifecycle regressions. No decoder or private data needed."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import unittest
import normalize as n

spec = importlib.util.spec_from_file_location('reference_fixtures', n.HERE.parent / 'hevc-controls/tests.py')
old = importlib.util.module_from_spec(spec)
# Existing fixture module's `import normalize` resolves here, so supply only its
# construction API. Its test methods are not executed by this suite.
spec.loader.exec_module(old)
old.n = n.base


def blank(name):
    result = {}
    for key, field in n.SCHEMA[name].items():
        if 'flags' in field:
            result[key] = ''
        else:
            one = blank(field['type'][7:]) if field['type'].startswith('struct ') else 0
            result[key] = [copy.deepcopy(one) for _ in range(math.prod(field['shape']))] if field['shape'] else one
    return result


def fixture():
    events = old.fixture()
    for e in events:
        if e.get('ioctl') != 'VIDIOC_S_EXT_CTRLS':
            continue
        ext = e['from_userspace']['v4l2_ext_controls']
        for c in ext['controls']:
            name = c['id'][len(n.base.CID):]
            key = 'v4l2_ctrl_hevc_' + name.lower()
            value = blank(key); value.update(c[key]); c[key] = value
        for name in ('PPS', 'SCALING_MATRIX'):
            key = 'v4l2_ctrl_hevc_' + name.lower()
            ext['controls'].append(dict(id=n.base.CID+name,size=n.SIZES[name],**{key:blank(key)}))
        ext['count'] = len(ext['controls'])
        e['from_driver'] = copy.deepcopy(e['from_userspace'])
    events[-2]['from_userspace'] = dict(type=n.base.OUT)
    return events


def convert(events, count=4):
    return n.normalize(n.base.parse(json.dumps(events).encode()), count, '1234567890abcdef')


def with_input_bytes(events):
    mode=old.ioctl('VIDIOC_G_EXT_CTRLS','from_driver',dict(v4l2_ext_controls=dict(
        which='V4L2_CTRL_WHICH_CUR_VAL',count=2,controls=[
            dict(id=n.base.CID+'DECODE_MODE',size=0,value='V4L2_STATELESS_HEVC_DECODE_MODE_FRAME_BASED'),
            dict(id=n.base.CID+'START_CODE',size=0,value='V4L2_STATELESS_HEVC_START_CODE_NONE')])))
    events.insert(2,mode)
    new=[]
    for e in events:
        if e.get('ioctl')=='VIDIOC_QBUF' and e['from_userspace']['v4l2_buffer']['type']==n.base.OUT:
            b=e['from_userspace']['v4l2_buffer'];b['m']['planes'][0]['data_offset']=0
            new.append(dict(mem_dump=n.base.OUT,fd=10,index=b['index'],bytesused=32,mem_array=[bytes(range(32)).hex(' ')]))
        new.append(e)
    return new


class Tests(unittest.TestCase):
    def test_complete_payloads_and_explicit_sps_carry(self):
        rows, refs, _ = convert(fixture())
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]['sps_from_picture'], 1)
        self.assertNotIn('SPS', rows[-1]['submitted'])
        self.assertEqual(rows[-1]['controls']['SPS'], rows[0]['controls']['SPS'])
        self.assertEqual(rows[-1]['controls']['DECODE_PARAMS']['dpb'][0]['timestamp_writer'], 3)
        for row in rows:
            for ent in row['controls']['DECODE_PARAMS']['dpb']:
                self.assertNotIn('timestamp', ent)
        self.assertEqual([r['poc'] for r in refs], [0, 2, 1, 3])

    def test_missing_unknown_and_boolean_fields(self):
        for change in (lambda s:s.pop('slice_qp_delta'), lambda s:s.update(extra=0),
                       lambda s:s.update(slice_qp_delta=True)):
            with self.subTest(change=change):
                e=fixture(); change(old.control(e,'SLICE_PARAMS')['v4l2_ctrl_hevc_slice_params'])
                with self.assertRaises(ValueError): convert(e)

    def test_complete_array_and_signed_range(self):
        for field,value in [('slice_qp_delta',-129),('slice_qp_delta',128),('ref_idx_l0',[0]*15)]:
            e=fixture();old.control(e,'SLICE_PARAMS')['v4l2_ctrl_hevc_slice_params'][field]=value
            with self.assertRaises(ValueError):convert(e)
        e=fixture();old.control(e,'SLICE_PARAMS')['v4l2_ctrl_hevc_slice_params']['slice_qp_delta']=-128
        old.selected(e,'VIDIOC_S_EXT_CTRLS')[0]['from_driver']=copy.deepcopy(old.selected(e,'VIDIOC_S_EXT_CTRLS')[0]['from_userspace'])
        self.assertEqual(convert(e)[0][0]['controls']['SLICE_PARAMS']['slice_qp_delta'],-128)

    def test_unknown_flags_and_extra_slice_rejected(self):
        for change in (lambda c:c.update(size=560),lambda c:c['v4l2_ctrl_hevc_slice_params'].update(flags='0x40000000'),
                       lambda c:c['v4l2_ctrl_hevc_slice_params'].update(num_entry_point_offsets=1)):
            e=fixture();change(old.control(e,'SLICE_PARAMS'))
            with self.assertRaises(ValueError):convert(e)

    def test_first_sps_cannot_come_from_negotiation(self):
        e=fixture();ext=old.ext(e);c=old.control(e,'SPS');ext['controls'].remove(c);ext['count']-=1
        e.insert(2,old.ioctl('VIDIOC_S_EXT_CTRLS','from_userspace',dict(v4l2_ext_controls=dict(which='V4L2_CTRL_WHICH_CUR_VAL',count=1,controls=[c]))))
        with self.assertRaises(ValueError):convert(e)

    def test_retired_buffer_timestamp_and_destination_alias(self):
        e=fixture()
        for event in e:
            if event.get('ioctl') in ('VIDIOC_QBUF','VIDIOC_DQBUF'):
                direction='from_driver' if event['ioctl']=='VIDIOC_DQBUF' else 'from_userspace'
                b=event[direction]['v4l2_buffer'];pic=b['timestamp_ns']//1000
                if pic==3:n.set_timestamp(b,0)
        self.assertEqual(convert(e)[0][-1]['target'],4)
        old.control(e,'DECODE_PARAMS',3)['v4l2_ctrl_hevc_decode_params']['dpb'][0].update(timestamp=0,pic_order_cnt_val=0)
        with self.assertRaises(ValueError):convert(e)

    def test_ambiguous_distinct_buffers(self):
        e=fixture()
        for event in e:
            if event.get('ioctl') in ('VIDIOC_QBUF','VIDIOC_DQBUF'):
                b=event['from_driver' if event['ioctl']=='VIDIOC_DQBUF' else 'from_userspace']['v4l2_buffer']
                if b['timestamp_ns']==1000:n.set_timestamp(b,0)
        old.control(e,'DECODE_PARAMS',2)['v4l2_ctrl_hevc_decode_params']['dpb'][0]['timestamp']=0
        with self.assertRaises(ValueError):convert(e)

    def test_final_output_can_be_returned_by_streamoff(self):
        e=fixture()
        out=[x for x in e if x.get('ioctl')=='VIDIOC_DQBUF' and x['from_driver']['v4l2_buffer']['type']==n.base.OUT][-1]
        e.remove(out)
        self.assertEqual(len(convert(e)[0]),4)
        e[-2]['from_userspace']['type']=n.base.CAP
        with self.assertRaises(ValueError):convert(e)

    def test_missing_capture_cannot_be_excused_by_streamoff(self):
        e=fixture();x=[x for x in e if x.get('ioctl')=='VIDIOC_DQBUF' and x['from_driver']['v4l2_buffer']['type']==n.base.CAP][-1];e.remove(x)
        with self.assertRaises(ValueError):convert(e)

    def test_queued_reference_before_userspace_completion(self):
        e=fixture();picture=0;new=[]
        # Each picture uses a separate request; delay picture1 DQBUF until after
        # picture2 QUEUE, as a queued-ahead direct client may legitimately do.
        for x in e:
            if x.get('ioctl')=='MEDIA_IOC_REQUEST_ALLOC':continue
            if x.get('ioctl')=='VIDIOC_S_EXT_CTRLS':
                picture+=1
                new.append(old.ioctl('MEDIA_IOC_REQUEST_ALLOC','from_driver',dict(request_fd=20+picture),fd=11))
                x['from_userspace']['v4l2_ext_controls']['request_fd']=20+picture
                x['from_driver']['v4l2_ext_controls']['request_fd']=20+picture
            if x.get('ioctl') in ('MEDIA_REQUEST_IOC_QUEUE','MEDIA_REQUEST_IOC_REINIT'):x['fd']=20+picture
            if x.get('ioctl')=='VIDIOC_QBUF':x['from_userspace']['v4l2_buffer']['request_fd']=20+picture
            if x.get('ioctl') in ('VIDIOC_QBUF','VIDIOC_DQBUF'):
                b=x['from_driver' if x['ioctl']=='VIDIOC_DQBUF' else 'from_userspace']['v4l2_buffer']
                if b['type']==n.base.OUT:b['index']=picture
            if x.get('ioctl')=='MEDIA_REQUEST_IOC_REINIT':continue
            new.append(x)
        delayed=[x for x in new if x.get('ioctl')=='VIDIOC_DQBUF' and x['from_driver']['v4l2_buffer']['timestamp_ns']==0]
        for x in delayed:new.remove(x)
        i=next(i for i,x in enumerate(new) if x.get('ioctl')=='MEDIA_REQUEST_IOC_QUEUE' and x['fd']==22)
        new[i+1:i+1]=delayed
        self.assertEqual(convert(new)[0][1]['controls']['DECODE_PARAMS']['dpb'][0]['timestamp_writer'],1)

    def test_extent_teardown_and_failed_request(self):
        for mutate in (lambda e:e.pop(),lambda e:old.selected(e,'MEDIA_REQUEST_IOC_QUEUE')[1].update(errno='EINVAL')):
            e=fixture();mutate(e)
            with self.assertRaises(ValueError):convert(e)
        with self.assertRaises(ValueError):convert(fixture(),5)

    def test_kernel_return_correction_is_measured_and_retained(self):
        e=fixture()
        sps=old.control(e,'SPS')['v4l2_ctrl_hevc_sps']
        sps['pcm_sample_bit_depth_luma_minus1']=255
        rows,_,_=convert(e)
        self.assertEqual(rows[0]['controls']['SPS']['pcm_sample_bit_depth_luma_minus1'],0)
        self.assertEqual(rows[0]['input_changes'],[dict(control='SPS',field='pcm_sample_bit_depth_luma_minus1',submitted=255,returned=0)])
        old.selected(e,'VIDIOC_S_EXT_CTRLS')[0].pop('from_driver')
        with self.assertRaises((ValueError,KeyError)):convert(e)

    def test_payload_hashes_and_explicit_mode_observation(self):
        e=with_input_bytes(fixture());r=n.extra_evidence(e,4)
        self.assertEqual(len(r['encoded_inputs']),4)
        self.assertEqual(r['encoded_inputs'][0]['sha256'],n.hashlib.sha256(bytes(range(32))).hexdigest())
        self.assertEqual(set(r['encoded_inputs'][0]),{'picture','bytes','sha256'})

    def test_missing_mismatched_and_unbound_dump(self):
        for change in (lambda d:d.update(fd=999),lambda d:d.update(bytesused=31),
                       lambda d:d.update(mem_array=['00']),lambda d:d.update(index=99)):
            e=with_input_bytes(fixture());change(next(x for x in e if 'mem_dump' in x))
            with self.assertRaises(ValueError):n.extra_evidence(e,4)
        e=with_input_bytes(fixture());e.remove(next(x for x in e if 'mem_dump' in x))
        with self.assertRaises(ValueError):n.extra_evidence(e,4)

    def test_bound_export_and_missing_modes(self):
        e=with_input_bytes(fixture());e.insert(3,old.ioctl('VIDIOC_EXPBUF','from_driver',dict(v4l2_exportbuffer=dict(type=n.base.OUT,plane=0,fd=50,index=0))))
        for x in e:
            if 'mem_dump' in x:x['fd']=50
        self.assertEqual(len(n.extra_evidence(e,4)['encoded_inputs']),4)
        closed=copy.deepcopy(e)
        i=next(i for i,x in enumerate(closed) if 'mem_dump' in x)
        closed.insert(i,dict(close='exported source',fd=50))
        with self.assertRaises(ValueError):n.extra_evidence(closed,4)
        e.remove(next(x for x in e if x.get('ioctl')=='VIDIOC_G_EXT_CTRLS'))
        with self.assertRaises(ValueError):n.extra_evidence(e,4)


if __name__=='__main__':unittest.main(verbosity=2)
