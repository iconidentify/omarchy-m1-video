# VA observer session and allocation contract (companion #95)

AI-assisted implementation and maintainer self-review. Original z23 contributions
remain in PR100 history. This experimental patch targets driver
`c77e7b566f7baf9c7a2aad797e62c9aa578d9687`; it is not installed or enabled by default.
Parent #82 and driver #42 retain integration, coherent memory admission and hardware
qualification. No receipt permits mapping or copying decoder memory.

## API and supported mode

`src/observer.h` exports five experimental driver functions. The argument is the
actual `VADriverContextP`, **not** a libva `VADisplay`. A future client integration
must deliberately arrange access to this exact module/context; casting a display
is invalid. The normal libva vtable ABI remains unchanged.

1. `open(va, context, &session)` opts in on the owner thread. Only one session per
   context is allowed. An unopened/zero, closed, foreign-display, foreign-thread
   or stale session cannot observe or end a lease.
2. `select(va, session, surface, &target)` obtains surface, allocation and successful
   writer identities from actual driver state. This is a selection, not a pin.
3. `begin(va, session, target, deadline, &receipt)` checks the selection again,
   excludes producers, drains **all** queued CAPTURE buffers on the context, and
   returns a metadata receipt while retaining the context/surface/allocation.
4. `end(va, session, receipt.lease)` releases the pin. Only the owner and exact live
   session/lease can end it. Foreign, stale and repeated ends fail without releasing
   a current lease; an old receipt cannot end a later lease.
5. `close(va, session)` disables the session, and fails during a lease. Destroying
   an unpaused context invalidates its session. A later context with the same
   numeric handle has a different creation generation and cannot revive it.

Begin supports a sole decoder context on its display, an owned MMAP CAPTURE
allocation, a complete successful submission, and no external aliases. It rejects
multiple contexts (including foreign VPP readers), conversion, VPP, DMABUF import,
standalone backing, partial pictures, failed queues, failed decoded surfaces and
conflicting observers. Export/derived-image history is sticky on both the surface
and the **allocation**, including after VA image destruction or surface recycling:
closing a local FD does not prove that all external copies/fences are gone.

`PutImage` invalidates decode-writer identity before its copy; only a subsequent
successful decode may establish a new writer. There are no CPU-write aliases in
an admitted lease. The caller must keep the libva display/driver alive and own
its lifetime, as for ordinary libva calls. Concurrent `vaTerminate` with arbitrary
API calls is unsupported; a terminate attempted during a live lease is refused.
Internal unwrapped driver functions are not a client API.

## Exclusion, lock order and deadlines

Order is `drv->api_mutex`, then `ctx->mutex`; handle lookup briefly takes
`drv->mutex` under the API lock. The observer does not hold the handle lock while
waiting for a context lock or device completion. All original driver call sites
continue using their existing order.

| Entry points / transitions | Ownership while a lease is live |
| --- | --- |
| Create/DestroyContext; Begin/Render/EndPicture | Actual public `api.c` wrappers refuse before allocation, codec, bind, reuse or queue work |
| DestroySurfaces | Wrapper refuses before handle lookup/release; capture allocation and selected surface remain alive |
| SyncSurface / QuerySurfaceStatus | Wrappers refuse; no hidden flush/conversion occurs |
| ExportSurfaceHandle / DeriveImage | Wrappers refuse new aliases; preexisting aliases prevent begin, even after local alias destruction |
| GetImage / PutImage | Wrappers refuse CPU reads/uploads; prior uploads invalidate the decode writer |
| VPP and conversion submission | No such context is admitted, including a second context on the display |
| Request/CAPTURE queue, output reuse, capture rebinding, streamoff and context cleanup | Reached through the excluded picture/destruction entrypoints; no independent driver worker submits them |
| CreateSurfaces / CreateSurfaces2 | Can create independent unbound surface objects; cannot rebind or destroy retained storage |
| Ordinary buffer/image create, map, unmap, resize, destroy | Independent host storage; derived aliases are never admitted. These operations cannot mutate retained CAPTURE storage |
| Config/capability/display queries and config objects | Do not mutate the retained allocation; creating a decoder still passes the gated wrapper |
| PutSurface / LockSurface / buffer-handle acquisition / subpictures | Unsupported stubs; no hidden producer path |
| Terminate | Refuses an active lease; display lifetime must otherwise be externally owned |

Begin takes the API lock before looking up the context or selected surface and
keeps it through the complete drain. It then sets `observer_active` before
unlocking. This display-wide ownership pin makes all supported producers and
destructors fail while the lock is released; it does not depend on an exported FD
or the current-picture pointer (which EndPicture clears). End clears the pin under
the same lock. No allocation is detached or reused during the lease.

Zero deadline selects two seconds; nonzero is an absolute `CLOCK_MONOTONIC`
deadline no more than two seconds away. API/context try-lock loops, dequeue/EINTR
retries and every poll share this deadline. There is no initial drain with its own
fresh timeout. V4L2 FDs are nonblocking. An ambiguous drain error/timeout leaves no
lease and marks the context failed, requiring normal teardown/recreation. As with
all userspace deadlines, this does not forcibly interrupt a kernel syscall stuck
inside a broken driver. The end/close lock wait is also bounded to two seconds.
An unsuccessful end retains the lease so the owner can retry; expiry never
silently releases storage still in use.

## Cancellation and caller obligations

Begin disables pthread cancellation before acquiring any lock. Failure restores
it only after unlocking. Success keeps it disabled through the retained interval;
matching end releases the pin and lock **before** restoring the owner's previous
state. A pending cancellation is therefore delivered after release. Foreign or
invalid end calls do not change the owner's cancellation state. Thread-local,
nonrecycled owner generations also prevent `pthread_t` reuse from reviving a dead
thread's session.

The owner must execute end on all ordinary exit/error paths, keep the interval
short, and must not call `pthread_exit`, unload/free the driver, longjmp out of the
lease, or re-enable cancellation before end. These are API lifetime obligations,
not supported observer operations. A dead session without a lease does not pin
storage: normal context destruction disposes of it. Input tokens and output
objects must not alias. Refused calls leave output tokens unchanged, so a nested
begin cannot erase the owner's live end token. No callback, raw pointer or DMA-BUF is handed out.

## Identity and joins

The receipt has fixed size and bounded plane metadata (at most VIDEO_MAX_PLANES).
It contains a display-run identifier, actual context creation generation, session
nonce, unique lease, selected VA surface and its creation generation, capture
allocation generation/index, last successful complete writer sequence, completed
submission frontier, last-reference sequence, and plane lengths from QUERYBUF.

- A display-run identifier is generated at real context creation; entropy failure
  disables observation. It is an identifier, not an authorization secret.
- Context and surface generations are assigned at actual creation. Allocation
  generations are assigned after actual successful CREATE_BUFS/QUERYBUF. They
  survive reuse of a CAPTURE slot and change on new allocation. The process-wide
  generation/nonce allocator saturates instead of wrapping.
- First CAPTURE QBUF clears the old writer. A successful final
  MEDIA_REQUEST_IOC_QUEUE records that frame's actual submitted sequence. CAPTURE
  DQBUF records completion only if the surface is successful. Partial/failed
  requests cannot manufacture a completed writer. Submission-counter exhaustion
  permanently disables observing that context.
- Begin drains all issued CAPTURE readers, verifies the completed writer and
  reference frontier, and snapshots the explicitly selected allocation.
- When a session is open, actual HEVC request trace records include an `observer`
  object with the identical run/context/allocation/surface/writer tuple. Open
  **before** the writer submission and enable the existing HEVC trace to join
  same-run command/reference records. Require a successful last-slice record and
  an exact tuple; no historical trace is upgraded by attaching new labels. Existing
  trace behavior/schema stays unchanged when no observer session is open.

Plane lengths and MMAP ownership are not exporter/cache/CPU-coherence proof.
No physical/DMA address, FD, mapped pointer, payload bytes, `coherent=true`, or
copy-admission bit is exposed. Kernel command association, exporter verification,
bounded content copying, FFmpeg/GStreamer client integration and guarded off/on
campaigns remain parent #82 work.

## Evidence boundary

The harness includes the pinned driver's `tests/failure-cleanup.c` syscall and
allocator model, unchanged. Full driver sources and original Meson-generated
configuration are compiled and linked. The test creates real driver contexts,
surfaces and capture allocations, runs actual public picture/destruction/image
entrypoints and request/dequeue code, and checks model resource baselines. V4L2
and codec payloads are fake; there is no device enumeration or open. A trace test
uses a declared fake HEVC payload with real queued identities and tracer code;
it does not claim a real HEVC decode or kernel command capture.

Both ASan/UBSan and TSan execute the observer cases, including a producer blocked
inside the real public entrypoint, foreign-thread teardown/mutation attempts and
cancellation. Mutation runs require a specific failed semantic assertion; build
errors, arbitrary crashes, timeouts and sanitizer reports never count as detection.
