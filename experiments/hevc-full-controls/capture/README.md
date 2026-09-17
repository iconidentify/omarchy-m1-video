# Complete paired control campaign — 2026-09-17

Eight short M1 workloads: B/E × VA/GStreamer × ioctl tracing off/on. Every run
completed 300 frames, actual child exit 0 and guard `ok`, with idle final state and
no new decoder fault. The original installed module stayed loaded throughout;
its installed hash and loaded build-ID note were rechecked. Build-ID attribution
does not hash resident kernel text. No reload, installation or reboot occurred.

| Result | VA | GStreamer |
| --- | --- | --- |
| RPS_B complete output | Exact, `6d1ed392b067050ebd3a24a37281da03` | Same |
| RPS_E complete output | `b09ac8e0bd31a96d8354505d7c2ebdd5`, 26 wrong outputs | `53952960ec7512d9cb64f8c7020ece03`, 25 wrong outputs |
| First bad E decode | Picture 31 / POC31 | Picture 29 / POC28 |
| Tracer off/on | Every frame equal | Every frame equal |
| Encoded input versus other client | All 300 picture payloads equal, both vectors | Same |

The [summary](summary.json) retains complete wrong sets and output/decode
associations. These results preserve the prior accepted wrong sets exactly; no
codec support improves from this measurement.

## What changed at the ioctl boundary

VA submits PCM values 255/255/253 on pictures 2–300 with PCM disabled. The actual
returned SPS contains zero in each field. The pinned kernel's
[`V4L2_CTRL_TYPE_HEVC_SPS` validation](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/v4l2-core/v4l2-ctrls-core.c#L1214)
performs exactly this correction. The provisional pre-call PCM hypothesis is
therefore withdrawn; it does not justify another hardware trial.

PPS returns also clear loop-filter-across-tiles because tiles are disabled. After
these observed adjustments, non-reference payloads differ only as follows:

| Field | Observation | Source relevance in this capture |
| --- | --- | --- |
| SPS maximum reorder pictures | VA 0, Gst 7, all pictures | No read by the pinned AVD HEVC command builder; not proof that all kernel layers ignore it |
| PPS uniform spacing | Set only by Gst; tiles disabled | The [tile path](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-hevc.c#L1172) uses this only with tiles enabled |
| I-slice CABAC/MVD/collocated flags | Nine I pictures per vector, including E CRA32 | The [motion path](https://github.com/AsahiLinux/linux/blob/94fb23346d522edf53722357c426a3e58030beea/drivers/media/platform/apple/avd/avd-hevc.c#L569) returns before these reads for I slices |

Weights, scaling matrices, QP/deblock offsets, NAL/POC/bit-size/data offsets and all
other compared non-reference returned fields agree. Mode observations are
FRAME_BASED / START_CODE_NONE on both clients (VA successful set-return, Gst get-return).
All 300 pre-QBUF encoded payload hashes and lengths agree for both vectors.
Raw DPB/list slot ordering remains in the full artifacts; all logical active slice
reference writers match. Source interpretation is not a firmware-contract proof.

## Published evidence and reproducibility

- `B/E-va/gst-controls.jsonl`: four complete 300-picture control sets, with returned
  values, exact submitted-field differences and explicit SPS persistence origin.
- `*-refs.jsonl`, `*-association.json`: complete request/reference and same-run
  output association. Both VA ioctl-derived reference sets also match the same-run
  native driver reftrace under the accepted driver checker. Output association
  uses actual successful child/count evidence, not the debug log alone.
- `*-input.json`: observed modes and bound input-buffer byte lengths/SHA-256.
- [runs.json](runs.json): all eight actual decoder statuses, redacted commands,
  unique guard records, complete per-frame hashes and observed whole-output MD5.
- [provenance.json](provenance.json): selected userspace/source/tool/device/module
  identity, unchanged fixed boundary and final state. The guard checkout differs
  from the explicitly selected userspace build; both are recorded.
- [private-artifacts.json](private-artifacts.json): retained raw-source digests and
  byte extents. These cannot independently authenticate private captures. Raw media,
  ioctl addresses, timestamps, FDs, PIDs and journals remain private.
- [files.json](files.json): complete public-input digest inventory; a reproducibility
  check, not a signature or an independent witness.

Run `python3 experiments/hevc-full-controls/report.py --verify` from the repository
root. The report verifies run/source identity, complete extents, prior/off-on frame
equality, guards, payload shape/association, logical references, input hashes and
the precise observed differences. Public symbolic writer ordinals do not reconstruct
private timestamps or prove physical-memory uniqueness.

The fixed journal boundary remains `2026-09-17T17:09:48.295096+00:00`, inherited from
the preceding accepted healthy campaign rather than advanced past a new error.
Six historical fault records stay in custody; none occurred since that boundary.
No decoder lease or worker remains. The tracer returns a raw wait status, so the
inner wrapper's actual waited child status is authoritative; an offline exit-23
counterexample checked this before hardware execution.

## Remaining uncertainty

Successful ioctl return data is not a snapshot of the copied controls at the later
job hook. Pre-QBUF bytes are not proof of subsequent cache/DMA/firmware reads. The
remaining emitted commands, compressed-reference contents and internal decoder
state are unmeasured here. Matching source predictions cannot prove the shared
firmware contract correct. This is one M1/two vectors, not full-suite, concurrency,
soak, throughput, boot or other-platform qualification.

Research #67 can close after review/merge; driver #42 keeps all actual-fix and
qualification requirements. #66 remains a contributor-owned command coverage task.
AI maintainer self-review; no independent kernel review claimed.
