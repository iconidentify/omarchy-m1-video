#!/usr/bin/env python3
"""Offline check of this dated evidence archive; never accesses a decoder."""
import hashlib
import json
from pathlib import Path
import struct
import tarfile

ROOT = Path(__file__).resolve().parent


def verify():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    archive = ROOT / 'records.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['archive_sha256']
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        assert all(m.isfile() for m in members)
        assert len(members) == len({m.name for m in members})
        data = {m.name: tar.extractfile(m).read() for m in members}
    assert set(data) == set(manifest['members'])
    for name, entry in manifest['members'].items():
        assert hashlib.sha256(data[name]).hexdigest() == entry['published_sha256'], name
    inputs = json.loads(data['fixtures/inputs.json'])
    identity = json.loads(data['comparison-identity.json'])
    for item in inputs['inputs']:
        assert hashlib.sha256(data['fixtures/' + item['name']]).hexdigest() == item['sha256']
    for row in ('baseline-normal', 'baseline-early', 'candidate-normal', 'candidate-early'):
        records = [json.loads(x) for x in data[row + '.jsonl'].splitlines()]
        meta, summary = records[0], records[-1]
        driver = 'installed_driver' if row.startswith('baseline') else 'candidate_driver'
        source = 'installed_source' if row.startswith('baseline') else 'candidate_source'
        assert meta['driver_sha256'] == identity['files'][driver]['sha256']
        assert meta['source_commit'] == identity[source]
        assert meta['inputs_sha256'] == hashlib.sha256(data['fixtures/inputs.json']).hexdigest()
        assert summary['passed'] and summary['returncode'] == 0 and not summary['violations']
        assert (summary['cycles'], summary['warmup_cycles'], summary['decoded_frames'],
                summary['held_image_checks']) == (400, 20, 20160, 420)
        samples = [r for r in records if r['type'] == 'sample']
        assert [s['cycle'] for s in samples] == list(range(401))
        for key in ('fd_count', 'map_count', 'mapped_bytes', 'vmrss_kib',
                    'dmabuf_references', 'dmabuf_objects', 'dmabuf_bytes'):
            assert len({s[key] for s in samples}) == 1, (row, key)
        assert max(s['allocator']['allocated'] for s in samples) - samples[0]['allocator']['allocated'] <= 65536
        lines = data[row + '.workload.log'].decode().splitlines()
        expected = []
        for cycle in range(1, 421):
            stream = (cycle - 1) % 4
            item = inputs['inputs'][stream]
            for part in range(2):
                expected.extend(item['frames'])
                expected.append(f"RESULT cycle={cycle} stream={stream} pass={part} frames=24 MD5={item['md5']}")
            expected.append(f'HELD_IMAGE_PASS cycle={cycle}')
        actual = [s for s in lines if s.startswith(('frame ', 'RESULT ', 'HELD_IMAGE_PASS '))]
        assert actual == expected, row
        assert [s for s in lines if s.startswith('CHECKPOINT ')] == [f'CHECKPOINT {n}' for n in range(401)]
        assert lines.count('INITIAL') == 1
        errors = data[row + '.stderr.log'].decode().splitlines()
        assert not any('EARLY_EXPORT_FAIL' in s or 'Failed to destroy' in s for s in errors)
        if row.endswith('early'):
            assert sum(s.startswith('EARLY_EXPORT_PASS:') for s in errors) == 20160
    for row in ('baseline-normal', 'baseline-early', 'candidate-normal', 'candidate-early',
                'mpv-baseline', 'mpv-candidate'):
        guard = [json.loads(x) for x in data[row + '.guard.jsonl'].splitlines()]
        assert [r['event'] for r in guard] == ['preflight', 'start', 'final']
        assert len({r['run_id'] for r in guard}) == 1
        assert guard[0]['idle'] and guard[-1]['idle']
        assert guard[-1]['status'] == 'ok' and guard[-1]['returncode'] == 0
        assert not guard[-1]['timed_out'] and not guard[-1]['wedged'] and not guard[-1]['holders']
    for row in ('mpv-baseline', 'mpv-candidate'):
        records = [json.loads(x) for x in data[row + '/results.jsonl'].splitlines()]
        assert [r['hwdec'] for r in records] == ['no', 'vaapi', 'vaapi-copy']
        shots = [data[row + '/' + Path(r['screenshot']).name] for r in records]
        assert shots[0] == shots[1] == shots[2]
        assert struct.unpack('>II', shots[0][16:24]) == (1750, 986)
        for r in records[1:]:
            assert r['hwdec_current'] == r['hwdec'] and r['hw_line'] and r['ok']
            assert r['played_to'] >= 0.2 and r['frame_drops'] == r['decoder_drops'] == 0
            assert r['psnr_db'] >= 40 and not r['errors']
    final = json.loads(data['final-state.json'])
    assert final['module_loaded'] and not final['holders'] and not final['stuck_tasks'] and not final['faults']
    print(f"Verified {len(data)} archive members; 80640 ordered frames, 1680 held-image checks, four mpv smoke rows, six idle guards.")


if __name__ == '__main__':
    verify()
