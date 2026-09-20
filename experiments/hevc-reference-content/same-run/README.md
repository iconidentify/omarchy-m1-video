# Same-run client/kernel evidence supervisor

AI-assisted implementation for
[#122](https://github.com/iconidentify/omarchy-m1-video/issues/122), under the
bounded reference-content campaign in
[#82](https://github.com/iconidentify/omarchy-m1-video/issues/82). This is an
experimental, default-off evidence path. It is not installed, does not load a
module, and is not campaign or hardware authorization.

This closes the process-attribution gap between the merged FFmpeg/VA and
GStreamer observer results and the existing paired AVD command/reference
recorders. A successful result now means that all of the following came from one
finite, reaped decoder process:

1. the strict normalized client result;
2. the client's actual observer queue identity;
3. a complete raw V4L2 request/completion trace;
4. sealed, zero-error command and reference snapshots for one kernel run and
   context; and
5. successful execution of the existing full-controls lifecycle checker,
   reference validator, returned-control comparison and pinned C command oracle.

No POC, frame number, output ordinal, fd or capture index is accepted as a join
by itself.

## Process topology

`v4l2-tracer` forks its tracee. Therefore the tracer must not be the process for
which the kernel recorders are armed. `supervisor.py` uses this topology:

```text
guarded runner
  └─ v4l2-tracer
       └─ private supervisor worker
            └─ decoder child (blocked before exec)
```

The worker forks the decoder, records its actual PID, arms both kernel recorders
for that PID and the same nonzero u64 run, then releases it. Linux parent-death
handling kills the decoder if the worker disappears. The worker reaps the real
decoder status, seals and persists both recorder snapshots, and exits. Only then
can the outer tracer finish its raw file; the guarded runner subsequently
validates and joins the artifacts. Putting `v4l2-tracer` inside the worker would
arm for the wrapper PID and is explicitly rejected by the design/tests.

The outer tracer, worker and decoder have finite deadlines. A timeout terminates
the entire tracer process group; a dead worker causes the already-released
decoder to receive its configured parent-death signal. Failed or partial kernel
captures remain preserved and are never cleared as success.

## Identity bridge

Client and kernel allocation numbers are intentionally different identity
domains. The join never compares them numerically:

- VA: selected output ordinal → real FFmpeg output/POC association → exact
  driver HEVC trace row → observer run/context/allocation/writer tuple → that
  same process's normalized raw V4L2 request.
- Gst: selected `system_frame_number` → exact `observer-queue` full tuple
  (run/context/allocation/request/writer/frame/capture) → copied raw V4L2
  timestamp and capture lifetime from that process.
- Both: raw request picture → same-run kernel reference start/completion pair →
  paired command history and oracle-checked selected command windows.

The final public schema, `omarchy.hevc.same-run-join/v1`, contains normalized
client identities, the distinct kernel run/context and allocation/writer
identity, copy hashes when enabled, and SHA-256 digests of every private input.
It contains no raw timestamp, fd, pointer, DMA address, lease, payload or copied
bytes. Publication is mode 0600, fully written and fsynced, then Linux
`renameat2(RENAME_NOREPLACE)`; a destination created during publication cannot
be overwritten.

## Later authorized use

The command below is a shape reference only. Values, binaries, corpus and oracle
paths must come from a separately reviewed live manifest and campaign admission.
The caller must already be an ordinary user inside `tests/hwguard.py` and must
use a fresh output root and kernel run.

```sh
python3 experiments/hevc-reference-content/same-run/supervisor.py \
  --root /private/fresh-run --client va --selectors 1,3 --copy on \
  --kernel-run 123 --deadline 90 --uapi /reviewed/v4l2-controls.h \
  --oracle /reviewed/compiled-oracle -- \
  /reviewed/ffmpeg -threads:v:0 1 -hwaccel vaapi \
  -va_observer_outputs:v:0 1,3 -va_observer_copy:v:0 1 \
  -va_observer_report:v:0 @OMARCHY_OBSERVER_REPORT@ \
  -i /locked/input.hevc -f null -
```

For Gst, the direct command must contain exactly one `v4l2slh265dec`; its three
observer properties must be on that element before the next `!`. The runner sets
`GST_DEBUG=v4l2codecs*:7` because `observer-queue` is a TRACE-level record; level
6 silently omits the identity needed for the join. For VA, the runner fixes the
native HEVC reference-trace destination and requires explicit single-threaded
VAAPI decode. Commands are argv arrays and never pass through a shell.

## Offline reproduction

```sh
python3 experiments/hevc-reference-content/same-run/tests.py
python3 experiments/hevc-reference-content/same-run/mutations.py
python3 experiments/hevc-avd-command-capture/tests.py
```

The tests use fake recorder backends and invented normalized identities. They
exercise real fork/exec/reap, exact-PID arming, environment/cwd/log binding,
strict VA and Gst joins, existing-validator orchestration, private stable reads,
exclusive publication and injected failures. No device or sudo command runs.
Exact results and hashes are in [VALIDATION.md](VALIDATION.md); adversarial
findings and unresolved limits are in [REVIEW.md](REVIEW.md).

## Remaining boundary

This leaf makes one later guarded workload mechanically attributable. It does
not provide or approve the root-owned live observer manifest, attest the complete
FFmpeg/Gst dependency set or corpus, choose real RPS_E targets, make a late
published Gst allocation eligible, demonstrate DMA visibility, run the eight
off/on workloads, install a build or increase codec coverage. The campaign
controller therefore still refuses execution; parent #82 and driver #42 remain
open.
