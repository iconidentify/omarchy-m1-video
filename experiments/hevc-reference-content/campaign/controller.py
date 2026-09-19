#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Campaign controller for the bounded HEVC reference-content observation.

Plans and validates the eight guarded workloads described in CAMPAIGN.md and
refuses to execute any of them without explicit authorization it cannot mint
itself. Planning and validation are offline and side-effect free; this module
opens no device, acquires no lease, loads no module and starts no client.

The constraints encoded here are the documented properties of the merged call
site (gst-callsite/README.md "Known limits for a controller" and SCHEDULING.md),
not invented policy. Where a limit is a property of the experiment rather than a
defect, the check names it so a plan fails review instead of failing on hardware.
"""
from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field, asdict

VECTORS = ("B", "E")
CLIENTS = ("va", "gst")
MODES = (False, True)          # observer copy off / on

# CAMPAIGN.md budgets. Bytes are exact; times are the external deadlines that
# bound acceptance of a result, not interruptions of a stuck memory access.
SNAPSHOT_BYTES = 184320
MAX_SNAPSHOTS = 8
TOTAL_BYTES = 1474560
MAX_MAPPING_BYTES = 368128
COPY_DEADLINE_MS = 20
DRAIN_DEADLINE_S = 2
RUN_DEADLINE_S = 120
CAMPAIGN_DEADLINE_S = 20 * 60

# gst-callsite.h: 1..8 distinct system_frame_numbers per arm.
MIN_SELECTION, MAX_SELECTION = 1, 8

# CAMPAIGN.md initial slots: three selected E writers and one B control per
# client, eight slots in total across both clients.
E_SLOTS_PER_CLIENT = 3
B_SLOTS_PER_CLIENT = 1


class PlanError(Exception):
    """A plan that must not reach hardware. Carries the specific reason."""


class AuthorizationError(Exception):
    """Execution attempted without authorization this module cannot mint."""


@dataclass(frozen=True)
class Authorization:
    """Externally granted permission to run one campaign.

    Every field is supplied by a person or by the guard. The controller never
    constructs this itself, and `execute()` is unreachable without one. An
    instance is not a manifest, a lease or a hardware approval on its own: it
    records that each of those exists and names it for the evidence record.
    """

    operator: str
    guard_lease_id: str
    approved_manifest_sha256: str
    issue_authorization_url: str
    hardware_window: str

    def check(self) -> None:
        missing = [k for k, v in asdict(self).items() if not v]
        if missing:
            raise AuthorizationError(f"authorization incomplete: {', '.join(sorted(missing))}")
        if len(self.approved_manifest_sha256) != 64:
            raise AuthorizationError("approved_manifest_sha256 is not a SHA-256 digest")


@dataclass
class Workload:
    vector: str                 # "B" or "E"
    client: str                 # "va" or "gst"
    copy: bool                  # observer copy on/off
    frames: tuple[int, ...] = ()        # selected system_frame_numbers
    pool_size: int = 0                  # publication boundary for this client
    parameter_set_changes: tuple[int, ...] = ()   # frame numbers of in-band changes

    @property
    def name(self) -> str:
        return f"{self.vector}-{self.client}-{'on' if self.copy else 'off'}"


@dataclass
class Plan:
    run_id: str
    workloads: list[Workload] = field(default_factory=list)
    fresh_element_per_observation: bool = True
    arm_on_streaming_owner: bool = True
    treat_flow_error_as_failure: bool = True
    finish_before_lifecycle_ops: bool = True

    def to_json(self) -> str:
        return json.dumps(
            {"run_id": self.run_id,
             "fresh_element_per_observation": self.fresh_element_per_observation,
             "arm_on_streaming_owner": self.arm_on_streaming_owner,
             "treat_flow_error_as_failure": self.treat_flow_error_as_failure,
             "finish_before_lifecycle_ops": self.finish_before_lifecycle_ops,
             "workloads": [asdict(w) | {"name": w.name} for w in self.workloads]},
            indent=2, sort_keys=True)


def build_plan(pool_size: int, frames_by_client: dict[str, dict[str, tuple[int, ...]]],
               parameter_set_changes: dict[str, tuple[int, ...]] | None = None,
               run_id: str | None = None) -> Plan:
    """Build the eight-workload matrix. Does not validate; call validate_plan."""
    changes = parameter_set_changes or {}
    workloads = []
    for vector in VECTORS:
        for client in CLIENTS:
            for copy in MODES:
                # Only the copy-on workloads select. Off and on perform the same
                # pause/drain, retention, mapping and preallocation; they differ
                # only in the copy, so a control that selected frames would not
                # be the control CAMPAIGN.md specifies.
                selected = frames_by_client.get(client, {}).get(vector, ()) if copy else ()
                workloads.append(Workload(
                    vector=vector, client=client, copy=copy,
                    frames=tuple(selected),
                    pool_size=pool_size,
                    parameter_set_changes=tuple(changes.get(vector, ())),
                ))
    return Plan(run_id=run_id or uuid.uuid4().hex, workloads=workloads)


def validate_plan(plan: Plan) -> list[str]:
    """Return every reason this plan must not reach hardware, or an empty list.

    Collects all reasons rather than raising on the first: a campaign review
    should see the whole set, and a plan fixed one error at a time wastes a
    hardware window per attempt.
    """
    problems: list[str] = []
    names = [w.name for w in plan.workloads]

    expected = {f"{v}-{c}-{'on' if m else 'off'}"
                for v in VECTORS for c in CLIENTS for m in MODES}
    if set(names) != expected:
        problems.append(f"workload set is not the eight {{B,E}}x{{VA,Gst}}x{{off,on}} runs: "
                        f"missing {sorted(expected - set(names))}, extra {sorted(set(names) - expected)}")
    if len(names) != len(set(names)):
        problems.append("duplicate workloads in plan")

    # Properties the merged call site requires of any controller.
    if not plan.fresh_element_per_observation:
        problems.append("one observation per decoder element: a fresh element per observation "
                        "is required because observer_submitted is never reset")
    if not plan.arm_on_streaming_owner:
        problems.append("arm() must happen on the streaming owner thread; arming elsewhere "
                        "turns every output into a dropped frame")
    if not plan.treat_flow_error_as_failure:
        problems.append("refusals are opaque: any GST_FLOW_ERROR in an armed window must be "
                        "treated as observation failure")
    if not plan.finish_before_lifecycle_ops:
        problems.append("lifecycle operations are reported as refused, not prevented: finish "
                        "the arm before flush or a state change")

    total_selected = 0
    for w in plan.workloads:
        if w.copy and not w.frames:
            problems.append(f"{w.name}: copy-on workload selects no frames")
        if not w.copy and w.frames:
            problems.append(f"{w.name}: copy-off control must select no frames; off and on "
                            "differ only in the copy itself")
        if w.frames:
            if not (MIN_SELECTION <= len(w.frames) <= MAX_SELECTION):
                problems.append(f"{w.name}: {len(w.frames)} selections outside 1..{MAX_SELECTION}")
            if len(set(w.frames)) != len(w.frames):
                problems.append(f"{w.name}: selections must be distinct system_frame_numbers")
            if any(f < 0 for f in w.frames):
                problems.append(f"{w.name}: negative system_frame_number")
            # Publication boundary: a hint only succeeds on an allocation that
            # has never been published, so it must land within roughly the
            # first pool-size outputs.
            if w.pool_size <= 0:
                problems.append(f"{w.name}: pool_size must be known to check the publication boundary")
            else:
                late = [f for f in w.frames if f >= w.pool_size]
                if late:
                    problems.append(f"{w.name}: selections {sorted(late)} fall outside the "
                                    f"publication boundary (pool_size={w.pool_size})")
            # An in-band parameter-set change inside the armed window is a hard
            # stream error, not a recoverable refusal.
            window_end = max(w.frames)
            inside = [c for c in w.parameter_set_changes if 0 <= c <= window_end]
            if inside:
                problems.append(f"{w.name}: parameter-set change at {sorted(inside)} falls inside "
                                f"the armed window (ends at frame {window_end})")
            total_selected += len(w.frames)

    if total_selected > MAX_SNAPSHOTS:
        problems.append(f"{total_selected} selected snapshots exceeds the budget of {MAX_SNAPSHOTS}")
    if total_selected * SNAPSHOT_BYTES > TOTAL_BYTES:
        problems.append(f"{total_selected * SNAPSHOT_BYTES} bytes exceeds the total budget "
                        f"of {TOTAL_BYTES}")

    # Slot shape: three selected E writers and one B control per client.
    for client in CLIENTS:
        for vector, want in (("E", E_SLOTS_PER_CLIENT), ("B", B_SLOTS_PER_CLIENT)):
            on = [w for w in plan.workloads
                  if w.client == client and w.vector == vector and w.copy]
            got = sum(len(w.frames) for w in on)
            if got != want:
                problems.append(f"{vector}/{client}: {got} selected slots, expected {want}")

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
        out = []
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
    """Plans a campaign offline; executes only under external authorization.

    `execute` is deliberately not implemented. The campaign needs a reviewed
    deployment manifest, a same-run kernel command/reference join and separate
    hardware authorization, none of which exist. Raising here keeps the refusal
    in code rather than in a comment that a later caller can miss.
    """

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
            "an actual same-run kernel command/reference join remain outstanding. "
            "See CAMPAIGN.md and companion issue #82.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool-size", type=int, required=True,
                        help="capture pool size, that is the publication boundary")
    parser.add_argument("--e-frames", type=int, nargs="+", required=True,
                        help=f"{E_SLOTS_PER_CLIENT} selected E system_frame_numbers per client")
    parser.add_argument("--b-frames", type=int, nargs="+", required=True,
                        help=f"{B_SLOTS_PER_CLIENT} selected B control system_frame_number per client")
    parser.add_argument("--parameter-set-change", type=int, nargs="*", default=[],
                        help="frame numbers of in-band parameter-set changes, if any")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args()

    frames = {c: {"E": tuple(args.e_frames), "B": tuple(args.b_frames)} for c in CLIENTS}
    changes = {v: tuple(args.parameter_set_change) for v in VECTORS}
    plan = build_plan(args.pool_size, frames, changes)
    problems = validate_plan(plan)

    if args.json:
        print(plan.to_json())
    else:
        for w in plan.workloads:
            print(f"  {w.name:12} frames={list(w.frames) or '-'}")
    if problems:
        print("\nPLAN REJECTED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nPlan is internally consistent. It is NOT authorized to run: the campaign "
          "requires a reviewed manifest, a same-run kernel command/reference join and "
          "separate hardware authorization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
