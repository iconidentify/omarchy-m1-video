# M1 submission qualification — 21 September 2026

The submitted userspace package and AVD kernel module passed the planned driver
campaign together on a 13-inch M1 MacBook Pro. Testing finished on 21 September
in Pacific time (22 September UTC).

## Tested versions

| Component | Revision |
| --- | --- |
| [Kernel PR #10](https://github.com/omacom/linux/pull/10) | `0b4025f19a985b904f7ec96de2b74ced68c710cb` |
| [Package PR #53](https://github.com/omarchy-mac/omarchy-pkgs-aarch64/pull/53) | `903213a1b2d9b42320c37c79051515aec5a9bd65` |
| VA-API driver source | `5b5046cbda6892f4a63df0015857a80bd42c17cf` |
| Installed package | `libva-v4l2_request-avd 1.3.r11.r164.g5b5046c-1` |
| Running kernel | Asahi `7.1.13-3-1-ARCH` |

The package was installed and the submitted AVD source was built and loaded as
a module for the running Asahi kernel. The complete destination Omarchy `tb`
kernel still needs to be built and booted.

## Results

- All **433 selected baseline videos** passed: H.264 73, HEVC 144 and VP9 216,
  totaling **22,357 frames**. These preserve the known passing sets from suites
  of 135, 147 and 305 videos; they do not claim every video in those suites passes.
- Five OpenGL mpv cases passed: H.264, HEVC Main/Main10 and VP9 8/10-bit.
  **100 seeks, 10 reloads and 30 rendered captures** passed; every capture
  matched its software reference byte for byte.
- **180 concurrent-client groups** passed across shared threads and separate
  processes, with 1, 2 and 4 contexts and **2,560 exact frame comparisons**.
- Early export, client termination, playback after interruption, and closing
  one player while another continued all passed.
- The **60-minute uninterrupted soak** passed **834,672 frame comparisons** and
  **17,389 retained-image checks**. It recorded no resource-limit violations.
- Offline validation passed: **196 driver checks, 92 packaging checks, five
  kernel regression groups and the ARM64 module build**. Allocation regressions
  cover **149 failure cases**.

The frozen experimental Chromium build selected hardware decoding and passed
20 seeks, full playback, reopening and normal sandbox/exit checks. Its five
image comparisons still showed the recorded color mismatch. Browser presentation
remains open. This campaign does not establish boot stability or qualify other Macs.

## Evidence

- [Acceptance audit](acceptance-audit.json), [run summary](run-summary.json) and
  [final runtime state](final-runtime-state.json).
- [Source revisions](candidate.json), [system and module identity](system-identity.json),
  and [PR heads checked at campaign completion](submission-status.json).
- [Conformance results](conformance-results.json) and [exact selected vectors](conformance-vectors.json).
- [Playback and browser comparisons](playback-comparison.json),
  [browser build identity](browser-verification.json) and
  [excluded setup attempts](evidence-notes.json).

This directory publishes the compact records from the completed campaign.
Commands and raw-log paths refer to the original test machine. The full local
archive retains logs, captures, fixtures and adapters; its checksum and the
source checksums for these records are in [source-records.json](source-records.json).
[SHA256SUMS](SHA256SUMS) covers this published directory.

Credits: Asahi Linux contributors, megi, sofus13, Aaron (aquarat), Igor Ryzhkov,
Ante042, laihenyi and the contributing community. Preparation and review were
AI-assisted under maintainer direction.
