# Offline validation, 2026-09-18

AI-assisted implementation and maintainer adversarial self-review. No independent
specialist review or hardware result is claimed. Original z23 history is retained.

The committed patch was applied with zero fuzz to a fresh verified complete
GStreamer 1.28.7 source archive. The committed runner configured the original
Meson project, including matching core/base/bad libraries and generated headers,
and compiled the complete v4l2codecs plugin. It did not use extracted struct
layouts or substitute request ref/unref implementations.

Full results, exact patch/test/helper identities, and built module/API binary
hashes are in [validation-20260918.log](validation-20260918.log).

| Check | Result |
| --- | --- |
| Full configured plugin and linked dependencies | Pass under ASan/UBSan and TSan |
| Actual API cases | 29 under ASan/UBSan; 29 under TSan |
| Original HEVC software regressions | 48 checks passed: parser 17, bitwriter 1, element 30 |
| Actual-source semantic mutations | 12 named assertions detect their intended failures |
| Companion Bash syntax and mocked rebuild | Pass |
| Existing reference-content tests | 25 passed, plus four existing source mutations |

API cases cover lifecycle/foreign-thread gates, repeated/stale leases and
sessions, request and allocation recycling, two pending readers, a producer
blocked inside the real MEDIA_REQUEST_IOC_QUEUE call, cancellation, finite lock
and poll deadlines, repeated EINTR, decode/queue/index failures, partial drain
cleanup, unsupported/in-progress requests, context retirement, closed export and
shared-memory aliases, mapped/published output, sticky capture-slot history,
actual H265 output publication and same-run trace/receipt tuple equality.

The fixture links the actual complete H265 client and decoder/allocator/pool
implementations, with synthetic codec/device inputs and fake V4L2 completion.
Its memfd allocations let real GstMemory/GstBuffer ownership and final request
REINIT/recycling execute. Teardown checks all model FDs closed. Model mapping
exercises alias exclusion, not hardware dma-buf visibility. The H265 output
callback test receives a synthetic framework frame; it is not a decoded stream.

Each mutation must compile, then abort on its specific semantic assertion.
Compiler errors, timeouts and sanitizer findings are failures of validation,
not successful mutation detection. Mutations cover producer admission, missing
request pin/end release/failed-begin release, skipped drain, wrong poll budget,
constant allocation/writer generations, foreign owner, mapping/publication,
actual client output hook and capture dequeue identity.

Commands, from the companion root:

```sh
python3 experiments/hevc-reference-content/gst-adapter/tests.py \
  --archive /tmp/gst-observer-completion-20260918/source.tar.gz \
  --keep /tmp/gst-observer-completion-20260918/verified \
  --native-file /tmp/gst-observer-completion-20260918/tools/native.ini
bash -n install.sh uninstall.sh bin/apple-avd-rebuild tests/rebuild.sh libva/PKGBUILD libva/libva-v4l2_request-avd.install
bash tests/rebuild.sh
python3 experiments/hevc-reference-content/tests.py
```

Toolchain: native aarch64 Linux, GCC 16.1.1 (20260430), Meson 1.12.0,
Python 3.14.7, GLib 2.88.3, libgudev 238. This host lacked the GLib code-generator
executables. The optional native file selected local `glib-mkenums` and
`glib-genmarshal` from the official GNOME/glib `2.88.3` tag, substituting only the
Python interpreter and version placeholders. Their exact hashes are recorded;
no host packages were installed. Hosted CI installs the normal development tools
and builds the pinned GStreamer libraries instead of relying on system GStreamer.

Source revision: `070125524a8422e29d3b69a372ed4f62fd343ffa`.
Archive SHA-256: `1def36bd4c68f13cb731740d0cd2697d858c073e674ef54726e97ee245639a44`.
Patch SHA-256: `7375ce4346b0e18be41fa8d7e791efd79a547b6a3cface9ebee0769183781e04`.

An early invocation of the unchanged software tests through generic Meson test
environment scanned all built plugins and reached the pinned upstream V4L2
discovery code, where UBSan reported a null string argument. That invocation did
not pass. The final no-device recipe gives these tests an isolated directory
containing only the three required software plugins; it neither scans the V4L2
plugin nor suppresses sanitizer diagnostics. Full plugin compilation and the
actual decoder APIs remain covered separately by the syscall fixture.

Other intermediate review corrections included real request ownership instead
of borrowed registry pointers, producer-side locking instead of separated
admission/submission, operation-bounded polling, matching dequeue index and frame,
sticky publication/share history, and avoiding the observer mutex across external
framework callbacks. The final archive/patch build supersedes earlier extracted
fixture results; no historical check is represented as independent review.

Unrun and out of scope: real HEVC client decoding, hardware access or qualification,
kernel command capture, exporter/cache/coherence validation, hardware memory
mapping/copying, installation and module operations. Parent #82 must integrate the
same-run receipt tuple with its command/reference records and establish copy
eligibility. Parent #82 and driver #42 remain open.
