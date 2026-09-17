# t6021 installed omarchy-m1-video stack, 2026-09-17

Boot-risk accepted. `./install.sh --i-accept-boot-risk` was run from
`a88d45cc74ec41d0e95ace3763900137d2ce9b19`. The patched module was then loaded
with `modprobe` **before** any reboot. This is still experimental: AVC/FRExt/VP9
full Fluster suites were waiting on corpus download when this record was written.

## Installed identities

| Item | Value |
| --- | --- |
| Package | `libva-v4l2_request-avd 1.3.r11-2` (PKGBUILD `_commit=db3014f9499694c6f186af7e023de07bd5bc3564`) |
| Stripped library SHA-256 | `a9d6225e0fd348ca22fd738cb2367d7835d7cda1f789ba7b5aae278b32b6729b` |
| Marker | `v4l2-request (omarchy-m1-video 1.3.r11)` |
| Module | `/lib/modules/7.1.13-3-1-ARCH/updates/apple-avd.ko` SHA-256 `27f9cfa4aef2842fd0a18ee794a68924e6b9092af10635de5d13f2867c96c5d6` |
| Stamp | `tag=asahi-7.1.13-3 patches=029f57377a00` |
| Taint | `O` |
| Boot service | `apple-avd-rebuild.service` enabled; no reboot yet |
| Device | `apple,j416c` / `apple,t6021` |

`vainfo --display drm`: H.264 Constrained Baseline/Main/High, HEVC Main/Main10, VP9 0/2.

## Results so far

| Check | Result |
| --- | --- |
| HEVC `JCT-VC-HEVC_V1` | **144/147**, exact r11 pass set (`compare-results.py` `ok: true`). Fails: `RPS_E_qualcomm_5`, `TSUNEQBD_A_MAIN10_Technicolor_2`, `VPSSPSPPS_A_MainConcept_1` |
| `hwdownload.sh` 8+10-bit | pass (240 hardware frames vs software; MAIN10 clip `WPP_C_ericsson_MAIN10_2`) |
| `early-export.sh` | pass (H.264/HEVC/VP9 normal+early) |
| `shared-contexts.sh` | pass (168+168 frames) |
| `h264-high10.sh` | pass (144 frames) |
| `vp9-matrix.sh` | pass (384 frames) |
| VP9 HIGH `vp92-2-20-10bit-yuv420.webm` | hardware_pass, 1/1 |
| mpv `--hwdec=vaapi --gpu-api=opengl --vo=gpu-next` | `Using hardware decoding (vaapi)`, `VO: [gpu-next] 640x360 vaapi[nv12]` |
| AVC / FRExt / VP9-TEST-VECTORS full suites | not yet run (corpus still downloading) |
| Boot-enabled load | not yet: module loaded by `modprobe`, reboot still pending |

Guard child-error on HEVC is expected: `conformance.py` exits 1 when 3/147 fail, matching r11.
No wedge, timeout, or new AVD kernel fault.
