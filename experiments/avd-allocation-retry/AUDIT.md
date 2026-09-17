# `avd_buf_alloc()` caller audit

Mechanically derived from the pinned, hash-verified, shipped-patched sources at
`94fb23346d522edf53722357c426a3e58030beea`. `tests.py` re-derives the counts in
[`caller-audit.json`](caller-audit.json) and fails if they drift.

47 call sites: `avd-av1.c` 15, `avd-vp9.c` 12, `avd-hevc.c` 11, `avd-h264.c` 8,
`avd-drv.c` 1.

## What the pinned function actually does

```c
if (!buf->cpu && size < buf->size)
	return 0;
```

The fast path is entered only when there is **no** allocation. Two consequences,
both reproduced against the extracted function in `harness.c`:

1. **Reuse never happens.** With a live buffer, `!buf->cpu` is false, so every
   repeat call falls through to `avd_buf_free()` plus a fresh
   `dma_alloc_coherent()`. No caller has ever received a reused buffer.
2. **A failure can be reported as success.** `buf->size` is assigned before the
   allocation is attempted, so a failed request leaves `size` set and `cpu`
   NULL. A following smaller request then satisfies the fast path and returns 0
   with no storage. A caller trusting that result can consume NULL storage or an invalid DMA address;
   the actual hardware consequence has not been measured.

## Which callers can reach the failing sequence

A first-failure-then-smaller-retry needs a call site that runs again with a
smaller size on the same `struct avd_buf`. The per-frame scratch paths do:

| Path | Cadence | Size source |
| --- | --- | --- |
| `avd_hevc_alloc_scratch()` | every run, from `avd_hevc_run()` | coded width/height |
| `avd_vp9_alloc_bufs()` | context start, and per resolution | coded width/height |
| `avd_h264_alloc_bufs()` | context start | macroblock count |
| `avd_h264_decode_run()` slice | every slice | `payload_len` |

A stream that shrinks its coded size after an allocation failure — a resolution
change under memory pressure — is the reachable case. The fixed-size buffers
(`inst`, `pipe_state` at `0x200`) cannot shrink and are not reachable this way.

The per-slice call at `avd-h264.c:749` takes a fresh `slices[slice_num]` slot
each time, so it always starts from a zeroed descriptor and is not exposed.

## Why the candidate does not enable reuse

`alternative-reuse.patch` restores what the guard evidently intended
(`buf->cpu && size <= buf->size`). It fixes the same defect and is tested here,
but it is **not** the candidate, because it is not behaviour preserving:

- No caller has ever been handed a reused buffer, so no caller has been shown to
  initialize one. `harness.c` poisons every allocation with `0xA5` rather than
  zeroing it, precisely so this assumption is not made silently.
- The pinned `Documentation/core-api/dma-api.rst` does not state that
  `dma_alloc_coherent()` returns zeroed memory, so "it was zeroed before" cannot
  be established from the pinned sources either way.
- Establishing that every byte the firmware reads is written before submission
  needs the firmware contract, which is not available offline.

Reuse is the better allocator. It should land only with that caller evidence,
and it is kept here as a separate patch so it can be evaluated on its own.

## Second defect: partially allocated scratch is leaked

`avd_{hevc,h264,vp9}_start()` allocate the private context, call
`avd_*_alloc_bufs()`, and on failure run:

```c
err_free_ctx:
	kfree(hevc_ctx);
	ctx->priv = NULL;
	return ret;
```

`avd_hevc_alloc_bufs()` takes `inst` (`fifo_size()`) and then `pipe_state`
(`0x200`). If the second call fails, the first buffer is already mapped, the
context is freed, `ctx->priv` is cleared, and `avd_hevc_stop()` — which frees
every buffer — returns early on `!hevc_ctx` and is never reached anyway. The
coherent mapping is leaked for the lifetime of the module. The same shape is in
all three codecs.

`candidate.patch` routes the error path through each codec's existing `stop()`,
which already frees every buffer its `alloc_bufs()` can take (verified as a set
comparison over the extracted text) and does the `kfree()` itself.
`avd_vp9_stop()` gains the `!vp9_ctx` guard `avd_hevc_stop()` and
`avd_h264_stop()` already have.

`avd-av1.c` is not touched: its start path is not part of this ticket and is not
covered by these tests.

## Not established here

- Whether either failure has ever been observed on hardware. Both are reached
  only under allocation failure, which this experiment injects.
- Whether the firmware tolerates a zero DMA address, or faults.
- Any claim about AV1.


## Maintainer runtime follow-up

The original set/text audit is supplemented by `lifecycle.py`: actual start,
alloc_bufs and stop bodies execute at every failure index with tracked mock DMA.
Baseline and reverted-cleanup mutants leak; the candidate unwinds to zero live
allocations. Full module build evidence is in `build-evidence.json`. The scratch
firmware overwrite contract and AV1 lifecycle are still outside this acceptance.
