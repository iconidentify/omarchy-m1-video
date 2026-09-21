# Opt-in BT.709 EGL import correction

The [paired lifecycle experiment](lifecycle-2026-09-21/README.md) passed hardware
seeks, playback and reopen, but its colors matched BT.601 conversion for a
BT.709 stream. Chromium's native-pixmap EGL import explicitly uses REC601 for
BT709. The measured six flat-patch values and source route support that diagnosis.

`prepare_color.py` adapts only the hash-pinned original
`ui/ozone/common/native_pixmap_egl_binding.cc`. It adds the default-off
`VaapiBt709EglImport` feature. When enabled, BT709 uses `EGL_ITU_REC709_EXT`;
disabled behavior, BT2020, other matrices, range hints, formats, plane offsets,
FDs, sampling and sandbox remain unchanged. No broad color-management or
direct-overlay qualification follows. The first runtime target is Wayland NV12.

For a fresh private build, add `--bt709-import` to the recorded
`prepare_local.py` invocation. For the retained completed build tree, run:

```sh
python3 experiments/chromium-avd/prepare_color.py /absolute/chromium/tree
python3 experiments/chromium-avd/prepare_color.py /absolute/chromium/tree --apply
```

Both require the pinned Chromium version and unmodified original source;
symlinks, unknown hashes and reapplication are refused. Preserve the original
browser and build manifests before rebuilding the import object and browser
under the agreed remote budget. Runtime activation adds `VaapiBt709EglImport`
to the existing experiment's `--enable-features` list. This is experimental
configuration, not a daily-browser recommendation or installation instruction.

Offline checks compile the actual adapted matrix/range switch body with enum
declarations and EGL constants from pinned upstream headers. FeatureList state
and ColorSpace accessors are explicit test substitutes; these checks do not
execute EGL or prove real browser feature dispatch. Five cases preserve default,
BT2020, other-matrix and all-range behavior; two compiled mutations must fail
their named default-off/correction assertions. Full browser compilation and a
new identity-matched software/hardware pair remain necessary.

The initial bounded offline run passed all five color cases, two color
mutations, the existing 12 policy cases, four policy mutations, fatal sanitizer
probe, actual diagnostic-wrapper checks and source/recipe checks. Separate AI
source review found no remaining confirmed defect in this delta. That review
is not human security certification. Build and runtime results will be recorded
separately; the correction is not yet hardware-qualified at this checkpoint.
