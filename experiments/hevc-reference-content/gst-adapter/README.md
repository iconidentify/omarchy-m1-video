# Experimental GStreamer HEVC observer

AI-assisted implementation and maintainer adversarial self-review; original z23
contribution history is retained. No independent specialist review is claimed.

This is the direct-V4L2 GStreamer child
[#96](https://github.com/iconidentify/omarchy-m1-video/issues/96). It adds an
explicit, default-off internal session API to pinned GStreamer 1.28.7. The patch
serializes actual decoder/request/allocator operations, drains the pending queue
under a deadline, retains the selected request and capture allocation, and emits
creation/queue/dequeue-derived metadata. It is not installed by this repository.

The [contract](CONTRACT.md) defines supported inputs, thread ownership, lifetime,
identity and failure behavior. [Validation](VALIDATION.md) records the executed
checks and limits. Parent [#82](https://github.com/iconidentify/omarchy-m1-video/issues/82)
and [driver #42](https://github.com/iconidentify/libva-v4l2_request/issues/42) remain
open for integration, exporter/coherence admission and guarded hardware work.

```sh
python3 experiments/hevc-reference-content/gst-adapter/tests.py
# Keep builds/logs; optionally use a cached archive and local build-tool paths:
python3 experiments/hevc-reference-content/gst-adapter/tests.py \
  --archive /path/to/source.tar.gz --keep /path/to/empty-directory \
  --native-file /path/to/meson-native.ini
```

Requires Linux, Python 3.12+, a C/C++ compiler, Meson 1.9+, Ninja, pkg-config,
GLib development headers/tools, libgudev development headers, flex and bison.
The runner retrieves the complete hash-verified source archive and applies the
committed patches with zero fuzz. It builds matching pinned GStreamer core/base/bad
libraries and the **whole v4l2codecs plugin**, using original Meson configuration
and generated headers. Installed GStreamer versions are not used as an ABI model.

A second, separate patch (`unaligned-io.patch`) fixes undefined behaviour in the
pinned upstream `gstutils.h` fast unaligned read/write helpers, which UBSan caught
on the hosted x86 runner. It rewrites those twelve helpers as byte-order-preserving
`memcpy` operations, touches no observer code and no installed source, and comes
with a focused test that forces the same fast path on ARM.

The API test compiles every original plugin translation unit. It includes the
complete H265 client source to exercise its internal output/stop/flush callbacks;
request, allocator and pool implementations are linked unchanged except for the
committed patch. The syscall model supplies synthetic codec/device inputs and
memfd-backed allocations. It never opens video devices. Real request ref/unref,
REINIT/recycling, GstBuffer/GstMemory ownership and allocator teardown execute.
No extracted struct layout or substitute retention implementation is used.

The suite runs 29 cases under ASan/UBSan and TSan, the focused unaligned IO check
under both, 48 original HEVC software checks, and 12 semantic mutations of actual
producer, ownership, deadline, identity and publication transitions. Original
software checks see only the parser/core/app plugins, preventing device discovery.
Required sanitizer failures are errors, not skips. No installed files, modules or
production defaults change.

This provides metadata only. Model memory mapping tests exercise exclusion of
already exposed allocations; no hardware dma-buf mapping, decoded-pixel copying,
cache visibility, full client decoding or corruption fix is claimed.
