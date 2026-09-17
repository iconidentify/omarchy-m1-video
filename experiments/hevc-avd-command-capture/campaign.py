#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Single-use temporary experiment, entirely inside one outer hwguard lease."""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class Campaign:
    def __init__(self,config_path):
        self.config_path=config_path;self.c=json.loads(config_path.read_text());self.root=Path(self.c['root'])
        sys.path.insert(0,str(Path(self.c['guard']).parent))
        import hwguard
        self.guard=hwguard;self.backend=hwguard.LinuxBackend(preflight_since=self.c['fixed_boundary'])
        self.changed=False;self.restored=False
    def record(self,event,**data):
        with (self.root/'campaign-events.jsonl').open('a') as f:
            f.write(json.dumps(dict(event=event,lease=os.environ.get('LIBVA_HW_GUARD_LEASE'),**data))+'\n');f.flush();os.fsync(f.fileno())
    def healthy(self,require_present=True):
        state=self.backend.state()
        self.record('state',**dataclasses.asdict(state))
        if state.busy or state.wedged or state.faults:raise RuntimeError('STOP: not healthy/idle; no module recovery')
        if state.module_loaded and Path('/sys/module/apple_avd/initstate').read_text().strip()!='live':
            raise RuntimeError('STOP: module is not live; no recovery')
        if require_present and not (state.module_loaded and state.video_node):raise RuntimeError('decoder missing')
        return state
    def identity(self,which):
        if sha(self.c['original'])!=self.c['original_sha256']:raise RuntimeError('installed original changed')
        note=Path('/sys/module/apple_avd/notes/.note.gnu.build-id').read_bytes()
        if note!=(self.root/(which+'.build-id.note')).read_bytes():raise RuntimeError('loaded module identity: '+which)
    def command(self,*args):
        self.record('transition-attempt',argv=list(args))
        r=subprocess.run(['sudo','-n',*args],capture_output=True,text=True,timeout=15)
        self.record('transition-result',argv=list(args),returncode=r.returncode,stdout=r.stdout,stderr=r.stderr)
        if r.returncode:raise RuntimeError('module transition failed; no retry: '+args[0])
    def restore(self):
        state=self.healthy(require_present=False)
        if state.module_loaded:
            self.identity('candidate');self.command('rmmod','apple_avd')
        self.healthy(require_present=False)
        self.command('modprobe','apple_avd')
        self.identity('original');self.healthy();self.restored=True
        self.record('original-restored',installed_sha256=sha(self.c['original']))

    def record_final_state(self):
        # Guard may observe process exit before its next polling interval.
        # Always retain the terminal fault/module state even on a quick failure.
        state=self.backend.state()
        path=Path('/sys/module/apple_avd/initstate')
        self.record('terminal-state',**dataclasses.asdict(state),
                    module_initstate=path.read_text().strip() if path.exists() else None,
                    original_restored=self.restored)
    def run(self):
        if os.geteuid()==0 or not os.environ.get('LIBVA_HW_GUARD_LEASE'):raise RuntimeError('ordinary user under hardware guard required')
        with (self.root/'campaign-attempted').open('x') as f:f.write('Single use; no replay.\n');f.flush();os.fsync(f.fileno())
        if subprocess.check_output(['uname','-m'],text=True).strip()!='aarch64' or b'apple,' not in Path('/proc/device-tree/compatible').read_bytes():raise RuntimeError('unsupported host')
        subprocess.run(['pacman','-Q','linux-asahi','linux-asahi-headers'],check=True,capture_output=True,timeout=5)
        for path,digest in self.c['tool_sha256'].items():
            if sha(path)!=digest:raise RuntimeError('tool identity changed: '+path)
        if sha(self.c['candidate'])!=self.c['candidate_sha256']:raise RuntimeError('candidate changed')
        self.identity('original');self.healthy()
        failure=None
        try:
            self.command('rmmod','apple_avd');self.changed=True
            self.healthy(require_present=False)
            self.command('insmod',self.c['candidate']);self.identity('candidate');self.healthy()
            number=0
            for vector in 'BE':
                for client in ('va','gst'):
                    for mode in ('off','on'):
                        number+=1;self.identity('candidate');self.healthy()
                        name=f'{vector}-{client}-{mode}'
                        self.record('run-start',name=name,run_id=number)
                        r=subprocess.run([sys.executable,str(HERE/'measure.py'),str(self.config_path),vector,client,mode,str(number)],timeout=180)
                        self.record('run-result',name=name,run_id=number,returncode=r.returncode)
                        if r.returncode:raise RuntimeError('capture/validation failed: '+name)
                        self.healthy()
        except Exception as exc:
            failure=exc;self.record('campaign-failed',error=str(exc))
        finally:
            if self.changed:
                try:self.restore()
                except Exception as exc:
                    self.record('restoration-not-completed',error=str(exc))
                    if failure is None:failure=exc
            self.record_final_state()
        if failure:raise failure
        if not self.restored:raise RuntimeError('original restoration not proved')
        self.record('complete',runs=8,restored=True)
        (self.root/'campaign-complete').write_text('Eight validated runs and original module restored.\n')

if __name__=='__main__':Campaign(Path(sys.argv[1]).resolve()).run()
