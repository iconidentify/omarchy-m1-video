# Offline validation — 2026-09-19

AI-assisted maintainer execution and adversarial self-review; no independent
review or hardware qualification is claimed. The reviewed tree is based on
`b3da53fd8b4cf5d118fd956455c392da759ce7ed`.

A fresh hash-verified GStreamer source extraction received the complete observer,
integration, call-site, runner and eligibility stack with zero fuzz. The complete
configured `v4l2codecs` plugin and real H265 class built under both sanitizer
configurations. The final command exited zero:

```sh
python3 experiments/hevc-reference-content/gst-eligibility/tests.py \
  --archive /tmp/omarchy-120-gst-source/source.tar.gz \
  --keep /tmp/omarchy-124-eligibility-final \
  --native-file /home/chrisk/src/video-120-gst-runner-20260919/.local-validation-tools/native.ini
```

The native file selected `glib-mkenums` and `glib-genmarshal` generated from the
official GLib 2.88.3 source already used for local validation. It is disposable
host state and is not part of the repository. No package was installed.

| Executed checks | ASan/UBSan | TSan |
| --- | ---: | ---: |
| New allocation-eligibility modes | 10 | 10 |
| Existing selected-output call-site modes | 33 | 33 |
| Existing retained-copy integration modes | 25 | 25 |
| Existing native observer modes | 29 | 29 |
| Named eligibility semantic mutations | 6 | Not repeated |

The late-selection success case performs twelve real request/output cycles on
one published allocation, then requires frame 31 to receive a distinct
never-published allocation and produce the unchanged normalized result. Other
new modes cover default-off FIFO order, two-selector reordering, duplicate
allocation, pre-supplied output, fully published shortage, blocked-wait flush,
map/share stickiness, incomplete output and incomplete pre-allocation config.

Mutations remove reserve sizing, published-first reuse, unpublished-only selected
acquisition, strict remaining-reserve accounting, selector allocation uniqueness
and default-off isolation. Every mutant compiled, then terminated with `SIGABRT`
at its named assertion without sanitizer output, timeout or unrelated crash.

The first TSan execution found a flush-flag race in the new reserved-wait path.
After making the flag explicitly atomic, a new source extraction repeated the
entire matrix and exited zero. Python bytecode compilation and `git diff --check`
also pass.

## Environment and identities

Host: Linux aarch64; GCC 16.1.1 (20260430); Meson 1.12.0; Python 3.14.7;
GLib/GObject 2.88.3; libgudev 238. GStreamer revision:
`070125524a8422e29d3b69a372ed4f62fd343ffa`.

| Artifact | SHA-256 |
| --- | --- |
| Pinned source archive | `1def36bd4c68f13cb731740d0cd2697d858c073e674ef54726e97ee245639a44` |
| `gst-eligibility.patch` | `f6f50f2bcb43442e65791c752c4e36ccd824c5c8b7b43d25d6f5bd7798eb4237` |
| `eligibility-model.inc` | `61725c1432cda4d94ef6ea4672bbcf2d588e545f0bf4159ec72807e61f0d4eaa` |
| `tests.py` | `97fdb7d12ef38a3a1993aa507c8557399e9efb4e7c3d8e08584e016e9f995894` |
| ASan/UBSan plugin | `591ccfc671e82db32ede3fc689772873ed18c21788fbbb4a3964395987c1fb02` |
| ASan/UBSan eligibility fixture | `124cf7cf32926b395d03c4545d6fc052f44a9c8c74b6018232762f04fbc65758` |
| TSan plugin | `f2e0cc61380fa47d81d53632715993270676338ad32b7289df6e488b244250cb` |
| TSan eligibility fixture | `9707f56f8702bf19fed9cdc17f7375b8614a71c321507cd1bb44bcf96a305dc7` |

Binary identities are sanitizer/toolchain-specific evidence, not release
artifacts. The run changed no hardware, installed software, decoder module,
package, boot or persistent system configuration. It does not establish a live
target, DMA visibility, corpus/dependency manifest, hardware result or support
count. Parent #82 and driver #42 remain open.
