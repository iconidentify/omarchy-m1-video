#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build actual patched decode.c observer API with a named fake V4L2 backend."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
import subprocess
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
PIN = 'c77e7b566f7baf9c7a2aad797e62c9aa578d9687'
ARCHIVE_SHA = 'a82f316c0468d3a5490bcfc33c8a876eab0e2b55ec1416b88f7f920535fc5bf4'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('mutation drift: ' + old[:80])
    return text.replace(old, new)


def fetch_tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    url = f'https://codeload.github.com/iconidentify/libva-v4l2_request/tar.gz/{PIN}'
    archive = urllib.request.urlopen(url, timeout=60).read()
    digest = sha(archive)
    if ARCHIVE_SHA != 'TO_FILL' and digest != ARCHIVE_SHA:
        raise ValueError('driver archive identity mismatch: ' + digest)
    print('archive_sha256', digest)
    (root / 'source.tar.gz').write_bytes(archive)
    with tarfile.open(root / 'source.tar.gz') as stream:
        stream.extractall(root, filter='data')
    tree = root / ('libva-v4l2_request-' + PIN)
    if not tree.exists():
        matches = list(root.glob('libva-v4l2_request-*'))
        if len(matches) != 1:
            raise FileNotFoundError('extracted driver tree')
        tree = matches[0]
    patch = HERE / 'driver-observer.patch'
    result = subprocess.run(
        ['patch', '-p1', '--fuzz=0', '-i', str(patch)],
        cwd=tree, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return tree


def compile_and_run(tree: Path, decode_text: str, context_text: str, env=None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'decode.c').write_text(decode_text)
        (root / 'context.c').write_text(context_text)
        binary = root / 'observer-test'
        va_cflags = subprocess.check_output(['pkg-config', '--cflags', 'libva'], text=True).split()
        cmd = [
            'cc', '-std=gnu11', '-O0', '-g', '-fsanitize=address,undefined',
            '-fno-sanitize-recover=all', '-Wall', '-Werror',
            '-Wno-unused-parameter',
            '-I', str(tree / 'build'), '-I', str(tree), '-I', str(tree / 'src'), *va_cflags,
            '-Wl,--wrap=ioctl', '-Wl,--wrap=poll',
            str(HERE / 'observer-test.c'), str(root / 'decode.c'), str(root / 'context.c'),
            str(tree / 'src/handles.c'),
            '-lpthread', '-o', str(binary),
        ]
        compiled = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr[-4000:])
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        run_env.setdefault('ASAN_OPTIONS', 'detect_leaks=1:halt_on_error=1')
        return subprocess.run([str(binary)], capture_output=True, text=True, timeout=10, env=run_env)


def full_driver_build(tree):
    build = tree / 'build'
    subprocess.run(['meson', 'setup', str(build), str(tree),
                    '--buildtype=debug', '-Db_sanitize=address,undefined'],
                   check=True, capture_output=True, text=True, timeout=60)
    result = subprocess.run(['meson', 'compile', '-C', str(build), '-j', '4',
                             'v4l2_request_drv_video'],
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    sources = re.findall(r"'([^']+\.c)'", (tree / 'src/meson.build').read_text())
    flags = subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'libva', 'libdrm'], text=True).split()
    binary = build / 'observer-public-api'
    command = ['cc', '-std=gnu11', '-g', '-O0', '-fsanitize=address,undefined',
               '-fno-sanitize-recover=all', '-UNDEBUG', '-pthread',
               '-I', str(build), '-I', str(tree / 'src'),
               str(HERE / 'public-api-test.c')]
    command += [str(tree / 'src' / name) for name in sources]
    command += ['-Wl,--wrap=ioctl', '-Wl,--wrap=poll', *flags, '-o', str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    if result.returncode or 'Sanitizer' in result.stderr or 'runtime error:' in result.stderr:
        raise RuntimeError(result.stdout + result.stderr)
    print(result.stdout.strip())
    print('full_driver_sha256', sha((build / 'src/v4l2_request_drv_video.so').read_bytes()))
    print('public_api_test_sha256', sha(binary.read_bytes()))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tree = fetch_tree(Path(tmp) / 'src')
        full_driver_build(tree)
        decode = (tree / 'src/decode.c').read_text()
        context = (tree / 'src/context.c').read_text()
        pause = '	if (ctx->observer_paused || ctx->observer_retain)\n		return VA_STATUS_ERROR_OPERATION_FAILED;\n'
        enabled = '	if (!ctx || !ctx->observer_enabled)\n		return VA_STATUS_ERROR_UNIMPLEMENTED;\n	if (!out)\n'
        wait = '	if (ctx->streaming && ctx->completed < ctx->submitted)\n		ret = wait_completed_locked(ctx, ctx->submitted, deadline_ns);\n'
        deadline = '\tif (observer_lock_until(&ctx->mutex, deadline_ns) < 0)\n'
        variants = {
            'actual': (decode, context),
            'pause-before-bind': (replace_once(decode, pause, ''), context),
            'default-off': (replace_once(decode, enabled, '	if (!ctx)\n		return VA_STATUS_ERROR_UNIMPLEMENTED;\n	if (!out)\n'), context),
            'drain': (replace_once(decode, wait, '	(void)ret;\n'), context),
            'deadline': (replace_once(decode, deadline, '\tdeadline_ns = v4l2r_now_ns() + 1000000;\n' + deadline), context),
        }
        assertions = {
            'pause-before-bind': 'ctx.observer_bind_count == binds',
            'default-off': 'v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_ERROR_UNIMPLEMENTED',
            'drain': 'rec.submitted == 1 && rec.completed == 1 && rec.queued_capture == 0',
            'deadline': 'v4l2r_observer_begin(&ctx, 1, &rec) == VA_STATUS_ERROR_OPERATION_FAILED',
        }
        for name, (decode_text, context_text) in variants.items():
            result = compile_and_run(tree, decode_text, context_text)
            diagnostic = result.stdout + result.stderr
            if name == 'actual':
                if (result.returncode or 'Sanitizer' in diagnostic or
                        'runtime error:' in diagnostic or
                        'PASS actual decode.c/context.c observer' not in result.stdout):
                    raise RuntimeError(diagnostic)
            elif (result.returncode != 1 or assertions[name] not in result.stderr or
                  'Sanitizer' in diagnostic or 'runtime error:' in diagnostic):
                raise RuntimeError('mutation not distinguished: ' + name + '\n' + diagnostic)
        destroy = (
            '	if (!ctx)\n'
            '		return VA_STATUS_ERROR_INVALID_CONTEXT;\n'
            '	if (ctx->observer_retain)\n'
            '		return VA_STATUS_ERROR_OPERATION_FAILED;\n'
        )
        mutated_ctx = replace_once(context, destroy,
            '	if (!ctx)\n		return VA_STATUS_ERROR_INVALID_CONTEXT;\n')
        result = compile_and_run(tree, decode, mutated_ctx)
        if (result.returncode != 1 or
                'v4l2r_DestroyContext(&va, cid) == VA_STATUS_ERROR_OPERATION_FAILED' not in result.stderr or
                'Sanitizer' in result.stderr or 'runtime error:' in result.stderr):
            raise RuntimeError('destroy-retain mutation not distinguished\n' + result.stdout + result.stderr)
        print('PASS: actual patched decode.c/context.c observer with fake V4L2; five semantic mutations fail')
        print('driver', PIN, 'patch', sha((HERE / 'driver-observer.patch').read_bytes()))


if __name__ == '__main__':
    main()
