# M1 playback delivery — current plan

Owner-approved reset, 2026-09-20. AI-assisted maintainer planning.

**Next milestone: qualify one reproducible M1 playback candidate against the
installed baseline, then make an explicit packaging decision.** A merged PR,
larger test count or completed research ticket is not the delivery milestone.
This page replaces the old contributor-wave priorities. The
[live scoreboard](https://github.com/iconidentify/libva-v4l2_request/issues/7)
records current results; dated evidence remains immutable.

**First result, 2026-09-20:** the [paired comparison](evidence/m1-delivery-2026-09-20/README.md)
passed 80,640 exact frame comparisons and 1,680 retained-image checks. Installed
and C1 also passed the selected OpenGL mpv smoke, with identical rendered-window
captures. Chrome, sustained playback/recovery, full strict-set preservation and
packaging remain the next gates. C1 stays uninstalled.

## What the reset changes

The work has produced real parser/lifetime fixes, exact hardware comparisons,
resource and concurrency evidence, and a selected FFmpeg HEVC improvement.
Reviews also caught errors in our tests and experimental tooling before they
could support stronger claims. Preserve that work and its contributor credits.

Delivery has lagged behind integration: the installed package still points to
an older source; ordinary browser/player behaviour remains unqualified; and
repeated observer/tooling work has not yet explained the remaining corruption.
Accumulated handoffs made historical states look current. The recent desktop
freeze also exposed a shared-build coordination problem: memory pressure was
recorded, but the forced restart's cause remains unproven.

Measure progress by a reproducible playback result, a defect removed or a clear
stop decision. Keep one current scoreboard, bounded builds and the work order
below; avoid growing the task graph before using what is already implemented.

## One candidate

| Component | Installed baseline | Candidate C1 |
| --- | --- | --- |
| VA driver | `1.3.r11-2`, package source `db3014f9499694c6f186af7e023de07bd5bc3564` | Separate release build of `5b5046cbda6892f4a63df0015857a80bd42c17cf` |
| Kernel | `linux-asahi 7.1.13.asahi3-1`, ordinary installed module | Same kernel/module; no experimental recorder or allocator substitution |
| FFmpeg | `2:9.0.1-4` | Same installed client |
| mpv / graphics | `1:0.41.0-6`, Mesa `26.1.8-1`, OpenGL | Same client and graphics stack, disposable command-line settings |
| Chrome | `152.0.7977.64-1`, normal sandbox | Same browser, separate test profile when qualified |

C1 is **unpackaged and unqualified for everyday playback**. Select its driver
only for the test process. Capture actual binary hashes and runtime identities
for every run; the vendor string still says r11 and cannot distinguish source
revisions. The final package and its exact dependencies require their own checks.

The separately qualified FFmpeg parameter-set patch improves HEVC 144/147 to
145/147. Keep that as a subsequent client integration decision; it is not silently
included in C1. Experimental kernel repairs likewise remain separate.

## Scoreboard

| Outcome | State at reset | Next evidence / owning ticket |
| --- | --- | --- |
| Existing r11 hardware pass sets | Installed, measured historical baseline | Preserve exact vector sets on C1; do not substitute eligible-subset percentages |
| Later userspace lifecycle/error fixes | Merged; selected earlier builds tested | Rebuild C1, compare baseline/candidate and record packaging gap |
| Decode, drain, seek-to-start, reopen | Paired installed/C1 comparison passed; exact evidence linked above | Broader legal format changes and failed-transition isolation under [driver #45](https://github.com/iconidentify/libva-v4l2_request/issues/45) remain open |
| Actual mpv/Chrome playback and recovery | Not qualified | [mpv #21](https://github.com/iconidentify/omarchy-m1-video/issues/21), [Chrome #22](https://github.com/iconidentify/omarchy-m1-video/issues/22), [fallback #49](https://github.com/iconidentify/libva-v4l2_request/issues/49) |
| HEVC parameter-set fix | Verified selected client, not packaged | Separate package/client decision; [evidence](evidence/issue15/hevc-parameter-sets-2026-09-19/README.md) |
| Remaining HEVC corruption | Experimental investigation; still wrong | [#128](https://github.com/iconidentify/omarchy-m1-video/issues/128) campaign, then a decision under driver #42 |
| Boot/reset confidence | Cause unresolved; four initial matrix attempts clean | [#13](https://github.com/iconidentify/omarchy-m1-video/issues/13); no stable boot-enabled claim |

## What C1 must demonstrate

1. Preserve all existing strict AVC/HEVC/VP9 passes, with original denominators,
   expected rejections and wrong-output cases still visible.
2. Repeated decode/drain/seek/reopen preserves exact pixels, delayed output and
   bounded resources. The first [paired test plan](M1_PLAYBACK_PLAN.md) covers a
   narrow existing workload, not all of #45.
3. On explicitly selected Chrome and mpv rows: actual hardware selection,
   correct displayed output, pause/seek/restart and one stream surviving another
   closing. Browser tests retain the normal sandbox; mpv retains OpenGL.
4. Unsupported/damaged input and allocation failure have an observed, usable
   client outcome. A driver error alone does not prove browser fallback. Do not
   deliberately replay a known firmware wedge without a concrete fix.
5. Produce an exact package/build manifest, rollback instructions and a release
   decision. Outstanding corruption/reset faults block stable claims for affected
   rows. Full [release #27](https://github.com/iconidentify/omarchy-m1-video/issues/27)
   and the driver support contract remain authoritative.

## Work order and stop decisions

- First: paired C1 playback/lifecycle evidence, then a concrete mpv/Chrome result.
  Separate the deliverable from the broader format-transition matrix. Do not make
  a narrow client experiment wait for unrelated container/platform coverage.
- Second: finish one freshly reviewed HEVC observer attempt under #128's existing
  ownership. Its output must identify the next discriminating corruption
  experiment. If instrumentation fails again, preserve the failure and review
  the approach before expanding it. No automatic retries or new framework.
- Defer new owner-directed work on additional platforms, interlacing, advanced
  profiles, Vulkan and performance tuning until the C1 decision. Existing
  contributor claims and evidence remain respected; this is not a cancellation.

Every active handoff names the user-visible problem, exact candidate, next
decisive test, result, blocker and next owner. Report installed / verified candidate /
experimental / blocked separately. Update this current view in place instead of
prepending another contradictory handoff. Preserve history in dated evidence.

## Lab discipline

Use [tools/bounded-build](../tools/bounded-build) for local builds and CPU tests on
the shared desktop. One fixed user-service name prevents overlapping cooperating
jobs; limits are one CPU, 1 GiB memory pressure threshold, 1.5 GiB hard memory cap,
64 tasks and a 30-minute deadline. The wrapper requires 10 GiB disk headroom and
3 GiB available RAM before starting, and puts temporary files on disk.

Pass one build/test worker (`-j1`, `--num-processes 1`) to the underlying tool.
Coordinate hardware windows separately and finish builds before acquiring the
decoder. Never delete retained evidence or raise limits just to manufacture a
pass. A constrained or aborted run is recorded as incomplete.
