# HEVC copied controls and actual command recorder

**Runtime correction (2026-09-17):** The original #70 module in `offline-build.json` is withdrawn: generated initialization prematurely removed the reference recorder and unload Oopsed before any decoder ran. See the [failed attempt](../hevc-avd-command-capture/failed-attempt-2026-09-17/README.md). The generator is corrected and its actual init/exit bodies plus the original-defect mutation are tested; [corrected build](corrected-build.json) records its original offline preparation. The later [recovered campaign](../hevc-avd-command-capture/capture-2026-09-17/README.md) successfully probed its lifecycle, completed all eight captures, and restored the original module with no new faults. This supplies measurement evidence, not an HEVC correction.

**AI disclosure:** Contributor implementation with AI maintainer review and remediation.

Default-off, isolated tooling for [#70](https://github.com/iconidentify/omarchy-m1-video/issues/70).
It records the numeric controls actually copied for each job and all explicitly
selected non-address command words in pictures 24–34. A same-run, complete
300-picture reference/writer history is mandatory. The measured eight-run
[campaign #71](https://github.com/iconidentify/omarchy-m1-video/issues/71) and
[actual corruption correction](https://github.com/iconidentify/libva-v4l2_request/issues/42)
remain separate. No new hardware result or codec-count increase is claimed.

## Offline reproduction

```sh
python3 experiments/hevc-avd-command-trace/tests.py
python3 experiments/hevc-avd-trace/fetch.py /tmp/avd-pristine
python3 experiments/hevc-avd-command-trace/source-tests.py /tmp/avd-pristine
python3 experiments/hevc-avd-command-trace/prepare.py \
  --source /tmp/avd-pristine --destination /tmp/avd-cmdtrace
python3 experiments/hevc-avd-command-trace/oracle.py prepare \
  --source /tmp/avd-pristine --candidate /tmp/avd-cmdtrace --output /tmp/avd-oracle
```

All output directories must be fresh. Python, patch and a Linux C compiler with
ASan/UBSan are required; fetching uses pinned public sources. No device, private
corpus, sudo, installation or module operation is involved. An optional matching
ARM64 build adds `--headers /path/to/matching/headers` to `prepare.py`. Preparation
finishes all hooks/storage adaptations before compiling and hashes final sources,
headers, compiler/log and module; exact recorder symbols must exist in the module.
This issue does not authorize module load.

## What is checked

`packing.py` inserts a braced hook after each explicitly classified `push` in the
hash-locked source. It records full scaling and weight interiors, header scalars
and constants, strides, QP/deblock, CABAC/CTB/MV locations and full relative coded
extents. Address pushes and reference commands remain outside this recorder.
`kernel/control-layout.inc` names every serialized field; native reserved bytes,
padding, pointers, DMA bases and DPB timestamps are excluded.

`oracle.py` compiles the **actual pinned C function bodies**, including
`stream_slices`, with bounded host command collectors and explicit address/reference
stubs. It reconstructs the complete selected sequence from the copied controls
and recorded device context. This is source consistency, not an independent
firmware specification. It cannot establish decoder correctness by itself.

The source checks exercise 32 synthetic cases, a full 11-window snapshot and
actual-source mutations that drop interior scaling/weights, change a decode push,
omit skipped-I state or truncate an extent. They also round-trip the real kernel
serializer with poisoned native reserved bytes. Original Asahi/eiln source notices
are retained in generated extracts; fixtures are authored synthetic values.

`parser.py` rejects wrong run/context/state, sticky errors, incomplete or duplicate
histories/windows, unknown sites/flags, missing inputs, invalid extents, nonzero
wire padding and control/job mismatches. Its reader does not accept old command
schema 1. Complete verification requires the source oracle and the accepted
reference reader/validator:

```sh
python3 experiments/hevc-avd-command-trace/oracle.py check \
  --build /tmp/avd-oracle/compiled --run RUN \
  --snapshot /private/command.snapshot --reference-snapshot /private/reference.snapshot
```

The reference capture must have the same run/context and all 300 starts/completions
and writer generations. Word equality never substitutes for pixel hashes, same-run
ioctl/control association or private corpus attribution. Keep raw evidence private.

## Storage and lifetime

The accepted reference source/captures stay untouched. `bounded.py` applies an
explicit storage-only adaptation to its **private candidate copy** and the new
command recorder. The reference wire rows remain schema 2. Each reader pins one
sealed immutable capture under its control mutex; `off`/`arm` cannot free or
replace it while open. Fresh `arm` requires `off` first. Failed allocation/open
leaves the prior state intact. Records render one bounded `seq_file` row at a
time; there is no full snapshot copy or transient replacement capture.

The two capture structs total **1,352,472 bytes** (reference 1,261,648, including
its 80-byte header; command 90,824). A 131,072-byte reserve for allocation rounding,
reader buffers/bookkeeping and recorder stack leaves the compile-time bound at
**1,483,544 bytes**, below the **2 MiB** cap. The largest possible command text row
is under 16 KiB; the reference row is under 2 KiB. A reader buffer needs at most
32 KiB including a growth step. Normal VFS file descriptors are not capture data.
Only one snapshot reader per recorder is admitted.

The exact prepared control/snapshot wrapper functions run under pthread mutexes
with ASan/UBSan and bounded host seq stubs. Tests cover reader/replacement overlap,
allocation and reader-open failures, default-off hooks, 300 start/done calls,
foreign codec binding, completion/disable overlap and no hot-hook allocation.
This exercises the lifetime contract; Linux IRQ/runtime behavior still needs the
separate guarded campaign. See [SCHEMA.md](SCHEMA.md), [CAPTURE.md](CAPTURE.md) and
[REVIEW.md](REVIEW.md) for the remaining gates and rejected-head findings.
