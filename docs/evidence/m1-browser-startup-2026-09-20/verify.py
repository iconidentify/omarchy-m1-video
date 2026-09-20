#!/usr/bin/env python3
"""Verify this dated evidence offline. Never extracts or executes records."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tarfile

ROOT = Path(__file__).resolve().parent


def load():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    archive = ROOT / 'records.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['archive_sha256']
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        assert all(m.isfile() for m in members)
        assert len(members) == len({m.name for m in members})
        data = {m.name: tar.extractfile(m).read() for m in members}
    assert set(data) == set(manifest['members'])
    for name, receipt in manifest['members'].items():
        assert hashlib.sha256(data[name]).hexdigest() == receipt['published_sha256'], name
    return data


def verify(data):
    def obj(name):
        return json.loads(data[name])

    def lines(name):
        return [json.loads(line) for line in data[name].splitlines()]

    runs = set()

    def guard(name, status='ok'):
        rows = lines(name + '.guard.jsonl')
        assert [r['event'] for r in rows] == ['preflight', 'start', 'final']
        assert len({r['run_id'] for r in rows}) == 1
        run = rows[0]['run_id']
        assert run not in runs
        runs.add(run)
        first, last = rows[0], rows[-1]
        assert first['idle'] and first['module_loaded'] and last['idle']
        assert not last['holders'] and not last['wedged'] and not last['timed_out']
        assert last['abort_reason'] is None and last['status'] == status
        assert last['returncode'] == (0 if status == 'ok' else 1)
        return run

    def gpu_pass(gpu):
        aux = gpu['auxAttributes']
        assert aux['sandboxed'] is True and aux['processCrashCount'] == 0
        assert 'AGX' in aux['glRenderer']
        assert gpu['featureStatus']['opengl'].startswith('enabled')
        assert gpu['featureStatus']['gpu_compositing'] == 'enabled'

    def isolation(processes, thread_key):
        for kind in ('--type=gpu-process', '--type=renderer'):
            found = [p for p in processes if p['type'] == kind]
            assert found
            assert all(p[thread_key] and all(t['Seccomp'] == '2' for t in p[thread_key]) for p in found)

    for name in ('chrome-default', 'chromium-default'):
        guard(name)
        row = obj(name + '/result.json')
        gpu = row['gpu']['gpu']
        assert gpu['auxAttributes']['sandboxed'] is False
        assert 'AGX' in gpu['auxAttributes']['glRenderer']
        gpu_proc = [p for p in row['processes'] if p['type'] == '--type=gpu-process']
        assert gpu_proc and all(p['threads'] and all(t['Seccomp'] == '0' for t in p['threads']) for p in gpu_proc)

    guard('chrome-cache-off')
    cache = obj('chrome-cache-off/result.json')['gpu']['gpu']
    assert cache['auxAttributes']['processCrashCount'] == 3
    assert cache['auxAttributes']['glRenderer'] == 'Disabled'
    assert data['chrome-cache-off/chrome.log'].count(b'seccomp-bpf failure in syscall nr=0x77') == 3
    guard('chrome-no-cache-object')
    passed = obj('chrome-no-cache-object/result.json')
    gpu_pass(passed['gpu']['gpu'])
    isolation(passed['processes'], 'threads')
    env = obj('chrome-no-cache-object.env.json')
    assert env['MESA_SHADER_CACHE_DISABLE'] is None
    assert all(env[k] == '0' for k in ('MESA_DISK_CACHE_MULTI_FILE', 'MESA_DISK_CACHE_DATABASE', 'MESA_DISK_CACHE_SINGLE_FILE'))
    for name in ('chrome-default', 'chromium-default', 'chrome-cache-off', 'chrome-no-cache-object'):
        args = obj(name + '/result.json')['argv']
        assert not any(a in args for a in ('--no-sandbox', '--disable-gpu-sandbox', '--gpu-sandbox-start-early'))

    ident = obj('identity.json')
    clip_sha = hashlib.sha256(data['fixtures/h264-12s-tagged.mp4']).hexdigest()
    assert clip_sha == 'befc52cf1eabc751f35ba254c47943b252cc93601724f015871f114d3da4dc0a'
    for name in ('playback-software', 'playback-software-v2', 'playback-installed', 'display-diagnostic'):
        run = guard(name, 'ok' if name == 'playback-software-v2' else 'child-error')
        events = lines(name + '/events.jsonl')
        meta = next(e for e in events if e['kind'] == 'identity')
        assert meta['lease'] == run and meta['clip_sha256'] == clip_sha
        assert meta['driver_sha256'] == ident['files']['installed_driver']['sha256']
        env = meta['environment']
        assert env['MESA_SHADER_CACHE_DISABLE'] is None
        assert all(env[k] == '0' for k in ('MESA_DISK_CACHE_MULTI_FILE', 'MESA_DISK_CACHE_DATABASE', 'MESA_DISK_CACHE_SINGLE_FILE'))
        assert not any(a in meta['argv'] for a in ('--no-sandbox', '--disable-gpu-sandbox'))
        if name == 'playback-software':
            assert events[-1]['kind'] == 'failure'
            assert not any(e['kind'] in ('loaded', 'seek', 'completed') for e in events)
            assert next(e for e in events if e['kind'] == 'isolation')['processes'] == []
            continue
        gpu_rows = [e for e in events if e['kind'] == 'gpu']
        isolation_rows = [e for e in events if e['kind'] == 'isolation']
        assert len(gpu_rows) == len(isolation_rows) == (2 if name == 'playback-software-v2' else 1)
        for e in gpu_rows:
            gpu_pass(e['value']['gpu'])
        for e in isolation_rows:
            isolation(e['processes'], 'tasks')
        gates = [e for e in events if e['kind'] == 'decoder_gate']
        assert len(gates) == (2 if name == 'playback-software-v2' else 1)
        for gate in gates:
            assert gate['players']
            assert all(p['kVideoDecoderName'] == 'FFmpegVideoDecoder' and p['kIsPlatformVideoDecoder'] == 'false' for p in gate['players'].values())
        if name != 'playback-software-v2':
            assert events[-1]['kind'] == 'failure'
            assert not any(e['kind'] in ('seek', 'completed', 'capture') for e in events)
            assert b'Could not get a valid VA display' in data[name + '/chrome.log']
            continue
        assert events[-1] == {'kind': 'completed', 'passed_execution': True}
        seeks = [e for e in events if e['kind'] == 'seek']
        assert [e['index'] for e in seeks] == list(range(20))
        assert [e['target'] for e in seeks] == [1, 4, 2, 6] * 5
        assert all(abs(e['value']['frame']['mediaTime'] - e['target']) < .002 and not e['value']['error'] for e in seeks)
        play = next(e['value'] for e in events if e['kind'] == 'play_all')
        assert play['after']['time'] >= 11.9 and not play['after']['error']
        assert play['after']['dropped'] == play['before']['dropped']
        pair = next(e['value'] for e in events if e['kind'] == 'two_videos')
        assert pair['primary']['time'] > 1 and pair['secondary']['time'] > 0
        assert not pair['primary']['error'] and not pair['secondary']['error']
        survivor = next(e['value'] for e in events if e['kind'] == 'survivor')
        assert survivor['after']['time'] - survivor['before']['time'] >= .5 and not survivor['after']['error']
        reopened = next(e['value'] for e in events if e['kind'] == 'reopen')
        assert abs(reopened['frame']['mediaTime'] - 1) < .002 and not reopened['error']
        captures = [e for e in events if e['kind'] == 'capture']
        assert [e['name'] for e in captures] == ['seek-1', 'seek-4', 'seek-2', 'seek-6', 'reopen-1']
        for e in captures:
            picture = data[name + '/' + e['name'] + '.png']
            assert hashlib.sha256(picture).hexdigest() == e['sha256']
            assert e['dimensions'] == [1280, 720] and e['display']['dpr'] == 2
            assert struct.unpack('>II', picture[16:24]) == (1280, 720)

    diag = lines('display-diagnostic/events.jsonl')
    gpu_pid = next(p['pid'] for e in diag if e['kind'] == 'isolation' for p in e['processes'] if p['type'] == '--type=gpu-process')
    log = data['display-diagnostic/chrome.log'].decode()
    prefix = f'DISPLAY_OBSERVE pid={gpu_pid} '
    nodes = re.findall(re.escape(prefix) + r'drmGetNodeTypeFromFd fd=(\d+) ret=(-?\d+) errno=(\d+)', log)
    assert nodes and any(ret == '2' for _, ret, _ in nodes)
    denied = [(fd, ret, err) for fd, ret, err in nodes if ret == '-1' and err == '22']
    assert denied and any(fd == denied[0][0] and ret == '2' for fd, ret, _ in nodes)
    assert prefix + 'stat64 path=/sys/dev/char/226:128/device/drm ret=-1 errno=13' in log
    final = obj('final-state.json')
    assert final['boot_id'] == ident['boot_id']
    state = final['state']
    assert state['module_loaded'] and not state['holders'] and not state['stuck_tasks'] and not state['faults']
    assert all(final['sha256'][k] == v['sha256'] for k, v in ident['files'].items())
    assert next(e for e in diag if e['kind'] == 'diagnostic')['sha256'] == final['sha256']['observer']
    assert len(runs) == 8


def self_test(data):
    """Semantic mutations start after byte integrity has been checked."""
    mutations = []
    row = json.loads(data['chrome-no-cache-object/result.json'])
    row['gpu']['gpu']['auxAttributes']['sandboxed'] = False
    mutations.append(('startup isolation', 'chrome-no-cache-object/result.json', json.dumps(row).encode()))
    row = json.loads(data['chrome-cache-off/result.json'])
    row['gpu']['gpu']['auxAttributes']['processCrashCount'] = 0
    mutations.append(('preserved crash', 'chrome-cache-off/result.json', json.dumps(row).encode()))
    name = 'playback-software-v2/events.jsonl'
    rows = [json.loads(s) for s in data[name].splitlines()]
    rows = [r for r in rows if not (r['kind'] == 'seek' and r['index'] == 19)]
    mutations.append(('missing seek', name, '\n'.join(json.dumps(r) for r in rows).encode()))
    name = 'playback-installed/events.jsonl'
    mutations.append(('false hardware decoder', name, data[name].replace(b'FFmpegVideoDecoder', b'VaapiVideoDecoder')))
    name = 'display-diagnostic/chrome.log'
    mutations.append(('missing denial', name, data[name].replace(b'ret=-1 errno=13', b'ret=0 errno=0')))
    row = json.loads(data['final-state.json'])
    row['state']['holders'] = [{'pid': 123, 'synthetic': True}]
    mutations.append(('busy final state', 'final-state.json', json.dumps(row).encode()))
    for label, name, replacement in mutations:
        mutated = dict(data)
        mutated[name] = replacement
        try:
            verify(mutated)
        except AssertionError:
            print('Rejected semantic mutation:', label)
        else:
            raise AssertionError('mutation escaped: ' + label)


if __name__ == '__main__':
    data = load()
    verify(data)
    if sys.argv[1:] == ['--self-test']:
        self_test(data)
    else:
        assert not sys.argv[1:], 'only --self-test is supported'
    print('Verified: sandboxed AGX startup, software-only lifecycle/captures, all failed attempts, observed VA display denial and unchanged idle stack. Browser hardware qualification: none.')
