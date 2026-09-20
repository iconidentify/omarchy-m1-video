#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Stage the complete pinned HEVC observer stack; never install or load it."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import manifest

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
REPO = PARENT.parent.parent
GST_BASE = Path("subprojects/gst-plugins-bad/sys/v4l2codecs")
FFMPEG_PIN = "bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa"
FFMPEG_ARCHIVE_SHA = "fb1931fd4eb29297ee1c1017a24f800c4d8fbea35b4f2aaeb28308a48a9149b4"
VA_PIN = "c77e7b566f7baf9c7a2aad797e62c9aa578d9687"
VA_ARCHIVE_SHA = "a82f316c0468d3a5490bcfc33c8a876eab0e2b55ec1416b88f7f920535fc5bf4"
GST_PIN = "070125524a8422e29d3b69a372ed4f62fd343ffa"
GST_ARCHIVE_SHA = "1def36bd4c68f13cb731740d0cd2697d858c073e674ef54726e97ee245639a44"
KERNEL_PIN = "94fb23346d522edf53722357c426a3e58030beea"
KERNEL_SOURCE_SHA = "a16ebf3b486144d45ed91122ed78040dc64bbaa9901a312669e11c31bc8ff7d3"
RECORDER_MODULE_SHA = "7a00ffa548e89d4316eb2b1454c7e153128906f099729efb58b77c26fadcdf02"
ORACLE_SHA = "d98837f95faa669a8c01f16caad7c986181bdc03cbce80c8ced26ec1697f4310"
UAPI_SHA = "c86036741a6b878cc2a28796c2fdd1ff18488ccdd274ea662cfadc934569d9fb"
TARGET_EVIDENCE_SHA = "b7b37270f6336f4096dd018354178c7e06c98da335b2ce02866b530afba3814e"


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load " + str(path))
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


def run(command: list[object], *, cwd: Path | None = None,
        timeout: int = 3600, record: list[dict] | None = None) -> str:
    values = [str(item) for item in command]
    if record is not None:
        record.append({"argv": values, "cwd": str((cwd or Path.cwd()).resolve())})
    result = subprocess.run(values, cwd=cwd, text=True, capture_output=True,
                            timeout=timeout)
    if result.returncode:
        raise RuntimeError(" ".join(values) + "\n" +
                           (result.stdout + result.stderr)[-20000:])
    return result.stdout


def checked_archive(path: Path, expected: str, name: str) -> Path:
    path = path.resolve(strict=True)
    if manifest.digest(path) != expected:
        raise ValueError(name + " archive identity mismatch")
    return path


def checked_file(path: Path, expected: str, name: str) -> Path:
    path = path.resolve(strict=True)
    if not path.is_file() or manifest.digest(path) != expected:
        raise ValueError(name + " identity mismatch")
    return path


def patch_record(order: int, component: str, path: Path) -> dict[str, object]:
    path = path.resolve(strict=True)
    return {"order": order, "component": component, "path": str(path),
            "sha256": manifest.digest(path)}


def apply(tree: Path, patch: Path, record: list[dict] | None = None) -> None:
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i", patch.resolve()], cwd=tree,
        record=record)


def build_va(root: Path, archive: Path, jobs: int,
             record: list[dict]) -> tuple[Path, list[Path]]:
    adapter = module("deployment_va_adapter", PARENT / "va-adapter/tests.py")
    integration = module("deployment_integration", PARENT / "integration/tests.py")
    source_root = root / "va-source"
    source_root.mkdir()
    tree = adapter.fetch_tree(source_root, archive)
    apply(tree, PARENT / "integration/va-integration.patch", record)
    apply(tree, PARENT / "va-callsite/driver-client-abi.patch", record)
    integration.sync(tree, "va")
    build = root / "va-build"
    run(["meson", "setup", build, tree, "--buildtype=release",
         "--wrap-mode=nodownload", "-Dc_link_args=-Wl,--build-id"], record=record)
    run(["meson", "compile", "-C", build, "-j", jobs,
         "v4l2_request_drv_video"], record=record)
    artifact = build / "src/v4l2_request_drv_video.so"
    symbols = run(["nm", "-D", artifact])
    for symbol in ("v4l2r_observer_abi", "v4l2r_content_snapshot",
                   "v4l2r_observer_result"):
        if symbol not in symbols:
            raise ValueError("VA artifact lacks observer symbol: " + symbol)
    return artifact, [PARENT / "va-adapter/driver-observer.patch",
                      PARENT / "integration/va-integration.patch",
                      PARENT / "va-callsite/driver-client-abi.patch"]


def build_ffmpeg(root: Path, archive: Path, jobs: int,
                 record: list[dict]) -> tuple[Path, list[Path]]:
    calls = module("deployment_va_callsite", PARENT / "va-callsite/tests.py")
    source_root = root / "ffmpeg-source"
    source_root.mkdir()
    tree = calls.fetch_tree(source_root, archive)
    build = root / "ffmpeg-build"
    build.mkdir()
    run([
        tree / "configure", "--disable-doc", "--disable-network",
        "--enable-vaapi", "--enable-libdrm", "--enable-pthreads",
        "--disable-stripping", "--enable-debug=3",
        "--extra-ldflags=-Wl,--build-id",
    ], cwd=build, record=record)
    run(["make", "-j", jobs, "ffmpeg"], cwd=build, record=record)
    artifact = build / "ffmpeg"
    version = run([artifact, "-hide_banner", "-version"])
    if "ffmpeg version 9.0.1" not in version:
        raise ValueError("staged FFmpeg identity mismatch")
    strings = run(["strings", artifact])
    for token in ("va_observer_outputs", "va_observer_copy", "va_observer_report"):
        if token not in strings:
            raise ValueError("FFmpeg artifact lacks observer option: " + token)
    return artifact, [PARENT / "va-callsite/ffmpeg-n9.0.1-va-observer-callsite.patch"]


def build_gst(root: Path, archive: Path, jobs: int,
              native_file: Path | None,
              record: list[dict]) -> tuple[dict[str, Path], list[Path]]:
    sys.path.insert(0, str(PARENT / "gst-adapter"))
    adapter = module("deployment_gst_adapter", PARENT / "gst-adapter/tests.py")
    integration = module("deployment_gst_integration", PARENT / "integration/tests.py")
    source_root = root / "gst-source"
    source_root.mkdir()
    tree = adapter.source.fetch(source_root, archive)
    patches = [
        PARENT / "gst-adapter/unaligned-io.patch",
        PARENT / "gst-adapter/gstv4l2decoder-observer.patch",
        PARENT / "integration/gst-integration.patch",
        PARENT / "gst-callsite/client-hook.patch",
        PARENT / "gst-runner/gst-runner.patch",
        PARENT / "gst-eligibility/gst-eligibility.patch",
    ]
    apply(tree, patches[0], record); apply(tree, patches[1], record)
    apply(tree, patches[2], record)
    integration.sync(tree, "gst")
    for name in ("gst-callsite.h", "gst-callsite.inc", "gst-callsite-native.inc"):
        shutil.copyfile(PARENT / "gst-callsite" / name, tree / GST_BASE / name)
    apply(tree, patches[3], record)
    for name in ("gst-runner.h", "gst-runner.inc"):
        shutil.copyfile(PARENT / "gst-runner" / name, tree / GST_BASE / name)
    apply(tree, patches[4], record); apply(tree, patches[5], record)
    build = root / "gst-build"
    command: list[object] = [
        "meson", "setup", build, tree, "--buildtype=release",
        "-Dauto_features=disabled", "-Dbase=enabled", "-Dbad=enabled",
        "-Dgood=disabled", "-Dugly=disabled", "-Dtests=disabled",
        "-Dgst-plugins-base:videoconvertscale=enabled",
        "-Dgst-plugins-bad:v4l2codecs=enabled",
        "-Dgst-plugins-bad:videoparsers=enabled",
        "-Db_lundef=true", "-Dc_link_args=-Wl,--build-id",
    ]
    if native_file:
        command += ["--native-file", native_file.resolve(strict=True)]
    run(command, record=record)
    run(["meson", "compile", "-C", build, "-j", jobs,
         "gst-launch-1.0", "gstv4l2codecs", "gstvideoparsersbad",
         "gstvideoconvertscale", "gstcoreelements"], record=record)
    artifacts = {
        "gst_launch": build / "subprojects/gstreamer/tools/gst-launch-1.0",
        "gst_plugin": build / GST_BASE / "libgstv4l2codecs.so",
        "gst_parser": (build / "subprojects/gst-plugins-bad/gst/videoparsers/"
                       "libgstvideoparsersbad.so"),
        "gst_videoconvert": (build / "subprojects/gst-plugins-base/gst/"
                             "videoconvertscale/libgstvideoconvertscale.so"),
        "gst_core": (build / "subprojects/gstreamer/plugins/elements/"
                     "libgstcoreelements.so"),
    }
    strings = run(["strings", artifacts["gst_plugin"]])
    for token in ("hevc-observer-frames", "hevc-observer-copy",
                  "hevc-observer-report", "observer-queue"):
        if token not in strings:
            raise ValueError("Gst artifact lacks observer token: " + token)
    return artifacts, patches


def copy_artifact(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source.resolve(strict=True), destination)
    if manifest.digest(source) != manifest.digest(destination):
        raise ValueError("staged copy differs: " + str(source))
    return destination.resolve()


def command_matrix(artifacts: dict[str, Path], corpus: dict[str, dict],
                   targets: list[dict]) -> list[dict]:
    by_key = {(row["client"], row["vector"]): row for row in targets}
    commands: list[dict] = []
    for vector in ("B", "E"):
        source = corpus[vector]["path"]
        for client in ("va", "gst"):
            selected = ",".join(map(str, by_key[(client, vector)]["selectors"]))
            for copied in (False, True):
                name = f"{vector}-{client}-{'on' if copied else 'off'}"
                if client == "va":
                    client_argv = [str(artifacts["ffmpeg"]), "-threads:v:0", "1",
                            "-hwaccel", "vaapi", "-va_observer_outputs:v:0", selected,
                            "-va_observer_copy:v:0", "1" if copied else "0",
                            "-va_observer_report:v:0", "@OMARCHY_OBSERVER_REPORT@",
                            "-i", source, "-vf", "hwdownload,format=nv12,format=yuv420p",
                            "-f", "framemd5", "@OMARCHY_RUN_ROOT@/frames.md5"]
                else:
                    client_argv = [str(artifacts["gst_launch"]), "-e", "filesrc",
                            "location=" + source, "!", "h265parse", "!", "v4l2slh265dec",
                            "hevc-observer-frames=" + selected,
                            "hevc-observer-copy=" + str(copied).lower(),
                            "hevc-observer-report=@OMARCHY_OBSERVER_REPORT@", "!",
                            "videoconvert", "!", "video/x-raw,format=I420", "!",
                            "filesink", "location=@OMARCHY_RUN_ROOT@/output.yuv"]
                environment = {"LC_ALL": "C"}
                if client == "va":
                    environment |= {
                        "LIBVA_DRIVER_NAME": "v4l2_request",
                        "LIBVA_DRIVERS_PATH": str(artifacts["va_driver"].parent),
                    }
                else:
                    environment |= {
                        "GST_PLUGIN_PATH_1_0": str(artifacts["gst_plugin"].parent),
                        "GST_REGISTRY_FORK": "no",
                        "GST_REGISTRY": "@OMARCHY_RUN_ROOT@/gst-registry.bin",
                    }
                argv = [sys.executable, str(artifacts["same_run_supervisor"]),
                        "--root", "@OMARCHY_RUN_ROOT@", "--client", client,
                        "--selectors", selected, "--copy", "on" if copied else "off",
                        "--kernel-run", "@OMARCHY_KERNEL_RUN@", "--deadline", "90",
                        "--uapi", str(artifacts["uapi"]),
                        "--oracle", str(artifacts["oracle"]), "--", *client_argv]
                commands.append({"name": name, "client": client, "vector": vector,
                                 "copy": copied, "environment": environment,
                                 "argv": argv})
    return commands


def plan_document(targets: list[dict]) -> dict:
    controller = module("deployment_campaign", PARENT / "campaign/controller.py")
    by_key = {(row["client"], row["vector"]): row for row in targets}
    plan = controller.build_plan(
        gst_pool_sizes={vector: by_key[("gst", vector)]["gst_pool_size"]
                        for vector in ("B", "E")},
        va_output_counts={vector: by_key[("va", vector)]["output_count"]
                          for vector in ("B", "E")},
        gst_frames={vector: tuple(by_key[("gst", vector)]["selectors"])
                    for vector in ("B", "E")},
        va_outputs={vector: tuple(by_key[("va", vector)]["selectors"])
                    for vector in ("B", "E")},
        last_required_inputs={client: {vector: by_key[(client, vector)]["last_input"]
                                      for vector in ("B", "E")}
                              for client in ("va", "gst")},
        parameter_set_change_inputs={
            vector: tuple(by_key[("gst", vector)]["parameter_set_change_inputs"])
            for vector in ("B", "E")
        },
        run_id="reviewed-at-execution",
    )
    value = json.loads(plan.to_json())
    if not value["valid"]:
        raise ValueError("target plan rejected: " + "; ".join(value["problems"]))
    return value


def tool(command: list[str]) -> str:
    try:
        return run(command, timeout=30).splitlines()[0]
    except RuntimeError:
        result = subprocess.run(command, text=True, capture_output=True, timeout=30)
        text = result.stdout + result.stderr
        if not text.strip():
            raise
        return text.splitlines()[0]


def dependency_records(path: Path) -> list[dict[str, str]]:
    return [manifest.file_record(item) for item in manifest.dependency_closure(path)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--ffmpeg-archive", required=True, type=Path)
    parser.add_argument("--va-archive", required=True, type=Path)
    parser.add_argument("--gst-archive", required=True, type=Path)
    parser.add_argument("--recorder-module", required=True, type=Path)
    parser.add_argument("--targets", required=True, type=Path)
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--oracle", required=True, type=Path)
    parser.add_argument("--uapi", required=True, type=Path)
    parser.add_argument("--native-file", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise ValueError("--root must be empty")
        ff_archive = checked_archive(args.ffmpeg_archive, FFMPEG_ARCHIVE_SHA, "FFmpeg")
        va_archive = checked_archive(args.va_archive, VA_ARCHIVE_SHA, "VA")
        gst_archive = checked_archive(args.gst_archive, GST_ARCHIVE_SHA, "GStreamer")
        recorder_module = checked_file(args.recorder_module, RECORDER_MODULE_SHA,
                                       "corrected paired recorder module")
        oracle = checked_file(args.oracle, ORACLE_SHA, "command oracle")
        uapi = checked_file(args.uapi, UAPI_SHA, "generated UAPI")
        target_evidence = checked_file(args.targets, TARGET_EVIDENCE_SHA,
                                       "campaign target evidence")
        build_commands: list[dict] = []
        ffmpeg, ff_patches = build_ffmpeg(root, ff_archive, args.jobs, build_commands)
        va_driver, va_patches = build_va(root, va_archive, args.jobs, build_commands)
        gst_artifacts, gst_patches = build_gst(
            root, gst_archive, args.jobs, args.native_file, build_commands)
        stage = root / "stage"
        recorder_provenance = REPO / "experiments/hevc-avd-command-trace/corrected-build.json"
        provenance_document = json.loads(recorder_provenance.read_text())
        if provenance_document.get("module_sha256") != RECORDER_MODULE_SHA:
            raise ValueError("corrected recorder provenance drift")
        artifacts = {
            "ffmpeg": copy_artifact(ffmpeg, stage / "bin/ffmpeg"),
            "va_driver": copy_artifact(va_driver, stage / "lib/dri/v4l2_request_drv_video.so"),
            "gst_launch": copy_artifact(gst_artifacts["gst_launch"],
                                        stage / "bin/gst-launch-1.0"),
            "gst_plugin": copy_artifact(gst_artifacts["gst_plugin"],
                                        stage / "lib/gstreamer-1.0/libgstv4l2codecs.so"),
            "gst_parser": copy_artifact(gst_artifacts["gst_parser"],
                                        stage / "lib/gstreamer-1.0/libgstvideoparsersbad.so"),
            "gst_videoconvert": copy_artifact(
                gst_artifacts["gst_videoconvert"],
                stage / "lib/gstreamer-1.0/libgstvideoconvertscale.so"),
            "gst_core": copy_artifact(gst_artifacts["gst_core"],
                                      stage / "lib/gstreamer-1.0/libgstcoreelements.so"),
            "recorder_module": copy_artifact(recorder_module, stage / "modules/apple-avd.ko"),
            "v4l2_tracer": Path(shutil.which("v4l2-tracer") or "").resolve(strict=True),
            "oracle": oracle,
            "uapi": uapi,
            "same_run_supervisor": (PARENT / "same-run/supervisor.py").resolve(strict=True),
            "hwguard": (REPO / "tests/hwguard.py").resolve(strict=True),
            "target_evidence": copy_artifact(target_evidence,
                                              stage / "target-evidence.json"),
            "recorder_provenance": copy_artifact(
                recorder_provenance, stage / "recorder-provenance.json"),
        }
        target_document = json.loads(target_evidence.read_text())
        if type(target_document) is not dict or set(target_document) != {
                "schema", "sources", "derivation", "targets"} or \
                target_document["schema"] != "omarchy.hevc.target-evidence/v1":
            raise ValueError("target evidence schema is invalid")
        target_rows = target_document["targets"]
        if type(target_rows) is not list:
            raise ValueError("target evidence targets must be an array")
        evidence_sha256 = manifest.digest(artifacts["target_evidence"])
        target_rows = [row | {"evidence_sha256": evidence_sha256}
                       for row in target_rows]
        plan = plan_document(target_rows)
        plan_path = stage / "campaign-plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")

        corpus_paths = {
            vector: args.corpus_root / f"RPS_{vector}_qualcomm_5" /
                    f"RPS_{vector}_qualcomm_5" / f"RPS_{vector}_qualcomm_5.bit"
            for vector in ("B", "E")}
        corpus = {vector: {"path": str(path.resolve(strict=True)),
                           "sha256": manifest.digest(path), "bytes": path.stat().st_size,
                           "frames": 300}
                  for vector, path in corpus_paths.items()}
        for vector in ("B", "E"):
            stream = target_document["sources"]["streams"][vector]
            if (stream["sha256"], stream["bytes"]) != \
                    (corpus[vector]["sha256"], corpus[vector]["bytes"]):
                raise ValueError("target evidence corpus drift: " + vector)
        commands = command_matrix(artifacts, corpus, target_rows)

        kernel_files = {
            "apple_avd": artifacts["recorder_module"],
            "videobuf2_common": Path(run(["modinfo", "-n", "videobuf2_common"]).strip()),
            "videobuf2_v4l2": Path(run(["modinfo", "-n", "videobuf2_v4l2"]).strip()),
            "videobuf2_dma_contig": Path(run(["modinfo", "-n", "videobuf2_dma_contig"]).strip()),
        }
        patches = va_patches + ff_patches + gst_patches
        source_info = json.loads((REPO / "experiments/hevc-avd-trace/sources.json").read_text())
        patches += [REPO / row["path"] for row in source_info["patches"]["files"]]
        patches += [REPO / "experiments/hevc-avd-trace/hooks.patch"]
        patches += [REPO / "experiments/hevc-avd-command-trace/kernel" / name
                    for name in ("avd-cmdtrace.c", "avd-cmdtrace.h", "cmd-core.h",
                                 "bounded-snapshot.h", "control-layout.inc")]
        reference_path = (REPO / "experiments/hevc-avd-command-capture/capture-2026-09-17/provenance.json").resolve()
        reference = manifest.file_record(reference_path)
        reference["frames_sha256"] = "6f25d3ad30b99ac0e8ee5c9cf2338b19f89dd3b884ed6607ef438bf8977a8cbf"
        repo_commit = run(["git", "rev-parse", "HEAD"], cwd=REPO).strip()
        dirty = bool(run(["git", "status", "--porcelain"], cwd=REPO).strip())
        compatible = [item.decode() for item in Path("/proc/device-tree/compatible").read_bytes().split(b"\0") if item]
        document = {
            "schema": manifest.SCHEMA,
            "state": "candidate",
            "repo": {"commit": repo_commit, "dirty": dirty},
            "host": {"architecture": os.uname().machine, "compatible": compatible,
                     "kernel_release": os.uname().release,
                     "linux_asahi": run(["pacman", "-Q", "linux-asahi"]).strip()},
            "sources": {
                "ffmpeg": {"revision": FFMPEG_PIN, "source_sha256": FFMPEG_ARCHIVE_SHA},
                "va_driver": {"revision": VA_PIN, "source_sha256": VA_ARCHIVE_SHA},
                "gstreamer": {"revision": GST_PIN, "source_sha256": GST_ARCHIVE_SHA},
                "kernel": {"revision": KERNEL_PIN, "source_sha256": KERNEL_SOURCE_SHA},
            },
            "patches": [patch_record(index, path.parent.name, path)
                        for index, path in enumerate(patches)],
            "build": {"commands": build_commands},
            "tools": {"cc": tool(["cc", "--version"]), "ld": tool(["ld", "--version"]),
                      "make": tool(["make", "--version"]), "meson": tool(["meson", "--version"]),
                      "ninja": tool(["ninja", "--version"]),
                      "pkg_config": tool(["pkg-config", "--version"]),
                      "python": sys.version.splitlines()[0]},
            "artifacts": {name: manifest.file_record(path) for name, path in artifacts.items()},
            "dependencies": {name: dependency_records(artifacts[name])
                             for name in manifest.EXPECTED_DEPENDENCIES},
            "kernel": {"vermagic": run(["modinfo", "-F", "vermagic",
                                           artifacts["recorder_module"]]).strip(),
                       "config_sha256": manifest.digest(Path("/usr/lib/modules") /
                                                         os.uname().release / "build/.config"),
                       "modules": {name: manifest.file_record(path)
                                   for name, path in kernel_files.items()},
                       "recorder_endpoints": ["/sys/kernel/debug/apple_avd_hevc_cmdtrace",
                                              "/sys/kernel/debug/apple_avd_hevc_trace"]},
            "corpus": corpus,
            "reference": reference,
            "targets": target_rows,
            "plan": manifest.file_record(plan_path),
            "commands": commands,
            "limits": {"snapshot_bytes": 184320, "snapshots": 8,
                       "total_bytes": 1474560, "copy_ms": 20,
                       "drain_seconds": 2, "run_seconds": 120,
                       "campaign_seconds": 1200},
        }
        # Candidate generation never self-approves.  Review changes state to
        # reviewed without changing any other byte/field, then pins that file's
        # exact digest in the external Authorization.
        manifest.validate(document | {"state": "reviewed", "repo": document["repo"] | {"dirty": False}},
                          root_owned=False, check_files=True)
        output = stage / "candidate-manifest.json"
        output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"candidate": str(output), "sha256": manifest.digest(output),
                          "state": "candidate", "execution_authorized": False},
                         sort_keys=True))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"BUILD REFUSED: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
