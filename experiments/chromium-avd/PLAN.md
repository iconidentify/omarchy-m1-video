# Opt-in Chromium M1 device access — implementation plan

Owner-directed session `codex-m1-chromium-access-20260920`; base
`bc0090a063387213033177f617617d841660fa12`, refs companion #22.
Prepare a reviewable browser patch and non-installing test-build recipe. This
does not complete browser playback or authorize installation/system changes.

Pin Chromium 153.0.8010.36 and the matching Arch Linux ARM packaging revision
`3d45100a45e945ac14f0fbb0c6e67c5540f9e6c9`. That recipe disables VA-API and
enables native V4L2; the experimental build must enable VA-API and select it
explicitly. Chromium's own args.gni permits ARM64 VA-API. Keep the previously
measured process-local three-cache-backends-off environment for later tests.

Implement a default-off GPU feature for this M1 integration. Before sandboxing,
inspect bounded node ranges using lstat and kernel sysfs metadata only: no
device opens, ioctls, decoder probes or arbitrary user-supplied path grants.
Require root-owned character nodes, matching sysfs device numbers and canonical
topology, asahi plus apple,agx-t8103 graphics, and avd plus apple,t8103-avd with
exactly one matching video/media pair. Unknown/missing/ambiguous observations
yield no new permissions. The media node has no `device` symlink on this host;
its canonical parent must match the video node's validated physical device.

Grant only the validated render/video/media node paths, read-only video-node
uevent metadata needed by libva-v4l2_request, and stat-only graphics device/drm
metadata. No recursive sysfs/device grants, camera enumeration permissions,
general directory access, sandbox disabling, synthetic syscall success or
library lifetime changes. Revalidate observations before publishing the set.
Kernel/root-owned device-tree and /dev replacement after GPU startup remain a
trust assumption consistent with Chromium's existing path-based broker model;
hot-unplug/rebinding is outside this experiment and needs review.

Keep device selection independent of Chromium infrastructure so the exact source
can be compiled under bounded-build with synthetic filesystem observations and
meaningful denials. Exercise real broker permission predicates where practical;
label any isolated build support substitutes, and do not call them a full
Chromium build or operating-system sandbox test. Add Chromium-side integration
tests/build wiring and verify patch application to pinned source.

Prepare an isolated build recipe that does not install, run Chromium or acquire
devices. Full browser compilation requires a provisioned build environment and
qualified independent review before hardware use. No configured remote host or
repository runner was found at preparation. The owner later explicitly requested
a build on the existing M1; LOCAL_BUILD.md records that scoped resource plan.
Keep one build worker and the general small-test limits unchanged; do not increase
the local attempt's limits automatically after a failure.

Next runtime gate, only after build/review: fresh whole-current-boot exclusive
guard, disposable profile, normal sandbox and no instrumentation; actual
VaapiVideoDecoder/platform=true before any seek/capture matrix. Preserve the
first failure and stop; other permissions/import restrictions may still appear.
