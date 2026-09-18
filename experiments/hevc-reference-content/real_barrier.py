#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute four pinned helper bodies with explicit stub boundaries. No live barrier."""
from __future__ import annotations
import json
import os
import subprocess
import tempfile
from pathlib import Path
import client_source
from adapter import AdapterError

HERE=Path(__file__).resolve().parent
NAMES=('wait_on_capture_locked','capture_wait_readers',
       'vb2_dc_dmabuf_ops_begin_cpu_access','vb2_dc_dmabuf_ops_end_cpu_access')
MUTATIONS={
    'reader-error':('capture_wait_readers','if (ret < 0) {','if (0) {',1),
    'reader-timeout':('capture_wait_readers','V4L2R_POLL_TIMEOUT_MS','0',1),
    'reader-negative-fd':('capture_wait_readers','if (capture->dmabuf_fd[i] < 0)','if (0)',1),
    'wait-clear-all':('wait_on_capture_locked','if (ctx->queued_capture) {','ctx->queued_capture = 0;\n\tif (ctx->queued_capture) {',1),
    'wait-index':('wait_on_capture_locked','UINT64_C(1) << index','UINT64_C(1) << (index + 1)',1),
    'wait-error':('wait_on_capture_locked','if (ret < 0)','if (0)',2),
    'wait-deadline':('wait_on_capture_locked','ctx->video_fd, POLLIN, deadline','ctx->video_fd, POLLIN, deadline + 1',1),
    'wait-device':('wait_on_capture_locked','ctx->video_fd, POLLIN, deadline','ctx->video_fd + 1, POLLIN, deadline',1),
    'wait-retry':('wait_on_capture_locked','ret < 0 && ret != -EAGAIN && ret != -EINTR','ret < 0',1),
    'cpu-result':('vb2_dc_dmabuf_ops_begin_cpu_access','return 0;','return -1;',1),
}


def extracted_bodies():
    texts=client_source.fetch()
    bodies,hashes=client_source.extract(texts)
    expected=json.loads((HERE/'function-hashes.json').read_text())
    if hashes!=expected:raise AdapterError('extracted helper identity mismatch')
    return {name:bodies[name] for name in NAMES}


def run_harness(bodies,mutation=None):
    bodies=dict(bodies)
    if mutation:
        name,old,new,count=MUTATIONS[mutation]
        if bodies[name].count(old)!=count:raise ValueError('mutation drift: '+mutation)
        bodies[name]=bodies[name].replace(old,new)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp)/'extracted-barrier.h').write_text('\n'.join(bodies[n] for n in NAMES)+'\n')
        binary=Path(tmp)/'barrier'
        subprocess.run([os.environ.get('CC','cc'),'-O0','-g','-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all','-Wall','-Werror','-I',tmp,
                        str(HERE/'barrier_harness.c'),'-o',str(binary)],check=True,timeout=30)
        return subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)


def exercise_selected_helpers():
    bodies=extracted_bodies()
    result=run_harness(bodies)
    if result.returncode!=0 or result.stdout.strip()!='PASS: 15 isolated helper cases; no device or real adapter executed':
        raise AdapterError('helper harness failed: '+result.stdout+result.stderr)
    if 'Sanitizer' in result.stderr or 'runtime error:' in result.stderr:
        raise AdapterError('helper sanitizer diagnostic')
    for mutation in MUTATIONS:
        mutant=run_harness(bodies,mutation)
        # Only the explicit semantic assertion counts. Compiler errors, crashes,
        # deadline expiry or sanitizer failures are not successful mutations.
        if mutant.returncode!=1 or 'case ' not in mutant.stderr or 'Sanitizer' in mutant.stderr or 'runtime error:' in mutant.stderr:
            raise AdapterError('semantic mutation not distinguished: '+mutation+' '+mutant.stdout+mutant.stderr)
    return result.stdout.strip()+f'; {len(MUTATIONS)} semantic mutations rejected'
