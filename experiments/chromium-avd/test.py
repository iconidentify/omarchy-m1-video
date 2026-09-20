#!/usr/bin/env python3
"""Offline C++ policy tests and pinned overlay checks; no device operations."""
import argparse
import base64
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from prepare_source import prepare, TARGETS, VERSION
from prepare_recipe import recipe
from source_cache import download, verified

HERE = Path(__file__).resolve().parent
COMMON = Path('content/common')


def run(command, **kwargs):
    return subprocess.run(command, check=True, timeout=120, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-cache', type=Path, required=True)
    args = parser.parse_args()
    cache = verified(args.source_cache.resolve())
    row = dict(path='synthetic', url='https://test.invalid/?format=TEXT',
               fallback_url='https://mirror.invalid/file',
               sha256=hashlib.sha256(b'expected').hexdigest())
    calls = []
    def timeout_then_mirror(url, timeout):
        calls.append(url)
        if url == row['url']:
            raise TimeoutError('synthetic timeout')
        return io.BytesIO(b'expected')
    assert download(row, timeout_then_mirror) == b'expected'
    assert calls == [row['url'], row['fallback_url']]
    calls.clear()
    def corrupt_response(url, timeout):
        calls.append(url)
        return io.BytesIO(base64.b64encode(b'corrupt'))
    try:
        download(row, corrupt_response)
    except ValueError:
        assert calls == [row['url']]
        print('PASS: transport fallback retains hash enforcement; corruption never falls back')
    else:
        raise AssertionError('Corrupt source accepted')
    with tempfile.TemporaryDirectory(prefix='chromium-avd-offline-') as temporary:
        work = Path(temporary)
        for relative in TARGETS:
            path = work / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache / relative, path)
        (work / 'chrome').mkdir()
        (work / 'chrome/VERSION').write_text(VERSION)
        target = work / TARGETS[0]
        original = target.read_bytes()
        target.write_bytes(original + b'\n')
        try:
            prepare(work, True)
        except ValueError:
            assert (work / TARGETS[1]).read_bytes() == (cache / TARGETS[1]).read_bytes()
            print('PASS: modified source refused before writes')
        else:
            raise AssertionError('Modified source was accepted')
        target.write_bytes(original)
        prepare(work)
        prepare(work, True)
        try:
            prepare(work, True)
        except ValueError:
            print('PASS: reapplication refuses modified source')
        else:
            raise AssertionError('Reapplication was not refused')
        package = work / 'PKGBUILD'
        package.write_text(recipe((cache / 'arch-PKGBUILD').read_bytes()))
        run(['bash', '-n', str(package)])
        try:
            recipe((cache / 'arch-PKGBUILD').read_bytes() + b'\n')
        except ValueError:
            print('PASS: recipe syntax and wrong-source refusal')
        else:
            raise AssertionError('Wrong recipe accepted')
        flags = [os.environ.get('CXX', 'c++'), '-std=c++20', '-O1', '-g',
                 '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                 '-fno-omit-frame-pointer', '-pthread',
                 '-I' + str(work), '-I' + str(HERE / 'tests/shims'), '-I' + str(cache)]
        selector = work / COMMON / 'apple_avd_gpu_permissions_linux.cc'
        tests = work / COMMON / 'apple_avd_gpu_permissions_linux_unittest.cc'
        broker = cache / 'sandbox/linux/syscall_broker/broker_file_permission.cc'
        binary = work / 'policy-tests'
        run(flags + [str(selector), str(tests), str(broker), '-lgtest_main', '-lgtest', '-o', str(binary)])
        run([str(binary)])
        # Each mutation must compile, execute the targeted case, and fail that
        # assertion. A compile error, signal, timeout or sanitizer issue is not a kill.
        mutations = [
            ('metadata-open', 'apple_avd_gpu_broker_linux.h',
             'BrokerPermission::StatOnlyWithIntermediateDirs(rule.path)',
             'BrokerPermission::ReadOnly(rule.path)', 'OnlyRequiredOperations'),
            ('uevent-write', 'apple_avd_gpu_broker_linux.h',
             'BrokerPermission::ReadOnly(rule.path)',
             'BrokerPermission::ReadWrite(rule.path)', 'OnlyRequiredOperations'),
            ('media-pair', 'apple_avd_gpu_permissions_linux.cc',
             'node->canonical != video.physical + "/" + name', 'false', 'MediaMustBelongToSameAvd'),
            ('camera-driver', 'apple_avd_gpu_permissions_linux.cc',
             '"/sys/bus/platform/drivers/avd"', '"/sys/bus/platform/drivers/uvcvideo"',
             'CameraCannotSubstituteForAvd'),
        ]
        for label, filename, before, after, case in mutations:
            path = work / COMMON / filename
            original = path.read_text()
            assert original.count(before) == 1, (label, 'ambiguous mutation')
            try:
                path.write_text(original.replace(before, after))
                run(flags + [str(selector), str(tests), str(broker), '-lgtest_main', '-lgtest', '-o', str(binary)])
                result = subprocess.run([str(binary), '--gtest_filter=AppleAvdPermissions.' + case],
                                        text=True, capture_output=True, timeout=30)
                assert (result.returncode == 1 and '[  FAILED  ] AppleAvdPermissions.' + case in result.stdout
                        and 'runtime error:' not in result.stderr and 'AddressSanitizer' not in result.stderr), (
                            label, result.returncode, result.stdout, result.stderr)
                print('PASS: targeted assertion detected mutation ' + label, flush=True)
            finally:
                path.write_text(original)
    print('PASS: pinned patch, 12 policy/native tests, four compiled negative mutations.')


if __name__ == '__main__':
    main()
