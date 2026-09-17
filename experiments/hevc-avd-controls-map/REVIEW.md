# Maintainer adversarial review

AI maintainer review of contributor head `cc3ac8f891fba4b4b41a7409ff89c2ad8ad4d336`,
followed by self-review of maintainer corrections. Original z23 commit retained;
no independent human/kernel specialist review claimed. No runtime/module change.

Findings corrected before acceptance:

- Global member-name coverage allowed a read missing from one function to be
  credited to a different function. Coverage is now local, with missing uses added,
  the tile-selection helper included, and exact read/call/flag/location snapshots.
  New helpers, nested reads, changed owners and cross-function omissions reject.
- Source hashes/imported macros were recorded but not actually checked by the PR's
  CI. CI now fetches exact primary files, verifies every patch, prepares the exact
  15-patch source, checks imported definitions and runs source-dependent tests.
  The scanner is narrow; production scanning rejects any changed source hash.
- Negotiated output geometry and compressed layout were overclassified as measured
  copied SPS/DECOMP words. Those claims were corrected. Historical reference/input
  evidence is distinguished from actual non-reference appended commands.
- Loose inequality packing checks were strengthened to exact signed bit arithmetic.
  An additional C harness executes the exact upstream weight/QP/deblock function
  bodies against the pinned UAPI with UBSan: I/P/B, inactive/default, signed weights,
  L1 identity, QP range, signed chroma offsets and deblock enable/overlap.
- The next observation's count/first/last summaries could miss interior corruption.
  It now requires complete selected command sequences and copied input attribution,
  explicit inactive records, no retained pointers, and calculated finite storage.
  Existing history alone exceeds 1 MiB, so the proposed total cap is 2 MiB.
- #67 has since supplied full ioctl-returned controls and matching compressed bytes.
  The obsolete full-VA-input gap and speculative PCM lead are superseded; the
  remaining experiment measures job-hook state and actual emitted commands.

Validation: 17 synthetic test groups with source-dependent cases enabled, exact C
branch/packing checks under UBSan, immutable source/patch/macro verification,
accepted schema-2 report and #67 report reproduction, required Bash syntax/mocked
rebuild and exact-head CI before merge. Fresh temporary source reproduction is part
of CI. No new hardware run, broad codec suite, concurrency/boot qualification or
corruption fix is claimed. Negative-result evidence is preserved without promoting
codec counts or blaming firmware.
