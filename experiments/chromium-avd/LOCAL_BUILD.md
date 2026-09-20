# Owner-directed build on the existing M1

On 2026-09-20 the owner explicitly requested using this machine after discussion
of the default small-build limits. A separate machine is no longer a dependency
for this attempt. This does not authorize installing the experimental browser,
changing the kernel/module, modifying desktop configuration or weakening its
sandbox. Independent sandbox review and guarded playback remain separate gates.

Session `codex-m1-chromium-local-build-20260920` continues PR #133 from
`fc4f47525c608de81233f0390699f6789d2c93e0`. The host has about 15 GiB usable RAM,
11 GiB available at preflight, 168 GiB free disk and no swap. Initial whole-boot
guard inspection found no decoder holder, wedge or recorded fault.

For this full build only, use the existing cooperative service name with one
worker/one CPU, low CPU/I/O priority, MemoryHigh=4G, MemoryMax=6G, TasksMax=64,
and a six-hour maximum window. Keep temporary/output files on disk. Stop if free
disk falls below 30 GiB or available system memory remains below 3 GiB; stop on
build/cgroup failure and inspect it before any continuation. Preserve incremental
objects. This replaces the small-test profile for the specifically requested
local browser build; it does not change tools/bounded-build or automatically
increase limits to retry failures. Do not overlap hardware campaigns. Long compile runs hold the existing hwguard
scheduling lock for exclusion only and stop if a decoder holder/fault appears;
they do not open decoder devices or grant a playback lease to any child.

Sources and private dependencies live outside Git in
`m1-chromium-local-build-20260920`. The 1,878,222,540-byte Chromium lite archive
was checked against its pinned SHA-256. All 22 adjacent distribution patches
were checked against the original PKGBUILD. Missing GN, lld, gperf, bindgen and
TypeScript packages were downloaded using the existing package database pins,
hash-checked and signature-checked against the installed pacman keyring, then
unpacked privately. No package installation or package database change occurred.
Existing Node, Go and Rust toolchains are selected explicitly and recorded.

prepare_local.py adapts the existing pinned recipe: private tool locations,
native ARM64 component build, no ThinLTO/debug symbols, one worker, and Chrome
plus its sandbox helper first. content_unittests remains an available target,
not a claimed completed build. The private prefix keeps compiler-resource links
to the installed matching Clang. Record actual GN arguments, all source changes,
tool versions and build logs. Test the modified GPU hook's real build targets
before proceeding to the entire browser. Full compilation and playback are not
established by source preparation.

Local configuration passed after moving the new test dependency into the GN
block where deps is already initialized. The native build explicitly selects lld
(the development default selected a bundled x86 mold binary), uses the private
lld library path, and links the existing rustfmt into the private tool prefix.
Initial failed attempts are retained. The scoped `CHROMIUM_AVD_CONFIGURE_ONLY=1`
mode generates the real build graph without claiming to compile the browser.
Bindgen also needs the matching installed libclang linked into that private
prefix, because Chromium explicitly sets its library search location there.
Direct incremental ninja invocations retain the distribution recipe's
`RUSTC_BOOTSTRAP=1` environment for its stable Rust compiler; generating
the build graph in a separate shell does not preserve that exported value.
The two modified GPU objects compiled successfully in the real Chromium build
and their ELF headers identify AArch64. The integrated policy test object pulls
in the much larger content_unittests dependency graph (33,937 remaining steps
at the first attempt), so the resumed sequence builds chrome and chrome_sandbox
before returning to that target. Completed objects are retained; an interrupted
test stage remains incomplete. No successful object build is counted as a
linked browser or executed test.

The non-official build also selects a bundled x86 esbuild for DevTools. Set
`devtools_skip_typecheck=false` to retain the supported, type-checked TypeScript
path used by official builds and the already verified private compiler. This
avoids introducing a mismatched native esbuild version or skipping type checks.

The lite archive leaves the test-font directory empty. Before building the
integrated test target, restore the exact bundle in its DEPS entry:
bucket `chromium-fonts`, object `9c07d19d9c5ee1ff94f717e6fb17e0c8c354e6f9`,
generation `1775663926405386`, 33,413,117 bytes, SHA-256
`f0e9628f9e43e3f3476cde06a1849058de460e0e037b7449ce0d42b9a73c37d5`.
After hash verification, extract into `third_party/test_fonts/test_fonts` and
retain the existing licence file. All 83 font paths in the pinned BUILD.gn are
present in the local tree. They are test inputs, not installed fonts.
