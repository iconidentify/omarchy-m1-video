#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Single-use, explicitly reviewed HEVC campaign; no retries or fault recovery.

Module transition/healthy-restoration ordering follows the accepted paired-command
campaign (PR76). The decoder path is the unchanged same-run supervisor (PR123).
"""
import argparse
import collections
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'deployment'))
import manifest
import admission

NATIVE = Path('/etc/apple-avd-observer/approved-builds')
CONFIG_KEYS = {'schema', 'manifest', 'manifest_sha256', 'preparation',
               'original_module', 'boot_id', 'journal_since', 'output_root',
               'authorization_scope'}


def need(value, message):
    if not value:
        raise ValueError(message)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def checked_config(path, expected):
    raw, config = manifest.read_document(path)
    need(hashlib.sha256(raw).hexdigest() == expected, 'campaign config digest drift')
    manifest.safe_path(path, root_owned=True)
    need(set(config) == CONFIG_KEYS and config['schema'] == 'omarchy.hevc.live-campaign/v1',
         'campaign config schema')
    need(config['authorization_scope'] == 'temporary-recorder-eight-workloads-no-retry',
         'missing bounded execution authorization')
    need(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == config['boot_id'],
         'boot changed after review')
    need(type(config['journal_since']) is str and config['journal_since'], 'missing fixed journal boundary')
    manifest._file(config['preparation'], 'preparation', root_owned=True, check_files=True)
    _, preparation = manifest.read_document(Path(config['preparation']['path']))
    for name, row in preparation['extra_sources'].items():
        manifest._file(row, name, root_owned=True, check_files=True)
    native = preparation['native_approval']
    manifest._file(native, 'native approval', root_owned=True, check_files=True)
    manifest._file(config['original_module'], 'original module', root_owned=True, check_files=True)
    document = manifest.verify(Path(config['manifest']), config['manifest_sha256'], live=False)
    admitted = admission.admitted_document(Path(config['manifest']), config['manifest_sha256'], live=False)
    need(admitted['execution_authorized'] is False, 'deployment layer changed its authority')
    # This separately authorized runner, not admission.py, owns execution.
    return config, document, preparation, admitted


def expanded(row, root, kernel_run, lease_env):
    need(root.is_absolute() and not root.exists() and not root.is_symlink(), 'workload root already exists')
    substitutions = {'@OMARCHY_RUN_ROOT@': str(root), '@OMARCHY_KERNEL_RUN@': str(kernel_run)}
    def replace(value):
        for key, replacement in substitutions.items():
            value = value.replace(key, replacement)
        return value
    argv = [replace(value) for value in row['argv']]
    env = {key: replace(value) for key, value in row['environment'].items()}
    env.update({key: lease_env[key] for key in
                ('LIBVA_HW_GUARD_LEASE', 'LIBVA_HW_GUARD_IDENTITY', 'LIBVA_HW_GUARD')})
    need(not any('@OMARCHY_RUN_ROOT@' in v or '@OMARCHY_KERNEL_RUN@' in v for v in argv + list(env.values())),
         'unexpanded run identity')
    return argv, env


def frame_hashes(root, client):
    if client == 'va':
        rows = [line.split(',') for line in (root / 'frames.md5').read_text().splitlines()
                if line.strip() and not line.startswith('#')]
        need(len(rows) == 300 and all(len(row) == 6 for row in rows), 'FFmpeg frame extent')
        hashes = []
        for index, row in enumerate(rows):
            stream, dts, pts, duration, size = [int(value) for value in row[:5]]
            need((stream, dts, pts, duration, size) == (0, index, index, 1, 149760),
                 'FFmpeg frame sequence/geometry drift')
            value = row[5].strip()
            need(re.fullmatch('[0-9a-f]{32}', value), 'FFmpeg frame hash shape')
            hashes.append(value)
        return hashes
    path = root / 'output.yuv'
    need(path.stat().st_size == 300 * 149760, 'Gst frame extent')
    with path.open('rb') as stream:
        return [hashlib.md5(stream.read(149760)).hexdigest() for _ in range(300)]


def compare_frames(hashes, prior, reference, paired=None):
    need(len(hashes) == len(reference) == 300, 'reference frame extent')
    need(prior == [[index, value] for index, value in enumerate(hashes)],
         'pixels differ from the prior accepted client baseline')
    if paired is not None:
        need(hashes == paired, 'copy observation perturbs decoded pixels')
    return [index for index, (actual, expected) in enumerate(zip(hashes, reference)) if actual != expected]


def projection(result):
    return [{'selector': row['selector'], 'picture': row['bridge']['picture'],
             'poc': row['bridge']['poc'], 'kernel_completed': row['bridge']['kernel_completed']}
            for row in result['selected']]


def reference_projection(records):
    """Accepted PR76 logical window projection; never compare raw allocation IDs."""
    groups = collections.defaultdict(list)
    for row in records:
        if 24 <= row['picture'] <= 34:
            groups[row['picture']].append(row)
    output = []
    for picture, group in sorted(groups.items()):
        start = group[0]
        motion = next(row for row in group if row['kind'] == 5)
        table = {row['slot']: row for row in group if row['kind'] == 3}
        lists = [[table[row['slot']]['writer'] for row in group
                  if row['kind'] == 4 and row['list'] == li] for li in (0, 1)]
        output.append({'picture': picture, 'poc': start['poc'], 'type': start['type'],
            'dpb': sorted([row['writer'], row['poc'], row['flags'] & 1, row['intra'], row['word']]
                          for row in table.values()), 'l0': lists[0], 'l1': lists[1],
            'collocated_writer': motion['writer'] if motion['lookup'] else None,
            'collocated_intra': motion['intra'] if motion['lookup'] else None,
            'matched': motion['matched'] if motion['lookup'] else None,
            'flags': motion['flags'] if motion['lookup'] else None,
            'motion_word': motion['word'], 'gate': motion['valid'], 'emitted': motion['emitted']})
    need(len(output) == 11, 'incomplete reference window')
    return output


def capture_projection(root, document):
    supervisor = load_module('live_evidence_supervisor', document['artifacts']['same_run_supervisor']['path'])
    validator = supervisor.validator
    traces = list(root.glob('*_trace.json'))
    need(len(traces) == 1, 'ambiguous V4L2 trace')
    evidence = validator.validate(execution_path=root / 'kernel/execution.json',
        v4l2_trace_path=traces[0], command_snapshot_path=root / 'kernel/command.snapshot',
        reference_snapshot_path=root / 'kernel/reference.snapshot',
        uapi_path=Path(document['artifacts']['uapi']['path']),
        oracle_path=Path(document['artifacts']['oracle_identity']['path']).parent)
    commands = validator.command_parser.parse_snapshot((root / 'kernel/command.snapshot').read_text(), evidence.run)
    return {'commands': [{key: row[key] for key in ('picture', 'poc', 'sites', 'words', 'inactive')}
                         for row in commands['windows']],
            'references': reference_projection(evidence.reference_records)}


class Campaign:
    def __init__(self, config, document, preparation, admitted, guard):
        self.config, self.document, self.preparation = config, document, preparation
        self.admitted, self.guard = admitted, guard
        self.root = Path(config['output_root'])
        self.backend = guard.LinuxBackend(preflight_since=config['journal_since'])
        self.changed = self.restored = self.approval_installed = False

    def record(self, event, **data):
        with (self.root / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps({'event': event, 'monotonic': time.monotonic(),
                                     'lease': os.environ.get('LIBVA_HW_GUARD_LEASE'), **data}) + '\n')
            stream.flush(); os.fsync(stream.fileno())

    def healthy(self, present=True):
        state = self.backend.state()
        self.record('health', **dataclasses.asdict(state))
        need(not (state.busy or state.wedged or state.faults), 'STOP: unhealthy; no module recovery')
        if state.module_loaded:
            need(Path('/sys/module/apple_avd/initstate').read_text().strip() == 'live', 'module is not live')
        need(not present or state.module_loaded and state.video_node, 'decoder missing')
        return state

    def identity(self, original):
        row = self.config['original_module'] if original else self.document['artifacts']['recorder_module']
        need(manifest.digest(Path(self.config['original_module']['path'])) ==
             self.config['original_module']['sha256'], 'installed module changed')
        need(manifest._loaded_note('apple_avd') == row['build_id'], 'loaded module identity drift')

    def privileged(self, *argv):
        self.record('privileged-attempt', argv=list(argv))
        result = subprocess.run(['/usr/bin/sudo', '-n', *map(str, argv)], text=True,
                                capture_output=True, timeout=20)
        self.record('privileged-result', argv=list(argv), returncode=result.returncode,
                    stdout=result.stdout, stderr=result.stderr)
        need(result.returncode == 0, 'privileged transition failed; no retry')

    def live_check(self):
        self.identity(False); self.healthy()
        self.privileged(self.document['artifacts']['python']['path'], '-I', '-B',
                        HERE.parent / 'deployment/manifest.py', self.config['manifest'],
                        '--approved-sha256', self.config['manifest_sha256'], '--live')

    def restore(self):
        state = self.healthy(present=False)
        if state.module_loaded:
            self.identity(False)
            self.privileged('/usr/bin/rmmod', 'apple_avd')
        self.healthy(present=False)
        self.privileged('/usr/bin/modprobe', 'apple_avd')
        self.identity(True); self.healthy()
        self.restored = True
        self.record('original-restored')

    def workload(self, row, number):
        need(manifest.digest(NATIVE) == self.preparation['native_approval']['sha256'], 'native approval drift')
        self.live_check()
        run_root = self.root / row['name']
        argv, environment = expanded(row, run_root, number, os.environ)
        self.record('workload-start', name=row['name'], kernel_run=number, argv=argv, environment=environment)
        with (self.root / (row['name'] + '.stdout')).open('x') as out, \
             (self.root / (row['name'] + '.stderr')).open('x') as err:
            result = subprocess.run(argv, env=environment, stdout=out, stderr=err, timeout=120)
        self.record('workload-exit', name=row['name'], returncode=result.returncode)
        need(result.returncode == 0, 'same-run workload failed; stop without replay: ' + row['name'])
        self.healthy()
        hashes = frame_hashes(run_root, row['client'])
        prior_key = ('experiments/hevc-avd-trace/captures/2026-09-17-schema2/frames/' +
                     f'{row["vector"]}-{row["client"]}-off.json')
        prior = json.loads(Path(self.preparation['extra_sources'][prior_key]['path']).read_text())
        reference = json.loads(Path(self.document['artifacts']['reference_frames']['path']).read_text())
        pair_root = self.root / f'{row["vector"]}-{row["client"]}-off'
        paired = json.loads((pair_root / 'frames.json').read_text()) if row['copy'] else None
        wrong = compare_frames(hashes, prior, reference[row['vector']]['frame_md5'], paired)
        joined = json.loads((run_root / 'same-run-result.json').read_text())
        need(joined['copy'] is row['copy'] and joined['client'] == row['client'], 'join workload identity')
        need(len(joined['selected']) == (1 if row['vector'] == 'B' else 3), 'selected observation extent')
        if row['copy']:
            before = json.loads((pair_root / 'same-run-result.json').read_text())
            need(projection(joined) == projection(before), 'selected writer logical projection changed')
        measured = capture_projection(run_root, self.document)
        if row['copy']:
            need(measured == json.loads((pair_root / 'kernel-projection.json').read_text()),
                 'copy observation changes command/reference projection')
        if row['client'] == 'gst':
            other_root = self.root / f'{row["vector"]}-va-{"on" if row["copy"] else "off"}'
            need(measured == json.loads((other_root / 'kernel-projection.json').read_text()),
                 'cross-client command/reference projection differs')
        write_json(run_root / 'kernel-projection.json', measured)
        write_json(run_root / 'frames.json', hashes)
        summary = {'frames': 300, 'wrong_indices': wrong, 'selected': projection(joined),
                   'copy': row['copy'], 'join_sha256': manifest.digest(run_root / 'same-run-result.json')}
        write_json(run_root / 'comparison.json', summary)
        self.record('workload-validated', name=row['name'], **summary)
        return summary

    def run(self):
        need(os.geteuid() != 0 and os.environ.get('LIBVA_HW_GUARD_LEASE'), 'ordinary user inside guard required')
        with (self.root / 'attempted').open('x') as marker:
            marker.write('single use; preserve all failures\n'); marker.flush(); os.fsync(marker.fileno())
        need(not NATIVE.parent.exists() and not NATIVE.parent.is_symlink(), 'native approval directory already exists')
        self.identity(True); self.healthy()
        failure = None
        runs = {}
        try:
            self.privileged('/usr/bin/rmmod', 'apple_avd'); self.changed = True
            self.healthy(present=False)
            self.privileged('/usr/bin/insmod', self.document['artifacts']['recorder_module']['path'])
            self.live_check()
            self.privileged('/usr/bin/install', '-d', '-m', '0755', NATIVE.parent)
            self.privileged('/usr/bin/install', '-m', '0644', self.preparation['native_approval']['path'], NATIVE)
            self.approval_installed = True
            need(manifest.digest(NATIVE) == self.preparation['native_approval']['sha256'], 'native approval drift')
            for index, row in enumerate(self.admitted['workloads'], 1):
                runs[row['name']] = self.workload(row, index)
        except Exception as error:
            failure = error; self.record('failed', error=str(error))
        finally:
            if self.changed:
                try:
                    self.restore()
                except Exception as error:
                    self.record('restoration-not-completed', error=str(error))
                    failure = failure or error
            if self.approval_installed:
                try:
                    need(manifest.digest(NATIVE) == self.preparation['native_approval']['sha256'], 'changed approval retained')
                    self.privileged('/usr/bin/rm', '--', NATIVE)
                    self.privileged('/usr/bin/rmdir', '--', NATIVE.parent)
                except Exception as error:
                    self.record('approval-cleanup-failed', error=str(error)); failure = failure or error
            self.record('terminal', restored=self.restored, runs=len(runs), **dataclasses.asdict(self.backend.state()))
        if failure:
            raise failure
        need(self.restored and len(runs) == 8, 'campaign incomplete')
        write_json(self.root / 'complete.json', {'runs': runs, 'frames': 2400, 'original_restored': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    config, document, preparation, admitted = checked_config(args.config.absolute(), args.config_sha256)
    guard = load_module('campaign_hwguard', document['artifacts']['hwguard']['path'])
    if args.worker:
        Campaign(config, document, preparation, admitted, guard).run()
        return 0
    root = Path(config['output_root'])
    need(root.is_absolute(), 'output root is not absolute')
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    write_json(root / 'config.json', config)
    result = guard.run_guarded(
        [sys.executable, '-s', str(Path(__file__).resolve()), str(args.config.absolute()),
         '--config-sha256', args.config_sha256, '--worker'],
        deadline=1200, poll=0.1, journal_since=config['journal_since'], log_path=root / 'guard.jsonl',
        env={'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'})
    write_json(root / 'guard-result.json', dataclasses.asdict(result))
    print(json.dumps(dataclasses.asdict(result)))
    return 0 if result.status == 'ok' and result.returncode == 0 else 125


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('CAMPAIGN STOPPED: ' + str(error), file=sys.stderr)
        raise SystemExit(125)
