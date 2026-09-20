# Offline validation — 2026-09-19

AI-assisted maintainer execution and adversarial self-review; no independent
review or hardware qualification is claimed. Implementation
`75b9cc59fd1876077bce4759914b9a48f3a9e6a1` was tested from base
`cc787997ba9a744cc95cdccb33d424631c3377ed`.

A fresh hash-verified GStreamer source extraction received every dependency and
the runner patch with zero fuzz. The complete configured v4l2codecs plugin and
real H265 class were built. The final command exited zero:

```sh
python3 experiments/hevc-reference-content/gst-runner/tests.py \
  --archive /tmp/omarchy-120-gst-source/source.tar.gz \
  --keep /tmp/omarchy-120-gst-runner-exit0 \
  --native-file /home/chrisk/src/video-120-gst-runner-20260919/.local-validation-tools/native.ini
```

The native-file path was disposable local validation state and is not part of
the repository. It selected `glib-mkenums` and `glib-genmarshal` generated from
the official GNOME GLib 2.88.3 tag because this host's pkg-config metadata named
missing executables. No package or dependency was installed.

| Executed checks | ASan/UBSan | TSan |
| --- | ---: | ---: |
| Real Gst runner/result modes | 20 | 20 |
| Existing selected-output callsite modes | 33 | 33 |
| Existing retained-copy integration modes | 25 | 25 |
| Existing native observer modes | 29 | 29 |
| Strict collector/refusal checks | 12 | Not repeated |
| Named runner semantic mutations | 6 | Not repeated |

Runner cases cover default-off, copy off/on, short writes, partial/duplicate/
late/malformed/mutable configuration, arm refusal, the real streaming-owner
vfunc, downstream failure, incomplete output, retained cleanup quarantine,
write/sync/close failure, exclusive collision and deterministic JSON. Successful
runs leave exactly the final report; unsuccessful runs leave no report or temp
file. Collector cases reject raw/duplicate fields, selector mismatch, malformed
or zero identity, multiple records, invalid expectations, failed process,
symlink, multiple hard links and exposed permissions, then exercise the CLI.

Mutations disable the real arm, move it after bitstream allocation, skip the
post-output runner, skip finish-before-publish, make collision publication fail
open, and replace a normalized field with `raw`. Every mutant compiled, then
terminated with `SIGABRT` at its named assertion without sanitizer output.

Additional checks passed: Python bytecode compilation; workflow YAML parsing;
required installer/rebuild/package Bash syntax; and `git diff --check`. The
hosted workflow adds a public `gst-runner` job using the normal GLib development
tools and a fresh pinned-source build.

## Environment and identities

Host: Linux aarch64; GCC 16.1.1 (20260430); Meson 1.12.0; Python 3.14.7;
GLib/GObject 2.88.3; libgudev 238. GStreamer revision:
`070125524a8422e29d3b69a372ed4f62fd343ffa`.

| Artifact | SHA-256 |
| --- | --- |
| Pinned source archive | `1def36bd4c68f13cb731740d0cd2697d858c073e674ef54726e97ee245639a44` |
| `gst-runner.patch` | `40fe30576eacaa469793743469b9adbad7a003728197f41e4ea9a2c88f9e10d5` |
| `gst-runner.inc` | `ccf13bfef9437d3795c8fbac5bccb994ebf1e17601b1aeeef2fdb31ca0c237e1` |
| `gst-runner.h` | `b00803b2b7b93efef9604f630af319ebbd0f6944f7bd403990282b1b9ea2e5d4` |
| `collector.py` | `3e53da7acb341ac08a1639a6f20b46d18dfa257b6d1b8ac349c93fef8b4e43ce` |
| `runner-model.inc` | `8776617e25359172c78856b38c892d6e9c57adf5f90cf3779ee7e2a6c050a6e8` |
| `tests.py` | `b98a54c98dbc570779b2b44d3621f93dc8dfb57559459fbfd362037bfd59be29` |
| ASan/UBSan plugin | `ab2cb54e351d0f0935c5befecd8527c1a7be1cdd14f7f8710ae7ce7d08ebe9b6` |
| ASan/UBSan runner fixture | `3c1927aef6a6e1cf3179ae75ef803cf233f4622efae075c6ba8b84527cfa4415` |
| TSan plugin | `361d5682d427628c883b4c08747e6d10ad7641d3fe5fdab5ff3f33d708e4a17d` |
| TSan runner fixture | `5eaff419f7f0cb7f45e2971a59465857290d968979268bea4826897cec4f7494` |

The binary identities are sanitizer/toolchain-specific evidence, not release
artifacts. These are synthetic syscall/runtime/framework checks, not decoded
HEVC output, DMA visibility, cache coherence, display, boot, performance or
noninterference measurements. No hardware, installed software, module or system
state changed. Parent #82 must add the same-run supervisor/kernel join before a
guarded campaign can promote this result; driver #42 remains open.
