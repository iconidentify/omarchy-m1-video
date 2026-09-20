#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bind a reviewed deployment manifest to one exact refusing campaign plan."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import manifest

HERE = Path(__file__).resolve().parent
CONTROLLER_PATH = HERE.parent / "campaign/controller.py"
BUILDER_PATH = HERE / "build.py"


class AdmissionError(ValueError):
    pass


def _controller_module():
    spec = importlib.util.spec_from_file_location("hevc_campaign_controller", CONTROLLER_PATH)
    if spec is None or spec.loader is None:
        raise AdmissionError("cannot load campaign controller")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _builder_module():
    spec = importlib.util.spec_from_file_location("hevc_deployment_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise AdmissionError("cannot load deployment builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def admitted_document(path: Path, approved_sha256: str, *, live: bool,
                      root_owned: bool = True) -> dict:
    document = manifest.verify(path, approved_sha256, live=live,
                               root_owned=root_owned)
    plan_path = Path(document["plan"]["path"])
    plan_raw, plan = manifest.read_document(plan_path)
    if hashlib.sha256(plan_raw).hexdigest() != document["plan"]["sha256"]:
        raise AdmissionError("campaign plan digest drift")
    if set(plan) != {"execution_authorized", "problems", "run_id", "valid",
                     "client_requirements", "workloads"}:
        raise AdmissionError("campaign plan schema drift")
    if not plan["valid"] or plan["problems"] or plan["execution_authorized"] is not False:
        raise AdmissionError("campaign plan is not a valid refusing plan")
    controller = _controller_module()
    # Reconstruct the plan through the owning implementation, not by trusting
    # the manifest's valid boolean.
    workloads = [controller.Workload(**{
        key: row[key] for key in (
            "vector", "client", "copy", "selector_domain", "selectors",
            "arm_input_index", "last_required_input_index",
            "parameter_set_change_inputs", "gst_pool_size", "va_output_count")
    }) for row in plan["workloads"]]
    rebuilt = controller.Plan(run_id=plan["run_id"], workloads=workloads)
    problems = controller.validate_plan(rebuilt)
    if problems:
        raise AdmissionError("owning controller rejects plan: " + "; ".join(problems))
    if json.loads(rebuilt.to_json()) != plan:
        raise AdmissionError("campaign plan differs from owning controller reconstruction")
    commands = document["commands"]
    if {row["name"] for row in commands} != {row["name"] for row in plan["workloads"]}:
        raise AdmissionError("command/workload matrix drift")
    builder = _builder_module()
    artifacts = {name: Path(row["path"])
                 for name, row in document["artifacts"].items()}
    expected_commands = builder.command_matrix(artifacts, document["corpus"],
                                                document["targets"])
    if commands != expected_commands:
        raise AdmissionError("workload command differs from deterministic builder output")
    return {
        "schema": "omarchy.hevc.campaign-admission/v1",
        "manifest_sha256": approved_sha256,
        "plan_sha256": document["plan"]["sha256"],
        "run_id": plan["run_id"],
        "workloads": commands,
        "live_preflight": live,
        "execution_authorized": False,
        "refusal": "hardware execution remains outside this deployment leaf",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--approved-sha256", required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        result = admitted_document(args.manifest.resolve(), args.approved_sha256,
                                   live=args.live, root_owned=True)
    except (AdmissionError, manifest.ManifestError, OSError, TypeError, KeyError) as error:
        print(f"REFUSED: {error}")
        return 125
    print(canonical(result).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
