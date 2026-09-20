#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Complete pinned clients + private copies, synthetic syscalls only; never /dev."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
BASE = Path('subprojects/gst-plugins-bad/sys/v4l2codecs')
MODES = '''copy padded disabled missing-manifest bad-kernel bad-vb2 bad-avd bad-client
builtin untrusted-owner untrusted-directory writable-manifest wrong-device changed-proof
wrong-cap-driver cap-driver-prefix cap-driver-empty
stale foreign-run foreign-lease overflow bad-planes bad-extent no-retention mmap-failure munmap-failure slow-copy expired'''.split()
ENV = os.environ | {'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                    'UBSAN_OPTIONS': 'halt_on_error=1', 'TSAN_OPTIONS': 'halt_on_error=1',
                    'GST_PLUGIN_SYSTEM_PATH_1_0': '', 'GST_PLUGIN_PATH_1_0': ''}
WRAPS = ('open', 'open64', '__open_2', '__open64_2', 'close', 'ioctl', 'mmap', 'mmap64', 'munmap', 'clock_gettime')
EXTRA = ('fstat', 'fstat64', 'lstat', 'lstat64', 'readlink', '__readlink_chk')


def run(command, **kwargs):
    result = subprocess.run(list(map(str, command)), env=ENV, text=True, capture_output=True,
                            timeout=1200, **kwargs)
    if result.returncode:
        raise RuntimeError(' '.join(map(str, command)) + '\n' + (result.stdout + result.stderr)[-14000:])
    return result.stdout


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('fixture source drift: ' + old)
    return text.replace(old, new)


def rename_wrappers(text):
    for name in WRAPS:
        text = text.replace('__wrap_' + name + '(', 'base_' + name + '(')
        text = text.replace('__wrap_' + name + ' (', 'base_' + name + ' (')
    return text


def sync(root, client):
    directory = root / ('src' if client == 'va' else BASE)
    files = ['content.h', 'runtime.h', client + '-content.h', client + '-content.inc', 'model-runtime.inc']
    if client == 'gst':
        files += ['gst-allocation-content.inc']
    for name in files:
        shutil.copyfile(HERE / name, directory / name)


def fixture(root, client):
    directory = root / ('src' if client == 'va' else BASE)
    original = (PARENT / (client + '-adapter') / 'public-api-test.c').read_text()
    if client == 'va':
        source = rename_wrappers((root / 'tests/failure-cleanup.c').read_text())
        (directory / 'content-failure-cleanup.c').write_text(source)
        original = replace(original, '#include "failure-cleanup.c"', '#include "content-failure-cleanup.c"')
        original = replace(original, 'int main(int argc, char **argv)', 'int native_fixture_main(int argc, char **argv)')
    else:
        original = rename_wrappers(original)
        original = replace(original, 'int main(int argc,char **argv)', 'int native_fixture_main(int argc,char **argv)')
        original = replace(original, 'ftruncate(original, 262144)', 'ftruncate(original, model_length)')
        original = replace(original, 'fmt->fmt.pix_mp.width=64; fmt->fmt.pix_mp.height=64;',
                           'fmt->fmt.pix_mp.width=448; fmt->fmt.pix_mp.height=240;')
        original = replace(original, 'bytesperline=64;', 'bytesperline=448;')
        original = original.replace('sizeimage=6144;', 'sizeimage=model_length;')
        original = original.replace('b->m.planes[0].length=6144;', 'b->m.planes[0].length=model_length;')
        original = replace(original, 'GST_VIDEO_FORMAT_NV12,64,64)', 'GST_VIDEO_FORMAT_NV12,448,240)')
    generated = '#define _GNU_SOURCE\n#include "model-runtime.inc"\n' + original + '\n' + (HERE / (client + '-model.inc')).read_text()
    (directory / 'content-api-test.c').write_text(generated)


def build_va(root, sanitizer, label):
    sources = re.findall(r"'([^']+\.c)'", (root / 'src/meson.build').read_text())
    wraps = re.findall(r"'-Wl,--wrap=([^']+)'", (root / 'tests/meson.build').read_text().split('dimensions =')[0])
    flags = run(['pkg-config', '--cflags', '--libs', 'libva', 'libdrm']).split()
    binary = root / 'build' / ('content-' + label)
    run(['cc', '-std=gnu11', '-g', '-O1', '-fno-omit-frame-pointer',
         '-fsanitize=' + sanitizer, '-fno-sanitize-recover=all', '-UNDEBUG', '-pthread',
         '-I' + str(root / 'build'), '-I' + str(root / 'src'), '-I' + str(root / 'tests'),
         root / 'src/content-api-test.c', *[root / 'src' / s for s in sources],
         *['-Wl,--wrap=' + w for w in dict.fromkeys(wraps + list(EXTRA))], *flags, '-o', binary])
    return binary


def build_gst(build):
    run(['meson', 'compile', '-C', build, '-j', '4', 'gstv4l2codecs', 'content-api', 'observer-api'])
    return build / BASE / 'content-api'


def positive(binary, client, sanitizer):
    modes = MODES + (['wrong-codec', 'noncoherent'] if client == 'va' else [])
    for mode in modes:
        try:
            output = run([binary, mode])
        except RuntimeError:
            symbols = run(['nm', '-u', binary])
            print('unresolved syscall symbols: ' + '\n'.join(line for line in symbols.splitlines()
                  if 'stat' in line or 'readlink' in line), flush=True)
            raise
        assert 'PASS actual ' in output, output
        print(sanitizer, output.strip(), flush=True)



def mutations(root, client, build=None):
    directory = root / ('src' if client == 'va' else BASE)
    cases = [
        ('actual-cap-driver', 'runtime.h', 'memcmp(cap.driver, "avd\\0", sizeof("avd"))',
         'memcmp(cap.driver, "apple-avd\\0", sizeof("apple-avd"))', 'copy', "Assertion `ok' failed"),
        ('exact-cap-driver', 'runtime.h', 'memcmp(cap.driver, "avd\\0", sizeof("avd"))',
         '0', 'wrong-cap-driver', '!ok && !pool.slot[0].valid'),
        ('range', 'content.h', '(const unsigned char *)map + HEVC_CONTENT_COMP_START,',
         '(const unsigned char *)map + HEVC_CONTENT_COMP_START + 1,', 'copy', 'pool->slot[index].bytes[n]'),
        ('kernel-build', 'runtime.h', 'if (!hevc_content_build_id("/sys/kernel/notes", values[2])) return false;',
         '/* mutation: omit kernel attestation */', 'bad-kernel', '!ok && !pool.slot[0].valid'),
        ('copy-deadline', 'content.h', 'after - before <= HEVC_CONTENT_COPY_NS',
         'true', 'slow-copy', '!ok && !pool.slot[0].valid'),
    ]
    if client == 'va':
        cases += [
            ('allocation', 'va-content.inc', 'actual.allocation_generation != receipt->target.allocation_generation ||',
             '', 'stale', '!ok && !pool.slot[0].valid'),
            ('retained-unmap', 'observer.c', 'if (ctx->observer_content_map && munmap(',
             'if (false && ctx->observer_content_map && munmap(', 'munmap-failure', 'v4l2r_observer_end(&va,&session,receipt.lease)!=VA_STATUS_SUCCESS'),
            ('context-budget', 'va-content.inc', 'ctx->observer_content_count >= HEVC_CONTENT_SLOTS ||',
             '', 'copy', '!v4l2r_content_snapshot(&va,&receipt,&pool,true)'),
        ]
    else:
        cases += [
            ('allocation', 'gst-content.inc', 'current.target.allocation != receipt->target.allocation ||',
             '', 'stale', '!ok && !pool.slot[0].valid'),
            ('retained-unmap', 'gstv4l2decoder.c', 'if (self->observer_content_map && munmap(',
             'if (FALSE && self->observer_content_map && munmap(', 'munmap-failure', '!gst_hevc_observer_end(decoder,&session,receipt.lease)'),
            ('context-budget', 'gst-content.inc', 'self->observer_content_count >= HEVC_CONTENT_SLOTS ||',
             '', 'copy', '!gst_hevc_content_snapshot(decoder,&receipt,&pool,TRUE)'),
        ]
    for label, name, old, new, mode, assertion in cases:
        path = directory / name
        original = path.read_text()
        try:
            path.write_text(replace(original, old, new))
            # Gst has a second independent allocation check at its private map boundary.
            companion = directory / 'gst-allocation-content.inc'
            allocator = companion.read_text() if client == 'gst' and label == 'allocation' else None
            if allocator is not None:
                companion.write_text(replace(allocator, 'buf->observer_generation != receipt->target.allocation ||', ''))
            binary = build_va(root, 'address,undefined', 'mutation') if client == 'va' else build_gst(build)
            result = subprocess.run([str(binary), mode], env=ENV, text=True, capture_output=True, timeout=20)
            output = result.stdout + result.stderr
            if (result.returncode != -signal.SIGABRT or assertion not in output or
                    'Sanitizer' in output or 'runtime error:' in output):
                raise RuntimeError('semantic mutation not distinguished: ' + label + '\n' + output)
            print('PASS semantic integration mutation', client, label, flush=True)
        finally:
            path.write_text(original)
            if client == 'gst' and label == 'allocation':
                companion.write_text(allocator)
    if client == 'gst':
        build_gst(build)

def prepare_gst_fixture(root):
    path = root / BASE / 'meson.build'
    text = path.read_text()
    if "executable('content-api'" not in text:
        addition = (PARENT / 'gst-adapter/test-meson.build').read_text()
        addition = addition[:addition.index('unaligned_io_test =')]
        addition = addition.replace('observer_sources', 'content_sources').replace('observer_test', 'content_test')
        addition = addition.replace("'observer-api', 'observer-api-test.c'", "'content-api', 'content-api-test.c'")
        addition = addition.replace("'-Wl,--wrap=clock_gettime'", "'-Wl,--wrap=clock_gettime', " + ', '.join("'-Wl,--wrap=" + x + "'" for x in ['mmap', 'mmap64', 'munmap', *EXTRA]))
        path.write_text(text + '\n' + addition)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', choices=['va', 'gst'], required=True)
    parser.add_argument('--keep', type=Path, required=True, help='new empty evidence directory')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--native-file', type=Path)
    args = parser.parse_args()
    destination = args.keep.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        parser.error('--keep must be empty')
    runtime_test = destination / 'runtime-test'
    run(['cc', '-std=gnu11', '-g', '-O1', '-UNDEBUG', '-Wl,--build-id',
         '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
         HERE / 'runtime-test.c', '-ldl', '-o', runtime_test])
    print(run([runtime_test]).strip(), flush=True)
    if args.client == 'va':
        adapter = module('va_adapter_tests', PARENT / 'va-adapter/tests.py')
        root = adapter.fetch_tree(destination, args.archive)
        run(['patch', '-p1', '--fuzz=0', '-i', HERE / 'va-integration.patch'], cwd=root)
        run(['patch', '-p1', '--fuzz=0', '-i', PARENT / 'va-callsite' / 'driver-client-abi.patch'], cwd=root)
        sync(root, 'va'); fixture(root, 'va')
        run(['meson', 'setup', root / 'build', root, '--buildtype=debug', '-Db_sanitize=address,undefined'])
        run(['meson', 'compile', '-C', root / 'build', '-j', '4'])
        (destination / 'regressions.log').write_text(run(['meson', 'test', '-C', root / 'build', '--no-rebuild', '--print-errorlogs']))
        for sanitizer in ['address,undefined', 'thread']:
            binary = build_va(root, sanitizer, sanitizer.replace(',', '-'))
            positive(binary, 'va', sanitizer)
            native = adapter.build_test(root, sanitizer, 'native-' + sanitizer.replace(',', '-'))
            for mode in adapter.CASES:
                result = adapter.execute(native, mode)
                assert result.returncode == 0, result.stdout + result.stderr
            print('PASS original VA adapter modes', sanitizer, flush=True)
        mutations(root, 'va')
    else:
        sys.path.insert(0, str(PARENT / 'gst-adapter'))
        adapter = module('gst_adapter_tests', PARENT / 'gst-adapter/tests.py')
        root = adapter.source.fetch(destination, args.archive)
        for patch in ['unaligned-io.patch', 'gstv4l2decoder-observer.patch']:
            run(['patch', '--fuzz=0', '-p1', '-i', PARENT / 'gst-adapter' / patch], cwd=root)
        for name in ['public-api-test.c', 'unaligned-io-test.c']:
            shutil.copyfile(PARENT / 'gst-adapter' / name, root / BASE / ('observer-api-test.c' if name == 'public-api-test.c' else name))
        with (root / BASE / 'meson.build').open('a') as stream:
            stream.write('\n' + (PARENT / 'gst-adapter/test-meson.build').read_text())
        run(['patch', '--fuzz=0', '-p1', '-i', HERE / 'gst-integration.patch'], cwd=root)
        sync(root, 'gst'); fixture(root, 'gst'); prepare_gst_fixture(root)
        for sanitizer, label in [('address,undefined', 'asan-ubsan'), ('thread', 'tsan')]:
            build = destination / label
            adapter.configure(root, build, sanitizer, args.native_file)
            binary = build_gst(build)
            adapter.pinned_linkage(build, binary)
            adapter.pinned_linkage(build, build / BASE / "libgstv4l2codecs.so")
            positive(binary, 'gst', sanitizer)
            adapter.positive(build, sanitizer)
            if label == 'asan-ubsan':
                mutations(root, 'gst', build)
    print('PASS integrated retained allocation copies; synthetic evidence only', flush=True)


if __name__ == '__main__':
    main()
