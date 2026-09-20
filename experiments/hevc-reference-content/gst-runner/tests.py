#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the complete pinned plugin and exercise its real Gst runner path."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
BASE = Path("subprojects/gst-plugins-bad/sys/v4l2codecs")
MODES = """runner-default-off runner-copy-off runner-copy-on runner-short-write
runner-partial-config runner-duplicate-config runner-late-config
runner-invalid-selectors runner-duplicate-selectors runner-arm-refusal
runner-mutable-config runner-actual-arm runner-downstream-failure
runner-incomplete runner-cleanup-quarantine runner-write-failure
runner-fsync-failure runner-close-failure runner-collision
runner-json-determinism""".split()
SUCCESS_REPORTS = {
    "runner-copy-off": False,
    "runner-copy-on": True,
    "runner-short-write": True,
}


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


integration = module("content_integration", PARENT / "integration/tests.py")
sys.path.insert(0, str(PARENT / "gst-adapter"))
adapter = module("gst_adapter", PARENT / "gst-adapter/tests.py")
callsite = module("gst_callsite", PARENT / "gst-callsite/tests.py")
collector = module("gst_runner_collector", HERE / "collector.py")
run = integration.run


def configure_fixture(root: Path) -> None:
    directory = root / BASE
    for name in ("gst-runner.h", "gst-runner.inc"):
        shutil.copyfile(HERE / name, directory / name)
    source = (directory / "callsite-api-test.c").read_text()
    source = integration.replace(
        source, "int main(int argc,char **argv)",
        "int callsite_fixture_main(int argc,char **argv)")
    marker = "__attribute__((visibility(\"default\"))) int __wrap_open(const char *name,int flags,...) {"
    declarations = """static const gchar *runner_report_path;
static int runner_report_fd = -1;
static int runner_close(int);
""" + marker
    source = integration.replace(source, marker, declarations)
    source = integration.replace(
        source,
        "__attribute__((visibility(\"default\"))) int __wrap_close(int fd) "
        "{return evidence_fd(fd)?evidence_close(fd):base_close(fd);}",
        "__attribute__((visibility(\"default\"))) int __wrap_close(int fd) "
        "{return evidence_fd(fd)?evidence_close(fd):runner_close(fd);}")
    source = integration.replace(
        source,
        "  return __real_gst_video_decoder_finish_frame(dec,frame);",
        "  GstFlowReturn flow=__real_gst_video_decoder_finish_frame(dec,frame);\n"
        "  return !strcmp(mode,\"runner-downstream-failure\")?GST_FLOW_ERROR:flow;")
    source += "\n" + (HERE / "runner-model.inc").read_text()
    (directory / "runner-api-test.c").write_text(source)

    meson = directory / "meson.build"
    text = meson.read_text()
    start = text.rindex("callsite_sources =")
    addition = text[start:]
    addition = addition.replace("callsite_sources", "runner_sources")
    addition = addition.replace("callsite-api", "runner-api")
    addition = addition.replace("callsite-api-test.c", "runner-api-test.c")
    addition = integration.replace(
        addition, "'-Wl,--wrap=gst_video_decoder_drop_frame'",
        "'-Wl,--wrap=gst_video_decoder_drop_frame', '-Wl,--wrap=write', "
        "'-Wl,--wrap=fsync', '-Wl,--wrap=g_mkstemp_full'")
    meson.write_text(text + "\n" + addition)


def compile_targets(build: Path) -> Path:
    run(["meson", "compile", "-C", build, "-j", "4", "gstv4l2codecs",
         "runner-api", "callsite-api", "content-api", "observer-api"])
    return build / BASE / "runner-api"


def run_mode(binary: Path, mode: str) -> tuple[str, dict[str, object] | None]:
    with tempfile.TemporaryDirectory(prefix="hevc-gst-runner-") as temp:
        report = Path(temp) / "result.json"
        output = run([binary, mode, report])
        assert f"PASS actual Gst runner {mode}" in output, output
        document = None
        if mode in SUCCESS_REPORTS:
            document = collector.collect_report(
                report, process_exit_code=0, expected_frames=(31,),
                expected_copy=SUCCESS_REPORTS[mode])
            assert document["count"] == 1
            assert set(Path(temp).iterdir()) == {report}
        else:
            assert not report.exists(), mode
            assert not any(Path(temp).iterdir()), mode
        return output, document


def positive(binary: Path, sanitizer: str) -> None:
    for mode in MODES:
        output, _ = run_mode(binary, mode)
        print(sanitizer, output.strip(), flush=True)


def collector_checks(binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="hevc-gst-collector-") as temp:
        root = Path(temp)
        report = root / "valid.json"
        result = subprocess.run(
            [str(binary), "runner-copy-on", str(report)],
            env=integration.ENV, text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        data = report.read_bytes()
        valid = collector.collect_report(
            report, process_exit_code=0, expected_frames=(31,), expected_copy=True)
        assert valid["count"] == 1

        def rejected(payload: bytes, label: str) -> None:
            try:
                collector.parse_report(payload, expected_frames=(31,), expected_copy=True)
            except collector.ReportError:
                print("PASS Gst collector rejects " + label, flush=True)
            else:
                raise AssertionError("collector accepted " + label)

        text = data.decode()
        rejected(text.replace('"capture_index":', '"raw":', 1).encode(), "raw field")
        rejected(text.replace('"sha256":', '"sha256":"00","sha256":', 1).encode(),
                 "duplicate JSON key")
        rejected(text.replace('"system_frame_number":31',
                              '"system_frame_number":32', 1).encode(),
                 "selector mismatch")
        rejected(text.replace('"session":"', '"session":"f', 1).encode(),
                 "malformed identity")
        zero_identity = json.loads(text)
        zero_identity["outputs"][0]["session"] = "0" * 16
        rejected((json.dumps(zero_identity, separators=(",", ":")) + "\n").encode(),
                 "zero identity")
        rejected(data + b"\n", "multiple records")
        try:
            collector.parse_report(data, expected_frames=(31, 31), expected_copy=True)
        except collector.ReportError:
            print("PASS Gst collector rejects invalid expected selectors", flush=True)
        else:
            raise AssertionError("collector accepted duplicate expected selectors")
        try:
            collector.collect_report(report, process_exit_code=1,
                                     expected_frames=(31,), expected_copy=True)
        except collector.ReportError:
            print("PASS Gst collector rejects failed process", flush=True)
        else:
            raise AssertionError("collector accepted a failed process")

        link = root / "link.json"
        link.symlink_to(report)
        try:
            collector.load_report(link, expected_frames=(31,), expected_copy=True)
        except collector.ReportError:
            print("PASS Gst collector rejects symlink", flush=True)
        else:
            raise AssertionError("collector followed a symlink")

        hardlink = root / "hardlink.json"
        os.link(report, hardlink)
        try:
            collector.load_report(report, expected_frames=(31,), expected_copy=True)
        except collector.ReportError:
            print("PASS Gst collector rejects multiple links", flush=True)
        else:
            raise AssertionError("collector accepted a multiply linked report")
        hardlink.unlink()

        exposed = root / "exposed.json"
        exposed.write_bytes(data)
        exposed.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        try:
            collector.load_report(exposed, expected_frames=(31,), expected_copy=True)
        except collector.ReportError:
            print("PASS Gst collector rejects exposed permissions", flush=True)
        else:
            raise AssertionError("collector accepted exposed permissions")

        cli = subprocess.run(
            [sys.executable, str(HERE / "collector.py"), str(report),
             "--frames", "31", "--copy", "on", "--process-exit-code", "0"],
            text=True, capture_output=True, timeout=30)
        assert cli.returncode == 0, cli.stdout + cli.stderr
        assert json.loads(cli.stdout)["schema"] == collector.SCHEMA
        print("PASS Gst collector CLI round trip", flush=True)


def mutations(root: Path, build: Path) -> None:
    cases = [
        ("real-stream-owner-arm", "gstv4l2codech265dec.c",
         "if (!gst_hevc_runner_arm (self))",
         "if (FALSE && !gst_hevc_runner_arm (self))",
         "runner-actual-arm", "client->content_callsite"),
        ("pre-allocation-arm", "gstv4l2codech265dec.c",
         "if (!gst_hevc_runner_arm (self))\n"
         "    return GST_FLOW_ERROR;\n\n"
         "  if (!gst_v4l2_codec_h265_dec_ensure_bitstream (self))",
         "if (!gst_v4l2_codec_h265_dec_ensure_bitstream (self))\n"
         "    return GST_FLOW_ERROR;\n\n"
         "  if (!gst_hevc_runner_arm (self))",
         "runner-actual-arm", "client->content_callsite"),
        ("post-publication-result", "gstv4l2codech265dec.c",
         "return gst_hevc_runner_after_output (self, ret);",
         "return ret;", "runner-copy-on", "status, expected"),
        ("finish-before-publish", "gst-runner.inc",
         "if (!gst_hevc_callsite_finish (GST_H265_DECODER (self))) {\n"
         "    if (json)",
         "if (FALSE && !gst_hevc_callsite_finish (GST_H265_DECODER (self))) {\n"
         "    if (json)",
         "runner-copy-on", "!client->content_callsite"),
        ("fail-closed-publication", "gst-runner.inc",
         "if (syscall (SYS_renameat2, AT_FDCWD, temporary, AT_FDCWD, path,\n"
         "          RENAME_NOREPLACE) < 0)",
         "if (FALSE && syscall (SYS_renameat2, AT_FDCWD, temporary, AT_FDCWD, path,\n"
         "          RENAME_NOREPLACE) < 0)",
         "runner-collision", "output (frame) == expected"),
        ("normalized-only", "gst-runner.inc",
         "\\\"capture_index\\\":%u,\\\"copied\\\":%s,\\\"sha256\\\":" ,
         "\\\"raw\\\":%u,\\\"copied\\\":%s,\\\"sha256\\\":" ,
         "runner-copy-on", "capture_index"),
    ]
    directory = root / BASE
    for label, name, before, after, mode, assertion in cases:
        path = directory / name
        original = path.read_text()
        try:
            path.write_text(integration.replace(original, before, after))
            binary = compile_targets(build)
            with tempfile.TemporaryDirectory(prefix="hevc-gst-mutation-") as temp:
                report = Path(temp) / "result.json"
                result = subprocess.run(
                    [str(binary), mode, str(report)], env=integration.ENV,
                    text=True, capture_output=True, timeout=120)
            output = result.stdout + result.stderr
            if (result.returncode != -signal.SIGABRT or assertion not in output or
                    "Sanitizer" in output or "runtime error:" in output):
                raise RuntimeError("wrong mutation failure: " + label + "\n" + output)
            print("PASS named Gst runner mutation " + label, flush=True)
        finally:
            path.write_text(original)
    compile_targets(build)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--native-file", type=Path)
    args = parser.parse_args()
    destination = args.keep.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        parser.error("--keep must name an empty directory")

    root = adapter.source.fetch(destination, args.archive)
    for patch in ("unaligned-io.patch", "gstv4l2decoder-observer.patch"):
        run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
             PARENT / "gst-adapter" / patch], cwd=root)
    for src, dst in (("public-api-test.c", "observer-api-test.c"),
                     ("unaligned-io-test.c", "unaligned-io-test.c")):
        shutil.copyfile(PARENT / "gst-adapter" / src, root / BASE / dst)
    meson = root / BASE / "meson.build"
    meson.write_text(meson.read_text() + "\n" +
                     (PARENT / "gst-adapter/test-meson.build").read_text())
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
         PARENT / "integration/gst-integration.patch"], cwd=root)
    integration.sync(root, "gst")
    integration.fixture(root, "gst")
    integration.prepare_gst_fixture(root)
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
         PARENT / "gst-callsite/client-hook.patch"], cwd=root)
    callsite.configure_fixture(root)
    for name in ("gst-runner.h", "gst-runner.inc"):
        shutil.copyfile(HERE / name, root / BASE / name)
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
         HERE / "gst-runner.patch"], cwd=root)
    configure_fixture(root)

    archive = args.archive.resolve() if args.archive else destination / "source.tar.gz"
    for sanitizer, label in (("address,undefined", "asan-ubsan"),
                             ("thread", "tsan")):
        build = destination / label
        adapter.configure(root, build, sanitizer, args.native_file)
        binary = compile_targets(build)
        adapter.pinned_linkage(build, binary)
        adapter.pinned_linkage(build, build / BASE / "libgstv4l2codecs.so")
        positive(binary, sanitizer)
        callsite.positive(build / BASE / "callsite-api", sanitizer)
        integration.positive(build / BASE / "content-api", "gst", sanitizer)
        adapter.positive(build, sanitizer)
        if label == "asan-ubsan":
            collector_checks(binary)
            mutations(root, build)
        for name in ("libgstv4l2codecs.so", "runner-api"):
            artifact = build / BASE / name
            print(label, name, "sha256", adapter.source.digest(artifact), flush=True)
    print("source archive sha256", adapter.source.digest(archive), flush=True)
    print("runner patch sha256", adapter.source.digest(HERE / "gst-runner.patch"), flush=True)
    print("PASS real Gst runner/result transport; synthetic syscalls only", flush=True)


if __name__ == "__main__":
    main()
