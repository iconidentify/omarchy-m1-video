# Boot matrix runbook — omarchy-m1-video#13

Campaign dir: `/home/chrisk/boot-matrix-13-20260919`
Device: M1 MacBook Pro 13" (J293/T8103), pseudonym `m1-t8103-primary`

**Stop the campaign at the first reset, freeze, panic, AVD fault or unexpected
recovery requirement.** Do not continue to the next cell after a failure; preserve
its evidence first.

## Why this needs an operator

The root filesystem is LUKS2 with a single passphrase keyslot and no TPM/FIDO2
enrolment, and there is a graphical login. Every attempt needs a person at the
console. The Claude session also runs on this machine, so it does not survive a
reboot: after each boot, relaunch it and say "continue the boot matrix".

## Recovery — read before the first attempt

If the machine resets or freezes and will not boot cleanly:

1. At power on, GRUB shows a menu for 5 seconds. Press `e` on the Omarchy entry.
2. Append ` module_blacklist=apple_avd` to the line starting with `linux`.
3. Press Ctrl-X to boot once with the decoder disabled.
4. Once logged in, make it persistent:
   `sudo cp /usr/local/share/apple-avd-patched/apple-avd-disabled.conf.2026-09-14 /etc/modprobe.d/`
5. A freeze with no console response needs a long power-button hold. Unsaved work is lost.

This path was verified available before the campaign: GRUB `timeout_style=menu`,
`timeout=5`, entry editor reachable.

## Cells

Controls run first and are reviewed before any patched cell is proposed.

| Cell | Transition | Decoder configuration |
| --- | --- | --- |
| C1 | Graceful shutdown, 30 s powered off, power on | blacklisted control, decoder absent |
| C2 | Graceful warm reboot | blacklisted control, decoder absent |
| P1 | Same cold transition as C1 | patched module loading at boot |
| P2 | Same warm transition as C2 | patched module loading at boot |

Control config is `/etc/modprobe.d/apple-avd-noboot.conf` containing both
`blacklist apple_avd` and `install apple_avd /bin/false`. The `blacklist` line alone
stops udev/kmod autoload; `install ... /bin/false` also defeats an explicit modprobe.
A control attempt is valid only if `capture.sh` reports `module loaded: NO`.

The boot service `apple-avd-rebuild.service` is skipped at boot while
`/usr/lib/modules/$(uname -r)/updates/apple-avd.ko.patched-stamp` exists, and the
rebuild script does not modprobe. Patched cells restore the current configuration,
which is: no blacklist file present.

## Fixed conditions — hold constant across all attempts

AC connected, battery 100%, lid open, no external peripherals attached beyond the
existing setup, no video playing, no other agent's decoder workload running, network
up. Record any departure in the attempt record.

## Per attempt

1. Confirm no decode or guard workload is running (`lsmod | grep apple_avd` refcount 0,
   and no `hwguard`/`soak`/`frame-check` processes).
2. Make the transition for the cell (shutdown+30 s+power on, or reboot).
3. Type the LUKS passphrase, log in.
4. Run: `bash /home/chrisk/boot-matrix-13-20260919/capture.sh <CELL>`
   It records the post-boot snapshot, observes for 10 minutes, then records the
   post-window snapshot. Leave the machine idle during the window.
5. Relaunch Claude and say "continue the boot matrix".

If the machine resets during the window, the attempt record stays incomplete. That
incomplete file is the evidence; do not delete it. On the next boot run
`capture.sh` for the *next* attempt number and tell Claude — the PMU counter in the
new boot reports the previous boot's outcome.

## What the evidence means

`PMU logged N boot error(s) and M panic(s)` is emitted by the kernel at boot and only
when a counter is non-zero. Absence of the line means zero of both. This was the only
signal that fired for either original 2026-09-14 reset; a kernel journal alone
captured nothing. An attempt without this capture is `no discriminating evidence`,
not a clean boot.

Eight attempts is a screening campaign. Completing it without a reset does **not**
establish that the boot path is reliable, and does not close #13 or unblock #17.
