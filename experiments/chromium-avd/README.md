# Experimental Chromium M1 VA-API device access

**The full browser and integrated test binary build; all 12 policy tests pass.
One short sandboxed M1 H.264 experiment passed with 61 advancing frames, zero
dropped-frame increase and normal teardown. See the
[runtime evidence and open gates](runtime-2026-09-21/README.md).
Do not install this experiment or
use it as a normal browsing configuration.** Refs
[browser #22](https://github.com/iconidentify/omarchy-m1-video/issues/22).

The [measured startup failure](../../docs/evidence/m1-browser-startup-2026-09-20/README.md)
is a sandbox-denied libdrm device-information lookup when the GPU process recreates
its VA display. The matching Arch Linux ARM Chromium recipe additionally sets
`use_vaapi=false`. This patch provides an opt-in candidate for those two barriers;
it does not establish that they are the only barriers.

## Source and behavior

- Chromium **153.0.8010.36**, exact upstream files/hashes in [sources.json](sources.json).
- [Arch Linux ARM packaging revision](https://github.com/archlinuxarm/PKGBUILDs/tree/3d45100a45e945ac14f0fbb0c6e67c5540f9e6c9/extra/chromium)
  **3d45100a45e945ac14f0fbb0c6e67c5540f9e6c9**. The lite archive hash is
  `645f64566cfbb780747430d53ff3656f03639f89fed9544c1eadd4c17e7b1c82`.
- [Patch](chromium-153-avd-hook.patch) wires the [overlay](overlay/content/common/)
  into the GPU's existing permission construction and Chromium `content_unittests`.
  `VaapiAppleAvd` is disabled by default and reachable only in an ARM64 VA-API build
  when accelerated video decoding is enabled. The ChromeOS/Chromecast early paths
  retain their existing behavior.

Pre-sandbox discovery reads metadata only. It scans bounded ranges (64 render,
64 video and 64 media nodes), requires root-owned non-symlink character nodes,
checks device numbers against sysfs, and matches canonical topology, platform
driver and exact device-tree compatible tokens. It requires one Asahi/T8103
render node and one AVD/T8103 video/media pair. Any missing, invalid, ambiguous or
changed selected observation yields no added permissions. Unrelated cameras do
not become authorized.

On the observed M1, the added permissions would be:

| Path | Added operations | Purpose |
| --- | --- | --- |
| `/dev/dri/renderD128` | read/write, existing node | libdrm node lookup / GPU |
| `/sys/dev/char/226:128/device/drm` | stat, including ancestor stat | libdrm VA-display recreation |
| `/dev/video0` | read/write, existing node | AVD decode context |
| `/sys/dev/char/81:0/uevent` | read only | driver's video-interface discovery |
| `/dev/media0` | read/write, existing node | media request API |

These numbers are discovered, not assumed. The media major is dynamic. No
recursive permissions, directory read grants, new syscall classes or sandbox
disabling are introduced. Chromium's **existing** generic permissions remain;
our negative tests describe the added policy, not the complete browser sandbox.
Read/write node permissions inherit Chromium's standard broker semantics, not
an ioctl whitelist. Review must assess the resulting GPU-process device surface.

Device/sysfs paths remain trusted kernel/root-owned objects after the startup
snapshot. This is not atomic enumeration, a retained-FD design, or protection
against privileged device replacement/hotplug. The selected nodes are integrated
SoC devices. These assumptions require independent review before runtime use.

## Reproduce the offline checks

Needs Python 3, patch, a C++20 Linux compiler, real GoogleTest headers/libraries,
and ASan/UBSan. Fetch source inputs separately; the test itself has no network
access requirement and never opens a GPU, video or media device.
The fetch step may use Chromium's official GitHub mirror after a transport
failure. Both endpoints must produce the same pinned bytes; a checksum mismatch
stops immediately, without fallback. Each request has a 15-second socket timeout.

```sh
python3 experiments/chromium-avd/source_cache.py /absolute/path/source-cache
tools/bounded-build python3 experiments/chromium-avd/test.py \
  --source-cache /absolute/path/source-cache
```

The test verifies source hashes, refuses modified/reapplied source, applies the
patch with zero fuzz, and compiles **the applied selector, tests and adapter**
with the exact upstream `BrokerFilePermission` implementation and command header.
It runs 12 GoogleTest cases with ASan/UBSan and four compiled negative mutations.
Undefined-behavior reports are fatal; a deliberate signed-overflow probe checks
that the configured compiler cannot report that error and still exit successfully.
Each mutation must fail its intended GoogleTest assertion; a compile failure,
timeout, signal or sanitizer report does not count. Native adapter checks use
ordinary temporary files and symlinks only. Real root-owned character-node
ownership enforcement is source-reviewed, not fully simulated by those tests.

The isolated build substitutes only CHECK streaming, the UNSAFE_TODO annotation,
case-sensitive StartsWith, export decorations and the host GoogleTest include
path ([shims](tests/shims/)). Broker path/flag decisions are not substituted.
This does **not** compile the GPU hook, GN graph, whole Chromium or OS sandbox.

## Prepare a full test build

Use a native **ARM64 Arch Linux ARM worker** with Chromium's build dependencies
already provisioned and a reviewed resource budget. The owner subsequently
requested using the existing M1: see [the scoped local build plan](LOCAL_BUILD.md)
and `prepare_local.py` for private dependencies and its explicit resource budget.
A separate machine is an option, not a requirement. The instructions below retain
the original native package-build route; the completed build used the remote
recipe below. Do not change general small-test limits to run this experiment.
The owner has now provided a dedicated ARM64 VM; its explicit parallel-build
budget and non-component configuration are in [REMOTE_BUILD.md](REMOTE_BUILD.md).

1. Obtain the exact packaging directory at the revision above in an isolated
   checkout, with all its adjacent patch files. Preserve the original PKGBUILD.
   Copy this experiment to the worker and record its Git SHA. The recipe uses
   that absolute experiment path for the source overlay.
2. Generate a new recipe, substituting absolute paths:

   ```sh
   python3 /path/to/experiment/prepare_recipe.py \
     /path/to/packaging/PKGBUILD /path/to/packaging/PKGBUILD.avd-test
   ```

   This validates the complete original recipe hash and writes a new file only.
   It enables VA-API, disables native V4L2, sets a non-component ARM64 release
   build, uses one worker including ALARM's job hint, removes the distribution
   API key, changes the package name, and adds `content_unittests` to the build.
   Original packaging credits, local patches and archive checksums are retained.
3. In that isolated packaging directory, with dependencies already present:

   ```sh
   makepkg -A -p PKGBUILD.avd-test --nobuild
   makepkg -A -p PKGBUILD.avd-test --noextract --noprepare --noarchive
   ```

   Neither command installs dependencies or the package. The first downloads,
   verifies and prepares the package sources, then applies our overlay only if
   all three touched Chromium originals still match their pinned hashes. The
   second compiles and stages package files within the build directory. A pinned
   distribution patch that changes those originals is a stop for review, not a
   reason to bypass the source check. This original package route has syntax
   checks; the separately recorded remote recipe has completed linking.
4. Run the built `content_unittests` with
   `--gtest_filter=AppleAvdPermissions.* --test-launcher-jobs=1`, under the worker's
   agreed limits. Preserve complete build/test logs, actual GN args, compiler and
   dependency versions, source manifest, binary hashes and accompanying runtime
   files. The relevant executable is `src/chromium-153.0.8010.36/out/Release/chrome`.
   Preserve the whole required output bundle; do not copy just one executable or
   install the staged package on the desktop.

The checked-in preparer may also validate an isolated Chromium tree directly:
`prepare_source.py /absolute/chromium/tree` is a dry run; `--apply` edits only the
validated sources and adds the overlay. This is a source preparation utility,
not an installer or a complete toolchain bootstrap.

## Scoped playback configuration

The first run followed full compilation, runtime verification and separate AI
source review. Further experiments retain a bounded guard, disposable profile
and the normal sandbox. Explicitly
select the validated render node using `--render-node-override`: upstream VA-API
preinitialization otherwise prefers PCI devices, while this GPU is a platform
device. Enable the experimental feature and required supported VA-API feature
flags for the pinned build, retaining the existing process-local cache setup:

```text
MESA_DISK_CACHE_MULTI_FILE=0
MESA_DISK_CACHE_DATABASE=0
MESA_DISK_CACHE_SINGLE_FILE=0
LIBVA_DRIVER_NAME=v4l2_request
LIBVA_DRIVERS_PATH=/usr/lib/dri
MESA_SHADER_CACHE_DISABLE unset
```

This is configuration context, **not a general-use launch command**. Fresh whole-current-boot
preflight, exclusive hwguard lease and finite deadline remain mandatory. Prove
actual `VaapiVideoDecoder` / platform=true, AGX graphics, normal sandbox and no GPU
crashes before any seek/capture matrix. Stop on the first failure. Do not retry
with a weaker sandbox. Import/export, unsupported driver behavior, color, seeks,
adaptation and C1 comparison remain open; this patch cannot certify them offline.

## Licenses and review

New C++ overlay files are BSD-3-Clause under [LICENSE.apple-avd](overlay/LICENSE.apple-avd).
Chromium authors retain their notices and [upstream license](CHROMIUM-LICENSE).
The Python support follows this repository's GPL-2.0-only license. Original
Arch packaging authors remain in the generated recipe. No binary is redistributed.
See [self-review and open gates](REVIEW.md) and the separate
[AI source review](AI_REVIEW_2026-09-20.md) of `88715ec`. The latter supports
one guarded local experiment only after build/runtime verification and fresh
preflight; it is not human review or general sandbox/hardware qualification.
Its two acceptance findings are fixed: hosted CI verifies fatal UBSan handling,
and the executed playback runner requires normal browser exit and a fresh final
check for all decoder holders and whole-boot faults before success. The exact
observer/launcher received [additional AI review](AI_REVIEW_2026-09-21.md).
AI-authored implementation and prose.
