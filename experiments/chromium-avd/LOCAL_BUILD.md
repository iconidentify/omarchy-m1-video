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
increase limits to retry failures. Do not overlap hardware campaigns.

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
