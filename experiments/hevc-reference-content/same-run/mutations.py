#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Require named semantic tests to kill fail-open same-run mutations."""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
FILES = (
    "experiments/hevc-reference-content/same-run/join.py",
    "experiments/hevc-reference-content/same-run/validator.py",
    "experiments/hevc-reference-content/same-run/supervisor.py",
    "experiments/hevc-reference-content/same-run/tests.py",
    "experiments/hevc-avd-command-capture/capture.py",
)

MUTATIONS = (
    ("exact-pid-arm", "experiments/hevc-avd-command-capture/capture.py",
     "b.control(f'arm {run} {pid}')", "b.control(f'arm {run} {os.getpid()}')",
     "SupervisorBoundary.test_paired_supervisor_binds_environment_cwd_logs_and_exact_pid"),
    ("outer-worker", "experiments/hevc-reference-content/same-run/supervisor.py",
     '"--worker-spec", str(worker_spec)]', '"--worker-spec-removed", str(worker_spec)]',
     "SupervisorBoundary.test_tracer_wraps_the_supervisor_worker_not_the_decoder"),
    ("same-process-va", "experiments/hevc-reference-content/same-run/join.py",
     "need(_va_projection(actual) == _va_projection(expected),",
     "need(True,", "ClientJoin.test_va_queue_must_be_the_same_raw_process"),
    ("full-tuple-gst", "experiments/hevc-reference-content/same-run/join.py",
     "need(all(row[key] == value for key, value in expected.items()),",
     'need(row["frame"] == frame,', "ClientJoin.test_gst_report_queue_mismatches_reject"),
    ("raw-timestamp-bridge", "experiments/hevc-reference-content/same-run/join.py",
     "raw = raw_by_frame.get(frame)",
     "raw = raw_by_frame.get(frame, evidence.associations[0])",
     "ClientJoin.test_gst_queue_must_bridge_raw_timestamp_and_capture"),
    ("paired-kernel-context", "experiments/hevc-reference-content/same-run/validator.py",
     'join.need(command["context"] == reference["context"] == context,',
     "join.need(True,", "RawValidatorBoundary.test_paired_kernel_context_must_match_supervisor"),
    ("existing-command-validator", "experiments/hevc-reference-content/same-run/validator.py",
     "join.need(not command_compare.compare(command, controls, flags),",
     "join.need(True,", "RawValidatorBoundary.test_raw_validator_rejects_control_or_oracle_mismatch"),
    ("completion-frontier", "experiments/hevc-reference-content/same-run/join.py",
     "need(completed == submitted,", "need(completed <= submitted,",
     "ClientJoin.test_report_frontier_and_queue_extent_reject"),
    ("normalized-only", "experiments/hevc-reference-content/same-run/join.py",
     "need(type(output) is dict and set(output) == expected_keys,",
     "need(type(output) is dict,", "ClientJoin.test_duplicate_json_and_malformed_queue_reject"),
    ("exclusive-publication", "experiments/hevc-reference-content/same-run/supervisor.py",
     "os.fsencode(path), RENAME_NOREPLACE) != 0:",
     "os.fsencode(path), 0) != 0:",
     "SupervisorBoundary.test_publication_race_cannot_replace_a_new_destination"),
)


def copy_current(worktree: Path) -> None:
    for cache in worktree.rglob("__pycache__"):
        shutil.rmtree(cache)
    for relative in FILES:
        source = REPO / relative
        target = worktree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="omarchy-same-run-mutants-") as directory:
        worktree = Path(directory) / "repo"
        subprocess.run(["git", "worktree", "add", "--detach", str(worktree), "HEAD"],
                       cwd=REPO, check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, timeout=30)
        try:
            for name, relative, old, new, test in MUTATIONS:
                copy_current(worktree)
                path = worktree / relative
                text = path.read_text()
                if text.count(old) != 1:
                    raise RuntimeError(f"{name}: mutation anchor count is {text.count(old)}")
                path.write_text(text.replace(old, new, 1))
                result = subprocess.run(
                    [sys.executable, "tests.py", test],
                    cwd=worktree / "experiments/hevc-reference-content/same-run",
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                output = result.stdout + result.stderr
                if result.returncode == 0 or "FAILED" not in output or "ERROR:" in output:
                    print(output, file=sys.stderr)
                    raise RuntimeError(f"{name}: intended semantic assertion did not fail cleanly")
                print(f"PASS mutation {name}: {test}")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)],
                           cwd=REPO, check=False, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
