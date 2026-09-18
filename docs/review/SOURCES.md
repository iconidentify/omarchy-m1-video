# Review prompt sources and adaptation

The user requested Sashiko and `masoncl/review-prompts`. On 2026-09-18 we read
the following immutable revisions. No literal upstream `sashiko.md` was found;
the repository-root file is our local adaptation, not a verbatim upstream file.

| Source | Revision and material used | Licence |
| --- | --- | --- |
| [sashiko-dev/sashiko](https://github.com/sashiko-dev/sashiko/tree/93ee8f6fa2e16144dfdac7417f37d2eb47b68983) | [designs/MULTI_STAGE_REVIEW.md](https://github.com/sashiko-dev/sashiko/blob/93ee8f6fa2e16144dfdac7417f37d2eb47b68983/designs/MULTI_STAGE_REVIEW.md): eleven stages, separate concerns/dismissals, conflict resolution and verification | [Apache-2.0](licenses/Sashiko-Apache-2.0.txt) |
| [masoncl/review-prompts](https://github.com/masoncl/review-prompts/tree/032284304f3bbad50e092fa870c5d810de324d9f) | [kernel/review-core.md](https://github.com/masoncl/review-prompts/blob/032284304f3bbad50e092fa870c5d810de324d9f/kernel/review-core.md), [callstack.md](https://github.com/masoncl/review-prompts/blob/032284304f3bbad50e092fa870c5d810de324d9f/kernel/callstack.md), [agent/side-effect.md](https://github.com/masoncl/review-prompts/blob/032284304f3bbad50e092fa870c5d810de324d9f/kernel/agent/side-effect.md), [false-positive-guide.md](https://github.com/masoncl/review-prompts/blob/032284304f3bbad50e092fa870c5d810de324d9f/kernel/false-positive-guide.md), [technical-patterns.md](https://github.com/masoncl/review-prompts/blob/032284304f3bbad50e092fa870c5d810de324d9f/kernel/technical-patterns.md), and [locking.md](https://github.com/masoncl/review-prompts/blob/032284304f3bbad50e092fa870c5d810de324d9f/kernel/subsystem/locking.md) | [MIT, Copyright (c) 2025 Chris Mason](licenses/Mason-MIT.txt) |

Changes made locally: rewrote the procedure around Apple video invariants and
our PR/claim workflow; replaced LKML email reporting with repository review;
made code navigation tool-independent; included test/fixture correctness;
separated unproven hypotheses from confirmed defects; retained hardware and
system authorization boundaries; added final-head verification and merge/handoff.
We do not adopt upstream test exclusions, mandatory tool/provider choices,
automatic email submission, or instructions to treat prompt rules as proof.

Credit belongs to the Sashiko contributors and Chris Mason/review-prompts
contributors for their source review methods. Licence texts are retained here
for the adapted material. This is an AI-authored local adaptation, not a claim
that either upstream project has reviewed or approved our work. Updating a pin
requires reviewing the source changes and their effect on the local protocol.
