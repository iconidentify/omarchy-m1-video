# Next observation: actual CRA-window commands and copied controls

**AI disclosure:** Contributor design with AI maintainer remediation.

A bounded experimental recorder child of [driver #42](https://github.com/iconidentify/libva-v4l2_request/issues/42).
This file is a design, not an implemented or tested kernel change. The owner has
provided standing machine/test authorization; the eventual implementation still
requires review, supported-machine checks and guarded fault/deadline stops.
No installation, shipped patch change or reboot is part of this experiment.

## Evidence and question

Schema-2 measured the reference/motion subset in B/E pictures 24–34. E picture
28 / POC32 is CRA I (`0x2d020000`); Gst first goes wrong at picture29 / POC28
(intra collocated writer28, `0x2d00889a`, no motion address); VA first goes wrong
at picture31 / POC31 (inter writer30, `0x2d0488ca`, address emitted).
No lookup/writer/reference-word discrepancy was observed.

#67 now supplies complete ioctl-returned controls and matching encoded bytes.
The earlier statement that no tool can supply full VA controls is superseded.
Still unknown: the copied values when each kernel job is built and its actual
non-reference command sequence. Compare these at CRA and the first corrupt jobs;
do not propose another speculative permutation or already-performed PCM zeroing.

## Exact observation contract

Use new experimental hooks and a versioned parser beside the accepted schema-2
recorder. Keep accepted evidence/contracts and the shipped 15 patches intact.

| Location | Required observation | Bounds/privacy |
| --- | --- | --- |
| `avd_hevc_run_preamble`, after request setup/copies, before building the job | Numeric SPS/PPS/scaling/one-slice values actually used, plus decode flags; bind to existing context/picture/POC/target | Explicit non-padding serialization; no pointers or DPB timestamps; existing reference records retain writer identity |
| `set_header` / `hevc_set_flags` | All selected scalar non-address header words, including dimensions/transform, PCM, SPS flags, PPS flags/QP, constants and DECOMP/intra decisions | Read appended table words after successful pushes; identify kind/index; never dump an unclassified table range |
| `set_scaling_lists` or disabled branch | Full ordered sequence of selected scaling words, including marker/dimensions; explicit inactive record | Counts or first/last words alone are insufficient; coefficient/control consistency remains testable |
| `stream_slice_dqtblk` | Actual QP/deblock words with copied offset/flag inputs | Signed values and exact masks, including overlapping deblock enable/OFF1 |
| `stream_weights` | Full ordered header/weight/offset sequence, explicit skipped-I and default-header-only cases | Preserve list/index/colour identity; never infer an absent record means default zero |
| `set_slice`, `submit_slice_segment` | Size, relative coded offset, NEW_SLICE/NEW_TILE decisions, CABAC/CTB/MV location words | Coded high/low address words remain excluded; retain only relative extent and separately selected non-address flags |

Keep the existing 300 starts/completions and writer generations. Detail window is
24–34 inclusive for **both** B and E, both clients. A bound that ignores scaling
and weight arrays is invalid: preallocate a separate window store for at most
11 pictures × (1,392 bytes of four fixed control structs plus decode flags,
1,024 selected u32 command words and fixed bounded metadata). Explicit serializer
size assertions and a total recorder allocation cap of 2 MiB are required.
The existing 2,048 × 616-byte history already uses 1,261,568 bytes; include it
in the total cap. Preserve its record limit separately. Any limit hit is an
error, never truncation or implicit sampling. Reject tiles/nonzero entry points,
multiple slices/contexts, missing records and unknown kinds for this experiment.
These are proposed maxima; review implementation arithmetic before loading.

## Ownership, lifetime and failure

Preallocate only at experiment enable while idle. Copy numeric controls while
this run's request is applied and its copied slices/entry arrays remain valid.
Append selected already-written words synchronously on the building job; retain
no source pointers or references to the mutable job table. Do not allocate, hash
large buffers, log to console or retain pointers in the hot hook/IRQ path.
Bind records to the existing job/picture lifecycle and mark a failed submission
or completion invalid. Disable/read/free only after guarded idle and under the
recorder's existing synchronization. Prove disable/completion overlap and bounds
in offline tests; no new lifetime shortcut is justified by the short window.

Use root-only finite storage; normalize metadata into symbolic context, target
and writer identities. Do not publish DMA addresses, raw media, process data or
unclassified words. Select every word type explicitly at the source hook.

## Validation and distinguishing outcomes

Before hardware: exact source/build attribution, zero-fuzz patching, disabled-path
parity, sanitizer/bounds tests, complete-sequence mutation tests (including interior
scaling/weight words), missing/inactive record tests, checked source packing and
control-to-picture association. Preserve original-source licences and credits.

Then eight guarded 300-picture B/E × VA/Gst × recorder off/on runs, with actual
child exits, complete per-frame off/on comparison and the prior exact wrong sets.
Use one temporary reviewed module, finite deadlines, a fixed justified journal
boundary, foreign-client/fault stops, and restore the original module only when
healthy and idle. Preserve failed attempts; never automatically replay a fault.

1. Copied controls differ from the same-run ioctl observations: investigate request
   persistence/copy/ownership before command interpretation.
2. Actual words differ from packing the observed copied controls: investigate kernel
   construction/state. A predictor mismatch can also be a model bug; adjudicate
   against pinned C, not an assumed firmware oracle.
3. Selected words and copied inputs agree across clients but corruption persists:
   move to compressed-reference content/lifetime and DMA/cache/firmware state. This
   still leaves a wrong shared firmware contract possible.
4. Tracing changes pixels, loses records or faults: reject the experiment's causal
   interpretation, preserve evidence, fix/review tooling before any new trial.

No support count changes until a concrete correction passes the parent's complete
RPS_E repetitions, RPS_B preservation, prior full-suite pass set and fault gates.
