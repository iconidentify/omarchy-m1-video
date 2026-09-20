#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run one guarded client and publish its validated same-run evidence join.

The outer process runs ``v4l2-tracer`` around a private worker.  That worker uses
the existing paired kernel supervisor to block the decoder child before exec and
arm both recorders for the decoder's actual PID.  This topology is intentional:
v4l2-tracer forks its tracee, so putting it *inside* the exact-PID supervisor
would arm the recorders for the tracer wrapper instead of the decoder.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
CAPTURE_PATH = REPO / "experiments/hevc-avd-command-capture/capture.py"
PLACEHOLDER = "@OMARCHY_OBSERVER_REPORT@"
AT_FDCWD = -100
RENAME_NOREPLACE = 1

sys.path.insert(0, str(HERE))
import join  # noqa: E402
import validator  # noqa: E402


def _load_capture():
    spec = importlib.util.spec_from_file_location("same_run_capture", CAPTURE_PATH)
    join.need(spec is not None and spec.loader is not None,
              "cannot load the paired kernel supervisor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = _load_capture()


def _option(command: tuple[str, ...], prefix: str) -> str | None:
    found: list[str] = []
    for index, value in enumerate(command):
        if value == prefix or value.startswith(prefix + ":"):
            if index + 1 < len(command):
                found.append(command[index + 1])
    return found[0] if len(found) == 1 else None


def configure_command(client: str, command: tuple[str, ...], selectors: tuple[int, ...],
                      copy: bool, report_path: Path) -> tuple[str, ...]:
    expected_program = "ffmpeg" if client == "va" else "gst-launch-1.0"
    join.need(command and Path(command[0]).name == expected_program,
              f"{client} command must execute {expected_program} directly")
    join.need(sum(value.count(PLACEHOLDER) for value in command) == 1,
              "command must contain exactly one observer-report placeholder")
    selected = ",".join(map(str, selectors))
    if client == "va":
        join.need(_option(command, "-va_observer_outputs") == selected,
                  "VA command selectors differ from the reviewed request")
        join.need(_option(command, "-va_observer_copy") == ("1" if copy else "0"),
                  "VA command copy mode differs from the reviewed request")
        join.need(_option(command, "-va_observer_report") == PLACEHOLDER,
                  "VA command does not bind the report placeholder to its private option")
        join.need(_option(command, "-threads") == "1" or
                  _option(command, "-threads:v") == "1",
                  "VA observer command must explicitly use one decoder thread")
        join.need(_option(command, "-hwaccel") == "vaapi",
                  "VA observer command must explicitly select VAAPI hardware decode")
    else:
        decoders = [index for index, value in enumerate(command) if value == "v4l2slh265dec"]
        join.need(len(decoders) == 1, "Gst command must contain exactly one v4l2slh265dec")
        start = decoders[0] + 1
        try:
            end = command.index("!", start)
        except ValueError:
            end = len(command)
        properties = command[start:end]
        frame_properties = [value for value in properties
                            if value.startswith("hevc-observer-frames=")]
        copy_properties = [value for value in properties
                           if value.startswith("hevc-observer-copy=")]
        report_properties = [value for value in properties
                             if value.startswith("hevc-observer-report=")]
        join.need(frame_properties == ["hevc-observer-frames=" + selected],
                  "Gst command selectors differ from the reviewed request")
        wanted_copy = "true" if copy else "false"
        join.need(copy_properties == ["hevc-observer-copy=" + wanted_copy],
                  "Gst command copy mode differs from the reviewed request")
        join.need(report_properties == ["hevc-observer-report=" + PLACEHOLDER],
                  "Gst command does not bind the report placeholder to its property")
    return tuple(value.replace(PLACEHOLDER, str(report_path)) for value in command)


def _environment(client: str, queue_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    if client == "va":
        environment["LIBVA_V4L2_HEVC_REFTRACE"] = str(queue_path)
        for name in ("GST_DEBUG", "GST_DEBUG_FILE", "GST_DEBUG_NO_COLOR"):
            environment.pop(name, None)
    else:
        environment.pop("LIBVA_V4L2_HEVC_REFTRACE", None)
        # observer-queue uses GST_TRACE_OBJECT (level 7); level 6 silently omits
        # the only client-generation side of the cross-domain join.
        environment.update(GST_DEBUG_NO_COLOR="1", GST_DEBUG="v4l2codecs*:7",
                           GST_DEBUG_FILE=str(queue_path))
    return environment


def _write_all(fd: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(fd, raw[offset:])
        if written <= 0:
            raise OSError("short publication write")
        offset += written


def private_write(path: Path, raw: bytes) -> None:
    """Internal durable write; the exclusive run root owns this pathname."""
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        _write_all(fd, raw); os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def publish(path: Path, raw: bytes) -> None:
    """Linux atomic no-replace publication after every validation has passed."""
    join.need(not path.exists() and not path.is_symlink(), "result destination already exists")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    published = False
    try:
        _write_all(fd, raw); os.fsync(fd); os.close(fd); fd = -1
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
        renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_uint)
        renameat2.restype = ctypes.c_int
        if renameat2(AT_FDCWD, os.fsencode(temporary), AT_FDCWD,
                     os.fsencode(path), RENAME_NOREPLACE) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), path)
        published = True
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd >= 0:
            os.close(fd)
        if not published:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def va_associations(stderr: bytes, evidence: join.KernelEvidence) -> list[dict[str, int]]:
    try:
        text = stderr.decode("utf-8")
    except UnicodeDecodeError as error:
        raise join.JoinError(f"VA stderr is not UTF-8: {error}") from error
    pairs = [(int(layer), int(poc)) for layer, poc in
             re.findall(r"^Output frame with POC (\d+)/(-?\d+)$", text, re.MULTILINE)]
    join.need(len(pairs) == len(evidence.requests) and all(layer == 0 for layer, _ in pairs),
              "VA output trace is incomplete or contains another layer")
    by_poc: dict[int, int] = {}
    for row in evidence.requests:
        poc = row["poc"]
        join.need(poc not in by_poc, "VA decode POC is ambiguous")
        by_poc[poc] = row["pic"]
    join.need(set(by_poc) == {poc for _, poc in pairs},
              "VA output trace does not cover the same decoded pictures")
    return [{"output_index": index, "pic": by_poc[poc], "poc": poc}
            for index, (_, poc) in enumerate(pairs)]


def gst_associations(log: bytes, evidence: join.KernelEvidence) -> list[dict[str, int]]:
    try:
        text = log.decode("utf-8")
        rows = validator.full.base.associate(text, list(evidence.associations),
                                             len(evidence.requests), 0)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, IndexError) as error:
        raise join.JoinError(f"Gst output association failed: {error}") from error
    return [{key: int(row[key]) for key in ("output_index", "pic", "poc")} for row in rows]


WORKER_KEYS = frozenset({"schema", "root", "client", "kernel_run", "deadline", "command"})


def worker(spec_path: Path) -> int:
    """Tracee process: supervise only; the outer tracer must finalize first."""
    try:
        raw = validator.safe_read(spec_path, 256 * 1024, "worker specification")
        spec = join.json_document(raw, maximum=256 * 1024, name="worker specification")
        join.need(type(spec) is dict and set(spec) == WORKER_KEYS and
                  spec["schema"] == "omarchy.hevc.same-run-worker/v1",
                  "worker specification has unexpected fields")
        root = Path(spec["root"])
        join.need(root.is_absolute() and root.is_dir(), "worker root is not an existing absolute path")
        client = spec["client"]
        join.need(client in ("va", "gst"), "worker client is invalid")
        kernel_run = join._uint(spec["kernel_run"], 64, "worker kernel run", nonzero=True)
        deadline = spec["deadline"]
        join.need(type(deadline) in (int, float) and 1 <= deadline <= 90,
                  "worker deadline is invalid")
        command = spec["command"]
        join.need(type(command) is list and command and
                  all(type(value) is str and value for value in command),
                  "worker command is invalid")
        join.need(os.geteuid() != 0 and bool(os.environ.get("LIBVA_HW_GUARD_LEASE")),
                  "worker requires an ordinary user inside the hardware guard")
        queue_path = root / ("client-queue.jsonl" if client == "va" else "gst.log")
        old_umask = os.umask(0o077)
        try:
            result = capture.supervise(
                command, kernel_run, True, float(deadline),
                {name: capture.KernelTrace(name) for name in capture.PATHS},
                capture.Store(root / "kernel"), environment=_environment(client, queue_path),
                working_directory=root, stdout_path=root / "stdout.log",
                stderr_path=root / "stderr.log")
        finally:
            os.umask(old_umask)
        return 0 if (not result["errors"] and result["child_exit"] == 0 and
                     result["child_reaped"]) else 125
    except (ValueError, OSError) as error:
        print(f"WORKER REFUSED: {error}", file=sys.stderr)
        return 125


def _run_tracer(root: Path, worker_spec: Path, deadline: float) -> int:
    command = ["v4l2-tracer", "-u", "trace", sys.executable, str(Path(__file__).resolve()),
               "--worker-spec", str(worker_spec)]
    stdout_fd = os.open(root / "tracer-stdout.log",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        stderr_fd = os.open(root / "tracer-stderr.log",
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            process = subprocess.Popen(command, cwd=root, env=os.environ.copy(),
                                       stdout=stdout_fd, stderr=stderr_fd,
                                       start_new_session=True, umask=0o077)
        finally:
            os.close(stderr_fd)
    finally:
        os.close(stdout_fd)
    try:
        return process.wait(timeout=deadline + 15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
        raise join.JoinError("outer v4l2-tracer/worker deadline expired")


def run(*, root: Path, client: str, selectors: tuple[int, ...], copy: bool,
        kernel_run: int, deadline: float, command: tuple[str, ...],
        uapi: Path, oracle: Path) -> dict[str, object]:
    join.need(os.geteuid() != 0 and bool(os.environ.get("LIBVA_HW_GUARD_LEASE")),
              "ordinary user inside the exclusive hardware guard is required")
    join.need(client in ("va", "gst"), "unknown client")
    join._uint(kernel_run, 64, "kernel run", nonzero=True)
    join.need(type(deadline) in (int, float) and 1 <= deadline <= 90,
              "run deadline must be between one and 90 seconds")
    join.need(1 <= len(selectors) <= 8 and len(set(selectors)) == len(selectors) and
              all(type(value) is int and 0 <= value < (1 << 32) - 1 for value in selectors),
              "selectors must be one to eight unique bounded integers")
    root = root.resolve()
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    report_path = root / "client-result.json"
    queue_path = root / ("client-queue.jsonl" if client == "va" else "gst.log")
    stdout_path, stderr_path = root / "stdout.log", root / "stderr.log"
    result_path = root / "same-run-result.json"
    configured = configure_command(client, command, selectors, copy, report_path)
    invocation = {
        "schema": "omarchy.hevc.same-run-invocation/v1", "client": client,
        "kernel_run": str(kernel_run), "selectors": list(selectors), "copy": copy,
        "deadline_seconds": deadline, "guard_lease": os.environ["LIBVA_HW_GUARD_LEASE"],
        "command": list(configured),
    }
    private_write(root / "invocation.json",
                  json.dumps(invocation, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    worker_spec = root / "worker-spec.json"
    private_write(worker_spec, json.dumps({
        "schema": "omarchy.hevc.same-run-worker/v1", "root": str(root.resolve()),
        "client": client, "kernel_run": kernel_run, "deadline": deadline,
        "command": list(configured),
    }, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    status = _run_tracer(root, worker_spec, deadline)
    join.need(status == 0, "v4l2-tracer or supervised decoder failed; evidence was preserved")
    traces = list(root.glob("*_trace.json"))
    join.need(len(traces) == 1, "v4l2-tracer did not produce exactly one trace")

    evidence = validator.validate(
        execution_path=root / "kernel/execution.json", v4l2_trace_path=traces[0],
        command_snapshot_path=root / "kernel/command.snapshot",
        reference_snapshot_path=root / "kernel/reference.snapshot",
        uapi_path=uapi, oracle_path=oracle)
    enriched_hashes = dict(evidence.hashes)
    for name, path in (("invocation", root / "invocation.json"),
                       ("worker_spec", worker_spec)):
        enriched_hashes[name] = hashlib.sha256(
            validator.safe_read(path, 256 * 1024, name)).hexdigest()
    evidence = join.KernelEvidence(
        evidence.run, evidence.context, evidence.child_pid, evidence.requests,
        evidence.associations, evidence.reference_records, enriched_hashes)
    report_raw = validator.safe_read(report_path, 8 * 1024, "client observer result")
    queue_raw = validator.safe_read(queue_path, join.MAX_QUEUE_BYTES, "client queue trace")
    report = join.json_document(report_raw, maximum=8 * 1024, name="client observer result")
    if client == "va":
        stderr = validator.safe_read(stderr_path, 16 * 1024 * 1024, "VA stderr")
        associations = va_associations(stderr, evidence)
        result = join.join_va(evidence, report, queue_raw, associations,
                              selectors, copy, join.digest(queue_raw))
    else:
        associations = gst_associations(queue_raw, evidence)
        result = join.join_gst(evidence, report, queue_raw, associations,
                               selectors, copy, join.digest(queue_raw))
    result["inputs"]["client_report"] = join.digest(report_raw)
    if client == "va":
        result["inputs"]["client_output_log"] = join.digest(stderr)
    publish(result_path, join.encode(result))
    return result


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker-spec":
        return worker(Path(sys.argv[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--client", choices=("va", "gst"), required=True)
    parser.add_argument("--selectors", required=True)
    parser.add_argument("--copy", choices=("off", "on"), required=True)
    parser.add_argument("--kernel-run", type=int, required=True)
    parser.add_argument("--deadline", type=float, default=90)
    parser.add_argument("--uapi", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = tuple(args.command[1:] if args.command[:1] == ["--"] else args.command)
    try:
        selectors = tuple(int(value, 10) for value in args.selectors.split(","))
        result = run(root=args.root, client=args.client, selectors=selectors,
                     copy=args.copy == "on", kernel_run=args.kernel_run,
                     deadline=args.deadline, command=command,
                     uapi=args.uapi, oracle=args.oracle)
    except (ValueError, OSError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 125
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
