#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual FFmpeg CLI report-path ownership under ASan/UBSan; no device.

Builds the pinned, patched FFmpeg and drives its real CLI, demuxer, decoder
and teardown with software HEVC decoding only.  The experimental observer
report option is the subject: the option string parsed on the command line
must be owned by the demuxer stream, because `open_files` frees the parsed
option immediately after each input is opened, long before `dec_open` runs.

Scope: this covers the option -> demuxer -> `dec_open` lifetime, where the
defect was, and the cleanup of both owned copies.  It cannot cover the
decoder worker's publication call: with the observer armed the patch refuses
non-VAAPI frames by design, so the `armed` case ends in that refusal instead
of publishing.  The exact-linked `va-callsite` fixture covers real
publication against the attempt-4 libraries.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'va-callsite'))
spec = importlib.util.spec_from_file_location('report_path_sources', HERE.parent / 'va-callsite/tests.py')
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)
SAN = '-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer'
ENV = os.environ | {'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                    'UBSAN_OPTIONS': 'halt_on_error=1'}
FAULTS = ('Sanitizer', 'runtime error:', 'detected memory leaks',
          'ASSERT: report-path-owned-through-worker')
REACHED = 'PASS actual CLI report path reached worker after option teardown'
# One synthetic black 64x64 frame, generated entirely in software:
# ffmpeg -f lavfi -i color=c=black:s=64x64:r=1 -frames:v 1 -c:v libx265
#   -x265-params pools=none:frame-threads=1:info=0:log-level=error -f hevc black.hevc
# FFmpeg 9.0.1 / libx265 on the development host; no media or corpus dependency.
BLACK = bytes.fromhex('''
0000000140010c01ffff01600000030090000003000003001e9598090000
000142010101600000030090000003000003001ea020810596566924caf0
16808000000300800000030084000000014401c172b422400000012801af
1380e668e3fffd17cfc7f6cf
''')


def command(argv, cwd=None):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, env=ENV,
                            capture_output=True, text=True, timeout=1200)
    if result.returncode:
        raise RuntimeError(' '.join(map(str, argv)) + '\n' + (result.stdout + result.stderr)[-18000:])
    return result.stdout


def test(root, archive, mutations):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    tree = sources.fetch_tree(root, archive)
    build = root / 'build'
    build.mkdir()
    wrapper = root / 'report-path-fixture.o'
    command(['cc', '-std=gnu11', '-g', *SAN.split(), '-c',
             HERE / 'report-path-fixture.c', '-o', wrapper])
    command([tree / 'configure', '--disable-everything', '--disable-autodetect',
             '--disable-doc', '--disable-network', '--disable-x86asm',
             '--enable-ffmpeg', '--enable-vaapi', '--enable-libdrm', '--enable-pthreads',
             '--enable-decoder=hevc', '--enable-parser=hevc', '--enable-hwaccel=hevc_vaapi',
             '--enable-demuxer=hevc', '--enable-protocol=file', '--enable-muxer=null',
             '--enable-encoder=wrapped_avframe', '--enable-filter=null',
             '--disable-stripping', '--enable-debug=3', '--extra-cflags=' + SAN,
             '--extra-ldflags=' + SAN], build)
    link = 'EXTRALIBS-ffmpeg=' + str(wrapper) + ' -Wl,--wrap=ff_vaapi_decode_observer_write_report,--wrap=av_strdup'
    def rebuild():
        command(['make', '-j4', 'ffmpeg', link], build)
    rebuild()
    clip = root / 'black.hevc'
    clip.write_bytes(BLACK)
    report = root / 'report with spaces.json'
    prefix = [build / 'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'verbose',
              '-hwaccel', 'none', '-threads:v:0', '1']
    armed = ['-va_observer_outputs:v:0', '0', '-va_observer_copy:v:0', '0',
             '-va_observer_report:v:0', report]

    def execute(case, options=armed, extra=(), oom=None):
        argv = [*prefix, *options, '-i', clip, '-map', '0:v:0', *extra, '-f', 'null', '-']
        env = ENV | {'OMARCHY_TEST_REPORT_PATH': str(report)}
        if oom is not None:
            env['OMARCHY_TEST_REPORT_OOM'] = str(oom)
        result = subprocess.run(list(map(str, argv)), env=env, text=True,
                                capture_output=True, timeout=30)
        (root / (case + '.log')).write_text(result.stdout + result.stderr)
        return result

    def check(case, result, *, succeeds, copies, message=None):
        """Assert the exact exit disposition, owned copies and diagnostics."""
        diagnostic = result.stdout + result.stderr
        for fault in FAULTS:
            if fault in diagnostic:
                raise RuntimeError(case + ': unexpected ' + fault + '\n' + diagnostic)
        if succeeds != (result.returncode == 0):
            raise RuntimeError(case + ': unexpected exit %d\n' % result.returncode + diagnostic)
        observed = re.findall(r'^REPORT-PATH-COPY (\d+) (\S+)$', diagnostic, re.M)
        if observed != copies:
            raise RuntimeError(case + ': owned copies %r, expected %r\n' % (observed, copies) + diagnostic)
        if message and message not in diagnostic:
            raise RuntimeError(case + ': missing ' + message + '\n' + diagnostic)
        if REACHED in diagnostic:
            raise RuntimeError(case + ': software decoding must not reach the report worker')
        if report.exists():
            raise RuntimeError(case + ': a real observer report was published')
        print('PASS actual CLI ' + case, flush=True)

    def owned(count, last='ok'):
        return [(str(n + 1), 'ok' if n + 1 < count else last) for n in range(count)]

    # The option is parsed, owned by the demuxer stream, and duplicated again by
    # the decoder; the decoder then refuses software frames, which is the
    # documented reason the worker is unreachable without a device.
    check('armed', execute('armed'), succeeds=False, copies=owned(3),
          message='Function not implemented')
    check('default-off', execute('default-off', options=[]),
          succeeds=True, copies=[])
    # No decoder is opened for a stream copy, so only ist_free can release the
    # demuxer's copy.
    check('unused-streamcopy', execute('unused-streamcopy', extra=['-c:v', 'copy']),
          succeeds=True, copies=owned(2))
    check('unpaired', execute('unpaired', options=['-va_observer_report:v:0', report]),
          succeeds=False, copies=owned(2), message='must be set together')
    for allocation, site in ((2, 'ist_add'), (3, 'dec_open')):
        check('oom-' + str(allocation), execute('oom-' + str(allocation), oom=allocation),
              succeeds=False, copies=owned(allocation, 'injected-failure'),
              message='Cannot allocate memory')
        print('PASS ' + site + ' allocation failure unwinds cleanly', flush=True)

    if mutations:
        path = tree / 'fftools/ffmpeg_demux.c'
        original = path.read_text()
        cases = [
            ('borrowed-path', 'ds->dec_opts.va_observer_report = av_strdup(va_observer_report);',
             'ds->dec_opts.va_observer_report = (char *)va_observer_report;',
             'heap-use-after-free', ('armed', {})),
            ('missing-cleanup', '    av_freep(&ds->dec_opts.va_observer_report);\n', '',
             'detected memory leaks', ('unused-streamcopy', {'extra': ['-c:v', 'copy']})),
        ]
        for name, old, new, expected, (case, kwargs) in cases:
            if original.count(old) != 1:
                raise RuntimeError('mutation extent: ' + name)
            try:
                path.write_text(original.replace(old, new, 1))
                rebuild()
                result = execute('mutant-' + name, **kwargs)
                diagnostic = result.stdout + result.stderr
                if result.returncode == 0 or expected not in diagnostic:
                    raise RuntimeError('mutation did not trigger its intended sanitizer: '
                                       + name + '\n' + diagnostic)
                print('PASS mutation ' + name + ': ' + expected, flush=True)
            finally:
                path.write_text(original)
        rebuild()
        check('armed', execute('armed'), succeeds=False, copies=owned(3),
              message='Function not implemented')
    print('PASS CLI fixture uses software decoding and a test-only report sink; '
          'no hardware result claimed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--keep', type=Path)
    parser.add_argument('--no-mutations', action='store_true')
    args = parser.parse_args()
    if args.keep:
        args.keep.mkdir(mode=0o700, parents=True, exist_ok=False)
        test(args.keep.resolve(), args.archive, not args.no_mutations)
    else:
        with tempfile.TemporaryDirectory(prefix='hevc-report-path-') as directory:
            test(Path(directory), args.archive, not args.no_mutations)
