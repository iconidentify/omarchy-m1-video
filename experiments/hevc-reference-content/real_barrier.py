#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile and run extracted wait/exporter helpers with stubs. Not client instrumentation."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import client_source
from adapter import AdapterError

HERE = Path(__file__).resolve().parent
READERS_ERROR = (
    'if (ret < 0) {\n'
    '\t\t\tv4l2r_diag(ctx, V4L2R_DIAG_LEVEL_ERROR,\n'
    '\t\t\t\t   v4l2r_diag_errno_category(ret), "reader-wait",\n'
    '\t\t\t\t   ret, "failed waiting for readers of CAPTURE "\n'
    '\t\t\t\t   "buffer %d plane %u", index, i);\n'
    '\t\t\treturn ret;\n'
    '\t\t}'
)


def write_extracted(destination: Path, mutate=None):
    texts = client_source.fetch()
    bodies, _ = client_source.extract(texts)
    names = (
        'wait_on_capture_locked',
        'capture_wait_readers',
        'vb2_dc_dmabuf_ops_begin_cpu_access',
        'vb2_dc_dmabuf_ops_end_cpu_access',
    )
    parts = [bodies[n] for n in names]
    if mutate == 'readers-error':
        if parts[1].count(READERS_ERROR) != 1:
            raise ValueError('readers-error mutation drift')
        parts[1] = parts[1].replace(READERS_ERROR, 'if (ret < 0) { /* mutated: ignore */ }')
    elif mutate == 'clear-all':
        old = '\twhile (ctx->queued_capture & (UINT64_C(1) << index)) {'
        if parts[0].count(old) != 1:
            raise ValueError('wait mutation drift')
        parts[0] = parts[0].replace(old, '\tctx->queued_capture = 0;\n\twhile (0) {')
    destination.write_text('\n'.join(parts) + '\n')


def run_harness(case='success', mutate=None):
    with tempfile.TemporaryDirectory() as tmp:
        extracted = Path(tmp) / 'extracted-barrier.h'
        write_extracted(extracted, mutate=mutate)
        binary = Path(tmp) / 'barrier'
        subprocess.run(
            ['cc', '-O0', '-g', '-fsanitize=address,undefined', '-Wall', '-Werror',
             '-Wno-unused-function', '-Wno-unused-variable',
             '-I', tmp, str(HERE / 'barrier_harness.c'), '-o', str(binary)],
            check=True, timeout=30)
        return subprocess.run([str(binary), case], capture_output=True, text=True, timeout=10)


def prove_no_real_barrier():
    result = run_harness('success')
    if result.returncode != 0:
        raise AdapterError('barrier harness failed: ' + result.stdout + result.stderr)
    if 'selected-index wait' not in result.stdout or 'leftover=0x2' not in result.stdout:
        raise AdapterError('selected-index leftover capture was not preserved')
    for case in ('readers-fail', 'dequeue-fail', 'poll-fail'):
        extra = run_harness(case)
        if extra.returncode != 0:
            raise AdapterError(case + ' failed: ' + extra.stdout + extra.stderr)
    mutant = run_harness('readers-fail', mutate='readers-error')
    if mutant.returncode == 0:
        raise AdapterError('removing capture_wait_readers error return was not distinguished')
    cleared = run_harness('success', mutate='clear-all')
    if cleared.returncode == 0:
        raise AdapterError('clearing every queued capture was not distinguished')
    return result.stdout.strip()
