# Paired HEVC command capture — 2026-09-17

AI-generated measured report and maintainer self-review; no independent kernel
review claimed. This completes the planned observation, not the HEVC correction.

The scheduled reboot completed with an orderly prior shutdown. The new boot's
original module build-ID and installed hash matched. A separate finite module-only
probe loaded the corrected candidate, verified both default-off endpoints, then
unloaded it and restored the original. It opened no decoder and ended fault-free.
The earlier [failed attempt](../failed-attempt-2026-09-17/README.md) stays preserved;
its candidate is withdrawn. Its Oops is not relabeled as a healthy run.

The fresh eight-run campaign then completed on corrected module SHA-256
`7a00ffa548e89d4316eb2b1454c7e153128906f099729efb58b77c26fadcdf02`.
One exclusive guard covered the entire temporary swap, eight serial workloads and
healthy-idle restoration; each decoder also had a finite inner deadline. Ioctl
tracing was enabled in both modes; off/on refers to both kernel recorders.
All actual decoder exits and the outer guard were zero/success. No timeout, foreign
client, stuck task, missing record or new kernel fault occurred. The original
module was restored and its loaded build-ID/installed hash verified afterward.

| Vector / client | Frames per run | Wrong outputs | First bad decode picture / POC |
|---|---:|---:|---|
| RPS_B / VA-API | 300 | 0 | none |
| RPS_B / GStreamer | 300 | 0 | none |
| RPS_E / VA-API | 300 | 26 | 31 / 31 |
| RPS_E / GStreamer | 300 | 25 | 29 / 28 |

Every individual off/on hash equals its partner and the accepted prior frame
hash. `runs.json` and `summary.json` retain the complete wrong sets, not just totals.
The eight runs total 2,400 frames. Four paired on captures retain 1,200 complete
writer/completion histories, 44 detailed pictures (24–34 in each), all explicitly
serialized controls and 1,756 selected command words.

## Finding

Every copied field matches the successful ioctl-returned control from that same
run and picture. All selected command words equal the actual pinned C's output.
The full selected sequence also matches across VA and GStreamer for every paired
window picture, as does the logical reference/motion projection. All 300 submitted
encoded-input hashes per vector match across clients and modes.

The clients still differ in copied reorder metadata, inactive uniform-spacing
flags, DPB-list slot numbers and some I-slice flags. These differences remain
visible in `summary.json`; their logical references agree and the observed selected
command words are identical. Thus this is not a claim that all raw controls match.
Live vectors have scaling disabled and default/skipped weight paths; weighted and
scaling-list interior coverage remains offline evidence, not a live-vector result.

RPS_E corruption is unchanged. This rules out an observed mismatch between the
same-run controls and the measured source-construction path. It does **not** prove
the shared firmware contract, later DMA reads, compressed-reference contents or
firmware state. The next bounded investigation is compressed-reference buffer
contents/lifetime and DMA/cache handling around CRA and the first corrupt jobs.
Do not retry the already-rejected PCM or reference-order permutation hypotheses.

## Reproduce

Build the oracle from the pinned primary sources using the commands in
[the command-recorder instructions](../../hevc-avd-command-trace/README.md), or follow
`.github/workflows/hevc-avd-command-capture.yml`. Then:

```sh
export HEVC_REFTRACE_CHECKER=/path/to/hash-matched/hevc-reftrace-check.py
python3 experiments/hevc-avd-command-capture/campaign-report.py --oracle /path/to/oracle/compiled --verify
python3 experiments/hevc-avd-command-capture/report-tests.py --oracle /path/to/oracle/compiled
```

The report checks file inventories, actual statuses, lease/run/source associations,
all frames and wrong sets, complete returned controls and output associations,
paired reference-history symbolic replay, every copied field and the entire
selected word sequence against pinned C. Mutation tests refresh inventories before
changing child status, lease, frames, windows, actual words, copied controls,
recorder error, holder state, restoration, context and writer identity; each must
still be rejected by a semantic check.

Public files contain metadata only. Raw ioctl traces, output images/media and
raw reference timestamps remain private, with digests for provenance. Symbolic
replay checks consistency; it cannot independently authenticate private captures.
No full-suite, concurrency, performance, boot-stability or wider-device qualification
is claimed. HEVC remains 144/147; driver #42 retains the correction and release gates.

The bounded next research leaf is [companion #77](https://github.com/iconidentify/omarchy-m1-video/issues/77):
audit compressed-reference memory ownership/ranges and design a safe content
observation. It can be done offline from the published data and pinned sources.
It includes explaining VA's DMABUF length 368128 / MV offset 360960 versus Gst's
MMAP length 345600 / MV offset 338432, with shared compressed-region layout and
MV size 7168. Different padding/tail placement is an observation, not a proved bug.
