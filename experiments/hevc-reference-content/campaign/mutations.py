#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prove campaign safety checks with source-level semantic mutations."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "controller.py"
TESTS = HERE / "tests.py"

MUTATIONS = (
    ("selector-domain",
     "if workload.selector_domain != expected_domain:",
     "if False:",
     "Selections.test_selector_domain_mismatch_rejected"),
    ("gst-reserve-capacity",
     "elif workload.gst_pool_size <= len(workload.selectors):",
     "elif False:",
     "Selections.test_gst_reserve_capacity_rejected"),
    ("parameter-input-window",
     "if workload.arm_input_index <= value <= workload.last_required_input_index]",
     "if workload.arm_input_index <= value <= max(workload.selectors)]",
     "Selections.test_parameter_change_uses_input_window_not_va_ordinal"),
    ("paired-off-on",
     "if off.selectors != on.selectors:",
     "if False:",
     "Selections.test_copy_off_on_selector_mismatch_rejected"),
    ("va-threads",
     "if plan.va.decoder_threads != 1:",
     "if False:",
     "VAProperties.test_threads_guard"),
    ("va-owner",
     "if not plan.va.single_application_owner:",
     "if False:",
     "VAProperties.test_single_owner_guard"),
    ("va-finish-before-close",
     "if not plan.va.finish_before_close:",
     "if False:",
     "VAProperties.test_finish_before_close_guard"),
    ("va-fatal-cleanup",
     "if not plan.va.fatal_cleanup_is_failure:",
     "if False:",
     "VAProperties.test_fatal_cleanup_guard"),
    ("json-authorization",
     '"execution_authorized": False,',
     '"execution_authorized": True,',
     "Contracts.test_invalid_json_carries_reasons_and_never_authorizes"),
    ("execution-refusal",
     """        raise AuthorizationError(
            "campaign execution is not implemented and is not authorized by this leaf: "
            "a reviewed deployment manifest, full client/dependency/corpus attestation and "
            "proven live target eligibility/workload admission remain outstanding. "
            "See CAMPAIGN.md and companion issue #82.")""",
     "        return None",
     "Execution.test_execute_refuses_even_with_valid_plan_and_authorization"),
)


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"mutation drift: expected one occurrence of {old!r}")
    return source.replace(old, new)


def main() -> int:
    original = SOURCE.read_text()
    for label, old, new, test in MUTATIONS:
        with tempfile.TemporaryDirectory() as temporary:
            mutated = Path(temporary) / "controller.py"
            mutated.write_text(replace_once(original, old, new))
            environment = os.environ | {"CAMPAIGN_CONTROLLER": str(mutated)}
            result = subprocess.run([sys.executable, str(TESTS), test],
                                    capture_output=True, text=True, env=environment,
                                    timeout=30)
        diagnostic = result.stdout + result.stderr
        if result.returncode == 0 or test not in diagnostic or "FAILED" not in diagnostic:
            raise RuntimeError(f"semantic mutation not distinguished: {label}\n{diagnostic}")
        print(f"PASS semantic campaign mutation {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
