# First M1 delivery comparison — 2026-09-20

AI-assisted maintainer execution and self-review under the owner-approved reset.
Refs driver #45 and companion #21/#27. This is a bounded result, not a release.

**All four baseline/C1 resource rows passed; the selected OpenGL mpv smoke rows
also passed.** The installed stack was unchanged. Chrome, broader transitions,
failure recovery, the full strict corpus and boot stability were not qualified.

## Exact scope and identities

The [plan](../../M1_PLAYBACK_PLAN.md) was committed before execution: resource
plan `8ded5d650669450def133b3fde93528e82b2c4fb`, subsequent mpv plan `b9375fa`.
Driver harness/source candidate: `5b5046cbda6892f4a63df0015857a80bd42c17cf`.
Installed package source: `db3014f9499694c6f186af7e023de07bd5bc3564`.

| Artifact | SHA-256 |
| --- | --- |
| Installed `1.3.r11-2` driver | `ff01edf14cf85f52cf07073da2cf642a9d9b0dde9f055e366478fdb1d2d89a10` |
| C1 separate release-build driver | `dc5315aee9243c0c8f55b0b5904ea83026e32e71f7ed52e76d2e3965ba38b5c9` |
| Installed module file | `e50540e1d0fc48c7e0bf9b21ff028758bdb35f94aa7070af00de88e61e5c70e9` |
| Generated input/reference manifest | `07ffbe3ec5393ccbc15ed1f5a40aeda1e01b9fdad315b471fde67cd02cb83c7d` |

M1 T8103/J293; kernel `7.1.13-3-1-ARCH`, package `linux-asahi 7.1.13.asahi3-1`;
FFmpeg `2:9.0.1-4`, mpv `1:0.41.0-6`, Mesa `26.1.8-1`, libva `2.24.1-1`.
Boot `d0a40094-af95-4bea-8dc2-85693b2f727f` stayed fixed. Loaded and on-disk GNU
build-ID notes matched `85742eb3b2b9f0692370842ae4f3dc439825dc47`; this is not a
memory hash of the loaded module. Artifact hashes were checked again after the
hardware runs. A live candidate-normal process mapping independently confirmed
that the candidate driver path was loaded.

The guard's `userspace.source_commit` identifies its harness checkout, including
in baseline runs. The resource record's `source_commit` and `driver_sha256`
identify the selected driver. Do not confuse those two provenance fields.

## Resource and seek/reopen comparison

Existing `tests/resource-campaign.py` and `resource-workload.c` generated and
checked four 24-frame 640x360 clips: H.264 with B frames, HEVC, VP9 8-bit and VP9
10-bit. Each lifecycle drains, seeks to the start, flushes, decodes again and
closes the decoder while a retained image survives. One VA display spans a row.

| Row | Measured cycles (+ warmups) | Exact frames | Retained images | Measured seconds |
| --- | --- | --- | --- | --- |
| Installed / normal | 400 (+20) | 20,160 | 420 | 82.564 |
| Installed / early export | 400 (+20) | 20,160 | 420 | 85.842 |
| C1 / normal | 400 (+20) | 20,160 | 420 | 82.813 |
| C1 / early export | 400 (+20) | 20,160 | 420 | 85.951 |

Total: **80,640 ordered frame comparisons and 1,680 retained-image checks**.
Every row includes 100 measured lifecycles per codec; warmups are included only
in the frame/image totals. These timings are observations, not a performance
benchmark. The independent software oracle was prepared from the same inputs.

All rows had zero FD, dma-buf, mapping-count, mapped-byte and RSS growth across
401 post-warmup checkpoints. Allocator-accounted peak growth stayed below the
accepted 64 KiB bound (largest 10,976 bytes). The existing 4 MiB mapped/RSS and
zero FD/dma-buf/map-count limits were unchanged. All 40,320 early-export identity
and layout checks passed. Quiescent dma-buf measurements were `none-observed`;
this does not claim the active decoder never allocated buffers.

The 40-cycle software preparation run used a 4 MiB heap bound and passed 2,880
frames. It checks harness operation; it is not the stricter hardware resource
acceptance. The hardware rows used the original 64 KiB heap bound.

## mpv rendered-window smoke

Reused the local `avdlab.playback` helper, whose exact source and hashes are
archived. Each driver ran explicit `gpu-next:opengl:vaapi` and
`gpu-next:opengl:vaapi-copy`, with `--no-config`, start zero and 0.5-second play.
Each call made its own software reference first.

All four hardware rows reported the requested VA mode, a hardware-selection log,
position 0.5 seconds and zero reported render/decode drops. All six 1750x986 PNG
captures are byte-identical, SHA-256
`25f47434e3b2f0802df0fa8f7647dade91707032ee3c47f1994de59c733682ce`.
The helper reported infinite PSNR. Equal sizes and identical PNGs independently
rule out its resize fallback masking a geometry mismatch for these captures.
Visual inspection confirmed the expected synthetic test pattern at time zero.

These are mpv GPU-rendered window captures, not compositor screenshots. One
paused frame and half a second of playback do not qualify all displayed frames,
long playback, mpv seeking, another stream's survival, recovery or Chrome.
The software reference log's direct-rendering fallback is preserved; it is not
counted as hardware decoding. The hardware rows have no reported decode errors.

## Guarding and reproduction

All six invocations used the existing portable guard, an exclusive `avd` lease,
whole-current-boot fault preflight, fresh output paths and finite deadlines.
Every guard ended `ok`, idle, without holders, timeout, wedge or observed fault.
No installation, module operation, kernel change, suspend or reboot occurred.
The final read-only state remains loaded, fault-free and idle; no worker/lease
is retained.

Build with one worker, using the [bounded build wrapper](../../../tools/bounded-build).
From the pinned driver checkout, prepare the existing resource fixtures. Select
the installed directory or C1 build's `src` through `LIBVA_DRIVERS_PATH`, set
`LIBVA_DRIVER_NAME=v4l2_request` and `V4L2R_SOURCE_COMMIT` to the selected source.
Run each row separately only after the preceding complete row passes:

```sh
python3 tests/hwguard.py --identity avd --deadline 300 --log ROW.guard.jsonl -- \
  python3 tests/resource-campaign.py run --directory FIXTURES --mode normal \
  --cycles 400 --max-mapped-growth-kib 4096 --output ROW.jsonl
```

Use `--mode early` for early export. The mpv invocations used a 120-second guard
around the archived helper's `python3 -m avdlab.playback FIXTURES/h264.mkv
--config gpu-next:opengl:vaapi --config gpu-next:opengl:vaapi-copy --start 0
--play 0.5 --min-psnr 40`. They require a normal Wayland desktop and the separate
approved hardware window; the offline evidence verifier requires neither.

The [archive](records.tar.gz) contains 56 records: original frame/result/resource
logs, guard events, fixtures/oracles, identities, helper snapshots and screenshots.
Only local home/workspace prefixes are redacted in text; [the manifest](manifest.json)
retains both original and published SHA-256 values. Original local records and
the actual compiled candidate remain retained. No private media was used.

```sh
python3 docs/evidence/m1-delivery-2026-09-20/verify.py
```

[The verifier](verify.py) checks the archive without extraction, all member and
fixture hashes, raw frame/result ordering, counters, resource samples, selected
driver identities, screenshot equality, actual hardware selection and final
guard states. It does not infer hardware execution from a summary pass flag.

## Delivery decision

C1 preserves this installed-driver workload and passes the selected mpv smoke;
keep it selected only for tests. The next decisive work is a normal-sandbox
Chrome row plus sustained mpv pause/seek/restart and recovery, followed by the
full strict-set/package comparison. No stable or packaged claim is made.
Driver #45 and client/release parents remain open. The HEVC observer experiment
is a separate lane and did not run during this comparison.
