# Proposed discriminating kernel capture

AI-authored design for the next child of [driver #42](https://github.com/iconidentify/libva-v4l2_request/issues/42).
**Not implemented or executed.** This offline research does not authorize a kernel
edit, module operation, installation or another hardware campaign. Preserve every
shipped patch and the current long-term SPS reorder gate.

## Question and stopping decision

For the first RPS_E corruption, does the kernel use the expected earlier buffer,
expected intra/inter state and source-predicted reference commands? If any of those
first diverges, investigate that owning-layer invariant before changing ordering.
If all measured fields agree, retain that negative result and identify the next
unmeasured inputs; do not declare firmware guilty by elimination of only a subset.

A difference in raw command slots between clients is expected and is also present
in correct RPS_B. Compare commands through resolved picture identities. This is
not a proposal to replay captured command streams or to alter decode behavior.

## Minimal hooks and record contract

Start from the pinned kernel plus all 15 existing patches, with hashes/build commands
recorded. Prepare instrumentation as a separate experimental change for review;
never silently replace shipped patches. The [source map](source-map.json) identifies
the exact functions and revision. Prefer bounded trace events or a bounded per-context
recorder, disabled by default, with explicit lost-record/overflow detection. Avoid
unbounded printk and full firmware-buffer dumps.

Select one capture context by an explicit run identifier. Record sequence numbers
and start/end extent; filter command details to decode pictures 24–34, while retaining
writer/completion history for all 300 pictures. Other clients' contexts must not
enter the artifact. No trace field should change the submitted controls.

1. **After `avd_hevc_run_preamble()` and `update_dec_buf_info()`**: request ordinal,
   selected destination buffer, timestamp identity, copied-timestamp validity,
   expected/previous writer generation, decode POC, actual first-slice POC/type,
   number of slices and destination `hevc.is_intra`. Snapshot applicable request
   values only after the existing setup/copy path. Record actual completion/error
   state so a metadata write before a failed job is never mistaken for decoded data.
2. **At each `stream_refs()` lookup**, after `avd_get_ref_buf()` resolves the entry:
   submitted slot/POC/long-term flag and timestamp identity; actual returned buffer,
   match/fallback indication, copied-timestamp validity and returned `is_intra`;
   emitted `hdr_d0_ref_hdr` word. Observe the fallback decision inside the helper
   or return an observational flag in the experimental hook; do not infer a miss
   solely from returned index. Preserve the same return behavior.
3. **At `stream_slice_dqtblk()` list emissions**: list, position, submitted slot and
   actual `AVD_OP_REF` word. Correlate every slot with the measured table entry;
   distinguish list/table words from compressed-buffer address words.
4. **At `stream_slice_mv()`**: raw flags, merge-candidate count, both raw reference
   counts, collocated list/index, `is_first`, selected slot, actual lookup buffer
   and `is_intra`, computed `ref_valid`, complete `slc_a8c_cmd_ref_type` word and
   whether the motion-address command was emitted. Preserve the I early-return
   branch and the non-I lookup that precedes the TMVP gate.
5. **Address/layout facts**, attached to the preceding records: opaque allocation
   identity plus relative compressed offsets, plane length, negotiated dimensions
   and relative motion-tail offset; whether each range lies inside its intended
   allocation. Equality of buffer indices does not prove equality of allocation
   lifetime or physical contents. Do not publish DMA/kernel pointers or unrelated
   memory; retain necessary raw timestamp mapping privately and normalize it to
   request/writer identities for publication.

Use an explicit bound for this one-slice/300-picture experiment: at most 600
start/completion records plus 11 × (16 table entries +32 list entries +1 motion
record) = **1,139 records**, with needed layout/control fields carried inside those
records. A capacity of 2,048 records leaves room for fixed run markers; any extra
slice/context/extent, overflow or missing record invalidates the artifact rather
than truncating it. The implementation must document actual record size, allocation
bound and error behavior; this arithmetic is a design bound, not measured overhead.
Do not trace media payload or register firmware addresses wholesale.

## Concrete expected observations

| Check | Expected from public metadata | Discriminating result |
| --- | --- | --- |
| E picture 28 / POC32 | I-picture; VA target13, Gst11; metadata becomes intra; reference table skipped | Different actual writer/type/history points to control or buffer-state handling |
| E picture 29 / POC28 lookup | Collocated POC32; VA slot 11 -> buffer 13, Gst slot 13 -> buffer 11 | Miss/fallback, wrong returned writer, or wrong `is_intra` isolates an observable kernel-state discrepancy |
| Same picture motion gate | False if the expected intra writer was found; no motion-address emission | True/address present contradicts that source-state prediction; first check measured controls and returned state |
| Same picture motion command | `(word & 0xffffff91) == 0x2d008890` under the expected lookup | A mismatch identifies a known-field discrepancy; matching masked bits still leaves merge/CABAC/MVD inputs to compare |
| VA E picture 31 / POC31 | Collocated POC30 inter, buffer 16; dependent-segment flag decides gate | Compare measured flag, full word and layout; do not assume an enabled gate |
| B control window | Correct pixels despite different table/list ordering | A benign permutation is not classified as the corruption cause |

The normalized trace lacks slice POC. Verify it against decode POC before using
any conditional header value as an oracle. Compare count, long-term bit and POC
delta independently; preserve the source's 17-bit encoding for negative deltas.
Check copied-timestamp validity explicitly: the pinned vb2 lookup will not match an
unused timestamp-zero buffer unless that validity flag is set.

## Later execution and acceptance gate

Before hardware, the instrumentation implementation needs review, source/build
identity and offline tests for enable/filter/overflow/normalization behavior.
The owner must separately approve the experimental kernel/module scope under root
AGENTS.md, save work before unloading and provide a fresh exclusive decoder window.
The prior capture's one-reload authorization is consumed. Installation and boot
changes are separate choices, not part of this design.

When authorized, use the portable guard and shared OS lock, a fixed justified
journal boundary, finite 90-second maximum per short run and durable logs. Stop
at a new fault, foreign decoder client, wedge, timeout or trace overflow; no
automatic retry or recovery. Keep the actual child status and all 300 output hashes.
Run both clients on RPS_B and RPS_E with tracing disabled/enabled on the same
instrumented build. Require unchanged exact pixels, complete trace extent,
no unrelated context, no lost records and final idle states. Preserve failures
separately. This short campaign does not replace parent full-suite/concurrency gates.

Publish a metadata-only decision with exact source/module provenance and limitations:
which lookup/word/state differed first, or which tested hypotheses are unsupported.
A kernel-state failure can justify a scoped correction with a before/after regression.
Matching observations call for the next targeted control/compressed-state experiment,
not a speculative reorder or a support claim. Parent #42 closes only after the actual
fix and its original qualification criteria are met.
