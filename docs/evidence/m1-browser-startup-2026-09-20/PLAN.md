# Browser startup and selected playback continuation — 2026-09-20

Owner-authorized session `codex-m1-browser-startup-20260920`, base
`861b54ce6b339900e5e06eb50fd89271b045c313`. Ref companion #22; independently
useful startup scope, not completion of its driver #48/adaptation dependencies.
No competing browser claim or open companion PR was present at preparation.

Compare the two already installed binaries directly: Google Chrome
`152.0.7977.64-1` and Chromium `153.0.8010.36-1`. Use a fresh disposable profile,
Wayland, ordinary defaults and no media. Reuse the prior dated DevTools helper
with explicit binary selection, logging and per-thread Seccomp snapshots. Pin
binary/helper hashes, packages, current boot/kernel/module and installed driver.
Each row has a separate 60-second exclusive AVD guard with whole-boot idle/fault
preflight. A startup diagnostic may truthfully report a failed qualification
gate; a guard fault, timeout, foreign client or script failure stops the campaign.

Record GPUInfo sandbox status, GPU/renderer process and thread isolation,
OpenGL/renderer/compositing/video profile state and relevant startup logs.
Require GPU and renderer Seccomp=2, GPU sandboxed=true and actual hardware
graphics together before proposing playback. Software graphics/fallback does
not qualify. Do not replay the rejected early-sandbox switch alone or disable
isolation. Diagnose negative results against exact available source/package
evidence; label source-version mismatches explicitly. A further diagnostic needs
a concrete hypothesis and recorded plan before execution.

If startup passes, pin that browser and commit a small playback plan using the
existing tagged H.264 fixture, a software reference, actual-DPR compositor
captures and actual decoder/driver/AVD-holder evidence. Preserve identical
content/timestamps/dimensions for comparisons, >=40 dB PSNR without resizing,
20 seeks, full 12-second playback with zero drop delta, reopen and two-element
close/survive. Only then compare installed and C1 under separate finite guards.
Do not run the known large-capture ENOMEM reproduction, HEVC corruption corpus
or adaptive resolution transitions as part of this small row.

Reuse existing tools. Builds and CPU tests use bounded-build, one worker and no
overlap with hardware. No package installation, persistent config, kernel/module
operation, reboot or release/tag is included. Preserve every failed/partial
result; no automatic retry/reset, journal cutoff advance or threshold relaxation.
Publish the measured result or a specific source-level blocker and release the
scope at closeout. Full codec/package/boot qualification remains separate.

## Cache-thread hypothesis after the paired startup result

Both default browsers report working Mesa AGX OpenGL but GPU sandboxed=false
and Seccomp=0, with disk-cache worker threads present. Chromium also defaults
video decode to software; neither qualifies. Both guarded diagnostics exited
normally and idle. No video was loaded.

Mesa's documented `MESA_SHADER_CACHE_DISABLE=true` disables its disk shader
cache while preserving the separate EGL blob-cache interface. Test that one
environment change on Chrome in a fresh profile and 60-second guard. Record the
environment explicitly. Hypothesis: avoiding the early disk-cache worker lets
normal sandbox initialization complete, without the early-sandbox flag or
library permission changes. Require actual GPU/renderer thread Seccomp=2,
sandboxed=true and AGX hardware OpenGL/compositing together. A cache-off pass
would still be a scoped launch alternative with unmeasured cache/performance
cost, not a persistent setting or proof of playback. Preserve a negative result
and stop this hypothesis if it does not satisfy the gate.
