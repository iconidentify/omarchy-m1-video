# Adversarial review record

AI implementation-agent self-review using the repository's `sashiko.md`; no
independent reviewer, specialist approval or hardware qualification is claimed.

Session: `codex-124-gst-eligibility-20260920T0353Z`. Base:
`b3da53fd8b4cf5d118fd956455c392da759ce7ed`. Pinned GStreamer revision:
`070125524a8422e29d3b69a372ed4f62fd343ffa`. Dependencies are the merged Gst
observer, retained-copy integration, selected-output call-site, runner and
same-run supervisor.

## Staged review

| Stage | Evidence and disposition |
| --- | --- |
| 1 Intent | Remove the known finite-pool eligibility blocker without weakening sticky publication. Additive patch only; no installer, shipped package or default enablement. |
| 2 Claims | Traced configuration through `decide_allocation`, source allocator creation, pool acquisition, request creation, output observation and publication. The reserve is real production capture storage, not a larger fixture-only pool. |
| 3 Execution | Complete configuration freezes before source allocation. The active runner plans by exact frame number; the allocator selects by sticky allocation state; selected commit precedes request creation. Every refusal returns a stream failure. |
| 4 Resources | Reserve size is selector count, bounded by the existing eight-slot parser and checked for unsigned overflow. Selected failure returns the empty GstBuffer wrapper. Ordinary waiting ends on an eligible published buffer or flush. |
| 5 Concurrency | Existing order remains stream lock to observer lock to allocator object lock. Candidate inspection/removal and release share the allocator lock. Flush uses an atomic flag plus the condition-variable lock and broadcast; final TSan is clean. |
| 6 Trust/bounds | No caller supplies eligibility metadata. The allocator-owned `observer_published` bit is the only fresh/published decision. Selector uniqueness is frozen once and committed with a bounded bitmask. |
| 7 Hardware | No hardware claim. Synthetic V4L2 syscalls and CPU memfds exercise the complete compiled plugin. Live target and DMA eligibility remain campaign evidence. |
| 8 Consolidate | The finite reserve, published-first reuse, unpublished-only selection, remaining count, selector uniqueness and default-off isolation each have a named mutant. One concurrency finding was fixed. |
| 9 Resolve conflicts | A first TSan run exposed the flush-flag access even though both paths used the object lock. The flag became explicitly atomic while retaining condition synchronization; the clean run was repeated from a fresh extraction. |
| 10 Verify | Zero-fuzz full-source ASan/UBSan and TSan builds pass ten new modes and all preceding observer/integration/call-site modes. Six compiled mutants fail only at their named assertion. |
| 11 Report | `VALIDATION.md`, this review and the public workflow state exact identities and offline limits. #124 may close without closing #82 or driver #42. |

## Confirmed finding fixed

- **R1 — flush flag produced a TSan-visible race on the new wait path (P0 for
  this leaf).** `set_flushing()` and both waiters used the allocator object lock,
  but the host GLib lock implementation did not establish a sanitizer-visible
  happens-before edge for the plain `gboolean`. The flag is now `gint` and every
  access uses `g_atomic_int_get/set`; the object lock still protects the queue
  predicate and condition wait/broadcast. The fresh TSan run, including an
  actual blocked reserve-preserving acquire released by flush, is clean.

## Dismissed concerns and remaining limits

- **D1, ordinary frames starve behind the reserve:** dismissed within the
  decoder allocation contract. The ordinary DPB/downstream capacity is retained
  in full. The reserve is additional. When only reserved fresh buffers are free,
  ordinary acquisition waits for an ordinary published buffer or flushes.
- **D2, selected wait could recover an eligible buffer:** dismissed. Any
  outstanding capture allocation has already been assigned to another picture;
  by the time it returns through normal output it is permanently published.
  Immediate selected refusal is the finite fail-closed behavior.
- **D3, publication reset on reuse:** dismissed. Reverse inspection found no
  write clearing `observer_published`; tests map, share, publish, release and
  recycle allocations, then require selection to skip them. Existing export and
  sticky-publication suites also pass on the modified source.
- **D4, default-off behavior drift:** dismissed. No runner object calls the
  original pool API unchanged. The fixture verifies ordinary FIFO order, the
  complete preceding suites pass, and the default-off-isolation mutant is
  detected.
- **U1, real pool capacity:** unresolved hardware admission. A live manifest
  must prove the driver can allocate the reviewed ordinary count plus the
  bounded selector reserve on the exact loaded stack.
- **U2, live target selection and DMA evidence:** unresolved external work.
  This leaf does not select RPS_E B/E targets, prove live DMA visibility, bind a
  corpus, or run the guarded eight-workload campaign.

Reverse checks covered renegotiation after freeze, post-success outputs,
pre-supplied buffers, duplicate selectors and allocations, unsigned sizing,
spurious/flush wakeups, outstanding DPB allocations, allocator detach, map/share
aliases, output publication and the unchanged same-run result boundary.
