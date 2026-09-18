# Real client boundary remains blocked

**AI disclosure:** AI-assisted maintainer review. No device experiment.

`real_client_adapter()` always raises a blocked result. Tests exercise VA, Gst and
unknown clients, including records that assert coherent/paused/retained state; none
can enable copying. `Observer` accepts only the synthetic queue. This is deliberate
partial delivery of #82, not an implementation of its real exporter/client adapter.

The source boundary is concrete:

- Driver [SyncSurface](https://github.com/iconidentify/libva-v4l2_request/blob/3570a2e09d232a5a541c63df7d2cf699fa4b096b/src/surface.c#L163)
  calls surface readiness. [wait_on_capture_locked / sync_capture](https://github.com/iconidentify/libva-v4l2_request/blob/3570a2e09d232a5a541c63df7d2cf699fa4b096b/src/decode.c#L315)
  waits on that capture index under a temporary context lock. It does not hand an
  observer a retained all-producer pause token lasting through a later copy.
- [ExportSurfaceHandle](https://github.com/iconidentify/libva-v4l2_request/blob/3570a2e09d232a5a541c63df7d2cf699fa4b096b/src/surface.c#L998)
  waits for surface readiness and exports a descriptor; that does not prevent later
  reference readers or client surface destruction/reuse. Retaining the fd alone
  keeps storage alive, not the identity of its last writer or client surface.
- Pinned [AVD completion](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-v4l2.c#L926)
  reports a completed job through vb2. DQBUF is not a freeze of all later submissions.
  No GStreamer client pause/retention adapter is implemented or qualified here.
- Pinned [exporter CPU access](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/common/videobuf2/videobuf2-dma-contig.c#L427)
  is no-op; [imported DMABUF handling](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/common/videobuf2/videobuf2-core.c#L408)
  skips prepare/finish sync. A label or SYNC ioctl does not prove a cacheable path safe.
  The full [ownership audit](../hevc-reference-memory/OWNERSHIP.md) distinguishes paths.

Next implementation must derive allocation origin, source/module/client identities,
REQBUFS/CREATE_BUFS policy, mapping permission and length from actual APIs; retain
both allocation and surface generation; stop all producer/requeue threads and drain
successful completions; join same-run command/reference/writer records; verify those
identities before and after the bounded process-context copy. Instrument and test
that adapter's actual pause/retention/error paths before proposing a hardware run.
If this requires a client patch or process-context kernel worker, review its complete
lifetime/locking design first. No IRQ, physical-address or unknown-exporter fallback.

The fake queue is an executable ordering and negative-test design, not proof that
these APIs exist in FFmpeg, GStreamer, VA-API or this kernel. Original #82 acceptance
criteria remain open; do not replace them with fixture results or a new research child.


## Static source inspection added after PR83

PR90 adds hash-pinned retrieval and exact function-body identities for selected VA
driver, FFmpeg VAAPI, vb2 exporter and upstream AVD completion sources. Run `python3 experiments/hevc-reference-content/tests.py` from the repository
root to repeat the current suite. The source audit alone performs no C execution;
the isolated helper tests below have a different scope. File and extracted-function drift are rejected. The C bodies are
**strings only: never compiled, executed or instrumented by this audit**.

`source_audit.inspect_sources` reports that limited scope. It is not a producer
barrier or client adapter. The AVD completion function is upstream base only; the
shipped-patched ownership and actual capture evidence remain in #77/#76. No GStreamer
API is pinned here: our accepted `v4l2slh265dec` path uses direct V4L2, not the VA
backend. Do not infer its capabilities from VA source.

Historical capture/association rows remain rejected even after adding plausible
generation and writer-job labels. The removed joiner could accept those fabricated
fields. Source strings and metadata cannot confer live retention. The real adapter
still unconditionally rejects; no snapshot path or hardware authorization is added.

## Isolated helper execution added in PR94

`real_barrier.py` verifies the pinned file and function hashes, then compiles four
selected bodies into `barrier_harness.c` under ASan/UBSan. The compiled bodies are
`wait_on_capture_locked`, `capture_wait_readers` and the two vb2 dma-contig CPU-access
callbacks. Context/kernel types, poll/dequeue and diagnostics are explicit stubs;
no configured client, VA display, kernel callback dispatch or real fd executes.

Fifteen cases check selected-index completion while an unrelated capture remains
queued, already-complete/empty/drained targets, initial/poll/dequeue errors,
EAGAIN/EINTR retries, a repeated wait ending at a fixed deadline, reader-plane
selection, reader errors/timeouts and the CPU callbacks' return values. Poll calls
must carry the exact device, events and deadline/timeout. Ten changes to actual
helper control flow/arguments must fail semantic assertions: reader error,
reader timeout, negative-fd skip, clearing every queued capture, capture index, wait error, deadline, device,
retry and CPU result. Compiler failure/crash/timeout is not counted as detection.

The original PR94 invented `all_producers_paused`/`generation` fields in a stand-in
context and mutated one of those fields. Maintainer review removed that circular
proof and reproduced an undetected removal of the real reader-error check; the
new error case rejects it. This narrow execution confirms selected helper
behavior under declared stub responses. It cannot establish a real producer
barrier, lifetime pin, cache coherence or live writer identity, nor prove that no
other API/design can provide them. `source_audit.py` remains a separate static
inspection, and the unexecuted FFmpeg/AVD/GStreamer scope remains as stated above.

**Next artifact for #82:** design a concrete default-off client/driver adapter
whose actual submission/requeue entrypoints participate in a pause operation,
whose surface/allocation ownership survives the entire bounded read, and whose
same-run writer/completion records bind that retained allocation. Test its real
entrypoints and cleanup, including outstanding reference readers and error paths.
A patch may introduce the missing API; do not loop on another source scan or
synthetic “no API” assertion. Review locking/lifetime/exporter admission before
any copy path. Every real adapter still rejects, and #82 / driver #42 remain open.

Maintainer validation: 25 Python groups, 15 compiled helper cases, ten semantic
helper mutations and four existing synthetic-source mutations pass under native
GCC ASan/UBSan. These corrections are maintainer self-review; no hardware result
or support-count change is claimed.
