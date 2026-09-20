#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual VAAPI device/pool/readback paths under synthetic libva; no device."""
import argparse
import importlib.util
import os
import resource
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'va-callsite'))
spec = importlib.util.spec_from_file_location('readback_ffmpeg_sources', HERE.parent / 'va-callsite/tests.py')
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)
ENV = os.environ | {'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                    'UBSAN_OPTIONS': 'halt_on_error=1'}
SANITIZERS = '-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer'


def command(argv, cwd=None):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, text=True, capture_output=True,
                            timeout=1200, env=ENV)
    if result.returncode:
        raise RuntimeError(' '.join(map(str, argv)) + '\n' + (result.stdout + result.stderr)[-16000:])
    return result.stdout


def test(root, archive):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    tree = sources.fetch_tree(root, archive)
    command(['patch', '--batch', '--fuzz=0', '-p1', '-i', HERE / 'ffmpeg-observer-copy-readback.patch'], tree)
    build = root / 'build'
    build.mkdir()
    command([tree / 'configure', '--disable-everything', '--disable-autodetect',
             '--enable-vaapi', '--enable-libdrm', '--enable-pthreads', '--disable-programs',
             '--disable-doc', '--disable-network', '--enable-debug=3', '--disable-stripping',
             '--extra-cflags=' + SANITIZERS + ' -ffunction-sections -fdata-sections',
             '--extra-ldflags=' + SANITIZERS], build)
    command(['make', '-j4', 'libavutil/libavutil.a'], build)
    cflags = shlex.split(command(['pkg-config', '--cflags', '--libs', 'libva', 'libva-drm', 'libdrm']))
    source = tree / 'libavutil/hwcontext_vaapi.c'
    original = source.read_text()
    def compile_run(name):
        binary = root / name
        command(['cc', '-DHAVE_AV_CONFIG_H', '-DVAAPI_SOURCE="' + str(source) + '"',
                 '-I' + str(build), '-I' + str(tree), '-g', '-ffunction-sections', '-fdata-sections',
                 *SANITIZERS.split(), HERE / 'readback-fixture.c', build / 'libavutil/libavutil.a',
                 '-Wl,--gc-sections,--wrap=open,--wrap=open64', *cflags, '-lm', '-pthread', '-ldl', '-o', binary])
        return subprocess.run([binary], text=True, capture_output=True, timeout=30, env=ENV)
    baseline = compile_run('positive')
    if baseline.returncode or 'PASS actual device/frame initialization' not in baseline.stdout:
        raise RuntimeError('actual-source baseline failed\n' + baseline.stdout + baseline.stderr)
    print(baseline.stdout, end='', flush=True)
    mutations = (
        ('probe-gate', '!((VAAPIDeviceContext *)hwfc->device_ctx->hwctx)->observer_copy_readback', '1', 'copy-readback-probe'),
        ('default-preserved', '!((VAAPIDeviceContext *)hwfc->device_ctx->hwctx)->observer_copy_readback', '0', 'copy-readback-probe'),
        ('option-wired', 'hwctx->observer_copy_readback = !strcmp(entry->value, "1");',
         'hwctx->observer_copy_readback = 0;', 'copy-readback-probe'),
        ('invalid-before-open', 'if (strcmp(entry->value, "0") && strcmp(entry->value, "1"))',
         'if (0 && strcmp(entry->value, "1"))', 'invalid-option-before-open'),
    )
    for name, old, new, assertion in mutations:
        if original.count(old) != 1:
            raise RuntimeError('mutation source extent: ' + name)
        try:
            source.write_text(original.replace(old, new, 1))
            result = compile_run('mutant-' + name)
            if result.returncode != -6 or ('ASSERT:' + assertion) not in result.stderr or \
                    'ERROR: AddressSanitizer' in result.stderr or 'runtime error:' in result.stderr:
                raise RuntimeError('mutation not detected by its assertion: ' + name + '\n' + result.stdout + result.stderr)
            print('PASS mutation ' + name + ': ' + assertion, flush=True)
        finally:
            source.write_text(original)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--keep', type=Path)
    args = parser.parse_args()
    if args.keep:
        args.keep.mkdir(parents=True, exist_ok=False)
        test(args.keep.resolve(), args.archive)
    else:
        with tempfile.TemporaryDirectory(prefix='hevc-readback-') as directory:
            test(Path(directory), args.archive)
