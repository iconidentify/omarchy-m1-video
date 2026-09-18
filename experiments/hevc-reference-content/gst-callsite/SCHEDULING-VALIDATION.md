# Scheduling validation — 2026-09-18

Implementation `2d4c483c1b8d8e31607cc9a1c4cb30b908a77983`, final test source
`4e8b50937a9a614307928442b3c7ad8bc199ca66`. The evidence commit changes only
documentation/logs. Unmerged dependency PR106 is preserved at
`b1a39794d2b828ebea0633d43ac559db0a814fa7`; fetched default main was
`a3a6dbedf12830c13d6e23605a538553f125a507`.

The fresh final-source run exited 0. Its complete successful stdout/stderr is
[retained here](scheduling-validation-20260918.log). Pinned GStreamer revision
`070125524a8422e29d3b69a372ed4f62fd343ffa` and the original archive/source hashes
are verified by the existing adapter recipe, before zero-fuzz application of
the unchanged unaligned/observer/integration/callsite patches. The complete
configured plugin is compiled, not just extracted scheduling predicates.

| Executed checks | ASan/UBSan | TSan |
| --- | ---: | ---: |
| Actual registered output callback modes | 32 (19 original + 13 new) | 32 |
| Retained-copy integration modes on modified source | 25 | 25 |
| Native observer modes on modified source | 29 | 29 |
| Named semantic callsite mutations | 13 (8 existing + 5 new) | Not repeated |
| Original HEVC parser/bitwriter/parser-element checks | 48 (17 + 1 + 5 + 25) | Not repeated |

New cases cover selection and matched no-copy, incomplete plan, duplicate output,
invalid plan, wrong native/frame identity on a would-be unselected path, second
selection unmap failure/retry and admission failure, eight fresh snapshots,
published-allocation reuse refusal, caller-array mutation, canceled arm, and
three queued requests output in a different order with all-reader completion.
The fixture's twelve-allocation positive pool is explicit; reuse retains four
allocations. Neither proves late RPS_E writers are eligible in a real pool.

Both sanitizer builds verify `ldd` resolves Gst dependencies in the pinned build.
Mutation success requires compilation followed by SIGABRT at the named assertion,
without sanitizer diagnostics; compiler failure, timeout and unrelated crash are
not detections. The five new mutations bypass plan copying, all-selected result
gating, duplicate-output refusal, native frame matching and plan uniqueness.

## Reproduction and environment

```sh
python3 experiments/hevc-reference-content/gst-callsite/tests.py \
  --keep /home/chrisk/video82-schedule-evidence-20260918/qualified \
  --archive /tmp/video-82-gst-baseline-20260918/source.tar.gz \
  --native-file /tmp/video-82-build-tools-20260918/native.ini
```

Use a fresh empty destination. Optional archive/native-file arguments reuse the
original independently verified archive and already available GLib tools; omit
them for the portable recipe in README.md. No dependencies were installed.
Host: Linux aarch64; GCC 16.1.1, Meson 1.12.0, Ninja 1.13.2, Python 3.14.7,
GLib/GObject 2.88.3 and libgudev 238.

Also passed: required `bash -n` on install/uninstall/rebuild/packaging scripts;
`bash tests/rebuild.sh`; `python3 experiments/hevc-reference-content/tests.py`
(25 groups plus four existing mutations); runner `py_compile`; `git diff --check`
against the stacked dependency. No transport patch changed in this delta.

The first local run passed 31 modes per sanitizer and all 13 mutations. Review
added the genuine queued-reader/output-order permutation case; the fresh final
run above repeats everything with 32 modes. No local failed test was suppressed.

Initial hosted head `2d4c483` had an executed failure in the unchanged VA observer
job, [run 35390394186, attempt 1](https://github.com/iconidentify/omarchy-m1-video/actions/runs/35390394186/attempts/1).
Its pinned driver suite passed 191/192; `hwguard --self-test` received SIGINT in
`Lease.acquire()`'s `fsync`, before `run_guarded()` installs its handler. At exact
driver pin `c77e7b566f7baf9c7a2aad797e62c9aa578d9687`, the test sends SIGINT after
a fixed 0.4-second sleep, not a readiness handshake. This is an observed test
startup race, not a failure in the Gst scheduler and not a claimed guard fix.
The failed job was rerun without code/test changes; retain both attempts. Final
head/attempt results belong to [PR107 checks](https://github.com/iconidentify/omarchy-m1-video/pull/107/checks)
and the issue handoff; local passes are not substitutes for pending hosted jobs.

## SHA-256 identities

| Artifact | SHA-256 |
| --- | --- |
| `gst-callsite.inc` | `dba401886a6f7f48a40d9e2252ca52506b05f50ceba6f9f04e387cfdfdb65a6d` |
| `gst-callsite-native.inc` | `ff0bd9eabe128f85b684f5a6a035af1a54281951a77f14aedc6ed95fb3b277dd` |
| `gst-callsite.h` | `e95be9f7106b7322af9babee7f86d88dd553e1a5fb8ca3b2b7ca98a6eff69ac6` |
| `callsite-model.inc` | `4d832fbc05be64955f53d5844b734c32c5407e99e97133d32ca856ec6c6dcb67` |
| `tests.py` | `29e16e500e5faece5c172f6b6dfc79ba22db227f283df51fb072a8c6eb419356` |
| ASan/UBSan plugin | `ddfe69c8982bb57937955096e4b7f6361281f63bb2932de65ea014e0a63670b2` |
| ASan/UBSan callsite executable | `a3c8f899ef86051b2a58a60c21f5e581deb6655b6b40dffed54da68e483a2592` |
| TSan plugin | `9a082abce1dc418274dee188fd55d20be1fbafef59fbff464d747188466540db` |
| TSan callsite executable | `58de26984ad0f912387d8fc14e113bef5d5dfab76a45b3f0d1d1d554d645c4c2` |

No hardware, device lease, installed software, module, shipped kernel patch or
host configuration changed. This is fake V4L2/runtime evidence and CPU memfd data,
not decoded HEVC outputs, DMA coherence, display, boot or noninterference evidence.
The VA source/API is unchanged and is covered by the existing hosted jobs, not a
new local VA build in this slice. Same-run kernel binding, late-writer ownership,
full provenance/manifest, VA production callback and guarded campaign remain
open. Review is implementation-agent self-review, not independent approval.
