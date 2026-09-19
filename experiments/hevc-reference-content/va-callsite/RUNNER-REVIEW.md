# FFmpeg VA result-runner review record

- Ticket/session: #118 / parent #82,
  `codex-118-va-runner-20260919T230028Z`.
- Base: `3d5abb095414dfdcac87b24d12dd46a68addcb9f`.
- Source: FFmpeg n9.0.1
  `bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa`, archive-hash pinned in
  [RUNNER-VALIDATION.md](RUNNER-VALIDATION.md).
- Reviewer: implementation agent, adversarial AI self-review at the repository
  owner's direction. This is not independent specialist review.
- Scope: private default-off FFmpeg worker export, bounded normalized schema,
  exclusive file publication, strict collector and no-device tests. No device,
  campaign, module, installation, raw content or support claim.

| Stage | Evidence / disposition |
| --- | --- |
| 1 Intent | The program-only `va_observer_report` option is additive, per-stream and paired with the existing private observer selection. No packaged client or public ABI changes. |
| 2 Claims | Traced option definition → demux stream matching → `DecoderOpts` → `DecoderPriv` → `decoder_thread()` → internal finish/result/report helper. Full `ffmpeg` builds, not only library objects. |
| 3 Execution | Report runs after successful drain/downstream EOF/error-rate handling and before codec free. Every finish/result/serialization/write/sync/close/rename error returns through the decoder thread. |
| 4 Resources | Temporary fd/path ownership is local. The fd closes on all paths; temporary files are unlinked on failure; final publication is one atomic no-replace rename. Persistent observer-end failure retains the established fatal quarantine and emits nothing. |
| 5 Concurrency | Finish and result execute on the decoder worker that owns send/receive. Foreign-thread reporting fails. Reused destinations across streams collide instead of interleaving. |
| 6 Trust/bounds | Serialization starts from `VAAPIObserverResult`, cannot reach pool bytes/receipt/fd/pointers, and is capped at 8192 bytes. The collector rejects duplicate keys, extra fields, malformed identities, mismatched copy/ordinal contracts and symlinks. |
| 7 Hardware | All driver behavior is synthetic. No claim about DMA visibility, firmware, real writer association or corrected pixels. Linux `renameat2(RENAME_NOREPLACE)` is intentional for the target platform. |
| 8 Consolidate | Two publication concerns were fixed: report loss at generic free and a cleanup race in the first hard-link design. Both reduce to publishing exactly one complete result after same-owner cleanup. |
| 9 Resolve conflicts | A log-line transport was rejected because unrelated FFmpeg logging can interleave and has no exclusive destination. A caller-side wrapper was rejected because it violates observer ownership. |
| 10 Verify | Full patched program and fixture run under ASan/UBSan and TSan. Twenty-nine cases, strict collector negatives and fourteen named mutations cover the final path. |
| 11 Report | This leaf can merge only as offline execution plumbing. The runner must still require the whole FFmpeg process to succeed; #82/#42 hardware and correction gates stay open. |

## Confirmed findings and fixes

- **R1, confirmed and fixed, P0/high confidence:** before this leaf, the real
  `ffmpeg` program never called the result API. Generic codec free could consume
  the only remaining same-owner teardown opportunity, so an external wrapper
  could neither collect safely nor prove finish-before-free. The worker now
  validates and publishes after its success checks and before
  `avcodec_free_context()`. A structural mutation removing that call fails the
  worker-before-free assertion.
- **R2, confirmed and fixed, P1/high confidence, introduced during #118:** the
  first publication design hard-linked the complete temporary file to the final
  path and then unlinked the temporary name. A rare cleanup error created an
  awkward second-name/error path, and trying to remove the final name could race
  a hostile replacement. Publication now uses one atomic
  `renameat2(RENAME_NOREPLACE)`; no existing destination is replaced and no
  post-publication final-path cleanup occurs. The pre-existing-destination case
  and exclusive-publication mutation exercise this contract.
- **R3, confirmed and fixed, P1/high confidence:** an unbounded `AVBPrint` was
  unnecessary even though the input count is capped. Serialization now has an
  explicit 8192-byte ceiling, and incomplete allocation/formatting fails before
  any destination is created.

## Dismissals and remaining limits

- **D1, dismissed:** copy-off can expose stale digest bytes. The result struct is
  zero-initialized, the serializer emits JSON `null` whenever `copied` is false,
  and the collector rejects any other value.
- **D2, dismissed:** two streams can append records to one file. Publication is
  a no-replace rename of one complete document. The second stream fails the
  process; it cannot append, truncate or replace the first record.
- **D3, dismissed:** a report can leak raw content through an accidental field.
  The serializer only receives the normalized result structure; source checks
  forbid pool/receipt/byte reachability, and both a raw-field collector test and
  a serializer mutation are rejected.
- **U1, external:** another FFmpeg component can fail after this decoder worker
  publishes. A future runner must accept evidence only when the entire process
  exits successfully and the strict collector validates the exact requested
  selectors/copy mode.
- **U2, external:** the Gst runner, live manifest, same-run kernel join, hardware
  guard and any RPS_E correction are not implemented here.

Decision: no remaining confirmed blocker for this offline leaf after final-head
sanitizer, repository and hosted checks. No independent approval is claimed.
