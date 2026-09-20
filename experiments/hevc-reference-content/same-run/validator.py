#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Validate raw V4L2 plus paired kernel evidence from one supervised process."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
FULL = REPO / "experiments/hevc-full-controls"
COMMAND = REPO / "experiments/hevc-avd-command-trace"
CAPTURE = REPO / "experiments/hevc-avd-command-capture"
REFERENCE = REPO / "experiments/hevc-avd-trace"

# These directories contain historical standalone tools with intentional generic
# module names.  Import them in their own process in a deterministic order.
sys.path[:0] = [str(FULL), str(COMMAND), str(CAPTURE), str(REFERENCE)]
import normalize as full  # type: ignore  # noqa: E402
import report as full_report  # type: ignore  # noqa: E402
import parser as command_parser  # type: ignore  # noqa: E402
import compare as command_compare  # type: ignore  # noqa: E402
import oracle as command_oracle  # type: ignore  # noqa: E402

import join  # noqa: E402


MAXIMUMS = {
    "execution": 256 * 1024,
    "v4l2_trace": 128 * 1024 * 1024,
    "command_snapshot": 512 * 1024,
    "reference_snapshot": 4 * 1024 * 1024,
}
EXECUTION_KEYS = frozenset({
    "schema", "run", "enabled", "child_pid", "child_exit", "child_reaped",
    "child_released", "errors", "status", "snapshots", "events", "elapsed_seconds",
})
SUCCESS_EVENTS = (
    ("preflight", None),
    ("child-blocked", None),
    ("arm-attempt", "reference"),
    ("armed", "reference"),
    ("arm-attempt", "command"),
    ("armed", "command"),
    ("child-released", None),
    ("child-waited", None),
    ("sealed", "reference"),
    ("snapshot-persisted", "reference"),
    ("sealed", "command"),
    ("snapshot-persisted", "command"),
    ("cleared", "reference"),
    ("cleared", "command"),
    ("complete", None),
)


def safe_read(path: Path, maximum: int, name: str, *, private: bool = True) -> bytes:
    """Read one private, stable, same-owner regular file without following links."""
    join.need(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW is required")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        raise join.JoinError(f"cannot open {name}: {error}") from error
    close_error: OSError | None = None
    try:
        before = os.fstat(fd)
        join.need(stat.S_ISREG(before.st_mode), f"{name} is not a regular file")
        # Private captures belong to the run user. Public immutable tool inputs
        # may instead belong to root after deployment has secured its inventory.
        owner_ok = before.st_uid == os.geteuid() or (not private and before.st_uid == 0)
        join.need(owner_ok and before.st_nlink == 1,
                  f"{name} ownership/link count is ambiguous")
        join.need(not private or before.st_mode & 0o077 == 0, f"{name} is not private")
        join.need(private or before.st_mode & 0o022 == 0, f"{name} is publicly writable")
        join.need(0 < before.st_size <= maximum, f"{name} has an invalid extent")
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(fd, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk); total += len(chunk)
        after = os.fstat(fd)
    except OSError as error:
        raise join.JoinError(f"cannot read {name}: {error}") from error
    finally:
        try:
            os.close(fd)
        except OSError as error:
            close_error = error
    if close_error is not None:
        raise join.JoinError(f"cannot close {name}: {close_error}") from close_error
    stable = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size",
              "st_mtime_ns", "st_ctime_ns")
    join.need(all(getattr(before, field) == getattr(after, field) for field in stable),
              f"{name} changed while being read")
    raw = b"".join(chunks)
    join.need(len(raw) == before.st_size, f"{name} changed extent while being read")
    return raw


def _load_reference_checker():
    spec = importlib.util.spec_from_file_location("same_run_reference_checker",
                                                  REFERENCE / "check.py")
    join.need(spec is not None and spec.loader is not None,
              "cannot load accepted reference checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _execution(document: object, snapshots: dict[str, bytes]) -> tuple[int, int, int]:
    join.need(type(document) is dict, "execution record is not an object")
    join.need(set(document) == EXECUTION_KEYS,
              "execution record has unexpected or missing fields")
    join.need(document["schema"] == "hevc-avd-command-capture.execution/1",
              "execution record has the wrong schema")
    run = join._uint(document["run"], 64, "execution run", nonzero=True)
    child = join._uint(document["child_pid"], 31, "execution child pid", nonzero=True)
    join.need(document["enabled"] is True and document["child_exit"] == 0 and
              document["child_reaped"] is True and document["child_released"] is True and
              document["errors"] == [], "decoder/supervisor execution was not successful")
    elapsed = document["elapsed_seconds"]
    join.need(type(elapsed) in (int, float) and elapsed >= 0,
              "execution record has an invalid elapsed time")
    events = document["events"]
    join.need(type(events) is list and len(events) == len(SUCCESS_EVENTS),
              "execution event transcript has the wrong extent")
    observed: list[tuple[object, object]] = []
    previous = -1.0
    for index, event in enumerate(events):
        join.need(type(event) is dict and set(event) == {"stage", "recorder", "seconds"},
                  f"execution event {index} has unexpected fields")
        seconds = event["seconds"]
        join.need(type(seconds) in (int, float) and seconds >= previous,
                  f"execution event {index} has invalid or decreasing time")
        previous = float(seconds)
        observed.append((event["stage"], event["recorder"]))
    join.need(tuple(observed) == SUCCESS_EVENTS,
              "execution event transcript is not the successful exact-PID sequence")
    status = document["status"]
    recorded = document["snapshots"]
    join.need(type(status) is dict and set(status) == {"reference", "command"},
              "execution record does not contain both recorder statuses")
    join.need(type(recorded) is dict and set(recorded) == {"reference", "command"},
              "execution record does not contain both snapshot receipts")
    contexts: set[int] = set()
    for name in ("reference", "command"):
        row = status[name]
        status_keys = {"run", "context", "phase", "errors", "pictures",
                       "completions", "opens"}
        if name == "reference":
            status_keys |= {"count", "attempted"}
        join.need(type(row) is dict and set(row) == status_keys,
                  f"{name} recorder status has unexpected or missing fields")
        for field in ("run", "context", "phase", "errors", "pictures", "completions", "opens"):
            join.need(type(row.get(field)) is int, f"{name} recorder status lacks {field}")
        if name == "reference":
            join.need(type(row["count"]) is int and type(row["attempted"]) is int and
                      0 <= row["count"] <= row["attempted"],
                      "reference recorder count/attempted fields are invalid")
        join.need(row["run"] == run and row["context"] > 0 and row["phase"] == 4 and
                  row["errors"] == 0 and row["pictures"] == row["completions"] == 300 and
                  row["opens"] == 0, f"{name} recorder is not a complete sealed same-run capture")
        contexts.add(row["context"])
        receipt = recorded[name]
        raw = snapshots[name]
        join.need(type(receipt) is dict and set(receipt) == {"bytes", "sha256"} and
                  receipt["bytes"] == len(raw) and
                  receipt["sha256"] == hashlib.sha256(raw).hexdigest(),
                  f"{name} snapshot does not match its durable execution receipt")
    join.need(len(contexts) == 1, "paired kernel recorders captured different contexts")
    return run, contexts.pop(), child


def validate(*, execution_path: Path, v4l2_trace_path: Path,
             command_snapshot_path: Path, reference_snapshot_path: Path,
             uapi_path: Path, oracle_path: Path) -> join.KernelEvidence:
    paths = {
        "execution": execution_path,
        "v4l2_trace": v4l2_trace_path,
        "command_snapshot": command_snapshot_path,
        "reference_snapshot": reference_snapshot_path,
    }
    raw = {name: safe_read(path, MAXIMUMS[name], name) for name, path in paths.items()}
    execution = join.json_document(raw["execution"], maximum=MAXIMUMS["execution"],
                                   name="execution record")
    run, context, child = _execution(execution, {
        "command": raw["command_snapshot"], "reference": raw["reference_snapshot"]})

    try:
        events = full.base.parse(raw["v4l2_trace"])
        trace_token = hashlib.sha256(raw["v4l2_trace"]).hexdigest()[:16]
        controls, requests, associations = full.normalize(events, 300, trace_token)
        full_report.validate_controls(controls, requests, trace_token)

        command = command_parser.parse_snapshot(raw["command_snapshot"].decode("ascii"), run)
        reference_checker = _load_reference_checker()
        reference = reference_checker.read_capture(
            raw["reference_snapshot"].decode("ascii"), run)
        expected = reference_checker.model.map_records(requests, 300)
        normalized_reference = reference_checker.validate(reference, expected)
        join.need(not normalized_reference["findings"],
                  "same-run reference validator reported findings")
        command_parser.bind_history(command, reference)
        join.need(command["context"] == reference["context"] == context,
                  "snapshots disagree with the supervisor's paired kernel context")

        flags = command_compare.flag_values(uapi_path)
        join.need(not command_compare.compare(command, controls, flags),
                  "same-run returned controls differ from the kernel command snapshot")
        command_oracle.verify_identity(oracle_path)
        mismatches = [row["picture"] for row in command["windows"]
                      if not command_oracle.verify_window(oracle_path, row)]
        join.need(not mismatches,
                  "selected command words differ from the pinned C oracle: " +
                  ",".join(map(str, mismatches)))
    except (ValueError, KeyError, TypeError, IndexError, UnicodeError, OSError,
            subprocess.SubprocessError) as error:
        if isinstance(error, join.JoinError):
            raise
        raise join.JoinError(f"raw same-run validation failed: {error}") from error

    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    hashes["uapi"] = hashlib.sha256(safe_read(
        uapi_path, 2 * 1024 * 1024, "UAPI", private=False)).hexdigest()
    identity = safe_read(oracle_path / "identity.json", 1024 * 1024,
                         "oracle identity", private=False)
    hashes["oracle_identity"] = hashlib.sha256(identity).hexdigest()
    evidence = join.KernelEvidence(
        run=run, context=context, child_pid=child,
        requests=tuple(requests), associations=tuple(associations),
        reference_records=tuple(normalized_reference["records"]), hashes=hashes)
    evidence.check()
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--v4l2-trace", type=Path, required=True)
    parser.add_argument("--command-snapshot", type=Path, required=True)
    parser.add_argument("--reference-snapshot", type=Path, required=True)
    parser.add_argument("--uapi", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = validate(
            execution_path=args.execution, v4l2_trace_path=args.v4l2_trace,
            command_snapshot_path=args.command_snapshot,
            reference_snapshot_path=args.reference_snapshot,
            uapi_path=args.uapi, oracle_path=args.oracle)
    except (join.JoinError, OSError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"valid": True, "kernel_run": str(evidence.run),
                      "kernel_context": str(evidence.context),
                      "child_pid": evidence.child_pid, "hashes": evidence.hashes},
                     sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
