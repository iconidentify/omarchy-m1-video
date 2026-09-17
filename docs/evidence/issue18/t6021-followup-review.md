# M2 Max installed-stack and boot follow-up review — 2026-09-17

AI maintainer source/artifact review of [PR #54](https://github.com/iconidentify/omarchy-m1-video/pull/54)
at `04428f852d88a7676b317ac3d2c49b5d5f177ece`. No hardware campaign was repeated.
The contributor's original commits and all 32 raw artifacts remain unchanged.
The maintainer's attribution corrections and this assessment were self-reviewed,
not independent specialist qualification.

## Accepted content

[Audit JSON](t6021-followup-review.json) records hashes for all raw files, eight
native conformance summaries and 17 three-row guard logs. All summaries load
through the driver repository's native-result validator at
`b5deb8c319f4e53b5243bc0583fee1800e8faa42`. Vector names are unique; frame counts
match included frame-record counts; hardware-pass vectors have nonempty frames
and equal recorded actual/expected stream MD5s. This checks the submitted
content; it does not regenerate frames or authenticate the device that ran it.

| Full suite | Submitted passing set | Recomputed comparison |
| --- | --- | --- |
| HEVC | 144/147, identical to r11 | Green; RPS_E and VPSSPSPPS change from decode error to checksum mismatch |
| AVC | 73/135, identical to r11 | **Non-green**; FM1_FT_E changes from decode error to software fallback |
| FRExt, opt-in High 10 | 27/69, identical to r11 | Green |
| VP9 | 216/305, identical to r11 | Green |

All four comparisons exactly reproduce the submitted `*-compare.json` using
`docs/r11-pass-sets.json`; there are no missing, additional, lost or newly
passing vectors. HEVC comparator `first_differing_frames` entries are comparisons
against a baseline lacking frames for those failures, not a measurement of the
first corrupt picture against a decoded reference.

The other four summaries contain one VP9 10-bit subset and three post-boot
smokes. Across all eight summaries there are 27,112 frame records, 26,563 in
vectors labelled hardware pass. These include repeated smoke content and are
not independent tests, new device-certified frames or new supported vectors.

Each guard's three events share one run ID. Four full-suite guards end
`child-error`/exit 1; the other 13 end `ok`/exit 0. All final rows report idle,
no timeout/wedge and no abort reason. The four-line kernel excerpt shows an
out-of-tree AVD module initializing with **hardware version 30010**. The mpv
snippets report VA-API decoding with gpu-next output.

## Attribution limits and remaining gates

- Summaries do not contain the guard run ID, and guard records do not contain
  the test command/output hash. Filename proximity does not independently bind
  a particular result file to a particular run or device.
- The reported package/source/module hashes appear in contributor prose. The
  summaries/guards identify harness source `27da69d…`; that is not proof that
  installed driver bytes match package source `db3014f…`. Selected library
  paths are redacted or empty; exact library/build attribution remains reported.
- `loaded_binary_sha256` is unknown. The selected on-disk module path, its hash,
  an out-of-tree taint and startup hardware version do not identify the exact
  running module or establish that all 15 patches were active.
- Detailed export/lifecycle frame counts are reported in prose. The included
  successful guard exits corroborate a completed child, but without its command
  and raw output they do not independently validate those counts.
- Original installation/reboot authorization, shutdown, complete journal
  interval and pstore records are absent. Consent, the LUKS-wait explanation,
  same-stack attribution and absence of new faults remain contributor reports.
  The startup excerpt alone does not prove a fault-free boot interval.

This accepts reported t6021 conformance, lifecycle/client and one boot-enabled
login evidence with these limits. It does not qualify two independent devices,
promote a support tier, prove reset safety or close #18/#13/#17. Further
qualification needs a contemporaneous bundle binding selected/loaded build,
device, guarded command, raw output and result hashes, plus the outstanding
boot/client/display acceptance. Do not discard the existing non-green AVC
verdict or historical unknowns.

## Reproduce the comparisons

Using a driver checkout at the revision above, run from that checkout (set
`COMPANION` to this companion checkout):

```sh
python3 tests/compare-results.py \
  --baseline docs/r11-pass-sets.json \
  --candidate "$COMPANION/docs/evidence/issue18/t6021-installed-stack/hevc-summary.json" \
  --suite hevc
```

Repeat for `avc`, `frext` and `vp9`; AVC intentionally exits 1. Output should
match each submitted comparison. The audit's `raw_artifacts` map can also be
recomputed with SHA-256 relative to this directory. No decoder access is needed.
