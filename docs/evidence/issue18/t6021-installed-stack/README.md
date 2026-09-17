# t6021 installed omarchy-m1-video stack, 2026-09-17

The contributor reports accepting boot risk, running the installer from
`a88d45cc74ec41d0e95ace3763900137d2ce9b19`, and loading the patched module
before recording these suites and later rebooting. Original installation,
load and consent logs are not included. See the [maintainer assessment](../t6021-followup-review.md)
for verified artifact content and attribution limits. This remains experimental.

## Contributor-reported installed identities

| Item | Value |
| --- | --- |
| Package | `libva-v4l2_request-avd 1.3.r11-2` (PKGBUILD `_commit=db3014f9499694c6f186af7e023de07bd5bc3564`) |
| Stripped library SHA-256 | `a9d6225e0fd348ca22fd738cb2367d7835d7cda1f789ba7b5aae278b32b6729b` |
| Marker | `v4l2-request (omarchy-m1-video 1.3.r11)` |
| Module | `/lib/modules/7.1.13-3-1-ARCH/updates/apple-avd.ko` SHA-256 `27f9cfa4aef2842fd0a18ee794a68924e6b9092af10635de5d13f2867c96c5d6` |
| Stamp | `tag=asahi-7.1.13-3 patches=029f57377a00` |
| Taint | `O` |
| Boot service | `apple-avd-rebuild.service` enabled; one later consented reboot is recorded in [t6021-boot-enabled](../t6021-boot-enabled/README.md) |
| Device | `apple,j416c` / `apple,t6021` |

`vainfo --display drm`: H.264 Constrained Baseline/Main/High, HEVC Main/Main10, VP9 0/2.

## Submitted results and reported checks

| Check | Result |
| --- | --- |
| HEVC `JCT-VC-HEVC_V1` | **144/147**, exact r11 pass set (`compare-results.py` `ok: true`). Fails: `RPS_E_qualcomm_5`, `TSUNEQBD_A_MAIN10_Technicolor_2`, `VPSSPSPPS_A_MainConcept_1` |
| AVC `JVT-AVC_V1` | **73/135**, same pass set as r11 (`lost_passes` empty). Comparator `ok: false` only because `FM1_FT_E` changed from `decode_error` to `software_fallback` (still not a pass) |
| VP9 `VP9-TEST-VECTORS` | **216/305**, exact r11 pass set (`ok: true`) |
| `hwdownload.sh` 8+10-bit | pass (240 hardware frames vs software; MAIN10 clip `WPP_C_ericsson_MAIN10_2`) |
| `early-export.sh` | pass (H.264/HEVC/VP9 normal+early) |
| `shared-contexts.sh` | pass (168+168 frames) |
| `h264-high10.sh` | pass (144 frames) |
| `vp9-matrix.sh` | pass (384 frames) |
| VP9 HIGH `vp92-2-20-10bit-yuv420.webm` | hardware_pass, 1/1 |
| mpv `--hwdec=vaapi --gpu-api=opengl --vo=gpu-next` | `Using hardware decoding (vaapi)`, `VO: [gpu-next] 640x360 vaapi[nv12]` |
| FRExt `JVT-FR-EXT` (High 10 mode) | **27/69**, exact r11 pass set (`ok: true`) |
| Boot-enabled load | one contributor-reported login after `shutdown -r`; operator reports a LUKS wait during the 06:40–09:12 gap; see [t6021-boot-enabled](../t6021-boot-enabled/README.md) |

All four full-suite guards end `child-error` / exit 1, consistent with their
non-passing vectors; the other published guards end `ok` / exit 0. Every final
guard row reports idle, no timeout/wedge and no abort reason. Full journal
coverage and raw export/lifecycle output are not included; their detailed
counts and absence of new kernel faults remain contributor reports. The HEVC
pass set matches while two non-pass categories change to checksum mismatch.
The AVC comparator remains non-green because software fallback is present.
