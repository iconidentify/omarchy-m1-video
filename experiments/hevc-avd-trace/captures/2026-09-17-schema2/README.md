# Measured reference-state result: no discrepancy in the observed subset

Eight owner-authorized M1 decoder workloads completed with 300 output frames each.
All four trace-on captures have 300 starts/completions, zero recorder errors and
complete same-run userspace correlation. RPS_B is exact. RPS_E remains corrupt on
26 VA / 25 GStreamer output frames, with exactly the preceding wrong-frame sets.
Every output hash is identical with kernel tracing off/on. **This does not fix
RPS_E, increase codec counts, or establish firmware culpability.**

The original installed module was restored, its loaded build ID verified, and the
final decoder state was idle with no new fault. No installation, reboot or shipped
patch change occurred. All hardware leases are released.

## What was actually observed

Reference-command detail covers decode pictures **24–34**; all 300 picture starts
and completions establish the writer history. Picture ordinals start at one;
output indices start at zero. The generated [summary](summary.json) contains all
11 detailed rows per vector, full wrong sets, first-bad associations and layouts.

| RPS_E decode picture | Observation in both clients | Measured consequence |
| --- | --- | --- |
| 28 / POC32, CRA I picture | I command `0x2d020000`; no collocated lookup | Early-return behavior is preserved |
| 29 / POC28, first bad Gst decode picture | Lookup matches completed writer 28 / POC32, marked intra; word `0x2d00889a` | Motion gate is false and no motion address is emitted |
| 31 / POC31, first bad VA decode picture | Lookup matches completed inter writer 30 / POC30; dependent flag is clear; word `0x2d0488ca` | Motion gate is true and the emitted relative address equals that allocation's MV tail |

All measured table lookups match their requested writer, with valid copied
timestamps, expected intra/inter state and completed writer history. No fallback,
stale writer, destination alias, allocation-range error or discrepancy against the
source's full header/list/motion-word construction is observed. Actual slice POC
matches decode POC. These statements cover the recorded command window, not every
reference lookup in the 300-picture streams.

After resolving slots into logical writer identities, both clients' complete
measured reference headers/lists and motion words agree across pictures 24–34 of
both vectors. Raw table/list slots can differ: at E picture 29 the collocated slot
is VA 11 / Gst 13, and at picture 31 it is VA 5 / Gst 14. The returned logical
writers nevertheless agree. Inactive I-slice flags differ at B picture 32 and E
picture 28; the I branch does not consume them and the emitted word is identical.

Both clients negotiate 448×240 capture dimensions for 416×240 output. Compressed
layout and the 7,168-byte MV size agree. VA uses DMABUF with a 368,128-byte plane
and MV offset 360,960; Gst uses MMAP with a 345,600-byte plane and MV offset 338,432.
Actual emitted relative addresses match each allocation's layout and remain in
range. This checks address construction, not compressed bytes or firmware reads.
It neither proves those size differences harmless in every case nor identifies
them as a cause; correct RPS_B uses the same differing layouts.

## The checker pause is retained

B/VA/off and B/VA/on completed with exact, identical pixels. The first offline
postprocessor then rejected the on-trace's reused timestamps. Its outer guard
therefore records `child-error` / return 1, while the actual decoder exited 0 and
the sealed recorder had zero errors, 300 pictures and 767 records. The campaign
paused before any subsequent decoder workload.

VA derives the timestamp from the capture buffer index; its 17 buffers legitimately
reuse timestamps across 300 writers. The old checker incorrectly required global
uniqueness and resolved all records through a final global map. Normalized schema
3 now resolves against the latest recorded writer at each picture, preserving
ambiguous candidates as findings and distinguishing an absent I lookup from a
real timestamp zero. Raw kernel schema 2 and the loaded module are unchanged.

The preserved full capture passed the corrected checker and same-run userspace
comparison, with 24 offline regression groups passing before continuation. Only
the six unattempted workloads then ran on the same unchanged module. No workload
was retried, no raw capture repaired, and no reset occurred. The original failure
is retained in [guards/B-va-on.jsonl](guards/B-va-on.jsonl) and
[postprocessing-correction.json](postprocessing-correction.json). The seven other
guards report `ok`; all eight actual decoder children exited 0 and every guard
finished idle without fault, timeout, wedge or foreign client. This is explicitly
**not** eight originally green outer-guard statuses.

Trace-on status is read after sealing. For trace-off, `execution.status` is the
supervisor's last live sample and may show a transient open context; the outer
guard's post-exit holder/fault check supplies the final idle result.

## Reproduce and inspect

```sh
HEVC_REFTRACE_CHECKER=/path/to/reviewed-driver/tests/hevc-reftrace-check.py \
  python3 experiments/hevc-avd-trace/campaign-report.py --verify
HEVC_REFTRACE_CHECKER=/path/to/reviewed-driver/tests/hevc-reftrace-check.py \
  python3 experiments/hevc-avd-trace/campaign-tests.py
```

The checker hash is pinned by the existing source map. The report verifies all
published input digests, eight run/guard/child outcomes, source associations,
300-frame off/on equality, wrong sets, restoration and four complete histories.
It replays the normalized writer/command metadata with **symbolic** writer tokens
against each run's userspace-derived model. Those tokens do not reconstruct the
raw timestamps. Mutated-evidence tests reject missing runs/records, changed pixels,
commands, future references, incorrect output association, mixed raw sources,
failed restoration and attempts to erase or broadly excuse guard errors.

- [runs.json](runs.json): redacted commands/environments, real child and sampled
  status, whole-output MD5, exact wrong sets and links through unique guard IDs.
- `frames/`, `refs/`, `associations/`: all eight measured output hashes, request
  metadata and complete same-run decode/output associations.
- `kernel/` and [kernel-meta.json](kernel-meta.json): four full normalized histories,
  raw source digests, current userspace digests, findings and per-run identities.
- [provenance.json](provenance.json), [candidate-build.json](candidate-build.json)
  and [transition.json](transition.json): exact candidate/source/header/module,
  userspace/tool/device attribution and successful dependency-aware load/restoration.
  The candidate manifest's `loaded: false` describes original build time, not this
  later measured execution. Loaded identity uses build-ID notes, not a hash of
  resident kernel text. The guard checkout `b5deb8c` differs from the actually
  selected `266269e` userspace driver; both are recorded separately.
- [private-artifacts.json](private-artifacts.json) hashes retained raw traces,
  outputs, journals and scripts. No raw request timestamps, media, DMA/kernel
  addresses or unrelated process logs are published. Digests alone cannot let an
  external reviewer independently authenticate private evidence.

The fixed journal boundary is `2026-09-17T17:09:48.295096+00:00`, before unloading
the original module. Six historical fault records were preserved; no fault was
found since the preceding accepted boundary or during this campaign. Standard
V4L2 dependencies were loaded before direct `insmod`, and both transition and
restoration succeeded without a retry.

## Decision and remaining work

The tested reference-lookup/state, intra-motion-gate and emitted-reference-word
hypotheses have no supporting discrepancy in this window. There is no attributable
owning-layer corruption fix from this measurement. Matching the source model also
does not prove that model's firmware contract is correct.

Next compare the **remaining source-consumed HEVC controls and non-reference AVD
commands** around CRA, then choose a narrowly discriminating compressed-reference
state measurement if those inputs also agree. Full SPS/PPS/scaling/weight/offset
controls, bitstream preparation, other command words, compressed buffer contents
and firmware state were not exhaustively compared here. Avoid a speculative DPB
reorder or declaring firmware guilty by eliminating only this subset.

#61 can close as the requested measured negative decision after review and merge.
Driver #42 still needs an actual correction, three complete exact RPS_E runs,
RPS_B/full-147-vector preservation and fault/concurrency qualification. This one
M1, two-vector serial campaign is not a soak, boot, throughput or other-platform
qualification. All work and review here are AI-authored maintainer self-review;
no independent kernel review is claimed.
