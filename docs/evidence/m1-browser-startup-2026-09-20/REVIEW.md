# Browser continuation review

AI self-review by Codex, not independent review. Owner-directed session
`codex-m1-browser-startup-20260920`; base
`861b54ce6b339900e5e06eb50fd89271b045c313`, refs companion #22.
Final reviewed head, hosted checks and merge decision are recorded in the PR.
Scope is dated evidence, its offline verifier and current delivery priorities;
no production browser, security policy, driver, installer or configuration changes.

| Stage | Evidence, concern and disposition |
| --- | --- |
| 1 Intent | Browser startup and actual decoder selection belong to the companion client gate. C1 is not attributed a failure when it was never selected. |
| 2 Claims | Sandboxed AGX startup and software lifecycle pass only with the dated three-variable environment. Both hardware selection attempts choose FFmpeg. Legacy GPUInfo profile lists are not used as proof of codec support. |
| 3 Execution | Read complete dated runners and reused WebSocket/process-tree callers. The first playback collector's NUL-only parsing misses rewritten Chrome titles; corrected to existing startup parsing, original failure/source preserved. All assertions remain. Diagnostic stops immediately after first-frame selection; no seeks. |
| 4 Resources | Only owned disposable browsers are closed in finally; finite guards cover process groups. Each final state idle, no holders. Observer forwards calls/errno, has no retained device/display allocation and is not a shipped workaround. Original crash cores remain private; extracted analysis copy removed. |
| 5 Concurrency | Sequential exclusive AVD leases, no CPU builds overlap hardware. Per-thread isolation sampled, not inferred from one process flag. Observer symbol pointers resolve at constructor time before sandboxed concurrent calls. No new production shared lifetime/locking changes. |
| 6 Trust/bounds | Generated local fixture, exact hashes, direct browser binaries. Observer resolution failure exits rather than faking success. Archive is read without extraction/execution; it is a committed evidence checker, not a verifier for arbitrary hostile archives. Profiles/cores/private crash metadata excluded. No policy weakening, upstream report or security fix published. |
| 7 Hardware | Each fresh guard uses whole-current-boot preflight with unchanged module/driver. Guard ok means bounded idle execution, not accepted graphics/decoder selection. No browser hardware frames, no full strict-set/package/boot qualification. |
| 8 Consolidate | Three distinct issues: default cache workers prevent sandbox initialization; the first cache-disable alternative creates a late scheduling violation; after all-backend disable, display recreation encounters a broker denial. Tool parsing failure is separate. |
| 9 Resolve | Cache-off superficially reports sandboxed=true but GPU crashes and graphics is Disabled: rejected. All-cache-backends=0 passes both isolation and real graphics. Software reference tags differ from Chrome's reported SMPTE170M; no colour pass invented. |
| 10 Verify | Forwarding observer's no-device stat/invalid-fd results and errno equal the plain process under bounded build. Evidence verifier passes; six semantic corruptions are rejected. Runtime denial is confirmed by forwarded return values; exact-version source explains it but downstream patch correspondence is not fully established. |
| 11 Report | Go for merging measured evidence and the revised next action. No-go for browser hardware support, persistent cache settings, installer pin changes or stable release. A production browser integration fix requires qualified review and new measured selection/output gates. |

Confirmed experimental-tool concern: title parsing produced an empty isolation
sample, which refused before media. Correction was checked against normal and
rewritten argument layouts before the fresh v2 reference. It does not relax the
requirement for both GPU and renderer entries and all sampled threads Seccomp=2.

Confirmed browser integration failure: uninstrumented VA display error and
software fallback. The diagnostic's actual sysfs stat returns EACCES, which
libdrm turns into EINVAL before libva display allocation. Counterargument that
the observer manufactured a pass is inapplicable: it forwards results and the
original uninstrumented row already failed at the same display boundary. The
instrumented row remains diagnosis only. Fix sufficiency is unresolved: later
video/media-node access and image import may need additional integration.

Crash attribution limit: cache-disable's late-worker scheduling path agrees with
exact source and the observed syscall/arguments. The core backtrace is only
partly symbolized; do not report a complete source stack or connect it to the
owner's earlier full-system freeze.

Reverse checks: only M1_DELIVERY.md consumes the new summary. Historical evidence,
codec denominators, native parent dependencies, contributor claims and installer
source pins remain. Included upstream source preserves notices and source URLs;
local helper source is omitted for its missing redistribution licence. No new
public CI hardware access, secrets or dependencies.

Validation: bounded offline evidence verification and six semantic mutation
checks; repository Checks workflow on exact PR head. No-device observer build
used one worker, 22.6 MiB peak memory; no browser rebuild attempted. Current
driver/module/browser/helper hashes match initial identity at final idle check.
