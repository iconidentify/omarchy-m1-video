# GStreamer selected-allocation eligibility

AI-assisted implementation for
[#124](https://github.com/iconidentify/omarchy-m1-video/issues/124), under the
selected-output campaign in
[#82](https://github.com/iconidentify/omarchy-m1-video/issues/82). This additive
patch applies after the observer, retained-copy integration, selected-output
call-site and runner patches. It is an offline experiment, is not installed by
the repository and remains off unless the private runner properties are set.

## Invariant

Publication is permanent for an allocator-owned capture allocation. Releasing
and reacquiring a buffer never clears `observer_published`, so a late selected
frame cannot safely use the ordinary recycled pool. The runner therefore parses
and freezes its complete selector list during allocation negotiation and adds
exactly one source allocation per selected frame to the decoder's ordinary
DPB/downstream requirement.

While the runner is armed, the real source allocator applies two rules:

- selected frames may take only a free allocation that has never been
  published, mapped or shared; and
- nonselected frames prefer a published allocation. They may take an
  unpublished allocation only when the number of free unpublished allocations
  is strictly greater than the number of selected frames not yet allocated.

The selected allocation is committed once for its exact
`system_frame_number` before request creation. Duplicate selection, a
pre-supplied output buffer, exhaustion, a published-only pool, malformed or
late configuration, or a flush while waiting fails the run. A selected acquire
never waits: an outstanding ordinary allocation will be published before it
returns and cannot become eligible again. An ordinary acquire may wait for a
published allocation without consuming the finite reserve.

The patch does not clear publication state, invent alias release, alter an
allocation generation, treat a capture index as writer identity, or change the
default-off allocator path. The existing request/allocation/writer/completion
receipt, bounded pre-publication observation, normalized result and same-run
supervisor remain unchanged.

## Offline reproduction

From the companion repository root:

```sh
python3 experiments/hevc-reference-content/gst-eligibility/tests.py \
  --keep /tmp/hevc-gst-eligibility
```

The destination must be empty. `--archive` accepts the hash-verified pinned
GStreamer archive, and `--native-file` accepts the same optional GLib generator
override as the preceding Gst suites. The test applies the complete patch
stack with zero fuzz, builds the full plugin and real H265 class under
ASan/UBSan and TSan, and repeats all preceding observer, retained-copy and
selected-output call-site modes.

The central case sends twelve nonselected frames through the real source pool,
request queue and output callback. Every one reuses the same already-published
allocation. A late selected frame then receives a distinct never-published
allocation and completes the unchanged normalized runner result. Additional
cases cover default-off FIFO order, selector reordering and uniqueness,
pre-supplied buffers, reserve exhaustion, flush wakeup, map/share publication,
incomplete output and pre-allocation configuration refusal. Six named semantic
mutations must compile and abort at their intended assertion.

The fixture models V4L2 ioctls with CPU memfds. It proves the bounded allocator
policy and production call path, not a hardware decode or live DMA visibility.
No live target, corpus, loaded dependency/module identity, manifest approval,
installation, support-count increase, boot result or noninterference result is
established. Parent #82 and driver #42 remain open for reviewed manifest
admission and the guarded hardware campaign.
