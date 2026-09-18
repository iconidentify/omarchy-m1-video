#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Full configured driver + public API, pinned syscall model, no device access."""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import re
import signal
import subprocess
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
PIN = 'c77e7b566f7baf9c7a2aad797e62c9aa578d9687'
ARCHIVE_SHA = 'a82f316c0468d3a5490bcfc33c8a876eab0e2b55ec1416b88f7f920535fc5bf4'
CASES = ('lifecycle', 'readers', 'export', 'derive', 'upload', 'trace-join',
         'contention', 'cancellation', 'partial', 'contexts', 'failed-queue',
         'failed-decode', 'timeout', 'eintr', 'expired', 'conversion',
         'import', 'vpp', 'partial-queue', 'foreign-display', 'owner-reuse')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError(' '.join(map(str, command)) + '\n' + result.stdout + result.stderr)
    return result.stdout


def fetch_tree(root, archive_path):
    archive = (archive_path.read_bytes() if archive_path else urllib.request.urlopen(
        f'https://codeload.github.com/iconidentify/libva-v4l2_request/tar.gz/{PIN}', timeout=60).read())
    if sha(archive) != ARCHIVE_SHA:
        raise ValueError('driver archive identity mismatch')
    path = root / 'source.tar.gz'
    path.write_bytes(archive)
    with tarfile.open(path) as stream:
        stream.extractall(root, filter='data')
    tree = root / ('libva-v4l2_request-' + PIN)
    run(['patch', '-p1', '--fuzz=0', '-i', str(HERE / 'driver-observer.patch')], cwd=tree)
    print('driver', PIN, 'archive_sha256', sha(archive), flush=True)
    return tree


def build_test(tree, sanitizer, name, changes=None):
    # Compile every original driver source, with its Meson-generated config.h.
    sources = re.findall(r"'([^']+\.c)'", (tree / 'src/meson.build').read_text())
    wraps = re.findall(r"'-Wl,--wrap=([^']+)'",
                       (tree / 'tests/meson.build').read_text().split('dimensions =')[0])
    flags = run(['pkg-config', '--cflags', '--libs', 'libva', 'libdrm']).split()
    directory = tree / 'build' / name
    directory.mkdir()
    inputs = []
    for source in sources:
        path = tree / 'src' / source
        if changes and source in changes:
            path = directory / source
            path.write_text(changes[source])
        inputs.append(str(path))
    binary = directory / 'observer'
    run(['cc', '-std=gnu11', '-g', '-O1', '-fno-omit-frame-pointer',
         '-fsanitize=' + sanitizer, '-fno-sanitize-recover=all', '-UNDEBUG', '-pthread',
         '-I' + str(tree / 'build'), '-I' + str(tree / 'src'), '-I' + str(tree / 'tests'),
         str(HERE / 'public-api-test.c'), *inputs,
         *['-Wl,--wrap=' + wrap for wrap in wraps], *flags, '-o', str(binary)])
    print(name, 'binary_sha256', sha(binary.read_bytes()), flush=True)
    return binary


def execute(binary, case):
    env = os.environ.copy()
    env['ASAN_OPTIONS'] = 'detect_leaks=1:halt_on_error=1'
    env['TSAN_OPTIONS'] = 'halt_on_error=1:exitcode=66'
    return subprocess.run([str(binary), case], capture_output=True, text=True, timeout=20, env=env)


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('mutation drift: ' + old)
    return text.replace(old, new)


def mutations(tree):
    observer = (tree / 'src/observer.c').read_text()
    api = (tree / 'src/api.c').read_text()
    image = (tree / 'src/image.c').read_text()
    # The expected assertion must identify the semantic violation. Compiler
    # failures, timeouts and sanitizer findings are NOT mutation detections.
    variants = [
        ('public-gate', 'lifecycle', 'api.c', api,
         'drv->observer_active ? VA_STATUS_ERROR_OPERATION_FAILED :',
         'false ? VA_STATUS_ERROR_OPERATION_FAILED :',
         'table.vaBeginPicture(&va, cid, sid) == VA_STATUS_ERROR_OPERATION_FAILED'),
        ('retain', 'lifecycle', 'observer.c', observer,
         '\tdrv->observer_active = ctx;', '\t/* mutation: omit pin */',
         'v4l2r_observer_close(&va, &session) != VA_STATUS_SUCCESS'),
        ('release', 'lifecycle', 'observer.c', observer,
         '\t\t\tdrv->observer_active = NULL;', '\t\t\t/* mutation: leak pin */',
         'v4l2r_observer_begin(&va, &session, &target, 0, &receipt) == VA_STATUS_SUCCESS'),
        ('writer', 'lifecycle', 'decode.c', (tree / 'src/decode.c').read_text(),
         'ctx->captures[target->capture_index].observer_writer = ctx->submitted;',
         'ctx->captures[target->capture_index].observer_writer = 1;',
         'v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS'),
        ('drain', 'readers', 'observer.c', observer,
         'v4l2r_observer_drain_locked(ctx, deadline) < 0', 'false',
         'v4l2r_observer_begin(&va, &session, &target, 0, &receipt) == VA_STATUS_SUCCESS'),
        ('deadline', 'expired', 'observer.c', observer,
         '\tif (!deadline)\n', '\tif (true)\n',
         'v4l2r_observer_begin(&va, &session, &target, 1, &receipt) != VA_STATUS_SUCCESS'),
        ('allocation-alias', 'export', 'observer.c', observer,
         'cap->observer_aliased || ', '',
         'v4l2r_observer_select(&va, &session, sid, &target) != VA_STATUS_SUCCESS'),
        ('upload-writer', 'upload', 'image.c', image,
         '\t\tcap->observer_writer = cap->observer_completed_writer = 0;', '\t\t(void)cap;',
         'v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS'),
        ('owner', 'lifecycle', 'observer.c', observer,
         '!owner_generation || ctx->observer_owner_generation != owner_generation ||\n'
         '\t    !pthread_equal(ctx->observer_owner, pthread_self())', 'false',
         'v4l2r_observer_end(&va, &session, receipt.lease) != VA_STATUS_SUCCESS'),
    ]
    for name, case, source, text, old, new, assertion in variants:
        binary = build_test(tree, 'address,undefined', 'mutation-' + name,
                            {source: replace_once(text, old, new)})
        result = execute(binary, case)
        diagnostic = result.stdout + result.stderr
        if (result.returncode != -signal.SIGABRT or assertion not in result.stderr or
                'Sanitizer' in diagnostic or 'runtime error:' in diagnostic):
            raise RuntimeError('mutation not distinguished: ' + name + '\n' + diagnostic)
        print('PASS semantic mutation', name, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, help='optional cached archive; exact SHA is still required')
    parser.add_argument('--keep', type=Path, help='retain a fresh build/evidence directory')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = args.keep or Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        if list(root.iterdir()):
            raise ValueError('build/evidence directory must be empty')
        tree = fetch_tree(root, args.archive)
        run(['meson', 'setup', str(tree / 'build'), str(tree),
             '--buildtype=debug', '-Db_sanitize=address,undefined'])
        run(['meson', 'compile', '-C', str(tree / 'build'), '-j', '4'])
        print('full_driver_sha256', sha((tree / 'build/src/v4l2_request_drv_video.so').read_bytes()), flush=True)
        (root / 'regressions.log').write_text(run(
            ['meson', 'test', '-C', str(tree / 'build'), '--no-rebuild', '--print-errorlogs']))
        print('PASS existing driver Meson regressions', flush=True)
        for sanitizer in ('address,undefined', 'thread'):
            binary = build_test(tree, sanitizer, sanitizer.replace(',', '-'))
            for case in CASES:
                result = execute(binary, case)
                diagnostic = result.stdout + result.stderr
                if (result.returncode or 'Sanitizer' in diagnostic or 'runtime error:' in diagnostic or
                        'PASS actual driver observer ' + case not in result.stdout):
                    raise RuntimeError(sanitizer + ' ' + case + '\n' + diagnostic)
                print(result.stdout.strip(), sanitizer, flush=True)
        mutations(tree)
        print('patch_sha256', sha((HERE / 'driver-observer.patch').read_bytes()), flush=True)


if __name__ == '__main__':
    main()
