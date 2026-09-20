# HEVC observer deployment staging

AI-assisted implementation for
[#126](https://github.com/iconidentify/omarchy-m1-video/issues/126), under the
guarded campaign in
[#82](https://github.com/iconidentify/omarchy-m1-video/issues/82). This directory
builds and attests the complete experimental client/recorder stack. It never
installs, loads, unloads or runs a decoder, and neither its candidate manifest
nor its admission output authorizes hardware execution.

## Exact staged stack

`build.py` accepts only the pinned source archives for FFmpeg n9.0.1, the
VA-request driver and GStreamer. It applies the merged observer, retained-copy,
private ABI, production call-site, result-publication and finite-allocation
patches in dependency order with zero fuzz. It stages the resulting FFmpeg,
VA driver, `gst-launch-1.0`, V4L2 codecs, H.265 parser, video-convert and core
element plugins alongside the corrected paired
recorder module, target evidence, same-run supervisor, C oracle, generated UAPI
and hardware guard.

The builder records every explicit patch/configure/compile command, tool
identity, source and patch digest, ELF build ID and `ldd` closure. It also binds
the loaded-kernel release/config, modular vb2 objects, corpus, reference
evidence, exact target plan and all eight same-run argv/environment records.
The output state is always `candidate`.

The host GLib package advertises two missing code generators. The builder
therefore regenerates only `glib-mkenums` and `glib-genmarshal` from the clean,
pinned GNOME/glib 2.88.3 source templates, checks their previously established
hashes, and supplies a staged pkg-config override through an exact Meson native
file. The generators, overridden `glib-2.0.pc`, native file and source identity
are ordinary manifest-bound inputs; nothing is installed on the host.

On the M1 staging host used for #126, the command shape is:

```sh
python3 experiments/hevc-reference-content/deployment/build.py \
  --root /home/chrisk/hevc-deployment-20260920 \
  --ffmpeg-archive /home/chrisk/src/video-114-work-20260919/runner-self-review2/ffmpeg.tar.gz \
  --va-archive /home/chrisk/src/video-114-work-20260919/integration-final/source.tar.gz \
  --gst-archive /home/chrisk/hevc-deployment-gstreamer-0701255.tar.gz \
  --glib-source /tmp/omarchy-120-glib-tools-src \
  --recorder-module /home/chrisk/hevc-command-capture-20260917T2045Z/corrected-build/apple-avd.ko \
  --targets experiments/hevc-reference-content/deployment/target-evidence-20260920.json \
  --corpus-root /home/chrisk/src/fluster/resources/JCT-VC-HEVC_V1 \
  --oracle /home/chrisk/hevc-command-capture-20260917T2118Z/oracle/candidate/packing \
  --uapi /home/chrisk/hevc-command-capture-20260917T2118Z/oracle/v4l2-controls.h \
  --jobs 4
```

The destination must be absent or empty. A failed or partial build remains
evidence and is never treated as a candidate.

## Target derivation

`derive_targets.py` hash-checks all four accepted 300-output association tables
and parses the raw private Gst V4L2 traces. Those traces contain one contiguous
ordinary capture pool of indices 0 through 18 for both locked streams. The
finite-allocation patch adds one never-published allocation per selected frame,
so the admitted patched pool sizes are 20 for B and 22 for E.
The same derivation parses the locked Annex-B streams: each has its initial
VPS/SPS/PPS before the first VCL NAL and no parameter-set NAL afterward, so the
listed input windows contain no in-band parameter-set change.

The selected coordinates are:

| Client/vector | Output evidence | Selector | Last input |
| --- | --- | --- | --- |
| Gst/B control | output 20, picture 25, POC 20 | `system_frame_number=24` | 24 |
| Gst/E | outputs 26/28/29 | `system_frame_number=31,28,32` | 32 |
| VA/B control | output 20, picture 25, POC 20 | `output_ordinal=20` | 24 |
| VA/E | outputs 31/73/74 | `output_ordinal=31,73,74` | 80 |

These are client selection coordinates only. The same-run supervisor still
requires the exact request/allocation/writer/completion receipt and paired
kernel evidence; frame number, POC, output ordinal or capture index never serves
as writer identity.

## Review and admission

A reviewer must change only `state` from `candidate` to `reviewed`, place the
manifest and every referenced path in the required trusted location, and pin
the exact resulting SHA-256 in the external authorization. `manifest.py`
rejects a different digest, dirty source, mutable/untrusted paths, symlinks,
duplicate or extra fields, dependency/build-ID drift, identity-less vb2,
corpus/target/plan drift and missing clean recorder endpoints.

`admission.py` then reconstructs the plan through the owning controller and all
eight commands through the deterministic builder. Both tools still emit
`execution_authorized: false`. The workload argv use fresh
`@OMARCHY_RUN_ROOT@` and `@OMARCHY_KERNEL_RUN@` placeholders and enter the real
same-run supervisor; a later separately authorized campaign runner must replace
them under the exclusive hardware guard.

## Offline checks

```sh
python3 experiments/hevc-reference-content/deployment/target_tests.py
python3 experiments/hevc-reference-content/deployment/tests.py
python3 experiments/hevc-reference-content/deployment/mutations.py
python3 -m py_compile experiments/hevc-reference-content/deployment/*.py
```

The offline tests do not establish that the staged binaries load on the current
host, that a selected allocation is DMA-visible, that observation preserves
pixels, or that HEVC correctness/support increased. Those are the next guarded
campaign and driver-correction gates in #82 and driver #42.
