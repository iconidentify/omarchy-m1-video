#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual patched decode_nal_units with ff_h2645_packet_split. No device."""
import argparse
import hashlib
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


def test(tree):
    glue = (tree / 'libavcodec/h264_vaapi_admit.c').read_text()
    if glue != (HERE / 'h264_vaapi_admit.c').read_text():
        raise ValueError('actual patched glue drift')
    decode = extract((tree / 'libavcodec/h264dec.c').read_text(), 'decode_nal_units')
    if 'ff_h264_vaapi_admit_nal' not in decode:
        raise ValueError('patched decode_nal_units missing admit_nal')
    if 'H264_BASELINE' in decode:
        raise ValueError('remap leaked into decode_nal_units')
    end = extract((tree / 'libavcodec/vaapi_h264.c').read_text(), 'vaapi_h264_end_frame')
    mutations = {
        'admit-nal': ('        ret = ff_h264_vaapi_admit_nal(avctx, nal->type);\n'
                      '        if (ret < 0)\n            goto end;\n', ''),
    }
    parse_c = tree / 'libavcodec/h2645_parse.c'
    util = tree / 'libavutil' / 'libavutil.a'
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / 'glue.inc').write_text(glue)
        (root / 'end.inc').write_text(end)
        for name in ('actual', *mutations):
            text = decode
            if name != 'actual':
                old, new = mutations[name]
                if text.count(old) != 1:
                    raise ValueError('mutation drift: ' + name)
                text = text.replace(old, new)
            (root / 'decode_nal.inc').write_text(text)
            binary = root / name
            cmd = ['cc', '-std=c11', '-O0', '-Wall', '-Werror',
                   '-Wno-deprecated-declarations', '-Wno-unused-function',
                   '-D_POSIX_C_SOURCE=200809L', '-DHAVE_AV_CONFIG_H',
                   '-I', str(root), '-I', str(tree), '-I', str(tree / 'libavcodec'),
                   '-I', str(tree / 'libavutil'),
                   str(HERE / 'parser-harness.c'), str(parse_c),
                   str(util), '-lm', '-o', str(binary)]
            compiled = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if compiled.returncode:
                raise RuntimeError(compiled.stderr[-4000:])
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            if name == 'actual' and result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            if name != 'actual' and result.returncode != 1:
                raise RuntimeError('mutation was not distinguished: ' + name + '\n' + result.stdout + result.stderr)
        print('PASS: actual decode_nal_units/packet_split; admit_nal dispatch mutation fails')
    return {
        'decode_nal_units_sha256': hashlib.sha256(decode.encode()).hexdigest(),
        'parser': 'ff_h2645_packet_split',
        'device_used': False,
        'remap': 'disabled',
    }


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    test(p.parse_args().source.resolve())
