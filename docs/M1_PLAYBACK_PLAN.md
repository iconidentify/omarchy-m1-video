# First C1 comparison: existing decode/seek/reopen workload

AI-assisted maintainer plan, 2026-09-20; refs driver #45 and companion #27.
The owner approved the M1 delivery reset. This run uses selected userspace
drivers and the ordinary installed kernel; it performs no installation, module
operation, suspend or reboot. Source base is recorded in [M1_DELIVERY.md](M1_DELIVERY.md).

## Question and bounded matrix

Does C1 preserve the installed driver's decoded output and cleanup across the
existing repeated decode/drain/seek-to-start/reopen workload?

Reuse driver `tests/resource-campaign.py` and `tests/resource-workload.c` at
`5b5046cbda6892f4a63df0015857a80bd42c17cf`. These already exercise the real FFmpeg
seek/flush and VA paths. Do not add another decoder or observer framework.

Prepare their four 24-frame, 640x360 synthetic clips and independent software
frame references: H.264 with delayed frames, HEVC, VP9 8-bit and VP9 10-bit.
Bind the generated files, helper binaries and references by SHA-256.

Run baseline normal, baseline early-export, C1 normal and C1 early-export,
sequentially. Each successful row requires 400 measured cycles plus 20 warmups:
100 measured cycles per codec. Every lifecycle decodes/drains, seeks/flushes,
decodes again, closes the decoder and checks its retained image. One VA display
survives the row. Expected per row: 20,160 compared frames and 420 retained-image
checks, including warmup; no count is reported until the row completes.

Use the prior accepted limits: zero FD/dma-buf/mapping-count growth, at most
4 MiB mapped/RSS growth, at most 64 KiB allocator-accounted growth, and an
allocator explanation for any mapped-byte increase. A fresh software preparation
run checks harness operation; it is not hardware evidence.

## Execution and stop boundary

Before each row, use the actual `tests/hwguard.py`, require an idle decoder and
fault-free whole-current-boot journal, and record boot/module identity. Its
exclusive host lock is mandatory. The guard deadline is 300 seconds per row;
the inner runner also has progress and cleanup deadlines. Each row has a fresh
output path. No other build or decoder campaign runs alongside it.

Select `/usr/lib/dri` for the installed row and C1's separate build `src`
directory for the candidate. Record the exact driver hash and source identity.
Keep all four rows on the same installed kernel/client stack.

Stop the matrix on the first mismatch, resource failure, foreign client, timeout
or kernel fault. Preserve partial rows. Do not unload/reload the module, retry a
wedged decoder, advance the journal boundary or relax limits. A failed baseline
is itself a result, not permission to proceed with later hardware rows.

## Result and limits

Publish the actual per-row disposition, exact source/artifact/input identities,
full counters, guard outcome and raw-evidence index. Compare the raw ordered
frame/RESULT/retained-image records with the pinned software references; a
summary pass flag is insufficient. Every pass ends idle with no abandoned worker.

This only qualifies small fixed-layout clips, seek-to-start, drain/reopen and
the existing early-export simulation. It does not establish random seeking,
adaptive resolution, a browser GPU importer, actual displayed pixels, failed
transition isolation, suspend, boot stability, performance or complete #45.
The next visible-client row uses a disposable mpv configuration on OpenGL with
hardware-selection logs and software-rendered comparison frames, followed by a
normal-sandbox Chrome test profile. Those results must remain separate.
