# Experimental HEVC AVD recorder

This is the offline implementation for #62 / PR #63, preparing the actual kernel
measurement in #61. It does **not** fix RPS_E or change any supported-codec count.
No candidate module has been loaded, installed or hardware-qualified by this work.
The existing 15 shipped patches and package pins are unchanged.

The recorder observes actual returned reference buffers, copied-timestamp validity,
writer/allocation lifetimes, intra state and the words appended by the HEVC command
builder. It records all 300 picture starts/completions and command detail for
pictures 24–34. This targets the first bad Gst decode picture 29 / POC28 and VA
picture 31 / POC31; it does not confuse decode order with displayed-frame order.
See the [accepted source map](../hevc-avd-map/README.md) and
[instrumentation design](../hevc-avd-map/INSTRUMENTATION.md).

## Files and offline reproduction

- `hooks.patch`: separate experimental changes to the pinned AVD source after the
  15 shipped patches. `kernel/` contains the new recorder source and shared state
  machine; neither location participates in the installer or rebuild service.
- `sources.json`: exact upstream AVD files, source revision and shipped patch hashes.
- `prepare.py`: verifies those inputs, creates a new isolated directory, applies the
  stack without fuzz, and optionally builds against matching ARM64 headers. It
  refuses existing output directories and does not install or execute a module.
- `check.py`: validates sealed snapshots, normalizes private timestamps to writer
  ordinals, and optionally correlates the same run's userspace reference trace.
- `capture.py`: an execution supervisor for a **later authorized** guarded run. It
  keeps the decoder unprivileged and uses noninteractive sudo only for fixed
  root-owned trace files. Its tests use a fake backend and harmless child programs.
- `tests.py`, `state-tests.c`, `motion-vectors.c`, `source-tests.py`: synthetic
  counterexamples, the actual shared C recorder under ASan/UBSan, 5,760 full motion
  word comparisons against the attributed upstream macros, and patch/preservation checks.

From the repository root, with ordinary Linux build tools and Python 3:

```sh
python3 experiments/hevc-avd-trace/tests.py
python3 experiments/hevc-avd-trace/fetch.py /tmp/avd-pristine-new
python3 experiments/hevc-avd-trace/source-tests.py /tmp/avd-pristine-new
python3 experiments/hevc-avd-trace/prepare.py \
  --source /tmp/avd-pristine-new --destination /tmp/avd-trace-new \
  --headers /usr/lib/modules/7.1.13-3-1-ARCH/build
```

Omit `--headers` for source-only preparation on a host without the pinned ARM64
headers. Do not install or force mismatched headers. `fetch.py` downloads only
hash-locked primary files from Asahi Linux revision
`94fb23346d522edf53722357c426a3e58030beea`. Ordinary PR CI runs no-device tests and
patch checks on GitHub-hosted Linux; the matching Asahi module build is recorded
separately in [build.json](build.json). The source map remains separately tested.

## Recording contract

Default state is off: there is no capture allocation or record collection until
an explicit root-only debugfs control write. The experimental module exposes
`/sys/kernel/debug/apple_avd_hevc_trace/{control,status,snapshot}`; control is
0200 and the read files are 0400. It adds no service, hook or boot configuration.

`arm RUN TGID` requires no open AVD contexts, a positive process ID and a strictly
increasing positive run ID. The selected process's first HEVC job binds one
opaque context ID. Same-process capability probes that submit no jobs do not
consume the capture. An unrelated opener or any additional/non-HEVC decoding
context through sealing sets a sticky error; its metadata is not collected.
The opener's process ID is stored at open, so kworker/IRQ callbacks cannot change
the filter. The direct decoder executable must keep that TGID: do not wrap it in
a shell that forks another decoder process.

Selected-context close checks extent and drains the recorder after m2m teardown
and watchdog cancellation. It does not yet freeze errors: a later extra decoder
context still invalidates this run. After the client exits and **all** contexts
close, `seal RUN` freezes it. A run that never binds is sealed with an extent
error. Only a sealed snapshot is readable. `off` or a new arm cannot clear a
capture while a context is open. Preserve failed artifacts before another arm.

Each record is 616 bytes: five u64 envelope fields and 72 scalar payload fields.
There are 2,048 slots; the capture object is 1,261,648 bytes. The intended bound
is 600 start/completion records plus 11 × (16 table + 32 list + 1 motion) = 1,139.
Overflow never overwrites old records: attempted count advances and a sticky error
invalidates the snapshot. Extra slices/entry points, picture extent, incomplete
jobs and bad ordering likewise invalidate evidence. `status` provides a bounded
live error/count read so the supervisor can stop the child without altering
kernel submission behavior.

At most one snapshot reader is allowed. Arm/replacement allocations and snapshots
are serialized; maximum capture storage is three objects (old, new, reader copy),
plus at most a 4 MiB seq_file text buffer for one reader: under 8 MiB, excluding
ordinary allocator bookkeeping. No large copy/allocation or userspace access
occurs under the IRQ-safe record spinlock. Default-off capture storage is zero.
See [REVIEW.md](REVIEW.md) for ownership, cleanup and limitations.

Allocation IDs identify vb2 `buf_init` / `buf_cleanup` attachment lifetimes,
including a changed DMABUF backing/length; they are not physical-page identities
or content checks. Recorded address words are decoded privately and exported
only as in-allocation relative offsets. Out-of-range addresses become the
`U64_MAX` sentinel. No raw DMA/kernel addresses or media are exported. Raw request
and returned timestamps are private; the normalizer removes their numeric values.
The exact field order and reserved-zero rules are in [SCHEMA.md](SCHEMA.md).

## Validate a later capture

```sh
HEVC_REFTRACE_CHECKER=/path/to/reviewed-driver/tests/hevc-reftrace-check.py \
python3 experiments/hevc-avd-trace/check.py private-run/snapshot.txt \
  --run 107 --userspace private-run/current-client-refs.jsonl > normalized.json
```

`--userspace` requires the trusted checker hash pinned by the source-map artifact;
its strict checker runs before source-model mapping. Use that **same campaign's**
normalized request trace, not historical captures with coincidentally matching
buffer indices. Without this option, the output explicitly says it is not
userspace-correlated. Successful parsing alone cannot satisfy #61.

Exit 0 means structurally valid with no discrepancies in the checked fields;
exit 1 preserves structurally valid records with measured discrepancies (e.g.
fallback, wrong writer/state/command); exit 2 rejects malformed, missing, duplicated,
wrong-context, overflowing, incomplete or unsupported evidence. A fallback is not
silently removed as bad input. Matching kernel fields do not establish correct
pixels, firmware innocence/guilt, or all-control equivalence.

## Next authorized experiment

The concrete candidate and self-review are recorded in [build.json](build.json)
and [REVIEW.md](REVIEW.md). Parent #61 retains independent kernel review routing,
explicit owner approval for the experimental module, saved work/closed apps and
fresh supported-machine/idle/fault checks. Prior single-reload permission is spent.
A matching-header build is not runtime qualification.

The proposed temporary window is eight serial short runs: RPS_B/E × VA/Gst ×
tracing off/on, all on the same instrumented module, each inside the shared driver
`tests/hwguard.py` with a finite deadline ≤90 seconds and a fixed justified journal
boundary. `capture.py` is nested **inside** that guard; it is not a replacement:

```text
hwguard [reviewed gate and deadline arguments] -- python3 capture.py \
  --run UNIQUE_INTEGER --trace on|off --deadline 60 --output NEW_PRIVATE_DIRECTORY \
  -- DIRECT_DECODER_EXECUTABLE [reviewed vector/client arguments]
```

The supervisor blocks its child before exec, arms for that exact PID (or turns
tracing off), monitors sticky errors, preserves actual wait status, seals and
saves even invalid snapshots. It never unloads/reloads, installs, resets or retries.
A child stuck in uninterruptible sleep remains explicitly unreaped, not successful.
The campaign must separately retain source/loaded-module identity, guard evidence,
all 300 output hashes, same-run user/kernel association and idle final state.
Require identical off/on hashes, exact RPS_B, and unchanged complete RPS_E wrong
sets. Stop on any fault, foreign client, wedge, timeout or trace error. Restore
the existing module only on the authorized clean path; a fault is a stop requiring
recovery coordination. No reboot, boot update or full-suite claim follows.

AI-authored instrumentation/tooling and self-review. Original AVD authorship
belongs to the Asahi Linux Contributors, including Eileen Yoon; existing source
licences remain intact. The upstream instruction macros used by the tests retain
their MIT notice in `../hevc-avd-map/avd-bits.h` and its accompanying licence.
New code and experimental kernel patch changes are GPL-2.0-only.
