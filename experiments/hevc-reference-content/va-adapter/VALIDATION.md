# Offline validation, 2026-09-18

AI-assisted implementation and maintainer adversarial self-review. No independent
specialist review or hardware result is claimed. Original z23 history is retained.

The final committed patch was applied with `patch -p1 --fuzz=0` to a fresh verified
archive, configured with its original Meson build and generated headers, and
executed by the committed runner. Full results and exact module/test/mutation
binary hashes are in [validation-20260918.log](validation-20260918.log).

| Check | Result |
| --- | --- |
| Full configured driver build, ASan/UBSan | Pass |
| Existing driver Meson tests | 195 passed, 0 failed |
| Actual public API observer cases | 21 passed under ASan/UBSan; 21 passed under TSan |
| Semantic mutation checks | Nine detected by their named assertions; no sanitizer crash counted |
| Software frame check | Native-size hashing, resolution/crop and truncation checks pass |
| Software shared contexts | Four streams, 168 frames match independent decoders |
| Companion Bash syntax / mocked rebuild baseline | Pass |

Observer cases cover successful drain/retain/resume, a still-issued reference
reader, normal closed current-picture state, all public mutation/destruction
gates, repeated and stale leases/sessions, actual surface/capture/context reuse,
foreign display/thread, thread-ID reuse, owner cancellation, real-entrypoint
producer contention, expired deadline, EAGAIN/EINTR deadline exhaustion, failed
queue/decode, open and partially issued pictures, conversion, VPP, DMABUF import,
closed export/derived aliases, uploads, and trace/receipt tuple equality.

Commands (run from the companion root unless noted):

```sh
python3 experiments/hevc-reference-content/va-adapter/tests.py \
  --archive /tmp/pr-audit-20260917/va-source/source.tar.gz \
  --keep /tmp/observer-completion-20260918/final
bash -n install.sh uninstall.sh bin/apple-avd-rebuild tests/rebuild.sh libva/PKGBUILD libva/libva-v4l2_request-avd.install
bash tests/rebuild.sh
# From the patched driver source, no device/driver-directory argument:
sh tests/frame-check.sh
sh tests/shared-contexts.sh
```

Toolchain: native aarch64 Linux, GCC 16.1.1 (20260430), Meson 1.12.0,
Python 3.14.7, libva pkg-config API 1.24.0, libdrm 2.4.134, Bash 5.3.15.
The runner preserves the production configuration and compiles all original
sources plus observer.c; original tests use the driver's syscall model. It does
not enumerate/open a real V4L2 device. Codec payloads in the observer test are
explicit model data, including the HEVC trace-join case.

Pinned source: `c77e7b566f7baf9c7a2aad797e62c9aa578d9687`.
Archive SHA-256: `a82f316c0468d3a5490bcfc33c8a876eab0e2b55ec1416b88f7f920535fc5bf4`.
Patch SHA-256: `64d5f77f80ccac6cb0664c368a3be8179dffe2b248b659337bbffce79caa2fa0`.
A live GitHub comparison with production `62e7dc512cdb03485d37dcfd0d91861ff9730bef`
confirmed no changes to `src/` or the included failure-cleanup model after this
pin; later differences are documentation/evidence and Meson test registration.

The corrected architecture replaced borrowed numeric/current-picture identity
with creation/queue/dequeue-derived tokens, excluded alias/reuse paths, made
output preservation and cancellation explicit, and tested the actual API.
The failed intermediate writer mutation showed that removing one of two writer
checks left the second protective check intact; the final mutation corrupts the
actual queue-derived writer assignment and is detected on a real resubmission.
No previously successful check is represented as independent review.

Unrun and out of scope: real decoder/client campaigns, kernel command capture,
exporter/cache/coherence validation, mapped-byte copying, installation and module
operations. Parent #82 and driver #42 retain those gates.
