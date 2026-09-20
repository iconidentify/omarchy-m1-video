#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build pinned FFmpeg and execute its real VA output hook without a device."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

from collector import (OUTPUT_KEYS, ReportError, collect_report, load_report,
                       parse_report)

HERE = Path(__file__).resolve().parent
PIN = "bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa"
ARCHIVE_SHA = "fb1931fd4eb29297ee1c1017a24f800c4d8fbea35b4f2aaeb28308a48a9149b4"
CASES = (
    "default-off", "success-off", "success-on", "invalid-display",
    "wrong-origin", "late-arm", "threaded-reject", "bad-abi", "duplicate",
    "foreign-owner", "wrong-surface", "receipt-mismatch", "end-retry",
    "snapshot-failure", "flush-retry", "uninit-retry", "incomplete",
    "post-finish-output", "close-retry",
)
REPORT_FAILURE_CASES = (
    "report-default-off", "report-incomplete", "report-sticky",
    "report-end-persistent", "report-close-failure", "report-write-failure",
    "foreign-report",
)
ENV = os.environ | {
    "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
    "UBSAN_OPTIONS": "halt_on_error=1",
    "TSAN_OPTIONS": "halt_on_error=1:exitcode=66",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(command, *, timeout=1200, **kwargs):
    command = list(map(str, command))
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=timeout, env=ENV, **kwargs)
    if result.returncode:
        raise RuntimeError(" ".join(command) + "\n" +
                           (result.stdout + result.stderr)[-18000:])
    return result.stdout


def fetch_tree(root: Path, archive_path: Path | None) -> Path:
    if archive_path:
        archive = archive_path.read_bytes()
    else:
        url = f"https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/{PIN}"
        archive = urllib.request.urlopen(url, timeout=60).read()
    if sha(archive) != ARCHIVE_SHA:
        raise ValueError("FFmpeg archive identity mismatch")
    archive_file = root / "ffmpeg.tar.gz"
    archive_file.write_bytes(archive)
    with tarfile.open(archive_file) as stream:
        stream.extractall(root, filter="data")
    tree = root / ("FFmpeg-" + PIN)
    run(["patch", "--fuzz=0", "-p1", "-i",
         HERE / "ffmpeg-n9.0.1-va-observer-callsite.patch"], cwd=tree)
    print("ffmpeg", PIN, "archive_sha256", sha(archive), flush=True)
    return tree


def sanitizer_flags(sanitizer: str) -> str:
    return (f"-fsanitize={sanitizer} -fno-sanitize-recover=all "
            "-fno-omit-frame-pointer")


def configure_and_build(tree: Path, root: Path, sanitizer: str) -> Path:
    label = sanitizer.replace(",", "-")
    build = root / ("build-" + label)
    build.mkdir()
    flags = sanitizer_flags(sanitizer)
    run([
        tree / "configure", "--disable-doc",
        "--disable-network", "--disable-autodetect", "--disable-everything",
        "--disable-x86asm",
        "--enable-ffmpeg", "--enable-avcodec", "--enable-avformat",
        "--enable-avfilter", "--enable-avutil", "--enable-swscale",
        "--enable-swresample", "--enable-decoder=hevc",
        "--enable-parser=hevc", "--enable-vaapi",
        "--enable-hwaccel=hevc_vaapi", "--enable-libdrm",
        "--enable-pthreads", "--enable-pic", "--disable-stripping",
        "--disable-optimizations", "--enable-debug=3",
        "--extra-cflags=" + flags, "--extra-ldflags=" + flags,
    ], cwd=build)
    run(["make", "-j", "2", "ffmpeg", "libavcodec/libavcodec.a",
         "libavutil/libavutil.a"], cwd=build)
    version = run([build / "ffmpeg", "-hide_banner", "-version"], cwd=build)
    if "ffmpeg version 9.0.1" not in version:
        raise RuntimeError("built ffmpeg does not report the pinned release identity")
    return build


def configured_libs(build: Path) -> list[str]:
    config = (build / "ffbuild/config.mak").read_text()
    values: list[str] = []
    for name in ("EXTRALIBS-avcodec", "EXTRALIBS-avutil", "EXTRALIBS"):
        match = re.search(r"^" + re.escape(name) + r"=(.*)$", config, re.M)
        if match:
            values.extend(shlex.split(match.group(1)))
    values.extend(["-ldl", "-pthread"])
    return list(dict.fromkeys(values))


def build_fixture(tree: Path, build: Path, sanitizer: str,
                  label: str = "baseline") -> tuple[Path, Path]:
    flags = sanitizer_flags(sanitizer).split()
    fake = build / ("fake-driver-" + label + ".so")
    binary = build / ("callsite-" + label)
    run(["cc", "-shared", "-fPIC", "-std=gnu11", "-g", "-O1", *flags,
         HERE / "fake-driver.c", "-pthread", "-lva", "-o", fake])
    run(["cc", "-std=gnu11", "-g", "-O1", *flags,
         "-I" + str(tree), "-I" + str(build), HERE / "callsite-test.c",
         "-Wl,--start-group", build / "libavcodec/libavcodec.a",
         build / "libavutil/libavutil.a", "-Wl,--end-group",
         *configured_libs(build), "-o", binary])
    return fake, binary


def execute(binary: Path, fake: Path, case: str, report: Path | None = None):
    command = [str(binary), str(fake), case]
    if report is not None:
        command.append(str(report))
    return subprocess.run(command, env=ENV,
                          text=True, capture_output=True, timeout=30)


def positive(fake: Path, binary: Path, sanitizer: str) -> None:
    for case in CASES:
        result = execute(binary, fake, case)
        diagnostic = result.stdout + result.stderr
        if (result.returncode or "Sanitizer" in diagnostic or
                "runtime error:" in diagnostic or
                f"PASS FFmpeg VA callsite {case}" not in result.stdout):
            raise RuntimeError(f"{sanitizer} {case}\n{diagnostic}")
        print(sanitizer, result.stdout.strip(), flush=True)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        records: dict[str, bytes] = {}
        for case, copied in (("report-off", False), ("report-on", True)):
            report = root / (case + ".json")
            result = execute(binary, fake, case, report)
            diagnostic = result.stdout + result.stderr
            if (result.returncode or "Sanitizer" in diagnostic or
                    "runtime error:" in diagnostic or
                    f"PASS FFmpeg VA callsite {case}" not in result.stdout):
                raise RuntimeError(f"{sanitizer} {case}\n{diagnostic}")
            document = collect_report(report, process_exit_code=result.returncode,
                                      expected_outputs=(1, 3),
                                      expected_copy=copied)
            if any(set(output) != OUTPUT_KEYS for output in document["outputs"]):
                raise AssertionError("collector accepted a non-normalized output")
            records[case] = report.read_bytes()
            print(sanitizer, result.stdout.strip(), flush=True)

            try:
                collect_report(report, process_exit_code=1,
                               expected_outputs=(1, 3), expected_copy=copied)
            except ReportError:
                print(sanitizer, "PASS collector rejects failed process", flush=True)
            else:
                raise RuntimeError("collector accepted a failed FFmpeg process")

        symlink = root / "report-link.json"
        symlink.symlink_to(root / "report-on.json")
        try:
            load_report(symlink, expected_outputs=(1, 3), expected_copy=True)
        except ReportError:
            print(sanitizer, "PASS collector rejects symlink", flush=True)
        else:
            raise RuntimeError("collector accepted a symlink report")

        cli_output = run([
            sys.executable, HERE / "collector.py", root / "report-on.json",
            "--outputs", "1,3", "--copy", "on",
            "--process-exit-code", "0",
        ], timeout=30)
        if json.loads(cli_output) != json.loads(records["report-on"]):
            raise RuntimeError("collector CLI changed the normalized record")
        print(sanitizer, "PASS collector CLI", flush=True)

        repeat = root / "report-off-repeat.json"
        result = execute(binary, fake, "report-off", repeat)
        if result.returncode or repeat.read_bytes() != records["report-off"]:
            raise RuntimeError(f"{sanitizer} report is not deterministic\n" +
                               result.stdout + result.stderr)
        print(sanitizer, "PASS deterministic normalized report", flush=True)

        for case in REPORT_FAILURE_CASES:
            report = root / (case + ".json")
            result = execute(binary, fake, case, report)
            diagnostic = result.stdout + result.stderr
            if (result.returncode or report.exists() or
                    "Sanitizer" in diagnostic or "runtime error:" in diagnostic or
                    f"PASS FFmpeg VA callsite {case}" not in result.stdout):
                raise RuntimeError(f"{sanitizer} {case}\n{diagnostic}")
            print(sanitizer, result.stdout.strip(), flush=True)

        preexisting = root / "report-preexisting.json"
        preexisting.write_text("sentinel\n")
        result = execute(binary, fake, "report-preexisting", preexisting)
        if (result.returncode or preexisting.read_text() != "sentinel\n" or
                "PASS FFmpeg VA callsite report-preexisting" not in result.stdout):
            raise RuntimeError(f"{sanitizer} report-preexisting\n" +
                               result.stdout + result.stderr)
        print(sanitizer, result.stdout.strip(), flush=True)
        collector_negative_tests(records["report-on"])


def collector_negative_tests(valid: bytes) -> None:
    checks = []

    raw = json.loads(valid)
    raw["outputs"][0]["raw_bytes"] = "00"
    checks.append(("raw-field", raw))

    digest = json.loads(valid)
    digest["outputs"][0]["sha256"] = None
    checks.append(("missing-digest", digest))

    duplicate = json.loads(valid)
    duplicate["outputs"][1]["output_ordinal"] = duplicate["outputs"][0]["output_ordinal"]
    checks.append(("duplicate-ordinal", duplicate))

    mixed_session = json.loads(valid)
    session = mixed_session["outputs"][1]["session"]
    mixed_session["outputs"][1]["session"] = (
        ("0" if session[0] != "0" else "1") + session[1:])
    checks.append(("mixed-session", mixed_session))

    for label, value in checks:
        encoded = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        try:
            parse_report(encoded)
        except ReportError:
            print("PASS collector rejection", label, flush=True)
        else:
            raise RuntimeError("collector accepted " + label)

    duplicate_key = valid.replace(b'"count":2', b'"count":2,"count":2', 1)
    try:
        parse_report(duplicate_key)
    except ReportError:
        print("PASS collector rejection duplicate-key", flush=True)
    else:
        raise RuntimeError("collector accepted a duplicate JSON key")


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("mutation drift: " + old)
    return text.replace(old, new)


def assert_actual_callsites(tree: Path) -> None:
    receive = (tree / "libavcodec/hevc/hevcdec.c").read_text()
    output = receive.index("do_output:")
    dequeue = receive.index("av_container_fifo_read", output)
    observe = receive.index("ff_vaapi_decode_observer_output(avctx, frame)", dequeue)
    cleanup = receive.index("av_frame_unref(frame)", observe)
    publish = receive.index("return 0;", observe)
    if not (dequeue < observe < cleanup < publish):
        raise AssertionError("observer/failed-frame cleanup is not between dequeue and publication")

    start = (tree / "libavcodec/vaapi_hevc.c").read_text()
    function = start.index("static int vaapi_hevc_start_frame")
    arm = start.index("ff_vaapi_decode_observer_arm", function)
    surface = start.index("pic->pic.output_surface", function)
    if not (function < arm < surface):
        raise AssertionError("observer session is not armed before first VA submission")

    decoder = (tree / "fftools/ffmpeg_dec.c").read_text()
    worker = decoder.index("static int decoder_thread")
    report = decoder.index("ff_vaapi_decode_observer_write_report(dp->dec_ctx", worker)
    finish = decoder.index("\nfinish:", report)
    free = decoder.index("avcodec_free_context(&dp->dec_ctx)", finish)
    if not (worker < report < finish < free):
        raise AssertionError("decoder worker does not publish before codec-context free")
    declaration = decoder.index("static int dec_open")
    open_function = decoder.index("static int dec_open", declaration + 1)
    pair = decoder.index("!!observer_outputs != !!o->va_observer_report", open_function)
    codec_open = decoder.index("avcodec_open2", open_function)
    if not (open_function < pair < codec_open):
        raise AssertionError("FFmpeg does not fail closed on unpaired report options")

    demux = (tree / "fftools/ffmpeg_demux.c").read_text()
    option = (tree / "fftools/ffmpeg_opt.c").read_text()
    if ("&o->va_observer_reports" not in demux or
            '"va_observer_report"' not in option):
        raise AssertionError("per-stream report option is not wired to DecoderOpts")
    duplicate = "ds->dec_opts.va_observer_report = av_strdup(va_observer_report)"
    release = "av_freep(&ds->dec_opts.va_observer_report)"
    if demux.count(duplicate) != 1 or demux.count(release) != 1:
        raise AssertionError("the demuxer's report-path copy is not made and released once")
    if not (demux.index("static void ist_free") < demux.index(release) <
            demux.index("static int ist_add") < demux.index(duplicate)):
        raise AssertionError("the demuxer does not own the report path across option teardown")

    implementation = (tree / "libavcodec/vaapi_decode.c").read_text()
    serializer = implementation.index("static int vaapi_observer_report_json")
    writer = implementation.index("static int vaapi_observer_write_all", serializer)
    body = implementation[serializer:writer]
    if "state->pool" in body or "->bytes" in body or "receipt" in body:
        raise AssertionError("report serializer can reach non-normalized observer storage")
    if ("mkostemp" not in implementation or "renameat2(" not in implementation or
            "RENAME_NOREPLACE" not in implementation or
            "unlink(temporary)" not in implementation):
        raise AssertionError("report publication is not exclusive and atomic")


def mutations(tree: Path, build: Path) -> None:
    path = tree / "libavcodec/vaapi_decode.c"
    original = path.read_text()
    cases = [
        ("driver-origin",
         "state->driver_handle = dlopen(origin.dli_fname,",
         'state->driver_handle = dlopen("libva.so.2",',
         "success-off", 'ff_vaapi_decode_observer_arm(&f.avctx, "1,3", copy) == 0'),
        ("abi",
         "if (state->abi() != VA_OBSERVER_ABI)", "if (false)",
         "bad-abi", 'ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) < 0'),
        ("open-before-submit",
         "ctx->va_context == VA_INVALID_ID || ctx->observer_issued)",
         "ctx->va_context == VA_INVALID_ID)",
         "late-arm", 'ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) < 0'),
        ("single-thread-owner",
         "if (avctx->active_thread_type || avctx->thread_count != 1)",
         "if (false)",
         "threaded-reject", 'ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) < 0'),
        ("owner-thread-check",
         "if (!pthread_equal(state->owner, pthread_self()) || state->closed ||",
         "if (false || state->closed ||",
         "foreign-owner", "call.ret < 0"),
        ("selected-surface",
         "VA_STATUS_SUCCESS || target.surface != surface)",
         "VA_STATUS_SUCCESS)",
         "wrong-surface", "counts.select == 1 && !counts.begin && !counts.end"),
        ("duplicate-selection",
         "if (outputs[i] == output)", "if (false && outputs[i] == output)",
         "duplicate", 'ff_vaapi_decode_observer_arm(&f.avctx, "2,2", 0) < 0'),
        ("lease-release",
         "if (end_status != VA_STATUS_SUCCESS) {\n"
         "        state->failed = true;\n"
         "        return AVERROR(EIO);\n"
         "    }\n"
         "    state->active = false;\n"
         "    av_frame_unref(state->held_frame);",
         "if (end_status != VA_STATUS_SUCCESS) {\n"
         "        state->failed = true;\n"
         "        return AVERROR(EIO);\n"
         "    }\n"
         "    /* mutation: retain active lease state after native end */\n"
         "    av_frame_unref(state->held_frame);",
         "success-off", "output(&f, 42) == 0"),
        ("failed-result",
         "if (!state || state->failed || !state->finished || !state->closed || state->active ||",
         "if (!state || false || !state->finished || !state->closed || state->active ||",
         "post-finish-output", "ff_vaapi_decode_observer_result(&f.avctx, &result) < 0"),
    ]
    for label, old, new, case, assertion in cases:
        try:
            path.write_text(replace_once(original, old, new))
            run(["make", "-j", "2", "libavcodec/libavcodec.a"], cwd=build)
            fake, binary = build_fixture(tree, build, "address,undefined",
                                         "mutation-" + label)
            result = execute(binary, fake, case)
            diagnostic = result.stdout + result.stderr
            if (result.returncode != -signal.SIGABRT or assertion not in diagnostic or
                    "Sanitizer" in diagnostic or "runtime error:" in diagnostic):
                raise RuntimeError("semantic mutation not distinguished: " + label +
                                   "\n" + diagnostic)
            print("PASS semantic FFmpeg mutation", label, flush=True)
        finally:
            path.write_text(original)
            run(["make", "-j", "2", "libavcodec/libavcodec.a"], cwd=build)

    receive_path = tree / "libavcodec/hevc/hevcdec.c"
    receive = receive_path.read_text()
    try:
        receive_path.write_text(replace_once(
            receive,
            "        ret = ff_vaapi_decode_observer_output(avctx, frame);\n"
            "        if (ret < 0) {\n"
            "            av_frame_unref(frame);\n"
            "            return ret;\n"
            "        }\n",
            "        /* mutation: publish without observation */\n"))
        try:
            assert_actual_callsites(tree)
        except (AssertionError, ValueError):
            print("PASS semantic FFmpeg mutation output-publication-order", flush=True)
        else:
            raise RuntimeError("output-publication-order mutation was not distinguished")
    finally:
        receive_path.write_text(receive)

    report_mutations(tree, build)


def report_mutations(tree: Path, build: Path) -> None:
    path = tree / "libavcodec/vaapi_decode.c"
    original = path.read_text()

    try:
        path.write_text(replace_once(
            original,
            '"{\\"schema\\":\\"omarchy.hevc.va-observer-result/v1\\","',
            '"{\\"schema\\":\\"omarchy.hevc.va-observer-result/v1\\",'
            '\\"raw_bytes\\":\\"00\\","'))
        run(["make", "-j", "2", "libavcodec/libavcodec.a"], cwd=build)
        fake, binary = build_fixture(tree, build, "address,undefined",
                                     "mutation-normalized-only")
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            result = execute(binary, fake, "report-off", report)
            if result.returncode:
                raise RuntimeError("normalized-only mutation failed for unrelated reason\n" +
                                   result.stdout + result.stderr)
            try:
                load_report(report, expected_outputs=(1, 3), expected_copy=False)
            except ReportError:
                print("PASS semantic FFmpeg mutation normalized-only", flush=True)
            else:
                raise RuntimeError("normalized-only mutation was not distinguished")
    finally:
        path.write_text(original)
        run(["make", "-j", "2", "libavcodec/libavcodec.a"], cwd=build)

    try:
        path.write_text(replace_once(
            original,
            "if (renameat2(AT_FDCWD, temporary, AT_FDCWD, path,\n"
            "                  RENAME_NOREPLACE) < 0)",
            "if (false)"))
        run(["make", "-j", "2", "libavcodec/libavcodec.a"], cwd=build)
        fake, binary = build_fixture(tree, build, "address,undefined",
                                     "mutation-exclusive-publish")
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            report.write_text("sentinel\n")
            result = execute(binary, fake, "report-preexisting", report)
            diagnostic = result.stdout + result.stderr
            assertion = "ff_vaapi_decode_observer_write_report(&f.avctx, report) < 0"
            if (result.returncode != -signal.SIGABRT or assertion not in diagnostic or
                    "Sanitizer" in diagnostic or "runtime error:" in diagnostic):
                raise RuntimeError("exclusive-publish mutation not distinguished\n" +
                                   diagnostic)
        print("PASS semantic FFmpeg mutation exclusive-publish", flush=True)
    finally:
        path.write_text(original)
        run(["make", "-j", "2", "libavcodec/libavcodec.a"], cwd=build)

    try:
        owner_mutation = replace_once(
            original,
            "    if (!pthread_equal(state->owner, pthread_self()))\n"
            "        return AVERROR(EPERM);",
            "    if (false)\n"
            "        return AVERROR(EPERM);")
        owner_mutation = replace_once(
            owner_mutation,
            "        !pthread_equal(state->owner, pthread_self()))",
            "        false)")
        path.write_text(owner_mutation)
        run(["make", "-j", "2", "libavcodec/libavcodec.a"], cwd=build)
        fake, binary = build_fixture(tree, build, "address,undefined",
                                     "mutation-report-owner")
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            result = execute(binary, fake, "foreign-report", report)
            diagnostic = result.stdout + result.stderr
            if (result.returncode != -signal.SIGABRT or "call.ret < 0" not in diagnostic or
                    "Sanitizer" in diagnostic or "runtime error:" in diagnostic):
                raise RuntimeError("report-owner mutation not distinguished\n" + diagnostic)
        print("PASS semantic FFmpeg mutation report-owner", flush=True)
    finally:
        path.write_text(original)
        run(["make", "-j", "2", "libavcodec/libavcodec.a"], cwd=build)

    worker_path = tree / "fftools/ffmpeg_dec.c"
    worker = worker_path.read_text()
    try:
        worker_path.write_text(replace_once(
            worker,
            "        ret = ff_vaapi_decode_observer_write_report(dp->dec_ctx,\n"
            "                                                     dp->va_observer_report);",
            "        /* mutation: free without publishing the observer result */\n"
            "        ret = 0;"))
        try:
            assert_actual_callsites(tree)
        except (AssertionError, ValueError):
            print("PASS semantic FFmpeg mutation worker-before-free", flush=True)
        else:
            raise RuntimeError("worker-before-free mutation was not distinguished")
    finally:
        worker_path.write_text(worker)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path,
                        help="optional cached FFmpeg archive; exact SHA still required")
    parser.add_argument("--keep", type=Path,
                        help="retain a fresh build/evidence directory")
    parser.add_argument("--skip-tsan", action="store_true",
                        help="developer shortcut; not accepted final evidence")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        root = args.keep or Path(temporary)
        root.mkdir(parents=True, exist_ok=True)
        if list(root.iterdir()):
            raise ValueError("build/evidence directory must be empty")
        tree = fetch_tree(root, args.archive)
        assert_actual_callsites(tree)
        print("PASS actual FFmpeg init/output/report-before-free call sites", flush=True)

        sanitizers = ["address,undefined"]
        if not args.skip_tsan:
            sanitizers.append("thread")
        builds = {}
        for sanitizer in sanitizers:
            build = configure_and_build(tree, root, sanitizer)
            builds[sanitizer] = build
            fake, binary = build_fixture(tree, build, sanitizer)
            print(sanitizer, "ffmpeg_vaapi_object_sha256",
                  sha((build / "libavcodec/vaapi_decode.o").read_bytes()), flush=True)
            print(sanitizer, "ffmpeg_program_sha256",
                  sha((build / "ffmpeg").read_bytes()), flush=True)
            print(sanitizer, "fixture_sha256", sha(binary.read_bytes()), flush=True)
            positive(fake, binary, sanitizer)
        mutations(tree, builds["address,undefined"])
        print("ffmpeg_patch_sha256",
              sha((HERE / "ffmpeg-n9.0.1-va-observer-callsite.patch").read_bytes()),
              flush=True)
        print("driver_abi_patch_sha256",
              sha((HERE / "driver-client-abi.patch").read_bytes()), flush=True)


if __name__ == "__main__":
    main()
