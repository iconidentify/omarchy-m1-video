# Offline validation — 2026-09-19

AI-executed implementation and self-review; no independent specialist review and
no hardware access. Repository base
`adfb9e5ec894f32cbf830e3f82fd9cc7f43bb597`.

## Identities

- FFmpeg n9.0.1 source `bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa`;
  codeload archive SHA-256
  `fb1931fd4eb29297ee1c1017a24f800c4d8fbea35b4f2aaeb28308a48a9149b4`.
- FFmpeg patch SHA-256
  `e8a7bbcadc0c0efb144612f978301f535030a036a6f2454312393ad7a26de840`.
- Paired driver ABI patch SHA-256
  `21ce2b1df7fcea8001cf0de6496a69ed1da6159e814cc2f42b58c4dd44ab766b`.
- Driver integration source `c77e7b566f7baf9c7a2aad797e62c9aa578d9687`;
  archive SHA-256
  `a82f316c0468d3a5490bcfc33c8a876eab0e2b55ec1416b88f7f920535fc5bf4`.
- Native AArch64; GCC `16.1.1 20260430`, Python `3.14.7`, libva `1.24.0`,
  libdrm `2.4.134`.

## FFmpeg complete-source client run

Command:

```sh
python3 experiments/hevc-reference-content/va-callsite/tests.py \
  --archive /home/chrisk/src/video-114-work-20260919/runner-final5/ffmpeg.tar.gz \
  --keep /home/chrisk/src/video-114-work-20260919/runner-self-review2
```

The runner configured and built the complete selected FFmpeg libraries twice,
with ASan/UBSan and TSan. It verified the real start/output call-site order and
ran 19 cases under each sanitizer: default-off, copy-off/on, invalid display,
wrong DSO origin, late arm, threaded and foreign-owner rejection, bad ABI,
duplicate selection, wrong selected surface, wrong receipt surface, failed-end
retry, snapshot failure, flush retry, active-uninit retry, incomplete finish,
post-finish output rejection and native-close retry. All 38 executions passed
without a sanitizer diagnostic.

| Build | `vaapi_decode.o` SHA-256 | Fixture SHA-256 |
| --- | --- | --- |
| ASan/UBSan | `f3b00f527eb93cff0983515ab4e9c0760b252b48b76a1730c13be4958d58c763` | `5dc58de60122e0aabeae440f0b81d52e83537c0d9118f93f97b98a1c4450f5b2` |
| TSan | `3f74facbba3bfc5b12554c2dccbc4d166763d748db7a251c8af12f926a615d78` | `9ba28bdadd94a9c672a22d46519bdc7362d757daae834c33175804bbf9977b88` |

Ten semantic mutations were distinguished by named behavioral assertions:
driver-DSO origin, private ABI, open-before-submit, single-thread ownership,
owner-thread enforcement, selected-surface binding, duplicate selection,
retained-lease cleanup, failed-result rejection and output-before-publication
order. No compiler failure, timeout or sanitizer finding counted as a mutation
pass.

## Real driver integration preservation

Command:

```sh
python3 experiments/hevc-reference-content/integration/tests.py \
  --client va --keep /home/chrisk/src/video-114-work-20260919/integration-final
```

The existing complete configured driver accepted the new ABI patch after the
observer and copy patches. All 27 content modes passed under ASan/UBSan and TSan,
the original VA adapter modes passed under both, and all six existing integration
mutations passed. Native fixture SHA-256 values were
`c6820eb9d3c187119f1e7f914de79b66c19f957ef816c77161a5aa2aff9e05b7`
(ASan/UBSan) and
`7c63e22c2412b950af8215011f88ebbc0c45b3480bed1ba486806b08a54b9837`
(TSan).

Repository checks also passed: the prescribed shell syntax set and
`tests/rebuild.sh`, all 30 refusing campaign-controller tests, Python bytecode
compilation for the changed runners/controller, and `git diff --check`.

## Limits and tests not run

The fake driver DSO executes real FFmpeg binding and lifetime code but supplies
synthetic VA receipts and content; it does not prove DMA visibility, firmware
behavior or a live manifest. Gst was not rerun locally because this change is
VA-only; the existing hosted matrix still runs all reference-content/Gst jobs.
No decoder device, hardware guard, module, installation, reboot, raw corpus byte,
or live campaign was used. Same-run kernel association, live dependency/corpus
attestation and the guarded B/E × VA/Gst × off/on campaign remain open.
