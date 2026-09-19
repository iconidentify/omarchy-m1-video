# Scheduling review record

AI implementation-agent self-review using `sashiko.md`; no independent reviewer
or specialist approval is claimed. Separate review remains requested on draft
[PR107](https://github.com/iconidentify/omarchy-m1-video/pull/107), stacked on
[PR106](https://github.com/iconidentify/omarchy-m1-video/pull/106).

Session: `codex-82-selected-writers-20260918T201000Z`. Fetched main is
`a3a6dbedf12830c13d6e23605a538553f125a507`; preserved dependency is
`b1a39794d2b828ebea0633d43ac559db0a814fa7`. Initial implementation is
`2d4c483c1b8d8e31607cc9a1c4cb30b908a77983`; the follow-up adds a queued-reader
reordering test and evidence only, not production logic. GStreamer and previous
patch pins are unchanged. The one-shot review record remains historical.

| Stage | Evidence and disposition |
| --- | --- |
| 1 Intent | Internal experimental client scheduling, no public ABI/installer/default changes. Kernel association is explicitly outside this delivered slice. |
| 2 Claims | Real registered output vfunc reaches the plan lookup before publication. No automatic activation/controller is claimed. Late-writer live feasibility is limited by sticky publication. |
| 3 Execution | Read full arm, before-output, leave, result, finish and native frame/buffer checks; trace their original callback and observer begin/end callers. Unselected outputs keep callback guards; selected failures are sticky. |
| 4 Resources | Added fields are fixed arrays/scalars in the existing preallocated state. Begin/end and retained failed-unmap frame/picture cleanup are unchanged; test failure on the second selection after a prior success. |
| 5 Concurrency | No new actor or lock. Stream -> observer -> allocator remains; immutable plan copied at arm, owner-only result/finish. Framework wrappers test reentrant cleanup refusal and observer mutex release on selected and nonselected paths. Queued-reader reordering also tests foreign-thread APIs. |
| 6 Trust/bounds | Count 1–8 and distinct hints validated before session creation; frame zero allowed. Actual request/frame/picture/buffer checked before skipping nonselected output. Hints do not replace native writer/allocation identities or manifest checks. |
| 7 Hardware | Fake V4L2 and runtime evidence, CPU memfds only. Test pool expansion is fixture-only; real reused published allocations still reject. No DMA or kernel-context binding claim. |
| 8 Consolidate | D1–D5 and U1–U2 below separate prevention from unmet external gates. No demonstrated new production defect remained after review. |
| 9 Resolve conflicts | Re-read allocator sticky publication, native selection, actual output order and queue draining rather than infer feasibility from a positive model. Added a true queued-request reordering test beyond plan-array permutation. |
| 10 Verify | ASan/UBSan and TSan run complete modified sources, earlier suites and original software checks. Mutants must compile and reach their named assertion, not arbitrary crashes. Exact final evidence is in SCHEDULING-VALIDATION.md. |
| 11 Report | Draft for separate review; neither dependency is merged here. #82/driver #42 remain open. No hardware or installation; claim released in the final issue handoff. |

## Concerns, counterarguments and limits

- D1 (dismissed): a wrong frame could hide a wanted request on the unselected
  fast path. The scheduled path compares the native request frame and actual
  output buffer before lookup, plus framework picture/frame equality. The native
  frame mutation causes `schedule-frame-mismatch` to detect unwanted publication.
- D2 (dismissed): reordering could assign bytes to the array position or confuse
  completion frontier with the selected writer. Each observation uses its real
  native receipt and appends a slot in callback order. The queued-reader test
  queues 31/0/2, outputs 0/31/2, and checks all three completed before each copy;
  the plan-order tests check distinct request/writer identities.
- D3 (dismissed): an incomplete or partially failed plan could be reported as
  successful. Result requires success, no failure/lease/callback, exact count
  and every slot valid. Missing selections and second-selection error/unmap
  tests expose no result. The all-selected mutation must fail on partial output.
  Strongest counterargument: finish still returns TRUE on incomplete cleanup.
  This is intentionally a cleanup API, documented separately from result;
  it never certified successful observation in the original cancel-arm path.
- D4 (dismissed): mutable caller input, duplicate hints or output could spend
  unintended slots. Input is copied once; count/uniqueness are checked before
  arm, selected duplicate outputs permanently fail, and native eight-copy budget
  remains independent. Tests cover input mutation, zero/oversized count, duplicate
  hints, duplicate selected output, frame zero and eight successful fresh slots.
- D5 (dismissed): later callbacks could reentrantly free state or recycle a
  failed-unmap frame. Every nonselected/selected output enters the existing
  callback guard; failed end preserves its frame/picture and lease until explicit
  same-owner retry. Tests exercise framework reentry and second-selection unmap
  failure. No new cleanup bypass or background thread is introduced.
- U1 (unresolved, pre-existing admission boundary): the normal finite pool may
  have published every allocation before RPS_E's late selections. Scheduling
  does not solve this. The real four-slot recycled-pool test refuses without a
  map. Positive fixtures use twelve allocations and are not live feasibility
  evidence. A pre-publication retention/alias design needs separate review.
- U2 (unresolved, external acceptance): client and kernel run/context identities
  lack an actual supervisor binding. No same-run join is claimed; no historical
  timestamps or assertion-only metadata are promoted into evidence. Full live
  dependency/corpus identity, approved manifest, VA call site, DMA visibility and
  guarded campaign remain absent. See SCHEDULING.md for the exact next boundary.

Reverse checks: legacy first-output arm still performs one observation, including
its repeated-output fast path; result is still unavailable during callbacks;
finish still handles canceled/error arms and refuses foreign ownership; the
existing stop/flush/close/new-sequence guards are untouched. Reinitializing a
pool or finishing cannot evade the native budget/pristine-session requirement.
No original test expectations were weakened to accept the new scheduled path;
publication assertions distinguish legacy success from valid partial schedules.
