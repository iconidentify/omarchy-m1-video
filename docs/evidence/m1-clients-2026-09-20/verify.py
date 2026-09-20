#!/usr/bin/env python3
"""Offline verification of this dated record; never opens a decoder."""
import hashlib
import json
from pathlib import Path
import struct
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
        objects = {m.name: tar.extractfile(m).read() for m in members}
    assert set(objects) == {r['object'] for r in manifest['members'].values()}
    data = {}
    for name, record in manifest['members'].items():
        content = objects[record['object']]
        assert hashlib.sha256(content).hexdigest() == record['published_sha256'], name
        data[name] = content
    return data


def verify(data):
    def lines(name):
        return [json.loads(x) for x in data[name].splitlines()]

    def guard(name, status='ok'):
        records = lines(name + '.guard.jsonl')
        assert [r['event'] for r in records] == ['preflight', 'start', 'final']
        assert len({r['run_id'] for r in records}) == 1
        first, last = records[0], records[-1]
        assert first['idle'] and last['idle'] and not last['holders']
        assert last['status'] == status and not last['timed_out'] and not last['wedged']
        assert last['returncode'] == (0 if status == 'ok' else 1)
        return first['run_id']

    identity = json.loads(data['identity.json'])
    refs = {'h264': 'mpv-software-h264-v2', 'vp9-10': 'mpv-software-vp9-10'}
    inputs = {'h264': 'h264-12s-tagged.mp4', 'vp9-10': 'vp9-10.webm'}
    for label in ('software', 'baseline', 'candidate'):
        for codec in refs:
            for mode in (('no',) if label == 'software' else ('vaapi', 'vaapi-copy')):
                name = refs[codec] if label == 'software' else f'mpv-{label}-{codec}-{mode}'
                events = lines(name + '/events.jsonl')
                meta = events[0]
                assert meta['lease'] == guard(name)
                assert meta['codec'] == codec and meta['mode'] == mode
                assert meta['input_sha256'] == hashlib.sha256(data['fixtures/' + inputs[codec]]).hexdigest()
                driver = 'candidate_driver' if label == 'candidate' else 'installed_driver'
                assert meta['driver_sha256'] == identity['files'][driver]['sha256']
                assert events[-1]['kind'] == 'completed' and not any(e['kind'] == 'failure' for e in events)
                seeks = [e for e in events if e['kind'] == 'seek']
                targets = [1., 4., 2., 6.] if codec == 'h264' else [0., 12/27, 6/27, 18/27]
                assert len(seeks) == 20
                assert [e['index'] for e in seeks] == list(range(20))
                assert [e['target'] for e in seeks] == targets * 5
                assert all(abs(e['actual'] - e['target']) < .003 for e in seeks)
                reopens = [e for e in events if e['kind'] == 'reopen']
                assert [e['index'] for e in reopens] == [0, 1]
                players = [e for e in events if e['kind'] == 'player'] + reopens
                assert len(players) == 3
                for e in players:
                    p = e['identity']
                    assert p['hwdec'] == mode and p['current_vo'] == 'gpu-next'
                    assert (p['output_params']['w'], p['output_params']['h']) == (640, 360)
                    if label != 'software':
                        assert identity['files'][driver]['path'] in p['mapped_drivers']
                        params = p['video_params']
                        assert params.get('hw-pixelformat', params['pixelformat']) == ('nv12' if codec == 'h264' else 'p010')
                play = [e for e in events if e['kind'] == 'play_complete']
                assert len(play) == 1 and play[0]['elapsed'] >= 30
                assert play[0]['before'] == play[0]['after'] == {'render': 0, 'decode': 0}
                samples = [e for e in events if e['kind'] == 'play_sample']
                assert len(samples) >= 50 and samples[-1]['elapsed'] >= 30
                assert all(e['drops'] == {'render': 0, 'decode': 0} for e in samples)
                assert max(e['position'] for e in samples) - min(e['position'] for e in samples) > .3
                captures = [e for e in events if e['kind'] == 'capture']
                assert len(captures) == 6
                for e in captures:
                    filename = e['name'] + '.png'
                    picture = data[name + '/' + filename]
                    assert hashlib.sha256(picture).hexdigest() == e['sha256']
                    assert struct.unpack('>II', picture[16:24]) == (1750, 986)
                    assert picture == data[refs[codec] + '/' + filename]
                if label != 'software':
                    result = json.loads(data[name + '/comparison.json'])
                    assert result['passed'] and len(result['comparisons']) == 6
                    assert all(c['psnr'] == 'identical' and c['sha256'] == c['reference_sha256'] for c in result['comparisons'])
    survivor = lines('mpv-survivor/events.jsonl')
    assert survivor[0]['lease'] == guard('mpv-survivor')
    assert survivor[0]['driver_sha256'] == identity['files']['candidate_driver']['sha256']
    assert [e['kind'] for e in survivor] == ['identity', 'player', 'player', 'concurrent', 'closed', 'survived', 'completed']
    for e in survivor[1:3]:
        assert e['state']['hwdec-current'] == 'vaapi'
        assert identity['files']['candidate_driver']['path'] in e['mapped_drivers']
    assert survivor[4]['returncode'] == 0
    for state in (survivor[3]['survivor'], survivor[5]):
        assert state['after']['time-pos'] > state['before']['time-pos'] + 1
        assert state['after']['hwdec-current'] == 'vaapi'
        for key in ('frame-drop-count', 'decoder-frame-drop-count'):
            assert state['after'][key] == state['before'][key] == 0
    guard('preview-smoke')
    assert b'Using hardware decoding (vaapi-copy)' in data['preview-smoke.mpv.log']
    guard('mpv-software-h264', 'child-error')
    assert lines('mpv-software-h264/events.jsonl')[-1]['kind'] == 'failure'
    for name, sandboxed in (('chrome-diagnostics', False), ('chrome-early-sandbox', True)):
        guard(name)
        result = json.loads(data[name + '/result.json'])
        gpu = result['gpu']['gpu']
        assert gpu['auxAttributes']['sandboxed'] is sandboxed
        proc = [p for p in result['processes'] if p['type'] == '--type=gpu-process']
        assert proc and all(p['Seccomp'] == ('2' if sandboxed else '0') for p in proc)
        assert '--no-sandbox' not in result['argv'] and '--disable-gpu-sandbox' not in result['argv']
        if sandboxed:
            assert gpu['auxAttributes']['glRenderer'] == 'Disabled'
            assert gpu['featureStatus']['video_decode'] == 'disabled_software'
    guard('chrome-software')
    final = json.loads(data['final-state.json'])
    state = final['state']
    assert state['module_loaded'] and not state['holders'] and not state['stuck_tasks'] and not state['faults']
    assert all(value == identity['files'][key]['sha256'] for key, value in final['sha256'].items())


if __name__ == '__main__':
    verify(load())
    print('Verified eight hardware rows: 160 seeks, 16 reloads, >=240 seconds, 48 byte-identical captures; survivor, preview, preserved preparations, Chrome blocker and final idle state.')
