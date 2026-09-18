#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Complete pinned plugin, actual client APIs, fake V4L2; no installed changes."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import source

HERE = Path(__file__).resolve().parent
MODES = '''lifecycle readers contention cancellation timeout eintr decode-error
published mapped raw-fd expired retention recycling unqueued default-off queue-error
partial trace-join deadline-poll late-timeout gates wrong-index export output-publication
identities unsupported sticky-publication retirement shared-memory'''.split()
ORIGINAL = ['libs_h265parser', 'libs_h265bitwriter', 'elements_h265parse']
ENV = os.environ | {'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                    'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1',
                    'TSAN_OPTIONS': 'halt_on_error=1',
                    'GST_PLUGIN_SYSTEM_PATH_1_0': '', 'GST_PLUGIN_PATH_1_0': '',
                    'GST_STATE_IGNORE_ELEMENTS': '', 'CK_DEFAULT_TIMEOUT': '20'}


def run(command, *, cwd=None, env=ENV, timeout=1200, log=None):
    result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                            text=True, capture_output=True, timeout=timeout)
    if log:
        log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'{command} exited {result.returncode}:\n' +
                           (result.stdout + result.stderr)[-10000:])
    return result


def configure(root, build, sanitizer, native):
    command = ['meson', 'setup', build, root, '-Dauto_features=disabled',
               '-Dbase=enabled', '-Dbad=enabled', '-Dgood=disabled', '-Dugly=disabled',
               '-Dtests=disabled', '-Dgstreamer:check=enabled', '-Dgstreamer:tests=enabled',
               '-Dgst-plugins-bad:tests=enabled', '-Dgst-plugins-bad:v4l2codecs=enabled',
               '-Dgst-plugins-bad:videoparsers=enabled', '-Dgst-plugins-base:app=enabled',
               '-Db_sanitize=' + sanitizer]
    if native:
        command += ['--native-file', native]
    run(command, log=build.parent / (build.name + '-configure.log'))


def compile_targets(build, *targets):
    run(['meson', 'compile', '-C', build, '-j', '4', *targets],
        log=build.parent / (build.name + '-compile.log'))


def api_path(build):
    return build / source.BASE / 'observer-api'


def positive(build, label):
    for mode in MODES:
        result = run([api_path(build), mode], timeout=20)
        assert f'PASS actual Gst observer {mode}' in result.stdout
        print(label + ': ' + result.stdout.strip(), flush=True)


def original_tests(build):
    # A separate plugin directory prevents real V4L2 device discovery. These
    # unchanged tests need only the parser, core elements and app plugin.
    plugins = build / 'software-plugins'
    plugins.mkdir()
    for name in ['libgstvideoparsersbad.so', 'libgstcoreelements.so', 'libgstapp.so']:
        (plugins / name).symlink_to(next(build.rglob(name)))
    env = ENV | {'GST_PLUGIN_PATH_1_0': str(plugins), 'GST_REGISTRY_FORK': 'no',
                 'GST_REGISTRY': str(plugins / 'registry.bin')}
    for name in ORIGINAL:
        result = run([build / 'subprojects/gst-plugins-bad/tests/check' / name],
                     env=env, timeout=180, log=build.parent / (name + '.log'))
        print('PASS original ' + name + '\n' + result.stdout.strip(), flush=True)


# Mutate real transitions, not a duplicate implementation. Every mutant must
# compile, then SIGABRT on its named semantic assertion before any sanitizer error.
DEC = 'gstv4l2decoder.c'
ALLOC = 'gstv4l2codecallocator.c'
MUTATIONS = [
 ('producer-gate', DEC, 'return self && (self->observer_lease || self->observer_ending);',
  'return self && self->observer_ending;', 'gates', '!gst_v4l2_decoder_flush(decoder)'),
 ('request-pin', DEC, 'GstV4l2Request *held = gst_v4l2_request_ref (request);',
  'GstV4l2Request *held = request;', 'retention', 'ioctls==before'),
 ('end-release', DEC, 'g_clear_pointer (&self->observer_request, gst_v4l2_request_unref);',
  'self->observer_request = NULL;', 'retention', 'ioctls==before+1'),
 ('failed-begin-release', DEC, 'release:\n  gst_v4l2_request_unref (held);',
  'release:\n  (void) held;', 'late-timeout', 'ioctls==before+1'),
 ('drain', DEC, 'while (gst_vec_deque_get_length (self->pending_requests)) {',
  'while (FALSE) {', 'readers', 'gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt)'),
 ('remaining-deadline', DEC, 'timeout = decoder->observer_deadline - now;',
  'timeout = GST_SECOND;', 'deadline-poll', 'last_poll_timeout>0 && last_poll_timeout<20*GST_MSECOND'),
 ('allocation-generation', ALLOC, 'buf->observer_generation = gst_hevc_observer_generation ();',
  'buf->observer_generation = 1;', 'recycling', 'allocations[j]!=target.allocation'),
 ('writer-generation', DEC, 'request->observer_writer = gst_hevc_observer_generation ();',
  'request->observer_writer = 1;', 'recycling', 'target.writer!=last_writer && target.request!=last_request'),
 ('session-owner', DEC, 'self->observer_owner == g_thread_self ();',
  'TRUE;', 'lifecycle', '!gst_hevc_observer_end(decoder,&session,receipt.lease)'),
 ('publication', ALLOC, '!buf || buf->observer_published || !buf->observer_writer',
  '!buf || !buf->observer_writer', 'mapped', '!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt)'),
 ('client-output', 'gstv4l2codech265dec.c', 'gst_hevc_observer_buffer_publish (frame->output_buffer);',
  '(void) frame;', 'output-publication', '!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt)'),
 ('capture-identity', DEC, 'capture_index != gst_v4l2_codec_buffer_get_index (pending_req->pic_buf)',
  'FALSE', 'wrong-index', '!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt)'),
]


def mutations(root, build):
    for label, name, before, after, mode, assertion in MUTATIONS:
        path = root / source.BASE / name
        original = path.read_text()
        if original.count(before) != 1:
            raise ValueError('mutation source drift: ' + label)
        try:
            path.write_text(original.replace(before, after))
            compile_targets(build, 'observer-api')
            result = subprocess.run([api_path(build), mode], env=ENV, text=True,
                                    capture_output=True, timeout=20)
            output = result.stdout + result.stderr
            if (result.returncode != -signal.SIGABRT or assertion not in output or
                    'Sanitizer' in output or 'runtime error:' in output):
                raise RuntimeError(f'mutation {label} wrong failure ({result.returncode}):\n{output}')
            print(f'PASS mutation {label}: SIGABRT at {assertion}', flush=True)
        finally:
            path.write_text(original)
    compile_targets(build, 'gstv4l2codecs', 'observer-api')


def validate(destination, archive, native):
    root = source.fetch(destination, archive)
    run(['patch', '--batch', '--fuzz=0', '-p1', '-i', HERE / 'gstv4l2decoder-observer.patch'], cwd=root)
    shutil.copyfile(HERE / 'public-api-test.c', root / source.BASE / 'observer-api-test.c')
    with (root / source.BASE / 'meson.build').open('a') as file:
        file.write('\n' + (HERE / 'test-meson.build').read_text())
    for label, sanitizer in [('asan-ubsan', 'address,undefined'), ('tsan', 'thread')]:
        build = destination / label
        configure(root, build, sanitizer, native)
        targets = ['gstv4l2codecs', 'observer-api', 'gst-tester-1.0']
        if label == 'asan-ubsan':
            targets += ORIGINAL + ['gstvideoparsersbad', 'gstcoreelements', 'gstapp']
        compile_targets(build, *targets)
        positive(build, label)
        if label == 'asan-ubsan':
            original_tests(build)
            mutations(root, build)
        for name in ['libgstv4l2codecs.so', 'observer-api']:
            artifact = build / source.BASE / name
            print(label, name, 'sha256', source.digest(artifact), flush=True)
    print('PASS complete configured plugin, 29 API modes per sanitizer, original HEVC tests and 12 semantic mutations', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='verified cached full source archive')
    parser.add_argument('--keep', type=Path, help='new or empty directory for build products and logs')
    parser.add_argument('--native-file', type=Path, help='optional local Meson tool paths')
    args = parser.parse_args()
    archive = args.archive.resolve() if args.archive else None
    native = args.native_file.resolve() if args.native_file else None
    if args.keep:
        destination = args.keep.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            parser.error('--keep must name an empty directory')
        validate(destination, archive, native)
    else:
        with tempfile.TemporaryDirectory(prefix='gst-observer-') as directory:
            validate(Path(directory), archive, native)


if __name__ == '__main__':
    main()
