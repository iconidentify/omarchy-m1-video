# Offline validation — 2026-09-18

AI-assisted maintainer execution and self-review; no independent specialist
review or hardware qualification is claimed.

Compiled implementation: `d171123ff6fb2f0ffde163d3702964757e4c505d`, after initial
`aeb85662c6ac3510fd459debfa91220178920136`; base
`a3a6dbedf12830c13d6e23605a538553f125a507`. The following evidence commit changes
only documentation/logs. Complete GStreamer source and existing patch provenance
remain pinned by the adapter and integration recipes.

The fresh run completed with exit 0. [Full successful stdout/stderr](validation-20260918.log)
retains every executed case, original suite total, mutation and binary hash.

| Checks | ASan/UBSan | TSan |
| --- | ---: | ---: |
| Actual registered output callback modes | 20 | 20 |
| Preceding retained-copy modes on modified sources | 25 | 25 |
| Preceding native observer modes on modified sources | 29 | 29 |
| Named call-site semantic mutations | 9 | Not repeated |
| Original HEVC parser/bitwriter/parser-element checks | 48 (17 + 1 + 5 + 25) | Not repeated |

The twentieth callback mode and the ninth mutation were added by the adversarial
review below. `flush-armed` drives a real FLUSH_START/FLUSH_STOP pair through the
framework while an arm exists and requires both allocators to be usable again;
`armed-flush-recovery` removes the fix and requires that assertion to fire, so
the regression is demonstrated able to fail rather than only to pass.

Both builds include the complete configured plugin; `ldd` checks establish that
GStreamer dependencies resolve inside that pinned build. Mutation detection
requires SIGABRT at the named assertion with no sanitizer diagnostic; build
failure, timeout and arbitrary crashes cannot pass. These are synthetic syscall,
runtime-provenance and framework-frame tests, not real HEVC decode outputs.

Local host/tool identities: Linux aarch64; GCC 16.1.1 (20260430), Meson 1.12.0,
Ninja 1.13.2, Python 3.14.7, GLib/GObject 2.88.3, libgudev 238. Existing local GLib
generator paths were supplied through the adapter's optional native file. No
dependencies were installed by this task.

Exact fresh-run command (the cached archive is independently hash-verified):

```sh
python3 experiments/hevc-reference-content/gst-callsite/tests.py \
  --keep /home/chrisk/video82-callsite-evidence-20260918/qualified \
  --archive /tmp/video-82-gst-baseline-20260918/source.tar.gz \
  --native-file /tmp/video-82-build-tools-20260918/native.ini
```

Portable reproduction omits the optional cache/native arguments and uses a new
empty destination as described in [README.md](README.md).

Additional completed checks: required installer/rebuild Bash syntax and
`bash tests/rebuild.sh`; `python3 experiments/hevc-reference-content/tests.py`
(25 groups and four mutations); Python compile; workflow YAML parsing; diff
whitespace checks excluding `*.patch` transport files. Unified-diff blank-context
lines intentionally contain a leading space; the new patch instead receives
zero-fuzz application against hash-verified complete sources in every fresh run.

The preceding integration baseline also passed 25 copy and 29 observer modes
under both sanitizer configurations plus its six existing mutations before
editing. Initial failures remain distinct: the first new fixture did not link
until its framework wrappers had default visibility; a later test exposed the
reentrant finish gap fixed in the initial implementation commit. An attempted
fresh extraction then exhausted the existing `/tmp` tmpfs. Only this task's
scratch directories were moved to persistent storage; no other task's data was
removed. The qualified run above starts fresh at the corrected source.

## Artifact identities

| Artifact | SHA-256 |
| --- | --- |
| `client-hook.patch` | `3347efbd2a3c7dbfa4c17552d7c8a2225d0e49535f7f5db76498d0136caca045` |
| `gst-callsite.inc` | `18cab04881bf0606ac6fbfbd374e8e0a9758d169029792b556bec385b2df4829` |
| `gst-callsite-native.inc` | `fb432b35f4bd852a8c7dc3cba959d2f11c1b1ca17c3f19b57f9c80870b646fa2` |
| `gst-callsite.h` | `613865f501320500f6b6b5ef368808adff23896dbd6774fabc49e23a7a786deb` |
| `tests.py` | `82a17bf58900eb6e6fea2d31695c63ab1b893f37430aff0615ca28ad4fffa0a5` |
| `callsite-model.inc` | `c8c0cb2d4c7b0ba935cff3ea2da9f232359dfbd6f649b6536f288ba44048378e` |
| ASan/UBSan plugin | `9b805837e6dbccf7bd2de0c91def735b65aae12ab176e1b3a9cec5c909984e3c` |
| ASan/UBSan call-site executable | `656de071b03f28bc26196bd622913b79fca79895023c07360dcd3a1cdd2f2dda` |
| TSan plugin | `935ccd0b9a0172a5c6e43b6f4569cf2fad55e933446d520cae441dc1078cccde` |
| TSan call-site executable | `f883d51c72af0da014e90c56dc57548b73536223fecbaa5f16f572f0cc434716` |

Hosted final-head status belongs to [PR106](https://github.com/iconidentify/omarchy-m1-video/pull/106/checks)
and its handoff; local results do not stand in for an unexecuted hosted job.
No decoder/device lease, hardware process, installation, module action, shipped
kernel patch or host configuration changed. No strict codec suite, DMA coherence,
live client playback, display or boot measurement was made. Same-run kernel joins,
selected-writer controller, full live provenance/manifest and hardware campaign
remain open in #82; driver #42's corruption correction is not claimed.
