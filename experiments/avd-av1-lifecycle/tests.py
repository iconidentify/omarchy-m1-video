#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce AV1 start unwind leak against extracted source, then the isolated patch."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RETRY = REPO / 'experiments/avd-allocation-retry'


def load_retry():
    import importlib.util
    spec = importlib.util.spec_from_file_location('avd_alloc_retry_source', RETRY / 'source.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extract_tree(root: Path) -> tuple:
    src = load_retry()
    cache = os.environ.get('AVD_SOURCE_CACHE')
    pinned = src.prepare(root / 'pinned', cache=Path(cache) if cache else None)
    expected = json.loads((HERE / 'patch-identities.json').read_text())
    for name, digest in expected.items():
        path = RETRY / 'candidate.patch' if name == 'base_candidate' else HERE / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('patch identity drift: ' + name)
    cand = src.patch(pinned, RETRY / 'candidate.patch', root / 'candidate')
    dest = root / 'av1-fixed'
    import shutil
    shutil.copytree(cand, dest)
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(HERE / 'av1-unwind.patch')],
                   cwd=dest, check=True, stdout=subprocess.PIPE, timeout=30)
    return pinned / 'patched', cand, dest


def write_extracted(tree: Path, dest: Path, mutant=False):
    src = load_retry()
    drv = (tree / 'avd-drv.c').read_text()
    av1 = (tree / 'avd-av1.c').read_text()
    bodies = [src.function(drv, 'avd_buf_free'), src.function(drv, 'avd_buf_alloc'),
              src.function(av1, 'avd_av1_alloc_bufs'), src.function(av1, 'avd_av1_stop'),
              src.function(av1, 'avd_av1_start')]
    if mutant == 'null-stop':
        old = 'if (!av1_ctx)\n\t\treturn;'
        if bodies[3].count(old) != 1: raise ValueError('null mutation drift')
        bodies[3] = bodies[3].replace(old, '')
    elif mutant:
        old = 'avd_av1_stop(ctx);'
        if bodies[4].count(old) != 1:
            raise ValueError('unwind mutation drift')
        bodies[4] = bodies[4].replace(old, 'kfree(av1_ctx);')
    dest.write_text('\n'.join(bodies) + '\n')
    dest.with_suffix('.json').write_text(json.dumps([hashlib.sha256(b.encode()).hexdigest() for b in bodies]))


def run_case(tree: Path, failure: int, mutant=False, null_stop=False):
    with tempfile.TemporaryDirectory() as tmp:
        extracted = Path(tmp) / 'extracted.h'
        write_extracted(tree, extracted, mutant=mutant)
        (Path(tmp) / 'actual-buf.h').write_text(load_retry().struct((tree / 'avd.h').read_text(), 'avd_buf'))
        binary = Path(tmp) / 'harness'
        subprocess.run(['cc', '-O0', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-Wall', '-Werror',
                        '-I', tmp, str(HERE / 'harness.c'), '-o', str(binary)],
                       check=True, timeout=30)
        result = subprocess.run([str(binary), str(failure)] + (['stop-null'] if null_stop else []), capture_output=True, text=True, timeout=10)
        return result.returncode, result.stdout, result.stderr


class Unwind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='av1-life-'))
        cls.addClassCleanup(shutil.rmtree, cls.root)
        cls.pinned, cls.candidate, cls.fixed = extract_tree(cls.root)

    def test_success_start_stop(self):
        for tree in (self.pinned, self.candidate, self.fixed):
            rc, out, err = run_case(tree, 0)
            self.assertEqual(rc, 0, out + err)
            self.assertIn('leaked=0', out)

    def test_context_alloc_failure(self):
        for tree in (self.pinned, self.candidate, self.fixed):
            rc, out, err = run_case(tree, -1)
            self.assertEqual(rc, 0, out + err)
            self.assertIn('leaked=0', out)

    def test_second_buffer_failure_leaks_on_unpatched(self):
        rc, out, err = run_case(self.candidate, 2)
        self.assertEqual(rc, 95, out + err)
        self.assertIn('leaked=1', out)

    def test_third_buffer_failure_leaks_two_on_unpatched(self):
        rc, out, err = run_case(self.candidate, 3)
        self.assertEqual(rc, 95, out + err)
        self.assertIn('leaked=2', out)

    def test_patch_unwinds_partial_allocation(self):
        for fail in (1, 2, 3):
            rc, out, err = run_case(self.fixed, fail)
            self.assertEqual(rc, 0, f'fail={fail} {out}{err}')
            self.assertIn('leaked=0', out)

    def test_reverting_cleanup_fails_oracle(self):
        rc, out, err = run_case(self.fixed, 2, mutant=True)
        self.assertEqual(rc, 95, out + err)

    def test_null_stop_after_success_and_each_failure(self):
        for fail in (-1, 0, 1, 2, 3):
            rc, out, err = run_case(self.fixed, fail, null_stop=True)
            self.assertEqual(rc, 0, out + err)

    def test_removing_null_guard_is_detected(self):
        rc, out, err = run_case(self.fixed, -1, mutant='null-stop', null_stop=True)
        self.assertNotEqual(rc, 0, out + err)
        self.assertIn('runtime error', err)

    def test_docs(self):
        readme = (HERE / 'README.md').read_text()
        self.assertIn('does not claim av1 hardware support', readme.lower())
        self.assertNotIn('Fixes https://github.com/iconidentify/omarchy-m1-video/issues/8', readme)


if __name__ == '__main__':
    unittest.main()
