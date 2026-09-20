#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prove named deployment gates are required by mutating their implementation."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE.parent / "campaign"


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("mutation source drift: " + old)
    return text.replace(old, new)


MUTATIONS = (
    ("manifest-digest", "manifest.py",
     [("    need(hashlib.sha256(raw).hexdigest() == approved_sha256,\n"
       "         \"manifest differs from reviewed digest\")\n",
       "    # mutation: omit exact reviewed digest\n")],
     "test_exact_manifest_digest_is_required"),
    ("source", "manifest.py",
     [("        _hex(row[\"source_sha256\"], f\"source.{name}.source_sha256\")\n",
       "        # mutation: trust source identity\n")],
     "test_source_and_patch_drift_are_rejected"),
    ("dependency", "manifest.py",
     [("            need(actual == set(paths), f\"dependency closure drift: {name}\")\n",
       "            # mutation: trust dependency closure\n")],
     "test_artifact_and_dependency_drift_are_rejected"),
    ("corpus", "manifest.py",
     [("            need(path.stat().st_size == row[\"bytes\"] and digest(path) == row[\"sha256\"],\n"
       "                 f\"corpus drift: {vector}\")\n",
       "            # mutation: trust corpus path\n")],
    "test_corpus_and_reference_drift_are_rejected"),
    ("capacity", "manifest.py",
     [("                 row[\"gst_reserve\"] == wanted and\n",
       "                 row[\"gst_reserve\"] > 0 and\n")],
     "test_target_shape_capacity_and_domains_are_rejected"),
    ("target", "manifest.py",
     [("        need(type(row[\"selectors\"]) is list and len(row[\"selectors\"]) == wanted and\n"
       "             len(set(row[\"selectors\"])) == wanted and\n"
       "             all(type(item) is int and item >= 0 for item in row[\"selectors\"]),\n"
       "             f\"{client}/{vector} selector shape is invalid\")\n",
       "        need(type(row[\"selectors\"]) is list and row[\"selectors\"],\n"
       "             f\"{client}/{vector} selector shape is invalid\")\n")],
     "test_target_shape_capacity_and_domains_are_rejected"),
    ("plan", "manifest.py",
     [("    _file(plan, \"plan\", root_owned=root_owned, check_files=check_files)\n",
       "    # mutation: do not bind the plan file\n")],
     "test_plan_and_command_drift_are_rejected"),
    ("execution-refusal", "admission.py",
     [("        \"execution_authorized\": False,\n",
       "        \"execution_authorized\": True,\n")],
     "test_complete_manifest_and_admission"),
    ("build-tool-wiring", "manifest.py",
     [("        verify_glib_tooling(artifact_paths)\n",
       "        # mutation: do not bind Meson to the staged GLib tools\n")],
     "test_glib_tool_wiring_drift_is_rejected"),
    ("target-contents", "manifest.py",
     [("        need(targets == expected_targets, \"targets differ from staged evidence contents\")\n",
       "        # mutation: accept targets unrelated to the evidence contents\n")],
     "test_target_contents_and_plan_are_bound"),
    ("plan-targets", "admission.py",
     [("    if expected_plan != plan:\n"
       "        raise AdmissionError(\"campaign plan differs from manifest targets\")\n",
       "    # mutation: accept a valid plan for different targets\n")],
     "test_target_contents_and_plan_are_bound"),
    ("recorder-idle", "manifest.py",
     [("         all(value == \"0\" for value in values[2:]),\n",
       "         all(value in (\"0\", \"1\") for value in values[2:]),\n")],
     "test_recorder_status_uses_actual_kernel_wire_format"),
)


def main() -> int:
    for label, filename, changes, expected_test in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="hevc-deployment-mutation-") as temporary:
            root = Path(temporary) / "experiments/hevc-reference-content"
            deployment = root / "deployment"
            campaign = root / "campaign"
            shutil.copytree(HERE, deployment)
            campaign.mkdir(parents=True)
            shutil.copy2(CAMPAIGN / "controller.py", campaign / "controller.py")
            path = deployment / filename
            text = path.read_text()
            command = ["python3", str(deployment / "tests.py"), "--test", expected_test]
            baseline = subprocess.run(command, capture_output=True, text=True, timeout=90)
            if baseline.returncode:
                raise RuntimeError(f"mutation baseline failed: {label}\n"
                                   f"{baseline.stdout}{baseline.stderr}")
            for old, new in changes:
                text = replace_once(text, old, new)
            path.write_text(text)
            compiled = subprocess.run(
                ["python3", "-m", "py_compile", str(deployment / "manifest.py"),
                 str(deployment / "admission.py")], capture_output=True, text=True,
                timeout=30)
            if compiled.returncode:
                raise RuntimeError(f"{label} did not compile\n{compiled.stdout}{compiled.stderr}")
            result = subprocess.run(
                command, capture_output=True,
                text=True, timeout=90)
            output = result.stdout + result.stderr
            if (result.returncode != 1 or
                    f"FAIL: {expected_test} (__main__.DeploymentTest.{expected_test})" not in output or
                    "FAILED (failures=1)" not in output or "ERROR:" in output):
                raise RuntimeError(f"mutation not distinguished: {label}\n{output[-12000:]}")
            print("PASS named deployment mutation", label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
