# Offline validation — 2026-09-19

AI-executed implementation and self-review; no independent specialist review and
no hardware access. Repository base
`adfb9e5ec894f32cbf830e3f82fd9cc7f43bb597`.

## Identities

- FFmpeg n9.0.1 source `bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa`;
  codeload archive SHA-256
  `fb1931fd4eb29297ee1c1017a24f800c4d8fbea35b4f2aaeb28308a48a9149b4`.
- FFmpeg patch SHA-256
  `5011cca17351479f19c91a678a6801590616e699ff496a03b9d148426ebb1833`.
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
  --keep /home/chrisk/src/video-114-work-20260919/runner-final4
```

The runner configured and built the complete selected FFmpeg libraries twice,
with ASan/UBSan and TSan. It verified the real start/output call-site order and
ran 17 cases under each sanitizer: default-off, copy-off/on, invalid display,
wrong DSO origin, late arm, threaded and foreign-owner rejection, bad ABI,
duplicate selection, wrong selected surface, wrong receipt surface, failed-end
retry, snapshot failure, flush retry, active-uninit retry and incomplete finish.
All 34 executions passed without a sanitizer diagnostic.

| Build | `vaapi_decode.o` SHA-256 | Fixture SHA-256 |
| --- | --- | --- |
| ASan/UBSan | `da9f54c123d899da17832c9d5f94382a50ce00fcd4e6e111575bbcc52e226722` | `88cc58ebb37656a096c930b8d74fde32042a7f4e7b7f9f1dd600faa675257470` |
| TSan | `2fca91d51c3d815462f56848b337a27ccd8227f84c6d359875b59b0ed09a9ae7` | `f98cb5be2f298d1b2ee03722fd2b1e01284b74dd30b864264af5f418aea591de` |

Nine semantic mutations were distinguished by named behavioral assertions:
driver-DSO origin, private ABI, open-before-submit, single-thread ownership,
owner-thread enforcement, selected-surface binding, duplicate selection,
retained-lease cleanup and output-before-publication order. No compiler failure,
timeout or sanitizer finding counted as a mutation pass.

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
