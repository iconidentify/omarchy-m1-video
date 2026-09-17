#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify the public schema-2 campaign and reproduce its measured decision.

Symbolic replay verifies normalized writer/command consistency; it does not
reconstruct private timestamps or independently authenticate raw hardware output.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import check
import report as source_report

HERE = Path(__file__).resolve().parent
DEFAULT = HERE / 'captures/2026-09-17-schema2'
REFERENCE = HERE.parent / 'hevc-controls/captures/2026-09-17/reference-frames.json'
HISTORY = REFERENCE.parent / 'results.json'
INPUTS = {'B': 'a5e2097201740c15824b75540b6d0d5050763681bedf7209cde80d93a3b88996',
          'E': 'b82c5c8c251943cc41b59e7f63f72890641fdcdbcec8e916223e4ee28a16c7ad'}
need = check.need


def read(path):
    return source_report.parse(source_report.read(path))


def rows(path):
    return [source_report.parse(line) for line in source_report.read(path).splitlines()]


def digest(path):
    return hashlib.sha256(source_report.read(path)).hexdigest()


def symbolic_replay(meta, records, expected):
    need(meta['schema'] == 'hevc-avd-trace.normalized/3' and meta['userspace_correlated'], 'unmatched normalized schema/correlation')
    need(meta['structural_validation'] == 'passed' and meta['findings'] == [], 'not a negative measured result')
    replay = []
    for row in records:
        need(type(row['kind']) is int and row['kind'] in check.FIELDS, 'invalid record kind')
        raw = row.copy()
        for field in ('timestamp', 'requested_timestamp'):
            if field not in check.FIELDS[row['kind']]:
                continue
            writer = raw.pop(field + '_writer')
            candidates = raw.pop(field + '_writer_candidates')
            need(candidates == ([] if writer is None else [writer]), 'ambiguous normalized identity')
            need(writer is None or type(writer) is int and 1 <= writer <= row['picture'], 'future/invalid normalized writer')
            # Distinct logical writer ordinals are synthetic tokens, NOT raw values.
            raw[field] = 0 if writer is None else writer
        need(set(raw) == set(check.FIELDS[row['kind']]) | {'kind', 'picture'}, 'missing/extra normalized fields')
        for key, value in raw.items():
            low, high = (-2**31, 2**31) if key in ('poc', 'slice_poc') else (0, 2**64)
            need(type(value) is int and low <= value < high, 'invalid normalized scalar')
        replay.append(raw)
    verified = check.validate(dict(run=meta['run'], context=meta['context'], records=replay), expected)
    need(verified['findings'] == [] and verified['records'] == records, 'symbolic writer/command replay differs')


def window(records):
    grouped = collections.defaultdict(list)
    for row in records:
        if 24 <= row['picture'] <= 34:
            grouped[row['picture']].append(row)
    result = []
    for pic, group in sorted(grouped.items()):
        s, m = group[0], next(r for r in group if r['kind'] == 5)
        table = {r['slot']: r for r in group if r['kind'] == 3}
        lists = {li: [table[r['slot']]['writer'] for r in group if r['kind'] == 4 and r['list'] == li] for li in (0, 1)}
        result.append(dict(picture=pic, poc=s['poc'], type=check.TYPES[s['type']],
            dpb=sorted([r['writer'], r['poc'], r['flags'] & 1, r['intra'], r['word']] for r in table.values()),
            l0=lists[0], l1=lists[1], collocated_writer=m['writer'] if m['lookup'] else None,
            collocated_intra=m['intra'] if m['lookup'] else None,
            matched=m['matched'] if m['lookup'] else None,
            dependent=bool(m['flags'] & check.DEPENDENT) if m['lookup'] else None,
            motion_word=f"0x{m['word']:08x}", gate=m['valid'], emitted=m['emitted']))
    need(len(result) == 11, 'incomplete detailed window')
    return result


def summarize(root):
    inventory = read(root / 'data-files.json')
    need(len(inventory) < 100, 'oversized inventory')
    for name, sha in inventory.items():
        p = Path(name)
        need(not p.is_absolute() and '..' not in p.parts, 'invalid inventory path')
        need(digest(root / p) == sha, 'published input digest mismatch: ' + name)
    provenance = read(root / 'provenance.json')
    need(digest(REFERENCE) == provenance['reference_frames_sha256'], 'reference changed')
    reference = read(REFERENCE)
    need(digest(HISTORY) == provenance['prior_results_sha256'], 'prior result evidence changed')
    history = read(HISTORY)['runs']
    restore = provenance['restoration']
    need(restore['loaded'] == 'existing' and restore['idle'] and restore['new_faults'] == 0 and restore['loaded_build_id_matches'], 'restoration not verified healthy')
    need(restore['boundary_unchanged'] == provenance['fixed_campaign_boundary'] and provenance['new_decoder_faults'] == 0, 'fault boundary/result mismatch')
    build = read(root / 'candidate-build.json')
    need(build['module_sha256'] == provenance['module_sha256'] and provenance['loaded_build_id_checked'], 'module attribution mismatch')
    transitions = read(root / 'transition.json')
    need(transitions[0]['event'] == 'authorized-transition-start' and transitions[-1]['event'] == 'restoration-complete', 'missing transition endpoints')
    need(all(t.get('returncode', 0) == 0 for t in transitions), 'transition failure')
    need(transitions[0]['boundary'] == provenance['fixed_campaign_boundary'], 'transition boundary mismatch')
    runs = read(root / 'runs.json')
    expected_ids = [f'{v}-{c}-{t}' for v in ('B', 'E') for c in ('va', 'gst') for t in ('off', 'on')]
    need([r['id'] for r in runs] == expected_ids, 'missing/duplicate/reordered runs')
    need(len({r['guard_run_id'] for r in runs}) == 8, 'guard identity reused')
    meta = read(root / 'kernel-meta.json')
    need(set(meta) == {r['id'] for r in runs if r['trace'] == 'on'}, 'missing kernel capture')
    private = {r['path']: r for r in read(root / 'private-artifacts.json')['files']}
    checker = source_report.checker_path()
    all_frames, results, kernels, refs_by_run = {}, {}, {}, {}
    for index, run in enumerate(runs):
        name = run['id']; v, client, trace = name.split('-')
        need((run['vector'], run['client'], run['trace'], run['run']) == (v, client, trace, 201 + index), 'run identity mismatch')
        need(run['input_sha256'] == INPUTS[v] and run['frames'] == 300, 'wrong corpus/extent')
        execution = run['execution']; st = execution['status']
        need(execution['run'] == run['run'] and execution['child_exit'] == 0 and execution['child_reaped'] and execution['trace_error'] is None and run['wrapper_status'] == 0, 'decoder/supervisor failure')
        # Trace-off status is the supervisor's last live sample, not a seal.
        # Its final idle evidence is the outer guard. Trace-on has a final seal.
        need(st['errors'] == 0 and (trace == 'off' or st['opens'] == 0), 'kernel trace error/open context')
        need(execution['trace_enabled'] == (trace == 'on'), 'trace mode mismatch')
        guards = rows(root / 'guards' / (name + '.jsonl'))
        need([g['event'] for g in guards] == ['preflight', 'start', 'final'], 'incomplete guard history')
        need(all(g['run_id'] == run['guard_run_id'] for g in guards), 'guard run mismatch')
        need(guards[0]['idle'] and guards[0]['module_loaded'], 'busy/missing preflight')
        final = guards[-1]
        need(final['idle'] and not final['holders'] and not final['timed_out'] and not final['wedged'] and final['abort_reason'] is None, 'guard fault/deadline/foreign failure')
        if name == 'B-va-on':
            correction = read(root / 'postprocessing-correction.json')
            need(final['status'] == 'child-error' and final['returncode'] == 1, 'original checker failure erased')
            need(correction['original_check_status'] == 2 and correction['original_guard_status'] == 'child-error' and correction['actual_decoder_child_exit'] == 0 and correction['kernel_errors'] == 0 and correction['validated_from_preserved_raw'], 'postprocessing exception unproven')
            need(correction['raw_sha256'] == meta[name]['raw_sha256'] == private[name + '/kernel/snapshot.txt']['sha256'], 'corrected evidence source mismatch')
            need(correction['original_check_stderr_sha256'] == private[name + '/kernel/check-stderr.log']['sha256'], 'original rejection evidence missing')
        else:
            need(final['status'] == 'ok' and final['returncode'] == 0, 'unsuccessful guard')
        frames = read(root / 'frames' / (name + '.json'))
        need(len(frames) == 300 and [r[0] for r in frames] == list(range(300)), 'missing/duplicate outputs')
        hashes = [r[1] for r in frames]
        need(all(re.fullmatch('[0-9a-f]{32}', h) for h in hashes), 'invalid frame hash')
        wrong = [i for i, (a, b) in enumerate(zip(hashes, reference[v]['frame_md5'])) if a != b]
        need(wrong == run['wrong_indices'], 'wrong-frame set inconsistent')
        need(len(wrong) == (0 if v == 'B' else 26 if client == 'va' else 25), 'unexpected compatibility change')
        need(run['md5'] == ('6d1ed392b067050ebd3a24a37281da03' if v == 'B' else 'b09ac8e0bd31a96d8354505d7c2ebdd5' if client == 'va' else '53952960ec7512d9cb64f8c7020ece03'), 'whole-output digest changed')
        prior = next(r for r in history if r['vector'] == v and r['client'] == client)
        need(hashes == prior['frame_md5'] and wrong == prior['wrong_indices'], 'prior output/wrong set changed')
        all_frames[name] = frames
        refpath = root / 'refs' / (name + '.jsonl')
        subprocess.run([sys.executable, str(checker), 'compare', str(refpath), str(refpath), '--expected-pictures', '300', '--json'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        refs = rows(refpath); refs_by_run[name] = refs
        assoc = read(root / 'associations' / (name + '.json'))
        need(len(assoc) == 300 and [a['output_index'] for a in assoc] == list(range(300)) and sorted(a['pic'] for a in assoc) == list(range(1, 301)), 'bad output association')
        need(all(a['poc'] == refs[a['pic'] - 1]['poc'] for a in assoc), 'wrong output picture')
        bad = [assoc[i] for i in wrong]
        results[name] = dict(frames=300, wrong_outputs=len(wrong), wrong_indices=wrong,
            first_bad_output=bad[0] if bad else None,
            first_bad_decode=min(bad, key=lambda a: a['pic']) if bad else None,
            guard_status=final['status'])
        if trace == 'on':
            need(all_frames[name] == all_frames[f'{v}-{client}-off'], 'tracing changed pixels')
            records = rows(root / 'kernel' / (name + '.jsonl'))
            need(st['phase'] == 4 and st['run'] == run['run'] and st['context'] == meta[name]['context'] and st['pictures'] == st['completions'] == 300 and st['count'] == st['attempted'] == len(records), 'trace extent/identity mismatch')
            need(meta[name]['raw_sha256'] == private[name + '/kernel/snapshot.txt']['sha256'] and meta[name]['userspace_sha256'] == digest(refpath), 'same-run kernel/userspace mismatch')
            symbolic_replay(meta[name], records, check.model.map_records(refs, 300))
            kernels[name] = records
            results[name]['kernel_records'] = len(records)
            results[name]['kernel_findings'] = 0
        else:
            need(st['phase'] == st['run'] == st['count'] == st['pictures'] == st['completions'] == 0, 'trace-off was not off')
    vectors = {}
    for v in ('B', 'E'):
        windows = {c: window(kernels[f'{v}-{c}-on']) for c in ('va', 'gst')}
        need(windows['va'] == windows['gst'], 'logical reference/motion discrepancy')
        layouts = {}
        for c in ('va', 'gst'):
            fields = 'width height memory length comp_start comp_size off0 off1 off2 off3 mv_size mv_offset'.split()
            starts = [r for r in kernels[f'{v}-{c}-on'] if r['kind'] == 1]
            values = sorted({tuple(s[k] for k in fields) for s in starts})
            layouts[c] = [dict(zip(fields, layout)) for layout in values]
        vectors[v] = dict(logical_reference_motion_window_equal=True, window=windows['va'], layouts=layouts)
    return dict(schema='hevc-avd-trace.campaign-decision/1', workloads=8, output_frames=2400,
        complete_kernel_traces=4, kernel_pictures=1200, runs=results, vectors=vectors,
        decision='No discrepancy in the measured reference lookup/writer/intra/layout/word subset. RPS_E cause remains undetermined.',
        limits=['Symbolic public replay checks normalized metadata, not private raw timestamp values or authenticity.',
                'Other controls/commands, compressed-reference contents and firmware state remain unmeasured.',
                'No RPS_E correction, higher codec count, full-suite, concurrency or stability qualification.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, nargs='?', default=DEFAULT)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    try:
        result = summarize(args.directory)
        if args.verify:
            need(result == read(args.directory / 'summary.json'), 'committed summary differs')
            print('PASS: 8 x 300 frames, 4 complete kernel histories, retained checker failure and measured negative decision')
        else:
            print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, IndexError, StopIteration, subprocess.SubprocessError) as exc:
        print(f'Campaign evidence rejected: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
