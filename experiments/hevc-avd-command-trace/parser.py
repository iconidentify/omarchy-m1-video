#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fail-closed command snapshot reader. Word verification uses pinned C in oracle.py."""
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
CMD_PACKED, CMD_CONTROL = 1380, 1392
CMD_SITE_QP, CMD_SITE_DBLK, CMD_SITE_WT_HDR, CMD_SITE_WT_SKIP = 20, 21, 22, 27
CMD_SITE_SLICE_META = 31
WINDOW_SIZE = 7596
CAPTURE_SIZE = (64 + 300 * 24 + 11 * WINDOW_SIZE + 7) // 8 * 8

class MissingInput(ValueError):
    pass

def need(ok, reason):
    if not ok:
        raise MissingInput(reason)

def layout():
    result = []
    for line in (HERE / 'kernel/control-layout.inc').read_text().splitlines():
        m = re.fullmatch(r'FIELD\((U8|S8|U16|U32|S32|U64|BYTES), (\w+), ([\w>\-]+), (\d+)\)', line)
        if m:
            kind, name, member, count = m.groups()
            result.append((kind, name, int(count) if kind == 'BYTES' else int(kind[1:]) // 8))
        else:
            need(not line or line.startswith('/*'), 'unknown wire layout line')
    need(sum(n for _, _, n in result) == CMD_PACKED, 'wire layout extent changed')
    return result

LAYOUT = layout()

def unpack_controls(buf):
    need(isinstance(buf, (bytes, bytearray)) and len(buf) == CMD_CONTROL,
         'controls require exactly 1392 bytes')
    need(not any(buf[CMD_PACKED:]), 'nonzero wire padding')
    c, i = {}, 0
    for kind, name, count in LAYOUT:
        data = buf[i:i + count]
        c[name] = list(data) if kind == 'BYTES' else int.from_bytes(data, 'little', signed=kind.startswith('S'))
        i += count
    return c

def pack_controls(c):
    """Offline fixture encoder: every field is mandatory, range checked."""
    need(set(c) == {name for _, name, _ in LAYOUT}, 'missing/unknown control fields')
    data = bytearray()
    for kind, name, count in LAYOUT:
        v = c[name]
        if kind == 'BYTES':
            need(isinstance(v, list) and len(v) == count and all(type(x) is int and 0 <= x <= 255 for x in v), 'array domain: ' + name)
            data.extend(v)
        else:
            need(type(v) is int, 'scalar domain: ' + name)
            try:
                data.extend(v.to_bytes(count, 'little', signed=kind.startswith('S')))
            except OverflowError as exc:
                raise MissingInput('scalar range: ' + name) from exc
    return bytes(data) + bytes(CMD_CONTROL - CMD_PACKED)

def validate_controls(c):
    """The narrow one-slice/no-tiles host-execution domain; never fix up inputs."""
    for name, mask in [('sps_flags', 511), ('pps_flags', (1 << 21) - 1),
                       ('slice_flags', 1023), ('decode_flags', 7)]:
        need(c[name] & ~mask == 0, 'unknown control flags: ' + name)
    need(c['slice_type'] in (0, 1, 2), 'unknown slice type')
    need(not c['pps_flags'] & (1 << 11) and c['num_entry_point_offsets'] == 0,
         'tiles/entry points outside experiment')
    need(c['num_tile_columns_minus1'] == c['num_tile_rows_minus1'] == 0,
         'unexpected inactive tile geometry')
    need(c['chroma_format_idc'] == 1 and c['bit_depth_luma_minus8'] in (0, 2) and
         c['bit_depth_luma_minus8'] == c['bit_depth_chroma_minus8'], 'depth/chroma outside experiment')
    need(all(0 < c[k] <= 16384 for k in ('pic_width_in_luma_samples', 'pic_height_in_luma_samples')), 'dimensions outside domain')
    log2 = 3 + c['log2_min_luma_coding_block_size_minus3'] + c['log2_diff_max_min_luma_coding_block_size']
    need(3 <= log2 <= 6, 'invalid CTB size')
    ctbs = ((c['pic_width_in_luma_samples'] + (1 << log2) - 1) >> log2) * ((c['pic_height_in_luma_samples'] + (1 << log2) - 1) >> log2)
    need(c['slice_segment_addr'] < ctbs, 'slice start outside picture')
    need(c['num_ref_idx_l0_active_minus1'] < 16 and c['num_ref_idx_l1_active_minus1'] < 16, 'reference extent')
    need(0 <= c['luma_log2_weight_denom'] <= 7 and
         0 <= c['luma_log2_weight_denom'] + c['delta_chroma_log2_weight_denom'] <= 7,
         'weight shift outside domain')
    need(c['bit_size'] <= (1 << 31) - 1 and 0 <= c['data_byte_offset'] < c['bit_size'] // 8,
         'coded extent outside source int domain')
    need(0 <= c['init_qp_minus26'] + 26 + c['slice_qp_delta'] <= 51 + 6*c['bit_depth_luma_minus8'], 'QP outside experiment')
    for k in ('pps_cb_qp_offset', 'pps_cr_qp_offset', 'slice_cb_qp_offset', 'slice_cr_qp_offset'):
        need(-12 <= c[k] <= 12, 'QP offset outside domain')
    for k in ('slice_beta_offset_div2', 'slice_tc_offset_div2'):
        need(-6 <= c[k] <= 6, 'deblock offset outside domain')

def unsigned(token, bits=64):
    need(token.isascii() and token.isdecimal() and len(token) <= 20, 'noncanonical integer')
    n = int(token)
    need(str(n) == token and n < 1 << bits, 'integer range/noncanonical spelling')
    return n

def signed32(n):
    return n if n < 1 << 31 else n - (1 << 32)

def parse_snapshot(text, expected_run):
    need(type(expected_run) is int and 0 < expected_run < 1 << 64, 'expected run required')
    need(len(text.encode()) <= 512 * 1024, 'snapshot too large')
    lines = text.splitlines()
    need(len(lines) == 323, 'require header, 300 histories and 11 complete windows')
    h = lines[0].split()
    need(len(h) == 14 and h[0] == 'H', 'header shape')
    version, run, context, phase, errors, pictures, done, cap, first, last, words, size, wsize = map(unsigned, h[1:])
    need((version, run, phase, errors) == (2, expected_run, 4, 0) and context > 0, 'wrong run/context/schema or invalid capture')
    need((pictures, done, cap, first, last, words, size, wsize) ==
         (300, 300, 2048, 24, 34, 1024, CAPTURE_SIZE, WINDOW_SIZE), 'extent/layout mismatch')
    histories, windows = [], []
    for pic, line in enumerate(lines[1:301], 1):
        p = line.split()
        need(len(p) == 7 and p[0] == 'P', 'history shape')
        number, poc, kind, target, flags, intra = [unsigned(x, 32) for x in p[1:]]
        need(number == pic and kind in (0, 1, 2) and flags & ~7 == 0 and intra == (kind == 2), 'history sequence/type/flags')
        histories.append(dict(picture=number, poc=signed32(poc), type=kind, target=target, flags=flags, intra=intra))
    for slot, pic in enumerate(range(24, 35)):
        w = lines[301 + slot * 2].split()
        need(len(w) >= 11 and w[0] == 'W', 'window shape')
        number, poc, kind, nwords, nbytes, inactive, decomp, revision, quirks, stride = [unsigned(x, 32) for x in w[1:11]]
        need(number == pic and (signed32(poc), kind) == (histories[pic-1]['poc'], histories[pic-1]['type']), 'window/history binding')
        need(0 < nwords <= 1024 and nbytes == CMD_CONTROL and len(w) == 11+2*nwords, 'word/control extent')
        need(decomp in (0, 1) and revision in (3, 4) and quirks & ~3 == 0 and 0 < stride < 1 << 24,
             'missing/unknown kernel context inputs')
        need(inactive & ~((1 << 19) | (1 << 27)) == 0, 'unknown inactive bits')
        pairs = [unsigned(x, 32) for x in w[11:]]
        sites, values = pairs[::2], pairs[1::2]
        need(all(1 <= site <= 32 for site in sites), 'unknown word site')
        raw = lines[302+slot*2].split()
        need(len(raw) == CMD_CONTROL+1 and raw[0] == 'C', 'control row shape')
        buf = bytes(unsigned(x, 8) for x in raw[1:])
        c = unpack_controls(buf); validate_controls(c)
        need((c['slice_pic_order_cnt'], c['slice_type'], c['decode_flags']) ==
             (signed32(poc), kind, histories[pic-1]['flags']), 'copied controls bound to wrong job')
        expected_inactive = ((1 << 19) if not c['sps_flags'] & 2 else 0) | ((1 << 27) if kind == 2 else 0)
        need(inactive == expected_inactive, 'missing/contradictory inactive state')
        windows.append(dict(picture=pic, poc=signed32(poc), type=kind, nwords=nwords, nbytes=nbytes,
                            inactive=inactive, sites=sites, words=values, controls=buf,
                            decomp=decomp, revision=revision, quirks=quirks, bytesperline=stride))
    return dict(run=run, context=context, pictures=histories, windows=windows)

def bind_history(capture, reference):
    """Mandatory same-run schema-2 reference history, including writer generations.

    Call the accepted read_capture AND validate first; this compares the entire
    start history, not an arbitrary list of expected words supplied by a caller.
    """
    need((capture['run'], capture['context']) == (reference['run'], reference['context']), 'paired trace identity')
    starts = [r for r in reference['records'] if r['kind'] == 1]
    need(len(starts) == 300, 'paired writer history extent')
    for own, ref in zip(capture['pictures'], starts):
        need((own['picture'], own['poc'], own['type'], own['target'], own['intra']) ==
             (ref['picture'], ref['poc'], ref['type'], ref['buffer'], ref['intra']), 'paired writer/job mismatch')

# Small independent arithmetic checks supplement, never replace the C oracle.
def predict_qp(c):
    keys = ('init_qp_minus26','slice_qp_delta','pps_cb_qp_offset','pps_cr_qp_offset','slice_cb_qp_offset','slice_cr_qp_offset')
    need(all(k in c and type(c[k]) is int for k in keys), 'QP inputs missing')
    return 0x2d900000 | ((c['init_qp_minus26']+26+c['slice_qp_delta']) & 255) << 10 | ((c['pps_cb_qp_offset']+c['slice_cb_qp_offset']) & 31) << 5 | ((c['pps_cr_qp_offset']+c['slice_cr_qp_offset']) & 31)

def classify_weights(row):
    sites, words = row['sites'], row['words']
    weight = [word for site, word in zip(sites, words) if 22 <= site <= 26]
    if row['inactive'] & (1 << 27):
        need(not weight, 'skipped weights also emitted'); return 'skipped'
    need(bool(weight), 'weight state missing')
    return 'default-header' if weight == [0x2dd00000] else 'weighted'
