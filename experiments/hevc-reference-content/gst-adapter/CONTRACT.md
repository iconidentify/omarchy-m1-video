# Gst v4l2slh265dec observer contract

AI-assisted implementation and maintainer adversarial self-review. The source is
pinned at `070125524a8422e29d3b69a372ed4f62fd343ffa` (GStreamer 1.28.7).
This experimental patch is separate from shipped patches and installation.

## API and supported operation

`gst-observer.h` is an internal plugin API: `open`, `select`, `begin`, `end`,
`close`. It is not a public GStreamer ABI, an opaque GstElement cast, a pipeline
PAUSED operation, or a callable CPU-copy capability. A future in-plugin caller
must supply live owned `GstV4l2Decoder` and `GstV4l2Request` references. A successful
`open` binds an explicit session to its calling GThread. Merely building the patch
does not enable a session. Failed APIs preserve their output arguments, including
a live receipt supplied to an accidentally repeated begin.

Supported observation requires the actual HEVC-slice decoder, both queues streaming,
a full non-HOLD request with successful submission, its original allocator-owned
CAPTURE planes, and no intervening retirement or external alias history. Requests
still under construction prevent begin. Subrequests/HOLD history, failed
submission/completion, foreign/detached/unsupported allocation, raw request/export
FD access, published output and mapped/shared CAPTURE memory are rejected. Once a slot
has been published/mapped/shared it remains ineligible across recycling. Conservative
rejection is intentional; no inference about a closed external alias's lifetime
is made. Recreate the context after flush, streamoff or post-submission format/
buffer reconfiguration before observing again.

## Actual boundaries and lock order

The recursive observer mutex spans the **whole** actual queue operation: bitstream
QBUF, CAPTURE QBUF, MEDIA_REQUEST_IOC_QUEUE, pending-queue insertion and completion
bookkeeping. It also spans request allocation/ref/unref/final destruction/reuse,
decoder mutation and lifecycle APIs, allocator preparation/release/detach and
memory-map/share admission. Admission and the corresponding side effect are not separate
critical sections. The global mutex conservatively serializes participating
contexts. Active lease checks are per context.

Ordering is codec stream lock (when held by GStreamer), then observer mutex, then
allocator object lock. Observer APIs do not acquire the stream lock. Allocator
wait/flushing paths use only their allocator lock and never acquire the observer
mutex while holding it. Buffer-pool callbacks run without a held pool queue lock.
The H265 output callback holds the observer mutex through completion and publication marking; it explicitly releases it before
framework ownership/copy operations and downstream `finish_frame`/push.
Renegotiation and error-message callbacks also run outside this mutex, avoiding
a lock held across external pipeline work.

The client stop, flush, close, streamoff and allocation-reset callbacks reject
before destructive state changes during a lease. Allocator detach, requeue,
format changes, raw export and CAPTURE mapping/sharing cannot silently invalidate a held
allocation. Normal stop/flush semantics apply again after release. An observer
caller must handle a rejected operation; this patch does not change GStreamer
state transitions into an automatic wait-for-observer protocol.

## Drain, ownership and deadline

`begin` defers pthread cancellation, obtains the same producer mutex using a finite
try-lock loop, validates session/selection, and acquires actual request,
GstBuffer and bitstream GstMemory references before draining. It holds the mutex
through the complete pending request queue. Every head has a temporary real
request reference while `gst_v4l2_request_set_done` retires the pending reference.
The V4L2 video FD is nonblocking. Poll uses the operation's remaining absolute
CLOCK_MONOTONIC deadline, recomputed after EINTR. Zero means now + two seconds;
explicit deadlines must be in the next two seconds. This bounds user-space lock
and poll waits, not arbitrary malfunctioning kernel ioctl execution.

Success requires every submitted request completed, no pending reader, no failed
DQBUF, and the selected request's completed writer matching its current allocation.
Sink DQBUF must match its actual bitstream index. Capture DQBUF must match both the
request timestamp/frame identifier and CAPTURE index, and have no error flag.
One DQBUF or a guessed frame/POC label is insufficient. A failed drain releases
all temporary pins, leaves no active lease and makes observation fail closed.

A successful lease keeps strong references to the actual request, its picture
GstBuffer, bitstream memory and decoder. Those buffer memories retain the actual
allocator/allocation. The GstH265Picture parser/POC metadata object itself is not
an ownership handle; the selected pixel storage is the retained GstBuffer.
Dropping all caller references cannot REINIT/recycle the selected request or
return its capture memory before end. `end` checks the owner/session/unique lease,
clears the lease under the mutex, blocks new producers during cleanup, executes
real final-unref/recycle paths, then releases the decoder and restores cancellation.
Wrong-owner, stale and repeated end calls fail without releasing another lease.

The session holds a GThread reference, so a later thread cannot inherit ownership
by recycling an OS thread ID. Cancellation is deferred from successful begin
through end's release, and is restored on every failed begin. The owner must call
end, including on its own error paths; abandoning a lease leaks its pins and keeps
that context blocked. Asynchronous cancellation of arbitrary GStreamer streaming
workers is unsupported; normal framework stop/flush is the lifecycle protocol.

## Identity and same-run join

All receipts are fixed-size metadata: a random 128-bit run/context-instance token,
monotonic context creation generation and session nonce, request checkout
creation generation, actual allocator-buffer creation generation, successful queue
writer generation, lease generation, submitted/completed counters, frame number,
CAPTURE index, plane count and bounded plane lengths. Generation exhaustion fails
closed; random-token acquisition failure disables observation. Numeric pointers,
FDs, POC and CAPTURE index alone are not identities.

The old allocation writer is invalidated before queue-side effects; a new writer
is assigned only after both QBUFs and MEDIA_REQUEST_IOC_QUEUE succeed. Completion
is assigned only by successful matching real dequeue transitions. Reused request
objects receive new generations; a recycled allocation preserves its allocation
generation while each successful writer changes. There is no borrowed-pointer
registry or fixed registry capacity.

When the existing GStreamer decoder trace category is enabled, a successful queue
in an observer session emits `observer-queue` with exactly the receipt's run,
context, allocation, request, writer, frame and capture tuple. The no-device test
joins that actual logging callback to the subsequent begin receipt. Parent #82
must propagate that tuple into its same-run command/reference capture; old
captures and synthetic labels do not acquire provenance from this API.

## Evidence boundary

The complete configured plugin and its actual APIs execute with a fake V4L2
syscall model, real Gst object ownership and memfd storage. Model mapping exercises
sticky exclusion, not hardware cache visibility. Tests cover producer contention,
pending readers, cancellation, timed lock/poll failure, partial drain cleanup,
stop/flush/detach gates, request/allocation reuse, same-run trace identity,
external publication and wrong dequeue identity. Mutations must hit named
semantic assertions without sanitizer diagnostics.

This leaf does not prove exporter provenance, CPU-access callbacks, cache
coherence, memory-copy eligibility, full live HEVC client decoding or a corruption
fix. Parent #82 and driver #42 stay open. No installation or hardware campaign
is performed by the recipe.
