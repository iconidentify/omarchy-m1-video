#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Empty-session end_frame must not issue. Mutating the real in_picture check fails."""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def extract(source, name):
    start = source.index('int ' + name + '(')
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    source = (HERE / 'h264_vaapi_admit.c').read_text()
    gate = extract(source, 'ff_h264_vaapi_admit_end')
    if 'h264_admit_in_picture' not in gate:
        raise ValueError('end gate missing in_picture')
    prefix = '''#include <errno.h>
#define AVERROR(x) (-(x))
typedef struct { int h264_admit_sticky; int h264_admit_in_picture; } VAAPIDecodeContext;
typedef struct { void *hwaccel_priv_data; } AVCodecInternal;
typedef struct AVCodecContext { AVCodecInternal *internal; } AVCodecContext;
'''
    main_c = '''
int main(void) {
    VAAPIDecodeContext ctx = {0};
    AVCodecInternal internal = {&ctx};
    AVCodecContext avctx = {&internal};
    int issues = 0;
    if (ff_h264_vaapi_admit_end(0) >= 0) return 1;
    /* Empty session must not be treated as a successful picture. */
    if (ff_h264_vaapi_admit_end(&avctx) >= 0) return 2;
    ctx.h264_admit_in_picture = 1;
    if (ff_h264_vaapi_admit_end(&avctx) != 0) return 3;
    issues++;
    if (issues != 1) return 4;
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'gate.c'
        binary = Path(temp) / 'gate'
        path.write_text(prefix + gate + main_c)
        cmd = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)]
        subprocess.run(cmd, check=True, timeout=30)
        subprocess.run([str(binary)], check=True, timeout=10)
        broken = gate.replace('ctx->h264_admit_sticky || !ctx->h264_admit_in_picture',
                              'ctx->h264_admit_sticky')
        if broken == gate:
            raise ValueError('could not mutate in_picture check')
        path.write_text(prefix + broken + main_c)
        subprocess.run(cmd, check=True, timeout=30)
        result = subprocess.run([str(binary)], timeout=10)
        if result.returncode != 2:
            raise RuntimeError('mutating the real in_picture gate did not fail the empty-session assertion')
    print('PASS: empty session does not issue; removing in_picture check is distinguished')


if __name__ == '__main__':
    main()
