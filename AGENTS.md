# Instructions for coding agents

This repository sets up hardware video decoding on Apple Silicon Macs running Omarchy with the
`linux-asahi` kernel. Read `README.md` fully before acting.

1. **Separate offline contribution from system work.** Source analysis, documentation and
   no-device tests are open to contributors without Apple hardware; start at
   `docs/CONTRIBUTOR_START.md`, `CONTRIBUTING.md` and the live shared agent workflow.
   Use a ready leaf, a unique-session claim and an isolated branch from current `main`.
   Linux is required for Linux C builds; source/Python tasks can use other suitable hosts.
   Before any installer, module or Apple hardware action, `uname -m` must be `aarch64`,
   `/proc/device-tree/compatible` must contain `apple,`, and `pacman -Q linux-asahi`
   must succeed. Otherwise stop that system/hardware action; offline work can continue.
2. **Get the user's explicit consent before installing.** Explain in your own words that this
   installs an out-of-tree kernel module that loads at every boot, that the test Mac hard-reset
   twice shortly after boot with these patches loaded at boot (cause unknown; one later boot with all
   patches was fine),
   and summarize "If the Mac freezes or resets" from `README.md`. Also say it installs pacman hooks,
   a boot service, a replacement VA-API driver package and mpv settings. Only continue after the
   user clearly agrees; do not pass `--i-accept-boot-risk` on your own.
3. **Ask the user to save their work** before any `modprobe -r apple_avd` and before rebooting.
4. **Install** by running `./install.sh --i-accept-boot-risk` as the normal user (it calls sudo
   itself). Do not edit the patches. If it stops with an error about headers not matching the
   kernel, the system needs a full update and a reboot first; tell the user instead of forcing it.
5. **Test before rebooting:** with every video closed,
   `sudo modprobe -r apple_avd && sudo modprobe apple_avd`, then have the user play a video.
6. **Verify** with `sudo apple-avd-rebuild --status`, `vainfo --display drm` (H264 and HEVC
   profiles listed) and `mpv -v --hwdec=vaapi <video> | grep -i 'hardware decoding'`.
7. **mpv output:** keep `gpu-api=opengl`; Vulkan output shows a green/pink ghost picture.
8. **If the machine freezes or resets**, follow "If the Mac freezes or resets" in `README.md`.
9. **Do not report problems** with this setup to Asahi Linux or other upstream projects. Report
   them as issues in this repository.
10. **To undo**, run `./uninstall.sh` and reboot.

## Reviewing pull requests

A pull request from a fork may arrive with red checks that executed **nothing**:
some contributor accounts cannot start GitHub Actions, and the run then completes
as a failure with zero jobs and no billable time. That is an absence of evidence,
not a failure and not a pass. Confirm which it is before reading anything into it:

```sh
gh api "repos/<owner>/<repo>/actions/runs?head_sha=<sha>" \
  --jq '.workflow_runs[] | "\(.name) \(.conclusion) jobs=\(.run_attempt)"'
gh api "repos/<owner>/<repo>/actions/runs/<run-id>/jobs" --jq '.total_count'
```

`total_count` of 0 means the workflow never ran. Do not merge on it, and do not
report it to the contributor as a failing test.

When hosted checks did not run, run them locally before merging:

```sh
tools/verify-pr.py <number>           # fetch the head and run its checks
tools/verify-pr.py <number> --list    # show what would run, without running it
```

It picks workflows using the `paths` filters the workflows already declare, so
the local set matches the hosted set. It never installs anything: dependency
steps are skipped, and a step that then fails for a missing dependency is
reported `UNVERIFIED` rather than as a pass or a defect. Treat `UNVERIFIED` as
unfinished review — install the dependency and rerun, or verify it another way.

Verifying a pull request whose CI did not run is part of reviewing it, not a
question to hand back to the maintainer.
