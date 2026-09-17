# Review and execution handoff

AI self-review by sessions `codex-hevc-avd-trace-20260917T1515Z` and
`codex-hevc-avd-live-20260917T1600Z`, routed through
iconidentify. **No independent kernel review has occurred.** This artifact can be
merged as experimental source/tooling; merging it neither loads it nor establishes
runtime safety. Parent #61 retains kernel review routing and execution acceptance.

## Schema-2 correction after the stopped campaign

The [first authorized campaign](captures/2026-09-17/README.md) stopped because
schema 1 confused copied control array extent with used slice entry points.
The original module is restored; no hardware test was retried. The new recorder
passes the copied first slice's actual entry count to its shape guard, preserves
array capacity separately, and exports both in a version-2 snapshot. Old schema-1
reserved zeroes cannot supply the missing fact: the parser rejects the old version.
The existing single-slice/zero-used-entry domain, finite extent, overflow and
stop-on-error behavior remain. Pinned control capacity is bounded at 1–256.

Review checked the applied/copied control lifetime, unchanged hook, new start field
27, zero padding from field 28, unchanged 616-byte record and 2,048-record capacity,
status-schema compatibility with the supervisor, and strict rejection of old/error/
incomplete snapshots. The new field uses an existing owned slice pointer; it adds
no pointer retention, allocation or submission change. New shared-C regressions
cover capacities 1–256 versus actual usage, with parser histories and source-path
checks; the correction has not been loaded. No independent kernel review is claimed.

## What is preserved and observed

The experimental hook patch leaves every HEVC `push`, `pusha`, `push_comp`, `writel`,
submission and postamble call expression unchanged; `source-tests.py` compares
those sequences after applying the exact original stack. It also checks the
I early return, non-I lookup before the TMVP gate, job-hook placement and close
placement after watchdog quiescence. This is a scoped source check, not a proof
of identical timing or all semantics. The later off/on pixel comparison remains
required.

`avd_get_ref_buf_observed` performs the same single `vb2_find_buffer` and destination
fallback as before, with an optional matched output. The original helper delegates
with a null output for other codecs. HEVC hooks receive the actual return object;
they do not repeat the search or guess fallback from the returned index.

Header/list/motion words are read from the just-appended instruction segment.
Compressed/motion address operands are reconstructed from the actual appended
words, handling the variant's address shifts. They are reduced relative to the
returned plane, and invalid ranges become a sentinel before export. Address
construction, instructions and decode controls are not changed. Full raw motion
inputs include inactive reference arrays/counts; I records retain their source's
early-return semantics.

Starts follow the applied/copied HEVC controls and `update_dec_buf_info`. Completions
are recorded before buffers are returned, so a failed job cannot become a successful
writer. A preamble failure produces a completion without a start and sticky failure/
ordering errors; a cancelled/incomplete job produces invalid extent at close.

## Lifetime, filtering, locking and cleanup

- Successful `avd_open` assigns the opaque context ID and remembers the opener TGID.
  The first HEVC job for the explicitly armed TGID binds the context. Same-process
  query-only probes are allowed; another process opener or another decoding context
  sets a sticky foreign error without exporting its data. No PID is inferred from
  the worker/IRQ task running a later callback.
- Capture buffer `buf_init` assigns an opaque allocation ID and zero writer history.
  `buf_cleanup` clears only trace fields. The pinned vb2 core calls these on MMAP
  lifetimes and DMABUF plane/length replacement. The additional primary source is
  hash-locked in `sources.json`; relevant DMABUF transitions are lines 1425–1430
  and 1495–1511 of that revision. Tokens do not prove physical-memory uniqueness
  when separately imported attachments refer to the same DMA buffer.
- `atr_lock` serializes recorder fields and per-buffer trace fields with IRQ-safe
  spin locking. Hooks copy scalar facts only while buffers/controls remain owned
  by the existing decode path. No captured record retains a kernel object pointer.
  No allocation, free, user copy or large snapshot copy runs under that spinlock.
  The completion hook takes the m2m ready-queue lock only to obtain the existing
  next destination; no new path holds that lock while entering `atr_lock`.
  Existing job_lock is released before trace completion, avoiding nesting it here.
- `atr_control_lock` serializes allocation/replacement and snapshot open. Control
  checks open-context count again under `atr_lock`; it cannot free/reset state used
  by an open client. Close runs after m2m release and synchronous watchdog cancellation.
  It drains, but does not seal: another decode before the explicit post-exit seal
  still invalidates the capture. Sealed snapshots are immutable.
- A snapshot open makes an independent copy under the control mutex after checking
  sealed state under the spinlock. A single-reader reservation bounds memory and
  survives control rearm; reads never borrow freed capture storage. Failed allocation/
  open paths free their copies and clear the reservation. File operations pin the
  module; module exit removes debugfs and frees the remaining capture.
- The fixed 2,048-record array never wraps. Attempted/stored counts and sticky error
  bits expose overflow. No error silently repairs data or changes submitted commands.
  Default off allocates no capture. Permission and filtering are controls for this
  supervised experiment, not a general multi-tenant tracing facility.

These arguments were checked against source and the actual local build. Live IRQ,
watchdog, teardown, debugfs and memory-pressure races have **not** been runtime-tested.
Do not represent the portable C state tests as a kernel concurrency test.

## Evidence

- Prior map: four 300-picture reports reproduced; 11 primary source/licence hashes
  and 19 verbatim instruction macros verified before implementation.
- 19 Python test groups pass (18 original groups plus entry capacity/usage): four synthetic full histories, record/extent/loss/
  context rejection, writer/intra/copied/completion errors, lookup fallback findings,
  full words and emitted offsets, actual slice POC, allocation changes, I inactive
  inputs and early return, TMVP-disabled lookup, dependent gating, trusted-model
  differences, C recorder transitions, C macro parity and supervised child failures.
- The actual `avd-trace-core.h` compiles and runs with ASan/UBSan. Its tests cover
  default off, probe filtering, foreign/wrong contexts, extra contexts after drain,
  incomplete sealing, maximum designed 1,139-record extent, overflow, extra slices,
  failed completion, ordering and excess pictures.
- 5,760 complete inter motion words compare with the MIT upstream instruction macros
  for B/P, five relevant flags, merge candidates, edge reference counts and gate values.
  These are generated combinations, not hardware observations or independent videos.
- Exact source/stack preparation passes with zero fuzz. Mismatched source and existing
  output are rejected before mutation. Applied decode emissions/submission are unchanged.
- Matching `7.1.13-3-1-ARCH` headers, GCC `16.1.1 20260430`: clean isolated module build
  with no warnings/errors. [build.json](build.json) identifies every candidate source,
  four key header inputs, source/patch revisions, command, vermagic and module hash.
- Required companion Bash syntax and mocked rebuild tests pass. Dedicated `avd-trace`
  CI runs the synthetic tests and exact source/patch checks; existing CI is retained.
  Original exact-head CI/merge evidence is recorded in PR #63; correction CI is
  recorded separately in its PR.

The original #62 preparation used no hardware or module operations. The later
#61 schema-1 execution and restoration are recorded separately in the campaign
report. Schema-2 correction/build/tests are offline; no installer, boot setting or
reboot was used. The only children executed by supervisor tests are `/bin/sh` with
an immediate exit, `/bin/true`, and bounded `/bin/sleep` processes using a fake trace
backend. Raw historical captures and licensed vectors were not changed or published.

## Specific later operation

Candidate module:
`/home/chrisk/hevc-avd-live-20260917/build-schema2/apple-avd.ko`

SHA-256: `bf890e4def112022cb1381261f51ccab747ec3e4f6184201d4776ee350e19ce3`.
It is an experimental build, currently **unloaded**. The selected installed module
and boot path are untouched. Recheck exact source/module/header hashes and loaded
identity before any authorized campaign; provenance in this file describes only
this offline build, not a future loaded state.

The previous window ended on error and restoration. After fresh explicit owner
consent and a saved-work/closed-app window, the proposed
operation is to unload the existing module once, load any standard dependencies removed by that unload, temporarily load this exact file,
run the eight guarded B/E × VA/Gst × off/on comparisons, then unload it and restore
the unchanged existing module on the clean path. No permanent installation, package
change or reboot. A fault/wedge ends the campaign and requires recovery coordination;
it is not permission to automatically cycle the module. Existing fault evidence
must be preserved before choosing a justified fixed campaign boundary.

Each run needs actual child status, 300 output hashes, complete same-run userspace
association and a sealed kernel snapshot for trace-on. The supervisor checks live
trace errors and a finite deadline; the outer shared hwguard remains responsible
for the decoder lease, fault/foreign-client monitoring and idle final state. The
campaign records exact client/vector/environment and verifies off/on equality,
RPS_B exactness and the unchanged complete RPS_E wrong sets. No reported match can
close driver #42 without its separate correction and full qualification criteria.
