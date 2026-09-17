#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce incomplete-picture admission in the actual rejected end gate."""
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
    source = (HERE / 'rejected/h264_vaapi_select.c').read_text()
    gate = extract(source, 'ff_h264_vaapi_gate_end')
    # Minimal storage fixture, not a VA device, full decoder or parser.
    prefix = '''#include <errno.h>
#include "h264_vaapi_select.h"
#define AVERROR(x) (-(x))
typedef struct { struct h264_va_session h264_sel; } VAAPIDecodeContext;
typedef struct { void *hwaccel_priv_data; } AVCodecInternal;
typedef struct AVCodecContext { AVCodecInternal *internal; } AVCodecContext;
'''
    main = '''
int main(void) {
    VAAPIDecodeContext ctx = {0};
    AVCodecInternal internal = {&ctx};
    AVCodecContext avctx = {&internal};
    if (ff_h264_vaapi_gate_end(0) >= 0) return 1;
    /* A zeroed session has never accepted a picture or slice. Actual gate allows it. */
    if (ff_h264_vaapi_gate_end(&avctx) != 0) return 2;
    ctx.h264_sel.sticky = 1;
    if (ff_h264_vaapi_gate_end(&avctx) >= 0) return 3;
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'gate.c'
        binary = Path(temp) / 'gate'
        path.write_text(prefix + gate + main)
        command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I',
                   str(HERE / 'rejected'), str(path), '-o', str(binary)]
        subprocess.run(command, check=True, timeout=30)
        subprocess.run([str(binary)], check=True, timeout=10)
        # Repair mutation: the blocking reproducer must stop passing if fixed.
        fixed = gate.replace('if (ctx->h264_sel.sticky || ctx->h264_sel.cancelled)',
                             'if (!ctx->h264_sel.in_picture || ctx->h264_sel.sticky || ctx->h264_sel.cancelled)')
        if fixed == gate:
            raise ValueError('source extraction drift')
        path.write_text(prefix + fixed + main)
        subprocess.run(command, check=True, timeout=30)
        result = subprocess.run([str(binary)], timeout=10)
        if result.returncode != 2:
            raise RuntimeError('reproducer failed to distinguish repaired gate')
    print('PASS: actual gate admits empty session; repair mutation is distinguished (no VA issue called)')


if __name__ == '__main__':
    main()
