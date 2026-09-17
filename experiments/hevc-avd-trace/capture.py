#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One explicitly authorized run INSIDE hwguard; never loads or resets a module.

Client stays unprivileged. sudo -n is used only for fixed root-owned trace files.
Caller owns vector/client commands, output hashes, userspace trace and journal gate.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

TRACE = '/sys/kernel/debug/apple_avd_hevc_trace/'


class KernelTrace:
    def control(self, text):
        subprocess.run(['sudo','-n','tee',TRACE+'control'], input=text+'\n',text=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=3)

    def status(self):
        text=subprocess.check_output(['sudo','-n','cat',TRACE+'status'],text=True,timeout=3)
        parts=text.split()
        if len(parts)!=11 or parts[:2]!=['S','1'] or not all(x.isascii() and x.isdecimal() for x in parts[2:]):
            raise ValueError('invalid kernel status')
        values=list(map(int,parts[2:]))
        if any(x>=2**64 for x in values):raise ValueError('oversized status number')
        return dict(zip('run context phase errors count attempted pictures completions opens'.split(),values))

    def snapshot(self):
        return subprocess.check_output(['sudo','-n','cat',TRACE+'snapshot'],timeout=5)


def supervise(command, run, enabled, deadline, backend):
    """Return actual wait status even when tracing fails; never silently retry."""
    if not command or not 1 <= deadline <= 90 or not 1 <= run < 2**64:
        raise ValueError('command/run/deadline outside allowed scope')
    reader, writer=os.pipe()
    parent=os.getpid()
    pid=os.fork()
    if pid==0:
        try:
            os.close(writer)
            # If the guarded supervisor disappears, its client cannot continue decoding.
            libc=ctypes.CDLL(None,use_errno=True)
            if libc.prctl(1, signal.SIGKILL, 0, 0, 0)!=0 or os.getppid()!=parent:
                os._exit(125)
            if os.read(reader,1)!=b'G':os._exit(125)
            os.close(reader)
            os.execvpe(command[0],command,os.environ)
        except BaseException:
            os._exit(126)
    os.close(reader)
    result={'schema':'hevc-avd-trace.execution/1','run':run,'trace_enabled':enabled,
            'child_pid':pid,'child_exit':None,'trace_error':None,'status':None}
    waited=False
    started=time.monotonic()
    try:
        backend.control(f'arm {run} {pid}' if enabled else 'off')
        os.write(writer,b'G')
        os.close(writer);writer=-1
        while True:
            observed,status=os.waitpid(pid,os.WNOHANG)
            if observed:
                result['child_exit']=os.waitstatus_to_exitcode(status);waited=True;break
            st=backend.status();result['status']=st
            if st['errors'] or (enabled and st['run']!=run) or (not enabled and st['phase']!=0):
                raise ValueError('kernel trace error or wrong run/state')
            if time.monotonic()-started>=deadline:raise TimeoutError('finite run deadline')
            time.sleep(0.1)
    except (OSError,ValueError,subprocess.SubprocessError,TimeoutError) as e:
        result['trace_error']=str(e)
    finally:
        if writer!=-1:os.close(writer)
        if not waited:
            # Bounded termination; a D-state process is reported, never reset/reopened.
            for sig,seconds in ((signal.SIGTERM,1),(signal.SIGKILL,2)):
                try:os.kill(pid,sig)
                except ProcessLookupError:pass
                end=time.monotonic()+seconds
                while time.monotonic()<end:
                    observed,status=os.waitpid(pid,os.WNOHANG)
                    if observed:
                        result['child_exit']=os.waitstatus_to_exitcode(status);waited=True;break
                    time.sleep(0.05)
                if waited:break
    snapshot=None
    if waited and enabled:
        try:
            backend.control(f'seal {run}')
            # Even an invalid trace is retained privately for diagnosis.
            snapshot=backend.snapshot()
            result['status']=backend.status()
            if result['status']['errors'] or result['status']['phase']!=4 or result['status']['run']!=run:
                raise ValueError('sealed capture invalid')
        except (OSError,ValueError,subprocess.SubprocessError) as e:
            result['trace_error']=result['trace_error'] or str(e)
    result['elapsed_seconds']=round(time.monotonic()-started,3)
    result['child_reaped']=waited
    return result,snapshot


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=int,required=True)
    p.add_argument('--trace',choices=('on','off'),required=True)
    p.add_argument('--deadline',type=float,default=60)
    p.add_argument('--output',type=Path,required=True,help='new private directory; parent must exist')
    p.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args();cmd=a.command[1:] if a.command[:1]==['--'] else a.command
    if os.geteuid()==0:p.error('run as the ordinary user inside hwguard, not as root')
    if not cmd or not 1 <= a.deadline <=90 or not 1<=a.run<2**64:p.error('invalid command/run/deadline')
    a.output.mkdir(mode=0o700,parents=False,exist_ok=False)
    result,raw=supervise(cmd,a.run,a.trace=='on',a.deadline,KernelTrace())
    (a.output/'execution.json').write_text(json.dumps(result,indent=2)+'\n')
    if raw is not None:(a.output/'snapshot.txt').write_bytes(raw)
    if result['trace_error'] or result['child_exit'] is None:return 125
    status=result['child_exit']
    return status if status>=0 else 128-status

if __name__=='__main__':sys.exit(main())
