# Chromium M1 integration candidate — self-review

Session `codex-m1-chromium-access-20260920`, refs companion #22. Base
`bc0090a063387213033177f617617d841660fa12`; plan commit `1330101` precedes code.
The PR records the final tested SHA. Chromium 153.0.8010.36 and Arch packaging
pins are in sources.json. Codex authored and reviewed this change with AI;
**this is not independent review**. A qualified Chromium/Linux sandbox reviewer
remains unassigned. The owner subsequently requested building on the existing M1;
LOCAL_BUILD.md records its private tools, budget and incremental evidence.

| Stage | Evidence and disposition |
| --- | --- |
| 1 Intent | Browser-owned fix candidate for measured post-sandbox libdrm lookup failure. Driver/kernel/installation untouched. Experimental added device access is default-off. |
| 2 Claims | Patch wires generic Linux GPU permissions behind ARM64, USE_VAAPI, accelerated-decode and feature gates. Recipe enables VA-API. Exact-file application and full-tree local GN configuration pass after the ordering fix below. Full hook/browser compilation and effective sandbox behavior remain unverified. |
| 3 Execution | Reviewed full discovery, caller hook, native filesystem adapter, rule-to-broker mapping and upstream permission predicates. Missing or nonunique validated sets return empty; all selected identities/topology are re-read. Bound scans and metadata sizes; no arbitrary user path becomes a rule. |
| 4 Resources | Native lstat/realpath/read only. realpath allocation freed; metadata fd closed on read error, size rejection and EOF; EINTR retries; vectors/strings own results. No new device fd, ioctl, VA object or decoder lifetime change. |
| 5 Concurrency | Startup snapshot, no shared mutable state. Synthetic selected-node deletion/inode changes before publication reject. New device appearance or privileged replacement after recheck is not covered; retain trusted non-hotplug SoC/root path assumption for independent review. |
| 6 Trust/bounds | Fixed /dev ranges, char/root/lstat checks, numeric sysfs match, canonical platform path, exact driver/compatible and physical media parent. Actual upstream broker tests reject recursive access, unrelated nodes, dot traversal, creation and metadata writes. Existing Chromium grants are outside the added-policy test. No ioctl filtering is claimed. |
| 7 Hardware | Source tracing: libdrm fstat/stat/access, driver media enumeration then video uevent/context opens. Node topology observed read-only before implementation. No candidate device open/ioctl/browser playback; DMA import, color and client behavior unverified. |
| 8 Consolidate | Open gates: full compilation/integration, independent sandbox review, selected hardware run. Startup metadata confidence is separate from runtime access correctness. |
| 9 Resolve | A metadata-only stat grant is insufficient: libdrm also probes the render path with access; later driver contexts open media/video and read video uevent. Exact separate permissions retained. Driver .so preloading/lifetime is unchanged; libva uses RTLD_NODELETE on this Linux path. |
| 10 Verify | 12 real GoogleTest cases and four compiled assertion-detecting mutations pass under ASan/UBSan. GCC 16.1.1 and Clang 22.1.8 used; host GoogleTest 1.18.0. Exact applied source plus upstream broker cc/h/command header; explicitly listed infrastructure shims. Recipe hash/syntax/refusal tests pass. |
| 11 Report | Draft only. No merge or runtime qualification recommendation. The owner-directed local build is underway; qualified sandbox review is still required before guarded playback. #22's playback/adaptation criteria and driver #48 remain open. |

## Findings resolved during implementation

- **Test integration, confirmed and fixed:** the broker command header supplies
  the process-local open-flag mask; it was initially misclassified as unused.
  Fetch and hash the real header. The tests exercise flags at the broker boundary,
  where Chromium's client has already removed O_CLOEXEC. No broker implementation
  or constants are substituted. The initial compiler run also rejected two copied
  range-loop values; they now use references.
- **Fixture validity, confirmed and fixed:** manual lengths truncated NUL-separated
  compatible strings and caused the positive cases to reject every device set.
  Construct explicit NUL-terminated strings without manual lengths. Require positive
  selection and deliberate policy mutations; the formerly passing negative cases
  alone provided no evidence that discovery worked.
- **Build resource hint, confirmed and fixed:** the packaging recipe separately
  exports ALARM_NINJA_JOBS=16 and MAKEFLAGS=-j16. Both become one, including when
  build executes in a later makepkg process; ninja receives -j1 explicitly.
- **Component visibility, source-reviewed:** exported selector/native adapter
  declarations allow Chromium test targets to link via the content component;
  the intended recipe is explicitly non-component. Source review also corrected the new test dependency to `sandbox_services`,
  which owns BrokerFilePermission, instead of the seccomp BPF target. Full link verification remains
  unresolved, so this is not a tested component-build claim.
- **Hosted source transport, confirmed and fixed:** the first GitHub job
  ([35531401890](https://github.com/iconidentify/omarchy-m1-video/actions/runs/35531401890))
  timed out fetching Gitiles before any C++ test executed. Add Chromium's official
  GitHub mirror after transport failure, verify its bytes against every unchanged
  source pin, and regress that checksum failures never trigger fallback. A failed
  fetch is not a policy-test pass or a policy defect.

## Validation scope and next decision

The first real local GN configuration exposed a patch defect that the isolated
test could not cover: the added test dependency used `deps +=` before that target
initialized `deps`. Move it to the later Linux dependency block. Configuration
then succeeded (31,953 targets from 4,995 files). The private tool prefix needed
lld's private shared-library path and an explicit rustfmt link. Initial native
compilation also selected Chromium's bundled x86 mold linker in the non-official
configuration; select native lld explicitly for the local ARM64 build. Preserve
these preparation failures; they are not hardware faults or passing browser runs.

Local checks use tools/bounded-build (one CPU/worker, 1.5 GiB maximum, disk TMPDIR).
Successful initial GCC policy/mutation run: 44.6 seconds, 435.1 MiB reported peak;
successful Clang run including recipe checks: 20.7 seconds, 193.1 MiB peak.
The final-head run and hosted job are recorded in the PR; initial compile/fixture
failures above are retained as failed preparation attempts, not hardware failures.

The four mutations broaden metadata stat to read, broaden uevent read to write,
remove physical media pairing, and accept a camera driver. Each compiled and then
failed its named assertion, with no sanitizer error accepted as evidence.

Native adapter tests cover regular-file rejection, final symlink rejection,
missing paths and metadata at/over its bound. They do not fully exercise real
character-device owner changes, inaccessible sysfs, GPU startup order or broker
IPC/seccomp dispatch. The parent full-build unit test wiring is supplied but
unrun. The generated recipe is syntax-tested, not build-qualified.

No hardware lease acquired, client launched, installed package changed, system
configuration edited or kernel/module operation performed. Existing Chrome crash
and browser evidence remains unchanged; this candidate does not explain the
earlier full desktop freeze. Keep the patch opt-in and draft pending review/build.
