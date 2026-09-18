# Integration design/code review

AI disclosure: implementation, this record and the separate review were produced
by Codex agents. This is not independent human specialist approval.

On 2026-09-18, a separate reviewer examined the lifetime/allocation design before
copy implementation and the resulting actual adapter code. The shared workflow's
request for separate lifetime/reference review was the basis for that review.

Findings incorporated:

- Move executable identity out of the caller's writable pool into private per-object
  state initialized once before a lease. Avoid dynamic-loader locking while paused.
- Snapshot lock acquisition must not add another two-second window to the original
  begin deadline; use immediate trylocks and the retained absolute deadline.
- Preserve a failed mapping pointer/length in the native context. End retries unmap
  and refuses to release ownership while it fails; a new snapshot cannot overwrite it.
- Require HEVC on the VA codec and negotiated output format.
- Retain exact normalized identity, bounded pre/post-checked build/device provenance
  and absolute monotonic timestamps, rather than only a boolean attestation.
- Reject `builtin` module markers: absence of a sysfs build-ID note does not distinguish
  a built-in component from a loaded module compiled without notes.

The reviewer found no additional ordinary snapshot identity/range defect in the
revised copy/gate code. Final review of native cleanup and test design found no additional blocker for
the scoped offline draft: failed end preserves the lease/pins/cancellation state,
and successful end clears the mapping before release. The implementer executed
the suites recorded in [VALIDATION.md](VALIDATION.md); the separate reviewer read
the test source rather than independently reproducing those runs. External client/dependency/corpus identity and actual same-run kernel
command/reference integration remain outside the runtime verifier's coverage;
they are explicitly required before a live campaign. No hardware evidence or
coherence qualification is inferred from the model tests.

## Adversarial follow-up, 2026-09-18

PR [#105](https://github.com/iconidentify/omarchy-m1-video/pull/105), session
`codex-pr105-adversarial-20260918T175638Z`; base
`69815eacb0aac6501d87b75b94d2603df9b8178a`, reviewed initial candidate
`6907ee64bfeceef4321216e56ed9e24cd3256bf3`. The PR's final review comment records
the final tested head and hosted run links without rewriting earlier evidence.
Original commits, in order: `101ca3a`, `1e1b650`, `551aa31`, `6907ee6`.
Pinned VA/Gst/kernel sources remain those in [VALIDATION.md](VALIDATION.md).

Method: [local Sashiko/Mason adaptation](../../../sashiko.md), with both
[upstream revisions pinned](../../../docs/review/SOURCES.md). This was an adapted
source review, not execution of the upstream Sashiko service. Root Codex performed
integration/provenance/testing review; a fresh separate Codex reviewer inspected
lifetime and reverse side effects, then independently tested the ELF fix and
reviewed the local protocol. A separate provenance reviewer did not complete;
no independent provenance approval is claimed. The root reviewer also authored
the initial implementation, so its contribution is self-review.

| Stage | Evidence and disposition |
| --- | --- |
| 1 Intent | Offline copies extend actual native leases; no shipped installer/driver/kernel behavior or support row changes. Accept only this partial experiment. |
| 2 Claims | Trace pool init → native begin → snapshot → end. Fixtures call real configured sources; no production FFmpeg/Gst hook exists. Remaining #82 work stays open. Timing wording corrected in R3. |
| 3 Execution | Read complete normalization, transfer, runtime parser, native cleanup and fixture paths. Loaded-note dereference lacked a readable mapping check: R1. |
| 4 Resources | Native context retains map/length after failed unmap; end retries before clearing lease/pins. Caller pool reset cannot erase native map/count. D1/D2. |
| 5 Concurrency | VA API→context lock order; Gst recursive observer lock and ending flag. Reverse searches cover native producer/destructor/final-unref/allocator paths. D1–D4. |
| 6 Trust/bounds | Fixed root manifest, device binding and pre/post loaded-ID checks examined; full dependency/corpus attestation remains absent. R1 fixes unsafe note access before manifest admission. |
| 7 Hardware | Layout/range, allocator policy, retained QUERYBUF/internal EXPBUF and cache-source assumptions inspected. Syscalls/memfds are synthetic; no DMA, device timing or hardware qualification claimed. |
| 8 Consolidate | One code finding (R1), two documentation corrections (R2/R3); overlapping lifetime concerns grouped below. |
| 9 Resolve conflicts | Distinguish native retained cleanup from a leak, and an acceptance deadline from a hard timeout. The loader does not establish PT_NOTE readability; verified by reproduction. |
| 10 Verify | Root reproduced loader acceptance then a crash; separate reviewer reproduced old-header failure using the new regression. Fixed regression and full client suites pass; no remaining confirmed offline blocker. |
| 11 Report | Final commit/CI and merge decision recorded on PR105. Live #82/#42 gates remain explicit; no human specialist or hardware approval is implied. |

### Confirmed and corrected

- **R1, P1, high confidence, introduced here:** `hevc_content_image()` followed
  PT_NOTE virtual addresses without proving they were mapped. Root built a small
  shared object containing the actual identification function, changed only its
  generic note virtual address outside PT_LOAD, and loaded it: dlopen succeeded,
  then identification exited on SIGSEGV. The counterargument that loader success
  proves note readability is therefore false. Pool initialization calls this
  before manifest admission, even when initialized disabled. The fix checks
  relocation arithmetic and complete containment in a readable PT_LOAD before
  reading any nonempty note; failure clears the ID. The same DSO now returns no
  ID, while the normal object still identifies. This is an experimental-tool
  robustness defect, not evidence of a production privilege boundary bypass.
  `runtime-test.c` covers unreadable/later notes, partial range, permissions,
  overflow, oversized notes, truncation, duplicate IDs and valid executable
  identification. Independently, the identical regression fails against the old
  header under ASan and passes against the fix under ASan/UBSan.
- **R2, P2 documentation:** README/contract broadly claimed all lock contention
  leaves the pool unchanged. `v4l2r_content_snapshot()` stops it if the inner
  context trylock fails after API lock acquisition. Wording now distinguishes
  outer and inner locks. No admitted runtime contention failure was demonstrated.
- **R3, P2 documentation:** deadline wording could imply forcibly bounded lease
  duration. `hevc_content_runtime()` and transfer make synchronous calls while
  cancellation is disabled; before/after time checks cannot interrupt them.
  Contract now explicitly describes result acceptance and the remaining live
  guard/timing requirement. No claim of hard syscall timeout remains.

### Dismissed with code evidence

- **D1, VA premature destruction:** transfer preserves the native map on failed
  munmap; `finish()` retries before clearing `observer_active`/`observer_lease`.
  `api.c`'s `LOCKED` wrapper rejects producers and DestroyContext/DestroySurfaces
  before native STREAMOFF, capture cleanup or fd closure while active.
- **D2, Gst recycling/finalization:** begin holds request, picture, bitstream
  and decoder references. Failed end returns before releasing them. Successful
  end sets `observer_ending` around final-reference callbacks under the recursive
  mutex; `gst_hevc_observer_busy()` covers both lease and ending states. Last
  decoder unref is the last `self` access; subsequent unlock uses a global mutex.
- **D3, allocation-policy race:** `gst_v4l2_codec_allocator_prepare()` holds the
  observer mutex across create_buffers(count=1) and buffer_new; the policy helper
  additionally matches index/direction. Export success alone cannot admit policy.
- **D4, pool reset/lock leak:** count and held mapping live in native context,
  independent of pool initialization; transfer refuses an existing mapping.
  Inspected VA error paths release context then API lock; Gst errors release the
  recursive mutex. No new lock inversion found.

### Follow-up validation

Root reran both complete suites after R1, using cached hash-verified sources:

```sh
python3 experiments/hevc-reference-content/integration/tests.py --client va --archive /tmp/video-82-va-baseline-20260918/source.tar.gz --keep /tmp/video105-va-review-final
python3 experiments/hevc-reference-content/integration/tests.py --client gst --archive /tmp/video-82-gst-baseline-20260918/source.tar.gz --native-file /tmp/video-82-build-tools-20260918/native.ini --keep /tmp/video105-gst-review-final
```

Both passed: new runtime regression under ASan/UBSan; 27 VA / 25 Gst integration
modes under ASan/UBSan and TSan; 21 VA / 29 Gst original observer modes under both;
six semantic mutants per client. VA's 195 original Meson tests also passed; Gst
pinned plugin/library linkage checked. Logs: `/tmp/video105-va-review-final.log`,
`/tmp/video105-gst-review-final.log`; tool versions match the earlier local
validation. These are current runs; earlier `evidence.json` remains historical.
No hardware, installed software, kernel patch or host configuration changed.
