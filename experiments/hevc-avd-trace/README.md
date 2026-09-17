# Experimental HEVC AVD recorder (offline preparation)

Refs #62 and parent #61. This is an experimental candidate, not an installed patch
or a hardware result. The shipped 15-patch stack and codec pass counts are unchanged.

The implementation follows [the accepted source map](../hevc-avd-map/README.md)
and [instrumentation plan](../hevc-avd-map/INSTRUMENTATION.md). It will use a
root-only, default-off debugfs recorder, explicitly armed for one opener process,
with a fixed record capacity and one selected context. Full 300-picture writer
and completion history accompanies command detail for pictures 24–34. Snapshots
are readable only after context teardown; failed, incomplete or overflowing runs
are invalid evidence. Kernel pointers, DMA addresses and media are never exported.

The patch is applied only to an isolated copy of Asahi Linux
`94fb23346d522edf53722357c426a3e58030beea` after the unchanged shipped patches.
Offline tests and a matching-header build must precede any execution proposal.
Parent #61 retains separate informed experimental-module authorization, saved
work, closed apps, a guarded exclusive decoder window, output comparison and
measured-result acceptance. No loading, installation or reboot occurs here.

Implementation and validation are in progress. AI-authored contribution;
Asahi Linux source authorship and licences are preserved in patch context.
