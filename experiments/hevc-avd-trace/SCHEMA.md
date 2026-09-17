# Recorder schema 2

Private text snapshot; ASCII unsigned decimal u64 values separated by whitespace.
The parser bounds input at 4 MiB, rejects noncanonical/overflowing numbers and
requires exact field counts, sequence, context, run and record extent.

Header:

```text
H version run context phase errors count attempted pictures completions capacity first last record_size
```

Require version 2, phase 4 (sealed), errors 0, count = attempted = record count,
pictures = completions = 300, capacity 2048, first 24, last 34, record_size 616.
Kinds: 1 start, 2 completion, 3 reference table, 4 reference list, 5 motion.
Record envelope followed by exactly 72 payload integers:

```text
R run context sequence kind picture v0 ... v71
```

Sequence starts at 1. Pictures start at 1. Command records are allowed only in
24–34, strictly between that picture's start and completion. Every reserved
payload field must be zero. An I picture has no table/list and one motion record;
an inter picture has every active DPB table slot, every emitted L0/L1 list word
and one motion record, in actual emission order.

## Shared buffer payload: 18 consecutive values

| Offset | Field |
| --- | --- |
| 0–6 | vb2 index, raw timestamp, copied_timestamp, is_intra, writer picture, writer completed, opaque allocation ID |
| 7–9 | plane-0 length, compressed start offset, compressed size |
| 10–13 | compressed offsets 0–3 |
| 14–17 | motion-tail size, motion-tail relative offset, computed range-valid flag, vb2 memory type |

The writer is updated at picture start; completion is initially false and becomes
true only on successful job completion. The allocation ID is assigned at buf_init,
reset at cleanup, and changes on replacement. A prior writer remains distinct
from an allocation lifetime. A failed/absent writer may be observed, never inferred
as successful. Range-valid means compressed offsets are inside the compressed
allocation and compressed end does not cross the motion tail. It is not a firmware
content check. Memory types in this experiment are MMAP=1 or DMABUF=4.

## Kind payloads

| Kind | Fields in order |
| --- | --- |
| Start | previous writer, decode POC, actual slice POC, slice type, num_slices, entry control array capacity (`ep->elems`), active DPB count, negotiated width, height; buffer payload at 9; first slice used entry count (`sl->num_entry_point_offsets`) at 27 |
| Completion | actual vb2 result (DONE=5 required); buffer payload at 1 |
| Table | submitted slot, DPB POC, DPB flags, requested timestamp, actual appended header word, lookup matched flag; returned buffer payload at 6; four actual emitted compressed-address relative offsets at 24 |
| List | list number, position, submitted slot, actual appended reference-list word |
| Motion | raw slice flags, slice type, five_minus_max_num_merge_cand, raw L0-minus-one, raw L1-minus-one, collocated index, is_first, selected slot, requested timestamp, lookup attempted, matched, ref_valid, actual appended motion word, address emitted; returned buffer payload at 14; all 16 raw L0 bytes at 32 and L1 bytes at 48; actual emitted motion-address relative offset at 64; variant quirks at 65 |

Signed POCs are encoded as u32 inside a u64 and decoded as signed 32-bit values.
Types are kernel B=0, P=1, I=2. I lookup fields, returned buffer payload and emitted
address are zero because the source returns before lookup; inactive controls can
still be recorded and are not treated as inputs to the I command. Non-I lookup
is required even when TMVP is false; the complete raw reference arrays preserve
otherwise inactive collocated selection bytes. Slots outside the active table
are outside this experiment's checker domain and are rejected explicitly.

Actual address operands are reconstructed from words already appended to the
instruction segment, accounting for AVD_QUIRK_LSR, then reduced relative to the
returned buffer's plane-0 DMA base. The base and absolute command addresses never
leave the recorder. Out-of-allocation results are U64_MAX. This confirms emitted
relative operands; it does not inspect compressed bytes or validate firmware reads.

Status file:

```text
S 1 run context phase errors count attempted pictures completions open_contexts
```

Phases: 0 off, 1 armed, 2 active, 3 drained, 4 sealed. No recorder is represented
by zero fields plus the current open-context count. Errors are sticky bits:
foreign opener/decoder 1, overflow 2, extent 4, ordering 8, failed job 16,
unsupported slice/entry shape 32 (slice count other than one, nonzero used
entry points, or entry array capacity outside the pinned 1–256 domain). A status read contains no other-context metadata.
The supervisor stops on nonzero errors; it cannot recover a wedge.

The normalized JSON replaces both timestamp fields with their matching logical
writer picture or null. It preserves reported facts and discrepancy codes. It
contains no raw timestamps, DMA addresses, pointers, bitstream, image payload or
other-context records. Raw snapshot and trace association inputs remain private.

Schema 1 did not record the slice's used entry count and incorrectly required
zero control array elements. Schema 2 preserves the array extent at start payload
5 and adds used entries at 27, formerly reserved. The checker rejects schema 1;
it never treats that reserved zero as an observed used count or upgrades an old
capture. One-element unused storage is valid. Any used entry point still rejects
this single-segment experiment. Record size/capacity and status schema 1 are unchanged.
Normalized JSON uses `hevc-avd-trace.normalized/2`, with `entry_capacity` and
`slice_entries` as distinct required fields.
