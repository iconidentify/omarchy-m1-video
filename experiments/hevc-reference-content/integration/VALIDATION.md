# Offline validation — 2026-09-18

AI-generated test record. No hardware, device leases, installation, shipped patch
changes or module operations. Base `69815eacb0aac6501d87b75b94d2603df9b8178a`.
Tool versions, source revisions and exact local artifact hashes are in
[evidence.json](evidence.json). Those binaries record the initial locally passing candidate, before final SPDX/
documentation edits and fixture-only glibc portability diagnostics. Hosted checks
build and exercise the submitted source, including the fortified syscall wrapper. The GLib generator
tools missing from the host were extracted to a temporary directory from a
signature-verified Arch Linux ARM package; no package was installed.

Commands from the repository root (the cached archives were still hash-verified):

```sh
python3 experiments/hevc-reference-content/integration/tests.py --client va --keep /tmp/video82-va-final --archive /tmp/video-82-va-baseline-20260918/source.tar.gz
python3 experiments/hevc-reference-content/integration/tests.py --client gst --keep /tmp/video82-gst-final --archive /tmp/video-82-gst-baseline-20260918/source.tar.gz --native-file /tmp/video-82-build-tools-20260918/native.ini
bash -n install.sh uninstall.sh bin/apple-avd-rebuild tests/rebuild.sh libva/PKGBUILD libva/libva-v4l2_request-avd.install
bash tests/rebuild.sh
python3 experiments/hevc-reference-content/tests.py
```

| Check | Result |
| --- | --- |
| Complete configured VA driver; original Meson suite | 195 passed, 0 failed |
| VA integration, actual driver code | 27/27 under ASan/UBSan; 27/27 under TSan |
| VA original observer modes on extended code | 21/21 under each sanitizer configuration |
| Complete configured Gst plugin and pinned linked libraries | Built under both sanitizer configurations; linkage verified |
| Gst integration, actual decoder/allocator/client code | 25/25 under ASan/UBSan; 25/25 under TSan |
| Gst original observer modes on extended code | 29/29 under each sanitizer configuration |
| New semantic mutations | 6/6 VA and 6/6 Gst detected by named assertions |
| Existing Python/reference-content suite | 25 groups passed; prior synthetic/helper mutation checks retained |
| Installer/rebuild offline checks | Passed, including consent gate |
| Driver `sh tests/frame-check.sh` without arguments | Software resolution/crop hashes match; truncated input rejected |
| Driver `sh tests/shared-contexts.sh` without arguments | Four software streams; all 168 frames match independent decoders |
| Workflow/document checks | YAML parsed; local links checked; existing jobs retained |

Before these changes, the existing full VA/Gst adapter runners also passed their
21/29 modes under both sanitizers, original regressions and 9/12 semantic mutations;
the Gst baseline included its 48 original HEVC software tests. Those baseline
runs do not constitute hardware codec-vector results. Integration adds two CI
matrix jobs and preserves the existing reference-content and Gst observer jobs.

Mutation detection requires compilation success followed by SIGABRT at the named
semantic assertion, without a sanitizer diagnostic. A generic crash or timeout
cannot satisfy the mutation check. The Gst allocation mutant removes both redundant
allocation checks; no claim is made that removing either alone defeats admission.

Not run: hardware B/E off/on workloads, live DMA/coherence or display tests,
production client hooks, same-run kernel command/reference collection, deployment
manifest approval and full hardware codec suites. These require the missing
integration/review gates and a separate guarded hardware scope. Raw model bytes
are checked inside tests and are not published as hardware observations.


The first Ubuntu/x86 hosted integration run refused its positive copy while both
ARM runs passed. The diagnostic counters placed refusal after manifest/device stat
checks and before the ordinary wrapped device-link call. Extending the synthetic
syscall boundary to glibc's `__readlink_chk` made the VA hosted suite pass without
changing production admission or expected results. The model also logs fortified
call counts so the emitted path is visible in subsequent hosted runs. This is a
fixture-portability correction; initial red checks are retained in PR history.
