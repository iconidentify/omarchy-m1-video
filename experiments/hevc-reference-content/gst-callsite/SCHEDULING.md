# Selected-output scheduling (offline)

AI-assisted follow-up to PR106; dependency head
`b1a39794d2b828ebea0633d43ac559db0a814fa7`, current main
`a3a6dbedf12830c13d6e23605a538553f125a507`. The original call-site evidence
in VALIDATION.md and REVIEW.md describes the preceding one-shot implementation,
not this extension. No external source pin or accepted patch is changed.

## API and state

Call `gst_hevc_callsite_arm_frames(decoder, copy, frames, count)` on the streaming
owner at the same post-negotiation/pre-first-request boundary as the legacy arm.
The caller owns the input array until the call returns; the API copies it into
fixed storage. Counts outside 1–8, NULL, duplicate frame numbers and nonboolean
copy modes reject before opening a session. Frame zero is valid. No launch
property, automatic arming or external process/controller is added.

Frame numbers are selection hints, never identities. For every armed scheduled
output the actual request must match the framework frame, picture and buffer
before even the nonselected path can pass. Each selected output obtains a new
native selection/begin receipt; the actual run, context, session, request,
allocation, writer, completion frontier and buffer metadata remain in the pool.
The immutable plan is searched without assuming decode order equals output
order. Storage is bounded at eight entries; no per-output allocation is added
by the scheduler. Pool allocation and native map/drain/copy budgets are unchanged.

Nonselected output: native observer begin, manifest admission and mapping are
not called. The ordinary callback still completes/publishes/delivers it. Selected
output: native begin/drain, copy or matched no-copy control, and end all precede
publication. Any selected failure is sticky, including failed end; the previous
same-owner retained-frame cleanup/retry contract applies. Subsequent callbacks
cannot silently resume the failed schedule. A duplicate selected frame number
(including wraparound/reuse) fails; this bounded experiment does not attempt to
disambiguate it using a counter guessed from output order.

`result()` returns NULL until every requested output succeeds, and after any
schedule failure. Slots are in observation/callback order, not array order.
The result is a borrowed private copy, valid only until same-owner finish; it
does not certify subsequent decoding, EOF, the kernel association or a whole
campaign. Recheck after decoding and validate all campaign evidence separately.
An absent selected output remains incomplete: NULL is not success. `finish()`
means cleanup succeeded, including cancellation/incomplete/error paths, not
that all planned outputs were seen. The external finite run deadline remains
necessary. The legacy `arm()` retains its existing first-output-only behavior.

## Published allocation boundary

Scheduling cannot make an ineligible allocation eligible. The accepted allocator
tracks publication/aliases for the allocation lifetime, even after a Gst buffer
is recycled. Thus an ordinary small capture pool can publish all its allocations
before a late frame (such as the desired RPS_E window) reaches this callback.
That selection must fail; clearing the publication bit on reuse would erase
the alias/lifetime proof. The new `schedule-reuse` regression cycles the actual
four-allocation pool through publication and checks refusal on reuse.

Positive scheduling tests use twelve actual model allocations (memfd backing,
fake V4L2) for eight selections plus nonselected outputs. This is a test of the
real callback/scheduler over eligible allocations, **not** evidence that the
production pool can observe the later RPS_E writers. No production allocation
count is changed. The next owner must design/review a pre-publication selected
allocation retention strategy or a separately proven alias-release contract;
neither a larger test pool nor frame-number matching resolves this live gate.

## Same-run kernel join: still not implemented

The existing Gst observer generates a 128-bit run, context generation and
request/allocation/writer generations. Its queue trace exports those scalars.
The accepted kernel reference/command collectors instead arm a separate u64 run
and bind a kernel context via opener PID. Their sealed records contain allocation
tokens, writer/completion identities and raw V4L2 timestamps. Normalized reference
JSON intentionally removes raw timestamps. These are different identity domains;
neither matching POC/index/frame nor using the same output directory binds them.

A real join needs a finite-run supervisor/controller that records the actual
client session and actual kernel arm/context binding before queueing, captures
complete successful client queue records and the raw sealed kernel snapshots,
rejects loss/foreign contexts/ambiguity, then joins request timestamp and capture
index within those bound lifetimes and checks allocation/writer transitions and
completed-reader frontier. It must run the existing reference validator and
selected-command oracle, not replace them with a syntactic match. The controller
also needs exact live dependency/corpus attestation and reviewed manifest.
Historical PR76 captures lack these observer identities and cannot be upgraded.

No join tool or fabricated binding is introduced by this scheduling slice.
No kernel code, shipped patch, approved manifest, hardware operation or support
count changes. #82 and driver #42 stay open. The additive
[FFmpeg/VA call site](../va-callsite/README.md) is now separate and complete
offline; the same-run join, live manifest and guarded off/on DMA campaign remain open.
