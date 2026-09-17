#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline predictions from a narrow HEVC reference subset, never hardware traces.

Source-derived from AsahiLinux/linux 94fb23346d522edf53722357c426a3e58030beea;
see source-map.json and README. Kernel AVD credits belong to the Asahi Linux
Contributors (HEVC implementation: Eileen Yoon and credited upstream authors).
"""

ALL = 0xffffffff
SCHEMA = 'libva-v4l2request.hevc-refs/1'


class Reject(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Reject(reason)


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, 'invalid integer/range')
    return value


def word(fields):
    """OR masked contributions; unknown inputs stay unknown unless known ones win."""
    value = unknown = 0
    missing = []
    for name, mask, bits in fields:
        if bits is None:
            unknown |= mask
            missing.append(name)
        else:
            require(type(bits) is int and bits & ~mask == 0, 'word field outside mask')
            value |= bits
    unknown &= ~value
    return dict(known_mask=f'0x{ALL ^ unknown:08x}', known_value=f'0x{value:08x}',
                value=None if unknown else f'0x{value:08x}', unknown_inputs=missing)


def ref_header(count, long_term, slice_poc=None, reference_poc=None):
    integer(count, 1, 16); integer(long_term, 0, 1)
    delta = None
    if slice_poc is not None and reference_poc is not None:
        integer(slice_poc, -(1 << 31), (1 << 31) - 1)
        integer(reference_poc, -(1 << 31), (1 << 31) - 1)
        # Avoid pretending C signed-subtraction overflow has defined semantics.
        delta = integer(slice_poc - reference_poc, -(1 << 31), (1 << 31) - 1) & 0x1ffff
    return word([('count_minus_one', 0xf0000000, (count - 1) << 28),
                 ('constant', 1 << 24, 1 << 24),
                 ('long_term', 1 << 17, long_term << 17),
                 ('slice_pic_order_cnt', 0x1ffff, delta)])


def ref_list_word(which, position, slot):
    integer(which, 0, 1); integer(position, 0, 15); integer(slot, 0, 15)
    return f'0x{0x2dc00000 | which << 8 | position << 4 | slot:08x}'


def kernel_lookup(buffers, timestamp, destination):
    """Synthetic explicit kernel snapshot only; real captures lack this snapshot.

    vb2_find_buffer scans by index, requires copied_timestamp, then compares the
    timestamp. avd_get_ref_buf falls back to destination on a miss.
    """
    integer(timestamp, 0, (1 << 64) - 1)
    indices = [b['index'] for b in buffers]
    require(len(set(indices)) == len(indices) and destination in indices, 'ambiguous buffer snapshot')
    for b in buffers:
        integer(b['index'], 0, (1 << 32) - 1)
        require(type(b['copied_timestamp']) is bool, 'missing timestamp validity')
        integer(b['timestamp'], 0, (1 << 64) - 1)
    for b in sorted(buffers, key=lambda b: b['index']):
        if b['copied_timestamp'] and b['timestamp'] == timestamp:
            return dict(index=b['index'], fallback=False)
    return dict(index=destination, fallback=True)


def motion(slice_, refs):
    typ, tmvp = slice_['type'], slice_['tmvp']
    if typ == 'I':
        return dict(lookup='skipped: I-slice early return', collocated=None,
                    expected_ref_valid=False, address_emission='absent',
                    word=word([('I early return', ALL, 0x2d020000)]))
    # Even with TMVP disabled, the C code performs lookup before the gate; raw
    # inactive col bytes are absent from this schema, so do not reconstruct it.
    col = None
    ref_valid = False if not tmvp else None
    reason = 'TMVP disabled' if not tmvp else 'dependent-segment flag is unrecorded'
    if tmvp:
        selected = slice_['l0'] if typ == 'P' or slice_['col_l0'] else slice_['l1']
        index = integer(slice_['col'], 0, len(selected) - 1)
        col = refs[selected[index]]['writer']
        if col['is_intra']:
            ref_valid = False
            reason = 'expected referenced writer is intra'
    fields = [('opcode', 0xff000000, 0x2d000000),
              ('five_minus_max_num_merge_cand', 0xe, None),
              ('col_from_l1_flag', 0x10, int(bool(tmvp and not slice_.get('col_l0', 0))) << 4),
              ('CABAC_INIT', 0x20, None), ('MVD_L1_ZERO', 0x40, None),
              ('num_ref_idx_l0_active_minus1', 0xf800, (len(slice_['l0']) - 1) << 11),
              ('num_ref_idx_l1_active_minus1', 0x780,
               (len(slice_['l1']) - 1) << 7 if typ == 'B' else None),
              ('DEPENDENT_SLICE_SEGMENT/FLAG2', 0x8000, 0x8000 if tmvp else None),
              ('P-slice', 0x10000, int(typ == 'P') << 16),
              ('ref_valid', 0x40000, None if ref_valid is None else int(ref_valid) << 18)]
    return dict(lookup='unobserved; expected writer from submitted trace' if tmvp else
                       'unavailable: raw inactive collocated fields not recorded',
                collocated=col, expected_ref_valid=ref_valid, gate_reason=reason,
                address_emission='absent' if ref_valid is False else 'unknown: dependent-segment flag',
                address_if_enabled=None if col is None else dict(
                    buffer=col['buffer'], writer_picture=col['picture'], generation=col['generation'],
                    expression='plane0_dma + plane0_length - ceil(fmt_width/64)*ceil(fmt_height/64)*256',
                    value=None, missing=['plane0_dma', 'plane0_length', 'fmt_width', 'fmt_height']),
                word=word(fields))


def map_records(records, expected):
    """One context, one complete progressive slice/request per picture; unique POC.

    Callers also run the trusted strict checker. This second validator rejects
    stale POC/buffer writers and unsupported model domains rather than guessing.
    """
    integer(expected, 1, 10000)
    require(len(records) == expected, 'incomplete extent')
    writers, generations, pocs, mapped = {}, {}, set(), []
    context = run = None
    for ordinal, r in enumerate(records, 1):
        require(r['schema'] == SCHEMA, 'unsupported schema')
        if ordinal == 1:
            context, run = r['ctx'], r['run']
        require(r['ctx'] == context and r['run'] == run, 'mixed context/run')
        for key in ('seq', 'pic', 'req'):
            require(integer(r[key], 1, 10000) == ordinal, 'incomplete or reordered picture')
        require(r['first'] == r['last'] == 1 and not r.get('slices_omitted', 0), 'batched/omitted picture')
        integer(r['poc'], -(1 << 31), (1 << 31) - 1)
        require(r['poc'] not in pocs, 'repeated POC/epoch outside model domain')
        pocs.add(r['poc'])
        target = integer(r['target'], 0, (1 << 32) - 1)
        require(len(r['slices']) == 1, 'model requires exactly one slice')
        s = r['slices'][0]
        require(s['i'] == 0 and s['type'] in ('I', 'P', 'B'), 'unsupported slice')
        integer(s['tmvp'], 0, 1)
        require(len(r['dpb']) <= 16, 'oversized DPB')
        refs, seen_buffers = [], set()
        for slot, e in enumerate(r['dpb']):
            require(e['i'] == slot and e['field'] == 0, 'unsupported DPB layout/field')
            integer(e['lt'], 0, 1)
            require(e['buf'] != target and e['buf'] not in seen_buffers, 'destination/duplicate DPB alias')
            seen_buffers.add(e['buf'])
            previous = writers.get(e['buf'])
            require(previous is not None and previous['poc'] == e['poc'], 'unresolved/stale buffer writer')
            refs.append(dict(slot=slot, writer=previous.copy(), long_term=e['lt'],
                             header=ref_header(len(r['dpb']), e['lt']),
                             header_if_slice_poc_equals_decode_poc=
                                 ref_header(len(r['dpb']), e['lt'], r['poc'], e['poc'])['value'],
                             compressed_address=dict(value=None, buffer=e['buf'],
                                 expression='plane0_dma + reference.comp.start_offset',
                                 missing=['plane0_dma', 'reference.comp.start_offset', 'reference.comp.offsets[4]'])))
        for key in ('st_before', 'st_after', 'lt_curr'):
            for i in r[key]:integer(i, 0, len(refs) - 1)
        lists = {}
        for li, key in enumerate(('l0', 'l1')):
            require(len(s[key]) <= 16, 'oversized active list')
            lists[key] = []
            for i, slot in enumerate(s[key]):
                integer(slot, 0, len(refs) - 1)
                lists[key].append(dict(position=i, slot=slot, word=ref_list_word(li, i, slot),
                                       writer=refs[slot]['writer']))
        require((s['type'] == 'I' and not s['l0'] and not s['l1']) or
                (s['type'] == 'P' and s['l0'] and not s['l1']) or
                (s['type'] == 'B' and s['l0'] and s['l1']), 'slice/list mismatch')
        if s['tmvp']:
            integer(s['col_l0'], 0, 1)
            integer(s['col'], 0, 255)
        prior = writers.get(target)
        generations[target] = generations.get(target, 0) + 1
        current = dict(picture=ordinal, poc=r['poc'], buffer=target,
                       generation=generations[target], is_intra=s['type'] == 'I')
        mapped.append(dict(picture=ordinal, poc=r['poc'], slice_type=s['type'], nal=s['nal'],
                           destination=current, previous_destination_writer=prior,
                           dpb=refs, reference_table_emitted=s['type'] != 'I', lists=lists,
                           motion=motion(s, refs)))
        # Kernel updates destination metadata before command building. Aliases
        # were rejected above; this represents expected history, not observation.
        writers[target] = current
    return mapped
