# Bounded allocator/startup runtime qualification

AI-generated plan and controller; maintainer self-review, not independent review.
Refs [#87](https://github.com/iconidentify/omarchy-m1-video/issues/87).

Select the **combined PR84 + PR89 candidate**, built from kernel
`94fb23346d522edf53722357c426a3e58030beea` plus the unchanged 15-patch stack
`029f57377a00f3584678f80a8011d8ba7a17c83f1708d9a429d3c91dbb2d0390`.
Candidate SHA256 `8caab2852b2d838999ba3774d79faea439c48de151c2a7592c93f13d35dd454d`;
original SHA256 `e50540e1d0fc48c7e0bf9b21ff028758bdb35f94aa7070af00de88e61e5c70e9`.
The behavior-preserving candidate is selected; the buffer-reuse alternative is not.
Its full build identity is in `../avd-av1-lifecycle/build-evidence.json`.

The owner explicitly saved work, granted the machine for continued work without
repeated saved-work questions, and renewed the instruction to keep progressing.
That session authority covers this temporary qualification, not an installation,
boot change or authority for another contributor. Local Apple M1/T8103,
`7.1.13-3-1-ARCH`, matching `linux-asahi[-headers] 7.1.13.asahi3-1`.
The initial current-boot read-only preflight is healthy/idle; repeat under the lease.

## Inputs and comparisons

Keep installed VA package `1.3.r11-2` fixed (driver SHA256
`ff01edf14cf85f52cf07073da2cf642a9d9b0dde9f055e366478fdb1d2d89a10`).
Compile the existing frame-check, shared-contexts and early-export helpers from
driver `c8e4aecf757c465a583f2b3534f1e617277a4721`; no userspace installation.
Pin client, helper, shared-library, plugin, corpus and expectation files before
running. `identities.json` records normalized exact inputs and expected results.
Private config includes local paths and is sealed by the outer launcher hash.

Run the same ten commands in each of three stages: original baseline, temporary
candidate, restored original. Each stage contains:

- Four generated 640x360 VA streams: H.264 24 frames, HEVC 36, VP9 8-bit 48,
  VP9 10-bit 60. Every output frame hash must equal its independent software decode.
- Those four streams on one shared VA display, ordinary and early-export modes:
  168 frames each. Per-stream frame counts/digests equal independent software;
  early export additionally requires exactly 168 successful storage/layout checks.
- Public HEVC RPS_B and RPS_E, VA and direct-V4L2 GStreamer, 300 frames each.
  Each output hash must equal the accepted PR76-era same-client frame list.
  B stays exact; E's known 26 VA / 25 Gst wrong-picture sets are retained, not
  converted into successes by comparison against their historical output.

Thirty commands and 5,112 decoded-frame comparisons total: 4,104 individual frame
hashes and 1,008 frames covered by counted whole-stream digests. This is a selected
regression matrix, **not** full conformance, a support-count increase, an AV1 decode
claim, proof of boot stability or a solution to RPS_E/CMA fragmentation.
No new live fault injection or memory pressure; failure-path proof remains the
actual-source ASan/UBSan sweeps in PR84/89. Runtime tests cover successful lifecycle,
shared contexts and export identity, not induced allocation-failure recovery.

## Finite execution and recovery

1. New private run directory, durable single-use marker; never replay a failed run.
   Run `qualify.py <sealed-config>` through the unchanged portable `hwguard.py`
   with one host-wide `avd` lease, 1,200-second outer deadline, 0.1-second monitor.
   Current boot is the fixed journal domain; no advancing fault exclusion boundary.
2. Verify every pinned input, original file hash, loaded original GNU build-ID note,
   supported host, healthy idle decoder and live module. Complete baseline first.
3. Healthy/idle check; one ordinary `rmmod apple_avd`, then `insmod` the selected
   exact candidate. No force, retry, installation or boot-policy change. Verify loaded
   candidate note and healthy state before any workload. Every command has 60 seconds;
   every module transition has 15 seconds. Stop on any mismatch/nonzero/error.
4. After candidate work, restore only if healthy/idle: verify loaded candidate note,
   ordinary unload, load the untouched original via `modprobe`, verify original note
   and file hash. Execute the same restored-driver matrix and retain final health.
5. A new fault, stuck task, foreign holder, unrecognized module or failed transition
   ends the experiment. Never force unload, restart a faulty decoder, reset or retry.
   The outer guard may terminate the controller; restoration is **not guaranteed**
   after an abort. Preserve the journal/events and inspect state before any separate
   recovery. A healthy output mismatch may restore the known candidate once, then stops.

Only a final completion marker plus all 30 accepted jobs, clean guard result,
original identity and healthy idle final state can qualify the selected matrix.
Every partial/failed run remains evidence. No public artifact includes raw media,
physical addresses, unrelated process arguments or private host data.

## Offline review

`python3 experiments/avd-allocation-qualification/tests.py` exercises actual
controller run/restore sequencing with substituted host services: refusal, failed
load, wrong output, hardware fault, unknown loaded identity and restored-stage
failure. A mutation removing the actual restoration health check must fail.
The tests do not call sudo, open devices, or prove hardware success.
