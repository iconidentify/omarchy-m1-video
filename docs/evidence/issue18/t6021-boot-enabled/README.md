# t6021 boot-enabled patched AVD, 2026-09-17

The contributor reports one consented reboot after installation and one
successful login. This is not a boot matrix or closure of the reset tickets.

The reported previous shutdown was **2026-09-17 06:40:20 UTC**. The included
four-line startup excerpt is timestamped **2026-09-17 09:12:39 UTC** and shows
an out-of-tree AVD module initializing with hardware version 30010. The
operator attributes the gap to waiting at LUKS while away. Original shutdown,
consent, full journal-window and pstore records are not included, so the gap's
cause and absence of faults are not independently established by this bundle.
See the [maintainer assessment](../t6021-followup-review.md).

## Reported selection and observed startup

| Item | Value |
| --- | --- |
| Selected module | `/lib/modules/7.1.13-3-1-ARCH/updates/apple-avd.ko` |
| SHA-256 | `27f9cfa4aef2842fd0a18ee794a68924e6b9092af10635de5d13f2867c96c5d6` |
| Stamp | `tag=asahi-7.1.13-3 patches=029f57377a00` |
| Taint | startup excerpt reports an out-of-tree load; selected binary identity remains unverified |
| Hardware version | startup excerpt: 30010 |
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

The contributor attributes the full Fluster suites to the installed stack
**before** this reboot. Those suites are not repeated in the post-boot records. See
[t6021-installed-stack](../t6021-installed-stack/README.md).
