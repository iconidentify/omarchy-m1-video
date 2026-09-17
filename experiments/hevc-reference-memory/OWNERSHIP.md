# HEVC memory ownership and byte ranges

**AI disclosure:** Original audit by z23; maintainer AI review corrected allocator,
DMA ownership and observation conclusions. No device was opened for this audit.

All source links below use kernel `94fb23346d522edf53722357c426a3e58030beea`.
`source.py` verifies every file in `source-map.json`, then applies all 15 **existing**
patches (concatenated SHA256 `029f57377a00f3584678f80a8011d8ba7a17c83f1708d9a429d3c91dbb2d0390`)
to a fresh private source copy. No shipped file is edited. This distinction matters:
patch0003 changes the CPU job table to `kvcalloc`; later patches change job completion.
The kernel source, applied patches and extracted-function hashes identify the tested code.

## Capture allocation and ranges

[AVD format construction](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-v4l2.c#L77-L87)
first obtains the decoded pixel size from
[`v4l2_fill_pixfmt_mp`](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/v4l2-core/v4l2-common.c#L452-L487),
appends [`fill_comp`](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-drv.c#L26-L71)
and then [`mv_color_size`](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-hevc.c#L47-L51).
Queue setup and buffer preparation reject planes smaller than required `sizeimage`
([source](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-v4l2.c#L772-L831)).
Larger imported planes are allowed; MV is placed at **actual plane length minus MV size**.

RPS_B/E capture geometry is 448×240, 8-bit 4:2:0 (coded width 416). All 44 selected
picture records, decode24–34 in each paired client/vector history, match the extracted C.
Half-open byte ranges in one capture plane:

| Region | Gst MMAP range | VA imported DMABUF range | Address/role |
| --- | --- | --- | --- |
| Decoded NV12 pixels | `[0,161280)` | same | Visible linear output; RPS_E mismatches measured here |
| Compressed luma payload | `[161280,275968)` | same | `comp_start + offsets[1]` |
| Compressed luma metadata | `[275968,280064)` | same | `comp_start + offsets[0]` |
| Compressed chroma payload | `[280064,337408)` | same | `comp_start + offsets[3]` |
| Compressed chroma metadata | `[337408,338432)` | same | `comp_start + offsets[2]` |
| Extra allocation gap | empty | `[338432,360960)` | 22528 bytes; no role assigned by this audit |
| Motion-vector region | `[338432,345600)` | `[360960,368128)` | `plane_length - 7168` |

The four compressed ranges and MV do not overlap for these inputs. This does not prove
all bytes are initialized or semantically defined. Firmware-written payload, metadata,
MV padding and overwrite extents remain unknown. AVD has no per-picture clear of these
capture tails; allocator initialization is not a guarantee of complete firmware writes
on reuse. Hash differences may include undefined bytes.

## Allocation, ownership and lifetime

| Storage | Allocation/initialization | CPU/device access and lifetime |
| --- | --- | --- |
| Pixel, compressed and MV capture regions | One vb2 plane, MMAP allocation or DMABUF import; AVD records geometry and firmware writes data. No AVD per-picture tail zeroing | CAPTURE queue is explicitly `bidirectional`, so vb2 selects `DMA_BIDIRECTIONAL`. Firmware may read completed pictures as references. CPU access is governed by the mapping/exporter contract below, not merely DQBUF |
| Source bitstream | OUTPUT vb2 plane, client fills encoded data | `DMA_TO_DEVICE`; controls/request apply before AVD submission. Separate from capture tails |
| CPU instruction-segment table | Shipped patch0003 uses `kvcalloc`; zero-initialized CPU table, freed by `kvfree` after submission (and cleaned on abandoned job paths) | `avd_submit_job` sends words with `writel`; the segment table itself is **not** device DMA memory |
| `ctx->inst` instruction FIFO | `avd_buf_alloc` → `dma_alloc_coherent`, allocated at open, freed on release/error | Kernel CPU mapping plus DMA address passed to SoC `configure_stream`; firmware use is not inferred from the CPU segment table. Coherent API still needs device command ordering |
| HEVC `bufs.inst` / `pipe_state` | Coherent allocations at codec start; freed at stop | `pipe_state` address is emitted by `set_header`. In the inspected HEVC source, `bufs.inst` has allocation/free references only; do not invent a firmware consumer |
| HEVC scratch (`ip_above`, `mv_above_info`, `lf_above`, `lf_above_info`, tile-only `lf_left`, `lf_left_info`, `sw_left`, plus `az_above`) | Size calculations in `avd_hevc_alloc_scratch`, called per run; all use `avd_buf_alloc`, freed at stop | Addresses emitted by header/reference code; exact firmware read/write contents remain unknown. The helper currently frees a live allocation on each call rather than retaining it on size decrease; a failed-then-smaller retry has a separate bug below |

Source: [queue directions and open/release](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-drv.c#L303-L398),
[coherent allocator](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-drv.c#L73-L94),
[CPU instruction submission](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-drv.c#L133-L190),
[HEVC allocation/scratch/stop](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-hevc.c#L1022-L1248),
[SoC instruction FIFO programming](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-hw.c#L77-L125),
and [shipped patch0003](../../patches/0003-media-apple-avd-allocate-the-job-segment-table-with-.patch).
The exact patch pathname is in the source manifest; upstream line links describe the base,
while extraction/testing uses the full applied stack.

## Reference retention and completion

[`avd_get_ref_buf`](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-drv.c#L96-L116)
looks up a capture buffer by timestamp in the current queue; a miss falls back to the
current destination. [HEVC reference emission](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-hevc.c#L101-L149)
uses that allocation plus its stored compression layout. The colocated MV reference
uses a referenced plane's length minus computed MV size. Retention of the client surface
and correct writer generation remain necessary even after its decode completed.

AVD completion travels through the IRQ/job completion path into
[`avd_job_finish_no_pm`](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-v4l2.c#L926-L945)
and vb2 buffer completion; shipped lifetime patches guard pending/early completion.
DQBUF reports completion of that buffer's write. It does **not** prove that no subsequently
queued job is reading it as a reference. A new writer must also change the generation
identity; a reused allocation index or POC alone cannot identify its contents.

## DMA synchronization belongs to specific paths

[AVD patch0001](../../patches/0001-media-apple-avd-allow-cacheable-non-coherent-MMAP-bu.patch)
enables standard cache hints. The same-pin implementations establish:

- [vb2 direction selection](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/common/videobuf2/videobuf2-core.c#L2659-L2662)
  uses bidirectional for AVD capture. [Cache-hint initialization](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/common/videobuf2/videobuf2-core.c#L408-L428)
  deliberately skips prepare/finish cache synchronization for imported DMABUFs, assigning
  responsibility to the exporter.
- [vb2-dma-contig allocation/mapping](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/common/videobuf2/videobuf2-dma-contig.c#L174-L289)
  selects coherent or noncoherent allocation/mapping from the queue policy. For noncoherent
  **MMAP** buffers, [prepare/finish](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/common/videobuf2/videobuf2-dma-contig.c#L123-L165)
  perform cache maintenance; the “no dma_sync in AVD” observation never implied no sync.
- Exported vb2-dma-contig [attachment map](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/common/videobuf2/videobuf2-dma-contig.c#L382-L413)
  uses `DMA_ATTR_SKIP_CPU_SYNC`; its [begin/end CPU-access callbacks](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/common/videobuf2/videobuf2-dma-contig.c#L427-L439)
  return zero without cache operations at this pin. An added sync ioctl alone cannot
  repair those no-op callbacks. A standalone cached MMAP allocation exported and then
  imported into another queue cannot borrow the original queue's unused prepare/finish.
- [DMA-BUF API documentation](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/Documentation/driver-api/dma-buf.rst)
  and [coherent/streaming DMA contract](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/Documentation/core-api/dma-api.rst)
  govern CPU access and ownership. Mapping permission, cache visibility and absence of
  in-flight readers are three different requirements.

Consequently the first content observer must require verified coherent/noncached backing,
source/allocation identity and paused submissions with no in-flight readers. Unknown or
cacheable exported backing is **blocked** at this pin pending its own synchronization fix.
This also informs [driver PR92](https://github.com/iconidentify/libva-v4l2_request/pull/92);
it is not evidence that the accepted coherent RPS_E captures suffered that regression.

## Proven helper defect versus HEVC hypotheses

An actual-function fault-injection test finds a bounded allocator bug: `avd_buf_alloc`
stores size4096 when `dma_alloc_coherent` fails. A retry with size2048 then takes
`if (!buf->cpu && size < buf->size) return 0`, reporting success with NULL storage and
without invoking the allocator. The test mechanically extracts both allocator/free
functions from the applied source. Changing that condition to require a live allocation
makes the blocking assertion fail. This is an offline helper defect; no kernel mutation
or hardware failure was induced. The accepted RPS_E runs had no allocation errors, so
this is **not an explanation of their deterministic corruption**.

Other hypotheses remain unproved: stale compressed bytes on reuse, an unobserved command,
wrong synchronization owner, read before a completed writer, or firmware state. The 44
selected layouts do not overlap, and existing same-run traces associate selected references
with completed writers. Those facts do not prove the semantics of every firmware-read byte.
