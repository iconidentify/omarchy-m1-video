# Client delivery review

AI self-review by Codex; not independent review. Owner-directed session
`codex-m1-clients-20260920`; refs companion #21/#22/#27, driver #45/#49.
Base `f5fd8ca2c6c5afb6d2a2d719d02f1ad2b9588382`. This series records a dated
experiment and changes the delivery scoreboard; no production driver, installer,
kernel, configuration or security boundary is changed. Exact final head and CI
are recorded in the PR at closeout.

| Stage | Evidence, concerns and resolution |
| --- | --- |
| 1 Intent | Selected client results and an experimental local demo fit the companion repository. Installer source pin unchanged. |
| 2 Claims | Eight hardware rows, actual decoder/mapped driver, seek/reload/progress/drop evidence and 48 byte-identical PNGs. No claim that software preparation qualifies Chrome. |
| 3 Execution | Read dated runners and one caller/callee level of reused IPC helpers. Property readiness failure preserved; corrected wait requires initialized output and explicit mode. Launcher preconditions precede guard exec. |
| 4 Resources | Runners quit only owned players/profiles in finally blocks; guards enforce deadlines and record idle exits. Bundle retains the original source guard. Complete GPL source/build files included locally. |
| 5 Concurrency | Matrix is sequential and stops on first failure. One exclusive C1 two-player row establishes close/survive. No builds overlap leases. Launcher execs the guard so signals and cleanup retain its existing behavior. |
| 6 Trust/bounds | Inputs are generated clips, manifest binds bytes, launcher accepts only measured clip hashes and installed stack. It is not a signed distribution or hostile-directory verifier. Archive verifier reads members without extracting. |
| 7 Hardware | Fresh whole-boot preflight for each lease, ordinary loaded module unchanged, no resets/retries/journal cutoff. Module build-ID note is not loaded-memory proof. Full strict corpus and boot gates unrun. |
| 8 Consolidate | Initialization/capture metadata failures are preparation limits; Chrome GPU startup is a separate blocker, not attributed to C1. |
| 9 Resolve | Early sandbox appeared promising but disabled graphics; reject it using actual GPU feature state and EGL log. Do not publish it as a workaround. |
| 10 Verify | Offline archive verifier passes; five semantic corruptions fail. Bundle valid identity passes; checksum and version mismatch refuse. Actual bundled H.264 smoke passes and final identity/idle inspection agrees. |
| 11 Report | Merge scope is selected evidence and current priorities. Stable packaging is no-go; local two-clip demonstration is go. All parent acceptance criteria remain authoritative. |

Resolved packaging concern: moving only `hwguard.py` would break its source-root
lookup. The delivered bundle contains the complete source tree and invokes
`source/tests/hwguard.py` unchanged. Git revision is unavailable in that unpacked
tree and remains null; the bundle manifest binds source/binary hashes separately.
The actual packaged smoke exercised this path successfully.

Known limits: local avdlab helpers lack a distributable licence in the inspected
tree, so they are referenced by exact hashes instead of copied. The evidence is
checkable offline; independent hardware reproduction requires those helpers or
a separately reviewed equivalent. Render screenshots measure selected window
output, not panel pixels or all frames. No claim that C1 improves measured pixels
over baseline: both drivers passed these rows; C1's merged lifecycle fixes are
covered by the separate earlier evidence.

Reverse checks: no existing production function, shared lock, ownership contract
or hardware ABI changes. Only the current planning document consumes the new
summary. Existing native issue dependencies and contributor claims are preserved.
Public CI remains offline and receives no host access or secrets.
