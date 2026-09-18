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

A stubbed harness can compile four selected helpers. That does not implement
all-producer pause, retained allocation identity, exporter admission, same-run
writer joins, or copy/lifetime tests. Original #82 acceptance criteria remain
open; do not replace them with fixture results or a new research child.


## Static source inspection added after PR83

PR90 adds hash-pinned retrieval and exact function-body identities for selected VA
driver, FFmpeg VAAPI, vb2 exporter and upstream AVD completion sources. Run `python3 experiments/hevc-reference-content/tests.py` from the repository
root to repeat the 23 groups and four synthetic-source mutations. File and extracted-function drift are rejected. The C bodies are
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

`real_barrier.py` now **compiles and runs** those four extracted functions
with recorded stubs. The wait waits one capture index on one `video_fd`;
reader-wait polls only that buffer's dmabuf fds; CPU-access is a no-op and
does not mint a generation. There is still no client API that pauses all
producers and retains writer identity through a later copy. Hardware copy
stays unauthorized. Parent #42 remains open.
