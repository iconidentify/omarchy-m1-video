# FFmpeg HEVC VA output call site

AI-assisted implementation for [#114](https://github.com/iconidentify/omarchy-m1-video/issues/114).
This additive experiment wires the merged VA observer and bounded-copy APIs into
the pinned FFmpeg n9.0.1 HEVC decoder's actual output path. Parent
[#82](https://github.com/iconidentify/omarchy-m1-video/issues/82) and driver
[#42](https://github.com/iconidentify/libva-v4l2_request/issues/42) stay open.
Nothing here is installed or enabled by default.

The offline result-export extension is tracked by
[#118](https://github.com/iconidentify/omarchy-m1-video/issues/118). It adds the
third, FFmpeg-program-only input option `va_observer_report`. In the `ffmpeg`
program, `va_observer_outputs` and `va_observer_report` must be set together or
decoder initialization fails. The report option is per stream; using one path
for multiple observed streams makes the second publication fail rather than
mixing records.

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

## Real FFmpeg worker result path

The patched `ffmpeg` program carries the explicit report path through its real
input-stream option handling into `DecoderPriv`. After decode, downstream EOF
and decode-error-rate checks succeed, `decoder_thread()` calls
`ff_vaapi_decode_observer_write_report()` on the same worker that owned
send/receive. That call repeats finish safely, validates the final result and
publishes it before `avcodec_free_context()`. Any finish, result, serialization,
write, sync, close or publication error becomes the decoder-thread error; no
success record is published.

The later guarded runner will use the equivalent per-stream option shape below;
the paths and ordinals here are illustrative, not approved campaign inputs:

```sh
ffmpeg -threads:v:0 1 -va_observer_outputs:v:0 1,3 \
  -va_observer_copy:v:0 1 \
  -va_observer_report:v:0 /private/run/va-result.json \
  -hwaccel vaapi -i input.hevc -f null -
```

The record has the fixed schema `omarchy.hevc.va-observer-result/v1`, is bounded
to 8192 bytes and contains only output ordinals, VA surface IDs, normalized
run/context/session/allocation/writer/completion identity, capture index, copy
flags and SHA-256 digests. Sixty-four-bit identities are fixed-width lowercase
hex strings so JSON consumers cannot lose precision. Copy-off hashes are null.
The pool, mapped bytes, DMA addresses, pointers, receipts and file descriptors
are unreachable from the serializer.

Publication uses a mode-0600 temporary regular file in the destination
directory, full write, `fsync()`, close and atomic
`renameat2(RENAME_NOREPLACE)`. An existing file or symlink is never replaced.
The strict offline collector rejects symlinks, non-regular or oversized files,
truncation, duplicate JSON keys, extra/raw fields, duplicate or unexpected
ordinals and a mismatched copy mode:

```sh
python3 experiments/hevc-reference-content/va-callsite/collector.py \
  /private/run/va-result.json --outputs 1,3 --copy on \
  --process-exit-code 0
```

A later authorized runner will supply that exclusive destination. This leaf
does not launch a decoder or authorize a campaign.

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
builds the real `ffmpeg` program and selected libraries under ASan/UBSan and
TSan, and links the actual observer implementation into an executable fixture.
The fixture's fake driver is a DSO so the real
`dladdr`/`RTLD_NOLOAD`/symbol-origin path executes. No device is opened.

```sh
python3 experiments/hevc-reference-content/va-callsite/tests.py \
  --keep /tmp/hevc-va-callsite
```

Twenty-nine positive/fail-closed cases cover default-off, copy-off/on, bad
display, wrong driver origin, late arm, threaded and foreign-owner rejection,
ABI mismatch, duplicate selections, target/receipt mismatch, snapshot failure,
failed-end retry, native-close retry, incomplete finish and post-finish output
rejection, including flush and uninit retry paths. The result cases add
deterministic copy-off/on reports, absent,
incomplete and sticky observers, persistent end and native-close failure, write
failure, foreign-owner reporting and pre-existing destinations. Five strict
collector rejection cases cover raw fields, missing hashes, duplicate ordinals
or mixed observation identity, and duplicate keys; separate checks reject a
failed process and symlink destination. Nine compiled semantic
mutations cover driver origin, ABI, open-before-submit, single-thread ownership,
owner-thread enforcement, selected-surface binding, duplicate selection and
retained-lease cleanup, plus sticky failed-result rejection. A tenth removes
the actual output hook and must fail the dequeue-before-publication assertion.
Four more mutations attack normalized-only serialization, exclusive publication,
report ownership and worker-before-free ordering.
Compiler, timeout or sanitizer failures are not counted as mutation detections.

The paired `driver-client-abi.patch` is layered after the existing VA adapter and
copy-integration patches. The existing VA integration job builds it in the full
driver; this call-site fixture exercises the client against a fake DSO.

## Remaining boundary

This supplies an actual FFmpeg-program result path and strict offline collector,
not a hardware runner. It does not provide a reviewed live manifest, full
dependency/corpus attestation, the actual same-run kernel command/reference
join, hardware DMA visibility evidence or the Gst runner. Output ordinals are
selection hints, not proof of writer identity; the real receipt and kernel join
must establish that identity in each run. No support count changes until the
guarded campaign identifies a cause and an actual correction passes driver
#42's full gates. See [RUNNER-REVIEW.md](RUNNER-REVIEW.md) and
[RUNNER-VALIDATION.md](RUNNER-VALIDATION.md) for #118 evidence and limits.
