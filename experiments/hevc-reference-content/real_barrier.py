#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile and run extracted wait/exporter functions. Not a source-string scan."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import client_source
from adapter import AdapterError

HERE = Path(__file__).resolve().parent


def write_extracted(destination: Path, mutate=False):
    texts = client_source.fetch()
    bodies, _ = client_source.extract(texts)
    names = (
        'wait_on_capture_locked',
        'capture_wait_readers',
        'vb2_dc_dmabuf_ops_begin_cpu_access',
        'vb2_dc_dmabuf_ops_end_cpu_access',
    )
    parts = [bodies[n] for n in names]
    if mutate:
        old = 'while (ctx->queued_capture & (UINT64_C(1) << index)) {'
        if parts[0].count(old) != 1:
            raise ValueError('wait mutation drift')
        parts[0] = parts[0].replace(
            old, 'ctx->all_producers_paused = 1;\nwhile (ctx->queued_capture & (UINT64_C(1) << index)) {')
    destination.write_text('\n'.join(parts) + '\n')


def run_harness(mutate=False):
    with tempfile.TemporaryDirectory() as tmp:
        extracted = Path(tmp) / 'extracted-barrier.h'
        write_extracted(extracted, mutate=mutate)
        binary = Path(tmp) / 'barrier'
        subprocess.run(
            ['cc', '-O0', '-g', '-fsanitize=address,undefined', '-Wall', '-Werror',
             '-I', tmp, str(HERE / 'barrier_harness.c'), '-o', str(binary)],
            check=True, timeout=30)
        return subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)


def prove_no_real_barrier():
    result = run_harness()
    if result.returncode != 0:
        raise AdapterError('barrier harness failed: ' + result.stdout + result.stderr)
    if 'no pause token' not in result.stdout:
        raise AdapterError('barrier harness missing proof')
    mutant = run_harness(mutate=True)
    if mutant.returncode != 11:
        raise AdapterError('mutating wait_on_capture_locked to fake pause was not distinguished')
    return result.stdout.strip()
