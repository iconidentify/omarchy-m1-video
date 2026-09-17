#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Full supported ioctl payloads, with the existing lifecycle checker underneath.

Only one-slice, zero-entry-point, one-context complete streams are accepted.
Raw timestamps become logical writer ordinals; inactive DPB timestamps are omitted.
The transformed events are internal checker input, never represented as raw data.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('reference_adapter', HERE.parent / 'hevc-controls/normalize.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
spec = importlib.util.spec_from_file_location('full_lifecycle', HERE / 'lifecycle.py')
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)
need, integer = base.require, base.integer
SCHEMA = json.loads((HERE / 'payload-schema.json').read_text())
SIZES = dict(SPS=40, PPS=64, SLICE_PARAMS=280, DECODE_PARAMS=328, SCALING_MATRIX=1000)


def payload(value, name):
    fields = SCHEMA[name]
    need(type(value) is dict and set(value) == set(fields), 'missing/unknown control field')
    result = {}
    for key, field in fields.items():
        item = value[key]
        if 'flags' in field:
            need(type(item) is str, 'invalid flags')
            tokens = [x.strip() for x in item.split('|')] if item else []
            need(len(tokens) == len(set(tokens)) and set(tokens) <= set(field['flags']), 'unknown flags')
            result[key] = (['V4L2_HEVC_DPB_ENTRY_LONG_TERM_REFERENCE'] if tokens else []) if name == 'v4l2_hevc_dpb_entry' else sorted(tokens)
            continue
        arr = field['shape']
        items = item if arr else [item]
        if arr:
            need(type(items) is list and len(items) == math.prod(arr), 'missing/extra array elements')
        checked = []
        for v in items:
            typ = field['type']
            if typ.startswith('struct '):
                checked.append(payload(v, typ[7:]))
            else:
                signed, bits = typ[2] == 's', int(typ[3:])
                checked.append(integer(v, -(2**(bits-1)) if signed else 0,
                                       2**(bits-1)-1 if signed else 2**bits-1))
        result[key] = checked if arr else checked[0]
    return result


def set_timestamp(buf, token):
    buf['timestamp_ns'] = token
    buf['timestamp'] = dict(tv_sec=token // 1000000000, tv_usec=(token // 1000) % 1000000)


def normalize(events, expected, run):
    events = copy.deepcopy(events)
    request_events = [e for e in events if e.get('ioctl') == 'VIDIOC_S_EXT_CTRLS'
                      and base.controls(e)[0]['which'] == 'V4L2_CTRL_WHICH_REQUEST_VAL'
                      and base.CID + 'DECODE_PARAMS' in base.controls(e)[1]]
    need(request_events and len({e['fd'] for e in request_events}) == 1, 'missing/multiple decoding contexts')
    fd = integer(request_events[0]['fd'])
    pending, out_buffers, completed_writers = {}, {}, {}
    control_sets, controls_by_fd, originals, input_changes = [], {}, {}, {}
    selected, raw_stamps, seq, queued = [], [], 0, 0
    for e in events:
        op = e.get('ioctl')
        if op == 'VIDIOC_S_EXT_CTRLS' and e.get('fd') == fd:
            need('errno' not in e, 'control submission failed')
            ext, cs = base.controls(e)
            if ext['which'] != 'V4L2_CTRL_WHICH_REQUEST_VAL':
                need(ext['which'] == 'V4L2_CTRL_WHICH_CUR_VAL' and not seq and not queued,
                     'current controls changed during decode')
                # Initial negotiation/current values do not replace the required
                # complete first queued request. Keep originals privately.
                continue
            reqfd = integer(ext['request_fd'])
            returned_ext, returned_cs = base.controls(dict(from_userspace=e['from_driver']))
            need(returned_ext['which'] == ext['which'] and returned_ext['request_fd'] == reqfd
                 and set(returned_cs) == set(cs), 'returned control identity mismatch')
            before_cs = copy.deepcopy(cs)
            # The lifecycle checker consumes a private projection of the actual
            # successful ioctl return values, not guessed zero/default fields.
            ext['controls'] = copy.deepcopy(returned_ext['controls'])
            _, cs = base.controls(e)
            need(set(cs) <= {base.CID+n for n in SIZES}, 'unsupported control')
            req = controls_by_fd.setdefault(reqfd, {})
            need(not req.keys() & cs.keys(), 'duplicate request control')
            original = originals.setdefault(reqfd, {})
            changes = input_changes.setdefault(reqfd, [])
            for cid, c in cs.items():
                name = cid.removeprefix(base.CID)
                need(integer(c['size']) == integer(before_cs[cid]['size']) == SIZES[name], 'unsupported dynamic extent')
                key = 'v4l2_ctrl_hevc_' + name.lower()
                original[name] = payload(c[key], key)
                before = payload(before_cs[cid][key], key)
                if name == 'SLICE_PARAMS':
                    need(c[key]['num_entry_point_offsets'] == before['num_entry_point_offsets'] == 0,
                         'entry points not captured by this contract')
                if name == 'DECODE_PARAMS':
                    dp = c[key]; n = integer(dp['num_active_dpb_entries'], high=16)
                    need(before == original[name], 'unexpected kernel reference correction')
                    for i, ent in enumerate(dp['dpb']):
                        if i < n:
                            # Gst can queue a reference before userspace dequeues
                            # its completed CAPTURE. Keep its queued identity;
                            # lifecycle validation below still requires all actual
                            # completions and the correct latest target generation.
                            matches = {w['token']: w for w in
                                       list(completed_writers.values()) + list(pending.values())
                                       if w['raw'] == ent['timestamp']}
                            need(len(matches) == 1, 'unknown/ambiguous timestamp writer at control submission')
                            ent['timestamp'] = next(iter(matches))
                        else:
                            ent['timestamp'] = 0  # Inactive timestamp is deliberately unavailable.
                        out = original[name]['dpb'][i]
                        out.pop('timestamp')
                        out['timestamp_writer'] = ent['timestamp'] // 1000 if i < n else None
                    before = copy.deepcopy(original[name])
                for field, value in original[name].items():
                    if before[field] != value:
                        changes.append(dict(control=name, field=field,
                                            submitted=before[field], returned=value))
                req[cid] = c
        elif op == 'VIDIOC_QBUF' and e.get('fd') == fd and 'errno' not in e:
            b = base.arguments(e, 'from_userspace', 'v4l2_buffer')
            if b['type'] == base.OUT:
                raw = base.timestamp(b); bi = integer(b['index'])
                need(raw not in pending and bi not in out_buffers, 'timestamp/output reused while pending')
                seq += 1
                raw_stamps.append(raw)
                p = dict(raw=raw, token=seq*1000, out=False, cap=False)
                pending[raw] = p; out_buffers[bi] = p
                set_timestamp(b, p['token'])
        elif op == 'VIDIOC_DQBUF' and e.get('fd') == fd and 'errno' not in e:
            b = base.arguments(e, 'from_driver', 'v4l2_buffer')
            raw = base.timestamp(b); need(raw in pending, 'orphan completion')
            p = pending[raw]; bi = integer(b['index'])
            if b['type'] == base.OUT:
                need(not p['out'] and out_buffers.pop(bi, None) is p, 'wrong OUTPUT completion')
                p['out'] = True
            elif b['type'] == base.CAP:
                need(not p['cap'], 'duplicate CAPTURE completion')
                p['cap'] = True; completed_writers[bi] = dict(raw=raw, token=p['token'])
            else:
                raise base.Reject('unsupported queue')
            set_timestamp(b, p['token'])
            if p['out'] and p['cap']:
                del pending[raw]
        elif op == 'VIDIOC_STREAMOFF' and e.get('fd') == fd:
            need('errno' not in e and queued == expected and all(p['cap'] for p in pending.values()),
                 'stream stopped with missing capture')
            if e.get('from_userspace', {}).get('type') == base.OUT:
                pending.clear(); out_buffers.clear()
        elif op == 'MEDIA_REQUEST_IOC_QUEUE':
            reqfd = integer(e['fd']); need(reqfd in originals, 'orphan request queue')
            cs = originals.pop(reqfd); controls_by_fd.pop(reqfd)
            need(set(cs) >= {'PPS', 'DECODE_PARAMS', 'SCALING_MATRIX', 'SLICE_PARAMS'}, 'missing per-request controls')
            submitted = sorted(cs)
            if 'SPS' in cs:
                sps_from = queued + 1
            else:
                need(control_sets, 'first request SPS missing')
                sps_from = control_sets[-1]['sps_from_picture']
                cs['SPS'] = copy.deepcopy(control_sets[-1]['controls']['SPS'])
            queued += 1
            control_sets.append(dict(picture=queued, submitted=submitted,
                                     sps_from_picture=sps_from, controls=cs,
                                     input_changes=input_changes.pop(reqfd)))
        selected.append(e)
    need(seq == queued == expected and not pending and not out_buffers and not originals,
         'incomplete request/completion history')
    refs, pictures = lifecycle.normalize(selected, expected, run)
    for pic, raw in zip(pictures, raw_stamps):
        need(pic['system_frame_number'] == pic['pic'], 'request queue differs from output submission order')
        pic['system_frame_number'] = raw // 1000
    # The existing adapter proves allocation/queue/reinit/teardown, timestamp-copy,
    # completed target, active references/POC and destination/reuse invariants.
    for full, ref in zip(control_sets, refs):
        full.update(schema='hevc-full-controls/1', run=run, target=ref['target'], poc=ref['poc'])
        for i, ent in enumerate(full['controls']['DECODE_PARAMS']['dpb']):
            if i < len(ref['dpb']):
                writer = ent['timestamp_writer']
                need(1 <= writer < full['picture'] and refs[writer-1]['target'] == ref['dpb'][i]['buf'],
                     'logical writer differs from lifecycle association')
    return control_sets, refs, pictures


def extra_evidence(events, expected):
    """Whitelisted mode observations and per-QBUF compressed-input digests.

    Hash the actual pre-QBUF dump, not media inferred from the source filename.
    This is not a measurement of bytes later read by DMA/firmware.
    """
    cids = {base.CID+'DECODE_MODE': 'V4L2_STATELESS_HEVC_DECODE_MODE_FRAME_BASED',
            base.CID+'START_CODE': 'V4L2_STATELESS_HEVC_START_CODE_NONE'}
    candidates = [e['fd'] for e in events if e.get('ioctl') == 'VIDIOC_S_EXT_CTRLS'
                  and base.controls(e)[0]['which'] == 'V4L2_CTRL_WHICH_REQUEST_VAL'
                  and base.CID+'DECODE_PARAMS' in base.controls(e)[1]]
    need(candidates and len(set(candidates)) == 1, 'missing/multiple contexts')
    fd = candidates[0]; modes = {}; hashes = []; dump = None; queued = False
    exports = {}
    for event in events:
        if 'close' in event and 'errno' not in event:
            # An exported FD may be reused by another object after close.
            # Its old context/index binding must not authenticate later dumps.
            exports.pop(event.get('fd'), None)
        if event.get('mem_dump') == base.OUT:
            need(event.get('fd') == fd or exports.get(event.get('fd')) == event.get('index'),
                 'payload dump belongs to an unbound export/context')
        elif event.get('fd') != fd:
            continue
        op = event.get('ioctl')
        if op == 'VIDIOC_EXPBUF' and 'errno' not in event:
            exp = base.arguments(event, 'from_driver', 'v4l2_exportbuffer')
            if exp['type'] == base.OUT:
                need(exp['plane'] == 0, 'multi-plane encoded export')
                exports[integer(exp['fd'])] = integer(exp['index'])
        if op in ('VIDIOC_S_EXT_CTRLS', 'VIDIOC_G_EXT_CTRLS') and 'errno' not in event:
            ext, cs = base.controls(dict(from_userspace=event['from_driver']))
            if set(cs) & set(cids):
                need(not queued and ext['which'] == 'V4L2_CTRL_WHICH_CUR_VAL', 'late/request mode operation')
                for cid, c in cs.items():
                    need(cid in cids and c['value'] == cids[cid] and type(c['size']) is int and c['size']==0,
                         'unsupported mode')
                    need(cid not in modes, 'duplicate mode observation')
                    modes[cid] = dict(value=c['value'], observed_by=op)
        if event.get('mem_dump') == base.OUT:
            need(dump is None, 'orphan/duplicate payload dump')
            lines = event['mem_array']
            need(type(lines) is list and lines and all(type(s) is str and re.fullmatch(r'[0-9a-f ]+',s) for s in lines),
                 'invalid encoded dump')
            data = bytes.fromhex(''.join(lines))
            need(0 < len(data) == integer(event['bytesused'], high=16*1024*1024), 'incomplete encoded dump')
            dump = dict(index=integer(event['index']), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        if op == 'VIDIOC_QBUF':
            b = base.arguments(event, 'from_userspace', 'v4l2_buffer')
            if b['type'] == base.OUT:
                need('errno' not in event and dump is not None, 'failed/unobserved source queue')
                planes=b['m']['planes']
                need(b['index']==dump['index'] and b['length']==len(planes)==1
                     and planes[0]['bytesused']==dump['bytes'] and planes[0]['data_offset']==0,
                     'payload dump does not match queued extent')
                hashes.append(dict(picture=len(hashes)+1, bytes=dump['bytes'], sha256=dump['sha256']))
                dump=None; queued=True
    need(set(modes)==set(cids) and dump is None and len(hashes)==expected, 'incomplete modes/input payloads')
    return dict(modes=modes, encoded_inputs=hashes)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('trace', type=Path)
    ap.add_argument('--expected-pictures', type=int, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    try:
        raw = base.load(args.trace); sha = hashlib.sha256(raw).hexdigest()
        events = base.parse(raw)
        full, refs, _ = normalize(events, args.expected_pictures, sha[:16])
        extra = extra_evidence(events, args.expected_pictures)
        with args.output.open('x') as out:
            json.dump(dict(raw_sha256=sha, controls=full, refs=refs, **extra), out, separators=(',', ':'))
            out.write('\n')
        print(f'Validated {len(full)} complete requests')
    except (ValueError, KeyError, TypeError, IndexError, OSError, UnicodeError, RecursionError):
        print('Rejected unavailable/ambiguous control evidence', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
