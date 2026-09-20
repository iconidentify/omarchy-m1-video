# Historical roadmap before the M1 delivery reset

Snapshot of driver issue #7, retrieved 2026-09-20. This entire body is historical;
its old readiness, ownership and completion statements are not current instructions.
The [live scoreboard](https://github.com/iconidentify/libva-v4l2_request/issues/7)
controls current status. Original prose follows; only trailing blank lines are trimmed.

---

## Latest scoped integrations — 2026-09-20

- [Companion PR #112](https://github.com/iconidentify/omarchy-m1-video/pull/112) merged at `03fe18157d75d9dc3856f677921f10b813b258fb`. Child #111 is complete with real H.264 non-VA dispatch/frame isolation, exact return/completion checks and adversarial mutation evidence. Parent #79 and driver #37 retain their remaining configuration, allocation, admission and hardware gates; remap stays disabled.
- [Companion PR #129](https://github.com/iconidentify/omarchy-m1-video/pull/129) merged at `c836cedc3361892dc4f40542821ee170e3a8ca0d` as experimental guarded HEVC campaign tooling and verified observer fixes. All 12 exact-head hosted checks and additional bounded local checks passed. Child #128 and parent #82 remain open: four failed attempts are preserved, and a fresh reviewed deployment, complete guarded campaign and normalized evidence are still required. Driver #42 retains the actual RPS_E correction and full qualification.

These are scoped AI-reviewed integrations, with no new hardware execution, installed package/module change, or support-count increase. The entries below retain historical context; this update supersedes older readiness/draft statements for the named PRs.

**AI disclosure:** AI-assisted maintainer roadmap update at the repository owner's request.

## Current continuation — 2026-09-18, after real-client concurrency execution

Eighteen PRs from this review/implementation round are merged, with contributor commits preserved: companion #56/#74/#78/#80/#83/#84/#85/#88/#89/#90/#91/#92/#93/#94 and driver #92/#93/#95/#96. Adversarial review corrected implementation and evidence issues; all merged heads passed hosted checks. Maintainer corrections are self-reviewed, not independently reviewed. Both community PR queues are clear at this snapshot. Maintainer [PR97](https://github.com/iconidentify/libva-v4l2_request/pull/97) now carries the completed real-client M1 concurrency evidence and is awaiting final-head CI/merge. Live claims govern.

### Concrete progress

- **AVD allocator/startup repairs:** [PR84](https://github.com/iconidentify/omarchy-m1-video/pull/84) corrects failed-allocation/smaller-retry NULL success and HEVC/H.264/VP9 startup leaks; [PR89](https://github.com/iconidentify/omarchy-m1-video/pull/89) proves/fixes AV1 startup unwind. Actual-source sanitizer sweeps and full matching-header module builds pass. [PR91](https://github.com/iconidentify/omarchy-m1-video/pull/91) now qualifies the combined isolated candidate on the M1: **30 commands / 5,112 selected decoded-frame comparisons**, across original/candidate/restored-original stages. H.264, HEVC, VP9 8/10-bit, shared VA contexts and early-export checks preserve outputs. Original installed hash/loaded note verified, final healthy/idle state, no faults/timeouts/wedges/foreign clients; workers and lease released. #81/#86/#87 are complete within those scopes. **Not installed or shipped, not full conformance or AV1 hardware support.**
- **HEVC investigation:** [PR76](https://github.com/iconidentify/omarchy-m1-video/pull/76) preserves eight 300-frame workloads, 44 selected command windows and 1,756 selected words; controls and selected commands agree while RPS_E still corrupts 26 VA / 25 Gst output frames. PR78 source/memory audit covers all 44 actual layouts. PR83's observer is synthetic; PR90 pins the static audit; PR94 now runs four selected helper bodies with explicit stubs, 15 cases and ten semantic mutations. Review removed fabricated pause/generation proof and fixed missing reader-error coverage. **No live coherent-content adapter exists yet.** Equal selected commands do not prove firmware guilt. The allocator runtime run retains the same wrong sets and does not establish an RPS_E cause.
- **H.264 compatibility:** PR74 preserves a rejected unsafe/unlinkable client design with reproducible builds. PR80 tests actual patched FFmpeg VA-off/on builds and real end-callback guards; PR92 adds actual NAL dispatch and SPS/PPS parsers, 34 Annex-B/AVCC calls and meaningful semantic/cleanup mutations. #79 still needs the actual slice queue, issue/cancel boundary and AU/thread/configuration/profile admission proof; those seams remain stubbed in the new dispatch harness. PR56/#43 complete field-feasibility research; companion #14 still needs a validated firmware/reference contract. No blanket profile remap or +49 interlaced-pass promise.
- **Real-client concurrency:** merged driver PR96/#94 supplies the actual FFmpeg worker, independent mixed-codec software oracle and bounded cleanup. A new guarded M1 run passes **180 groups / 2,560 decoded frame hashes / 200 retained frames with 400 extra readbacks**. Guard `2258b641-2057-4f0c-ae5c-6de52b1b51c4` ended healthy/idle, with unchanged original module and no faults/timeouts/holders. PR97's independent archive verifier rejects 16 evidence mutations; local integration is 196/196 sanitizer tests. #36 stays open until its final evidence review/CI/merge and criterion reconciliation. No strict-suite/count/boot/browser promotion; hardware teardown and FFmpeg EOF scope remain explicit.
- **Capture allocation:** driver PR92 preserves coherent early export and correctly classifies CREATE_BUFS ENOMEM. Review rejected a non-coherent flag-only change because imported buffers skip queue cache maintenance and the pinned exporter CPU sync hooks are no-ops. Driver #90 and companion #52/#22 remain open for allocation/export/import/coherence and Chromium qualification. CPU job-table patch0003 is distinct from contiguous decoded capture-plane allocation.

### Contribution queue — concrete implementation remains available

Read the full live issue/comments and native dependencies, claim with a unique session, branch from current default, run meaningful negative tests and open a scoped draft PR. Linux is needed for C/FFmpeg work; no Apple hardware or private media is required for these implementation leaves.

| Leaf and live state at this audit | Concrete next artifact | Parent gate preserved |
| --- | --- | --- |
| [Companion #82](https://github.com/iconidentify/omarchy-m1-video/issues/82) — review ([draft PR105](https://github.com/iconidentify/omarchy-m1-video/pull/105)) | Actual VA/Gst retained-copy integration is in an offline draft; five hosted checks pass. Production call sites, same-run kernel command/reference joins, approved live builds and guarded campaign remain open. Claim released in the issue handoff. | Driver #42 actual RPS_E correction, full codec/concurrency qualification |
| [Companion #79](https://github.com/iconidentify/omarchy-m1-video/issues/79) — ready | Actual slice/issue/cancel callbacks and AU/thread/configuration/profile admission; real NAL/SPS/PPS dispatch is already merged | Driver #37 automatic five-vector selection, recovery and full AVC preservation |
| [Driver #36](https://github.com/iconidentify/libva-v4l2_request/issues/36) — maintainer evidence integration | PR97 archive, independent verifier, CI and criterion-by-criterion acceptance | Wider codec/client/release outcomes remain separate |

[Contributor guide](https://github.com/iconidentify/libva-v4l2_request/blob/avd-fixes/docs/CONTRIBUTOR_START.md) includes a copyable agent prompt. Check [driver ready work](https://github.com/iconidentify/libva-v4l2_request/issues?q=is%3Aissue%20is%3Aopen%20label%3Astatus%3Aready) and [companion ready work](https://github.com/iconidentify/omarchy-m1-video/issues?q=is%3Aissue%20is%3Aopen%20label%3Astatus%3Aready) before claiming. Do not repeat completed synthetic/source research as the real adapter or claim hardware success from a software/model run.

**Other active/reserved work:** driver #22 fuzzing remains claimed by torstenwerner; companion #44 HEVC parameter-set work by SarthakU. Driver #90's existing contributor claim is recorded with its remaining coherence contract blocked; coordinate first. Driver #36's old grudev lease expired at 19:15 UTC; no renewal/PR was found, and all merged work/credits remain. Its offline child #94 is complete through PR96; the new maintainer #36 claim covers completed hardware execution and pending PR97 evidence integration. The old grudev history/credits remain preserved. Field/VP9/device/client/boot/release parents keep their concrete contract/evidence requirements.

**Distribution audit after the merges and hardware run:** 40 open work tickets: 2 ready, 3 in progress, 35 blocked, plus eight epics and roadmap/workflow. Exactly one status per open work item; native open dependency graph acyclic; ready leaves have no open native prerequisites. Completed research and qualifications remain linked history. This is a dated snapshot; live claims can change.

### Evidence and support limits

M1 strict counts remain **HEVC144/147, AVC73/135, VP9216/305**; FRExt default25/69, opt-in High10 27/69. These are conformance vectors, not everyday-video percentages. No count gain from this review/qualification; the short concurrency campaign did not rerun the strict suites. The accepted resource campaigns retain an uninterrupted hour and [882,336 frame comparisons](https://github.com/iconidentify/libva-v4l2_request/blob/b9803ed5290ecb4b48c09482cbc6e943aee08b63/docs/resource-churn-2026-09-17/README.md). M2 Max [PR54](https://github.com/iconidentify/omarchy-m1-video/pull/54) remains limited attributed evidence, not full platform/boot qualification.

The allocator candidate was loaded temporarily and the original restored. No installation, shipped-patch, package, boot-policy or reboot action occurred in this continuation. Future device work needs its own exact finite reviewed plan and exclusive guard; another contributor cannot inherit this owner's private machine authority. Earlier failed recorder attempts and the withdrawn candidate remain evidence, never instructions to replay them.

The product plan and dated closeouts below preserve history; old queues/counts/claims there are superseded by this current handoff and live issue state.

## Product outcome

Build a dependable Linux VA-API driver with broad, truthful codec/backend support and a reproducible Omarchy/Apple Silicon distribution. The historical r11 userspace baseline after [PR #68](https://github.com/iconidentify/libva-v4l2_request/pull/68) is 123 sanitizer cases (including 23 sweeps of 260 injected operation failures); 72,000 generated parser inputs within three cases; HEVC 144/147, AVC 73/135, opt-in High 10 FRExt 27/69 and VP9 216/305; and 864 additional generated hardware frame comparisons. These are M1 results with the companion kernel patchset, not universal hardware support or a speed benchmark.

## Scope and quality contract

- Qualify H.264, HEVC, VP9 and the existing AV1/VP8/MPEG-2 backends by actual profile, bit depth, chroma, device, kernel and client. Compiled-in support is not hardware validation.
- Preserve exact existing passing-vector sets and show raw full-suite denominators. Every mandatory vector for a supported matrix row must match independent reference output; software fallback, expected rejection and untested rows remain separate.
- Eliminate reproducible crashes, memory corruption, silent wrong output and unbounded resource growth in declared supported paths; qualify concurrency, faults, clients and measured performance.
- Kernel capability, client parsing, rendering/HDR, container parsing and distribution setup have separate owning layers. Encoding, DRM and codecs absent from the hardware/API are not promised by this driver roadmap.
- No affected platform row may be called stable while an open P0 reset/corruption/lifetime fault remains. Userspace qualification does not certify boot-enabled installation. Research closure never means a feature was implemented.

## Delivery stages

- **M0 - Reproducible foundation:** Make support claims, test inputs, results and agent coordination reproducible. Exit: baseline schema/corpus/runner and build gates are usable from a fresh checkout. No calendar commitment.
- **M1 - Correctness and isolation:** Eliminate reproducible corruption, memory-safety and lifecycle failures in declared supported paths. Preserve the exact r11 pass sets. Exit requires evidence for each closed defect.
- **M2 - Broader playback compatibility:** Qualify additional formats, clients and devices against the support matrix. Hardware-dependent rows stay experimental until their acceptance evidence exists.
- **M3 - Production release readiness:** Prove stress behavior, measured performance, maintainability, packaging and recovery. A stable claim applies only to qualified platform rows with no open release-blocking faults.
- **M4 - Hardware-dependent expansion:** Discovery and implementation of kernel/firmware-dependent or presently unverified codec features. This is a gated research backlog, not a promise that all devices can decode every format.

## Evidence and maintenance

Starting evidence: [r11 evidence](https://github.com/iconidentify/omarchy-m1-video/blob/main/docs/codec-validation-r11-2026-09-15.json), [codec status](https://github.com/iconidentify/omarchy-m1-video/blob/main/docs/CODEC_STATUS.md), [open gaps](https://github.com/iconidentify/omarchy-m1-video/blob/main/docs/GAP_STATUS.md). The original upstream driver and imported contributors retain their attribution. This roadmap represents the currently known work and includes discovery/triage gates for newly found defects; it is not a guarantee of every codec on every device.

Priorities and S/M/L sizes are sequencing/review aids, not dates or staffing promises. Agents claim one ready leaf task, record a unique session, use an isolated worktree, and coordinate exclusive hardware access. Workstream links and the first-wave queue are attached as the tickets are published.


<!-- roadmap:2026-09-15:ROADMAP -->
## Published workstreams

- [ ] [iconidentify/libva-v4l2_request#9](https://github.com/iconidentify/libva-v4l2_request/issues/9) — Establish a reproducible support contract and test infrastructure
- [ ] [iconidentify/libva-v4l2_request#10](https://github.com/iconidentify/libva-v4l2_request/issues/10) — Prove lifecycle safety, fault recovery and predictable resource use
- [ ] [iconidentify/libva-v4l2_request#11](https://github.com/iconidentify/libva-v4l2_request/issues/11) — Expand and qualify H.264 profiles and coding features
- [ ] [iconidentify/libva-v4l2_request#12](https://github.com/iconidentify/libva-v4l2_request/issues/12) — Resolve remaining HEVC correctness and client parser gaps
- [ ] [iconidentify/libva-v4l2_request#13](https://github.com/iconidentify/libva-v4l2_request/issues/13) — Complete VP9 state, resizing and format coverage
- [ ] [iconidentify/libva-v4l2_request#14](https://github.com/iconidentify/libva-v4l2_request/issues/14) — Qualify additional codec backends and dynamic playback
- [ ] [iconidentify/omarchy-m1-video#7](https://github.com/iconidentify/omarchy-m1-video/issues/7) — Deliver correct playback through real clients and display paths
- [ ] [iconidentify/omarchy-m1-video#8](https://github.com/iconidentify/omarchy-m1-video/issues/8) — Qualify platforms, boot behavior, packaging and releases

## Initial foundation queue (historical)

- [iconidentify/libva-v4l2_request#15](https://github.com/iconidentify/libva-v4l2_request/issues/15) — Define codec, device and client support tiers with explicit release gates
- [iconidentify/libva-v4l2_request#16](https://github.com/iconidentify/libva-v4l2_request/issues/16) — Publish a licensed, checksum-pinned codec regression corpus manifest
- [iconidentify/libva-v4l2_request#17](https://github.com/iconidentify/libva-v4l2_request/issues/17) — Ship a portable hardware guard with an exclusive device lease and durable logs
- [iconidentify/libva-v4l2_request#18](https://github.com/iconidentify/libva-v4l2_request/issues/18) — Expand build and sanitizer CI across supported compilers, architectures and API versions
- [iconidentify/libva-v4l2_request#19](https://github.com/iconidentify/libva-v4l2_request/issues/19) — Add actionable decoder diagnostics without leaking media or user data
- [iconidentify/omarchy-m1-video#9](https://github.com/iconidentify/omarchy-m1-video/issues/9) — Test installer upgrades, failure recovery and uninstall in disposable environments
- [iconidentify/libva-v4l2_request#20](https://github.com/iconidentify/libva-v4l2_request/issues/20) — Establish maintenance, contribution and security reporting procedures

## Claim protocol and sequencing

[iconidentify/libva-v4l2_request#8](https://github.com/iconidentify/libva-v4l2_request/issues/8) is the shared execution guide. Claim one leaf, confirm the session owner, and satisfy native blocked-by dependencies before dependent work. The seven tickets above describe the initial foundation sequence, not the current claimable queue. Use the [live status:ready list](https://github.com/iconidentify/libva-v4l2_request/issues?q=is%3Aissue%20is%3Aopen%20label%3Astatus%3Aready), then check each ticket's claims and native blockers. Coordinate shared test/docs interfaces before editing.

## Milestones

- [iconidentify/libva-v4l2_request milestones](https://github.com/iconidentify/libva-v4l2_request/milestones)
- [iconidentify/omarchy-m1-video milestones](https://github.com/iconidentify/omarchy-m1-video/milestones)

## Completion rules

The initial roadmap introduced 54 implementation and research tickets. New bounded children and discoveries extend that backlog; the contributor-wave snapshot and live queues above give the current distribution state. All eight workstreams are native sub-issues, and leaf blockers are native GitHub dependencies. Re-triage discoveries into linked children; do not delete failing vectors, convert blocked research into support, or close this roadmap just because the ticket list exists. The release qualification ticket [iconidentify/omarchy-m1-video#27](https://github.com/iconidentify/omarchy-m1-video/issues/27) owns the final evidence-backed support decision.

## API lifetime completion — 2026-09-16

The public API lifetime audit [#23](https://github.com/iconidentify/libva-v4l2_request/issues/23) is complete in [PR #66](https://github.com/iconidentify/libva-v4l2_request/pull/66): 22 new lifecycle regressions, 75 total sanitizer cases, 864 exact generated hardware frames and unchanged full codec passing sets. [Evidence](https://github.com/iconidentify/libva-v4l2_request/blob/3d620db0417467c55d8600f5c79947cca71fdcf6/docs/api-lifetime-validation-2026-09-16.json) retains the known failures and self-review limitation. No codec support or boot-stability promotion follows from this completion.

The follow-on #35 audit is now complete (below); #36 is in progress under grudev’s confirmed claim for initial offline concurrency work, with its separate qualified-hardware gate. #40's code prerequisites are satisfied, but full completion still needs a qualified non-M1 converter backend. Native dependency links are retained. Other roadmap workstreams remain open; this is a scoped completion, not a declaration that all earlier tracking gaps are reconciled.

## Request and buffer cleanup completion — 2026-09-16

[#35](https://github.com/iconidentify/libva-v4l2_request/issues/35) is complete in [PR #68](https://github.com/iconidentify/libva-v4l2_request/pull/68), merged as `1edeb1560525d959b13c85b7b3e4fef793e2e3d1`. Twelve reproduced failure sequences were fixed; the final 123 sanitizer cases include 48 new cases and 260 operation-index injections across 23 sweeps. The final M1 candidate passed 864 generated frame comparisons and preserved every prior full-suite passing vector. [Evidence](https://github.com/iconidentify/libva-v4l2_request/blob/1edeb1560525d959b13c85b7b3e4fef793e2e3d1/docs/failure-cleanup-validation-2026-09-16.json) retains the known AVC non-green fallback result, hardware/model limits and maintainer self-review disclosure. No install, module operation, codec support promotion or boot qualification occurred.

Direct child #41 has its offline tooling merged and both M1 1,000-cycle campaigns complete; its interrupted soak requires a fresh uninterrupted hardware window. #45’s code prerequisites, including #16, are accepted; its hardware campaign remains outstanding; #49 on #48. Companion installer #20 has its code prerequisites satisfied but remains blocked on task-specific suspend authorization/scheduling. Release qualification installer #27 remains blocked by its other gates. Native links are retained; the reliability epic and roadmap remain open.


<!-- community-review-closeout:2026-09-16 -->
## Community contribution review completion — 2026-09-16

All six reviewed community PRs are merged, preserving laihenyi, edulmartins, grudev and ianrelecker's commits: driver [#64](https://github.com/iconidentify/libva-v4l2_request/pull/64) → [#67](https://github.com/iconidentify/libva-v4l2_request/pull/67) → [#65](https://github.com/iconidentify/libva-v4l2_request/pull/65), companion [#32](https://github.com/iconidentify/omarchy-m1-video/pull/32) → [#33](https://github.com/iconidentify/omarchy-m1-video/pull/33), followed by driver [#69](https://github.com/iconidentify/libva-v4l2_request/pull/69).

Driver #63/#34 and companion research #11/#10 are complete with criterion-by-criterion evidence on each ticket. Review remediation fixed false-positive audit tests, malformed allowlist/date handling, ABI/install guidance and checks, VP9 queue/session/recovery assumptions, and H.264 evidence parsing/overclaims. Driver validation includes 127 sanitizer tests, 30 audit fixtures, software and two-layout install checks; all 11 default CI jobs pass with runtime warnings reduced from 11 to zero. H.264 evidence adds 12 regression tests and a clean 135-vector offline prefix scan.

This batch changes CI/build/test/docs/research, not decoder source or installed packages. No new codec support, hardware, boot or release qualification. Companion #14/#16 and driver #44 remain blocked on the explicit kernel/firmware contracts and authorization/evidence; companion #19 is in progress under davefano’s active reservation after #9’s verified maintainer closeout. Parent indexes are updated, native dependencies retained, all workstreams/release gates remain open. Original contributions were independently reviewed; maintainer corrections were self-checked.



## Resource tooling handoff — 2026-09-16

[#41](https://github.com/iconidentify/libva-v4l2_request/issues/41)'s offline contribution is merged in [PR #69](https://github.com/iconidentify/libva-v4l2_request/pull/69) (`19c375e4e4dcf50cd99e83bdf5e8b6db1d14932c`): 3,000 lifecycle cycles, in-process checks at all 260 fault injections, and a corrected bounded process-local recorder. All 11 PR CI checks pass; local sanitizer count is 127. #41 remains OPEN/BLOCKED for real-device resource checkpoints, exact hashes and its required 60-minute guarded soak. Its child checkbox remains unchecked. No hardware, decoder source, installed-package or support-status change. Companion [PR #34](https://github.com/iconidentify/omarchy-m1-video/pull/34) reconciles the accepted research wording in codec/gap docs; both source checkouts are being fast-forwarded to the merged defaults.


Maintainer follow-up [PR #70](https://github.com/iconidentify/libva-v4l2_request/pull/70), merged as `963a031b31a254bad1177e0795ba1f9c8ec08dd4`, makes owned process-group cleanup idempotent. A regression rejects any attempt to revisit a released numeric group ID; local recorder regressions and all current-head CI checks pass. This corrects the maintainer cleanup helper from #69. #41 remains open/blocked for its hardware campaign; no hardware or production decoder change.


## Current resource/concurrency handoff — 2026-09-16 20:30 UTC

[#41 PR #71](https://github.com/iconidentify/libva-v4l2_request/pull/71) now contains two complete 1,000-cycle M1 campaigns, 97,920 exact hardware frame comparisons total including warmup, flat FD/dma-buf/mapping/RSS measurements, allocator bounds and a hash-verified raw archive. [Evidence](https://github.com/iconidentify/libva-v4l2_request/blob/1cc871664731a8e06a44f33c65d23b73ecb37373/docs/resource-churn-2026-09-16/README.md). The hour-long soak was stopped by the guard on a foreign decoder client after 616.048 measured seconds; it remains failed/incomplete. A later read-only preflight is idle with no new kernel fault. A fresh uninterrupted window is pending user video-playback coordination; no module reset/reload/reboot or installation occurred. PR #71 merged as `0758361796905981d8855988f71f4c2ca5a66ff4` after all 22 protected push/PR checks passed. The ticket and child checkbox remain open; a fresh hour, exact-build codec comparison, updated interruption check and final qualification-evidence integration remain pending.

[#36 PR #72](https://github.com/iconidentify/libva-v4l2_request/pull/72) received an adversarial changes-requested review: two forced legal schedules reproduce harness races, the process digest oracle accepts forged output, and deadline/cleanup/TSan reporting need correction. Contributor grudev acknowledged all six findings and is applying fixes under the existing claim. No competing branch edits or #36 hardware claim. Package provenance [installer #19](https://github.com/iconidentify/omarchy-m1-video/issues/19) is reserved by davefano under its active claim; it is no longer unclaimed ready work.

Native dependencies remain intact. #47 still has open #36/#24 prerequisites; installer #27 has other open qualification gates. No parent/roadmap/release completion or stable-support promotion follows from these partial results.


<!-- live-handoff:20260916T2130 -->
## Current accepted-work and review status

Current handoff, 2026-09-16 21:30 UTC:

- Driver #16 (corpus, PR #61) and #19 (diagnostics, PR #59) are accepted and closed after verifying their merged evidence and independent reviews. Foundation/reliability child indexes are reconciled; parent outcomes remain open.
- #41’s second guarded attempt ran from 21:07 to 21:31 UTC and was interrupted by another decoder client after 1,426.146 measured seconds / 6,063 cycles. Resources stayed flat, but the run is failed; the earlier 616-second attempt is also preserved. A later read-only guard was healthy and idle. [Draft PR #76](https://github.com/iconidentify/libva-v4l2_request/pull/76) contains both failed attempts and a verified 97-member archive. No decoder workload/lease is active. A fresh exclusive hour and selected-build follow-ups await user coordination to fully close video apps.
- Contributor PRs #72 (concurrency), #73 (HEVC boundary) and #75 (fuzzing) have concrete changes-requested reviews. Their author claims remain respected. Installer [PR #35](https://github.com/iconidentify/omarchy-m1-video/pull/35) is merged as `abb853c` after maintainer remediation, exact-head CI and two further clean matching package builds; installer #19 is closed. No pending PR is counted as accepted work.
- Driver #27 and installer #12 are now ready for their bounded offline research. Other dependent tasks still need their listed hardware, authorization, design or open implementation gates; closed corpus/diagnostics tickets do not satisfy those gates.
- HEVC [child #74](https://github.com/iconidentify/libva-v4l2_request/issues/74) is accepted as blocked on #26/#40/#28, hardware and corpus terms, and is included in the HEVC index. No wider-chroma support is promoted.

No package installation, module operation, kernel edit, reboot, boot qualification or stable-support promotion occurred.

## Maintainer integration closeout — 2026-09-16

All five open contributions are now integrated: driver PR #78 (preserving #72/#73/#75/#77) at b775d9b, and companion PR #38 (preserving #36) at cca0e19. Both repositories have zero open PRs at closeout. All required exact combined-head checks passed before merge; 158 local sanitizer cases, actual TSan, four fuzz smokes, software helpers and disposable package-root checks also passed.

H.264 discovery #27 is closed with corrected AVC and FRExt inventories; this adds no support claim. #22 retains long campaigns/coverage/minimization evidence, #28 retains guarded HEVC qualification, and #36 retains measured in-driver overlap plus real-worker/hardware qualification. Companion #12 remains open on newly linked driver #79; companion #37 tracks a separately authorized firmware experiment. No release tier or package pin was promoted. Older local staging work is already integrated/superseded; explicitly experimental padding/DPB work and local build overrides were preserved, not mistaken for qualified fixes. No hardware/system action occurred.


## Current roadmap reconciliation — 2026-09-17 UTC

Driver #79 and companion #12 are complete after the reviewed dimension fix (#80, `299d293`) and guarded hardware evidence (#81, `27da69d`) merged. Both VP9 profiles expose/enforce 64..4096 for the selected backend, 864 generated hardware frames pass, and every exact r11 passing-vector set remains unchanged. Companion #37 remains open/blocked for a separately authorized firmware experiment; no sub-64 support or higher pass count is claimed.

Codec-feasibility research #33 was already delivered in PR #62 (`9e4b42e455d3cbc01bbb1d9b3809ce15bdc36752`). Its inventory, criteria and successful exact merge-commit CI are reconciled; #33 is closed as completed research. Linked implementation/qualification tickets stay open.

[Driver PR #82](https://github.com/iconidentify/libva-v4l2_request/pull/82) is merged at `b9803ed5290ecb4b48c09482cbc6e943aee08b63`; [#41](https://github.com/iconidentify/libva-v4l2_request/issues/41) is complete. The selected #80 build passed a fresh 3,600.167885861-second soak (16,298 measured cycles / 783,264 exact frames), both fresh 1,000-cycle campaigns, intentional-client-exit/recovery checks and unchanged exact r11 codec pass sets. Accepted resource campaigns total 882,336 exact frame comparisons and 18,382 surviving-image checks. All guards ended healthy/idle; complete raw evidence and 1,394 verified archive members are [published](https://github.com/iconidentify/libva-v4l2_request/blob/b9803ed5290ecb4b48c09482cbc6e943aee08b63/docs/resource-churn-2026-09-17/README.md). All 11 jobs passed in both exact-head CI runs. Review of this evidence is maintainer self-review; previous failed soaks and the known AVC non-green fallback verdict remain explicit.

The user-authorized existing-module reload occurred once at 02:16:40 UTC after saved-work confirmation; the earlier timeout and fixed recovery boundary are preserved. No installation, package-pin change, kernel source edit or reboot occurred. Hardware work ended and released the decoder at 03:38:46 UTC. All implementation claims from this acceptance work are released. This qualifies the fixed selected-build M1 workload; it does not qualify concurrency, browsers/displays, throughput, boot stability or new codec support.

The current contributor-wave section above supersedes the earlier 36-ticket snapshot: five bounded offline children were published (four currently ready, one claimed), active claims are retained, and the remaining parent gates are explicit. Ticket counts include parents/children and are not estimates of remaining effort.

There are no open PRs in either repository at this closeout. Companion [PR #40](https://github.com/iconidentify/omarchy-m1-video/pull/40) is merged at `f50a4a4c88b03ea1e10acf734a53c3a0ee9b2519` after independent contribution review, maintainer documentation/provenance corrections and exact-head offline CI. It preserves all contributor commits and 18 raw records, accepting an M2 Max inventory and reported three-vector smoke output. The 238 published frame records match independent M1 output, but exact execution/module/patch attribution remains unverified; paired campaign summaries lack independent run linkage. #18 remains open with its contributor campaign now labeled in-progress; installed-stack/boot acceptance remains outside that merge. No new codec totals, full M2 Max qualification or stable tier is claimed. Maintainer session `codex-pr40-integration-20260917` is released; no maintainer hardware/system operations occurred.

#22 still needs full 24 CPU-hour campaigns per target and coverage/minimization evidence; #36 still needs proven in-driver overlap and a real hardware worker/campaign. Codec expansion, HEVC correctness, client/display validation, performance and boot/platform qualification remain in their owning tickets. The roadmap, all epics and companion release #27 remain open.


## New contribution review closeout — 2026-09-17

Driver #87 merged at `c3cad962386ffc49835f8778d4e375f5c8b334b9`; companion #48 at `64e2647c12ddea869f181c0b2cfa294685d9a8fe` and #49 at `845c332e14c343bbff3ca8fd470ec77dfc2f05ff`. The contributor-wave section above is the current queue snapshot (39 open task/research tickets), superseding historical pending-review and overlap statements below it. Both source checkouts are fast-forwarded to the merged defaults. The original #46/#47/#86 histories are preserved. Hardware-dependent parent outcomes and all workstreams remain open.
