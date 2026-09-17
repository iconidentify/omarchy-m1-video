#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Patch application and preservation checks against exact upstream sources."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import prepare


def calls(text, name):
    out=[]
    for match in re.finditer(r'\b'+name+r'\(',text):
        start=match.end();pos=start;depth=1
        while depth:
            if text[pos]=='(':depth+=1
            if text[pos]==')':depth-=1
            pos+=1
        out.append(re.sub(r'\s+','',text[start:pos-1]))
    return out


def verify(source):
    with tempfile.TemporaryDirectory() as tmp:
        work=Path(tmp)/'candidate';prepare.prepare(source,work)
        pristine=Path(tmp)/'stack';pristine.mkdir()
        import shutil,json
        manifest=json.loads((prepare.HERE/'sources.json').read_text())
        for name in manifest['upstream_files']:shutil.copyfile(source/name,pristine/name)
        for p in manifest['patches']['files']:
            subprocess.run(['patch','--batch','--fuzz=0','-p6','-i',str(prepare.REPO/p['path'])],cwd=pristine,check=True,stdout=subprocess.PIPE)
        old=(pristine/'avd-hevc.c').read_text();new=(work/'avd-hevc.c').read_text()
        for name in ('push','pusha','push_comp','writel','avd_submit_job','avd_run_postamble'):
            if calls(old,name)!=calls(new,name):raise ValueError('decode operations changed: '+name)
        # Lookup still precedes the TMVP gate and remains after the I early return.
        mv=new[new.index('static void stream_slice_mv('):new.index('static void set_slice(')]
        if not mv.index('return;') < mv.index('avd_get_ref_buf_observed(') < mv.index('ref_valid ='):
            raise ValueError('motion control flow changed')
        drv=(work/'avd-drv.c').read_text()
        if drv.count('avd_trace_job(ctx);')!=1:raise ValueError('unexpected job hook')
        if drv.index('cancel_delayed_work_sync(&ctx->watchdog_work);',drv.index('static int avd_release'))>drv.index('avd_trace_close(ctx);'):
            raise ValueError('close precedes watchdog quiescence')
        # Existing directories and mismatched inputs are rejected before mutation.
        try:prepare.prepare(source,work)
        except FileExistsError:pass
        else:raise ValueError('existing output overwritten')
        (pristine/'avd-hevc.c').write_text('deliberately wrong source\n')
        try:prepare.prepare(pristine,Path(tmp)/'bad')
        except ValueError:pass
        else:raise ValueError('mismatched source accepted')
        if (Path(tmp)/'bad').exists():raise ValueError('bad input created output')
    print('PASS: exact stack application, unchanged decode emissions/submission, hook order and fail-closed preparation')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path)
    verify(p.parse_args().source.resolve())
