# Issue 13: M1 boot matrix, first pass — 2026-09-19

The boot-reset cause remains unknown. This records an **operator-attended, partial**
execution of the [proposed boot matrix](../../BOOT_RESET_INVESTIGATION.md) on the
affected M1 MacBook Pro 13" (J293/T8103), pseudonym `m1-t8103-primary`.

**One attempt was run in each of the four cells. Four of the planned eight attempts
were not run.** Four clean attempts do not establish that the boot path is reliable,
do not close #13 and do not unblock #17.

## Authorization and conditions

The repository owner was present at the console for every attempt, authorized the
campaign and the control configuration change, and confirmed nothing was unsaved
before each transition. The rescue path was verified available beforehand: GRUB
`timeout_style=menu`, `timeout=5`, entry editor reachable for
`module_blacklist=apple_avd`. It was never needed.

Fixed conditions held constant: AC connected, battery 100%, lid open, no external
peripherals beyond the existing setup, no video playing, no other agent's decoder
workload running. A concurrent decode soak from another session was allowed to
complete before the campaign began, and no decoder workload ran during it.

Base `47567cee4dcaf7773b0a69520d6f5d077f7ddf70`, kernel `7.1.13-3-1-ARCH`,
`linux-asahi 7.1.13.asahi3-1`, `libva-v4l2_request-avd 1.3.r11-2`. Selected module
SHA-256 `e50540e1d0fc48c7e0bf9b21ff028758bdb35f94aa7070af00de88e61e5c70e9`; that
identifies a possible future load, not the binary loaded in any attempt. Loaded
binary identity is unresolved for every attempt.

## Results

| Cell | Transition | Decoder | PMU report | Kernel faults | Window | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | cold: shutdown, 30 s off, power on | provably absent | none | 0 | 89.8–689.9 s | clean |
| C2 | warm reboot | provably absent | none | 0 | 570.9–1171.0 s | clean |
| P1 | cold: shutdown, 30 s off, power on | loaded at boot | none | 0 | 84.7–684.8 s | clean |
| P2 | warm reboot | loaded at boot | none | 0 | 620.6–1220.8 s | clean |

No reset, freeze, panic, AVD fault or recovery requirement occurred in any attempt.
`PMU logged …` is emitted only when a counter is non-zero, so "none" is zero boot
errors and zero panics. Per-attempt records are in
[boot-matrix-20260919/](boot-matrix-20260919/), alongside the `RUNBOOK.md` and the
`capture.sh` used. Boot identifiers are published only as truncated hashes; the
mapping to real boot IDs was kept private and is not in this repository.

**Control validity.** Both control attempts were verified decoder-absent, not merely
configured that way: no module, no `/sys/module/apple_avd`, no AVD video node, and
`video0` bound to `apple-isp`. The control policy was `blacklist apple_avd` plus
`install apple_avd /bin/false`; `blacklist` alone stops udev/kmod autoload, and the
`install` line also defeats an explicit modprobe. The boot service is skipped while
its stamp exists and does not modprobe.

**Patched-cell validity.** Both patched attempts were verified decoder-loaded:
module present, `/sys/module/apple_avd` present, `video0` bound to `avd`. The only
AVD-related kernel message in either attempt was the out-of-tree taint line — the
same signature as the two 2026-09-14 reset boots, which also showed a loaded, idle
module and nothing else.

## The observation window does not cover the period that resets

Both original resets ended their boots roughly **40 seconds and 1 second** after
start. The ten-minute idle window begins at login, and the earliest any attempt
reached login was 84.7 s. **No attempt observed the interval in which the historical
resets occurred**, and no attempt can, because a person cannot log in inside it.

That interval is covered by different evidence: whether login was reached at all,
and the PMU counter on the following boot. The idle window evidences post-login
stability only. "Ten minutes observed, clean" should not be read as ten minutes of
coverage of the risky period.

## What this does not establish

- **Not reliability.** One attempt per cell. The procedure requires non-reproduction
  to be reported with its sample count and states it cannot prove boot reliability.
- **Not a cause, and not an exoneration.** Non-reproduction in four attempts does not
  show the module is harmless in every configuration.
- **Conditions differ from 2026-09-14 in ways this matrix does not probe.** The resets
  occurred with patches 0001-0005; these attempts ran 0001-0015. They also followed a
  long uptime with heavy lab activity, a module that failed to load with `Unknown
  symbol` errors, and DART translation faults in the preceding hour. These attempts
  were idle boots from a quiescent machine and reproduce none of that context.
- **Loaded-binary identity is unresolved** for every attempt.

## Not run, and why

Second attempts in C1, C2, P1 and P2 — four of the planned eight — were **not run**.
The owner elected to stop after a complete first pass. They are `not_run`, not
passes. The campaign is therefore a partial screening pass, not the eight-attempt
campaign the procedure proposes.

## Suggested next experiment

More identical idle boots test the cold/warm distinction, which is not what differed
on 2026-09-14. A more discriminating design would condition the machine before the
transition — sustained decode activity and a long uptime before a boot attempt — and
would need its own plan, its own authorization and an operator present. Any such
campaign should capture the PMU counter per attempt, since it remains the only
signal that fired for either original reset.
