# FFmpeg HEVC VA output call site

AI-assisted implementation for [#114](https://github.com/iconidentify/omarchy-m1-video/issues/114).
This additive experiment wires the merged VA observer and bounded-copy APIs into
the pinned FFmpeg n9.0.1 HEVC decoder's actual output path. Parent
[#82](https://github.com/iconidentify/omarchy-m1-video/issues/82) and driver
[#42](https://github.com/iconidentify/libva-v4l2_request/issues/42) stay open.
Nothing here is installed or enabled by default.

The patch adds two private HEVC options. `va_observer_outputs` arms one to eight
distinct zero-based output ordinals; its absence is a no-allocation/no-symbol-
lookup fast path. `va_observer_copy` chooses the existing copy-off/on behavior.
The first real `vaapi_hevc_start_frame()` opens the native observer session
before that picture is submitted. Late arming is rejected.

The observer lease is owner-thread-bound while FFmpeg frame threading rotates
the shared VA state across worker threads. Armed decoding therefore requires
`threads=1`; any active frame/slice threading or another thread count fails
closed before symbol binding or session open. All armed send/receive, flush,
result and close activity must remain on that same application thread; a
cross-thread output fails before selecting a surface. The default-off path is
unchanged.

When an armed ordinal reaches the actual `hevc_receive_frame()` dequeue path,
the hook retains that exact `AVFrame`, selects its real `VASurfaceID`, begins the
driver lease, runs the existing bounded snapshot and ends the lease before the
frame is returned. Unselected outputs never read the manifest or map content.
Display order may differ from submission order; the returned normalized record
retains both the selected output ordinal and the driver's same-run writer tuple.

After every native end succeeds, copied bytes are hashed in process and remain
private. `ff_vaapi_decode_observer_result()` returns only normalized identity,
the copy flag and SHA-256 digest after a complete successful finish. It never
returns the pool, a DMA pointer, fd or raw bytes. Copy-off records contain no
digest. Flush and EOF finish the one observation; a failed native end retains
the exact receipt and an `AVFrame` reference for same-owner retry. A decoder
cannot be rearmed after success or failure.

The observing client must finish any retained end retry on the owner thread
before `avcodec_free_context()`. FFmpeg's generic close API cannot report a
hardware-uninit failure; if a persistent native-end failure reaches uninit, the
patched VA callback deliberately skips VA-context/session destruction and keeps
the held frame rather than releasing a retained allocation. That is a fatal
quarantine, not a recoverable close path, and the campaign must reject the run.

## Loaded-driver binding

`VADisplay` is not cast to `VADriverContextP`. The hook first validates the
libva display magic and obtains its real backend context from `va_backend.h`.
It locates the DSO containing that context's `vaEndPicture` vtable entry, opens
that already-loaded object with `RTLD_NOLOAD`, and requires every private
observer/content symbol to resolve from the same DSO base. A paired private ABI
token is checked before the first call. The existing content runtime verifier
still requires its root-owned exact build manifest before any live copy.

This is a private paired experiment, not a proposed libva ABI and not an FFmpeg
upstream interface. Another VA driver, a different observer ABI, a guessed
global symbol, a fake display and a post-submission arm all fail closed.

## Offline reproduction

The runner downloads the checksum-pinned FFmpeg archive, applies the patch,
builds the complete selected libraries under ASan/UBSan and TSan, and links the
actual observer implementation into an executable fixture. The fixture's fake
driver is a DSO so the real `dladdr`/`RTLD_NOLOAD`/symbol-origin path executes.
No device is opened.

```sh
python3 experiments/hevc-reference-content/va-callsite/tests.py \
  --keep /tmp/hevc-va-callsite
```

Positive cases cover default-off, copy-off/on, bad display, wrong driver origin,
late arm, threaded and foreign-owner rejection, ABI mismatch, duplicate selections,
target/receipt mismatch, snapshot failure, failed-end retry and incomplete
finish, including flush and uninit retry paths. Eight compiled semantic
mutations cover driver origin, ABI, open-before-submit, single-thread ownership,
owner-thread enforcement, selected-surface binding, duplicate selection and
retained-lease cleanup. A ninth removes the actual output hook
and must fail the dequeue-before-publication assertion. Compiler, timeout or
sanitizer failures are not counted as mutation detections.

The paired `driver-client-abi.patch` is layered after the existing VA adapter and
copy-integration patches. The existing VA integration job builds it in the full
driver; this call-site fixture exercises the client against a fake DSO.

## Remaining boundary

This closes the remaining VA client call-site wiring only. It does not provide a
reviewed live manifest, full executable/dependency/corpus attestation, the actual
same-run kernel command/reference join, hardware DMA visibility evidence or a
runnable campaign. Output ordinals are selection hints, not proof of writer
identity; the real receipt and kernel join must establish that identity in each
run. No support count changes until the guarded campaign identifies a cause and
an actual correction passes driver #42's full gates.
