# Review and evidence boundaries

AI maintainer self-review by `codex-hevc-full-controls-20260917T1803Z`.
No independent kernel review is claimed. Runtime kernel/driver code is unchanged.

The normalizer is deliberately narrower than the UAPI: one context, one slice,
zero used entry points and full capture completion. Pinned tracer source establishes
pre/post-ioctl serialization, flattened arrays, DPB flag spelling and pre-QBUF byte
dumps. Pinned kernel UAPI/request/core sources establish widths, complete fields,
sizes, SPS persistence and actual PCM/PPS validation. Source hashes are reverified;
the C size check uses that exact header, not a newer installed one.

Review caught the initial PCM false lead by examining successful ioctl return data
and kernel validation. `controls` now contains those observed return values, while
`input_changes` preserves submitted differences. Missing return fields reject. No
kernel defaults or absent measurements are silently fabricated.

Timestamp normalization retains chronology and buffer generations. Pending Gst
references are allowed before userspace dequeue, but complete later lifecycle,
target/POC and no-destination-alias validation remain required. Simultaneous aliases
reject. Inactive timestamps become null, and all other published scalars/arrays
are whitelisted by the exact serialized struct schema. The standalone copied
lifecycle checker differs only for successful final OUTPUT STREAMOFF after all
CAPTURE completions; source verification enforces that small delta. No historical
adapter or accepted capture is rewritten.

Encoded input hashes are bound to pre-QBUF dumps, actual buffer index/extent and
the selected context's exported-buffer mapping. No bytes or absolute addresses
are exported. The hash does not attest to later DMA coherency. Output association
retains actual waited decoder status and verified complete frame counts. The
tracer's raw-wait exit-status bug is handled by the inner waited-child record;
offline exit-23 validation preceded the finite guarded campaign.

Validation includes 15 synthetic payload/lifecycle/mode/dump test groups, eight
mutated-public-evidence groups, full report reproduction, immutable source and C
size verification, native VA versus ioctl reference-checker agreement, required
companion Bash syntax/mocked rebuild, and exact-head CI before merge. Tests exercise
missing/unknown/bool/out-of-range fields, array truncation, dynamic extent, missing
initial SPS, reference reuse/ambiguity, queued-ahead completion, streamoff versus
missing capture, returned corrections, dump/source binding, changed pixels/controls,
mixed raw capture provenance and guard failures.

All eight hardware workloads completed with every prior frame hash preserved,
final idle/no faults and unchanged original loaded module identity. There was no
module operation, installation, reboot or package change. Broad hardware suites,
race coverage and a corruption fix were not delivered. Private raw authenticity
cannot be independently proven by public digests; this is a transparent local
measurement record and consistency checker, not an independent witness.
