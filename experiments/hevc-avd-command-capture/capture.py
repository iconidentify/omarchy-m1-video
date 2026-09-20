#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One finite unprivileged decoder child with two recorder backends, inside hwguard.

No module operations. Fresh backends must be OFF. Every attempted transition and
actual waited child status is persisted before successful captures are cleared.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

PATHS={'reference':'/sys/kernel/debug/apple_avd_hevc_trace/',
       'command':'/sys/kernel/debug/apple_avd_hevc_cmdtrace/'}
FIELDS={'reference':'run context phase errors count attempted pictures completions opens'.split(),
        'command':'run context phase errors pictures completions opens'.split()}

class KernelTrace:
    def __init__(self,name):self.name=name
    def control(self,text):
        subprocess.run(['sudo','-n','tee',PATHS[self.name]+'control'],input=text+'\n',text=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=3)
    def status(self):
        text=subprocess.check_output(['sudo','-n','cat',PATHS[self.name]+'status'],text=True,timeout=3)
        p=text.split();fields=FIELDS[self.name]
        if len(p)!=len(fields)+2 or p[:2]!=['S','1']:raise ValueError('status schema: '+self.name)
        if any(not x.isascii() or not x.isdecimal() or len(x)>20 or str(int(x))!=x or int(x)>=2**64 for x in p[2:]):
            raise ValueError('status integer: '+self.name)
        return dict(zip(fields,map(int,p[2:])))
    def snapshot(self):
        raw=subprocess.check_output(['sudo','-n','cat',PATHS[self.name]+'snapshot'],timeout=5)
        limit=4*1024*1024 if self.name=='reference' else 512*1024
        if not 0<len(raw)<=limit:raise ValueError('snapshot size: '+self.name)
        return raw

class Store:
    def __init__(self,path):
        self.path=path;path.mkdir(mode=0o700,parents=False,exist_ok=False)
    def save(self,name,data):
        tmp=self.path/(name+'.tmp')
        with tmp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        tmp.replace(self.path/name)
        fd=os.open(self.path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    def event(self,result):self.save('execution.json',json.dumps(result,indent=2).encode()+b'\n')
    def snapshot(self,name,raw):self.save(name+'.snapshot',raw)

class NullStore:
    def event(self,result):pass
    def snapshot(self,name,raw):pass


def check_state(st,run,enabled,sealed=False):
    if st['errors']:raise ValueError('sticky recorder error')
    if st['pictures']>300 or st['completions']>st['pictures']:raise ValueError('recorder count extent')
    if enabled:
        if st['run']!=run or st['phase'] not in ((4,) if sealed else (1,2,3)):
            raise ValueError('recorder run/phase mismatch')
        if sealed and (not st['context'] or st['pictures']!=300 or st['completions']!=300 or st['opens']):
            raise ValueError('incomplete sealed capture')
    elif any(st[k] for k in ('run','context','phase','errors','pictures','completions')):
        raise ValueError('recorder is not off')


def supervise(command,run,enabled,deadline,backends,store=None,*,environment=None,
              working_directory=None,stdout_path=None,stderr_path=None):
    if not command or not 1<=deadline<=90 or not 1<=run<2**64 or set(backends)!=set(PATHS):
        raise ValueError('command/run/deadline/backend contract')
    if environment is not None and (type(environment) is not dict or
            any(type(key) is not str or type(value) is not str
                for key,value in environment.items())):
        raise ValueError('environment contract')
    if working_directory is not None and not Path(working_directory).is_dir():
        raise ValueError('working directory contract')
    if (stdout_path is None)!=(stderr_path is None):
        raise ValueError('child log path contract')
    store=store or NullStore()
    result=dict(schema='hevc-avd-command-capture.execution/1',run=run,enabled=enabled,
                child_pid=None,child_exit=None,child_reaped=False,child_released=False,
                errors=[],status={},snapshots={},events=[])
    started=time.monotonic();pid=None;writer=-1;armed=[];cancelled=[]
    def event(stage,name=None,fatal=True):
        result['events'].append(dict(stage=stage,recorder=name,seconds=round(time.monotonic()-started,4)))
        try:store.event(result)
        except OSError as exc:
            result['errors'].append(dict(stage='persist',recorder=name,error=str(exc)))
            if fatal:raise
    def error(stage,name,exc):
        result['errors'].append(dict(stage=stage,recorder=name,error=str(exc)))
        event(stage+'-failed',name,fatal=False)
    def stopped(signum,frame):cancelled.append(signum)
    old={sig:signal.signal(sig,stopped) for sig in (signal.SIGTERM,signal.SIGINT)}
    try:
        event('preflight')
        for name,b in backends.items():
            st=b.status();result['status'][name]=st;check_state(st,run,False)
            if st['opens']:raise ValueError('open context before arm: '+name)
        if cancelled or time.monotonic()-started>=deadline:raise TimeoutError('cancel/deadline before fork')
        reader,writer=os.pipe();parent=os.getpid();pid=os.fork()
        if pid==0:
            try:
                # Child must not inherit the supervisor's cancellation handler.
                signal.signal(signal.SIGTERM,signal.SIG_DFL);signal.signal(signal.SIGINT,signal.SIG_DFL)
                os.close(writer);libc=ctypes.CDLL(None,use_errno=True)
                if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:os._exit(125)
                if os.read(reader,1)!=b'G':os._exit(125)
                os.close(reader)
                if working_directory is not None:os.chdir(working_directory)
                if stdout_path is not None:
                    opened=[]
                    try:
                        for fd,path in ((1,stdout_path),(2,stderr_path)):
                            out=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
                            opened.append(out);os.dup2(out,fd)
                    finally:
                        for out in opened:os.close(out)
                os.execvpe(command[0],command,environment if environment is not None else os.environ)
            except BaseException:os._exit(126)
        os.close(reader);result['child_pid']=pid;event('child-blocked')
        for name,b in backends.items():
            if cancelled:raise InterruptedError('cancelled before arm')
            if enabled:
                # Record attempted arm too: a failing control write can still
                # leave kernel state to inspect, even if no success was returned.
                armed.append(name);event('arm-attempt',name);b.control(f'arm {run} {pid}')
            else:b.control('off')
            st=b.status();result['status'][name]=st;check_state(st,run,enabled)
            if st['opens']:raise ValueError('unexpected open context before release')
            event('armed' if enabled else 'disabled',name)
        if cancelled:raise InterruptedError('cancelled before child release')
        if time.monotonic()-started>=deadline:raise TimeoutError('deadline before child release')
        os.write(writer,b'G');os.close(writer);writer=-1
        result['child_released']=True;event('child-released')
        while True:
            observed,status=os.waitpid(pid,os.WNOHANG)
            if observed:
                result['child_exit']=os.waitstatus_to_exitcode(status);result['child_reaped']=True;break
            if cancelled:raise InterruptedError('supervisor cancelled')
            if time.monotonic()-started>=deadline:raise TimeoutError('finite decoder deadline')
            for name,b in backends.items():
                st=b.status();result['status'][name]=st;check_state(st,run,enabled)
            contexts=[s['context'] for s in result['status'].values() if s['context']]
            if len(contexts)==2 and contexts[0]!=contexts[1]:raise ValueError('paired recorder context mismatch')
            time.sleep(0.05)
        event('child-waited')
    except (OSError,ValueError,subprocess.SubprocessError) as exc:error('execution',None,exc)
    finally:
        if writer!=-1:os.close(writer)
        if pid and not result['child_reaped']:
            for sig,seconds in ((signal.SIGTERM,1),(signal.SIGKILL,2)):
                try:os.kill(pid,sig)
                except ProcessLookupError:pass
                until=time.monotonic()+seconds
                while time.monotonic()<until:
                    observed,status=os.waitpid(pid,os.WNOHANG)
                    if observed:
                        result['child_exit']=os.waitstatus_to_exitcode(status);result['child_reaped']=True;break
                    time.sleep(0.025)
                if result['child_reaped']:break
            if not result['child_reaped']:error('reap',None,'child did not reap; no recovery')
            else:event('child-terminated-and-waited',fatal=False)
        # Preserve each attempted recorder independently, including invalid captures.
        if result['child_reaped']:
            for name in armed:
                b=backends[name]
                try:
                    st=b.status();result['status'][name]=st
                    if st['run']!=run:raise ValueError('attempt did not bind this run')
                    if st['opens']:raise ValueError('context still open; cannot seal')
                    b.control(f'seal {run}');event('sealed',name)
                    raw=b.snapshot();store.snapshot(name,raw)
                    result['snapshots'][name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
                    event('snapshot-persisted',name)
                    st=b.status();result['status'][name]=st;check_state(st,run,True,sealed=True)
                except (OSError,ValueError,subprocess.SubprocessError) as exc:error('seal/read',name,exc)
        if result['child_reaped'] and not result['errors']:
            try:
                for name,b in backends.items():
                    st=b.status();result['status'][name]=st;check_state(st,run,enabled,sealed=enabled)
                    if st['opens']:raise ValueError('final open context')
                if enabled and len({s['context'] for s in result['status'].values()})!=1:
                    raise ValueError('final paired context mismatch')
            except (OSError,ValueError,subprocess.SubprocessError) as exc:error('final-status',None,exc)
        if cancelled and not result['errors']:error('cancelled',None,'supervisor signal received')
        # Clear only successful, durably preserved evidence. Failure stays sealed
        # for investigation; the caller must stop the campaign.
        if result['child_reaped'] and result['child_exit']==0 and not result['errors']:
            for name,b in backends.items():
                try:b.control('off');check_state(b.status(),run,False);event('cleared',name)
                except (OSError,ValueError,subprocess.SubprocessError) as exc:error('clear',name,exc)
        result['elapsed_seconds']=round(time.monotonic()-started,3);event('complete',fatal=False)
        for sig,handler in old.items():signal.signal(sig,handler)
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run',type=int,required=True);ap.add_argument('--trace',choices=('on','off'),required=True)
    ap.add_argument('--deadline',type=float,default=60);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('command',nargs=argparse.REMAINDER);a=ap.parse_args()
    cmd=a.command[1:] if a.command[:1]==['--'] else a.command
    if os.geteuid()==0 or not os.environ.get('LIBVA_HW_GUARD_LEASE'):ap.error('ordinary user inside hwguard required')
    result=supervise(cmd,a.run,a.trace=='on',a.deadline,{name:KernelTrace(name) for name in PATHS},Store(a.output))
    if result['errors'] or result['child_exit'] is None:return 125
    return result['child_exit'] if result['child_exit']>=0 else 128-result['child_exit']

if __name__=='__main__':sys.exit(main())
