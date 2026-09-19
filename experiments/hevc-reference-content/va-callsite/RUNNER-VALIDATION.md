# Offline FFmpeg result-runner validation — 2026-09-19

AI-executed implementation and adversarial self-review; no independent
specialist review and no hardware access. Repository base
`3d5abb095414dfdcac87b24d12dd46a68addcb9f`.

## Identities

- FFmpeg n9.0.1 source `bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa`;
  codeload archive SHA-256
  `fb1931fd4eb29297ee1c1017a24f800c4d8fbea35b4f2aaeb28308a48a9149b4`.
- FFmpeg patch SHA-256
  `58b7c2b8b009f128011cc4ac858a2a3e59748765e7571ad9521b4069750f9013`.
- Paired driver ABI patch SHA-256
  `21ce2b1df7fcea8001cf0de6496a69ed1da6159e814cc2f42b58c4dd44ab766b`.
- Native AArch64; GCC `16.1.1 20260430`, Python `3.14.7`, libva `1.24.0`,
  libdrm `2.4.134`.

## Complete-source execution

```sh
python3 experiments/hevc-reference-content/va-callsite/tests.py \
  --archive /home/chrisk/src/video-114-work-20260919/runner-self-review2/ffmpeg.tar.gz \
  --keep <fresh-empty-directory>
```

The runner checksum-verifies and extracts the pin, applies with `--fuzz=0`,
builds the real `ffmpeg` program plus selected libraries under ASan/UBSan and
TSan, and executes the fake loaded-driver DSO fixture without a device.

| Build | Cases | `vaapi_decode.o` SHA-256 | `ffmpeg` SHA-256 | Fixture SHA-256 |
| --- | ---: | --- | --- | --- |
| ASan/UBSan | 29/29 | `7690d79cb4160c48efc78b0c35bd98615e8e545b096247996a3304615193b71b` | `a75b201a3d1a0d058b1387aaa0627a3edfd3c1840b27f01bb66a1e6f56ca3d4b` | `4a2680a6ebc2a5728603147ceb2777a97dfe181d975ddfe83d644baed96a825f` |
| TSan | 29/29 | `69b7045b6a102a35e2ec0d95e8dadba8000ffbf6f749507b7c60d988a4ffe215` | `5687e36d00e4c1ed637b8afaeaf173a279a6168cd072c71a894b801853d7ad5a` | `b6145d1c7936246d0fca138ee3f6f7e208ec6220ec5f9b26b551b0084b01d339` |

The 29 cases comprise the original 19 call-site/lifetime cases plus ten report
cases: deterministic copy-off/on success; absent, incomplete and sticky state;
persistent native-end and native-close failure; bounded write failure;
foreign-owner reporting; and a pre-existing destination. Five collector
negative cases reject raw fields, a missing copied digest, duplicate ordinals,
mixed run/context/session identity and duplicate JSON keys. Separate checks
reject a nonzero full-process status and a symlink report.

Fourteen semantic mutations must fail their named assertion: the original ten
driver origin, ABI, open-before-submit, single-thread, owner, selected-surface,
duplicate-selection, lease-release, sticky-result and output-publication gates,
plus normalized-only serialization, exclusive publication, report ownership and
worker-before-free ordering. Compiler failure, timeout or sanitizer diagnostics
do not count as mutation detection. All fourteen passed under the ASan/UBSan
build; the strict collector negatives passed under both sanitizer builds.

## Repository checks

The final head must also pass:

```sh
python3 -m py_compile \
  experiments/hevc-reference-content/va-callsite/tests.py \
  experiments/hevc-reference-content/va-callsite/collector.py
bash -n install.sh uninstall.sh bin/apple-avd-rebuild tests/rebuild.sh \
  libva/PKGBUILD libva/libva-v4l2_request-avd.install
bash tests/rebuild.sh
git diff --check
```

## Limits

The fake DSO executes the real FFmpeg binding, owner, result, serializer and
publication code with synthetic identities/content. It does not open VA/V4L2,
establish DMA visibility, select real corpus outputs, join kernel command data,
or prove corrected pixels. No module, install, reboot, guard lease, hardware
client, raw media byte or support count is involved. The Gst runner, live
manifest, full process/dependency attestation and guarded campaign remain open.
