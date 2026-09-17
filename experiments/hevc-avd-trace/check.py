#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Strict offline reader. Raw timestamps stay private; findings are not fixes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'hevc-avd-map'))
import model

CAPACITY, VALUES, PICTURES, FIRST, LAST = 2048, 72, 300, 24, 34
RECORD_SIZE = (5 + VALUES) * 8
TMVP, MVD_ZERO, CABAC, COL_L0, DEPENDENT = 4, 8, 16, 32, 512
TYPES = {0: 'B', 1: 'P', 2: 'I'}
BUFFER = ('buffer timestamp copied intra writer completed allocation length '
          'comp_start comp_size off0 off1 off2 off3 mv_size mv_offset bounds memory').split()
START = 'previous_writer poc slice_poc type slices entries dpb_count width height'.split() + BUFFER
TABLE = 'slot poc flags requested_timestamp word matched'.split() + BUFFER + ['emitted_comp' + str(i) for i in range(4)]
MOTION = ('flags type merge l0_minus1 l1_minus1 col_index first slot requested_timestamp '
          'lookup matched valid word emitted').split() + BUFFER + ['l0_' + str(i) for i in range(16)] + ['l1_' + str(i) for i in range(16)] + ['emitted_mv', 'quirks']
FIELDS = {1: START, 2: ['result'] + BUFFER, 3: TABLE,
          4: ['list', 'position', 'slot', 'word'], 5: MOTION}


class Reject(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise Reject(message)


def unsigned(token):
    need(token.isascii() and token.isdecimal() and len(token) <= 20, 'noncanonical unsigned integer')
    value = int(token)
    need(str(value) == token and value < 2**64, 'integer out of range/noncanonical')
    return value


def signed32(value):
    need(0 <= value < 2**32, 'POC outside encoded s32')
    return value if value < 2**31 else value - 2**32


def read_capture(text, expected_run):
    need(len(text.encode()) <= 4 * 1024 * 1024, 'oversized snapshot')
    lines = text.splitlines()
    need(lines and len(lines) <= CAPACITY + 1, 'empty/oversized extent')
    h = lines[0].split()
    need(len(h) == 14 and h[0] == 'H', 'missing/invalid header')
    version, run, ctx, phase, errors, count, attempted, pictures, done, cap, first, last, size = map(unsigned, h[1:])
    need(version == 1 and run == expected_run and run > 0 and ctx > 0, 'wrong schema/run/context')
    need(phase == 4 and errors == 0, 'unsealed or kernel-invalid capture')
    need((pictures, done, cap, first, last, size) == (PICTURES, PICTURES, CAPACITY, FIRST, LAST, RECORD_SIZE), 'wrong extent/schema constants')
    need(count == attempted == len(lines) - 1 and 600 <= count <= 1139, 'loss/overflow/extent mismatch')
    rows = []
    for sequence, line in enumerate(lines[1:], 1):
        tokens = line.split()
        need(len(tokens) == VALUES + 6 and tokens[0] == 'R', 'missing/extra record inputs')
        rr, rc, seq, kind, pic, *values = map(unsigned, tokens[1:])
        need((rr, rc, seq) == (run, ctx, sequence), 'wrong context/run or missing/duplicate sequence')
        need(kind in FIELDS and 1 <= pic <= PICTURES, 'unknown kind/picture')
        keys = FIELDS[kind]
        need(not any(values[len(keys):]), 'unknown nonzero reserved inputs')
        row = dict(zip(keys, values))
        row.update(kind=kind, picture=pic)
        for field in ('poc', 'slice_poc'):
            if field in row:
                row[field] = signed32(row[field])
        rows.append(row)
    return {'run': run, 'context': ctx, 'records': rows, 'count': count}


def motion_word(m):
    if m['type'] == 2:
        return 0x2d020000
    f = m['flags']
    need(0 <= m['merge'] <= 4 and m['l0_minus1'] < 16 and m['l1_minus1'] < 16,
         'motion controls outside experiment domain')
    return (0x2d000000 | (5 - m['merge']) << 1 | bool(f & TMVP and not f & COL_L0) << 4 |
            bool(f & CABAC) << 5 | (not bool(f & MVD_ZERO)) << 6 |
            m['l0_minus1'] << 11 | m['l1_minus1'] << 7 |
            bool(f & (TMVP | DEPENDENT)) << 15 | (m['type'] == 1) << 16 | m['valid'] << 18)


def validate(capture, expected=None):
    """Separate malformed evidence from measured discrepancies in valid records.

    expected is a same-campaign model.map_records result, never a historical oracle.
    A validated trace does not establish correct pixels or firmware semantics.
    """
    if expected is not None:
        need(len(expected) == PICTURES, 'incomplete userspace oracle')
    rows = capture['records']
    findings, starts, histories, allocations, timestamps = [], {}, {}, {}, {}
    normalized, group, next_picture = [], [], 1

    def finding(row, code):
        findings.append({'picture': row['picture'], 'kind': row['kind'], 'code': code})

    def check_value(row, condition, code):
        if not condition:
            finding(row, code)

    def buffer(row, start, destination=False):
        for name in ('copied', 'intra', 'completed', 'bounds'):
            need(row[name] in (0, 1), 'invalid buffer boolean')
        need(row['buffer'] < 2**32 and row['allocation'] > 0 and row['memory'] in (1, 4), 'invalid buffer/allocation/memory identity')
        need(0 < row['length'] < 2**32 and row['comp_start'] < 2**32 and row['comp_size'] < 2**32, 'layout outside plane domain')
        offsets = [row['off' + str(i)] for i in range(4)]
        need(all(x < 2**32 for x in offsets), 'invalid compressed offset')
        mv = ((start['width'] + 63) // 64) * ((start['height'] + 63) // 64) * 256
        valid = row['length'] >= mv and row['comp_start'] + row['comp_size'] <= row['length'] - mv and all(x < row['comp_size'] for x in offsets)
        need(row['mv_size'] == mv and row['mv_offset'] == max(0, row['length'] - mv) and row['bounds'] == valid, 'inconsistent layout snapshot')
        check_value(row, valid, 'allocation-range-out-of-bounds')
        check_value(row, row['copied'] == 1, 'copied-timestamp-invalid')
        if row['allocation'] in allocations:
            need(allocations[row['allocation']] == row['buffer'], 'allocation identity aliases buffer indices')
        allocations[row['allocation']] = row['buffer']
        if not destination:
            writer = histories.get((row['buffer'], row['allocation']))
            check_value(row, writer == row['writer'] and writer in starts, 'stale-or-unknown-writer')
            if row['writer'] in starts:
                known = starts[row['writer']]
                check_value(row, row['timestamp'] == known['timestamp'], 'writer-timestamp-mismatch')
                check_value(row, row['intra'] == (known['type'] == 2), 'writer-intra-mismatch')
            check_value(row, row['completed'] == 1, 'reference-writer-not-completed')

    def compare_expected(start, table, lists, motion):
        if expected is None:
            return
        pred = expected[start['picture'] - 1]
        if start['type'] != 2:
            check_value(start, len(table) == len(pred['dpb']), 'userspace-dpb-count-mismatch')
            for actual, reference in zip(table, pred['dpb']):
                writer = reference['writer']
                check_value(actual, (actual['slot'], actual['poc'], actual['flags'] & 1,
                             actual['buffer'], actual['writer'], actual['intra']) ==
                            (reference['slot'], writer['poc'], reference['long_term'],
                             writer['buffer'], writer['picture'], writer['is_intra']), 'userspace-reference-mismatch')
        for li in (0, 1):
            wanted = pred['lists']['l' + str(li)]
            actual = [r for r in lists if r['list'] == li]
            check_value(start, [(r['slot'], r['word']) for r in actual] ==
                        [(r['slot'], int(r['word'], 16)) for r in wanted], 'userspace-list-mismatch')
        mw = pred['motion']['word']
        check_value(motion, motion['word'] & int(mw['known_mask'], 16) == int(mw['known_value'], 16), 'userspace-known-motion-bit-mismatch')

    def check_group(g):
        start, done = g[0], g[-1]
        pic = start['picture']
        need(start['kind'] == 1 and done['kind'] == 2 and all(r['picture'] == pic for r in g), 'incomplete/mixed picture group')
        need(start['type'] in TYPES and start['slices'] == 1 and start['entries'] == 0 and start['dpb_count'] <= 16, 'unsupported slice/extent')
        need(0 < start['width'] <= 16384 and 0 < start['height'] <= 16384, 'invalid negotiated dimensions')
        need(start['writer'] == pic and start['completed'] == 0 and done['result'] == 5 and done['completed'] == 1, 'invalid start/completion state')
        need(all(start[k] == done[k] for k in BUFFER if k != 'completed'), 'destination changed before completion')
        need(start['timestamp'] not in timestamps, 'ambiguous/reused picture timestamp')
        timestamps[start['timestamp']] = pic
        prior = histories.get((start['buffer'], start['allocation']), 0)
        check_value(start, start['previous_writer'] == prior, 'destination-previous-writer-mismatch')
        check_value(start, start['intra'] == (start['type'] == 2), 'destination-intra-mismatch')
        if expected is not None:
            pred = expected[pic-1]
            check_value(start, (start['poc'], TYPES[start['type']], start['buffer']) ==
                        (pred['poc'], pred['slice_type'], pred['destination']['buffer']), 'userspace-picture-mismatch')
        starts[pic] = start
        histories[(start['buffer'], start['allocation'])] = pic
        buffer(start, start, True)
        detail = FIRST <= pic <= LAST
        table = [r for r in g if r['kind'] == 3]
        lists = [r for r in g if r['kind'] == 4]
        motion = [r for r in g if r['kind'] == 5]
        need(len(motion) == int(detail), 'missing/duplicate motion record')
        need(len(table) == (start['dpb_count'] if detail and start['type'] != 2 else 0), 'missing/extra table records')
        need([r['kind'] for r in g] == [1] + [3]*len(table) + [4]*len(lists) + [5]*len(motion) + [2], 'unexpected emission ordering')
        if not detail:
            need(not lists, 'command records outside window')
            return
        m = motion[0]
        need(m['type'] == start['type'] and m['first'] == 1, 'missing/invalid slice inputs')
        for k in ('lookup', 'matched', 'valid', 'emitted'):
            need(m[k] in (0, 1), 'invalid motion boolean')
        for li in (0, 1):
            need(all(m[f'l{li}_{i}'] <= 255 for i in range(16)), 'invalid raw reference byte')
        for i, r in enumerate(table):
            need(r['slot'] == i and r['matched'] in (0, 1), 'missing/duplicate table slot')
            buffer(r, start)
            check_value(r, r['matched'] == 1, 'reference-lookup-fallback')
            check_value(r, r['requested_timestamp'] == r['timestamp'], 'lookup-timestamp-mismatch')
            check_value(r, r['writer'] < pic, 'reference-aliases-current-destination')
            if r['writer'] in starts:
                check_value(r, starts[r['writer']]['poc'] == r['poc'], 'reference-poc-mismatch')
            header = model.ref_header(start['dpb_count'], int(bool(r['flags'] & 1)), start['slice_poc'], r['poc'])
            check_value(r, r['word'] == int(header['value'], 16), 'reference-header-word-mismatch')
            check_value(r, all(r['emitted_comp' + str(i)] == r['comp_start'] + r['off' + str(i)] for i in range(4)), 'compressed-address-mismatch')
        expected_lists = []
        if start['type'] != 2:
            need(m['l0_minus1'] < 16 and m['l1_minus1'] < 16, 'oversized lists')
            for li in range(2 if start['type'] == 0 else 1):
                for i in range(m[f'l{li}_minus1'] + 1):
                    slot = m[f'l{li}_{i}']
                    need(slot < len(table), 'active list outside recorded table')
                    expected_lists.append((li, i, slot, int(model.ref_list_word(li, i, slot), 16)))
        need(len(lists) == len(expected_lists), 'missing/extra list records')
        for r, wanted in zip(lists, expected_lists):
            need((r['list'], r['position']) == wanted[:2], 'missing/duplicate list position')
            check_value(r, (r['list'], r['position'], r['slot'], r['word']) == wanted, 'reference-list-word-mismatch')
        if start['type'] == 2:
            need(not any(m[k] for k in ['lookup','matched','valid','emitted','slot','requested_timestamp','emitted_mv'] + BUFFER), 'I-slice lookup/address violates early return')
        else:
            need(m['lookup'] == 1 and m['col_index'] < 16, 'non-I lookup omitted/invalid (including TMVP off)')
            li = 0 if start['type'] == 1 or m['flags'] & COL_L0 else 1
            slot = m[f'l{li}_{m["col_index"]}']
            need(slot < len(table), 'collocated slot outside experiment domain')
            check_value(m, m['slot'] == slot, 'collocated-slot-mismatch')
            buffer(m, start)
            check_value(m, m['matched'] == 1, 'motion-lookup-fallback')
            check_value(m, m['requested_timestamp'] == table[slot]['requested_timestamp'] == m['timestamp'], 'motion-lookup-timestamp-mismatch')
            check_value(m, all(m[k] == table[slot][k] for k in BUFFER), 'motion-table-state-mismatch')
            gate = bool(not m['flags'] & DEPENDENT and m['flags'] & TMVP and m['first'] and not m['intra'])
            check_value(m, m['valid'] == gate and m['emitted'] == gate, 'motion-gate-mismatch')
            check_value(m, m['emitted_mv'] == (m['mv_offset'] if m['emitted'] else 0), 'motion-address-mismatch')
        check_value(m, m['word'] == motion_word(m), 'full-motion-word-mismatch')
        check_value(start, start['slice_poc'] == start['poc'], 'slice-decode-poc-difference')
        compare_expected(start, table, lists, m)

    for row in rows:
        if row['kind'] == 1:
            need(not group and row['picture'] == next_picture, 'missing/duplicate/out-of-order picture')
        else:
            need(bool(group), 'record outside picture')
        group.append(row)
        if row['kind'] == 2:
            check_group(group)
            group = []
            next_picture += 1
    need(not group and next_picture == PICTURES + 1, 'missing final completion')
    for row in rows:
        out = row.copy()
        for field in ('timestamp', 'requested_timestamp'):
            if field in out:
                out[field + '_writer'] = timestamps.get(out.pop(field))
        normalized.append(out)
    return dict(schema='hevc-avd-trace.normalized/1', run=capture['run'], context=capture['context'],
                structural_validation='passed', userspace_correlated=expected is not None,
                findings=findings, records=normalized,
                limitations=['No pixel, firmware, boot or stability conclusion.',
                             'Allocation identities are vb2 attachment lifetimes, not proof of physical contents.',
                             'Matching commands do not exhaust decoder controls or firmware state.'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('snapshot', type=Path)
    p.add_argument('--run', required=True, type=int)
    p.add_argument('--userspace', type=Path, help='same-campaign normalized HEVC request JSONL, never old captures')
    args = p.parse_args()
    try:
        with args.snapshot.open('rb') as f:
            raw = f.read(4 * 1024 * 1024 + 1)
        need(len(raw) <= 4 * 1024 * 1024, 'oversized snapshot')
        expected = None
        if args.userspace:
            # Reuse the source-map parser's strict JSON duplicate/nonfinite rejection.
            import report
            content = report.read(args.userspace).decode('utf-8')
            checker = report.checker_path()
            subprocess.run([sys.executable, str(checker), 'compare', str(args.userspace),
                            str(args.userspace), '--expected-pictures', '300', '--json'],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            inputs = [report.parse(line) for line in content.splitlines()]
            expected = model.map_records(inputs, PICTURES)
        result = validate(read_capture(raw.decode('ascii'), args.run), expected)
        result['raw_sha256'] = hashlib.sha256(raw).hexdigest()
        if args.userspace:
            result['userspace_sha256'] = hashlib.sha256(args.userspace.read_bytes()).hexdigest()
        print(json.dumps(result, indent=2))
        return int(bool(result['findings']))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as e:
        print(f'INVALID: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
