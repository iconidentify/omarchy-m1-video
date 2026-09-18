# Reference-content integration contract

AI-assisted implementation. Design reviewed by a separate Codex agent; this is
not independent human review or hardware qualification. Existing VA/Gst patches,
authors, tests and historical evidence remain unchanged.

The integration extends the real retained-allocation APIs with private bounded
read-only copies. Receipt normalization preserves separate VA surface and Gst
request identities. A normalized receipt is metadata, never permission to map.
Generations from different clients or run tokens are never compared numerically.

## Admission and lifetime

The actual adapter verifies the exact current owner/session/lease, selected
allocation and writer, successful drain, absence of pending readers and external
alias history. It derives allocation policy from successful CREATE_BUFS/QUERYBUF
operations, retaining the input memory/type/flags and actual returned index and
extent. Only coherent MMAP capture allocation at the audited source is admitted.
The first scope is single-plane NV12, 448 by 240, stride 448, plane length 345600
or 368128. No format is inferred from a POC, allocation size or filename.

VA follows api_mutex then context mutex. Gst follows its existing observer mutex
and allocator ownership; it never invokes public gst_buffer_map. Neither exports
a pointer or fd. Producer/destruction gates remain active across mapping, copying,
final validation and unmapping. The caller must end the native lease on every
exit path; an unsuccessful end retains ownership for a retry. Copy failure stops
the pool and never fabricates a valid snapshot or releases an unknown lease.

## Coherence provenance

No approved live build manifest ships with this experiment. Live copying must
fail closed until a separately reviewed manifest binds the exact client/observer
build, kernel/DMA implementation, modular vb2 builds, and patched AVD
module. Runtime verification must bind the actual retained video fd through
fstat, QUERYCAP and sysfs driver/module identity and compare loaded ELF build IDs.
An arbitrary expected-ID JSON file or caller-provided coherent boolean is not
an authorization source. AVD module identity alone does not attest vb2 or DMA.

The offline fixture explicitly supplies fake device/sysfs/build evidence and
checks the executed verifier and allocation selection. Its memory is synthetic;
passing these tests cannot establish hardware cache visibility.

## Bounds and disturbance

Allocate the eight-slot 1474560-byte output pool before begin. Each snapshot maps
one bounded plane read-only, copies only compression [161280,338432) and the final
7168 MV bytes, then unmaps before releasing the native lease. Copy off/on perform
the same mapping, lifetime and provenance checks. No allocation, hashing,
serialization or callbacks occur within the timed two-memcpy interval (20 ms).
The whole mapping/copy operation checks the native lease's original absolute
deadline before admission and after validation. This is a result-acceptance
deadline, not a hard wall-clock timeout: synchronous file/sysfs reads, ioctls,
mmap/munmap and memcpy cannot be interrupted by these checks. Cancellation stays
disabled while the native lease is retained. Live qualification must account for
blocked operations and use the separately authorized external guard; this
offline implementation does not prove bounded device response or lease duration.

Before and after copying, allocation/writer/lease and runtime identity must still
match. Failures after transfer reserves a slot consume that slot and leave it invalid.
Admission refusals before transfer do not reserve a slot. Failures after acquiring
the outer native snapshot lock stop the pool, including VA context-mutex
contention; initial disabled/owner/outer-lock-contention refusals return without
changing it. Raw bytes remain private. Hashing and publication happen only after end.
Same-run command/reference association and the separately guarded B/E x VA/Gst x
off/on campaign remain required; old captures cannot acquire new provenance by
attaching a normalized receipt.
