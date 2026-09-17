# Direct-V4L2 HEVC reference evidence

This is offline tooling for [child #50](https://github.com/iconidentify/omarchy-m1-video/issues/50)
of [driver #42](https://github.com/iconidentify/libva-v4l2_request/issues/42).
It converts a narrowly supported `v4l2-tracer` capture to the reference subset
used by the driver's `hevc-reftrace-check.py`. It also associates GStreamer
output-log events with decode-order pictures. **The committed tests are synthetic.
No new hardware result, cause, fix or codec support is established here.**

## Supported contract

- v4l2-tracer **1.32.0**, pinned upstream commit
  `5a666c7ce89c00d66aa8e53c8f098a0c6c401f91`, with userspace arguments (`-u`).
- GStreamer **1.28.7**, upstream commit
  `070125524a8422e29d3b69a372ed4f62fd343ffa`, for timestamp and output-log semantics.
  Record actual package revisions and binary hashes separately; a version string
  does not prove that a distributor has no local patches.
- One opened HEVC video context, one complete slice/request/picture, one-plane
  MPLANE CAPTURE buffers, no reconfiguration, flushing, seeking or dropped pictures.
- An independently known expected picture count, bounded to 1–10,000. A valid
  shorter prefix is rejected when it does not meet that count.
- Successful request allocation, controls, OUTPUT QBUF, media-request queue,
  OUTPUT/CAPTURE completion and final stream stop/close. Nonblocking DQBUF EAGAIN
  is allowed; other selected-operation errors fail closed. Unknown errno spelling
  may conservatively reject a capture.

Two limitations in this pinned tracer need special handling:

1. `trace_v4l2_ext_control()` calls the HEVC slice generator once regardless of
   dynamic-array size. A size other than **280 bytes** is rejected, even if its
   first slice looks valid. SPS/decode payload sizes must be 40/328 bytes.
2. `trace_v4l2_hevc_dpb_entry_gen()` uses the **PPS** flag table for DPB flags.
   Its `V4L2_HEVC_PPS_FLAG_DEPENDENT_SLICE_SEGMENT_ENABLED` text represents bit 0,
   which in a DPB entry is `V4L2_HEVC_DPB_ENTRY_LONG_TERM_REFERENCE`. The adapter
   maps exactly that known encoding and rejects other DPB flags. This corrects
   metadata interpretation only; no installed library is changed.

The tracer also serializes only plane zero. This adapter requires a single
CAPTURE plane. It does not interpret compressed payload, validate bitstream bytes,
or certify the contents of other controls. Source URLs and SHA-256 hashes are in
[source-map.json](source-map.json); the relevant functions are:

| Fact | Pinned source/function |
| --- | --- |
| Pre-call arguments, errno and accepted queue event | `libv4l2tracer.cpp:ioctl` |
| Control size, single slice, buffer timestamp | `trace.cpp:trace_v4l2_ext_control`, `trace_v4l2_buffer` |
| DPB flag-table bug and fixed arrays | `trace-gen.cpp:trace_v4l2_hevc_dpb_entry_gen`, `trace_v4l2_ctrl_hevc_decode_params_gen` |
| Flag strings and separators | `v4l2-tracer-common.cpp:fl2s`, `add_separator` |
| OUTPUT timestamp = system frame number × 1,000 ns | `gstv4l2decoder.c:gst_v4l2_decoder_queue_sink_mem` |
| DPB timestamp uses the same system frame number | `gstv4l2codech265dec.c:gst_v4l2_codec_h265_dec_fill_decode_params` |
| Output event occurs before completion/error checks | `gstv4l2codech265dec.c:gst_v4l2_codec_h265_dec_output_picture` |

## Identity and comparison

Timestamp zero is a valid first GStreamer picture. POC alone is not a unique
identity, and output order is not decode order. Successful CAPTURE DQBUF events
map the unique timestamp of each queued request to its real buffer index.
DPB references must name earlier pictures, agree with their POC, and resolve to
the most recent writer of that buffer. Stale references to reused buffers and
references aliasing the destination are rejected.

The emitted schema is `libva-v4l2request.hevc-refs/1`: request order supplies
`pic`/`req`, completed CAPTURE indices supply `target`/`dpb.buf`, and run identity
is the first 16 hex digits of the private raw trace's SHA-256. `reorder=0` is
client metadata, excluded by the driver's comparison. `total_curr` is derived
from the three submitted current-RPS list lengths. Only whitelisted integer
metadata and fixed schema strings are emitted; paths, FDs, pointers and media
payload never enter the normalized files.

The optional association file uses zero-based `output_index` and one-based
decode-order `pic`, plus POC and GStreamer's system frame number. It requires one
element's complete unique output-log sequence, all queued/completed pictures,
**successful pipeline exit and an independently verified raw output frame count**.
The latter two are caller-provided evidence assertions. The converter cannot
prove them, or that the log and raw output belong to the same run. The capture
operator must retain provenance tying them together. An output log alone is not
proof of successful output: GStreamer logs before checking completion/errors.

Equal records mean equal **recorded reference fields** over the stated extent.
They do not compare all SPS/PPS, weights, entry points or bitstream bytes, and do
not establish kernel/firmware sufficiency. Extra unused DPB entries/order can
differ legitimately between clients. Investigate a reported difference; do not
assume it causes corruption. The parent still owns real paired captures, an
accepted cause/correction, RPS_B preservation and full HEVC qualification.

## Offline use and tests

With a trusted checkout of driver commit
`266269ee49d2fbb147f4983307b4b2492bd1a829` (or a reviewed compatible successor):

```sh
HEVC_REFTRACE_CHECKER=/absolute/driver/tests/hevc-reftrace-check.py \
  python3 experiments/hevc-controls/tests.py

python3 experiments/hevc-controls/normalize.py private/raw_trace.json \
  --expected-pictures 300 --output gst-refs.jsonl \
  --gst-log private/gst.log --gstreamer-version 1.28.7 \
  --decoded-frames 300 --tracee-status 0 --association gst-output.json

python3 /absolute/driver/tests/hevc-reftrace-check.py validate gst-refs.jsonl
python3 /absolute/driver/tests/hevc-reftrace-check.py compare \
  va-refs.jsonl gst-refs.jsonl --expected-pictures 300 --json
```

Pass the observed child status/count, never copy the example's zero/300 without
checking. Comparison exit 1 means a difference to investigate; exit 2 means
unavailable evidence. Conversion exit 2 also rejects input. Output paths must
not exist. Files are capped at 128 MiB; duplicate JSON keys, non-JSON numbers,
incomplete lifecycle, omitted slices, unknown flag encodings and ambiguous
association are rejected. Larger captures need a separately reviewed design.

The tests exercise zero timestamps, decode/display reordering, pending requests,
request-FD reuse, CAPTURE reuse, implicit P-slice L0 selection, the tracer flag
bug, malformed and missing events, output association, privacy and interoperability
with the pinned driver checker. Without `HEVC_REFTRACE_CHECKER`, they explicitly
report that interoperability was not run. Public CI supplies it and runs entirely
offline on a hosted worker.

## Future guarded capture recipe (not run by these tests)

Read root AGENTS.md/README.md and the driver hardware guard first. Verify Apple
hardware and linux-asahi. Check exact package versions, source and binary hashes,
the licensed corpus identity, decoder idle state and fault history. Keep all
other video apps closed for the exclusive window. A new fault stops the campaign;
an issue claim does not authorize module recovery, installation or kernel edits.

Create a fresh **private directory per run** (`umask 077`, directory mode 0700).
Raw tracer JSON contains compressed media, paths and addresses. Do not commit or
publish it, and do not treat `v4l2-tracer clean` as a privacy sanitizer. Preserve
it locally alongside guard logs, stderr, actual child exit status, raw YUV, hashes,
input identity and package/build provenance. Publish only reviewed metadata.

The GStreamer pipeline to put under a finite `tests/hwguard.py` lease is:

```sh
v4l2-tracer -u trace sh -c '
  GST_DEBUG_NO_COLOR=1 GST_DEBUG=v4l2codecs:6 GST_DEBUG_FILE="$2/gst.log" \
    gst-launch-1.0 -e filesrc location="$1" ! h265parse ! \
    v4l2slh265dec name=refprobe ! videoconvert ! video/x-raw,format=I420 ! \
    filesink location="$2/output.yuv"
  child_status=$?
  printf "%s\n" "$child_status" > "$2/tracee-status"
  exit "$child_status"
' sh "$HEVC_VECTOR" "$PRIVATE_RUN_DIR"
```

Run with the current working directory set to that private run directory; the
tracer writes its timestamp-named JSON there. The explicit inner-shell status
file is necessary: this tracer version returns a raw `wait()` status, so its
outer shell exit code can be zero after a child fails. A missing status file,
failed guard or child, truncated trace, unexpected file count or incomplete raw
output invalidates the capture. Do not automatically retry a hardware failure.

For RPS_E, the known input is 416×240 8-bit I420, 300 frames: raw output must
contain exactly **44,928,000 bytes**. Check each frame against the authoritative
software/reference output, retaining the full wrong-frame set. RPS_B is the
unchanged regression control; determine its dimensions/count from its own
verified reference. For VA, select the reviewed local build with
`LIBVA_DRIVERS_PATH`, enable `LIBVA_V4L2_HEVC_REFTRACE` to a new metadata file,
and retain complete native-size frame hashes. Never equate its output-frame
indices directly with trace picture numbers.

Start with one RPS_B and one RPS_E capture per client, each with a finite deadline
and clean final idle state. Trace-disabled comparisons establish that tracing
has not changed the observed wrong-frame set. Associate the first differing
output with decode requests/POC on both paths before proposing an AVD change.
