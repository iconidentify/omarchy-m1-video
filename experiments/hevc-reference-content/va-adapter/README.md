# Experimental VA observer session and allocation API

AI-assisted implementation and maintainer self-review; original z23 commits and
attribution remain in [PR100](https://github.com/iconidentify/omarchy-m1-video/pull/100).
This implements the offline driver side of
[#95](https://github.com/iconidentify/omarchy-m1-video/issues/95).
Parent #82 and driver #42 remain open. No installation, hardware access, live
mapping, payload copy, coherence admission or support-count change is included.

```sh
python3 experiments/hevc-reference-content/va-adapter/tests.py
```

Requires Linux, a C compiler with ASan/UBSan and TSan, patch, Meson, Ninja,
pkg-config, libva/libdrm development packages and HEVC-capable Linux UAPI headers.
The runner fetches a SHA-256-pinned driver archive; `--archive PATH` accepts the
same verified archive offline. `--keep EMPTY_DIRECTORY` retains build artifacts
and original-driver regression output. No sanitizer failure is silently skipped.

The committed patch adds explicit sessions, selected-surface/allocation/writer
identities and a display-wide ownership gate to actual driver entrypoints. It
replaces the earlier numeric-ID/current-picture observer, which could not retain
an explicitly selected allocation or reject stale/foreign ends. Export/derived
aliases remain excluded across allocation reuse, and CPU uploads invalidate the
decode writer. The receipt joins opt-in same-run HEVC reference records and never
claims that memory is coherent or permits a copy.

The runner builds the complete configured module, runs all original Meson
regressions, and executes the public API harness under ASan/UBSan and TSan. The
pinned driver's existing fake V4L2/allocator model supplies syscalls; context,
surface, queue, dequeue, image and destruction code are real. Nine deliberate
changes to producer gating, pin/release, writer validation, drain, deadline,
allocation alias history, uploads and owner checks must fail named assertions.
The earlier hand-populated context/helper fixture is superseded.

Read [CONTRACT.md](CONTRACT.md) for exact supported modes, participating entrypoints,
lock order, cancellation obligations, receipt identity and remaining parent work.
[VALIDATION.md](VALIDATION.md) records the completed checks and artifact identities.
