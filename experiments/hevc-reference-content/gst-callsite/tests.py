#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the complete pinned plugin and exercise its wired output vfunc offline."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
BASE = Path('subprojects/gst-plugins-bad/sys/v4l2codecs')
MODES = '''copy control padded disabled cancel-arm late-arm readers wrong-buffer
wrong-frame missing-manifest mmap-failure munmap-failure decode-error timeout
published flush changed-proof slow-copy lifecycle schedule-copy schedule-control
schedule-incomplete schedule-duplicate schedule-invalid schedule-frame-mismatch
schedule-munmap schedule-mid-failure schedule-budget schedule-reuse
schedule-mutable-plan schedule-cancel schedule-reader-reorder flush-armed'''.split()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


integration = module('content_integration', PARENT / 'integration/tests.py')
sys.path.insert(0, str(PARENT / 'gst-adapter'))
adapter = module('gst_adapter', PARENT / 'gst-adapter/tests.py')
run = integration.run


def configure_fixture(root):
    directory = root / BASE
    for name in ['gst-callsite.h', 'gst-callsite.inc', 'gst-callsite-native.inc']:
        shutil.copyfile(HERE / name, directory / name)
    source = (directory / 'content-api-test.c').read_text()
    source = integration.replace(source, 'int main(int argc,char **argv)',
                                  'int integration_fixture_main(int argc,char **argv)')
    # Enough distinct real allocations for eight selected + two unselected
    # outputs; the reuse case deliberately keeps the original four-slot pool.
    for direction in ['SINK', 'SRC']:
        source = integration.replace(source,
            'gst_v4l2_codec_allocator_new(decoder,GST_PAD_' + direction + ',4)',
            'gst_v4l2_codec_allocator_new(decoder,GST_PAD_' + direction +
            ',g_str_has_prefix(mode,"schedule-") && strcmp(mode,"schedule-reuse")?12:4)')
    source += '\n' + (HERE / 'callsite-model.inc').read_text()
    (directory / 'callsite-api-test.c').write_text(source)
    meson = directory / 'meson.build'
    text = meson.read_text()
    if 'callsite_sources =' in text:
        return
    addition = text[text.index('# Test-only fixture added'):]
    addition = addition[addition.index('content_sources ='):]
    addition = addition.replace('content_sources', 'callsite_sources').replace('content_test', 'callsite_test')
    addition = addition.replace("'content-api', 'content-api-test.c'", "'callsite-api', 'callsite-api-test.c'")
    addition = integration.replace(addition, "'-Wl,--wrap=clock_gettime'",
        "'-Wl,--wrap=clock_gettime', '-Wl,--wrap=gst_hevc_observer_buffer_publish', "
        "'-Wl,--wrap=gst_video_decoder_finish_frame', '-Wl,--wrap=gst_video_decoder_drop_frame'")
    meson.write_text(text + '\n' + addition)


def compile(build):
    run(['meson', 'compile', '-C', build, '-j', '4', 'gstv4l2codecs', 'callsite-api', 'content-api', 'observer-api'])
    return build / BASE / 'callsite-api'


def positive(binary, sanitizer):
    for mode in MODES:
        output = run([binary, mode])
        assert 'PASS actual Gst callsite ' + mode in output, output
        print(sanitizer, output.strip(), flush=True)


def mutations(root, build):
    cases = [
        ('wired-hook', 'gstv4l2codech265dec.c', 'if (!content_before_output (',
         'if (FALSE && !content_before_output (', 'copy', 'state->success && state->pool.slot[0].valid'),
        ('release-before-publish', 'gst-callsite.inc',
         'if (!gst_hevc_observer_end (self->decoder, &state->session, state->receipt.lease)) {',
         'if (FALSE) {', 'copy', '!gst_hevc_observer_busy(decoder)'),
        ('retain-callback-ownership', 'gst-callsite.inc', 'state->held_frame = frame;',
         'state->held_frame = NULL;', 'munmap-failure', '!gst_hevc_observer_busy(decoder)'),
        ('pristine-session', 'gst-callsite-native.inc', '!self->observer_submitted &&',
         '', 'late-arm', '!gst_hevc_callsite_arm(GST_H265_DECODER(client),TRUE)'),
        ('actual-output-buffer', 'gst-callsite-native.inc', 'request->pic_buf == buffer',
         'TRUE', 'wrong-buffer', 'result==GST_FLOW_ERROR && published==0 && finished==0'),
        ('frame-identity', 'gst-callsite.inc',
         'state->receipt.frame_num == frame->system_frame_number &&\n      state->receipt.frame_num == GST_CODEC_PICTURE (picture)->system_frame_number &&',
         'TRUE &&', 'wrong-frame', 'result==GST_FLOW_ERROR && published==0 && finished==0'),
        ('later-output-reentry', 'gst-callsite.inc',
         'state->in_callback = TRUE;\n  *active = state;',
         'if (!state->scheduled && state->attempted)\n    return state->success;\n  state->in_callback = TRUE;\n  *active = state;',
         'copy', '!gst_hevc_callsite_finish(GST_H265_DECODER(client))'),
        ('armed-lifecycle', 'gstv4l2codech265dec.c',
         'gst_v4l2_codec_h265_dec_close (GstVideoDecoder * decoder)\n{\n  GST_HEVC_OBSERVER_LOCK;\n  GstV4l2CodecH265Dec *self = GST_V4L2_CODEC_H265_DEC (decoder);\n  if (self->content_callsite || gst_hevc_observer_busy (self->decoder))',
         'gst_v4l2_codec_h265_dec_close (GstVideoDecoder * decoder)\n{\n  GST_HEVC_OBSERVER_LOCK;\n  GstV4l2CodecH265Dec *self = GST_V4L2_CODEC_H265_DEC (decoder);\n  if (gst_hevc_observer_busy (self->decoder))',
         'lifecycle', '!gst_v4l2_codec_h265_dec_close(GST_VIDEO_DECODER(client))'),
        ('armed-flush-recovery', 'gstv4l2codech265dec.c',
         '    gst_v4l2_codec_h265_dec_set_flushing (self, FALSE);\n    return FALSE;',
         '    return FALSE;', 'flush-armed',
         'gst_v4l2_codec_allocator_wait_for_buffer(client->src_allocator)'),
        ('schedule-immutable', 'gst-callsite.inc',
         'memcpy (state->frames, frames, count * sizeof (*frames));',
         'memset (state->frames, 0, count * sizeof (*frames));',
         'schedule-copy', 'state->pool.used==scheduled_maps'),
        ('schedule-all-selected', 'gst-callsite.inc',
         'state->success = state->collected == state->count;',
         'state->success = TRUE; state->count = state->collected;',
         'schedule-copy', '!gst_hevc_callsite_result(GST_H265_DECODER(client))'),
        ('schedule-duplicate', 'gst-callsite.inc', 'if (state->observed[selected]) {',
         'if (state->observed[selected]) return TRUE;\n    if (FALSE) {',
         'schedule-duplicate', 'output(order[target_count-1])==GST_FLOW_ERROR'),
        ('schedule-native-frame', 'gst-callsite-native.inc',
         'request->frame_num == frame', 'TRUE', 'schedule-frame-mismatch',
         'output(wrong?999:order[i])==GST_FLOW_ERROR'),
        ('schedule-plan-unique', 'gst-callsite.inc', 'if (frames[i] == frames[j])',
         'if (FALSE)', 'schedule-invalid',
         '!gst_hevc_callsite_arm_frames(GST_H265_DECODER(client),TRUE,duplicates,2)'),
    ]
    for label, name, before, after, mode, assertion in cases:
        path = root / BASE / name
        original = path.read_text()
        try:
            path.write_text(integration.replace(original, before, after))
            binary = compile(build)
            result = subprocess.run([str(binary), mode], env=integration.ENV, text=True,
                                    capture_output=True, timeout=20)
            output = result.stdout + result.stderr
            if (result.returncode != -signal.SIGABRT or assertion not in output or
                    'Sanitizer' in output or 'runtime error:' in output):
                raise RuntimeError('wrong mutation failure: ' + label + '\n' + output)
            print('PASS named callsite mutation ' + label, flush=True)
        finally:
            path.write_text(original)
    compile(build)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', required=True, type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--native-file', type=Path)
    args = parser.parse_args()
    destination = args.keep.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        parser.error('--keep must name an empty directory')
    root = adapter.source.fetch(destination, args.archive)
    for patch in ['unaligned-io.patch', 'gstv4l2decoder-observer.patch']:
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', PARENT / 'gst-adapter' / patch], cwd=root)
    for src, dst in [('public-api-test.c', 'observer-api-test.c'), ('unaligned-io-test.c', 'unaligned-io-test.c')]:
        shutil.copyfile(PARENT / 'gst-adapter' / src, root / BASE / dst)
    path = root / BASE / 'meson.build'
    path.write_text(path.read_text() + '\n' + (PARENT / 'gst-adapter/test-meson.build').read_text())
    run(['patch', '--batch', '--fuzz=0', '-p1', '-i', PARENT / 'integration/gst-integration.patch'], cwd=root)
    integration.sync(root, 'gst')
    integration.fixture(root, 'gst')
    integration.prepare_gst_fixture(root)
    run(['patch', '--batch', '--fuzz=0', '-p1', '-i', HERE / 'client-hook.patch'], cwd=root)
    configure_fixture(root)
    for sanitizer, label in [('address,undefined', 'asan-ubsan'), ('thread', 'tsan')]:
        build = destination / label
        adapter.configure(root, build, sanitizer, args.native_file)
        binary = compile(build)
        adapter.pinned_linkage(build, binary)
        adapter.pinned_linkage(build, build / BASE / 'libgstv4l2codecs.so')
        positive(binary, sanitizer)
        integration.positive(build / BASE / 'content-api', 'gst', sanitizer)
        adapter.positive(build, sanitizer)
        if label == 'asan-ubsan':
            adapter.compile_targets(build, *adapter.ORIGINAL, 'gstvideoparsersbad', 'gstcoreelements', 'gstapp')
            adapter.original_tests(build)
            mutations(root, build)
        for name in ['libgstv4l2codecs.so', 'callsite-api']:
            artifact = build / BASE / name
            print(label, name, 'sha256', adapter.source.digest(artifact), flush=True)
    print('PASS production output callback; synthetic syscalls only', flush=True)


if __name__ == '__main__':
    main()
