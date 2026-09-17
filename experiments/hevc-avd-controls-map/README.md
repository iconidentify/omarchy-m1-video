# HEVC non-reference AVD control coverage map

**AI disclosure:** Contributor analysis and maintainer remediation were AI-assisted.
Original contributor authorship is retained.

Research for [#66](https://github.com/iconidentify/omarchy-m1-video/issues/66):
map the named HEVC command paths after the schema-2 reference/motion result.
[Driver #42](https://github.com/iconidentify/libva-v4l2_request/issues/42) retains
actual corruption correction and full hardware qualification.
`decoded_frame_evidence=false`: this source analysis adds no hardware pass.

## Reproduce from a fresh checkout

Linux, Python 3, a C compiler and `patch` are sufficient. No device, sudo, media
or module build is involved. The first command fetches hash-locked primary files
into an automatically removed temporary directory, verifies all 15 shipped
patches, prepares the exact source without experimental hooks, checks imported
macros and campaign hashes, audits function-local coverage and runs all tests:

```sh
python3 experiments/hevc-avd-controls-map/verify-source.py
python3 experiments/hevc-full-controls/report.py --verify
```

`verify-source.py --source-dir DIR` can reuse a pristine source cache; every file
is still checked. For a separately prepared **15-patch-only** file:

```sh
python3 experiments/hevc-avd-controls-map/validate.py --source /tmp/avd-15patch/avd-hevc.c
HEVC_AVD_HEVC_C=/tmp/avd-15patch/avd-hevc.c python3 experiments/hevc-avd-controls-map/validate.py --self-test
```

The accepted schema-2 campaign additionally needs the pinned driver checker:

```sh
# driver tests/hevc-reftrace-check.py at ba66572ff7e1e380377eb2414a7eb7d7f97bb0d9
# SHA-256 666eacdde663e8ef890a0e974f5f0ce0f857803b25558b5e56db8f775f9d7dfa
HEVC_REFTRACE_CHECKER=/path/to/hevc-reftrace-check.py python3 experiments/hevc-avd-trace/campaign-report.py --verify
```

Existing `avd-map` CI reproduces that campaign. The additive checks step runs
`verify-source.py`, including source-dependent counterexamples with no skips.

## Coverage and evidence classes

[inventory.json](inventory.json) is the canonical curated field interpretation;
[source-coverage.json](source-coverage.json) binds each named function's reads,
flag constants, calls and exact lines to the pinned 15-patch source. Coverage is
function-local: the same member in a different function cannot excuse a missing
use. Changed source hashes, new reads/calls, changed source locations and omitted
local uses fail. The scanner is deliberately narrow, not a general C parser;
exact source hashing prevents a new alias or syntax from silently changing scope.
`historical_lines` retain the contributor's original hints; use the verified
coverage locations for the patched source.

| Class | Meaning at the accepted #61 baseline |
| --- | --- |
| `already_measured` | Published reference/motion, slice count, used entry count or dependent flag; the named emitted non-reference word may still be unmeasured |
| `statically_derivable` | Pinned arithmetic/constant conditional on valid input; not independently firmware-validated |
| `missing_runtime_input` | Copied job-hook value or actual appended command not measured by #61 |
| `outside_scope` | Absolute DMA, scratch/pipe state, compressed bytes and firmware |

Negotiated output dimensions and compressed layout do not establish copied SPS
values or the actual DECOMP header bit; those overclaims were corrected in review.
The source's deblock OFF1 mask overlaps its enable bit. That is a checked packing
property and an unresolved contract detail, not proof of a decoder defect.

## New inputs and decision

[#67 / PR #68](https://github.com/iconidentify/omarchy-m1-video/pull/68) subsequently
supplied [complete ioctl-returned controls and input digests](../hevc-full-controls/capture/README.md)
for all 300 pictures of both streams and clients. Compressed bytes agree; weights,
scaling, QP/deblock and other source-consumed non-reference input fields agree.
The kernel already clears the apparent submitted PCM underflow. No PCM trial or
DPB reorder follows. Remaining I-slice flag differences are inactive in the motion
path. These ioctl observations do **not** supply copied job-hook state or actual
appended non-reference words, so the historical inventory classes stay explicit.

The next experiment is [actual commands plus copied control attribution around
CRA](next-observation.md), pictures 24–34 with complete 300-picture writer history.
Capture every selected word, not only count/first/last summaries; reconcile against
#67 inputs before moving to compressed-reference contents. Equal commands cannot
prove that the shared firmware contract is correct.

## Credits and review

Kernel AVD sources: Asahi Linux Contributors; Eileen Yoon and credited upstream
authors. Selected `avd-inst.h` macros are MIT; selected `avd-hevc.c` macros are GPL-2.0.
See [LICENSE.avd-bits](LICENSE.avd-bits), headers and immutable source pins.
[REVIEW.md](REVIEW.md) records maintainer findings, fixes and remaining limits.
