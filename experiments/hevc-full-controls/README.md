# Paired HEVC control inputs and kernel-returned values

The two clients submit **identical compressed bytes for all 300 pictures of both
RPS_B and RPS_E**. Their observed decode/start-code modes agree. The returned
non-reference controls differ only in three field families whose differences are
unused in these source paths. The apparent VA PCM underflow is corrected by the
kernel before decode: actual ioctl returns contain zeroes. A PCM-zeroing experiment
would repeat behavior already present, so it is not justified by these captures.

Eight guarded M1 workloads completed on the unchanged original installed module,
300 frames each, all actual decoder exits and outer guards successful, final idle
and no new fault. Every frame equals the prior accepted output and its tracer-off
counterpart. RPS_B is exact; RPS_E remains wrong on **26 VA / 25 GStreamer outputs**.
No corruption fix, codec-count increase or general firmware-contract proof follows.

This is companion [#67](https://github.com/iconidentify/omarchy-m1-video/issues/67),
under [driver #42](https://github.com/iconidentify/libva-v4l2_request/issues/42).
The [generated decision](capture/summary.json), [campaign report](capture/README.md)
and [review](REVIEW.md) describe evidence and limits. Contributor-owned #66 supplies
the separate source-consumption/command map; its files are unchanged here.

## Reproduce without hardware

```sh
python3 experiments/hevc-full-controls/verify-sources.py
python3 experiments/hevc-full-controls/tests.py
python3 experiments/hevc-full-controls/report.py --verify
python3 experiments/hevc-full-controls/report-tests.py
```

Python and a Linux C compiler are sufficient. Source verification downloads only
hash-locked primary files to a temporary directory; `--source-dir DIR` can use a
cache and rejects changed content. It checks the complete serialized UAPI field
inventory, actual C sizes and the one scoped lifecycle-checker change. Public
report reproduction does not need the device, raw traces, private paths or media.

To normalize a privately held supported trace into a new metadata file:

```sh
python3 experiments/hevc-full-controls/normalize.py private/trace.json \
  --expected-pictures 300 --output new-metadata.json
```

Do not publish the input. The pinned tracer records compressed bytes, pointers,
paths and FDs. The normalizer emits only schema-selected controls, writer ordinals,
encoded-input digests and symbolic mode observations. An independently verified
actual child status, output hashes and same-run log association remain required
for a hardware campaign decision; parsing a trace alone does not supply them.

## Narrow supported contract

- Pinned v4l2-tracer 1.32.0 with `-u`, one HEVC context, one complete slice/request,
  zero used entry points, one capture plane, no seek/flush/reconfiguration. Unknown
  fields/flags, truncated arrays, duplicate JSON keys and invalid scalar types fail.
- All non-padding SPS/PPS/decode/scaling/slice fields serialized by the pinned
  tracer are retained. Weight and scaling arrays are flattened in C row-major order.
  Reserved padding is omitted by the tracer and cannot be validated here. Extended
  SPS-RPS controls and nonzero/multi-slice dynamic extents are outside this contract.
- Every request explicitly supplies PPS, decode, scaling and slice controls. The
  first request must also supply SPS; later absent SPS is linked to the last explicit
  **returned** SPS by `sps_from_picture`. Negotiation/current-value SPS cannot stand
  in for a missing first request. This persistence follows pinned request setup;
  it is not a copied-kernel-control snapshot at the job hook.
- `controls` contains validated successful ioctl-return payloads. `input_changes`
  retains every differing submitted field/value. Together with `submitted`, these
  distinguish actual per-request arguments, observed kernel adjustments and the
  explicitly derived SPS carry. No missing field is filled from a codec default.
- The tracer's DPB-bit-0 PPS spelling is translated into
  `V4L2_HEVC_DPB_ENTRY_LONG_TERM_REFERENCE`. Active raw timestamps become logical
  writer ordinals; inactive DPB timestamps are deliberately omitted (`null`).
  Other inactive numeric fields/arrays remain available for inspection.
- VA legitimately reuses timestamps by capture buffer. Resolution considers latest
  observed buffer writers and queued pictures awaiting userspace dequeue, rejecting
  ambiguous/future/retired/destination references. Gst may queue a reference before
  its CAPTURE DQBUF is logged; later complete lifecycle/target validation is still
  mandatory. A queued identity does not claim userspace already dequeued it.
- [lifecycle.py](lifecycle.py) copies the accepted reference adapter at `3cdf66b`
  with one audited change: a successful OUTPUT STREAMOFF may return final source
  buffers after **all** expected CAPTURE completions. VA logs 299 OUTPUT DQBUFs and
  300 CAPTURE DQBUFs before clean streamoff. No synthetic DQBUF is inserted and no
  missing capture is excused. Original adapter behavior stays unchanged.
- Encoded-input hashes bind each pre-QBUF memory dump to the selected context,
  buffer index, plane extent and zero data offset. Exported buffer FDs must have
  been bound by that context's EXPBUF. Only the bytes' length and SHA-256 are public.
  These hashes are not an observation of later DMA reads or firmware consumption.

## Decision and next experiment

The apparent PCM difference disappears in the observed ioctl returns. The kernel
also clears loop-filter-across-tiles when tiles are disabled. The remaining returned
differences are `sps_max_num_reorder_pics` (0/7), uniform-spacing with tiles disabled,
and unused I-slice motion flags. Full weights, scaling matrices, QP/deblock values,
slice byte offsets and encoded input bytes agree between clients. Raw DPB/list slots
remain different; logical slice reference writers agree for all 300 pictures.

Use these inputs in #66's command coverage map. A useful next measurement compares
the remaining **actual emitted commands and compressed-reference state**, preserving
reference identities, allocation/lifetime, privacy and finite bounds. The command
map must distinguish an incorrect shared firmware contract from a kernel state or
memory problem. Do not infer firmware guilt from equal source-model predictions,
and do not apply a speculative DPB permutation or PCM workaround.

AI maintainer self-review; no independent kernel review claimed. This campaign
did not change/load/install a module, change packages, edit shipped patches or reboot.
