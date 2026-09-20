# M1 client delivery — 2026-09-20

**Selected mpv playback passes; an exact local demonstration is delivered.
Chrome hardware qualification is blocked before either hardware row.** No
package, module, kernel, boot or desktop setting changed. This is an experimental
result for two generated clips, not a stable release or arbitrary-video support.

Owner-authorized session `codex-m1-clients-20260920` follows the merged
[reset](../m1-delivery-2026-09-20/README.md). The [committed plan](PLAN.md) records
the original scope, preparation failures, corrected preparations and explicit
stop decisions. Driver/source pins remain unchanged. All owned processes exited
and guard leases were released; final whole-boot inspection found no decoder
faults, stuck tasks or holders. Installed driver/module hashes stayed unchanged.

## What passed

M1 T8103/J293; kernel `7.1.13-3-1-ARCH`, linux-asahi `7.1.13.asahi3-1`, mpv
`1:0.41.0-6`, FFmpeg `2:9.0.1-4`, Mesa `26.1.8-1`, libva `2.24.1-1`.
Boot `d0a40094-af95-4bea-8dc2-85693b2f727f`. Installed source `db3014f9499694c6f186af7e023de07bd5bc3564`;
C1 source `5b5046cbda6892f4a63df0015857a80bd42c17cf`. Full binary/module hashes,
build-ID note limitation, package identities and fresh preflight are in archived
`identity.json`; final identities are in `final-state.json`.

| Driver | Input | Actual modes | Completed evidence |
| --- | --- | --- | --- |
| Installed r11 | H.264 8-bit, NV12 | `vaapi`, `vaapi-copy` | Both rows pass |
| Installed r11 | VP9 10-bit, P010 | `vaapi`, `vaapi-copy` | Both rows pass |
| C1 | H.264 8-bit, NV12 | `vaapi`, `vaapi-copy` | Both rows pass |
| C1 | VP9 10-bit, P010 | `vaapi`, `vaapi-copy` | Both rows pass |

Each of eight rows completed 20 exact seeks, two file reloads and over 30 seconds
of looped playback. Total: **160 seeks, 16 reloads, 241.85 measured seconds**,
zero observed render/decode drop deltas. IPC reports actual VA selection and
`/proc/<pid>/maps` identifies the selected driver. All **48 selected rendered-window
PNGs are byte-identical** to their matching software references. Images are
1750x986 window renders of 640x360 content; comparisons do not resize images.
This proves selected rendered output, not every displayed frame or panel pixels.
Two software reference rows have separate records and are excluded from hardware
counts. Pixel format and color metadata are recorded per row.

The C1 direct-VA two-player row also passed: both selected the C1 driver, the
second exited normally, and the survivor advanced from 2.133 to 4.167 seconds
with zero drops. This is a close/survive result, not damaged-input recovery.

## Local demonstration and packaging decision

The owner has `omarchy-m1-mpv-c1-20260920.tar.gz` and its extracted directory in
the retained local artifacts. Its SHA-256 is
`86c7900d5331f29a707735e257eb413e27bc586bed865bf471d0cb3e480a6928`.
The archive includes the exact tested C1 binary, full corresponding driver
source with original licences/build files, the unmodified source guard, a
launcher and both generated clips. It is not a published release asset.

From the extracted directory, `./run-mpv` plays the 12-second H.264 sample;
`./run-mpv samples/vp9-10.webm` plays the short P010 sample. `./run-mpv --check`
validates files and the exact installed stack without opening the decoder.
Only the two bundled clip hashes are accepted. Other hardware video must be
closed. The launcher uses OpenGL, VA copy, no audio and a finite exclusive guard;
press q to exit. Logs go to the user's state directory. No installation or
rollback operation is needed; removing the directory removes the demo.

Checksum and wrong-version negative cases both refused before guard launch.
The packaged H.264 sample then completed with actual `vaapi-copy` selection and
an idle successful guard exit. Those logs are separate from the comparison rows.
The checksum manifest is an integrity record, not a signature. Source identity
is bound by the bundle manifest; the unchanged guard reports a null Git revision
when run from the unpacked source. No source revision is fabricated.

**Go: retain this experimental local demonstration. No-go: change the installer
pin, advertise everyday stability or publish a stable release.** Full strict-set
preservation, odd/cropped dimensions, resize/fullscreen, format transitions,
damaged inputs/allocation fallback and boot/reset confidence remain open under
[#21](https://github.com/iconidentify/omarchy-m1-video/issues/21),
[driver #45](https://github.com/iconidentify/libva-v4l2_request/issues/45),
[driver #49](https://github.com/iconidentify/libva-v4l2_request/issues/49) and
[#27](https://github.com/iconidentify/omarchy-m1-video/issues/27).

## Chrome blocker and retained preparations

Chrome `152.0.7977.64-1` was launched directly with separate disposable profiles,
Wayland and no sandbox-disabling flags. The first software row completed its
20 seeks, full clip with zero drop delta, two-element survivor and reopen.
It is **preparation only**: the 640x360 CSS capture was actually 1280x720 at DPR 2,
and the GPU process reported `sandboxed=false`. The initial input's primaries
and transfer tags were also missing. A separately tagged copy used for mpv has
all BT.709 tags and 360 unchanged software frame hashes. Both inputs remain.

A no-media default-startup diagnostic confirmed GPU `Seccomp: 0` and renderer
`Seccomp: 2`; its log says sandbox initialization encountered multiple threads.
`chrome://sandbox` yielded blank page text and is **not** the evidence for this
conclusion. Process status and GPUInfo are the evidence. C1 was not selected.

One planned no-media comparison used `--gpu-sandbox-start-early`. It enabled GPU
Seccomp and reported `sandboxed=true`, but native `libEGL.so.1` loading failed
inside the sandbox, OpenGL/GPU compositing/video decode were disabled and no
decode profiles remained. **Rejected workaround: do not persist this flag.**
Neither run proves a C1 regression or explains the earlier total desktop freeze.
Both Chrome hardware rows remain unrun. The next browser task is to establish
normal GPU sandboxing **and** working graphics on this installed build before
attempting decode, then correct the capture contract for actual DPR.

The first mpv software attempt also remains in the archive: it stopped before
any seek on an unavailable initialization property, with a child-error/idle
guard. The corrected runner waits for explicit output/decoder readiness before
recording identity. This preparation failure is not counted as a hardware pass.

## Evidence and reproduction limits

Run `python3 docs/evidence/m1-clients-2026-09-20/verify.py` from the repository.
It verifies archive/member hashes, actual identities/modes, seek/reload counts,
drop samples, PNG bytes/dimensions, healthy guard exits, the preserved failed
preparation, Chrome diagnostic states and final idle identities. Negative
semantic probes rejected a wrong driver hash, missing seek, software fallback,
dropped frame and wrong image. This is offline record verification, not a new
hardware run or independent certification.

`records.tar.gz` contains 164 logical records stored as 111 members. Identical
PNGs are stored once; `manifest.json` maps every original record path to its
stored object and original/published hashes. Text replaces only the home prefix
with `<HOME>`. Browser profiles/caches, unrelated issue snapshots and personal
media are excluded. Dated execution scripts and preview recipe are snapshots,
not new general-purpose test interfaces. Their paths need deliberate rebinding
for reproduction under a newly reviewed hardware plan.

The execution reused local avdlab IPC/DevTools helpers; exact helper hashes are
in `identity.json`. Those helpers are retained locally and not copied here
without a distributable licence. This limits independent hardware reproduction;
the archived results and verifier do not depend on those helpers. The preview
itself is self-contained apart from the explicitly pinned installed software.

Self-review, source/licence handling and merge scope are recorded in
[REVIEW.md](REVIEW.md). No claim to independent review or broad qualification.
