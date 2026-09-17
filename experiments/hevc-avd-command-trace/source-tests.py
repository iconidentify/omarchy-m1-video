#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Additive hooks must not change decode push/submit sequences."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import prepare


def calls(text, name):
    out = []
    for match in re.finditer(r"\b" + name + r"\(", text):
        start = match.end()
        pos = start
        depth = 1
        while depth:
            if text[pos] == "(":
                depth += 1
            if text[pos] == ")":
                depth -= 1
            pos += 1
        out.append(re.sub(r"\s+", "", text[start:pos - 1]))
    return out


def verify(source):
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "candidate"
        prepare.prepare(Path(source), work)
        need = work / "avd-hevc.c"
        text = need.read_text()
        if "avd_cmdtrace_start(ctx, run.sps, run.pps, run.scaling_matrix," not in text:
            raise ValueError("command-trace start hook missing")
        if "avd_cmdtrace_word(ctx, CMD_SITE_QP)" not in text:
            raise ValueError("QP hook missing")
        if "avd_cmdtrace_word(ctx, CMD_SITE_HDR_MODE)" not in text:
            raise ValueError("HDR_MODE hook missing")
        if "avd_cmdtrace_inactive(ctx, CMD_SITE_WT_SKIP)" not in text:
            raise ValueError("WT_SKIP inactive record missing")
        if "sl->data_byte_offset" not in text:
            raise ValueError("slice meta omits data_byte_offset")
        if "for (i = 0; i < 2; i++) {\n\t\tpush(AVD_SCALING_I2(dc_16x16" not in text:
            raise ValueError("dc_16x16 hook is outside the loop")
        if '\telse {\n\t\tpush(0, "cm3_mark_end_section");' not in text:
            raise ValueError("SCL_OFF hook is outside the else")
        if "slc_bd8_slice_addr" in text and "avd_cmdtrace_word(ctx, CMD_SITE_SLICE" in text:
            raise ValueError("coded address word was classified")
        if "avd_cmdtrace_start" not in (work / "avd-cmdtrace.c").read_text():
            raise ValueError("command recorder sources were not copied before hashing")
        files = json.loads((work / "provenance.json").read_text())["candidate_files"]
        if files["avd-hevc.c"] != prepare.digest(need):
            raise ValueError("provenance hashes a file other than the hooked avd-hevc.c")
        if files["avd-cmdtrace.c"] != prepare.digest(work / "avd-cmdtrace.c"):
            raise ValueError("provenance hashes a file other than the command recorder")
        start = text.index("static void set_scaling_lists")
        end = text.index("static void hevc_set_flags")
        stub = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8; typedef uint32_t u32;
struct v4l2_ctrl_hevc_scaling_matrix {
  u8 scaling_list_4x4[6][16]; u8 scaling_list_8x8[6][64];
  u8 scaling_list_16x16[6][64]; u8 scaling_list_32x32[2][64];
  u8 scaling_list_dc_coef_16x16[6]; u8 scaling_list_dc_coef_32x32[2];
};
struct avd_hevc_run { const struct v4l2_ctrl_hevc_scaling_matrix *scaling_matrix; };
struct avd_ctx { int dummy; };
enum { CMD_SITE_SCL_DIMS=11, CMD_SITE_SCL_DC16, CMD_SITE_SCL_DC32,
       CMD_SITE_SCL_4, CMD_SITE_SCL_8, CMD_SITE_SCL_16, CMD_SITE_SCL_32 };
#define HEVC_SCL_DIMS 1
#define AVD_SCALING_I0(v) ((u32)(v))
#define AVD_SCALING_I1(v) ((u32)(v)<<8)
#define AVD_SCALING_I2(v) ((u32)(v)<<16)
#define AVD_SCALING_I3(v) ((u32)(v)<<24)
static int npush, ntrace;
static void push(u32 w, const char *n) { (void)w; (void)n; npush++; }
#define avd_cmdtrace_word(ctx, site) do { (void)(ctx); (void)(site); ntrace++; } while (0)
'''
        body = text[start:end].replace("struct avd_ctx *ctx, struct avd_hevc_run *run",
                                       "struct avd_ctx *ctx, struct avd_hevc_run *run")
        driver = stub + body + r'''
int main(void) {
  struct v4l2_ctrl_hevc_scaling_matrix s; struct avd_hevc_run run; struct avd_ctx ctx;
  memset(&s, 1, sizeof(s)); run.scaling_matrix = &s;
  set_scaling_lists(&ctx, &run);
  if (npush != ntrace) return 2;
  if (npush != 1+2+2+24+96+96+32) return 3;
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as ctmp:
            src = Path(ctmp) / "scl.c"
            src.write_text(driver)
            binp = Path(ctmp) / "scl"
            subprocess.run(["cc", "-O0", "-Wall", "-Werror", "-Wmisleading-indentation",
                            str(src), "-o", str(binp)], check=True, timeout=30)
            subprocess.run([str(binp)], check=True, timeout=10)
        drv = (work / "avd-drv.c").read_text()
        if drv.index("avd_cmdtrace_open") < drv.index("avd_trace_open"):
            raise ValueError("cmdtrace open precedes accepted trace identity")
        v4l = (work / "avd-v4l2.c").read_text()
        if "avd_cmdtrace_done" not in v4l:
            raise ValueError("cmdtrace done hook missing")
        if (work / "Makefile").read_text().count("avd-cmdtrace.o") != 1:
            raise ValueError("cmdtrace not linked once")
        print("PASS: additive command-trace hooks, no coded-address capture")


if __name__ == "__main__":
    verify(Path(sys.argv[1]).resolve())
