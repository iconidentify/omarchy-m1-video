# Issue 13: M1 retained-journal analysis of the 2026-09-14 resets

The boot-reset cause remains unknown. This is a read-only analysis of the retained
journals on the affected M1 MacBook Pro 13" (J293/T8103), the machine on which the two
resets occurred. **No boot, reboot, module operation, installation, decoder workload or
configuration change was performed for this record, and no hardware lease was taken.**
It does not reproduce the resets and does not qualify boot-enabled installation.

This record supersedes nothing in the [M2 read-only assessment](README.md), which remains
a separate device.

**What was already known.** [Gap status H1](../../GAP_STATUS.md#h1--unexplained-resets-shortly-after-boot-high-priority)
already records that the reset journals show module loading but no AVD panic or oops, that
a PMU report gives one boot error and zero panics, and that pstore was empty. This record
does not rediscover those facts. What it adds is the cross-boot baseline that makes them
discriminating, the observation that both post-reset boots carry the counter, the exact
state of the decoder in the reset boots, separation of the unrelated oopses in the same
history, and the resulting change to the per-attempt capture.

## Sources and identity

Repository base: `4a54925586e4a3fce59e778f7ffb673f9a111725`.
Collector and helper hashes, limits and package versions are in
[m1-boot-evidence.json](m1-boot-evidence.json) (10-boot window, `--boots 10`).
Current host at collection: `7.1.13-3-1-ARCH`, `linux-asahi 7.1.13.asahi3-1`,
`libva-v4l2_request-avd 1.3.r11-2`, Python 3.14.7.
These current versions do not identify any previous boot's installed or loaded software.
The file selected for a future module load was SHA-256
`e50540e1d0fc48c7e0bf9b21ff028758bdb35f94aa7070af00de88e61e5c70e9`; that identifies a
possible future load, not the binary loaded during any boot below.

The journal retains 25 boots. Timestamps below are retained-message bounds, not measured
boot or shutdown times. Original messages, boot identifiers, addresses and hostnames
remain private.

## The two reset boots are retained

Repository history records two resets on 2026-09-14 with the 0001-0005 module loading at
boot, "boots ending ~40 s and ~1 s after start". Both boots are still in the journal:

| Slot | Retained window (local) | Duration | Ends with |
| --- | --- | --- | --- |
| -6 | 2026-09-13 14:29:43 → 2026-09-14 20:41:42 | ~30 h | orderly systemd shutdown |
| -5 | 2026-09-14 20:44:51 → 21:41:03 | ~56 min | orderly systemd shutdown |
| **-4** | **2026-09-14 21:41:53 → 21:42:33** | **~40 s** | **no shutdown sequence** |
| **-3** | **2026-09-14 21:44:40 → 21:44:41** | **~1 s** | **no shutdown sequence** |
| -2 | 2026-09-14 21:46:02 → 2026-09-15 12:57:43 | ~15 h | orderly systemd shutdown |

Slots -4 and -3 match the recorded durations. Both end mid-stream with no systemd
shutdown units, consistent with an abrupt stop. A truncated journal alone cannot
distinguish a reset from a power cut or lost writes; the PMU record below is what
separates them.

## What the reset boots contain

In slot -4 the decoder module is present but **completely idle**. Its entire AVD-related
content is two lines: the platform device joining IOMMU group 5, and
`apple_avd: loading out-of-tree module taints kernel`. There is no decode, no AVD error,
no firmware message, no DART fault, no watchdog, no warning and no oops. The last entries
are ordinary startup work — display coprocessor init, Bluetooth, network, time
synchronisation — and then the log simply stops. Slot -3 is the same shape, one second long.

**Neither reset boot contains a kernel oops, warning or panic.**

## The PMU recorded a boot error, not a panic

The SMC reboot driver reports the platform's own power-management counters, and the line
is emitted only when a counter is non-zero:

| Slot | `macsmc-reboot` report | Reads out the end of |
| --- | --- | --- |
| -24 | `PMU logged 0 boot error(s) and 11 panic(s)` | pre-setup history, hostname still `alarm`; unrelated to this work |
| **-3** | **`PMU logged 1 boot error(s) and 0 panic(s)`** | **slot -4, the 40-second boot** |
| **-2** | **`PMU logged 1 boot error(s) and 0 panic(s)`** | **slot -3, the 1-second boot** |

No other retained boot emits the line at all, including the current one. Each reset is
therefore accounted for by exactly one PMU **boot error**, and by **zero panics** — both
resets, not only the second as previously recorded.

Slot -24 establishes that this counter does record panics when they occur, so zero panics
across both resets is a positive observation rather than an absent capability. Combined
with the empty kernel logs, the evidence is that **these two events were not kernel
panics and produced no kernel-visible fault**. The `pmu_boot_report` category already
present in the collector fires on exactly these two boots; what was missing was reading
the underlying line.

Note the distinction the procedure already draws: ARM performance-counter PMU
initialisation is unrelated, and appears in every boot. So does
`apple-pmgr-pwrstate ... always-on domain msg is not on at boot`, which is present in
every retained boot including healthy ones and is not an anomaly.

## What this does not establish

- **Not a cause.** An idle out-of-tree module can still be a precondition for a
  firmware- or power-level fault. Nothing here rules the module in or out.
- **The counter carries no detail.** It is a count. It gives no reason code, subsystem or
  timestamp, and it is consumed when read.
- **Two samples**, both on one device, one configuration, one evening.
- **Non-reproduction is not reliability.** No PMU boot error has appeared in any boot
  since 2026-09-14, including the period from 2026-09-15 onward with the full 0001-0015
  module loading at boot. That is an absence of recurrence in a handful of boots, not
  evidence that the boot path is safe, and it does not close this issue.
- **Loaded-binary identity is unresolved** for every boot above. The installed file today
  does not attribute a patchset to any previous attempt.

## Distinct events in the same history, not resets

The retained window also contains kernel oopses that are **not** the resets and must not
be merged with them:

- Slot -6, 2026-09-13/14: `avd_submit_job+0x144/0x2b8 [apple_avd]`, in a browser decode
  thread. A decode-path fault in the module that preceded patches 0010-0015, which
  repository history records as fixing a use-after-free and out-of-bounds accesses.
- Slot -5, 2026-09-14 20:47: DART `NO PTE FOR IOVA` translation faults with watchdog
  deferrals, minutes after a mismatched test build failed to load with `Unknown symbol`
  errors. Experimental lab activity; that boot then shut down normally.
- Slot -1, 2026-09-17 14:02: `avd_trace_exit → debugfs_remove` NULL dereference on
  `rmmod`, already captured and root-caused in
  [the failed-attempt report](../../../experiments/hevc-avd-command-capture/failed-attempt-2026-09-17/README.md)
  as a source-generation defect in an experimental trace candidate. Not the shipped module.

None of these occurred in a reset boot, and none is evidence about boot-time behaviour.

## Effect on the proposed experiment

The only signal that fired for either reset was the PMU counter. A boot matrix that
collects kernel journals alone would have recorded nothing for both original events. The
[per-attempt record](../../BOOT_RESET_INVESTIGATION.md) therefore needs the
`macsmc-reboot` counter captured immediately after each attempt's login, before anything
else reads and clears it, and recorded even when it is zero. A kernel-log-only attempt
must be reported as having no discriminating capture rather than as a clean boot.
