#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute actual slice-header/queue, field-end and AU completion. No device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def extract(source, name, prefix):
    start = source.index(prefix + name + '(')
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('mutation anchor drift: ' + old[:80])
    return text.replace(old, new)


def test(tree):
    glue = (tree / 'libavcodec/h264_vaapi_admit.c').read_text()
    if glue != (HERE / 'h264_vaapi_admit.c').read_text():
        raise ValueError('actual patched glue drift')
    h264dec = (tree / 'libavcodec/h264dec.c').read_text()
    slice_c = (tree / 'libavcodec/h264_slice.c').read_text()
    picture_c = (tree / 'libavcodec/h264_picture.c').read_text()
    vaapi_c = (tree / 'libavcodec/vaapi_h264.c').read_text()
    decode = extract(h264dec, 'decode_nal_units', 'static int ')
    frame = extract(h264dec, 'h264_decode_frame', 'static int ')
    frame_helpers = '\n'.join(extract(h264dec, name, 'static int ') for name in
                              ('is_avcc_extradata', 'send_next_delayed_frame'))
    refs_c = (tree / 'libavcodec/h264_refs.c').read_text()
    header = extract(slice_c, 'h264_slice_header_parse', 'static int ')
    queue = extract(slice_c, 'ff_h264_queue_decode_slice', 'int ')
    execute = extract(slice_c, 'ff_h264_execute_decode_slices', 'int ')
    field_end = extract(picture_c, 'ff_h264_field_end', 'int ')
    end_frame = extract(vaapi_c, 'vaapi_h264_end_frame', 'static int ')
    flush = extract(h264dec, 'ff_h264_flush_change', 'void ')
    reorder = extract(refs_c, 'ff_h264_decode_ref_pic_list_reordering', 'int ')
    marking = extract(refs_c, 'ff_h264_decode_ref_pic_marking', 'int ')
    harness = (HERE / 'slice-queue-harness.c').read_text()
    if 'header_parse.inc' not in harness or '(void)nal; /* Deliberately' in harness:
        raise ValueError('slice-queue harness still stubs the NAL')
    error_end = (
        '        if (h->current_slice && h->cur_pic_ptr && FF_HW_HAS_CB(avctx, end_frame)) {\n'
        '            (void)FF_HW_SIMPLE_CALL(avctx, end_frame);\n'
        '            h->current_slice = 0;\n'
        '        }\n'
    )
    if error_end not in decode:
        raise ValueError('patched decode_nal_units is missing error-path end_frame')
    variants = {
        'actual': dict(decode=decode, queue=queue, field_end=field_end),
        'header-parse': dict(
            decode=decode,
            queue=replace_once(queue, '    ret = h264_slice_header_parse(h, sl, nal);\n', '    ret = 0;\n'),
            field_end=field_end,
        ),
        'field-end': dict(
            decode=decode,
            queue=queue,
            field_end=replace_once(
                field_end,
                '        err = FF_HW_SIMPLE_CALL(avctx, end_frame);\n',
                '        err = 0;\n',
            ),
        ),
        'error-end': dict(
            decode=replace_once(decode, error_end, ''),
            queue=queue,
            field_end=field_end,
        ),
        'split-cancel': dict(
            decode=replace_once(decode,
                '        if (ff_h264_vaapi_admit_is_active(avctx))\n            goto end;\n',
                '        if (ff_h264_vaapi_admit_is_active(avctx))\n            ff_h264_vaapi_admit_reject(avctx);\n'),
            queue=queue, field_end=field_end,
        ),
        'cancel-once': dict(
            decode=replace_once(decode, '            h->current_slice = 0;\n', ''),
            queue=queue, field_end=field_end,
        ),
        'flush-cancel': dict(
            decode=decode, queue=queue, field_end=field_end,
            flush=replace_once(flush,
                '            (void)FF_HW_SIMPLE_CALL(h->avctx, end_frame);\n',
                '            (void)h;\n'),
        ),
        'eof-cancel': dict(
            decode=decode, queue=queue, field_end=field_end,
            frame=replace_once(frame, '            ff_h264_flush_change(h);\n',
                               '            (void)h;\n'),
        ),
        'chunk-completion': dict(
            decode=decode, queue=queue, field_end=field_end,
            frame=replace_once(frame,
                '    if (!(avctx->flags2 & AV_CODEC_FLAG2_CHUNKS) ||\n',
                '    if (1 ||\n'),
        ),
    }
    results = {}
    expected_assertions = {
        'header-parse': 'ret == n',
        'field-end': 'issues == 1 && cancels == 0',
        'error-end': 'ret < 0 && starts == 1 && slices == 1 && issues == 0 && cancels == 1',
        'split-cancel': 'ret < 0 && issues == 0 && cancels == 1',
        'cancel-once': 'ctx.h264_admit_sticky && h.current_slice == 0',
        'flush-cancel': 'cancels == 1 && issues == 0 && h.current_slice == 0',
        'eof-cancel': 'decode_frame(buf, 0) == 0 && cancels == 1 && issues == 0',
        'chunk-completion': 'ret == n && issues == 0 && cancels == 0 && starts == 1',
    }
    env = os.environ.copy()
    env.update(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1')
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / 'glue.inc').write_text(glue)
        (root / 'frame_helpers.inc').write_text(frame_helpers)
        (root / 'header_parse.inc').write_text(header)
        (root / 'execute.inc').write_text(execute)
        (root / 'end_frame.inc').write_text(end_frame)
        (root / 'ref_helpers.inc').write_text('\n'.join((reorder, marking)))
        for name, parts in variants.items():
            (root / 'decode_frame.inc').write_text(parts.get('frame', frame))
            (root / 'flush.inc').write_text(parts.get('flush', flush))
            (root / 'decode_nal.inc').write_text(parts['decode'])
            (root / 'queue.inc').write_text(parts['queue'])
            (root / 'field_end.inc').write_text(parts['field_end'])
            (root / 'harness.c').write_text(harness)
            binary = root / name
            va_libs = subprocess.check_output(
                ['pkg-config', '--libs', 'libva', 'libva-drm'], text=True).split()
            cmd = [
                'cc', '-std=c11', '-O0', '-g', '-fsanitize=address,undefined',
                '-fno-sanitize-recover=all', '-Wall', '-Werror',
                '-Wno-deprecated-declarations', '-Wno-unused-function',
                '-Wno-unused-variable', '-Wno-pointer-sign',
                '-Wno-parentheses',  # pinned h264_decode_frame Q264 condition
                '-D_POSIX_C_SOURCE=200809L', '-DHAVE_AV_CONFIG_H',
                '-I', str(root), '-I', str(HERE), '-I', str(tree),
                '-I', str(tree / 'libavcodec'), '-I', str(tree / 'libavutil'),
                str(root / 'harness.c'),
                str(tree / 'libavcodec/h2645_parse.c'),
                str(tree / 'libavcodec/h264_ps.c'),
                str(tree / 'libavcodec/h264_parse.c'),
                str(tree / 'libavcodec/libavcodec.a'),
                str(tree / 'libavutil/libavutil.a'), '-lm', *va_libs, '-o', str(binary),
            ]
            compiled = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if compiled.returncode:
                raise RuntimeError(compiled.stderr[-4000:] + compiled.stdout[-1000:])
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10, env=env)
            diagnostic = result.stdout + result.stderr
            sanitizer = 'Sanitizer' in diagnostic or 'runtime error:' in diagnostic
            if name == 'actual':
                if result.returncode or sanitizer or 'PASS actual slice-header/queue' not in result.stdout:
                    raise RuntimeError(diagnostic)
            elif result.returncode != 1 or 'failed line ' not in result.stderr or sanitizer:
                raise RuntimeError('semantic mutation not distinguished without sanitizer error: ' + name + '\n' + diagnostic)
            assertion = next((line.split(': ', 1)[1] for line in result.stderr.splitlines()
                              if line.startswith('failed line ')), None)
            if name != 'actual' and assertion != expected_assertions[name]:
                raise RuntimeError('mutation failed at the wrong assertion: ' + name + '\n' + diagnostic)
            results[name] = dict(
                returncode=result.returncode,
                stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
                expected_failure=name != 'actual',
                assertion=assertion,
            )
    print('PASS: actual frame/dispatch/slice-header/queue/field-end/flush with issue/cancel stubs; eight semantic mutations fail')
    return dict(
        decode_nal_units_sha256=hashlib.sha256(decode.encode()).hexdigest(),
        h264_decode_frame_sha256=hashlib.sha256(frame.encode()).hexdigest(),
        ff_h264_flush_change_sha256=hashlib.sha256(flush.encode()).hexdigest(),
        frame_helpers_sha256=hashlib.sha256(frame_helpers.encode()).hexdigest(),
        h264_parse_sha256=hashlib.sha256((tree / 'libavcodec/h264_parse.c').read_bytes()).hexdigest(),
        slice_fixtures_sha256=hashlib.sha256((HERE / 'slice-fixtures.inc').read_bytes()).hexdigest(),
        queue_sha256=hashlib.sha256(queue.encode()).hexdigest(),
        header_parse_sha256=hashlib.sha256(header.encode()).hexdigest(),
        field_end_sha256=hashlib.sha256(field_end.encode()).hexdigest(),
        harness_sha256=hashlib.sha256(harness.encode()).hexdigest(),
        results=results,
        device_used=False,
        remap='disabled',
        limitations=[
            'h264_field_start/h264_slice_init substituted (no DPB allocation)',
            'software MB decode not executed',
            'output-frame construction substituted; delayed output not qualified',
            'VA start/slice parameter buffers not filled (no surface/device)',
            'vaapi_decode_make_config and frame threading untested',
            'linked FFmpeg libraries not fully sanitizer-instrumented',
        ],
    )


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    print(json.dumps(test(p.parse_args().source.resolve()), indent=2))
