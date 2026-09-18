# Retained-allocation copy integration

AI-assisted implementation for [#82](https://github.com/iconidentify/omarchy-m1-video/issues/82).
**Offline experiment; no hardware qualification or installed changes.** Separate
Codex design/code review is recorded in [REVIEW.md](REVIEW.md). Human specialist
review and the remaining #82 gates are still required.

This applies additive patches to the complete, pinned VA driver and Gst plugin
already exercised by [va-adapter](../va-adapter/CONTRACT.md) and
[gst-adapter](../gst-adapter/CONTRACT.md). Their accepted patches/tests are unchanged.
The actual native lease protects allocation selection, read-only mapping, bounded
copy, post-copy validation and unmapping. Native end refuses to release a lease
while an unsuccessful unmap still owns a pointer; the owner must retry cleanup.
The eight-copy limit is also kept privately by the native context, so reinitializing
a caller pool cannot reset it. A failure after acquiring the snapshot lock stops that pool; disabled, wrong-owner
and lock-contention refusals return without changing it.

The normalized record fixes the plane bound at eight and separates common generation
fields from client-specific identities:

| Record | VA source | Gst source |
| --- | --- | --- |
| `context_generation` | `session.context_generation` | `session.context` |
| `allocation_generation` | `target.allocation_generation` | `target.allocation` |
| Tagged detail | context/surface handles, surface generation, last reference | request generation, frame number |
| Common identity | client tag, run pair, session nonce, lease, writer, submitted/completed, capture index, plane sizes | same concepts; counters remain local to that client's run |

`va-content.h` and `gst-content.h` declare the internal experiment APIs. Initialize
and allocate the output pool **before** native begin. After begin succeeds, call
snapshot on the owner thread, then end on every path. Never hash, serialize or
publish bytes until end succeeds. A stopped/invalid slot is not evidence. These
are not generic libva/GStreamer interfaces or automatic decode hooks.

See [CONTRACT.md](CONTRACT.md) for ordering, provenance and bounds. Only the audited
single-plane NV12 geometry and two extents are admitted. VA maps the selected
QUERYBUF offset on its retained video fd. Gst maps the original internal EXPBUF
fd owned by its allocator; it never calls public `gst_buffer_map`. Imported or
previously aliased/published allocations remain rejected by the underlying APIs.

## Runtime evidence and remaining boundary

No `/etc/apple-avd-observer/approved-builds` file is provided or installed. Copying
requires that fixed, root-owned, non-writable-by-others regular file and directory;
its nine exact entries identify the reviewed kernel source and shipped patch set,
loaded kernel, AVD, three vb2 components, and the two observer build IDs. The
manifest is an administrator's reviewed build attestation, not automatic proof
that a binary came from source. The selected video fd must match the AVD driver
through fstat, QUERYCAP and sysfs. Both checks and bounded provenance records occur
before/after copying. Missing IDs, `builtin` markers and unknown allocation policy
fail closed. This first version deliberately does not support built-in vb2: a
missing module note cannot prove built-in status.

The private build-ID cache identifies the object containing each native snapshot
function before the lease. It **does not attest the entire FFmpeg/Gst dependency
stack or corpus**. No production FFmpeg call site or Gst pre-publication hook is
wired, and no kernel command/reference collector is joined here. Existing native
writer/completion receipts are normalized faithfully; they do not retroactively
authenticate old capture files. Those are concrete remaining integration gates,
along with a reviewed live manifest, not evidence that lifetime APIs are absent.
No hardware campaign can run from this directory as shipped.

## Reproduce offline tests

Dependencies are those of the two adapter suites: Linux C toolchain with
ASan/UBSan/TSan, Meson, Ninja, pkg-config, libva/libdrm, GLib development tools,
libgudev, Flex and Bison. Sources are downloaded by the existing hash-pinned
fetchers. `--archive` accepts their cached archive but still verifies its hash.
`--keep` must name an empty directory. No dependency installation or device access
is performed by these commands.

```sh
python3 experiments/hevc-reference-content/integration/tests.py --client va --keep /tmp/content-va
python3 experiments/hevc-reference-content/integration/tests.py --client gst --keep /tmp/content-gst
```

Gst additionally accepts `--native-file /path/to/meson-native.ini` for GLib tool
paths. The suite builds the complete configured module/plugin, and compiles its
actual sources into the fixture. It exercises the existing native APIs rather
than duplicated observer bodies. Syscalls, device properties, backing memfds and
root/sysfs evidence are explicitly synthetic. Pinned Gst libraries are checked
with `ldd`; the host's installed Gst plugin cannot substitute for them.

The integration cases cover both layouts, byte patterns unique to each allocation,
exact fd/offset/permissions/extent, paired off/on, normalized identity, eight-copy
limits across pool reset, disabled mode, bad/missing/changed build evidence,
untrusted manifest ownership, wrong driver binding, stale/foreign receipts,
malformed planes/extents, missing retention, deadlines and failed mmap/munmap
cleanup. VA adds actual codec/policy-record refusal. Existing foreign-thread
producer/destruction gates are exercised while a lease is retained. The original
21 VA / 29 Gst observer modes run again on the extended sources under both
sanitizers. Mutations must compile and abort at a named semantic assertion;
compiler failures, timeouts and sanitizer errors are not counted as detections.

The Gst allocation mutation removes **both** redundant allocation checks, at
receipt normalization and the private map boundary. Other mutants independently
remove range correctness, kernel attestation, copy deadline, retained unmap and
native context budget. Original helper/synthetic tests remain separate evidence.

These model results establish code behavior under the stated syscall model.
They do not establish DMA visibility, hardware output correctness or noninterference.
Use the separately reviewed [campaign plan](../CAMPAIGN.md) only after its missing
gates and authorization are satisfied. #82 and parent driver #42 remain open.
