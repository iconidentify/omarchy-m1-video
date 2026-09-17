#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile exact prepared kernel wrapper functions with pthread/seq stubs."""
import subprocess
from pathlib import Path
import packing

HERE=Path(__file__).resolve().parent

def verify(candidate,out,uapi,negative=False):
    out.mkdir()
    for command in ((True,) if negative else (False,True)):
        name='command' if command else 'reference';work=out/name;work.mkdir()
        code=(candidate/('avd-cmdtrace.c' if command else 'avd-trace.c')).read_text()
        prefix='cmd' if command else 'atr';typ='cmd_capture' if command else 'atr_capture'
        header='cmd-core.h' if command else 'avd-trace-core.h'
        source=f'#include "{header}"\n#define CAPTURE_BYTES sizeof(struct {typ})\n'
        source+=f'static DEFINE_MUTEX({prefix}_control_lock);\nstatic DEFINE_SPINLOCK({prefix}_lock);\n'
        source+=f'static struct {typ} *capture;\nstatic u64 open_contexts,last_run;\nstatic bool snapshot_busy;\n'
        if command:
            source+='#define CMD_CAPACITY_MARK 2048\n'
            # selected is static; public hooks extracted by adding a scanner-only
            # static prefix to the temporary string, not editing function bodies.
            names=('selected','pack_bytes','pack_u16','pack_u32','pack_u64','pack_controls','avd_cmdtrace_open','avd_cmdtrace_close','avd_cmdtrace_job','avd_cmdtrace_start','avd_cmdtrace_word','avd_cmdtrace_inactive','avd_cmdtrace_slice_meta','avd_cmdtrace_done')
            scan=code
            for n in names:
                if n.startswith('avd_'):scan=scan.replace('void '+n+'(', 'static void '+n+'(',1)
            source+='\n'.join(packing.extract(scan,n) for n in names)+'\n'
        source+=packing.extract(code,'control_write')+'\n'
        source+=packing.extract(code,'snapshot_rows')+'\n'+packing.extract(code,'snapshot_row')+'\n'
        source+=f'#define BND_CONTROL_LOCK {prefix}_control_lock\n#define BND_LOCK {prefix}_lock\n#define BND_SEALED {prefix.upper()}_SEALED\n#include "bounded-snapshot.h"\n'
        (work/'wrapper-functions.h').write_text(source)
        args=['cc','-std=gnu11','-Wall','-Werror','-Wno-unused-function','-fsanitize=address,undefined',
              '-fno-sanitize-recover=all','-pthread','-I',str(work),'-I',str(candidate),'-I',str(uapi.parent),
              str(HERE/'wrapper-host.c'),'-o',str(work/'wrapper')]
        if command:args.insert(1,'-DTEST_COMMAND')
        subprocess.run(args,check=True,timeout=60)
        r=subprocess.run([str(work/'wrapper')],capture_output=True,text=True,timeout=30)
        (work/'run.log').write_text(r.stdout+r.stderr)
        if negative:
            assert r.returncode != 0, 'reader/free guard mutation escaped'
            print('PASS: removing the actual reader/free guard breaks the wrapper test')
        else:
            if r.returncode:raise RuntimeError(r.stderr)
            print(r.stdout.strip())
