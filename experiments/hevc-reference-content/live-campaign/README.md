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
