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
import re
import shutil
import subprocess
import sys

import bounded
import packing
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

    needle = "run.num_slices, run.num_entry_point_offsets);"
    need(hevc.count(needle) == 1, "start site changed")
    hevc = hevc.replace(needle, needle + "\n\tavd_cmdtrace_start(ctx, run.sps, run.pps, run.scaling_matrix,\n"
                        "\t\t\trun.decode, &run.sl[0], run.num_slices,\n"
                        "\t\t\trun.num_entry_point_offsets, dst);", 1)
    hevc = packing.instrument(hevc)
    (destination / "avd-hevc.c").write_text(hevc)

    drv = (destination / "avd-drv.c").read_text()
    drv = drv.replace('#include "avd-trace.h"\n',
                      '#include "avd-trace.h"\n#include "avd-cmdtrace.h"\n', 1)
    drv = drv.replace("\tavd_trace_init();\n",
                      "\tavd_trace_init();\n\tavd_cmdtrace_init();\n", 1)
    # Match the entire conditional. Replacing the nested call alone would
    # leave the second cleanup unconditional on successful registration.
    old = "\tif (ret)\n\t\tavd_trace_exit();\n"
    if drv.count(old) != 1:
        raise ValueError("module registration cleanup source drift")
    drv = drv.replace(old, "\tif (ret) {\n\t\tavd_cmdtrace_exit();\n\t\tavd_trace_exit();\n\t}\n", 1)
    old = "\tplatform_driver_unregister(&avd_driver);\n\tavd_trace_exit();\n"
    if drv.count(old) != 1:
        raise ValueError("module exit cleanup source drift")
    drv = drv.replace(old, "\tplatform_driver_unregister(&avd_driver);\n\tavd_cmdtrace_exit();\n\tavd_trace_exit();\n", 1)
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
    for name, expected in json.loads((HERE / "sources.json").read_text())["accepted_trace_files"].items():
        need(digest(TRACE / name) == expected, "accepted source changed: " + name)
    spec = importlib.util.spec_from_file_location("hevc_avd_trace_prepare", TRACE / "prepare.py")
    trace_prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trace_prepare)
    # Source-only first: never compile before command-trace hooks exist.
    trace_prepare.prepare(source, destination, None)
    apply_cmd_hooks(destination)
    for name in ("avd-cmdtrace.c", "avd-cmdtrace.h", "cmd-core.h", "bounded-snapshot.h", "control-layout.inc"):
        shutil.copyfile(HERE / "kernel" / name, destination / name)
    bounded.constrain(destination / "avd-trace.c")
    bounded.constrain(destination / "avd-cmdtrace.c", command=True)
    provenance = json.loads((destination / "provenance.json").read_text())
    provenance["cmdtrace_files"] = {name: digest(destination / name)
                                    for name in ("avd-cmdtrace.c", "avd-cmdtrace.h", "cmd-core.h", "bounded-snapshot.h", "control-layout.inc")}
    provenance["command_trace"] = True
    provenance["candidate_files"] = {p.name: digest(p) for p in sorted(destination.iterdir())
                                     if p.is_file() and p.name != "provenance.json"}
    if headers:
        manifest = json.loads((TRACE / "sources.json").read_text())
        need((headers / "include/config/kernel.release").read_text().strip() ==
             manifest["kernel_release"], "headers release differs from pinned kernel")
        need("CONFIG_ARM64=y" in (headers / ".config").read_text(), "headers are not ARM64")
        command = ["make", "-C", str(headers), "M=" + str(destination),
                   "CONFIG_VIDEO_APPLE_AVD=m", "V=1", "modules", "-j4"]
        with (destination / "build.log").open("w") as log:
            run(command, stdout=log, stderr=subprocess.STDOUT)
        ko = destination / "apple-avd.ko"
        need(ko.is_file(), "module was not built")
        nm = subprocess.check_output(["nm", str(ko)], text=True)
        for sym in ("avd_cmdtrace_start", "avd_cmdtrace_word", "avd_cmdtrace_job"):
            need(re.search(r"[tT]\s+" + sym + r"$", nm, re.M), "built module missing %s" % sym)
        provenance["module_sha256"] = digest(ko)
        provenance["candidate_files"] = {p.name: digest(p) for p in sorted(destination.iterdir())
                                         if p.is_file() and p.name != "provenance.json"}
        provenance["headers_used"] = True
        provenance["build_command"] = command
        provenance["headers_config_sha256"] = digest(headers / ".config")
        provenance["headers"] = {name: digest(headers / name) for name in
            (".config", "Module.symvers", "include/generated/autoconf.h", "include/generated/utsrelease.h")}
        provenance["compiler"] = subprocess.check_output(["cc", "--version"], text=True).splitlines()[0]
        provenance["vermagic"] = subprocess.check_output(["modinfo", "-F", "vermagic", str(ko)], text=True).strip()
        provenance["headers_release"] = (headers / "include/config/kernel.release").read_text().strip()
        provenance["kernel_compiler_header"] = (headers / "include/generated/compile.h").read_text()
        provenance["build_log_sha256"] = digest(destination / "build.log")
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
