# VA-aware campaign-controller review

- Ticket/session: #116 / `codex-116-va-controller-20260919T223500Z`.
- Base: merged PR #115, `6b768d8deef9c3d60af0d65d4d2aadd4c1162a83`.
- Reviewer: implementation agent, AI self-review using `sashiko.md`; no
  independent specialist review is claimed.
- Scope: offline plan schema, validation, deterministic client contracts,
  tests/mutations and status documentation. No client execution, device or
  system change.

| Stage | Evidence / disposition |
| --- | --- |
| 1 Intent | The change consumes the accepted Gst and FFmpeg/VA private contracts without changing either call site. Execution remains unavailable. |
| 2 Claims | Traced every issue #116 criterion to a validation branch, emitted contract field, positive/negative test and relevant mutation. |
| 3 Execution | Read builder → workload matrix → validation → JSON/CLI and authorization → preconditions → unconditional execution refusal. Invalid plans collect errors and cannot reach the final refusal boundary as a nominal plan. |
| 4 Resources | Inapplicable to planning: no fd, mapping, request, frame, lease or process is created. JSON contains metadata/options only. |
| 5 Concurrency | No concurrent actor exists in the planner. The emitted contracts preserve the clients' distinct owner and lifecycle constraints rather than claiming to enforce them at runtime. |
| 6 Trust/bounds | CLI integers are bounded per selector domain; cross-client limit fields reject. Counts, duplicates, negatives, pair equality and byte budgets are checked. Declared corpus/output facts remain explicitly unverified inputs. |
| 7 Hardware | Inapplicable to execution. No AVD/V4L2/DMA operation ran; hardware, loaded-build and same-run association claims remain external gates. |
| 8 Consolidation | Three pre-existing planner defects shared one root: client coordinates and control semantics were collapsed into a Gst-only `frames` model. They are fixed together, not papered over with aliases. |
| 9 Conflict resolution | CAMPAIGN.md says copy-off/on both retain/drain/map and differ only in copies; the old "copy-off selects nothing" behavior contradicted that text. The campaign contract controls. |
| 10 Verification | 49 tests, nine source-level semantic mutations, Python compilation, repository rebuild/shell baseline and whitespace checks pass. Mutation detection requires the named test failure. |
| 11 Decision | Ready for exact-head hosted validation. Parent #82/#42 gates remain; merging this leaf does not authorize or execute a campaign. |

## Findings

- **R1, confirmed and fixed, P0/high confidence, pre-existing:** copy-off rows
  selected no outputs, so they did not execute the retain/drain/provenance/map
  path and could not be controls for copy-on disturbance. Paired rows now carry
  identical selectors, input windows and limits; only the copy flag differs.
- **R2, confirmed and fixed, P0/high confidence, pre-existing:** one `frames`
  tuple and one Gst pool bound were applied to both clients. A superficially
  valid plan could arm unrelated VA output ordinals. Gst frame numbers and VA
  ordinals now have separate builder/CLI/schema fields and domain-specific
  bounds; cross-domain fields reject.
- **R3, confirmed and fixed, P1/high confidence, pre-existing:** parameter-set
  change positions were compared directly with the selected output number. That
  is invalid for reordered VA output. The guard now compares input-change
  indices with an explicit per-client last-required-input window. A regression
  places a change after the VA ordinal but inside its input window; the
  `parameter-input-window` mutation must miss it and fail that named test.
- **D1, dismissed:** counting paired controls creates sixteen observations and
  appears to violate the eight-snapshot budget. Copy-off maps but retains no
  copied content; the byte budget counts the eight copy-on targets. Each fresh
  decoder arm remains within the native eight-slot bound.
- **U1, unresolved external gates:** real selector/output-count/input-window
  facts, client/result collection, loaded identities, same-run kernel join,
  hardware behavior and health restoration are not established here. The
  controller continues to refuse execution.

Decision: no remaining in-scope blocker after exact-head CI. This is a
self-review, not independent validation.
