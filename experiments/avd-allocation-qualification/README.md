# Allocator candidate: selected runtime qualification passed

AI-assisted implementation/evidence and maintainer self-review. Original allocator
candidate by tankbottoms and AV1 follow-up by z23 remain attributed in PR84/89.

The isolated combined candidate passed the [bounded plan](PLAN.md) on the M1.
Thirty actual decoder commands exited zero across original, temporary candidate
and restored-original stages. All selected outputs were unchanged: **5,112 decoded
frames**, comprising 4,104 individual frame-hash checks and 1,008 frames covered by
counted per-stream digests. Early-export storage/layout checks passed for 168 frames
in each stage. The outer guard completed `ok` with no timeout, fault, wedge or foreign
holder. The original installed and loaded module identities were verified after
restoration; final decoder state is healthy/idle and the lease is released.

| Selected workload per stage | Frames | Oracle |
| --- | ---: | --- |
| H.264 / HEVC / VP9 8-bit / VP9 10-bit serial | 24 / 36 / 48 / 60 | Every frame versus independent software |
| Four codecs sharing one VA display, ordinary | 168 | Per-stream count and whole-stream digest versus independent software |
| Same shared streams, early export | 168 | Same digest/count plus 168 buffer identity/layout checks |
| HEVC RPS_B via VA / direct-V4L2 Gst | 300 / 300 | Every frame versus accepted exact historical output |
| HEVC RPS_E via VA / direct-V4L2 Gst | 300 / 300 | Every frame versus accepted historical output, retaining known errors |

RPS_E's exact **26 VA / 25 Gst wrong-frame sets remain unchanged**. This allocator
repair is not its demonstrated cause or correction. Global strict counts remain
HEVC 144/147, AVC 73/135, VP9 216/305; this selected matrix does not rerun those full
suites. No AV1 hardware decode, live allocation-failure injection, boot test,
installation, package update or shipped-patch edit occurred. Failure/unwind proof
is the actual-source sanitizer work in PR84/89; runtime proof here covers successful
startup/teardown, selected pixels, shared contexts and stable exported storage.

## Evidence

- [Exact input/build/client identities](identities.json), sealed before execution.
- [Normalized runtime evidence](evidence.json): all selected output hashes/digests,
  transitions, actual command exits, full health/guard events, retained HEVC wrong
  sets and final loaded original note. Execution source is commit
  `33c5f28118e7a901f96b9418f0b189818032368b`.
- [Private artifact digest inventory](private-inventory.json) binds the local
  config, stdout/stderr and raw outputs without publishing media or host paths.
- Existing build evidence: [PR84](../avd-allocation-retry/build-evidence.json) and
  [combined PR89](../avd-av1-lifecycle/build-evidence.json). Combined module
  `8caab2852b2d838999ba3774d79faea439c48de151c2a7592c93f13d35dd454d` was selected.

Recheck the published evidence without hardware:

```sh
python3 experiments/avd-allocation-qualification/tests.py
python3 experiments/avd-allocation-qualification/report.py
python3 experiments/avd-allocation-qualification/report-tests.py
```

Eleven controller groups include an actual restoration-health source mutation and
wrong-output rejection. Evidence verification rejects thirteen semantic mutations
including changed pixels, missing runs, false restoration, hidden faults and erased
known failures. Hosted CI never loads a module or opens a device.

This completes #87's bounded qualification, subject to PR review/integration.
A separately reviewed shipped-integration decision remains necessary. Preserve the
unchanged successful-allocation behavior; do not silently adopt the unqualified
reuse alternative. Platform/release, capture backing and HEVC corruption parents
remain open. The owner's private machine authority does not transfer to contributors.
