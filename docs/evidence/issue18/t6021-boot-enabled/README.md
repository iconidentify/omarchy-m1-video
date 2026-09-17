# t6021 boot-enabled patched AVD, 2026-09-17

One consented reboot after `./install.sh --i-accept-boot-risk`. This is **one
successful login**, not a boot matrix and not closure of the unexplained-reset
tickets.

Previous boot ended in an orderly `shutdown -r` at **2026-09-17 06:40:20 UTC**.
This boot's journal starts at **2026-09-17 09:12:39 UTC**. The wall-clock gap is
the LUKS unlock prompt while the operator was away, not a hang or hard reset.
`/sys/fs/pstore` was empty. This boot's kernel AVD window has no H2/H3, oops or
panic lines.

## What loaded

| Item | Value |
| --- | --- |
| Selected module | `/lib/modules/7.1.13-3-1-ARCH/updates/apple-avd.ko` |
| SHA-256 | `27f9cfa4aef2842fd0a18ee794a68924e6b9092af10635de5d13f2867c96c5d6` |
| Stamp | `tag=asahi-7.1.13-3 patches=029f57377a00` |
| Taint | `O` (out-of-tree loaded at boot) |
| Firmware | `avd 287080000.avd: booting hw version: 30010` |
| Userspace | `libva-v4l2_request-avd 1.3.r11-2` |
| Rebuild service | enabled; skipped because the stamp already existed |

`loaded_binary_sha256` remains unknown: sysfs cannot certify that the running
bytes equal the on-disk file.

## Post-boot guarded checks

| Check | Result |
| --- | --- |
| Idle preflight | pass |
| `vainfo --display drm` | H.264 ConstrainedBaseline/Main/High, HEVC Main/Main10, VP9 0/2, marker `1.3.r11` |
| HEVC `AMP_A_Samsung_7` | hardware_pass, 17 frames, 2560x1600, bit-exact |
| AVC `AUD_MW_E` | hardware_pass, 100 frames, 176x144, bit-exact |
| VP9 `vp90-2-00-quantizer-00.webm` | hardware_pass, 2 frames, 352x288, bit-exact |
| mpv OpenGL VA-API | `Using hardware decoding (vaapi)` |

Full Fluster suites were run on this same installed stack **before** the reboot
and are not repeated here. See
[t6021-installed-stack](../t6021-installed-stack/README.md).
