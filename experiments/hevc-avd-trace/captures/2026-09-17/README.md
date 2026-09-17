# First experimental campaign: stopped, recorder correction required

Owner-authorized temporary schema-1 module execution on the M1; source
`d021d9dcea4f839bc1bfce2c386b28b9faed9ac1`. This campaign **does not satisfy #61**
and establishes no RPS_E cause or improvement. The installed module file and boot
configuration were unchanged. The original module was restored after the stop,
with its loaded build ID verified and an idle, fault-free final check.

| Planned run | Outcome |
| --- | --- |
| RPS_B / VA / kernel trace off | 300/300 output frames exactly match the reference; child exit 0; guard ok |
| RPS_B / VA / kernel trace on | Recorder error; child terminated/reaped with SIGTERM; 79 starts/completions, 325 records; invalid/incomplete |
| RPS_B / Gst / off and on | Not started |
| RPS_E / VA and Gst / off and on | Not started |

The same userspace reference tracing was enabled for both attempted runs. Kernel
trace-off MD5 is `6d1ed392b067050ebd3a24a37281da03`. The trace-on run cannot be
compared as a complete output, even though its 24–34 detail window exists. No
accepted normalized kernel artifact is published and no missing frames are filled
from prior runs. Old RPS_E wrong sets remain historical inputs, not new results.

## Recorder finding and bounded correction

The snapshot header records errors 36: shape 32 plus incomplete extent 4 after the
supervisor stopped the child. Its start records show one slice and one element in
the entry-point control array. Schema 1 passes `run.num_entry_point_offsets`
(`ep->elems`, copied array extent) to a guard requiring zero. That rejects unused
nonempty storage regardless of the slice's actual use. The pinned driver instead
reads `sl->num_entry_point_offsets` when deciding how many entries a slice uses;
array extent bounds that access. These are different facts.

Schema 1 did **not** record the actual slice entry count. We do not infer it from
reserved zeroes, certify an old snapshot, or claim actual zero use was measured.
Schema 2 retains the array extent and records slice usage separately; one slice,
zero used entries and array capacity 1–256 are supported by this bounded recorder.
Used entries/extra slices remain unsupported and invalidate a capture. The parser
rejects version 1 and all incomplete/error-marked captures. Sanitized shared-C
and full synthetic-history regressions cover unused capacity, used-entry rejection
and wrong-schema rejection. Source checks verify which fields reach the guard.

This changes recorder metadata and its guard only. The experimental hook patch,
all decoder operations, the 15 shipped patches and userspace binaries are unchanged.
The [new candidate](../../build.json) is built offline and has not been loaded.
Its [review](../../REVIEW.md) is AI self-review, not independent kernel review.

## Transition and restoration evidence

Six historical decoder fault records were retained. Preflight found none after
the prior accepted boundary. The new fixed boundary is
`2026-09-17T16:02:51.266903+00:00`, before the first unload, and was never advanced.
The initial direct `insmod` failed with missing standard V4L2 symbols because
`modprobe -r apple_avd` had also removed dependencies. No candidate driver code
initialized in that failed attempt. Loading the exact candidate's standard
`modinfo` dependencies allowed the authorized transition to finish. These symbol
errors are retained separately from the zero new decoder faults.

Both guards ended idle, with no timeout, wedge or new decoder fault. The first
restoration attempt was refused as module-in-use after Chrome had reopened; the
exact transient reference owner was not proven. We did not force an unload. The
owner reconfirmed all apps closed, then restoration succeeded at 16:11:32 UTC.
The loaded build ID matches the original module; its SHA-256 remains
`e50540e1d0fc48c7e0bf9b21ff028758bdb35f94aa7070af00de88e61e5c70e9`.
The experimental debugfs directory is gone. No decoder worker or lease remains.

## Evidence and next gate

[results.json](results.json) records the eight-run denominator, real child/guard
statuses, fixed boundaries, exact binary attribution and redacted command/environment.
[B-va-off-frames.json](B-va-off-frames.json) contains the 300 measured output hashes,
compared with the [accepted reference hashes](../../../hevc-controls/captures/2026-09-17/reference-frames.json).
[candidate-build.json](candidate-build.json) preserves the original build-time
provenance: its `loaded: false` describes preparation, not the later execution
recorded here. [private-manifest.json](private-manifest.json) hashes retained raw
snapshots/logs/scripts. No raw timestamps, media, pointers, DMA addresses or unrelated
process arguments are published. Hashes alone cannot independently establish the
contents of private evidence.

The guard checkout is `b5deb8c`; the actually selected VA driver is the unchanged
`266269e` tracing build. These are intentionally separate provenance fields.
The loaded module identity is checked via build-ID notes, not an independent
hash of resident kernel text.

Next: review the schema-2 candidate and obtain a fresh saved-work/closed-app window
for eight guarded comparisons, including same-run userspace correlation. Preserve
the original stop conditions and dependency-aware module transition. #61 remains
open; driver #42 still requires an attributable correction, three exact RPS_E
runs, RPS_B/full-suite preservation and fault/concurrency qualification. Counts
remain unchanged. This report and correction were AI-authored at the owner's request.
