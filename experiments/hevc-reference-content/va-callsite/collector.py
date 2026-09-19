#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Validate one normalized FFmpeg VA observer report without opening a device."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

SCHEMA = "omarchy.hevc.va-observer-result/v1"
MAX_REPORT_BYTES = 8 * 1024
TOP_KEYS = frozenset({"schema", "count", "outputs"})
OUTPUT_KEYS = frozenset({
    "output_ordinal", "surface", "run", "context_generation", "session",
    "allocation_generation", "writer", "submitted", "completed",
    "capture_index", "copied", "sha256",
})
HEX64_FIELDS = (
    "context_generation", "session", "allocation_generation", "writer",
    "submitted", "completed",
)


class ReportError(ValueError):
    """The report is incomplete, ambiguous, or outside the normalized schema."""


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _hex(value: object, digits: int, field: str) -> None:
    if (type(value) is not str or len(value) != digits or
            any(char not in "0123456789abcdef" for char in value)):
        raise ReportError(f"{field} must be {digits} lowercase hexadecimal digits")


def _uint(value: object, bits: int, field: str) -> None:
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ReportError(f"{field} must be an unsigned {bits}-bit integer")


def parse_report(data: bytes, *, expected_outputs: tuple[int, ...] | None = None,
                 expected_copy: bool | None = None) -> dict[str, object]:
    if not data or len(data) > MAX_REPORT_BYTES or not data.endswith(b"\n"):
        raise ReportError("report must be one bounded newline-terminated record")
    if b"\x00" in data:
        raise ReportError("report contains a NUL byte")
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReportError(f"invalid report JSON: {error}") from error
    if type(document) is not dict or set(document) != TOP_KEYS:
        raise ReportError("unexpected top-level report fields")
    if document["schema"] != SCHEMA:
        raise ReportError("unknown report schema")
    outputs = document["outputs"]
    count = document["count"]
    if type(outputs) is not list or type(count) is not int:
        raise ReportError("count and outputs have invalid types")
    if not 1 <= count <= 8 or count != len(outputs):
        raise ReportError("count does not describe one to eight outputs")

    ordinals: list[int] = []
    observation_identity: tuple[object, object, object] | None = None
    for index, output in enumerate(outputs):
        prefix = f"outputs[{index}]"
        if type(output) is not dict or set(output) != OUTPUT_KEYS:
            raise ReportError(f"{prefix} has unexpected fields")
        _uint(output["output_ordinal"], 64, prefix + ".output_ordinal")
        _uint(output["surface"], 32, prefix + ".surface")
        _uint(output["capture_index"], 32, prefix + ".capture_index")
        run = output["run"]
        if type(run) is not list or len(run) != 2:
            raise ReportError(f"{prefix}.run must contain two identities")
        _hex(run[0], 16, prefix + ".run[0]")
        _hex(run[1], 16, prefix + ".run[1]")
        for field in HEX64_FIELDS:
            _hex(output[field], 16, prefix + "." + field)
        identity = (tuple(run), output["context_generation"], output["session"])
        if observation_identity is None:
            observation_identity = identity
        elif identity != observation_identity:
            raise ReportError("outputs do not share one run/context/session")
        if type(output["copied"]) is not bool:
            raise ReportError(f"{prefix}.copied must be boolean")
        if output["copied"]:
            _hex(output["sha256"], 64, prefix + ".sha256")
        elif output["sha256"] is not None:
            raise ReportError(f"{prefix}.sha256 must be null when copy is off")
        ordinals.append(output["output_ordinal"])

    if len(set(ordinals)) != len(ordinals):
        raise ReportError("output ordinals are duplicated")
    if expected_outputs is not None and tuple(ordinals) != expected_outputs:
        raise ReportError("report output ordinals do not match the requested order")
    if expected_copy is not None and any(
            output["copied"] is not expected_copy for output in outputs):
        raise ReportError("report copy mode does not match the requested mode")
    return document


def load_report(path: Path, **expectations: object) -> dict[str, object]:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ReportError("this collector requires O_NOFOLLOW")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ReportError(f"cannot open report: {error}") from error
    try:
        status = os.fstat(fd)
        if not stat.S_ISREG(status.st_mode):
            raise ReportError("report is not a regular file")
        if status.st_uid != os.geteuid() or status.st_nlink != 1:
            raise ReportError("report ownership or link count is ambiguous")
        if status.st_mode & 0o077:
            raise ReportError("report permissions expose private evidence")
        if not 0 < status.st_size <= MAX_REPORT_BYTES:
            raise ReportError("report size is outside the accepted bound")
        data = bytearray()
        while len(data) <= MAX_REPORT_BYTES:
            chunk = os.read(fd, min(4096, MAX_REPORT_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
    finally:
        os.close(fd)
    if len(data) != status.st_size:
        raise ReportError("report changed while it was read")
    return parse_report(bytes(data), **expectations)


def collect_report(path: Path, *, process_exit_code: int,
                   **expectations: object) -> dict[str, object]:
    if type(process_exit_code) is not int or process_exit_code != 0:
        raise ReportError("the complete FFmpeg process did not exit successfully")
    return load_report(path, **expectations)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--outputs", required=True,
                        help="comma-separated zero-based output ordinals")
    parser.add_argument("--copy", choices=("off", "on"), required=True)
    parser.add_argument("--process-exit-code", type=int, required=True,
                        help="exit code of the complete FFmpeg process")
    args = parser.parse_args()
    try:
        outputs = tuple(int(value, 10) for value in args.outputs.split(","))
    except ValueError as error:
        raise SystemExit(f"invalid --outputs: {error}") from error
    document = collect_report(args.report,
                              process_exit_code=args.process_exit_code,
                              expected_outputs=outputs,
                              expected_copy=args.copy == "on")
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
