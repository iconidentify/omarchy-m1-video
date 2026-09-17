#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual patched glue and end callback, with real FFmpeg types and VA issue stub."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent


def extract(source,name):
    start=source.index('static int '+name+'(')
    end=source.index('{',start)+1
    depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]


def test(tree):
    glue=(tree/'libavcodec/h264_vaapi_admit.c').read_text()
    if glue!=(HERE/'h264_vaapi_admit.c').read_text(): raise ValueError('actual patched glue drift')
    end=extract((tree/'libavcodec/vaapi_h264.c').read_text(),'vaapi_h264_end_frame')
    mutations={
        'backend':('avctx->hwaccel->pix_fmt == AV_PIX_FMT_VAAPI','1'),
        'slice-required':(' || ctx->h264_admit_slices <= 0',''),
        'sticky':('ctx->h264_admit_sticky || ctx->h264_admit_in_picture','ctx->h264_admit_in_picture'),
        'unsupported-nal':('default: /* includes partitions, auxiliary/extension and unknown NALs */\n        return ff_h264_vaapi_admit_reject(avctx);','default: return 0;'),
    }
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        (root/'end.inc').write_text(end)
        for name in ('actual',*mutations):
            text=glue
            if name!='actual':
                old,new=mutations[name]
                if text.count(old)!=1: raise ValueError('mutation drift: '+name)
                text=text.replace(old,new)
            (root/'glue.inc').write_text(text)
            binary=root/name
            subprocess.run(['cc','-std=c11','-O0','-Wall','-Werror','-Wno-deprecated-declarations',
                            '-D_POSIX_C_SOURCE=200809L','-DHAVE_AV_CONFIG_H',
                            '-I',str(root),'-I',str(tree),'-I',str(tree/'libavcodec'),
                            str(HERE/'glue-fixture.c'),'-o',str(binary)],check=True,timeout=30)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
            if name=='actual' and result.returncode: raise RuntimeError(result.stderr)
            if name!='actual' and result.returncode!=1: raise RuntimeError('mutation was not distinguished: '+name)
        print('PASS: actual glue and end callback; four real-source mutations fail')
    return {'actual_glue_sha256':hashlib.sha256(glue.encode()).hexdigest(),
            'end_callback_sha256':hashlib.sha256(end.encode()).hexdigest(),'mutations':list(mutations),
            'parser_exercised':False,'device_used':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path)
    test(p.parse_args().source.resolve())
