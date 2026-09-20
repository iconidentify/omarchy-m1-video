# Contribute to the next codec and AVD phase

Help make more videos decode correctly on Linux. The next work combines focused
client fixes with Apple Video Decoder (AVD) source analysis, reference-control
tracing and executable checks of proposed state transitions. We build on the
Asahi Linux AVD driver, [eiln's original reverse engineering](https://github.com/eiln/avd),
libva-v4l2_request and the contributors credited in both repository READMEs.
This is an unofficial project; keep reports and coordination in these forks.

## Start without Apple hardware

The offline tasks below can be completed without a decoder, privileged access,
installation or private lab data. Linux is needed for C/FFmpeg builds; source
analysis and standalone Python tools can use any suitable host. A synthetic
model is not hardware validation. New codec support still needs its separate
reviewed hardware evidence.

The [live roadmap](https://github.com/iconidentify/libva-v4l2_request/issues/7)
controls current status. These are entry points, not permanent reservations:

## Current contribution priorities — 2026-09-20

The owner has selected [M1 playback delivery](M1_DELIVERY.md) as the next milestone.
Use that scoreboard and the live roadmap instead of older contributor-wave tables.
The first step reuses existing decode/drain/seek/reopen tests on one pinned
candidate; the next results must address actual mpv/Chrome playback and recovery.

Existing #128 HEVC and driver #22 fuzzing ownership remain in their live tickets.
#128 has one bounded campaign decision point; its merged tooling is not a
corruption fix. New owner-directed platform/advanced-codec expansion is deferred
until the candidate decision. Independently contributed work and its credits are
preserved; coordinate before changing another contributor's scope.

Use `tools/bounded-build` for local builds and CPU tests on the shared desktop,
with one build/test worker. Hardware has its separate exclusive guarded window.
No general-purpose test framework is required for the first comparison.

Check the open ready queues in the
[driver](https://github.com/iconidentify/libva-v4l2_request/issues?q=is%3Aissue%20is%3Aopen%20label%3Astatus%3Aready)
and [companion](https://github.com/iconidentify/omarchy-m1-video/issues?q=is%3Aissue%20is%3Aopen%20label%3Astatus%3Aready),
then read the complete ticket and current claims. A blocked parent is not made
ready by this prioritization, and a merged experiment is not shipped support.

## Claim one bounded task

1. Read the ticket, all comments, native dependencies, repository `AGENTS.md`,
   [CONTRIBUTING.md](../CONTRIBUTING.md) and the
   [shared workflow](https://github.com/iconidentify/libva-v4l2_request/issues/8).
2. Fork the owning repository and branch from its current default: driver
   `avd-fixes`, companion `main`. Record the actual fetched base SHA. Keep changes
   in an isolated checkout/worktree.
3. Post a unique-session claim with files, a concrete plan and a lease of at most
   24 hours. Re-read comments/open PRs before editing; an assignment alone is not
   a claim. Coordinate shared test registration and common driver files.
4. Open a small draft PR early. Link the parent with `Refs`, keep the child's
   acceptance table current, and preserve original authorship and source/fixture
   provenance. People and coding agents follow the same review requirements.
5. Run meaningful positive and negative tests and required CI. Record what was
   not run. Close only the child after its own evidence and code are merged;
   parent hardware/feature gates remain open.

If you cannot edit labels, your claim comment is still useful: ask a maintainer
to reconcile the status. Do not create a duplicate ticket just to obtain an
assignment. Review routing goes through `iconidentify`; a named routing contact
is not a claim that independent technical review has already happened.

A useful starting prompt for a coding agent:

> Work on <full ready-child issue URL>. Read its complete discussion, native
> dependencies, AGENTS.md, CONTRIBUTING.md and the live shared workflow first.
> Confirm the ticket is unclaimed, post a unique-session claim, and use an isolated
> branch from the current default SHA. Implement only its bounded offline scope.
> Preserve existing behavior and other contributors' work. Add tests that detect
> the claimed failure, record exact results and limitations, and open a draft PR.
> Do not promote hardware support from a model or close the parent. Coordinate
> shared files and release or renew the claim at handoff. Follow the repository's
> separate authorization rules before any hardware or system action.

## What the next phase can establish

The selected M1 build retains **HEVC 144/147, AVC 73/135 and VP9 216/305** strict
hardware passes. Its resource acceptance includes an uninterrupted one-hour
soak and **882,336 exact frame comparisons across the accepted campaigns**.
[Published evidence](https://github.com/iconidentify/libva-v4l2_request/blob/b9803ed5290ecb4b48c09482cbc6e943aee08b63/docs/resource-churn-2026-09-17/README.md).
These are conformance/workload results, not everyday-video success percentages,
universal stability or counts of unique videos. The M2 Max contribution is
[limited reported smoke evidence](https://github.com/iconidentify/omarchy-m1-video/blob/f50a4a4c88b03ea1e10acf734a53c3a0ee9b2519/docs/evidence/issue18/t6021-review.md),
not full multi-device qualification.

Paired HEVC captures now show matching selected commands and controls while RPS_E
still produces wrong pixels. The next discriminating observation is coherent
reference content with proven writer identity and quiescence; equal commands do not
prove firmware guilt. The source-proven allocation retry/startup defects have an
isolated candidate that preserved 5,112 selected decoded frames across original,
candidate and restored-original stages ([evidence](https://github.com/iconidentify/omarchy-m1-video/blob/c47ee15a6d4c4809377af11d2e70f2bd31be5ad6/experiments/avd-allocation-qualification/README.md)).
This is selected runtime qualification, not a full conformance rerun or shipped fix.
Accepted RPS_E runs had no allocation errors, and its known wrong sets remain, so
this candidate is not an established corruption fix. VP9 resizing still needs its validated
state-preservation contract. H.264 interlacing is a feasibility
question: the original reverse engineer reports hardware limitations. Do not
promise to recover all 49 failing Main-profile vectors or assume a missing
kernel implementation proves either firmware capability or impossibility.

Device owners can coordinate qualification through the owning tickets. An issue
claim is not a decoder lease. Kernel instrumentation, module operations,
installation, suspend and boot testing retain their explicit authorization and
recovery gates. Hardware evidence must retain the exact source/build identity,
corpus lock, command/environment, guard run ID and fixed journal boundary. Keep
original failures and unknowns; never reconstruct historical records as measurements.

AI-assisted contribution planning; original source and contributor credits remain intact.
