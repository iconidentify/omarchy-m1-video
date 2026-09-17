# HEVC compressed-reference memory audit

**AI disclosure:** z23 contributed the initial layout audit. Maintainer AI remediation
preserves the author commits, replaces the rewritten arithmetic with verified extraction,
and corrects DMA/lifetime claims. This is maintainer self-review, not independent approval.

Offline research for [#77](https://github.com/iconidentify/omarchy-m1-video/issues/77).
The actual pinned and shipped-patched C reproduces both clients' compressed layouts and
explains their MV offsets. The proposed content observation now requires verified coherent
backing and quiescent retained references; post-DQBUF alone was insufficient.
[Driver #42](https://github.com/iconidentify/libva-v4l2_request/issues/42) remains open.
No device, module, installation or shipped patch change. Counts remain unchanged.

## Reproduce

Linux, Python, C compiler, patch and access to public pinned kernel sources:

```
python3 experiments/hevc-reference-memory/tests.py
```

The runner verifies exact source hashes, applies the 15 existing patches to a fresh private
copy, and mechanically extracts actual `calc_tile_meta`, `fill_comp`, `mv_color_size`,
V4L2 pixel-size functions/format rows, AVD format assembly and MV placement expression.
`layout-harness.c` supplies synthetic structs/macros and an explicit bounded input domain;
it is not a kernel module. No copied arithmetic is used as a stand-in for those functions.
The real extracted offset assignment is mutated before compilation; the published layout
comparison detects that change. The test also rejects source hash drift.

Twelve test groups cover all 44 selected live layout records, 8/10-bit sizing, domain/alignment,
maximum extents, overflow/undersized planes, resize/reuse extents, an actual allocator failure
sequence and repair mutation, plus malformed/range/identity/lifetime/observation-disturbance
fixtures. The original 5-test group only checked a handwritten copy and one geometry;
its conclusions were not sufficient for safe instrumentation.

The accepted PR76 campaign report was independently rerun during maintainer integration
against the pinned C oracle: 2400 frames, 44 selected windows, 1756 selected command words;
RPS_E remains 26 wrong VA frames / 25 wrong Gst frames, RPS_B exact. This is verification
of existing evidence, not a new decoder run. `layout-evidence.json` records extracted-source
identities and commands for the new no-device checks.

## Results and limits

For capture448×240, `comp_start=161280`, `comp_size=177152`,
offsets `[114688,0,176128,118784]`, `mv_size=7168`:

| Client allocation | Plane length | MV offset | Gap after compression |
| --- | ---: | ---: | ---: |
| Gst MMAP | 345600 | 338432 | 0 |
| VA imported DMABUF | 368128 | 360960 | 22528 |

The real source places MV at plane length minus MV size. Different tail placement is
**not a proved bug**. Firmware-written byte semantics, complete overwrite and padding
initialization remain unknown. See [ownership/range/lifetime table](OWNERSHIP.md) for
actual allocators, reference retention, instruction/scratch separation and same-pin DMA paths.

Two additional findings matter. The pinned exporter has no-op CPU-access synchronization
callbacks, so a cacheable exported/imported buffer needs a separate ownership solution;
the MMAP cache-hint flag alone does not provide one. An actual-function fault-injection
reproduction also proves `avd_buf_alloc` can return success with NULL storage after a failed
allocation followed by a smaller request. Neither finding has been demonstrated as the
cause of the error-free accepted RPS_E runs.

[The observation contract](next-observation.md) admits only a future verified coherent,
paused and lifetime-retained implementation, with byte/time/slot bounds and off/on pixel
checks. `observation.py` is a strict **synthetic design checker**, not a capture tool or
hardware authorization. Unknown/cacheable exported backing is an explicit blocked design
at the current pin. Parent #42 keeps actual corruption correction and full qualification.

Next bounded children: [#81](https://github.com/iconidentify/omarchy-m1-video/issues/81)
fixes the source-proven allocator retry defect in an isolated candidate;
[#82](https://github.com/iconidentify/omarchy-m1-video/issues/82) implements the coherent-only
observation contract offline before any separate guarded measurement. Neither promises an
RPS_E fix. Original Linux V4L2 source credits (Bill Dirks, Alan Cox and contributors) and
Asahi driver credits/licenses are retained in generated extraction headers.
