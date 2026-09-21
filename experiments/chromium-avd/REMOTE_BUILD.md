# Owner-designated remote ARM64 builder

On 2026-09-20 the owner supplied SSH access to an ARM64 Linux VM on an M3 Pro
and designated it as the build machine. It has eight virtual CPUs, about
24 GiB RAM and 393 GiB free disk at inspection. This continues PR #133 and
the existing #22 claim; the M1 remains the later hardware-test machine.
The shared desktop's limits and installed software are unchanged.

## Local attempt and configuration correction

The local `browser-04` attempt stopped at 22:07 UTC after 61 minutes, at
3,041/51,666 browser steps. Linking `libnet_third_party_quiche.so` failed with
unresolved Rust allocation/deallocation symbols. Its result, full log and
completed objects are retained. Both modified GPU objects had already compiled;
this later failure is not a passing browser build or a decoder fault.

The pinned Chromium `build/rust/std/BUILD.gn` documents a component-build
limitation with prebuilt Rust standard libraries: linker flags can reach one
shared library without the corresponding allocator implementation. The failing
QUIC link includes those standard libraries without the allocator crate.
The remote recipe uses the original distribution's non-component layout,
retaining Rust, PartitionAlloc and linker undefined-symbol checks. This is the
selected correction; the full remote browser link passed on 2026-09-21.

## Remote preparation and budget

Transfer the verified Chromium 153.0.8010.36 archive, all 22 original distribution
patches, the reviewed overlay and the DEPS-pinned test fonts. Start a fresh
output tree; retain the M1's partial output as evidence. Keep the recorded
native Clang 22.1.8, Rust 1.98.0, Node 26.8.2 and Go 1.26.8 identities. The
builder's glibc, Clang and key Linux development libraries match the M1;
complete dependency/binary compatibility is checked before later playback.

Tools missing from the VM are privately unpacked after package checksum and
distribution-signature verification. No package installation, decoder access,
browser launch, system configuration change or administrator access is needed
for this preparation. Keep private host addresses and credentials out of Git.

The owner-designated builder has its own finite CPU-build budget:

- Four compiler workers and `CPUQuota=400%`, with low CPU/I/O priority.
- `MemoryHigh=14G`, `MemoryMax=18G`, `MemorySwapMax=0`, `TasksMax=256`.
- A 12-hour maximum build window; disk-backed temporary and output files.
- Stop on build/cgroup failure, below 30 GiB disk free, or below 3 GiB available
  RAM for three observations. Preserve outputs and inspect before restarting.
- Use one fixed `omarchy-video-build` user service on that VM. Do not run a
  competing build service or automatically raise limits after failure.

Generate the private recipe with explicit paths and resource choices:

```sh
python3 experiments/chromium-avd/prepare_local.py \
  --original /absolute/packaging/PKGBUILD.original \
  --output /absolute/packaging/PKGBUILD.remote \
  --tools /absolute/tools-root/usr \
  --rust-sysroot /absolute/toolchains/rust-1.98.0 \
  --jobs 4 --non-component
```

`--jobs` changes the explicit Ninja count and both preparation/build worker
hints. It does not enforce memory or CPU limits; the enclosing service does.
The default invocation retains the one-worker component settings used on the
shared desktop. Both modes point Chromium's tracked Rust-compiler symlink at
the supplied private sysroot; the VM need not have `/usr/bin/rustc` installed.
Recipe generation and shell syntax have been checked. Real remote preparation
passed (32,229 GN targets, all 83 fonts restored); the first compile refused
the original broken system-Rust symlink before doing work. That link is
corrected without changing Rust versions or Chromium code.

## Browser and integrated tests complete — 2026-09-21

Remote `browser-02` compiled both modified GPU objects and successfully linked
`chrome` and `chrome_sandbox` at 09:37 UTC. The content test binary build stopped
at 10:07 UTC after 2,622/3,366 additional steps. This was an ordinary test-build
failure after 11 hours 20 minutes overall, before the 12-hour deadline; the
completed browser and all logs/output are retained.

`browser_thread_nocompile.nc` expected two thread-safety diagnostics that were
not emitted. The original distribution `0002-Fix-distcc.patch` adds `-w` in two
configurations inherited by the test, suppressing those diagnostics. Removing
only `-w` restores them but exposes two unsupported warning switches. A direct
run with the same private Clang 22, omitting exactly `-w`,
`-Wno-stringop-overread` and `-Wno-unused-but-set-global`, passes both original
expectations. A deliberately wrong expected diagnostic still fails.

`prepare_test_build.py` verifies the pinned wrapper hash and filters those
three flags only for diagnostic tests. It retains `-verify`, `-Werror`, all
expected diagnostics and all test dependencies. The private recipe applies
this adapter after the browser overlay. No browser source, browser compiler
command or runtime sandbox permission changes. Hosted checks execute the actual
adapted wrapper with Clang: expected warnings pass; missing/unexpected warnings
and an unrelated unknown option fail. Only its unused Windows depfile import
is shimmed.

Remote `browser-03` resumed with 746 remaining test-build steps under the same
CPU/memory limits and a shorter two-hour window. The test binary linked at
16:11 UTC, and all 12 `AppleAvdPermissions.*` cases executed and passed, with
no skipped cases. The runner exited zero after 26 minutes 10 seconds. The
browser/helper hashes match their pre-correction artifacts exactly. No build
service remains running. [The completion receipt](build-result-2026-09-21.json)
records executable identities, cases and hashes of the retained raw evidence.
This completes the build/integrated-policy gate; runtime bundle compatibility
and M1 playback remain unverified.

## Return and test

Retain actual source, recipe, GN arguments, tool and dependency hashes with the
build logs. Return the complete necessary runtime bundle and compare it with
the M1's libraries before launching. Compilation in the VM cannot qualify the
M1 video decoder or graphics stack. The separate AI review's conditions and
fresh whole-boot preflight, exclusive finite hardware guard, normal sandbox,
actual hardware selection, displayed frames and clean teardown remain required.
PR #133 stays draft while runtime verification and playback are unfinished.
