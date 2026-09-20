# First live reference-content campaign

AI-assisted implementation and maintainer self-review for #128, under #82 and
driver #42. This directory is not an installer or blanket hardware permission.
No hardware result is claimed by its offline tests.

`prepare.py` starts from the complete #126 build at its final `/var/lib` runtime
path, copies external patch/corpus/reference inputs without changing their
bytes, and binds campaign source files. It emits another **candidate**, plus the
nine-line native build-ID approval candidate. It neither approves nor loads it.
The byte-identical hardware guard is referenced in its real pinned Meson source
tree because its provenance lookup requires that layout.

After the exact inventory/code/native IDs have been reviewed, the operator pins
the reviewed manifest and a separately reviewed single-use campaign config by
SHA-256. All code/data inventory ancestors must be root-owned and not writable
by other users. The output root belongs privately to the ordinary run user.
Never relocate a linked runtime without re-building/re-attesting its loader path.

`run.py` verifies those identities before acquiring the host-wide guard and again
inside it. The bounded config binds the original installed module, boot ID and
fixed journal boundary. Under the owner's separately recorded authorization it:

1. Confirms original loaded identity and healthy idle, temporarily substitutes
   the accepted recorder and verifies both clean endpoints.
2. Creates the exact native approval file, then runs the deterministic eight
   supervisor commands with fresh private roots and fresh kernel run identities.
3. Requires every same-run join, all 300 frame hashes, prior exact client pixels,
   paired off/on pixels and selected logical writer projections. It revalidates
   the full kernel evidence and compares command/reference windows off/on and
   across clients using the accepted PR76 logical projection.
4. Stops on the first refusal, discrepancy or fault. Restores the ordinary module
   only if the decoder remains healthy/idle; a fault is never auto-recovered.
   Removes only its unchanged temporary native approval. Preserves all failures.

Deadlines are 90 seconds in the decoder supervisor, 120 per workload and 1,200
for the outer guard. They are external process deadlines, not proof that a stuck
kernel operation can be interrupted. The single-use marker prevents replay.
No installed module/package, shipped patch, service or boot configuration changes.

Offline checks:

```sh
python3 experiments/hevc-reference-content/live-campaign/tests.py
python3 experiments/hevc-reference-content/same-run/tests.py
python3 experiments/hevc-reference-content/same-run/mutations.py
python3 experiments/hevc-reference-content/live-campaign/readback-tests.py
python3 experiments/hevc-reference-content/live-campaign/report-path-tests.py
```

Twelve orchestration groups cover single-use/no-replay, healthy restoration,
fault-blocked restoration, stop at a software refusal, strict frame extent and
sequence, separate prior/pair pixel gates, real accepted cross-client reference
projections, bounded ELF note parsing, sanitized placeholder expansion and config
digest refusal, external UAPI relocation and privileged argv serialization.
These are no-device models, not measured decoder behavior.

## First measured refusal and copy-readback correction

The first guarded attempt stopped before any decoder workload because event
logging received a `Path`; normalization now precedes logging and execution.
The second reached `B-va-off`: the kernel completed 300 pictures with zero
recorder errors, but the observer refused selected output 20. FFmpeg's ordinary
error handling then spun; the exact child was terminated and reaped, and no
same-run join or complete pixel result is claimed. Both attempts restored the
original module while healthy/idle. Their raw evidence/configs remain preserved.

Source and measured ioctl traces identify the mismatch: FFmpeg's startup
`vaDeriveImage` probe creates exported backing before decode, selecting DMABUF.
The observer deliberately admits only private MMAP backing. Its memory, alias
and lifetime checks are unchanged.

The experimental FFmpeg patch adds a default-off device option,
`observer_copy_readback=1`, which skips that startup probe. Ordinary pixel
readback continues through an independent `vaCreateImage`/`vaGetImage` copy;
direct mapping is unavailable in this mode. Invalid option values are rejected
before device access. The attested VA commands explicitly select this device
and `-xerror` so a decode error is fatal. This is instrumentation compatibility,
not a shipped decoder fix or a new passing vector.

The no-device readback fixture compiles the actual pinned libavutil source and
runs its device option, frame-pool and pixel-transfer entrypoints with synthetic
libva calls under ASan/UBSan. It checks absent/0/1 values, invalid-before-open,
derive-probe counts and copied pixels. Four compiling source mutations must hit
their named assertions. Two deployment mutations independently require the
copy-readback option and fatal-error flag in all VA commands. These checks do
not establish live MMAP selection or observation noninterference; a fresh
reviewed build and guarded campaign are still required.

Pre-run review also reproduced an offline join defect using the preserved
reference snapshot: selected detailed windows contain table/list/motion records
between their start and completion. The join now selects only the two lifetime
record kinds after the existing full reference validator has checked every
record. It still rejects duplicate, missing or reversed endpoints. A regression
uses all 44 detailed windows from the accepted public B/E VA/Gst captures, and
a source mutation restores the old refusal to prove the test distinguishes it.

Attempt 3 confirmed MMAP and prompt fatal-error termination, then refused the
first observation with 20 persisted output hashes and 28 kernel completions.
It restored the original healthy/idle state; no successful join is claimed.
The last `VIDIOC_QUERYCAP` identifies the next concrete boundary: the kernel
reports platform driver name `avd`, while `integration/runtime.h` and both fake
syscall fixtures incorrectly expected `apple-avd`. The pinned `avd_querycap`
copies `avd_driver.driver.name`; the separately verified module remains
`apple_avd`. Correcting the fixtures first reproduced the exact false rejection.
Runtime admission now expects exact NUL-terminated `avd`, while retaining the
module symlink and all nine build/source checks. Wrong-name, prefix and empty
capability cases reject, and two mutations exercise the old spelling and a
missing name gate. This corrects observer admission, not decoded output.

Self-review found two deployment integration gaps before device access: the
standalone guard copy had no real source-root metadata, and the same-run reader
required even public immutable oracle/UAPI inputs to belong to the ordinary run
user. The campaign uses the pinned guard's real source tree. The reader now
allows root-owned non-group/other-writable public inputs while retaining strict
same-user ownership and private mode for all captured evidence. Its new test
rejects root-owned private captures and writable public inputs.

The exact reviewed config/digest, hardware transcript and interpretation will be
recorded in the issue/PR and normalized evidence. Until those runs complete,
neither observation noninterference, DMA coherence, RPS_E correction nor a support
count increase has been established. Opaque hash differences are not firmware blame.

## Attempt 4 and the report-path ownership defect

Attempt 4 decoded the whole `B-va-off` workload: 300 kernel pictures and
completions, matching context 10, 767/767 reference records, zero recorder or
decoder errors, and 300 persisted frame hashes matching both the locked
reference and the prior accepted B/VA baseline. Publishing the observer result
then failed with `EEXIST`, the exact child exited 239 and was reaped normally in
0.727 seconds. There is no `client-result.json`, no same-run join and no pass.
The original module was restored healthy and idle and the temporary native
approval removed. Saved frames do not change that classification.

The cause is in our own experimental FFmpeg patch, not in FFmpeg's shipped
behaviour. `ist_add` stored the borrowed `-va_observer_report` option string
straight into `ds->dec_opts`. `open_files` then calls `uninit_options`, which
frees every parsed per-stream option string, before output and filter binding
reach `ist_use -> dec_init -> dec_open`, where the patch finally duplicated it
for the decoder. The neighbouring `hwaccel_device` option had always taken
ownership at input-stream creation and released it in `ist_free`; the report
option omitted both steps. `DecoderOpts` now holds a mutable copy made in
`ist_add` with an `ENOMEM` check and released in `ist_free`, which covers used,
stream-copied and partially initialised streams because `demux_stream_alloc`
registers the stream before any option handling. The decoder keeps its separate
duplicate and its existing `dec_free` cleanup, so the worker's lifetime stays
independent of the demuxer's.

Publication still uses a mode-0600 temporary file, `fsync`, `close` and
`renameat2(RENAME_NOREPLACE)`; exclusive publication is unchanged. The exact
allocator reuse that turned the stale read into attempt 4's `EEXIST` was not
traced, and nothing stronger than the confirmed borrowed-pointer defect is
claimed.

`report-path-tests.py` builds the pinned patched FFmpeg under ASan/UBSan and
drives its real CLI, demuxer, decoder and teardown with software HEVC decoding
only, replacing the final report sink through a test-only linker wrapper. The
wrapper also traces every duplication of the requested path, so each case pins
the exact number of owned copies: three when a decoder opens (parsed option,
demuxer, decoder), two for an unused stream copy or unpaired options, none when
the option is absent. It covers the armed path, the default-off path, an unused
stream copy, unpaired options and both owned allocation failures. Two mutations
must fail: restoring the borrowed pointer trips ASan `heap-use-after-free` at
`dec_open`, and removing the `ist_free` release trips an LSan leak. The existing
call-site suite separately asserts that the copy is made in `ist_add` and
released in `ist_free`.

The regression deliberately does not assert that the decoder worker publishes a
report. With the observer armed, the patch refuses non-VAAPI frames by design,
so a software decode cannot reach publication; the `va-callsite` fixture covers
actual publication against the attempt-4 libraries, plainly and under the
`libv4l2tracer` preload. Reaching that boundary offline would mean faking
hardware, which these tests do not do.

None of this changes decoded output, packaged HEVC support, or the status of
parent #82 and driver #42. A fresh reviewed build and a new guarded campaign
are still required before any measured claim.
