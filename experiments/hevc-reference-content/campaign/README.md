# Campaign controller

Plans and reviews the eight guarded workloads in [CAMPAIGN.md](../CAMPAIGN.md)
and **refuses to execute any of them**. This closes the "no campaign controller"
gap in that plan; it does not make the campaign runnable, and it is not hardware
authorization.

```sh
python3 experiments/hevc-reference-content/campaign/controller.py \
    --pool-size 16 --e-frames 2 5 9 --b-frames 3
python3 experiments/hevc-reference-content/campaign/tests.py
```

Planning and review are offline and side-effect free: no device is opened, no
lease acquired, no module loaded, no client started.

The controller predates the FFmpeg/VA call site. Its `frames` values and
publication-window checks describe Gst `system_frame_number`s; they are not VA
output ordinals. Before this planner can become a runner, its VA workloads must
gain distinct output-ordinal selection, `threads=1`, one application owner for
send/receive/finish/close, and the call site's fatal-cleanup handling. Passing the
same integer tuple to both clients is only matrix planning, not a valid VA arm.

## What it checks, and why each check exists

Every rule is a documented property of the merged call site or a budget from
CAMPAIGN.md, not invented policy. The point is that a plan fails review at a
desk instead of failing partway through a hardware window.

| Check | Source |
| --- | --- |
| Exactly the eight `{B,E} × {VA,Gst} × {off,on}` workloads, no duplicates | CAMPAIGN.md |
| Copy-off controls select nothing; off and on differ only in the copy | CAMPAIGN.md |
| 1–8 distinct `system_frame_number`s per arm | `gst-callsite.h` |
| Selections land inside the publication boundary (`pool_size`) | `gst-callsite.h`, SCHEDULING.md |
| No in-band parameter-set change between arm and the last selected output | gst-callsite README |
| Three selected E writers and one B control per client, eight slots total | CAMPAIGN.md |
| 8 snapshots, 184320 bytes each, 1474560 total | CAMPAIGN.md |
| A fresh decoder element per observation | gst-callsite README |
| `arm()` on the streaming owner thread | gst-callsite README |
| Any `GST_FLOW_ERROR` in an armed window counts as observation failure | gst-callsite README |
| Finish the arm before a flush or state change | gst-callsite README |
| Healthy idle, no foreign client, journal boundary, module loaded, refcount 0 | CAMPAIGN.md |

`validate_plan()` returns every reason a plan is unfit rather than the first, so
a review sees the whole set; fixing one error per attempt would waste a hardware
window each time.

## Why `execute()` raises

`Controller.execute()` validates the authorization, the plan and the
preconditions, and then raises `AuthorizationError` unconditionally. The campaign
still needs a reviewed deployment manifest, full client/dependency/corpus
attestation and an actual same-run kernel command/reference join, none of which
exist. Keeping the refusal in code rather than in prose means a later caller
cannot miss it, and the refusal is covered by a test that fails if it is removed.

`Authorization` is a record that external approvals exist — operator, guard lease,
approved manifest digest, issue authorization, hardware window. The controller
never constructs one. Holding an `Authorization` is not itself permission to run,
and no field of it is checked against anything real; it names approvals for the
evidence record.

## Limits

This is planning and refusal only. It does not drive a decoder, allocate a
request, arm a call site, collect evidence, compare off/on outputs or restore a
machine. It cannot detect a plan that is internally consistent but wrong about
the stream — frame numbers, pool size and parameter-set positions are inputs, and
CAMPAIGN.md requires selecting writer identities from same-run records rather
than assumed POC or index mappings. A plan passing review says only that it
violates none of the constraints above.

Tests are mutation-checked: removing the publication-boundary check, the
parameter-set-window check, the fresh-element check, the copy-off selection rule,
the slot-shape check or the execution refusal each makes a named assertion fail.
