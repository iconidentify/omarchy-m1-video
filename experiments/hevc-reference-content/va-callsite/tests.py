#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build pinned FFmpeg and execute its real VA output hook without a device."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
PIN = "bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa"
ARCHIVE_SHA = "fb1931fd4eb29297ee1c1017a24f800c4d8fbea35b4f2aaeb28308a48a9149b4"
CASES = (
    "default-off", "success-off", "success-on", "invalid-display",
    "wrong-origin", "late-arm", "threaded-reject", "bad-abi", "duplicate",
    "foreign-owner", "wrong-surface", "receipt-mismatch", "end-retry",
    "snapshot-failure", "flush-retry", "uninit-retry", "incomplete",
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
        tree / "configure", "--disable-programs", "--disable-doc",
        "--disable-network", "--disable-autodetect", "--disable-everything",
        "--disable-x86asm",
        "--enable-avcodec", "--enable-avutil", "--enable-decoder=hevc",
        "--enable-parser=hevc", "--enable-vaapi",
        "--enable-hwaccel=hevc_vaapi", "--enable-libdrm",
        "--enable-pthreads", "--enable-pic", "--disable-stripping",
        "--disable-optimizations", "--enable-debug=3",
        "--extra-cflags=" + flags, "--extra-ldflags=" + flags,
    ], cwd=build)
    run(["make", "-j", "2", "libavcodec/libavcodec.a",
         "libavutil/libavutil.a"], cwd=build)
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


def execute(binary: Path, fake: Path, case: str):
    return subprocess.run([str(binary), str(fake), case], env=ENV,
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
        print("PASS actual FFmpeg init/output publication call sites", flush=True)

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
