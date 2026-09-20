#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline, fail-closed planner for the bounded HEVC observation campaign."""
from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass, field

VECTORS = ("B", "E")
CLIENTS = ("va", "gst")
MODES = (False, True)          # observer copy off / on

GST_SELECTOR = "system_frame_number"
VA_SELECTOR = "output_ordinal"
VA_OWNER_OPERATIONS = ("send", "receive", "flush", "result", "finish", "close")

# CAMPAIGN.md budgets. Copy-off traverses the same selected observations but
# spends no snapshot-byte budget; the eight copied targets are the copy-on rows.
SNAPSHOT_BYTES = 184320
MAX_SNAPSHOTS = 8
TOTAL_BYTES = 1474560
MAX_MAPPING_BYTES = 368128
COPY_DEADLINE_MS = 20
DRAIN_DEADLINE_S = 2
RUN_DEADLINE_S = 120
CAMPAIGN_DEADLINE_S = 20 * 60

MIN_SELECTION, MAX_SELECTION = 1, 8
E_SLOTS_PER_CLIENT = 3
B_SLOTS_PER_CLIENT = 1


class PlanError(Exception):
    """A plan that must not reach hardware. Carries the specific reason."""


class AuthorizationError(Exception):
    """Execution attempted without authorization this module cannot mint."""


@dataclass(frozen=True)
class Authorization:
    """Names external approvals; it does not grant or verify them."""

    operator: str
    guard_lease_id: str
    approved_manifest_sha256: str
    issue_authorization_url: str
    hardware_window: str

    def check(self) -> None:
        missing = [key for key, value in asdict(self).items() if not value]
        if missing:
            raise AuthorizationError(f"authorization incomplete: {', '.join(sorted(missing))}")
        if len(self.approved_manifest_sha256) != 64:
            raise AuthorizationError("approved_manifest_sha256 is not a SHA-256 digest")


@dataclass
class GstRequirements:
    fresh_element_per_observation: bool = True
    arm_on_streaming_owner: bool = True
    treat_flow_error_as_failure: bool = True
    finish_before_lifecycle_ops: bool = True


@dataclass
class VARequirements:
    fresh_decoder_per_observation: bool = True
    decoder_threads: int = 1
    active_thread_type: int = 0
    single_application_owner: bool = True
    owner_operations: tuple[str, ...] = VA_OWNER_OPERATIONS
    finish_before_close: bool = True
    fatal_cleanup_is_failure: bool = True
    sticky_failure_invalidates_result: bool = True


@dataclass
class Workload:
    vector: str
    client: str
    copy: bool
    selector_domain: str
    selectors: tuple[int, ...]
    arm_input_index: int
    last_required_input_index: int
    parameter_set_change_inputs: tuple[int, ...] = ()
    gst_pool_size: int | None = None
    va_output_count: int | None = None

    @property
    def name(self) -> str:
        return f"{self.vector}-{self.client}-{'on' if self.copy else 'off'}"


@dataclass
class Plan:
    run_id: str
    workloads: list[Workload] = field(default_factory=list)
    gst: GstRequirements = field(default_factory=GstRequirements)
    va: VARequirements = field(default_factory=VARequirements)

    def to_json(self) -> str:
        problems = validate_plan(self)
        document = {
            "run_id": self.run_id,
            "valid": not problems,
            "problems": problems,
            "execution_authorized": False,
            "client_requirements": {"gst": asdict(self.gst), "va": asdict(self.va)},
            "workloads": [asdict(workload) | {
                "name": workload.name,
                "client_contract": client_contract(self, workload),
            } for workload in self.workloads],
        }
        return json.dumps(document, indent=2, sort_keys=True)


def client_contract(plan: Plan, workload: Workload) -> dict[str, object]:
    """Return the deterministic adapter contract for a later runner."""
    selector = {"domain": workload.selector_domain, "values": list(workload.selectors)}
    input_window = {
        "arm_input_index": workload.arm_input_index,
        "last_required_input_index": workload.last_required_input_index,
    }
    if workload.client == "gst":
        return {
            "arm_api": "gst_hevc_callsite_arm_frames",
            "copy": workload.copy,
            "selector": selector,
            "input_window": input_window,
            "publication_pool_size": workload.gst_pool_size,
            "requirements": asdict(plan.gst),
        }
    if workload.client == "va":
        return {
            "private_options": {
                "threads": plan.va.decoder_threads,
                "va_observer_outputs": ",".join(map(str, workload.selectors)),
                "va_observer_copy": int(workload.copy),
            },
            "selector": selector,
            "input_window": input_window,
            "decoded_output_count": workload.va_output_count,
            "requirements": asdict(plan.va),
            "persistent_end_failure": "fatal_quarantine",
            "result_report": {
                "private_option": "va_observer_report",
                "destination": "runner_allocated_exclusive_path",
                "schema": "omarchy.hevc.va-observer-result/v1",
                "publication": "renameat2(RENAME_NOREPLACE)",
                "max_bytes": 8192,
                "require_process_exit_zero": True,
            },
        }
    raise ValueError(f"unknown client: {workload.client}")


def build_plan(*, gst_pool_size: int, va_output_count: int,
               gst_frames: dict[str, tuple[int, ...]],
               va_outputs: dict[str, tuple[int, ...]],
               last_required_inputs: dict[str, dict[str, int]],
               parameter_set_change_inputs: dict[str, tuple[int, ...]] | None = None,
               run_id: str | None = None) -> Plan:
    """Build the paired eight-workload matrix; call validate_plan before use."""
    changes = parameter_set_change_inputs or {}
    workloads: list[Workload] = []
    for vector in VECTORS:
        for client in CLIENTS:
            selectors = gst_frames.get(vector, ()) if client == "gst" else va_outputs.get(vector, ())
            domain = GST_SELECTOR if client == "gst" else VA_SELECTOR
            last_input = last_required_inputs.get(client, {}).get(vector, -1)
            for copy in MODES:
                # Paired off/on rows select the same outputs and execute the same
                # observer path. Only the bounded memcpy operations differ.
                workloads.append(Workload(
                    vector=vector,
                    client=client,
                    copy=copy,
                    selector_domain=domain,
                    selectors=tuple(selectors),
                    arm_input_index=0,
                    last_required_input_index=last_input,
                    parameter_set_change_inputs=tuple(changes.get(vector, ())),
                    gst_pool_size=gst_pool_size if client == "gst" else None,
                    va_output_count=va_output_count if client == "va" else None,
                ))
    return Plan(run_id=run_id or uuid.uuid4().hex, workloads=workloads)


def validate_plan(plan: Plan) -> list[str]:
    """Return every reason this plan must not reach hardware."""
    problems: list[str] = []
    names = [workload.name for workload in plan.workloads]
    expected = {f"{vector}-{client}-{'on' if copy else 'off'}"
                for vector in VECTORS for client in CLIENTS for copy in MODES}
    if set(names) != expected:
        problems.append(f"workload set is not the eight {{B,E}}x{{VA,Gst}}x{{off,on}} runs: "
                        f"missing {sorted(expected - set(names))}, extra {sorted(set(names) - expected)}")
    if len(names) != len(set(names)):
        problems.append("duplicate workloads in plan")

    if not plan.gst.fresh_element_per_observation:
        problems.append("Gst requires a fresh decoder element per observation")
    if not plan.gst.arm_on_streaming_owner:
        problems.append("Gst arm() must happen on the streaming owner thread")
    if not plan.gst.treat_flow_error_as_failure:
        problems.append("Gst GST_FLOW_ERROR in an armed window must fail the observation")
    if not plan.gst.finish_before_lifecycle_ops:
        problems.append("Gst must finish before flush or a state change")

    if not plan.va.fresh_decoder_per_observation:
        problems.append("VA requires a fresh decoder per observation")
    if plan.va.decoder_threads != 1:
        problems.append("VA armed decoding requires decoder_threads=1")
    if plan.va.active_thread_type != 0:
        problems.append("VA armed decoding requires active_thread_type=0")
    if not plan.va.single_application_owner:
        problems.append("VA send/receive/flush/result/finish/close require one application owner")
    if tuple(plan.va.owner_operations) != VA_OWNER_OPERATIONS:
        problems.append("VA owner_operations must cover send/receive/flush/result/finish/close exactly")
    if not plan.va.finish_before_close:
        problems.append("VA observer finish must succeed before avcodec_free_context/close")
    if not plan.va.fatal_cleanup_is_failure:
        problems.append("VA persistent native-end failure must be a fatal quarantined run")
    if not plan.va.sticky_failure_invalidates_result:
        problems.append("VA sticky output failure must invalidate result and repeated finish")

    copied_targets = 0
    for workload in plan.workloads:
        expected_domain = VA_SELECTOR if workload.client == "va" else GST_SELECTOR
        if workload.selector_domain != expected_domain:
            problems.append(f"{workload.name}: selector domain {workload.selector_domain!r} is not "
                            f"{expected_domain!r}")
        if not workload.selectors:
            problems.append(f"{workload.name}: paired copy mode selects no outputs")
            continue
        if not (MIN_SELECTION <= len(workload.selectors) <= MAX_SELECTION):
            problems.append(f"{workload.name}: {len(workload.selectors)} selections outside "
                            f"1..{MAX_SELECTION}")
        if len(set(workload.selectors)) != len(workload.selectors):
            problems.append(f"{workload.name}: selectors must be distinct {expected_domain}s")
        if any(value < 0 for value in workload.selectors):
            problems.append(f"{workload.name}: negative {expected_domain}")

        if workload.client == "gst":
            if workload.va_output_count is not None:
                problems.append(f"{workload.name}: VA output count attached to a Gst workload")
            if workload.gst_pool_size is None or workload.gst_pool_size <= 0:
                problems.append(f"{workload.name}: Gst pool size must be known")
            else:
                late = [value for value in workload.selectors if value >= workload.gst_pool_size]
                if late:
                    problems.append(f"{workload.name}: system_frame_numbers {sorted(late)} fall "
                                    f"outside the publication boundary "
                                    f"(pool_size={workload.gst_pool_size})")
        elif workload.client == "va":
            if workload.gst_pool_size is not None:
                problems.append(f"{workload.name}: Gst pool size attached to a VA workload")
            if workload.va_output_count is None or workload.va_output_count <= 0:
                problems.append(f"{workload.name}: VA decoded output count must be known")
            else:
                late = [value for value in workload.selectors if value >= workload.va_output_count]
                if late:
                    problems.append(f"{workload.name}: output ordinals {sorted(late)} exceed decoded "
                                    f"output count {workload.va_output_count}")

        if workload.arm_input_index < 0:
            problems.append(f"{workload.name}: negative arm input index")
        if workload.last_required_input_index < workload.arm_input_index:
            problems.append(f"{workload.name}: invalid input window "
                            f"{workload.arm_input_index}..{workload.last_required_input_index}")
        negative_changes = [value for value in workload.parameter_set_change_inputs if value < 0]
        if negative_changes:
            problems.append(f"{workload.name}: negative parameter-set input indices "
                            f"{sorted(negative_changes)}")
        inside = [value for value in workload.parameter_set_change_inputs
                  if workload.arm_input_index <= value <= workload.last_required_input_index]
        if inside:
            problems.append(f"{workload.name}: parameter-set change input {sorted(inside)} falls "
                            f"inside armed input window {workload.arm_input_index}.."
                            f"{workload.last_required_input_index}")
        if workload.copy:
            copied_targets += len(workload.selectors)

    for client in CLIENTS:
        for vector, wanted in (("E", E_SLOTS_PER_CLIENT), ("B", B_SLOTS_PER_CLIENT)):
            pair = {workload.copy: workload for workload in plan.workloads
                    if workload.client == client and workload.vector == vector}
            if set(pair) != set(MODES):
                continue
            off, on = pair[False], pair[True]
            if off.selectors != on.selectors:
                problems.append(f"{vector}/{client}: copy-off/on selectors differ")
            if (off.arm_input_index, off.last_required_input_index) != \
                    (on.arm_input_index, on.last_required_input_index):
                problems.append(f"{vector}/{client}: copy-off/on input windows differ")
            if off.parameter_set_change_inputs != on.parameter_set_change_inputs:
                problems.append(f"{vector}/{client}: copy-off/on stream-change inputs differ")
            if (off.gst_pool_size, off.va_output_count) != \
                    (on.gst_pool_size, on.va_output_count):
                problems.append(f"{vector}/{client}: copy-off/on selector limits differ")
            if len(on.selectors) != wanted:
                problems.append(f"{vector}/{client}: {len(on.selectors)} selected slots, "
                                f"expected {wanted}")

    if copied_targets > MAX_SNAPSHOTS:
        problems.append(f"{copied_targets} copied snapshots exceeds the budget of {MAX_SNAPSHOTS}")
    if copied_targets * SNAPSHOT_BYTES > TOTAL_BYTES:
        problems.append(f"{copied_targets * SNAPSHOT_BYTES} copied bytes exceeds the total budget "
                        f"of {TOTAL_BYTES}")
    return problems


@dataclass
class Preconditions:
    """Guard state a campaign requires before its first workload."""

    healthy_idle: bool
    foreign_client_absent: bool
    journal_boundary: str
    module_loaded: bool
    decoder_refcount: int

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.healthy_idle:
            out.append("decoder is not in a healthy idle state")
        if not self.foreign_client_absent:
            out.append("a foreign client holds the decoder")
        if not self.journal_boundary:
            out.append("no fixed journal boundary recorded")
        if not self.module_loaded:
            out.append("decoder module is not loaded")
        if self.decoder_refcount != 0:
            out.append(f"decoder refcount is {self.decoder_refcount}, expected 0")
        return out


class Controller:
    """Reviews offline plans; execution remains deliberately unavailable."""

    def __init__(self, plan: Plan) -> None:
        self.plan = plan

    def review(self) -> list[str]:
        return validate_plan(self.plan)

    def execute(self, authorization: Authorization, preconditions: Preconditions) -> None:
        authorization.check()
        problems = self.review() + preconditions.problems()
        if problems:
            raise PlanError("; ".join(problems))
        raise AuthorizationError(
            "campaign execution is not implemented and is not authorized by this leaf: "
            "a reviewed deployment manifest, full client/dependency/corpus attestation and "
            "proven live target eligibility/workload admission remain outstanding. "
            "See CAMPAIGN.md and companion issue #82.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gst-pool-size", type=int, required=True)
    parser.add_argument("--va-output-count", type=int, required=True)
    parser.add_argument("--gst-e-frames", type=int, nargs="+", required=True)
    parser.add_argument("--gst-b-frames", type=int, nargs="+", required=True)
    parser.add_argument("--va-e-outputs", type=int, nargs="+", required=True)
    parser.add_argument("--va-b-outputs", type=int, nargs="+", required=True)
    for client in CLIENTS:
        for vector in ("e", "b"):
            parser.add_argument(f"--{client}-{vector}-last-input", type=int, required=True)
    parser.add_argument("--e-parameter-set-change-input", type=int, nargs="*", default=[])
    parser.add_argument("--b-parameter-set-change-input", type=int, nargs="*", default=[])
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args()

    plan = build_plan(
        gst_pool_size=args.gst_pool_size,
        va_output_count=args.va_output_count,
        gst_frames={"E": tuple(args.gst_e_frames), "B": tuple(args.gst_b_frames)},
        va_outputs={"E": tuple(args.va_e_outputs), "B": tuple(args.va_b_outputs)},
        last_required_inputs={
            "gst": {"E": args.gst_e_last_input, "B": args.gst_b_last_input},
            "va": {"E": args.va_e_last_input, "B": args.va_b_last_input},
        },
        parameter_set_change_inputs={
            "E": tuple(args.e_parameter_set_change_input),
            "B": tuple(args.b_parameter_set_change_input),
        },
    )
    problems = validate_plan(plan)
    if args.json:
        print(plan.to_json())
    else:
        for workload in plan.workloads:
            print(f"  {workload.name:12} {workload.selector_domain}="
                  f"{list(workload.selectors)} copy={int(workload.copy)} "
                  f"input_window={workload.arm_input_index}.."
                  f"{workload.last_required_input_index}")
    if problems:
        print("\nPLAN REJECTED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nPlan is internally consistent. It is NOT authorized to run: the campaign "
          "requires a reviewed live manifest, proven target eligibility and "
          "separate hardware authorization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
