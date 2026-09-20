#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Strict HEVC observer deployment manifest validation.

Candidate manifests are build inventories.  Only an exact, separately reviewed
digest in a root-owned location may become a live admission input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Callable

SCHEMA = "omarchy.hevc.observer-deployment/v1"
TOP_KEYS = frozenset({
    "schema", "state", "repo", "host", "sources", "patches", "build", "tools",
    "artifacts", "dependencies", "kernel", "corpus", "reference",
    "targets", "plan", "commands", "limits",
})
SOURCE_KEYS = frozenset({"revision", "source_sha256"})
PATCH_KEYS = frozenset({"order", "component", "path", "sha256"})
FILE_KEYS = frozenset({"path", "sha256", "build_id"})
CORPUS_KEYS = frozenset({"path", "sha256", "bytes", "frames"})
TARGET_KEYS = frozenset({
    "client", "vector", "selector_domain", "selectors", "last_input",
    "output_count", "gst_pool_size", "gst_reserve", "parameter_set_change_inputs",
    "evidence_sha256",
})
EXPECTED_SOURCES = frozenset({"ffmpeg", "va_driver", "gstreamer", "kernel"})
EXPECTED_ARTIFACTS = frozenset({
    "ffmpeg", "va_driver", "gst_launch", "gst_plugin", "gst_parser",
    "gst_videoconvert", "gst_core", "recorder_module",
    "v4l2_tracer", "oracle", "uapi", "same_run_supervisor", "hwguard",
    "target_evidence", "recorder_provenance",
})
EXPECTED_DEPENDENCIES = frozenset({
    "ffmpeg", "va_driver", "gst_launch", "gst_plugin", "gst_parser",
    "gst_videoconvert", "gst_core",
})
EXPECTED_MODULES = frozenset({
    "apple_avd", "videobuf2_common", "videobuf2_v4l2",
    "videobuf2_dma_contig",
})
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
BUILD_ID = re.compile(r"(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})\Z")


class ManifestError(ValueError):
    """A manifest or live identity that must not reach the decoder."""


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise ManifestError(reason)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ManifestError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def read_document(path: Path, maximum: int = 1024 * 1024) -> tuple[bytes, dict]:
    need(path.is_absolute(), "manifest path is not absolute")
    try:
        info = path.lstat()
    except OSError as error:
        raise ManifestError(f"cannot stat manifest: {error}") from error
    need(stat.S_ISREG(info.st_mode) and not path.is_symlink(),
         "manifest is not a direct regular file")
    need(info.st_size <= maximum, "manifest exceeds size limit")
    raw = path.read_bytes()
    try:
        document = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ManifestError(f"manifest is not strict JSON: {error}") from error
    need(type(document) is dict, "manifest root is not an object")
    return raw, document


def safe_path(path: Path, *, root_owned: bool) -> None:
    need(path.is_absolute(), f"path is not absolute: {path}")
    current = path
    while True:
        info = current.lstat()
        need(not stat.S_ISLNK(info.st_mode), f"symlink is forbidden: {current}")
        need(not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH),
             f"group/other-writable path is forbidden: {current}")
        if root_owned:
            need(info.st_uid == 0, f"approved path is not root-owned: {current}")
        if not root_owned or current.parent == current:
            break
        current = current.parent


def build_id(path: Path) -> str:
    result = subprocess.run(["readelf", "-n", str(path)], text=True,
                            capture_output=True, timeout=30)
    if result.returncode:
        return "none"
    matches = re.findall(r"Build ID:\s*([0-9a-fA-F]+)", result.stdout)
    need(len(matches) <= 1, f"multiple build IDs in {path}")
    return matches[0].lower() if matches else "none"


def dependency_closure(path: Path) -> tuple[Path, ...]:
    result = subprocess.run(["ldd", str(path)], text=True, capture_output=True,
                            timeout=30)
    need(result.returncode == 0, f"ldd failed for {path}: {result.stderr.strip()}")
    found: set[Path] = set()
    for line in result.stdout.splitlines():
        text = line.strip()
        if " => not found" in text:
            raise ManifestError(f"unresolved dependency for {path}: {text}")
        candidate = ""
        if " => /" in text:
            candidate = text.split(" => ", 1)[1].split(" (", 1)[0]
        elif text.startswith("/"):
            candidate = text.split(" (", 1)[0]
        if candidate:
            found.add(Path(candidate).resolve())
    return tuple(sorted(found))


def file_record(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": digest(resolved),
            "build_id": build_id(resolved)}


def require_tokens(path: Path, command: str, tokens: tuple[str, ...], name: str) -> None:
    result = subprocess.run([command, "-D", str(path)] if command == "nm"
                            else [command, str(path)], text=True,
                            capture_output=True, timeout=30)
    need(result.returncode == 0, f"cannot inspect observer symbols: {name}")
    for token in tokens:
        need(token in result.stdout, f"{name} lacks observer token: {token}")


def _exact(value: object, keys: frozenset[str], name: str) -> dict:
    need(type(value) is dict and set(value) == keys,
         f"{name} has unexpected fields")
    return value


def _hex(value: object, name: str) -> str:
    need(type(value) is str and HEX64.fullmatch(value) is not None,
         f"{name} is not a SHA-256 digest")
    return value


def _file(value: object, name: str, *, root_owned: bool,
          check_files: bool) -> Path:
    row = _exact(value, FILE_KEYS, name)
    path = Path(row["path"])
    _hex(row["sha256"], name + ".sha256")
    need(type(row["build_id"]) is str and
         (row["build_id"] == "none" or BUILD_ID.fullmatch(row["build_id"])),
         f"{name}.build_id is invalid")
    if check_files:
        safe_path(path, root_owned=root_owned)
        need(path.is_file(), f"{name} is not a regular file")
        need(digest(path) == row["sha256"], f"{name} hash drift")
        need(build_id(path) == row["build_id"], f"{name} build-ID drift")
    return path


def validate(document: dict, *, root_owned: bool = False,
             check_files: bool = True,
             dependency_reader: Callable[[Path], tuple[Path, ...]] = dependency_closure) -> None:
    _exact(document, TOP_KEYS, "manifest")
    need(document["schema"] == SCHEMA, "unknown manifest schema")
    need(document["state"] == "reviewed", "candidate manifest is not reviewed")
    _exact(document["repo"], frozenset({"commit", "dirty"}), "repo")
    need(re.fullmatch(r"[0-9a-f]{40}", document["repo"]["commit"] or "") is not None,
         "repo commit is invalid")
    need(document["repo"]["dirty"] is False, "dirty source tree is not admitted")
    host = _exact(document["host"], frozenset({"architecture", "compatible", "kernel_release",
                                                "linux_asahi"}), "host")
    need(host["architecture"] == "aarch64", "manifest is not for aarch64")
    need(type(host["compatible"]) is list and "apple," in "".join(host["compatible"]),
         "manifest is not for Apple hardware")
    need(all(type(host[key]) is str and host[key] for key in ("kernel_release", "linux_asahi")),
         "host kernel/package identity is incomplete")

    need(type(document["sources"]) is dict and
         set(document["sources"]) == EXPECTED_SOURCES, "source set is incomplete")
    for name, value in document["sources"].items():
        row = _exact(value, SOURCE_KEYS, "source." + name)
        need(re.fullmatch(r"[0-9a-f]{40}", row["revision"] or "") is not None,
             f"source.{name}.revision is invalid")
        _hex(row["source_sha256"], f"source.{name}.source_sha256")

    patches = document["patches"]
    need(type(patches) is list and patches and len(patches) <= 32,
         "patch inventory is empty or excessive")
    for index, value in enumerate(patches):
        row = _exact(value, PATCH_KEYS, f"patches[{index}]")
        need(row["order"] == index and type(row["component"]) is str,
             "patch order/component is invalid")
        path = Path(row["path"])
        _hex(row["sha256"], f"patches[{index}].sha256")
        if check_files:
            safe_path(path, root_owned=root_owned)
            need(digest(path) == row["sha256"], f"patch drift: {path}")

    build = _exact(document["build"], frozenset({"commands"}), "build")
    need(type(build["commands"]) is list and build["commands"],
         "build command inventory is empty")
    for index, value in enumerate(build["commands"]):
        row = _exact(value, frozenset({"argv", "cwd"}), f"build.commands[{index}]")
        need(type(row["argv"]) is list and row["argv"] and
             all(type(item) is str and item for item in row["argv"]),
             f"build.commands[{index}].argv is invalid")
        need(type(row["cwd"]) is str and Path(row["cwd"]).is_absolute(),
             f"build.commands[{index}].cwd is not absolute")

    tools = document["tools"]
    need(type(tools) is dict and set(tools) == {
        "cc", "ld", "make", "meson", "ninja", "pkg_config", "python"},
         "tool identity set is incomplete")
    need(all(type(value) is str and value for value in tools.values()),
         "empty tool identity")

    artifacts = document["artifacts"]
    need(type(artifacts) is dict and set(artifacts) == EXPECTED_ARTIFACTS,
         "artifact set is incomplete")
    artifact_paths = {name: _file(value, "artifact." + name,
                                  root_owned=root_owned, check_files=check_files)
                      for name, value in artifacts.items()}
    if check_files:
        require_tokens(artifact_paths["va_driver"], "nm",
                       ("v4l2r_observer_abi", "v4l2r_content_snapshot",
                        "v4l2r_observer_result"), "VA driver")
        require_tokens(artifact_paths["ffmpeg"], "strings",
                       ("va_observer_outputs", "va_observer_copy",
                        "va_observer_report"), "FFmpeg")
        require_tokens(artifact_paths["gst_plugin"], "strings",
                       ("hevc-observer-frames", "hevc-observer-copy",
                        "hevc-observer-report", "observer-queue"), "Gst decoder")
        require_tokens(artifact_paths["gst_parser"], "strings", ("h265parse",),
                       "Gst parser")
        require_tokens(artifact_paths["gst_videoconvert"], "strings", ("videoconvert",),
                       "Gst video converter")
        require_tokens(artifact_paths["gst_core"], "strings", ("filesink",),
                       "Gst core elements")
        try:
            provenance = json.loads(artifact_paths["recorder_provenance"].read_text(),
                                    object_pairs_hook=_pairs)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ManifestError(f"recorder provenance is not strict JSON: {error}") from error
        need(type(provenance) is dict, "recorder provenance is not an object")
        need(provenance.get("module_sha256") == artifacts["recorder_module"]["sha256"],
             "recorder module differs from corrected-build provenance")

    dependencies = document["dependencies"]
    need(type(dependencies) is dict and set(dependencies) == EXPECTED_DEPENDENCIES,
         "dependency closure set is incomplete")
    for name, values in dependencies.items():
        need(type(values) is list and values, f"empty dependency closure: {name}")
        paths = [_file(value, f"dependencies.{name}[{index}]",
                       root_owned=root_owned, check_files=check_files)
                 for index, value in enumerate(values)]
        need(len(paths) == len(set(paths)), f"duplicate dependency path: {name}")
        if check_files:
            actual = set(dependency_reader(artifact_paths[name]))
            need(actual == set(paths), f"dependency closure drift: {name}")

    kernel = _exact(document["kernel"], frozenset({
        "vermagic", "config_sha256", "modules", "recorder_endpoints"}), "kernel")
    need(type(kernel["vermagic"]) is str and kernel["vermagic"], "empty module vermagic")
    _hex(kernel["config_sha256"], "kernel.config_sha256")
    need(type(kernel["modules"]) is dict and set(kernel["modules"]) == EXPECTED_MODULES,
         "kernel module identity set is incomplete")
    for name, value in kernel["modules"].items():
        need(type(value) is dict and value.get("build_id") != "none",
             f"built-in/identity-less module is refused: {name}")
        _file(value, "kernel.modules." + name, root_owned=root_owned,
              check_files=check_files)
    endpoints = kernel["recorder_endpoints"]
    need(endpoints == ["/sys/kernel/debug/apple_avd_hevc_cmdtrace",
                       "/sys/kernel/debug/apple_avd_hevc_trace"],
         "recorder endpoint set is invalid")

    corpus = document["corpus"]
    need(type(corpus) is dict and set(corpus) == {"B", "E"}, "corpus set is incomplete")
    for vector, value in corpus.items():
        row = _exact(value, CORPUS_KEYS, "corpus." + vector)
        path = Path(row["path"])
        _hex(row["sha256"], "corpus." + vector + ".sha256")
        need(type(row["bytes"]) is int and row["bytes"] > 0 and row["frames"] == 300,
             f"corpus.{vector} extent is invalid")
        if check_files:
            safe_path(path, root_owned=root_owned)
            need(path.stat().st_size == row["bytes"] and digest(path) == row["sha256"],
                 f"corpus drift: {vector}")

    reference = _exact(document["reference"], FILE_KEYS | {"frames_sha256"}, "reference")
    _hex(reference["frames_sha256"], "reference.frames_sha256")
    _file({key: reference[key] for key in FILE_KEYS}, "reference",
          root_owned=root_owned, check_files=check_files)

    targets = document["targets"]
    need(type(targets) is list and len(targets) == 4, "exactly four target groups are required")
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(targets):
        row = _exact(value, TARGET_KEYS, f"targets[{index}]")
        client, vector = row["client"], row["vector"]
        need(client in ("va", "gst") and vector in ("B", "E") and
             (client, vector) not in seen, "target client/vector set is invalid")
        seen.add((client, vector))
        wanted = 3 if vector == "E" else 1
        need(type(row["selectors"]) is list and len(row["selectors"]) == wanted and
             len(set(row["selectors"])) == wanted and
             all(type(item) is int and item >= 0 for item in row["selectors"]),
             f"{client}/{vector} selector shape is invalid")
        domain = "output_ordinal" if client == "va" else "system_frame_number"
        need(row["selector_domain"] == domain, f"{client}/{vector} selector domain is invalid")
        need(type(row["last_input"]) is int and row["last_input"] >= max(row["selectors"]),
             f"{client}/{vector} input window is invalid")
        changes = row["parameter_set_change_inputs"]
        need(type(changes) is list and len(changes) == len(set(changes)) and
             all(type(item) is int and item >= 0 for item in changes),
             f"{client}/{vector} parameter-set changes are invalid")
        need(all(item > row["last_input"] for item in changes),
             f"{client}/{vector} parameter-set change enters the armed window")
        need(type(row["output_count"]) is int and
             max(row["selectors"]) < row["output_count"],
             f"{client}/{vector} selector exceeds output count")
        if client == "gst":
            need(type(row["gst_pool_size"]) is int and
                 type(row["gst_reserve"]) is int and
                 row["gst_reserve"] == wanted and
                 row["gst_pool_size"] > row["gst_reserve"],
                 f"{client}/{vector} capacity is invalid")
        else:
            need(row["gst_pool_size"] is None and row["gst_reserve"] is None,
                 f"{client}/{vector} carries Gst capacity")
        _hex(row["evidence_sha256"], f"{client}/{vector}.evidence_sha256")
        need(row["evidence_sha256"] == artifacts["target_evidence"]["sha256"],
             f"{client}/{vector} target evidence is not the staged evidence")
    need(seen == {(client, vector) for client in ("va", "gst") for vector in ("B", "E")},
         "target matrix is incomplete")
    by_target = {(row["client"], row["vector"]): row for row in targets}
    for vector in ("B", "E"):
        need(by_target[("gst", vector)]["parameter_set_change_inputs"] ==
             by_target[("va", vector)]["parameter_set_change_inputs"],
             f"{vector} parameter-set evidence differs by client")

    plan = _exact(document["plan"], FILE_KEYS | {"sha256"}, "plan")
    # FILE_KEYS already contains sha256; set union intentionally documents the one digest.
    _file(plan, "plan", root_owned=root_owned, check_files=check_files)
    commands = document["commands"]
    need(type(commands) is list and len(commands) == 8, "eight admitted workload commands required")
    names = set()
    command_matrix = set()
    for index, row in enumerate(commands):
        _exact(row, frozenset({"name", "client", "vector", "copy", "environment", "argv"}),
               f"commands[{index}]")
        need(type(row["argv"]) is list and row["argv"] and
             all(type(item) is str and item for item in row["argv"]),
             f"commands[{index}].argv is invalid")
        need(type(row["environment"]) is dict and row["environment"] and
             all(type(key) is str and key and type(item) is str and item
                 for key, item in row["environment"].items()),
             f"commands[{index}].environment is invalid")
        need(row["argv"].count("@OMARCHY_RUN_ROOT@") == 1 and
             row["argv"].count("@OMARCHY_KERNEL_RUN@") == 1,
             f"commands[{index}] lacks fresh run placeholders")
        names.add(row["name"])
        need(row["client"] in ("va", "gst") and row["vector"] in ("B", "E") and
             type(row["copy"]) is bool and
             row["name"] == f"{row['vector']}-{row['client']}-"
                            f"{'on' if row['copy'] else 'off'}",
             f"commands[{index}] identity is invalid")
        command_matrix.add((row["vector"], row["client"], row["copy"]))
    need(len(names) == 8, "workload command names are not unique")
    need(command_matrix == {(vector, client, copied)
                            for vector in ("B", "E")
                            for client in ("va", "gst")
                            for copied in (False, True)},
         "workload command matrix is incomplete")
    limits = _exact(document["limits"], frozenset({
        "snapshot_bytes", "snapshots", "total_bytes", "copy_ms",
        "drain_seconds", "run_seconds", "campaign_seconds"}), "limits")
    need(limits == {"snapshot_bytes": 184320, "snapshots": 8,
                    "total_bytes": 1474560, "copy_ms": 20,
                    "drain_seconds": 2, "run_seconds": 120,
                    "campaign_seconds": 1200}, "campaign limits drift")


def verify(path: Path, approved_sha256: str, *, live: bool,
           root_owned: bool = True) -> dict:
    _hex(approved_sha256, "approved manifest digest")
    raw, document = read_document(path)
    need(hashlib.sha256(raw).hexdigest() == approved_sha256,
         "manifest differs from reviewed digest")
    safe_path(path, root_owned=root_owned)
    validate(document, root_owned=root_owned, check_files=True)
    if live:
        live_preflight(document)
    return document


def _loaded_note(module: str) -> str:
    path = Path("/sys/module") / module / "notes/.note.gnu.build-id"
    need(path.is_file(), f"loaded module lacks a build-ID note: {module}")
    raw = path.read_bytes()
    # GNU build-ID desc is the final 20 bytes on the modules admitted here.
    need(len(raw) >= 20, f"short loaded build-ID note: {module}")
    return raw[-20:].hex()


def live_preflight(document: dict) -> None:
    need(os.uname().machine == "aarch64", "live host is not aarch64")
    compatible = Path("/proc/device-tree/compatible").read_bytes().split(b"\0")
    need(any(item.startswith(b"apple,") for item in compatible), "live host is not Apple")
    need(os.uname().release == document["host"]["kernel_release"], "kernel release drift")
    for name, row in document["kernel"]["modules"].items():
        need(_loaded_note(name) == row["build_id"], f"loaded module build-ID drift: {name}")
    for path in document["kernel"]["recorder_endpoints"]:
        status_path = Path(path) / "status"
        need(status_path.is_file(), f"missing recorder endpoint: {path}")
        status_text = status_path.read_text()
        need("phase=off" in status_text and "contexts=0" in status_text and
             "errors=0" in status_text, f"recorder is not clean/off: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--approved-sha256", required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        document = verify(args.manifest.resolve(), args.approved_sha256,
                          live=args.live, root_owned=True)
    except (ManifestError, OSError) as error:
        print(f"REFUSED: {error}")
        return 125
    print(json.dumps({"schema": SCHEMA, "manifest_sha256": args.approved_sha256,
                      "plan_sha256": document["plan"]["sha256"],
                      "live": args.live, "execution_authorized": False},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
