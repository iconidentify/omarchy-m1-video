# Paired full HEVC controls (work in progress)

Owner-authorized research for companion #67 / driver #42. Eight guarded M1 runs
completed on the unchanged original installed module: 300 frames per run, all
actual decoder exits and outer guards successful, no new faults, final idle.
Ioctl tracing preserves every prior output hash; RPS_B is exact, RPS_E retains
26 wrong VA /25 wrong GStreamer outputs. This does not fix the corruption.

Full metadata normalization and review are in progress. Raw ioctl traces contain
private media/addresses and remain outside this repository. Existing accepted
reference captures and the independently claimed #66 source map are untouched.

A preliminary difference is PCM values: VA sends 255/255/253 versus Gst zero
with PCM disabled. The AVD source packs those fields into a word regardless of
the PCM-enable bit. It also occurs in correct RPS_B and is not established as a
cause. Remaining controls must be checked before a discriminating experiment.

AI maintainer self-review; no independent kernel review claimed.
