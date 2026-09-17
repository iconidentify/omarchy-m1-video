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

    def after(needle, extra, every=False):
        nonlocal hevc
        count = hevc.count(needle)
        need(count == 1 or (every and count >= 1),
             "hook site missing/ambiguous (%d): %s" % (count, needle[:60]))
        if every:
            hevc = hevc.replace(needle, needle + extra)
            return
        idx = hevc.index(needle)
        end = hevc.index("\n", idx) + 1
        hevc = hevc[:end] + extra + hevc[end:]

    after("run.num_slices, run.num_entry_point_offsets);",
          "\tavd_cmdtrace_start(ctx, run.sps, run.pps, run.scaling_matrix,\n"
          "\t\t\trun.decode, &run.sl[0], run.num_slices,\n"
          "\t\t\trun.num_entry_point_offsets, dst);\n")
    after('"hdr_7c_pps_scl_dims");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_DIMS);\n")
    after('"dc_16x16");',
          "\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_DC16);\n")
    after('"dc_32x32");',
          "\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_DC32);\n")
    after('"scaling_4x4");',
          "\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_4);\n")
    after('"scaling_8x8");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_8);\n")
    after('"scaling_16x16");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_16);\n")
    after('"scaling_32x32");',
          "\t\t\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_32);\n")
    after('"cm3_mark_end_section");',
          "\t\tavd_cmdtrace_inactive(ctx, CMD_SITE_SCL_OFF);\n"
          "\t\tavd_cmdtrace_word(ctx, CMD_SITE_SCL_OFF);\n")
    after('"hdr_30_sps_pcm");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_PCM);\n")
    after('"hdr_34_sps_flags");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_SPSFLAGS);\n")
    after('"hdr_5c_pps_flags");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_PPSFLAGS);\n")
    after('"hdr_60_pps_qp");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_QP);\n")
    after('"hdr_34_start_hdr");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_START);\n")
    after('"hdr_2c_sps_txfm");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_HDR_TXFM);\n")
    after('"slc_bcc_cmd_quantization");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_QP);\n")
    after('"slc_bd0_cmd_deblocking_filter");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_DBLK);\n")
    after('"slc_76c_cmd_weights_denom");',
          "\tavd_cmdtrace_word(ctx, CMD_SITE_WT_HDR);\n", every=True)
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
          "\tavd_cmdtrace_slice_meta(ctx, size, offset, flags);\n")
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
    trace_prepare.prepare(source, destination, headers)
    apply_cmd_hooks(destination)
    for name in ("avd-cmdtrace.c", "avd-cmdtrace.h", "cmd-core.h"):
        shutil.copyfile(HERE / "kernel" / name, destination / name)
    provenance = json.loads((destination / "provenance.json").read_text())
    provenance["cmdtrace_files"] = {name: digest(destination / name)
                                    for name in ("avd-cmdtrace.c", "avd-cmdtrace.h", "cmd-core.h")}
    provenance["command_trace"] = True
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
