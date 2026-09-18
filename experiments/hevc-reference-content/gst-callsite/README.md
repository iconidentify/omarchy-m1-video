# GStreamer HEVC output call site

AI-assisted implementation for [#82](https://github.com/iconidentify/omarchy-m1-video/issues/82).
This additive experiment wires the existing observer and bounded-copy API into
the pinned GStreamer HEVC decoder's **actual registered output callback**. It
applies after the accepted observer and copy-integration patches. Existing
patches and historical evidence remain unchanged.

The unarmed decoder does no new allocation, session creation, build-manifest
read, or content mapping. The internal `gst_hevc_callsite_arm()` API deliberately
arms one output, on the streaming owner, after initial format/pool negotiation
and stream-on but before the first request is allocated or submitted.
It is not a GStreamer launch property or a shipped activation
recipe. A future in-plugin campaign controller must call it at that boundary.
Calling it after submission is rejected by the actual decoder counters.

At the output callback, the hook verifies the actual request/output-buffer
relationship, selects that request's live writer/allocation, drains through the
existing native begin API, checks frame identity, takes the bounded snapshot and
ends the lease. Only then does the original callback mark the buffer published
and invoke framework delivery. Later outputs do not take more snapshots.
The `copy=FALSE` control performs the same retention, mapping, provenance and
cleanup operations without copying bytes. The native eight-copy lifetime budget
and all existing geometry/exporter/build checks remain in force.

## Ownership and failures

The internal APIs take the decoder stream lock; the output vfunc is called with
that lock held by GStreamer. Lock order remains stream, observer, allocator.
The arm owns an explicit element reference and GThread reference until a
successful same-owner `gst_hevc_callsite_finish()`. Call finish after the callback,
including a failed callback, or to cancel an arm before output. The caller must
retain its own ordinary element reference while using these APIs. The returned
result is a borrowed private heap copy, valid only until finish, never a DMA
pointer or automatic publication of raw bytes.

A rejected begin or copy returns `GST_FLOW_ERROR` and drops the output after
releasing the observer mutex. If native end cannot unmap, the callback transfers
its frame and picture ownership into the call-site state, returns an error and
withholds publication **and** framework dropping. The native lease, map, decoder,
request and allocation stay retained. Finish must run on the same owner to retry
end; only a successful end allows the stored frame/picture to be dropped and the
session closed. A failed finish retains the exact state for another explicit
retry; it does not loop or discard the cleanup token. The client's stop/flush/close,
streamoff and allocation reset refuse while an arm exists, including before begin
and after a successful copy. Otherwise close could invalidate the session needed
by finish. Finish the arm before those lifecycle operations. The arm pointer is
published/removed under both stream and observer locks, matching the lifecycle
callbacks' observer-lock reads. New-sequence handling also refuses before
changing dimensions, controls or entering renegotiation; simply refusing its
void streamoff helper would let that caller continue with inconsistent state.

No user callback is invoked inside the native retained interval. The hook defers
pthread cancellation until its native resources and callback-owned objects are
settled; failed end keeps cancellation deferred until finish can release the
lease. Arbitrary pthread cancellation/exit of a GStreamer streaming owner is
unsupported, as in the underlying observer API: use normal framework lifecycle
operations and fulfill same-owner cleanup. Abandoning the arm leaks its explicit
element reference; abandoning a failed end also retains the native lease. No
timeout silently releases storage still in use.

This is a one-output wiring slice, not the campaign controller. The arm API does
not identify which B/E writer the campaign should sample. No kernel command or
reference collector is joined here. No approved live manifest, full client/corpus
attestation, hardware DMA visibility result, or campaign authorization ships.
VA production call-site wiring remains separate. #82 and driver #42 stay open.

## Offline reproduction

Dependencies and pinned source/license provenance are inherited from
[the Gst adapter](../gst-adapter/README.md) and
[copy integration](../integration/README.md).

```sh
python3 experiments/hevc-reference-content/gst-callsite/tests.py --keep /tmp/hevc-gst-callsite
```

The destination must be empty. `--archive` accepts the original hash-verified
GStreamer archive; `--native-file` supports the same optional GLib tool paths as
the existing runner. The complete configured plugin and actual H265 class/vfunc
are compiled. The fixture supplies fake V4L2 calls, memfds, device properties and
root/sysfs evidence. Its codec frames are framework input fixtures, not decoded
HEVC bitstreams. Framework finish/drop execute their real bodies, with wrappers
checking that no native lease or observer mutex survives into those calls.

Tests cover enabled/control/default-off, one-shot behavior, session timing,
actual buffer/frame identity, all-reader drain, foreign ownership, reentrant
cleanup refusal, failed copy/end and cleanup retry. Both sanitizer configurations
also run the preceding 25 copy and 29 observer modes; software parser/bitwriter
regressions run separately. Semantic mutations must compile and fail at a named
assertion, never count a timeout/compiler/sanitizer error as detection.

See [REVIEW.md](REVIEW.md) for the review record and remaining evidence.
