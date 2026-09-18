# Review record template

Copy this into a PR comment or a scoped review document. Use the
[local review protocol](../../sashiko.md); do not mark unchecked stages complete.

- PR / acceptance ticket / session claim:
- Base SHA / reviewed candidate SHA / final tested SHA:
- Commits in order / external source pins:
- Reviewer(s), independence and AI assistance:
- Scope / entry points / behavior categories / unavailable context:

| Stage | Evidence or reason inapplicable | Concerns / dismissals / unknowns |
| --- | --- | --- |
| 1 Intent | | |
| 2 Claims and reachability | | |
| 3 Execution and preconditions | | |
| 4 Resource ownership | | |
| 5 Concurrency and reverse side effects | | |
| 6 Trust and bounds | | |
| 7 Hardware assumptions | | |
| 8 Consolidation | | |
| 9 Conflict resolution | | |
| 10 Verification and severity | | |
| 11 Report and decision | | |

For every concern, including dismissals:

- ID, status (`confirmed` / `dismissed` / `unresolved`), introduced/pre-existing:
- File/symbol, trigger/configuration and caller-to-effect path:
- Expected/actual behavior, impact, priority and confidence:
- Strongest counterargument and concrete evidence resolving it:
- Fix commit / reproduction / regression result, or remaining question:

Validation: exact commands, tool/source versions, result and logs/CI links.
Separate model/software/hardware evidence; list checks not run and why.

Decision: merge / changes needed / missing evidence, with scope and rationale.
Final remote head check, merge SHA, remaining parent gates, claim release and
next owner/action. No hardware used, or separately authorized guard/lease and
final state. Do not label an incomplete stage or failed reviewer run a pass.
