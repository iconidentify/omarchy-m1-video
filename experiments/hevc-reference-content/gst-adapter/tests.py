#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Patched gst_v4l2_request_queue with configured GStreamer headers. No device."""
from pathlib import Path
import subprocess
import tempfile
import source

HERE = Path(__file__).resolve().parent


def cflags():
    return subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'gstreamer-1.0', 'gstreamer-video-1.0'],
        text=True).split()


def compile_run(mode='success', mutate=None):
    texts = source.fetch()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'extracted-gst.inc').write_text(source.patched_bodies(texts, mutate=mutate))
        binary = tmp / 'harness'
        cmd = ['cc', '-std=c11', '-O0', '-g', '-fsanitize=address,undefined',
               '-Wall', '-Werror', '-Wno-unused-parameter', '-Wno-unused-variable',
               '-pthread',
               '-I', str(HERE), '-I', str(tmp)] + cflags() + [
                   str(HERE / 'harness.c'), str(HERE / 'gst-observer.c'), '-o', str(binary)]
        built = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if built.returncode:
            raise RuntimeError(built.stderr[-5000:])
        return subprocess.run([str(binary), mode], capture_output=True, text=True, timeout=10)


def expect(mode, substring, mutate=None):
    result = compile_run(mode=mode, mutate=mutate)
    if result.returncode != 0 or substring not in result.stdout:
        raise SystemExit('%s failed (rc=%s):\n%s%s' %
                         (mode, result.returncode, result.stdout, result.stderr))
    print(result.stdout.strip())


def expect_fail(mode, mutate, assertion):
    result = compile_run(mode=mode, mutate=mutate)
    if result.returncode == 0:
        raise SystemExit('mutation %s unexpectedly passed:\n%s' % (mutate, result.stdout))
    if assertion not in result.stderr and assertion not in result.stdout:
        raise SystemExit('mutation %s missing assertion %r (rc=%s):\n%s%s' %
                         (mutate, assertion, result.returncode, result.stdout, result.stderr))
    if 'ERROR: AddressSanitizer' in result.stderr or 'runtime error:' in result.stderr:
        raise SystemExit('mutation %s sanitizer crash counted as negative:\n%s' %
                         (mutate, result.stderr))
    print('PASS: mutation', mutate, 'failed as', assertion)


def write_patch():
    texts = source.fetch()
    original = texts[source.DEC]
    patched = source.patch_decoder(original)
    Path('/tmp/gst-orig.c').write_text(original)
    Path('/tmp/gst-patched.c').write_text(patched)
    diff = subprocess.run(
        ['diff', '-u', '--label', 'a/' + source.DEC, '--label', 'b/' + source.DEC,
         '/tmp/gst-orig.c', '/tmp/gst-patched.c'],
        capture_output=True, text=True)
    (HERE / 'gstv4l2decoder-observer.patch').write_text(diff.stdout)


def main():
    write_patch()
    expect('success', 'PASS: success pause/retain after successful queue')
    expect('fail-ioctl', 'PASS: failed ioctl does not mint a writer receipt')
    expect('reuse', 'PASS: reused request retires previous writer_job')
    expect('drain-timeout', 'PASS: begin does not invent completion on drain timeout')
    expect_fail('success', 'no-queue-hook', 'fail')
    expect_fail('success', 'no-record-hook', 'fail')
    expect_fail('success', 'no-free-hook', 'fail')
    print('PASS: gst observer correction')


if __name__ == '__main__':
    main()
