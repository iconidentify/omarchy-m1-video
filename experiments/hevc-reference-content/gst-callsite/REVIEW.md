# Output call-site review record

- Ticket/session: #82, `codex-82-production-callsite-20260918T191638Z`.
- Base: `a3a6dbedf12830c13d6e23605a538553f125a507`.
- External source: GStreamer `070125524a8422e29d3b69a372ed4f62fd343ffa`,
  with the accepted unaligned, observer and copy-integration patches.
- Reviewer: implementation agent, AI self-review. No separate specialist or
  provenance review is claimed. That review remains required before live use.
- Scope: additive H265 output-vfunc wiring and actual-source offline tests;
  no installed software, shipped kernel patch, device or system operation.

| Stage | Evidence / remaining work |
| --- | --- |
| 1 Intent | In-plugin experimental integration; no installer, codec-profile or public libva change. |
| 2 Claims | Registered H265 output vfunc calls the hook before publication. Internal arm remains explicit; campaign controller and kernel join are absent. |
| 3 Execution | Trace arm, native selection/begin/copy/end, output, result and finish. Test each refusal and the default-off branch. |
| 4 Resources | Arm pins element/thread; native begin pins storage. Failed end transfers callback frame/picture ownership and preserves retry token. Finish releases after end. |
| 5 Concurrency | Stream -> observer -> allocator; owner checks and reentrant finish refusal. Framework boundaries check the observer mutex is released using another thread. |
| 6 Trust/bounds | No new evidence override; actual buffer pointer and frame identity checked. Pristine native queue required. Existing source/build admission and byte budgets retained. |
| 7 Hardware | Synthetic syscalls and CPU bytes only; DMA coherence and noninterference unknown. No hardware run. |
| 8 Consolidation | Findings and dismissals recorded below as testing proceeds. |
| 9 Conflict resolution | Compare actual complete source, not the earlier handoff's readiness labels. |
| 10 Verification | Pending final sanitizer, original regression and mutation results. |
| 11 Decision | Draft for review; parent #82 and driver #42 remain open. |

## Concerns and dispositions

- R1, confirmed and fixed during local testing: the attempted-output fast path
  originally bypassed `in_callback`. A subsequent real output's framework
  boundary could finish the session reentrantly, invalidating its borrowed
  result while that callback was in flight. Every owned output now enters the
  callback guard, including outputs after the one-shot snapshot. The `copy`
  case exercises a second output and attempts reentrant finish at both boundaries.
- T1, test integration corrected: GStreamer's hidden-symbol build required the
  framework wrappers to have default visibility. The first build failed at link;
  it supplied no execution evidence. No warning or sanitizer check was disabled.
- R2, confirmed by source and covered by lifecycle regression: native decoder
  close clears `observer_session`. Allowing client close with an outstanding arm
  would make finish unable to close its session and release its element pin.
  Client lifecycle operations now require finish first; arm pointer changes
  use the observer mutex as well as the stream lock, matching those readers.
  A named mutation removes the close guard and must fail the lifecycle assertion.
- R3, confirmed reverse-call-site finding and fixed: the new-sequence caller
  would continue after its void streamoff helper refused an armed operation,
  updating fields and negotiating against still-streaming storage. Arm now
  requires completed initial streaming/pool setup, and new-sequence rejects
  before changing state. The lifecycle test invokes the real registered
  new-sequence vfunc with a changed SPS and checks the refusal without I/O.
- D1, dismissed: putting begin after publication would always encounter sticky
  alias exclusion. The hook is before the existing publication marker, uses
  the request's exact buffer, and is exercised via the registered output vfunc.
- D2, addressed in design: failed unmap cannot be followed by ordinary frame
  dropping or token loss. The callback transfers its owned frame/picture to the
  arm and withholds delivery until same-owner finish successfully retries end.
- D3, addressed in design: downstream reentrancy could free state still used by
  the callback. `in_callback` remains set through real framework finish/drop;
  result and finish reject until callback cleanup clears it.
- D4, explicit limitation: arbitrary thread exit/cancellation can abandon an
  armed owner. GStreamer streaming-worker cancellation is unsupported by the
  underlying API. Same-owner finish and ordinary framework lifecycle remain
  required; the implementation does not claim orphan recovery.
- U1, unresolved external gate: live kernel command/reference join, approved
  full deployment identity, DMA visibility and hardware campaign remain absent.

Validation and exact artifact identities will be recorded after final execution.
