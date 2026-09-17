#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Additive hooks must not change decode push/submit sequences."""
from __future__ import annotations

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
        if "avd_cmdtrace_start" not in text:
            raise ValueError("command-trace start hook missing")
        if "avd_cmdtrace_word(ctx, CMD_SITE_QP)" not in text:
            raise ValueError("QP hook missing")
        if "slc_bd8_slice_addr" in text and "avd_cmdtrace_word(ctx, CMD_SITE_SLICE" in text:
            raise ValueError("coded address word was classified")
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
