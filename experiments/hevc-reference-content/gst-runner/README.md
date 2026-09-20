# GStreamer observer runner and normalized result

AI-assisted implementation for [#120](https://github.com/iconidentify/omarchy-m1-video/issues/120),
under the selected-output campaign in
[#82](https://github.com/iconidentify/omarchy-m1-video/issues/82). This
experimental layer turns the existing internal GStreamer call-site API into a
real decoder configuration and a bounded machine-readable result. It applies
after the observer, retained-copy integration and client-hook patches. It is not
part of the installer and is off by default.

The patched `v4l2slh265dec` has three write-once properties:

- `hevc-observer-frames`: one to eight distinct comma-separated decimal
  `system_frame_number` selectors;
- `hevc-observer-copy`: whether the already bounded compressed/MV ranges are
  copied and hashed; and
- `hevc-observer-report`: the new result path, which must not already exist.

All three properties are required. They must be set before streaming, and any
duplicate, partial, malformed, late or mutable configuration is refused. The
real `start_picture` vfunc arms on the streaming owner after negotiation and
before its first bitstream/request allocation. With no properties set, no
runner state is allocated and the decoder takes the original path.

`hevc-observer-status` exposes `disabled`, `configured`, `armed`,
`configuration-refused`, `arm-refused`, `armed-stream-failure`,
`incomplete-observation`, `cleanup-quarantine`, `report-failure`, or `success`.
Terminal results are also posted on the element bus; failures post a
`GST_ELEMENT_ERROR`. A downstream failure, missing selected output, failed
native cleanup or failed report write cannot produce success.

## Result boundary

The runner serializes only normalized identities and hashes. It never writes a
pointer, file descriptor, DMA address, raw copied bytes, native receipt or lease.
Every output must match the configured selector set and copy mode; outputs must
be unique and share one run, decoder context and observer session. Copy-off
results carry `sha256: null`, while copy-on hashes the existing fixed-size
private snapshot.

Serialization completes in memory, then same-owner native finish must release
the observer session and retained objects before publication. The report is at
most 8192 bytes, mode `0600`, fully written and `fsync`ed, then published with
Linux `renameat2(RENAME_NOREPLACE)`. A destination collision or any open,
write, sync, close, cleanup or rename failure leaves no report from this run and
returns a stream error. A failed native finish remains quarantined for an
explicit retry and is never represented as a result.

`collector.py` opens the report with `O_NOFOLLOW` only after the complete
GStreamer process has exited successfully. It requires a bounded private regular
file owned by the current user with one link, a stable read, exact schema and
field set, well-formed identities, one shared run/context/session, unique
frames/requests, and the externally expected selectors and copy mode. Thus the
report alone is not success: a later pipeline/process error invalidates it.

Example collection after a successful process exit:

```sh
python3 experiments/hevc-reference-content/gst-runner/collector.py result.json \
  --frames 31,47 --copy on --process-exit-code 0
```

## Offline reproduction

From the companion repository root:

```sh
python3 experiments/hevc-reference-content/gst-runner/tests.py \
  --keep /tmp/hevc-gst-runner
```

The destination must be empty. `--archive` reuses the hash-verified pinned
GStreamer archive and `--native-file` supports the same optional GLib generator
overrides as the adapter tests. The runner builds the complete pinned plugin and
real H265 class under ASan/UBSan and TSan, then repeats all preceding call-site,
copy-integration and observer API modes on the modified source. The fixture uses
synthetic V4L2 syscalls, framework frames and CPU memfds; it does not claim a
hardware decode, DMA coherence, display result or qualification.

Named mutations require a compiled binary to abort at their intended semantic
assertion. Compiler failures, sanitizer findings, timeouts and unrelated crashes
do not count. The suite also tests write/sync/close failures, short writes,
exclusive collisions, strict collection, actual vfunc arming, downstream error,
incomplete output and retained-cleanup quarantine.

This leaf closes the GStreamer process-to-result gap. It does not bind that
result to a same-run kernel command/reference record, decide late RPS_E writer
eligibility, install a patched plugin or authorize hardware. Those remain parent
#82 and driver #42 work.
