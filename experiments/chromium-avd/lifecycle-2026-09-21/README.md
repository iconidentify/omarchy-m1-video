# Chromium seek/reopen and picture comparison — 2026-09-21

**Hardware seeking, full-clip playback and reopening passed. The software/hardware
picture comparison failed with a repeatable color-matrix difference.** Keep
PR #133 draft. This continues the [first selection run](../runtime-2026-09-21/README.md).

| Measurement | Software reference | Hardware |
| --- | --- | --- |
| Browser | Same Chromium 153.0.8010.36 binary | Same binary |
| Fixture | Same pinned 640×360 H.264 High, 30 fps, 12 seconds | Same bytes |
| Decoder samples | FFmpegVideoDecoder / platform=false | VaapiVideoDecoder / platform=true |
| Seeks | 20 passed: [1,4,2,6] × 5 | 20 passed, same sequence |
| Full playback | Reached 12 s; 356 additional frames; zero dropped-frame increase | Same |
| Reopen | New player ID; software decoder confirmed | New player ID; hardware decoder confirmed |
| Captures | Five at measured DPR 2, 1280×720 | Five, same times and geometry |
| Isolation | Sandboxed AGX, zero GPU crashes; all observed GPU/renderer threads Seccomp=2 | Same |
| Exit | Browser.close, exit zero, no forced cleanup | Same |
| Final state | No decoder holders, stuck tasks, faults or surviving owned group | Same |

Software ran at 18:24:05–18:24:29 UTC; hardware at 18:24:40–18:25:03 UTC.
Each had its own exclusive `avd` lease, fresh whole-boot idle preflight and nominal
90-second deadline plus bounded observation/cleanup overhead. Both used the
installed r11 VA driver and Mesa 26.2.3. No further hardware launch followed
the failed picture comparison.

## Picture result

All five same-time RGB comparisons failed exact equality: mean absolute channel
error 6.82–6.84 out of 255, maximum 34–35. More than 99.98% of pixels differed.
No acceptance tolerance was introduced after seeing the result. In each mode,
the four seek frames were distinct and reopen reproduced the first seek frame
exactly. Thus the result does not look like a stale-frame/reopen failure.

[Software frame](software-seek-1.png) · [Hardware frame](hardware-seek-1.png)

An offline check decoded frame 30 to YUV and calculated limited-range BT.601
and BT.709 RGB values for six flat patches. Every saved hardware sample exactly
matched BT.601; every software sample exactly matched BT.709. For example:

| Patch | Decoded YUV | BT.709 / software RGB | BT.601 / hardware RGB |
| --- | --- | --- | --- |
| Red | 62, 102, 239 | 253, 0, 0 | 231, 0, 1 |
| Green | 172, 42, 26 | 0, 254, 0 | 19, 255, 8 |
| Blue | 31, 239, 117 | 0, 0, 252 | 0, 0, 241 |

The numerical models cover matrix conversion only, excluding other transfer,
primary and quantization behavior. The pinned fixture reports BT.709 through
FFprobe and lacks MP4 `colr` bytes. Chromium's demuxer reports SMPTE170M in both
rows, but its software decoder and H.264 hardware decoder prefer available
frame/SPS color information; that demuxer report alone does not explain the
observed divergence.

## Source diagnosis and correction boundary

Separate AI source inspection traced SPS color through the H.264 VAAPI delegate,
frame resource, Linux mailbox converter, Ozone external texture and Wayland EGL
import. In pinned Chromium 153.0.8010.36,
`ui/ozone/common/native_pixmap_egl_binding.cc:131` sets
`EGL_YUV_COLOR_SPACE_HINT_EXT` to REC2020 only for BT2020_NCL and **REC601 for
everything else, including BT709**. Range is handled separately. ANGLE forwards
the hint, and the external-sampler result is consumed as RGB without an apparent
compensating matrix. The source and six exact numerical matches strongly support
this import decision as the cause; the live EGL call was not instrumented.

Next correction experiment: honor BT709 in that import-hint decision while
preserving range, formats, plane offsets, FDs, sampling, sandbox and guard behavior.
Initially qualify only the tested Wayland compositing path. Audit direct-overlay
behavior before broader use: the old import comment says DRM always uses601,
but this pinned source's `hardware_display_plane_atomic.cc:153` already selects
709 for a BT709 matrix while still forcing limited range. Wayland surface color
management is separate; the tested compositor does not expose its protocol.
Adding container tags alone cannot fix an import switch that still chooses601
for correctly propagated709. A corrected matrix may fix flat colors without
making all pixels bit-exact, since sampling and rounding can still differ.

## Review, provenance and limits

The [review addendum](../AI_REVIEW_2026-09-21.md#lifecycle-continuation) identifies
the exact reviewed files. Before launch, review caught stale-player decoder
evidence at reopen: delayed old-player properties could satisfy a cleared map.
The corrected gate requires the sole newly created, non-retired player ID and
all decoder/platform/page properties. Four offline regressions passed; each
stage allows the Media-log batch to arrive before checking. These are stage
samples, not continuous per-frame hardware attribution.

Initial analysis preparation failed because optional NumPy/Pillow were absent.
It was replaced with installed FFmpeg and standard-library analysis; no package
installation. Final preparation and comparisons used tools/bounded-build, after
all browser processes and hardware leases had ended.

[Structured result](result.json) · [redacted raw records](records.tar.gz) ·
[original/published artifact hashes](manifest.json). The archive includes all
ten captures, exact harness/launcher/comparator sources, events, guards and
relevant browser-log lines. Profiles and binaries are omitted; full raw logs
remain local. Original first-run evidence is unchanged.

This is one generated H.264 clip with the installed driver. No C1 comparison,
multiple elements, adaptation, long soak or ordinary-browser qualification.
The color mismatch blocks picture-correctness acceptance. No package, persistent
configuration, kernel/module or reboot action. The previous full-desktop freeze
remains unexplained. AI-assisted execution and separate AI source review;
no human security certification.
