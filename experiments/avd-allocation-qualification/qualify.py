#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Finite, single-use allocator qualification; one outer portable hardware lease."""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

CANDIDATE = '8caab2852b2d838999ba3774d79faea439c48de151c2a7592c93f13d35dd454d'
ORIGINAL = 'e50540e1d0fc48c7e0bf9b21ff028758bdb35f94aa7070af00de88e61e5c70e9'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frames(text):
    rows = re.findall(r'^frame (\d+) (\d+x\d+) (\w+) ([0-9a-f]{32})$', text, re.M)
    if [int(row[0]) for row in rows] != list(range(len(rows))) or not rows:
        raise ValueError('missing/nonsequential frames')
    if len(re.findall(r'^MD5=[0-9a-f]{32}$', text, re.M)) != 1:
        raise ValueError('missing complete digest')
    return rows


class Campaign:
    def __init__(self, config):
        self.c = config
        self.root = Path(config['root'])
        sys.path.insert(0, str(Path(config['guard']).parent))
        import hwguard
        # Entire current boot is the fixed fault domain. No moving --since bypass.
        self.backend = hwguard.LinuxBackend()
        self.changed = False
        self.restored = False

    def record(self, event, **data):
        with (self.root/'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(event=event, lease=os.environ.get('LIBVA_HW_GUARD_LEASE'), **data))+'\n')
            f.flush()
            os.fsync(f.fileno())

    def healthy(self, present=True):
        state = self.backend.state()
        # Do not publish unrelated process arguments.
        for holder in state.holders:
            holder['cmd'] = '<redacted>'
        self.record('health', **dataclasses.asdict(state))
        if state.busy or state.wedged or state.faults:
            raise RuntimeError('STOP: busy, wedged or faulted; no module recovery')
        if state.module_loaded and Path('/sys/module/apple_avd/initstate').read_text().strip() != 'live':
            raise RuntimeError('STOP: module not live')
        if present and not (state.module_loaded and state.video_node):
            raise RuntimeError('decoder absent')
        return state

    def identity(self, which):
        if sha(self.c['original']) != ORIGINAL:
            raise RuntimeError('installed original changed')
        actual = Path('/sys/module/apple_avd/notes/.note.gnu.build-id').read_bytes()
        expected = bytes.fromhex(self.c[which+'_note_hex'])
        if actual != expected:
            raise RuntimeError('loaded identity mismatch: '+which)

    def transition(self, *argv):
        self.record('transition-attempt', argv=argv)
        p = subprocess.run(['sudo', '-n', *argv], capture_output=True, text=True, timeout=15)
        self.record('transition-result', argv=argv, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        if p.returncode:
            raise RuntimeError('module transition failed; never retry')

    def restore(self):
        state = self.healthy(present=False)
        if state.module_loaded:
            self.identity('candidate')
            self.transition('rmmod', 'apple_avd')
        self.healthy(present=False)
        self.transition('modprobe', 'apple_avd')
        self.identity('original')
        self.healthy()
        self.restored = True
        self.record('original-restored')

    def execute(self, stage, job):
        out = self.root/stage/job['name']
        out.mkdir(parents=True)
        env = os.environ.copy()
        for key in list(env):
            if key.startswith('LIBVA_V4L2_') or key in ('LD_PRELOAD', 'GST_DEBUG', 'GST_DEBUG_FILE'):
                env.pop(key)
        env.update(self.c['environment'])
        env.update(job.get('environment', {}))
        argv = [part.replace('{output}', str(out/'output.yuv')) for part in job['argv']]
        self.record('job-start', stage=stage, name=job['name'])
        with (out/'stdout').open('w') as stdout, (out/'stderr').open('w') as stderr:
            result = subprocess.run(argv, env=env, stdout=stdout, stderr=stderr, timeout=60)
        self.record('job-exit', stage=stage, name=job['name'], returncode=result.returncode)
        if result.returncode:
            raise RuntimeError('decoder failed: '+job['name'])
        self.healthy()
        text = (out/'stdout').read_text()
        if job['kind'] == 'frames':
            actual = [row[-1] for row in frames(text)]
        elif job['kind'] == 'raw':
            data = (out/'output.yuv').read_bytes()
            size = job['frame_bytes']
            if len(data) != size*job['count']:
                raise ValueError('raw extent mismatch')
            actual = [hashlib.md5(data[i:i+size]).hexdigest() for i in range(0,len(data),size)]
        elif job['kind'] == 'shared':
            actual = sorted(re.findall(r'^stream .*$', text, re.M))
        else:
            raise ValueError('unknown output kind')
        expected = job['expected']
        report = dict(count=len(actual), actual=actual, expected=expected,
                      differences=[i for i,(a,b) in enumerate(zip(actual,expected)) if a != b],
                      count_matches=len(actual)==len(expected))
        (out/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
        if actual != expected:
            raise ValueError('selected exact output changed: '+job['name'])
        if job.get('early_exports') and (out/'stderr').read_text().count('EARLY_EXPORT_PASS:') != job['early_exports']:
            raise ValueError('early-export coverage mismatch')
        self.record('job-accepted', stage=stage, name=job['name'], frames=job['count'])

    def stage(self, name, module):
        self.identity(module)
        for job in self.c['jobs']:
            self.healthy()
            self.execute(name, job)

    def validate(self):
        if os.geteuid() == 0 or not os.environ.get('LIBVA_HW_GUARD_LEASE'):
            raise RuntimeError('ordinary user under outer hwguard required')
        if subprocess.check_output(['uname','-m'],text=True).strip() != 'aarch64' or b'apple,' not in Path('/proc/device-tree/compatible').read_bytes():
            raise RuntimeError('unsupported host')
        subprocess.run(['pacman','-Q','linux-asahi','linux-asahi-headers'],check=True,capture_output=True,timeout=5)
        if sha(self.c['candidate']) != CANDIDATE or sha(self.c['original']) != ORIGINAL:
            raise RuntimeError('module file identity')
        if len(self.c['jobs']) != 10 or sum(j['count'] for j in self.c['jobs']) != 1704:
            raise ValueError('reviewed workload extent changed')
        if len({j['name'] for j in self.c['jobs']}) != 10:
            raise ValueError('duplicate job')
        for path, digest in self.c['files'].items():
            if sha(path) != digest:
                raise RuntimeError('pinned input/tool changed: '+path)
        with (self.root/'attempted').open('x') as f:
            f.write('Single use. Preserve failure; never replay.\n')
            f.flush()
            os.fsync(f.fileno())
        self.identity('original')
        self.healthy()

    def run(self):
        self.validate()
        failure = None
        try:
            self.stage('baseline', 'original')
            self.healthy()
            self.transition('rmmod', 'apple_avd')
            self.changed = True
            self.healthy(present=False)
            self.transition('insmod', self.c['candidate'])
            self.identity('candidate')
            self.healthy()
            self.stage('candidate', 'candidate')
        except Exception as exc:
            failure = exc
            self.record('failed', error=str(exc))
        finally:
            if self.changed:
                try:
                    self.restore()
                except Exception as exc:
                    self.record('restore-incomplete', error=str(exc))
                    if failure is None:
                        failure = exc
            self.record('terminal', restored=self.restored)
        if failure:
            raise failure
        if not self.restored:
            raise RuntimeError('original not restored')
        try:
            self.stage('restored', 'original')
            self.healthy()
        except Exception as exc:
            self.record('restored-stage-failed', error=str(exc))
            raise
        self.record('complete', commands=30, frame_comparisons=5112)
        (self.root/'complete').write_text('30 accepted commands; original restored.\n')


if __name__ == '__main__':
    # External guard owns forced termination. No signal-driven module reset.
    Campaign(json.loads(Path(sys.argv[1]).read_text())).run()
