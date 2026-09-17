#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare an isolated candidate: 15 shipped patches + accepted trace hooks + this experiment.

Never installs or loads a module. Reuses hevc-avd-trace prepare/fetch read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TRACE = HERE.parent / "hevc-avd-trace"


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(cond, reason):
    if not cond:
        raise ValueError(reason)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, timeout=300, **kw)


def apply_cmd_hooks(destination: Path):
    makefile = (destination / "Makefile").read_text()
    need("avd-trace.o" in makefile, "accepted trace hooks missing")
    makefile = makefile.replace("avd-trace.o", "avd-trace.o avd-cmdtrace.o", 1)
    (destination / "Makefile").write_text(makefile)

    hevc = (destination / "avd-hevc.c").read_text()
    need('#include "avd-trace.h"' in hevc, "trace include missing")
    hevc = hevc.replace('#include "avd-trace.h"\n',
                        '#include "avd-trace.h"\n#include "avd-cmdtrace.h"\n', 1)

    def once(old, new):
        nonlocal hevc
        need(hevc.count(old) == 1, "hook block missing/ambiguous: %s" % old[:50])
        hevc = hevc.replace(old, new, 1)

    def after(needle, extra):
        nonlocal hevc
        need(hevc.count(needle) == 1, "hook site missing/ambiguous: %s" % needle[:50])
        idx = hevc.index(needle)
        end = hevc.index("\n", idx) + 1
        hevc = hevc[:end] + extra + hevc[end:]

    after("run.num_slices, run.num_entry_point_offsets);",
          "\tavd_cmdtrace_start(ctx, run.sps, run.pps, run.scaling_matrix,\n"
          "\t\t\trun.decode, &run.sl[0], run.num_slices,\n"
          "\t\t\trun.num_entry_point_offsets, dst);\n")
    after('"hdr_7c_pps_scl_dims");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_DIMS);\n")
    once(
        '\tfor (i = 0; i < 2; i++)\n'
        '\t\tpush(AVD_SCALING_I2(dc_16x16[i][0]) |\n'
        '\t\t\t     AVD_SCALING_I1(dc_16x16[i][1]) |\n'
        '\t\t\t     AVD_SCALING_I0(dc_16x16[i][2]),\n'
        '\t\t     "dc_16x16");\n',
        '\tfor (i = 0; i < 2; i++) {\n'
        '\t\tpush(AVD_SCALING_I2(dc_16x16[i][0]) |\n'
        '\t\t\t     AVD_SCALING_I1(dc_16x16[i][1]) |\n'
        '\t\t\t     AVD_SCALING_I0(dc_16x16[i][2]),\n'
        '\t\t     "dc_16x16");\n'
        '\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_DC16);\n'
        '\t}\n')
    once(
        '\tfor (i = 0; i < 2; i++)\n'
        '\t\tpush(AVD_SCALING_I2(s->scaling_list_dc_coef_32x32[i]),\n'
        '\t\t     "dc_32x32");\n',
        '\tfor (i = 0; i < 2; i++) {\n'
        '\t\tpush(AVD_SCALING_I2(s->scaling_list_dc_coef_32x32[i]),\n'
        '\t\t     "dc_32x32");\n'
        '\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_DC32);\n'
        '\t}\n')
    once(
        '\tfor (i = 0; i < 6; i++)\n'
        '\t\tfor (j = 0; j < 4; j++)\n'
        '\t\t\tpush(AVD_SCALING_I3(sc_4x4[i][0][j]) |\n'
        '\t\t\t\t     AVD_SCALING_I2(sc_4x4[i][1][j]) |\n'
        '\t\t\t\t     AVD_SCALING_I1(sc_4x4[i][2][j]) |\n'
        '\t\t\t\t     AVD_SCALING_I0(sc_4x4[i][3][j]),\n'
        '\t\t\t     "scaling_4x4");\n',
        '\tfor (i = 0; i < 6; i++)\n'
        '\t\tfor (j = 0; j < 4; j++) {\n'
        '\t\t\tpush(AVD_SCALING_I3(sc_4x4[i][0][j]) |\n'
        '\t\t\t\t     AVD_SCALING_I2(sc_4x4[i][1][j]) |\n'
        '\t\t\t\t     AVD_SCALING_I1(sc_4x4[i][2][j]) |\n'
        '\t\t\t\t     AVD_SCALING_I0(sc_4x4[i][3][j]),\n'
        '\t\t\t     "scaling_4x4");\n'
        '\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_4);\n'
        '\t\t}\n')
    once(
        '\t\t\tfor (k = 0; k < 8; k++)\n'
        '\t\t\t\tpush(AVD_SCALING_I3(sc_8x8[i][j][0][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I2(\n'
        '\t\t\t\t\t\t     sc_8x8[i][j][1][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I1(\n'
        '\t\t\t\t\t\t     sc_8x8[i][j][2][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I0(sc_8x8[i][j][3][k]),\n'
        '\t\t\t\t     "scaling_8x8");\n',
        '\t\t\tfor (k = 0; k < 8; k++) {\n'
        '\t\t\t\tpush(AVD_SCALING_I3(sc_8x8[i][j][0][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I2(\n'
        '\t\t\t\t\t\t     sc_8x8[i][j][1][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I1(\n'
        '\t\t\t\t\t\t     sc_8x8[i][j][2][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I0(sc_8x8[i][j][3][k]),\n'
        '\t\t\t\t     "scaling_8x8");\n'
        '\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_8);\n'
        '\t\t\t}\n')
    once(
        '\t\t\tfor (k = 0; k < 8; k++)\n'
        '\t\t\t\tpush(AVD_SCALING_I3(sc_16x16[i][j][0][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I2(\n'
        '\t\t\t\t\t\t     sc_16x16[i][j][1][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I1(\n'
        '\t\t\t\t\t\t     sc_16x16[i][j][2][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I0(\n'
        '\t\t\t\t\t\t     sc_16x16[i][j][3][k]),\n'
        '\t\t\t\t     "scaling_16x16");\n',
        '\t\t\tfor (k = 0; k < 8; k++) {\n'
        '\t\t\t\tpush(AVD_SCALING_I3(sc_16x16[i][j][0][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I2(\n'
        '\t\t\t\t\t\t     sc_16x16[i][j][1][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I1(\n'
        '\t\t\t\t\t\t     sc_16x16[i][j][2][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I0(\n'
        '\t\t\t\t\t\t     sc_16x16[i][j][3][k]),\n'
        '\t\t\t\t     "scaling_16x16");\n'
        '\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_16);\n'
        '\t\t\t}\n')
    once(
        '\t\t\tfor (k = 0; k < 8; k++)\n'
        '\t\t\t\tpush(AVD_SCALING_I3(sc_32x32[i][j][0][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I2(\n'
        '\t\t\t\t\t\t     sc_32x32[i][j][1][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I1(\n'
        '\t\t\t\t\t\t     sc_32x32[i][j][2][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I0(\n'
        '\t\t\t\t\t\t     sc_32x32[i][j][3][k]),\n'
        '\t\t\t\t     "scaling_32x32");\n',
        '\t\t\tfor (k = 0; k < 8; k++) {\n'
        '\t\t\t\tpush(AVD_SCALING_I3(sc_32x32[i][j][0][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I2(\n'
        '\t\t\t\t\t\t     sc_32x32[i][j][1][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I1(\n'
        '\t\t\t\t\t\t     sc_32x32[i][j][2][k]) |\n'
        '\t\t\t\t\t     AVD_SCALING_I0(\n'
        '\t\t\t\t\t\t     sc_32x32[i][j][3][k]),\n'
        '\t\t\t\t     "scaling_32x32");\n'
        '\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_32);\n'
        '\t\t\t}\n')
    once(
        '\telse\n'
        '\t\tpush(0, "cm3_mark_end_section");\n',
        '\telse {\n'
        '\t\tpush(0, "cm3_mark_end_section");\n'
        '\t\tavd_cmdtrace_inactive(ctx, CMD_SITE_SCL_OFF);\n'
        '\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_OFF);\n'
        '\t}\n')
    after('"hdr_30_sps_pcm");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_PCM);\n")
    after('"hdr_34_sps_flags");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_SPSFLAGS);\n")
    after('"hdr_5c_pps_flags");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_PPSFLAGS);\n")
    after('"hdr_60_pps_qp");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_QP);\n")
    after('"hdr_64_zero");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_ZERO);\n")
    after('"hdr_34_start_hdr");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_START);\n")
    after('"hdr_50_mode");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_MODE);\n")
    once(
        '\tpush(AVD_HDR_HEIGHT(height - 1) | AVD_HDR_WIDTH(width - 1),\n'
        '\t     "hdr_54_height_width");\n'
        '\tpush(0, "hdr_58_pixfmt_zero");\n',
        '\tpush(AVD_HDR_HEIGHT(height - 1) | AVD_HDR_WIDTH(width - 1),\n'
        '\t     "hdr_54_height_width");\n'
        '\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_DIM);\n'
        '\tpush(0, "hdr_58_pixfmt_zero");\n')
    after('"hdr_28_height_width_shift3");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_SHIFT3);\n")
    after('"hdr_2c_sps_txfm");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_TXFM);\n")
    after('"slc_bcc_cmd_quantization");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_QP);\n")
    after('"slc_bd0_cmd_deblocking_filter");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_DBLK);\n")
    once(
        '\t\tpush(AVD_OP_WEIGHTS_HDR, "slc_76c_cmd_weights_denom");\n'
        '\t\treturn;\n',
        '\t\tpush(AVD_OP_WEIGHTS_HDR, "slc_76c_cmd_weights_denom");\n'
        '\t\tavd_cmdtrace_word(ctx, CMD_SITE_WT_HDR);\n'
        '\t\tavd_cmdtrace_inactive(ctx, CMD_SITE_WT_SKIP);\n'
        '\t\treturn;\n')
    once(
        '\t     "slc_76c_cmd_weights_denom");\n'
        '\n'
        '\tluma_weight_denom',
        '\t     "slc_76c_cmd_weights_denom");\n'
        '\tavd_cmdtrace_word(ctx, CMD_SITE_WT_HDR);\n'
        '\n'
        '\tluma_weight_denom')
    after('"slc_luma_weights");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_WT_LUMA);\n")
    after('"slc_luma_offsets");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_WT_LUMA_OFF);\n")
    after('"slc_chroma_weights[0]");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_WT_CHR);\n")
    after('"slc_chroma_offsets[0]");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_WT_CHR_OFF);\n")
    after('"slc_chroma_weights[1]");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_WT_CHR);\n")
    after('"slc_chroma_offsets[1]");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_WT_CHR_OFF);\n")
    after('"hdr_98_const_30");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_FEAT);\n")
    after('"cm3_cmd_set_cabac_xy");',
          "\t\tavd_cmdtrace_word(ctx, CMD_SITE_LOC_CABAC);\n")
    after('"cm3_cmd_set_ctb_xy");',
          "\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_LOC_CTB);\n")
    after('"cm3_set_mv_xy");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_LOC_MV);\n")
    after('"slc_bdc_slice_size");',
          "\tavd_cmdtrace_slice_meta(ctx, size, offset, flags, sl->data_byte_offset);\n")
    (destination / "avd-hevc.c").write_text(hevc)

    drv = (destination / "avd-drv.c").read_text()
    drv = drv.replace('#include "avd-trace.h"\n',
                      '#include "avd-trace.h"\n#include "avd-cmdtrace.h"\n', 1)
    drv = drv.replace("\tavd_trace_init();\n",
                      "\tavd_trace_init();\n\tavd_cmdtrace_init();\n", 1)
    drv = drv.replace("\tavd_trace_exit();\n",
                      "\tavd_cmdtrace_exit();\n\tavd_trace_exit();\n")
    drv = drv.replace("\tavd_trace_open(ctx);\n",
                      "\tavd_trace_open(ctx);\n\tavd_cmdtrace_open(ctx);\n", 1)
    drv = drv.replace("\tavd_trace_close(ctx);\n",
                      "\tavd_cmdtrace_close(ctx);\n\tavd_trace_close(ctx);\n", 1)
    drv = drv.replace("\tavd_trace_job(ctx);\n",
                      "\tavd_trace_job(ctx);\n\tavd_cmdtrace_job(ctx);\n", 1)
    (destination / "avd-drv.c").write_text(drv)

    v4l = (destination / "avd-v4l2.c").read_text()
    if '#include "avd-trace.h"' in v4l:
        v4l = v4l.replace('#include "avd-trace.h"\n',
                          '#include "avd-trace.h"\n#include "avd-cmdtrace.h"\n', 1)
    need("avd_trace_done(ctx, result);" in v4l, "trace done hook missing")
    v4l = v4l.replace("\tavd_trace_done(ctx, result);\n",
                      "\tavd_trace_done(ctx, result);\n\tavd_cmdtrace_done(ctx, result == VB2_BUF_STATE_DONE);\n", 1)
    (destination / "avd-v4l2.c").write_text(v4l)


def prepare(source: Path, destination: Path, headers=None):
    need(digest(TRACE / "hooks.patch") == json.loads((HERE / "sources.json").read_text())["trace_hooks_sha256"],
         "accepted trace hooks changed")
    spec = importlib.util.spec_from_file_location("hevc_avd_trace_prepare", TRACE / "prepare.py")
    trace_prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trace_prepare)
    # Source-only first: never compile before command-trace hooks exist.
    trace_prepare.prepare(source, destination, None)
    apply_cmd_hooks(destination)
    for name in ("avd-cmdtrace.c", "avd-cmdtrace.h", "cmd-core.h"):
        shutil.copyfile(HERE / "kernel" / name, destination / name)
    provenance = json.loads((destination / "provenance.json").read_text())
    provenance["cmdtrace_files"] = {name: digest(destination / name)
                                    for name in ("avd-cmdtrace.c", "avd-cmdtrace.h", "cmd-core.h")}
    provenance["command_trace"] = True
    provenance["candidate_files"] = {p.name: digest(p) for p in sorted(destination.iterdir())
                                     if p.is_file()}
    if headers:
        manifest = json.loads((TRACE / "sources.json").read_text())
        need((headers / "include/config/kernel.release").read_text().strip() ==
             manifest["kernel_release"], "headers release differs from pinned kernel")
        need("CONFIG_ARM64=y" in (headers / ".config").read_text(), "headers are not ARM64")
        command = ["make", "-s", "-C", str(headers), "M=" + str(destination),
                   "CONFIG_VIDEO_APPLE_AVD=m", "modules", "-j4"]
        with (destination / "build.log").open("w") as log:
            run(command, stdout=log, stderr=subprocess.STDOUT)
        ko = destination / "apple-avd.ko"
        need(ko.is_file(), "module was not built")
        nm = subprocess.check_output(["nm", str(ko)], text=True)
        for sym in ("avd_cmdtrace_start", "avd_cmdtrace_word", "avd_cmdtrace_job"):
            need(sym in nm, "built module missing %s" % sym)
        provenance["module_sha256"] = digest(ko)
        provenance["candidate_files"] = {p.name: digest(p) for p in sorted(destination.iterdir())
                                         if p.is_file()}
        provenance["headers_used"] = True
        need(provenance["candidate_files"]["avd-hevc.c"] == digest(destination / "avd-hevc.c"),
             "provenance avd-hevc.c hash is not the hooked file")
    (destination / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--headers", type=Path)
    a = p.parse_args()
    try:
        prepare(a.source.resolve(), a.destination.resolve(),
                a.headers.resolve() if a.headers else None)
        print("PASS: isolated command-trace candidate prepared; not installed")
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("prepare rejected:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
