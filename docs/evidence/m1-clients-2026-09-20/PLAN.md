# Bounded real-client continuation — 2026-09-20

Owner-authorized delivery continuation, session `codex-m1-clients-20260920`.
Refs companion #21/#22/#27 and driver #45/#49. Existing parent criteria remain.
No competing claim was present on the two client tickets at preparation.

Keep C1 source `5b5046cbda6892f4a63df0015857a80bd42c17cf`, built driver SHA-256
`dc5315aee9243c0c8f55b0b5904ea83026e32e71f7ed52e76d2e3965ba38b5c9`, installed
kernel/module and client versions from the preceding comparison. Record fresh
identities and whole-current-boot fault/idle preflight. No installation, module
operation, kernel change, suspend or reboot is included.

Generate a deterministic 12-second 640x360 H.264 8-bit MP4 with B frames and
explicit limited-range BT.709 metadata. Reuse the existing VP9 10-bit fixture
for the separately identified P010 player row. Bind all inputs and helper source
by SHA-256. Prepare software references before any decoder run, with bounded
one-worker builds on disk. Do not reproduce the known large-capture ENOMEM case.

## Chrome first

Reuse the local avdlab DevTools transport for a dated, narrowly scoped execution
script. Launch only the installed Google Chrome binary, separate disposable
profile, Wayland and normal sandbox. No hardware-enabling/profile override or
sandbox-weakening flags. Use the browser's default hardware decision; software
reference alone uses `--disable-accelerated-video-decode`.

Run software, installed hardware, then C1 hardware in separate 180-second guard
leases. Enable Media diagnostics before loading the local generated page.
For each row: 20 exact seeks through 1/4/2/6 seconds, one uninterrupted full
12-second playback, two concurrent video elements, remove the second and verify
the first advances, then reopen the first. Capture native 640x360 compositor
regions at the four seek positions and after reopen. Require matching frame
timestamps, no media errors, normal sandbox evidence, actual platform decoder
selection plus AVD holders and selected-driver mapping evidence for hardware.

Compare software/hardware RGB output without resizing, PSNR >=40 dB for each
capture, with no gross blank/green/stale output. Preserve frame/drop counters;
require zero drops for the uninterrupted 12-second segment, measured as a delta
separate from intentional seeks and context operations. Browser/compositor
screenshots are not a photograph of the panel or proof of every played frame.

## mpv follow-through

Reuse avdlab's existing mpv IPC helper. Keep `--no-config`, `gpu-next`, OpenGL,
`vaapi` and `vaapi-copy`. Compare selected software reference captures with
baseline/C1 for H.264 NV12 and the pinned VP9 P010 fixture. Per row, repeat 20
seeks, two loads, and 30 seconds of looped playback; record actual VA mode,
display dimensions and drop deltas. Use separate 180-second guard leases and
the same >=40 dB no-resize comparison. A second player closing must leave the
first advancing in one selected C1 concurrency row.

## Stop and decision

Stop that matrix on its first failed assertion, refusal, foreign client, timeout
or decoder/kernel fault; preserve partial data. No automatic hardware retry,
module recovery, journal-boundary advance or relaxed thresholds. A tool-only
failure is diagnosed offline and requires a recorded corrected plan before a
new attempt. Never represent incomplete rows as passes.

At closeout, publish exact rows completed, actual errors and unrun rows, release
all owned processes/leases, and make an explicit packaging go/no-go decision.
These selected small clips cannot close the broader crop/odd-size/adaptation,
damaged-input/allocation-fallback, full strict-suite or boot/release gates.

## Preparation findings and scoped continuation

The first Chrome software row completed all 20 seeks, the whole 12-second clip
with zero drop delta, the two-element survivor check and reopen. It is preserved
as preparation, not qualification: the 640x360 CSS capture is 1280x720 at the
desktop's actual DPR 2, and the installed browser reports GPU `sandboxed=false`.
A separate guarded diagnostic with no video confirmed GPU `Seccomp: 0`, while
renderer processes have `Seccomp: 2`; no sandbox-disabling launch flag was added.
Its GPU log reports sandbox initialization with multiple threads. This is not
evidence that C1 caused a sandbox problem: C1 was not selected in these runs.

The Chrome qualification matrix stops before its two hardware rows. Preserve
the default-browser sandbox finding for a scoped startup investigation; do not
weaken sandbox flags or count the default GPU state as a passing sandbox gate.
The independent mpv matrix may continue after fresh idle/fault preflight.

FFprobe also showed the initial encoder output retained the BT.709 matrix but
not primaries/transfer metadata. Prepare a separate explicitly tagged copy with
the existing H.264 metadata bitstream filter and prove identical software frame
hashes before player use. Keep the original clip and software preparation.
The player comparison uses the tagged copy; the initial browser result does not.

The first mpv software preparation stopped before any seek when `time-pos`
became available before `hwdec-current`. Its guard ended idle, with no hardware
decode or kernel fault. Preserve that failed preparation. The corrected runner
waits for actual output parameters and an explicit decoder mode before recording
identity; unavailable properties cannot satisfy the condition. Start a new
software preparation row and only advance to hardware after it completes.
