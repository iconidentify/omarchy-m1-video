#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute actual NAL dispatch/splitting and SPS/PPS parsing; no VA issue timing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def extract(source, name, prefix='static int '):
    start = source.index(prefix + name + '(')
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('mutation anchor drift')
    return text.replace(old, new)


def test(tree):
    glue = (tree/'libavcodec/h264_vaapi_admit.c').read_text()
    if glue != (HERE/'h264_vaapi_admit.c').read_text():
        raise ValueError('actual patched glue drift')
    decode = extract((tree/'libavcodec/h264dec.c').read_text(), 'decode_nal_units')
    harness = (HERE/'parser-harness.c').read_text()
    if 'canary_intact' not in harness or 'AV_PIX_FMT_CUDA' not in harness:
        raise ValueError('parser harness missing non-VA isolation')
    nal = '        ret = ff_h264_vaapi_admit_nal(avctx, nal->type);\n        if (ret < 0)\n            goto end;\n'
    sps = '            if (ff_h264_vaapi_admit_is_active(avctx)) {\n                ret = AVERROR_INVALIDDATA;\n                goto end;\n            }\n'
    pps_start=decode.index('        case H264_NAL_PPS:')
    pps_end=decode.index('        case H264_NAL_AUD:',pps_start)
    pps=decode[pps_start:pps_end]
    weak_pps=replace_once(pps,'ff_h264_vaapi_admit_is_active(avctx) ||','0 ||')
    split_start=decode.index('    ret = ff_h2645_packet_split(')
    split_end=decode.index('    if (avctx->active_thread_type',split_start)
    split=decode[split_start:split_end]
    weak_split=replace_once(split,'            goto end;','            (void)avctx;')
    backend_pred='avctx->hwaccel->pix_fmt == AV_PIX_FMT_VAAPI'
    if glue.count(backend_pred)!=1:
        raise ValueError('backend predicate drift')
    variants={
        'actual':(decode,harness,glue),
        'admit-nal':(replace_once(decode,nal,''),harness,glue),
        'sps-strict':(replace_once(decode,sps,''),harness,glue),
        'pps-strict':(replace_once(decode,pps,weak_pps),harness,glue),
        'split-sticky':(replace_once(decode,split,weak_split),harness,glue),
        'cleanup':(decode,replace_once(harness,'    ff_h2645_packet_uninit(&h.pkt);','    /* cleanup deliberately removed */'),glue),
        'backend-isolation':(decode,harness,replace_once(glue,backend_pred,'avctx->hwaccel != NULL')),
    }
    expected_assertions={
        'admit-nal':None,
        'sps-strict':None,
        'pps-strict':None,
        'split-sticky':None,
        'backend-isolation':'canary_intact()',
    }
    results={}
    env=os.environ.copy()
    # A caller cannot turn the leak/UB oracle off for this test.
    env.update(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1')
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        for name,(text,source,glue_text) in variants.items():
            (root/'glue.inc').write_text(glue_text)
            (root/'decode_nal.inc').write_text(text)
            (root/'harness.c').write_text(source)
            binary=root/name
            cmd=['cc','-std=c11','-O0','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                 '-Wall','-Werror','-Wno-deprecated-declarations','-Wno-unused-function',
                 '-D_POSIX_C_SOURCE=200809L','-DHAVE_AV_CONFIG_H',
                 '-I',str(root),'-I',str(HERE),'-I',str(tree),'-I',str(tree/'libavcodec'),
                 '-I',str(tree/'libavutil'),str(root/'harness.c'),
                 str(tree/'libavcodec/h2645_parse.c'),str(tree/'libavcodec/h264_ps.c'),
                 str(tree/'libavcodec/libavcodec.a'),str(tree/'libavutil/libavutil.a'),'-lm','-o',str(binary)]
            compiled=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
            if compiled.returncode:raise RuntimeError(compiled.stderr[-4000:])
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env=env)
            diagnostic=result.stdout+result.stderr
            sanitizer='Sanitizer' in diagnostic or 'runtime error:' in diagnostic
            if name=='actual':
                if result.returncode or sanitizer or 'PASS actual NAL dispatch' not in result.stdout:
                    raise RuntimeError(diagnostic)
            elif name=='cleanup':
                if result.returncode!=1 or 'LeakSanitizer: detected memory leaks' not in result.stderr:
                    raise RuntimeError('cleanup mutation not detected: '+diagnostic)
            elif result.returncode!=1 or 'failed line ' not in result.stderr or sanitizer:
                raise RuntimeError('semantic mutation not distinguished without sanitizer error: '+name+'\n'+diagnostic)
            assertion=next((line.split(': ',1)[1] for line in result.stderr.splitlines()
                            if line.startswith('failed line ')),None)
            expected=expected_assertions.get(name)
            if expected and assertion!=expected:
                raise RuntimeError('mutation failed at the wrong assertion: '+name+'\n'+diagnostic)
            results[name]=dict(returncode=result.returncode,stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
                               expected_failure=name!='actual',sanitizer_failure_expected=name=='cleanup',
                               assertion=assertion)
    print('PASS: actual NAL dispatch/splitter/SPS/PPS in Annex-B/AVCC and both error modes; five semantic mutations and packet-cleanup leak mutation fail')
    return dict(decode_nal_units_sha256=hashlib.sha256(decode.encode()).hexdigest(),
                h2645_parse_sha256=hashlib.sha256((tree/'libavcodec/h2645_parse.c').read_bytes()).hexdigest(),
                h264_ps_sha256=hashlib.sha256((tree/'libavcodec/h264_ps.c').read_bytes()).hexdigest(),
                harness_sha256=hashlib.sha256(harness.encode()).hexdigest(),
                parameter_fixtures_sha256=hashlib.sha256((HERE/'parameter-fixtures.inc').read_bytes()).hexdigest(),
                results=results,dispatch_calls=34,device_used=False,remap='disabled',
                limitations=['slice header/queue and picture ownership substituted','start/slice callbacks call actual stop helpers only',
                             'no end_frame or issue callback; no real submission timing','SEI/IDR/thread/error-concealment services stubbed',
                             'no AU/chunk/thread/config/flush proof','linked FFmpeg libraries not fully sanitizer-instrumented',
                             'non-VA isolation uses a fake CUDA pix_fmt hwaccel and canary priv_data; no real other backend'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    print(json.dumps(test(p.parse_args().source.resolve()),indent=2))
