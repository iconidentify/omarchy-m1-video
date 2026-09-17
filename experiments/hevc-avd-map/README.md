# HEVC references through the AVD command builder

AI-authored offline research for [companion #58](https://github.com/iconidentify/omarchy-m1-video/issues/58)
and [driver #42](https://github.com/iconidentify/libva-v4l2_request/issues/42).
This branch is a work in progress. `model.py` predicts a bounded subset from the
accepted 300-picture RPS_B/E metadata. It does not capture firmware instructions,
execute the decoder, or establish a corruption fix.

The source map pins the public capture files, trusted external checker, kernel
sources and all 15 unmodified shipped patches. `avd-bits.h` is a credited subset
of the pinned kernel instruction definitions for independent C parity checks.
The original captures remain unchanged.

The model preserves unknown inputs: slice POC is absent from the normalized trace,
as are dependent-slice/CABAC/MVD flags, merge-candidate count, addresses, allocated
plane length and negotiated capture dimensions. Conditional header words assume
slice POC equals decode POC; they are explicitly labeled. Motion state follows
earlier buffer writers, while actual kernel timestamp lookup remains unobserved.

Required output: full-history comparison, a readable window around pictures
24–34, negative tests and a minimal discriminating instrumentation proposal.
Research completion does not deliver additional HEVC support.
