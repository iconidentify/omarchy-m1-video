# Maintainer review and remediation

**Runtime correction (2026-09-17):** The original #70 module in `offline-build.json` is withdrawn: generated initialization prematurely removed the reference recorder and unload Oopsed before any decoder ran. See the [failed attempt](../hevc-avd-command-capture/failed-attempt-2026-09-17/README.md). The generator is corrected and its actual init/exit bodies plus the original-defect mutation are tested; [corrected build](corrected-build.json) is offline-only and has not been loaded. #71 remains open.

AI-assisted maintainer self-review after reviewing the contributor's implementation;
this is not independent specialist approval of the resulting kernel changes.
Contributor commits are preserved. No module was loaded or installed for this review.

The initial `d5e3bb7` head built before adding recorder hooks, omitted interior
scaling words, serialized native padding/truncated flags, and lacked a real strict
snapshot comparison. The follow-up `fc2b7a6` corrected build order, loop bracing and
named packing, but still accepted `H 1` plus 300 duplicate P rows and no windows.
It also misclassified unweighted P/B as skipped-I, omitted header/location words,
used incorrect deblock masks and underestimated snapshot/replacement storage.
The original reviews and failed build/reproduction evidence remain preserved.

The resulting tool uses complete explicit hook selection, schema-2 validation,
actual pinned C packing and mandatory same-run reference/writer binding. Its
prepared private reference copy has a disclosed storage/control adaptation:
readers pin sealed state, `arm` requires `off`, and seq output is bounded per row.
Accepted sources, wire records and historical captures are untouched. The
2 MiB cap is retained; no larger unreviewed allocation allowance is substituted.

A further source-order check found `job.codec` is initialized after the job hook.
The hook now binds using the negotiated format, as the accepted reference recorder
does. Tests cover the first foreign-codec job with an otherwise zero job structure.

Local evidence is in [offline-build.json](offline-build.json):

- Nine shared-core/parser test groups under the local toolchain; C core uses ASan/UBSan.
- 32 complete exact-C packing/hook cases and an 11-window synthetic snapshot.
- Five real source mutations detected: missing interior scaling/weight hook,
  changed emitted packing, missing skipped-I state, truncated coded extent.
- Native reserved bytes poisoned while the actual named serializer round-trips.
- Exact prepared wrappers, both recorders: pinned reader/free exclusion,
  allocation/open failure, concurrent reader/replacement and completion/disable;
  command default-off hooks and 300 start/done calls with no hot-hook allocation.
  Removing the actual reader/free guard makes the wrapper test fail.
- Required Bash syntax and mock rebuild checks plus installer mocks pass.
- Fresh ARM64 build against `7.1.13-3-1-ARCH`, GCC16.1.1, no compiler warnings;
  module SHA-256 `3f17561f44fdf578c14c79e0d0dd55190aa63b70f6ad07908536807e030e8bb4`.
  All final source/header/build-log identities are recorded. Hosted exact-head
  checks are a separate PR merge gate.

The host harness uses mutex and seq stubs and excludes address/reference helpers.
It cannot prove Linux IRQ behavior, DMA coherence, correct firmware semantics or
unchanged decoded pixels. The source oracle is deliberately the driver's actual
packing contract; agreement could still mean both clients share a wrong contract.

Before #71 runs, its two-recorder supervisor must be implemented/reviewed, both
recorders bound to the same waited decoder child, and same-run ioctl/encoded input,
writer history and output hashes linked. Existing single-recorder scripts must
not be reused blindly. Healthy idle/fault checks, exclusive hardware guard,
finite deadlines and verified restoration remain mandatory. Parent #42 retains
the actual RPS_E fix, three exact repetitions, RPS_B/full pass-set preservation
and fault/concurrency qualification.
