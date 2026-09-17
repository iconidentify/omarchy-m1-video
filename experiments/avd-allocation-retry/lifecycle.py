#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute actual start/alloc_bufs/stop bodies with synthetic kernel services.

Geometry, control validation, codec context layout and VP9 table initialization
are stand-ins. This verifies failure unwind, not codec correctness or kernel ABI.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import source

HERE = Path(__file__).resolve().parent

def exercise(variants, root):
    results = {}
    prefix = (HERE/'harness.c').read_text().split('/* ---- functions under test')[0]
    prefix = prefix.replace('void *dev;\n};', 'void *dev;\n\tstruct variant { int quirks; } *variant;\n};')
    for variant in ('pinned', 'candidate', 'unwind-mutant'):
        tree = variants['candidate' if variant == 'unwind-mutant' else variant]
        drv = (tree/'avd-drv.c').read_text()
        allocator = source.function(drv,'avd_buf_free') + '\n' + source.function(drv,'avd_buf_alloc')
        for codec, count in (('hevc',2),('h264',7),('vp9',12)):
            c = (tree/('avd-'+codec+'.c')).read_text()
            bodies = [source.function(c,'avd_'+codec+'_'+name) for name in ('alloc_bufs','stop','start')]
            if variant == 'unwind-mutant':
                old = 'avd_'+codec+'_stop(ctx);'
                if bodies[2].count(old) != 1: raise ValueError('unwind mutation drift')
                bodies[2] = bodies[2].replace(old,'kfree('+codec+'_ctx);')
            # Only fields actually consumed by these functions. Explicit synthetic
            # environment: no claim to use the full real codec context layout.
            fields = sorted(set(re.findall(r'bufs\.(\w+)', '\n'.join(bodies))))
            env = '''
#define EINVAL 22
#define AVD_IMG_FMT_420_10BIT 1
#define AVD_IMG_FMT_422_10BIT 2
#define AVD_QUIRK_NO_PIPE_STATE 1
#define VP9_MAX_TILE_COLS 64
#define DIV_ROUND_UP(n,d) (((n)+(d)-1)/(d))
struct avd_ctx { struct avd_dev *dev; void *priv; int image_fmt; int ctrl_hdl; };
struct avd_vp9_probs { char opaque[4096]; };
struct avd_vp9_frame_symbol_counts { char opaque[8192]; };
struct v4l2_ctrl { struct { void *p_h264_sps; } p_new; };
#define V4L2_CID_STATELESS_H264_SPS 1
#define fmt_width(ctx) 448
#define fmt_height(ctx) 240
#define fifo_size() 4096
#define avd_h264_validate_sps(ctx,sps) 0
#define avd_init_v4l2_vp9_count_tbl(ctx) ((void)(ctx))
static struct v4l2_ctrl fixture_ctrl;
#define v4l2_ctrl_find(h,id) ((void)(h), (void)(id), &fixture_ctrl)
static int fail_context;
static void *kzalloc(size_t n, int flags) { (void)flags; return fail_context ? NULL : calloc(1,n); }
#define kfree(p) free(p)
'''
            env += 'struct avd_'+codec+'_ctx { struct {\n'
            env += ''.join('struct avd_buf '+f+';\n' for f in fields)
            env += '} bufs; int slice_num; struct avd_buf slices[64]; };\n'
            main = '''
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    int failure = atoi(argv[1]);
    fail_at_count = failure > 0 ? 1 : 0; fail_at[0] = failure;
    fail_context = failure < 0;
    struct variant v = {0}; struct avd_dev dev = {.variant=&v};
    struct avd_ctx ctx = {.dev=&dev};
    int ret = avd_CODEC_start(&ctx);
    int bad = 0;
    if (failure == 0 && ret != 0) bad = 1;
    if (failure != 0 && (ret != -ENOMEM || ctx.priv != NULL)) bad = 1;
    if (ret == 0) { avd_CODEC_stop(&ctx); ctx.priv = NULL; }
    int leaked = live_count;
    /* Cleanup the known mock allocations AFTER recording the leak verdict. */
    while (live_count) { free(live[--live_count].cpu); }
    printf("ret=%d leaked=%d allocs=%d frees=%d\\n",ret,leaked,alloc_calls,free_calls);
    return bad ? 96 : leaked ? 95 : 0;
}
'''.replace('CODEC',codec)
            work = root/(variant+'-'+codec)
            work.mkdir()
            (work/'extracted-types.h').write_text(source.struct((tree/'avd.h').read_text(),'avd_buf')+';\n')
            # ctrl is unused for the other codecs; keep only their used stubs.
            if codec != 'h264': env = env.replace('static struct v4l2_ctrl fixture_ctrl;','')
            code = prefix + '\n' + env + allocator + '\n' + '\n'.join(bodies) + main
            path = work/'lifecycle.c'; path.write_text(code)
            cmd = [os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Wextra','-Werror','-O1','-g','-fno-omit-frame-pointer']
            if os.environ.get('AVD_SANITIZE'): cmd += ['-fsanitize=address,undefined','-fno-sanitize-recover=all']
            cmd += [str(path),'-o',str(work/'lifecycle')]
            compile = subprocess.run(cmd,capture_output=True,text=True,timeout=60)
            if compile.returncode: raise AssertionError(compile.stderr)
            for fail in (-1,0,*range(1,count+1)):
                result = subprocess.run([str(work/'lifecycle'),str(fail)],capture_output=True,text=True,timeout=10)
                expected = 95 if variant != 'candidate' and fail >= 2 else 0
                if result.returncode != expected: raise AssertionError((variant,codec,fail,result.returncode,result.stdout,result.stderr))
            results[variant+'-'+codec] = dict(failure_indices=count, context_failure=True,
                actual_functions_sha256=[hashlib.sha256(x.encode()).hexdigest() for x in bodies])
    return results
