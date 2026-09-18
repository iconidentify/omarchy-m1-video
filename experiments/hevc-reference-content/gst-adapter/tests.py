#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile patched gst_v4l2_request_queue with the default-off observer. No device."""
from pathlib import Path
import subprocess
import sys
import tempfile
import source

HERE = Path(__file__).resolve().parent


def compile_run(mutate=None):
    texts = source.fetch()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'extracted-gst.inc').write_text(source.patched_bodies(texts, mutate=mutate))
        binary = tmp / 'harness'
        cmd = ['cc', '-std=c11', '-O0', '-g', '-fsanitize=address,undefined',
               '-Wall', '-Werror', '-Wno-unused-parameter',
               '-I', str(HERE), '-I', str(tmp),
               str(HERE / 'harness.c'), str(HERE / 'gst-observer.c'),
               '-o', str(binary)]
        built = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if built.returncode:
            raise RuntimeError(built.stderr[-4000:])
        return subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)


def main():
    result = compile_run()
    if result.returncode:
        raise SystemExit('harness failed:\n' + result.stdout + result.stderr)
    if 'PASS' not in result.stdout:
        raise SystemExit('missing PASS')
    print(result.stdout.strip())
    for mutate, label in (('no-queue-hook', 'queue hook'),
                          ('no-free-hook', 'free hook'),
                          ('no-flush-hook', 'flush hook')):
        mutant = compile_run(mutate=mutate)
        if mutant.returncode == 0:
            raise SystemExit('mutation not distinguished: ' + label + '\n' + mutant.stdout)
        print('PASS: rejected', label, 'mutation')


if __name__ == '__main__':
    main()
