# Adversarial review record

AI implementation-agent self-review; no independent reviewer, specialist
approval or hardware qualification is claimed.

Session: `codex-122-same-run-join-20260920T0259Z`. Base:
`b60be8ad8b966ed3fc44d8edc62ff88f80d74fb4`. Reviewed implementation:
`f9d3d85ebc4686cf928b0dae67b524d361ed6de3`. The merged FFmpeg/VA and
GStreamer observers/runners, raw V4L2 normalizer, paired kernel supervisor,
reference validator and command oracle on that base remain dependencies.

## Staged review

| Stage | Evidence and disposition |
| --- | --- |
| 1 Intent | Add one default-off per-workload evidence runner. It installs nothing, changes no boot/module state and does not authorize the eight-workload campaign. |
| 2 Claims | Followed the actual `v4l2-tracer` process tree, paired-recorder lifecycle, client report production, queue trace, raw V4L2 normalization, kernel reference lifetime and command-oracle calls. |
| 3 Execution | The decoder blocks before exec; both recorders arm for its real PID; release, wait, seal, snapshot and clear have an exact successful transcript. The outer tracer must finish before raw-trace validation. The decoder's recorded wait status, not the tracer's status, is authoritative. |
| 4 Resources | Run roots are newly created mode 0700. Evidence/log/report files are private and exclusive. Child log descriptors, tracer descriptors, timeout process groups and publication temporaries were traced through failure paths. |
| 5 Concurrency | Parent-death behavior remains in the existing supervisor. Finite child and outer deadlines remain. Stable-file reads use `O_NOFOLLOW`, same owner, one link and before/after identity/stat checks. Publication uses `RENAME_NOREPLACE`. |
| 6 Trust/bounds | Commands are argv arrays, never shell strings. Client-specific options/properties, one-to-eight selectors, report/queue schemas, u64 identities, extents, one-session rules and normalized-only output are checked before publication. |
| 7 Identity | VA binds output ordinal through actual output POC and the same process's complete native request row. Gst binds the full observer tuple through the copied raw timestamp/capture lifetime. Both end at the exact kernel reference start/completion pair and paired command context. Client and kernel allocation identifiers remain distinct domains. |
| 8 Failure | Added explicit tests for nonzero child exit, recorder loss/error, foreign context, stale snapshot receipt, ambiguous timestamp, stale client tuple, later writer/frontier, destination collision and injected publication failure. Failed kernel attempts remain preserved rather than cleared. |
| 9 Verify | Twenty-eight focused tests, ten semantic mutants, the existing 22 supervisor tests, 51 campaign tests, ten campaign mutants, 25 reference-content tests/four source mutations and the full pinned FFmpeg call-site suite pass. Exact commands and hashes are in `VALIDATION.md`. |
| 10 Report | Public workflow coverage and parent/campaign documentation are updated. Hardware, target eligibility, DMA visibility, live manifest, installation and codec support remain explicitly unclaimed. |

## Confirmed findings fixed during review

- **R1 — tracer-inside-supervisor topology armed the wrong PID (P0).** A
  no-device probe proved `v4l2-tracer` forks its tracee. The final topology wraps
  the private supervisor worker with the tracer; only the worker forks and
  blocks the actual decoder whose PID is given to both kernel recorders.
- **R2 — tracer status is not the decoder status (P0 evidence).** A tracee that
  exited 23 still produced tracer exit zero. The final validator requires the
  durable supervisor record to contain a released, reaped decoder with exit zero
  and the exact successful recorder event sequence. A missing/failed worker is
  therefore rejected even if the tracer reports success.
- **R3 — Gst level 6 omitted the join record (P0 for this leaf).** The native
  `observer-queue` line uses `GST_TRACE_OBJECT`, so the runner now fixes
  `GST_DEBUG=v4l2codecs*:7`; level 6 cannot silently produce an unjoinable run.
- **R4 — allocation domains were initially conflated (P0 correctness).** Client
  allocation generations and kernel allocation tokens are not numerically
  comparable. The final bridge uses the client queue tuple, actual V4L2
  timestamp/capture lifetime and kernel picture history. The output labels the
  domains separately and never asserts numeric equality.
- **R5 — VA collector accepted weaker records than Gst (P1 evidence).** It now
  requires one canonical record, nonzero run/context/session/allocation/writer,
  ordered counters, valid external expectations, stable pre/post file identity
  and a successful close.
- **R6 — two descriptor cleanup edges were incomplete (P1 resource).** Partial
  child stdout/stderr setup now closes every opened fd, and failure to create the
  tracer stderr file closes the already-open stdout fd. Timeout termination also
  tolerates the process-group exit race while still reaping the wrapper.
- **R7 — duplicate Gst observer properties could pass configuration review (P1
  command integrity).** Each frames/copy/report property must now occur exactly
  once on the sole decoder element before the next link separator.
- **R8 — successful execution parsing was too permissive (P1 stale evidence).**
  The validator now requires exact top-level/status/receipt fields, monotonic
  event times and the complete ordered arm/release/wait/seal/persist/clear
  transcript. Stale, partial and foreign recorder records reject before any
  `KernelEvidence` exists.
- **R9 — reference completion accepted extra lifetime rows (P1 ambiguity).** A
  selected kernel picture must now have exactly one start and one completion
  row, with stable allocation/layout, the selected capture, its expected writer
  and successful completion.

## Dismissed concerns and remaining limits

- **D1, publication replacement race:** dismissed. The result is fully written,
  synced and closed under a private temporary name, then published with Linux
  `renameat2(RENAME_NOREPLACE)` and its directory synced. Collision and a
  destination created during publication both fail without replacement.
- **D2, raw identity leakage:** dismissed. The public schema is bounded and
  recursively rejects timestamp/fd/DMA/pointer/lease/bytes field names. It
  contains normalized generations/coordinates plus SHA-256 input inventory;
  raw traces, logs, payload and the guard lease remain private.
- **D3, allocation reuse or later writer:** dismissed for the accepted result.
  Selection must reproduce the queue row's full available generation/request/
  writer/capture tuple and a drained submitted/completed frontier. That row must
  map to the successful kernel lifetime; substituting an earlier tuple fails.
- **D4, forged same-user artifacts:** outside this maintenance evidence threat
  boundary. Exclusive paths, stable reads, exact schemas and cross-artifact
  identities reject accidental/stale/foreign evidence; they are not a
  cryptographic attestation against a malicious process with the runner user's
  credentials. A reviewed root-owned live manifest remains required.
- **U1, live target eligibility:** unresolved. In particular, synthetic Gst
  coverage does not prove the chosen real selected buffers are still unpublished
  when observation begins.
- **U2, complete deployment identity:** unresolved. Loaded driver/module,
  FFmpeg/GStreamer dependency closure, oracle/tool and corpus identities still
  need a reviewed live manifest and controller admission.
- **U3, hardware outcome:** unresolved by design. No decoder/device, DMA copy,
  pixel comparison, RPS_E selection or eight-workload campaign ran for this
  leaf. Parent #82 and driver #42 remain open.

No package, installer, module, boot state, device lease or host configuration
changed during this review.
