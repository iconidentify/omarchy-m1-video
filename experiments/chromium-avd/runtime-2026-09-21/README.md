# First patched Chromium hardware playback — 2026-09-21

**The selected short H.264 experiment passed with the normal sandbox.** At
16:46 UTC, Chromium 153.0.8010.36 selected `VaapiVideoDecoder` / platform=true.
Its GPU process held the AVD video/media nodes and mapped the exact installed
VA driver. Playback advanced 61 frames over 2.002693 seconds with no dropped-frame
increase. This crosses the hardware-selection gate; broader qualification remains open.

The [structured receipt](result.json) records identities, environment, flags,
observations and hashes of retained raw local artifacts. The
[captured frame](selection-frame.png) shows the generated fixture's bars, markers
and frame counter: 1280×720 at measured DPR 2, from a 640×360 video element.
No reference-pixel or color comparison was run.

## Execution and teardown

- All 242 runtime files (877,609,463 bytes) matched the remote manifest; eight
  ELF loader/dependency checks passed. No setuid helper was used.
- Fresh metadata selected the five expected permissions. Read-only root
  observation established full process visibility and an idle, fault-free
  whole-current-boot preflight after the owner closed ordinary Chrome.
- One unprivileged browser launch used a disposable profile, the existing `avd`
  lease and a nominal 90-second deadline with bounded observation/cleanup
  overhead. The complete invocation took about six seconds. No automatic retry.
- Before and after media, Chromium reported sandboxed=true, AGX graphics,
  enabled OpenGL/compositing and zero GPU crashes. Every observed GPU/renderer
  thread reported Seccomp=2.
- Browser.close completed with exit zero and no forced cleanup. Inner and outer
  checks independently examined all decoder holders and whole-boot faults.
  Final state: no holders, stuck tasks, faults or surviving process in the
  owned guard group. The lease was released.

The exact runtime files received [separate AI source review](../AI_REVIEW_2026-09-21.md)
before launch. Review caught an observer race where one unrelated closing FD
could hide a process's persistent decoder FD. Per-FD collection now retains
the holder and rejects other visibility errors. Both synthetic regressions
passed under tools/bounded-build before the hardware window.

## Limits and next gate

This used installed VA driver `1.3.r11-2`; C1 browser playback was not tested.
Running kernel: `7.1.13-3-1-ARCH`; installed kernel package: `7.1.13.asahi3-2`;
Mesa: `26.2.3-1`. Mesa changed from the earlier experiment's `26.1.8-1`, so this
is not a controlled comparison changing only Chromium. Loaded module-note and
installed driver hashes matched the prior run; a module note does not certify
every loaded kernel patch.

The browser reports SMPTE170M for the BT.709-tagged fixture. Raw Chromium logs
retain pre-playback SharedImage mailbox errors plus Wayland, metrics and
teardown messages. They did not prevent these measured gates; their effects
remain unqualified. No error-free-browser or correct-color claim follows.

Next: a separately bounded same-client hardware/software rendered-pixel and
seek/reopen check, then two-element close/survive and adaptation gates. PR #133
stays draft; browser #22, driver #48, full strict-set preservation and broader
stability/recovery remain open. The earlier desktop freeze is unexplained.

AI-assisted maintainer execution and evidence preparation. No installation,
persistent desktop settings, module operation, reboot or release was performed.
