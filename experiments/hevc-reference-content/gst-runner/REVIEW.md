# Adversarial review record

AI implementation-agent self-review using the repository's `sashiko.md`; no
independent reviewer, specialist approval or hardware qualification is claimed.

Session: `codex-120-gst-runner-20260919T2345Z`. Base:
`cc787997ba9a744cc95cdccb33d424631c3377ed`. Reviewed implementation:
`75b9cc59fd1876077bce4759914b9a48f3a9e6a1`. Dependencies are the merged
observer, retained-copy integration and selected-output callsite on that base.
Pinned GStreamer revision remains
`070125524a8422e29d3b69a372ed4f62fd343ffa`.

## Staged review

| Stage | Evidence and disposition |
| --- | --- |
| 1 Intent | Additive experiment on the pinned `v4l2slh265dec`; new properties are default-off and not installed by this repository. The hosted job is CPU-only and uses no device or secret. |
| 2 Claims | Traced the real registered `start_picture`, `output_picture`, `handle_frame`, `finish` and `drain` vfuncs. The hook arms after negotiated allocators exist and before `ensure_bitstream`; the output hook invokes result/finish only after callback cleanup and downstream success. |
| 3 Execution | Followed every configuration, arm, stream, completion, drain and publication return. Partial/duplicate/late/mutable configuration, arm refusal, downstream failure, incomplete selection, cleanup quarantine and report failure all return failure without a successful report. |
| 4 Resources | Runner strings/state are element-owned. Callsite owns the explicit element/thread references. JSON is private heap state until same-owner finish succeeds. Temp fd paths cover short/error writes, sync, close, collision and unlink; successful rename does not unlink the now-free temp name. |
| 5 Concurrency | Configuration/get/arm serialize on the recursive decoder stream lock; armed result/finish stay on the streaming owner. Existing order remains stream -> observer -> allocator. TSan covers the complete modified plugin and runner plus all preceding suites. |
| 6 Trust/bounds | Selectors are one to eight unique ASCII-decimal values below the reserved maximum. Results require the exact selected set, unique frames/requests, valid nonzero identities, one run/context/session, ordered counters and a fixed 8192-byte schema. Collector uses `O_NOFOLLOW`, current uid, one link, private mode and before/after file identity/stat checks. |
| 7 Hardware | No hardware claim. The fixture uses synthetic V4L2 syscalls, framework frames and CPU memfds. Existing retention, mapping, provenance and copy bounds are reused, not replaced by report metadata. |
| 8 Consolidate | Six implementation/test defects found below were fixed. No unresolved in-scope runner defect remained. External supervisor/kernel binding and real late-writer eligibility remain parent work. |
| 9 Resolve conflicts | Re-read the actual GLib temp API, Linux rename lifecycle, allocator API visibility and H265 start path when tests contradicted initial assumptions. Each contradiction produced a code/test correction rather than a weakened expectation. |
| 10 Verify | Fresh zero-fuzz full-source builds passed ASan/UBSan and TSan. Six mutants compile and abort at their named semantic assertion; sanitizer, timeout or compiler failures cannot pass. Exact results are in `VALIDATION.md`. |
| 11 Report | This record, validation and public workflow disclose offline scope. Separate review remains welcome; #120 can merge as an offline leaf without closing #82 or driver #42. |

## Confirmed findings fixed during review

- **R1 — report temp opened read-only (P0 for this leaf).**
  `g_mkstemp_full()` does not add an access mode. Passing only `O_CLOEXEC`
  created an `O_RDONLY` fd, so every success failed its first write. The runner
  now passes `O_RDWR | O_CLOEXEC`; copy-off/on and short-write modes reach the
  real exclusive publication path.
- **R2 — inherited fixture counter rejected runner publication (test defect).**
  The callsite wrapper requires its selected-map counter before publication.
  Runner output had not advanced that test-only counter, causing an unrelated
  assertion. The runner fixture now advances it only for a configured selected
  frame; production code was unchanged.
- **R3 — actual-arm probe passed a null slice (test defect).**
  Flushing the allocator does not make its nonblocking `alloc()` fail, so the
  real decoder advanced to a null slice and UBSan correctly rejected it. The
  fixture now exhausts its four public sink-memory slots, making the first
  post-arm bitstream allocation fail before any slice access. The test and
  mutation still prove the real vfunc location and pre-allocation ordering.
- **R4 — successful rename could unlink another process's new temp-name file
  (P1 correctness/race).** After `RENAME_NOREPLACE` succeeds the temp pathname
  is free. Unconditionally unlinking it opened a small race against same-user
  recreation. Cleanup now unlinks only on failed publication; success owns only
  the final path.
- **R5 — normalization trusted too much upstream state (P1 evidence).** Initial
  parsing accepted `strtoull` whitespace/sign forms, and C serialization did not
  independently match results to configured selectors or reject duplicate
  request identities. Parsing is ASCII-decimal only and reserves `UINT32_MAX`;
  both producer and collector now enforce selection, identity, uniqueness and
  counter invariants.
- **R6 — cached-archive evidence footer named the wrong file (test defect).**
  A complete cached-archive run passed both matrices, then the footer tried to
  hash a nonexistent copy under `--keep`. It now hashes the supplied archive;
  the fresh repeat exits zero.

## Dismissed concerns and remaining limits

- **D1, partial or stale report:** dismissed. JSON is built privately; finish
  must succeed before any open. Full write, file sync, close and no-replace
  rename precede success. Every failure test requires an empty temp directory.
  The collector additionally requires the whole GStreamer process to exit zero,
  so a later pipeline failure invalidates an already published result.
- **D2, default-off side effects:** dismissed for the claimed boundary. Without
  any runner property, no runner object or report exists; hooks perform only
  null checks/recursive stream locking around the original path. The complete
  preceding callsite suites pass on the modified source.
- **D3, property/stream race:** dismissed. Property set/get and arm use the
  decoder stream lock. The plan and strings become write-once before arm; a
  mutable attempt marks the run invalid and same-owner output/drain cleans it.
- **D4, cleanup after failed native end:** dismissed as success, retained as an
  operational limit. The runner reports `cleanup-quarantine`, preserves the
  exact callsite/lease and emits no file. An explicit same-owner retry is still
  required; no timeout can safely discard retained DMA ownership.
- **U1, same-run evidence join:** unresolved external acceptance. This result
  does not yet bind a kernel command/reference record to its run/context/session
  and process identity. A guarded supervisor must perform that join.
- **U2, live RPS_E eligibility:** unresolved hardware question. Synthetic fresh
  allocations do not prove late selected writers remain unpublished/eligible in
  the real finite pool. Driver #42 and the parent campaign remain open.

Reverse checks covered the unchanged default path, repeated outputs after runner
success/failure, parent H265 handle/drain/finish behavior, callback cleanup
attributes, property offsets, element disposal, failed-end ownership and the
collector's final process gate. No installer, package, module, boot state,
device lease or host configuration changed.
