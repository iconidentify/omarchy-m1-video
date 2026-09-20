# M1 Chrome startup and display-boundary result — 2026-09-20

**Scoped result: sandboxed AGX graphics and software playback work with all three
Mesa disk-cache backends disabled for the test process. Accelerated Chrome
playback remains blocked: the GPU sandbox denies a libdrm device-information
lookup when libva recreates its display.** C1 playback was not attempted.

Owner-authorized session `codex-m1-browser-startup-20260920`, refs
[Chrome #22](https://github.com/iconidentify/omarchy-m1-video/issues/22).
Base `861b54ce6b339900e5e06eb50fd89271b045c313`. The committed [plan](PLAN.md)
records each hypothesis before its new diagnostic, including rejected attempts.
[Review](REVIEW.md) is AI self-review, not independent security review.

## Outcomes

| Row | Measured result | Classification |
| --- | --- | --- |
| Chrome 152 default | AGX graphics; GPU sandboxed=false, GPU threads Seccomp=0 | Startup gate fails |
| Chromium 153 default | AGX graphics; GPU sandboxed=false, GPU threads Seccomp=0; video_decode disabled_software | Startup gate fails |
| Chrome, MESA_SHADER_CACHE_DISABLE=true | Sandbox scheduling violation; Chrome itself restarts GPU three times, then software graphics | Rejected hypothesis; no media |
| Chrome, all three cache backends=0 | AGX graphics/compositing, sandboxed=true, every sampled GPU/renderer thread Seccomp=2, zero GPU crashes | Selected startup pass |
| Software attempt 1 | Process-title collector found no entries and refused before media load | Tool-only failure, preserved |
| Software v2 | Actual FFmpegVideoDecoder/platform=false; 20 seeks, full 12 seconds with zero drop delta, two elements, close/survive, reopen, five 1280x720 captures | Software reference only |
| Installed driver playback | Actual FFmpegVideoDecoder/platform=false; invalid VA display error | Hardware selection fails; zero seeks |
| Display-boundary diagnostic | Same fallback; actual stat64 returns EACCES, then drmGetNodeTypeFromFd returns EINVAL | Instrumented diagnosis only; zero seeks |
| C1 | Unrun after installed-driver gate failed | No candidate attribution |

Every separate whole-current-boot guard ended idle with no holders, timeout,
wedge or recorded AVD fault. The three script failures are `child-error`, never
passes. The cache-off browser recovered internally, so its guard says `ok`;
that is **not** successful browser qualification. The earlier full-desktop
freeze remains unexplained; these test GPU subprocess crashes do not establish
its cause.

## Exact scope and environment

M1 T8103/J293, kernel `7.1.13-3-1-ARCH`, linux-asahi `7.1.13.asahi3-1`, Mesa
`26.1.8-1`, libva `2.24.1-1`, libdrm `2.4.134-1`. Chrome
`152.0.7977.64-1` and Chromium `153.0.8010.36-1` are launched directly from
their installed binaries with disposable profiles on Wayland. Installed VA
driver `1.3.r11-2`, source `db3014f9499694c6f186af7e023de07bd5bc3564`, SHA-256
`ff01edf14cf85f52cf07073da2cf642a9d9b0dde9f055e366478fdb1d2d89a10`.
`identity.json` and `final-state.json` bind actual binaries, loaded-module build-ID
note and module file. The note is not a loaded-memory hash. Guard source commit
`5b5046c` identifies the guard checkout, **not the selected installed VA driver**.

The selected startup environment is:

```text
MESA_DISK_CACHE_MULTI_FILE=0
MESA_DISK_CACHE_DATABASE=0
MESA_DISK_CACHE_SINGLE_FILE=0
MESA_SHADER_CACHE_DISABLE unset
LIBVA_DRIVER_NAME=v4l2_request
LIBVA_DRIVERS_PATH=/usr/lib/dri
```

This is a dated process-local experiment, not an installed launcher or a general
browser recommendation. Shader-cache/performance costs are unmeasured. No
sandbox-disabling or driver-check override flags are used. The inherited playback
runner's `--force-device-scale-factor=1` is test-only on Wayland; actual DPR was
2 and captures correctly retained 1280x720 pixels. Do not persist that flag.

The exact generated 12-second H.264 fixture is SHA-256
`befc52cf1eabc751f35ba254c47943b252cc93601724f015871f114d3da4dc0a`;
its bytes and FFprobe/frame-identity receipts are in the preceding
[client evidence](../m1-clients-2026-09-20/README.md). This archive also carries
the exact fixture. Chrome reports SMPTE170M metadata despite its BT.709 tags;
that remains a separate colour question. No hardware/reference PSNR comparison
was possible, and no browser hardware frame is claimed.

## Why the cache alternatives differ

Mesa's [documented disk-cache disable](https://docs.mesa3d.org/envvars.html#envvar-MESA_SHADER_CACHE_DISABLE)
leaves EGL blob caching available. Versioned Mesa 26.1.8 source shows that a
retained cache object's callback setter can create a queue later. Its creator
calls pthread_setschedparam on the new worker with SCHED_BATCH. Chrome 152's
sandbox scheduling policy accepts self-targeted scheduling, not that other
thread. The observed SIGSYS diagnostic names aarch64 syscall 119 and policy 3;
the subsequent SIGSEGV is in Chrome's trap handler. Core analysis was partly
unsymbolized, so the Mesa caller is a source-supported inference, not a complete
symbolized stack. Three original local cores are retained privately; none is
published.

Disabling all three existing cache backends makes `disk_cache_create()` return
NULL. The DRI callback setter returns on NULL, avoiding both initial and later
cache workers. This alternative passed the actual sandbox-plus-AGX gate and the
software lifecycle row. It changes no scheduling return value or sandbox policy.

## The next blocker, observed directly

The uninstrumented installed-driver row logs
`vaapi_wrapper.cc:1792: Could not get a valid VA display` and selects software.
A final diagnostic forwards the real stat64/drmGetNodeTypeFromFd calls, logs
results and restores errno. It neither substitutes success nor opens a device.
The same GPU PID and fd show:

```text
before sandboxed playback: drmGetNodeTypeFromFd fd=21 ret=2
after sandboxing: stat64 /sys/dev/char/226:128/device/drm ret=-1 errno=13
then: drmGetNodeTypeFromFd fd=21 ret=-1 errno=22
then: Could not get a valid VA display
then: FFmpegVideoDecoder, platform=false
```

The diagnostic's own sampled GPU/renderer isolation passes before media. This
locates the immediate failure; its observation layer is excluded from acceptance
results. Success-path errno is unspecified and is not interpreted as an error.

Versioned libva 2.24.1 calls `drmGetNodeTypeFromFd` before allocating a display;
libdrm 2.4.134 checks that sysfs path. Chrome 152's generic Linux GPU broker
permission list omits it. A VA display used for pre-sandbox enumeration can be
destroyed when its last handle goes away, requiring this later recreation.
The source path and observed denial agree. Upstream versioned source is retained
with licence notices; correspondence to every downstream package patch is not
claimed. Actual installed binary hashes and runtime results take precedence.

**Next owner/decision:** maintainer routing under #22 for a narrowly reviewed
browser integration change that permits the required device discovery/lifetime
while preserving the sandbox. It needs qualified security review and a build on
an appropriately resourced worker. Re-run the display/decoder-selection gate
first; only actual hardware selection permits the planned seek/capture matrix.
Further video/media-node access or import restrictions may follow; fixing this
lookup alone is not yet proven sufficient. Do not move this compatibility fix
into a codec quirk, use a success-forcing shim, or broaden permissions blindly.

## Records and checking

`manifest.json` binds each original record and its published bytes in
`records.tar.gz`. Home paths are redacted; browser logs are filtered to relevant
GPU/VA/sandbox/observer lines with original hashes retained. Profiles, core dumps,
private crash diagnostics and unrelated browser logs are omitted. Source notices
are retained. Dated runners are included; local `avdlab` helpers are referenced
by exact hash because the inspected tree has no distributable licence.
Independent reruns require those helpers or a separately reviewed equivalent.

Run the offline verifier through the shared desktop's bounded-build wrapper:

```sh
tools/bounded-build python3 docs/evidence/m1-browser-startup-2026-09-20/verify.py
```

It reads records without extracting or executing them and checks classifications,
isolation, software operations, capture hashes/dimensions, preserved failures,
the observed denial and final unchanged/idle identity. It does not operate
hardware or qualify general browser playback. `playback.source.sha256` is the
initial pre-parser-fix receipt; `final-runner-hashes.txt` binds the executed v2
runner. The preparation recipe is historical and must not overwrite v2.

No package, persistent browser/desktop setting, kernel/module, reboot or release
changed. Full strict codec pass-set preservation, actual hardware browser output,
colour/adaptation/recovery, final package and boot gates remain open. All owned
test clients exited and guarded leases were released.
