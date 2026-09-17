#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline H.264 VA-API profile-selection prototype (omarchy-m1-video#41).

Models FFmpeg n9.0.1 vaapi_decode.c matching against a stubbed VA profile
list. Distinguishes current exact-match refusal from a feature-aware remap.
A selected VA profile is not a decoded frame and not hardware evidence.
"""
from __future__ import annotations

SCHEMA = "omarchy-m1-video.h264-profile-selection/1"

# FFmpeg n9.0.1 libavcodec/vaapi_decode.c vaapi_profile_map, H.264 rows only,
# in source order. Baseline (66) and Extended (88) are absent.
VAAPI_PROFILE_MAP = (
    ("H264_HIGH_10_INTRA", "VAProfileH264High10"),
    ("H264_HIGH_10", "VAProfileH264High10"),
    ("H264_CONSTRAINED_BASELINE", "VAProfileH264ConstrainedBaseline"),
    ("H264_MAIN", "VAProfileH264Main"),
    ("H264_HIGH", "VAProfileH264High"),
)

DEFAULT_ADVERTISED = (
    "VAProfileH264ConstrainedBaseline",
    "VAProfileH264Main",
    "VAProfileH264High",
    "VAProfileH264High10",
)

# Driver libva-v4l2_request src/codec_h264.c h264_profiles at b9803ed.
DRIVER_ADVERTISED = DEFAULT_ADVERTISED

FFMPEG_COMMIT = "bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa"
FFMPEG_TAG = "n9.0.1"
DRIVER_COMMIT = "b9803ed5290ecb4b48c09482cbc6e943aee08b63"

SLICE_TYPE_NAMES = {"I", "P", "B", "SP", "SI"}
SLICE_SET_IP = frozenset({"I", "P"})
SLICE_SET_IPB = frozenset({"I", "P", "B"})

# Advertised VA profiles accept these FFmpeg profiles as a subset, not an upgrade.
VA_PROFILE_ALLOWED_FF = {
    "VAProfileH264ConstrainedBaseline": {
        "H264_BASELINE", "H264_CONSTRAINED_BASELINE",
    },
    "VAProfileH264Main": {
        "H264_BASELINE", "H264_CONSTRAINED_BASELINE", "H264_MAIN", "H264_EXTENDED",
    },
    "VAProfileH264High": {
        "H264_BASELINE", "H264_CONSTRAINED_BASELINE", "H264_MAIN", "H264_EXTENDED",
        "H264_HIGH",
    },
    "VAProfileH264High10": {
        "H264_BASELINE", "H264_CONSTRAINED_BASELINE", "H264_MAIN", "H264_EXTENDED",
        "H264_HIGH", "H264_HIGH_10", "H264_HIGH_10_INTRA",
    },
}

VA_PROFILE_MAX_BIT_DEPTH_MINUS8 = {
    "VAProfileH264ConstrainedBaseline": 0,
    "VAProfileH264Main": 0,
    "VAProfileH264High": 0,
    "VAProfileH264High10": 2,
}

DEFAULT_CHECKS = {
    "fmo": True,
    "fields": True,
    "partitions": True,
    "malformed": True,
    "scan_all_pictures": True,
    "forbid_blanket_mismatch": True,
    "sps_compat": True,
    "slice_types": True,
}


class FixtureError(ValueError):
    pass


def ffmpeg_profile_from_sps(sps):
    """FFmpeg ff_h264_get_profile: 66+constraint_set1 is Constrained Baseline."""
    if not sps.get("parse_ok", True):
        return None
    pidc = sps["profile_idc"]
    cs1 = bool(sps.get("constraint_set1_flag", 0))
    if pidc == 66:
        return "H264_CONSTRAINED_BASELINE" if cs1 else "H264_BASELINE"
    if pidc == 77:
        return "H264_MAIN"
    if pidc == 88:
        return "H264_EXTENDED"
    if pidc == 100:
        return "H264_HIGH"
    if pidc == 110:
        intra = bool(sps.get("constraint_set3_flag", 0))
        return "H264_HIGH_10_INTRA" if intra else "H264_HIGH_10"
    return "H264_UNKNOWN_%s" % pidc


def vaapi_current_match(ff_profile, advertised, allow_profile_mismatch):
    """Reproduce vaapi_decode_make_config exact-match / mismatch behaviour."""
    advertised = tuple(advertised)
    matched_va = None
    matched_ff = None
    exact = False
    for map_ff, map_va in VAAPI_PROFILE_MAP:
        profile_match = ff_profile == map_ff
        if map_va not in advertised:
            continue
        exact = profile_match
        matched_va = map_va
        matched_ff = map_ff
        if exact:
            break
    if matched_va is None:
        return {
            "status": "refuse",
            "reason": "no_h264_va_profile_advertised",
            "va_profile": None,
            "ffmpeg_profile": ff_profile,
            "exact_match": False,
        }
    if exact:
        return {
            "status": "select",
            "reason": "exact_profile_match",
            "va_profile": matched_va,
            "ffmpeg_profile": ff_profile,
            "exact_match": True,
        }
    if allow_profile_mismatch:
        return {
            "status": "select",
            "reason": "allow_profile_mismatch",
            "va_profile": matched_va,
            "ffmpeg_profile": ff_profile,
            "exact_match": False,
            "mismatch_uses": matched_ff,
        }
    return {
        "status": "refuse",
        "reason": "profile_mismatch",
        "va_profile": None,
        "ffmpeg_profile": ff_profile,
        "exact_match": False,
        "would_mismatch_to": matched_va,
    }


def _nal_is_partition(nal_unit_type):
    return nal_unit_type in (2, 3, 4)


def picture_disallowed(picture, checks):
    """Return a feature reason string or None. Does not decode."""
    sps = picture.get("sps") or {}
    pps = picture.get("pps") or {}
    slices = picture.get("slices") or []
    if checks.get("malformed", True):
        if not sps.get("parse_ok", True) or not pps.get("parse_ok", True):
            return "malformed_header"
        if any(not s.get("parse_ok", True) for s in slices):
            return "malformed_header"
        for s in slices:
            if s.get("slice_type") not in SLICE_TYPE_NAMES:
                return "malformed_header"
    if checks.get("partitions", True):
        for s in slices:
            if _nal_is_partition(int(s.get("nal_unit_type", 1))):
                return "data_partition"
    if checks.get("fmo", True):
        if int(pps.get("num_slice_groups_minus1", 0) or 0) > 0:
            return "fmo"
    if checks.get("fields", True):
        if not int(sps.get("frame_mbs_only_flag", 1)):
            return "fields"
        if int(sps.get("mb_adaptive_frame_field_flag", 0) or 0):
            return "fields"
        if any(int(s.get("field_pic_flag", 0) or 0) for s in slices):
            return "fields"
    return None


def allowed_slices_for_ff_profile(ff_profile):
    """I/P for Baseline/CB remaps; I/P/B for Main/Extended/High. Never SP/SI."""
    if ff_profile in ("H264_BASELINE", "H264_CONSTRAINED_BASELINE"):
        return SLICE_SET_IP
    return SLICE_SET_IPB


def picture_slice_disallowed(picture, ff_profile):
    """Return a slice-set reason or None. SP/SI are outside every advertised subset."""
    allowed = allowed_slices_for_ff_profile(ff_profile)
    for s in picture.get("slices") or []:
        kind = s.get("slice_type")
        if kind == "SP":
            return "sp_slice"
        if kind == "SI":
            return "si_slice"
        if kind == "B" and "B" not in allowed:
            return "baseline_with_b_slices"
        if kind not in allowed:
            return "disallowed_slice"
    return None


def sps_incompatible_with_va(sps, va_profile):
    """True when this SPS cannot stay on the already-selected VA subset."""
    ff = ffmpeg_profile_from_sps(sps)
    allowed_ff = VA_PROFILE_ALLOWED_FF.get(va_profile)
    if not allowed_ff or ff not in allowed_ff:
        return "sps_incompatible"
    luma = int(sps.get("bit_depth_luma_minus8", 0) or 0)
    chroma_depth = int(sps.get("bit_depth_chroma_minus8", 0) or 0)
    max_depth = VA_PROFILE_MAX_BIT_DEPTH_MINUS8.get(va_profile, 0)
    if luma > max_depth or chroma_depth > max_depth:
        return "sps_incompatible"
    chroma = sps.get("chroma_format_idc", 1)
    if chroma is None:
        chroma = 1
    if int(chroma) != 1:
        return "sps_incompatible"
    return None


def _has_b_slice(pictures):
    for pic in pictures:
        for s in pic.get("slices") or []:
            if s.get("slice_type") == "B":
                return True
    return False


def proposed_va_for_safe_stream(ff_profile, pictures):
    """Map a stream with no FMO/fields/partitions onto an advertised subset."""
    has_b = _has_b_slice(pictures)
    if ff_profile == "H264_CONSTRAINED_BASELINE":
        return "VAProfileH264ConstrainedBaseline", "exact_profile_match"
    if ff_profile == "H264_MAIN":
        return "VAProfileH264Main", "exact_profile_match"
    if ff_profile == "H264_HIGH":
        return "VAProfileH264High", "exact_profile_match"
    if ff_profile in ("H264_HIGH_10", "H264_HIGH_10_INTRA"):
        return "VAProfileH264High10", "exact_profile_match"
    if ff_profile == "H264_BASELINE" and not has_b:
        return "VAProfileH264ConstrainedBaseline", "baseline_constrained_subset"
    if ff_profile == "H264_BASELINE" and has_b:
        return None, "baseline_with_b_slices"
    if ff_profile == "H264_EXTENDED":
        return "VAProfileH264Main", "extended_main_subset"
    return None, "unmapped_profile"


def select_current(stream, advertised=None, allow_profile_mismatch=False):
    pictures = stream["pictures"]
    if not pictures:
        raise FixtureError("stream has no pictures")
    ff_profile = ffmpeg_profile_from_sps(pictures[0]["sps"])
    advertised = advertised if advertised is not None else stream.get(
        "advertised", DEFAULT_ADVERTISED)
    allow = bool(stream.get("allow_profile_mismatch", allow_profile_mismatch))
    result = vaapi_current_match(ff_profile, advertised, allow)
    result["path"] = "current"
    result["decoded_frame_evidence"] = False
    return result


def select_proposed(stream, advertised=None, checks=None):
    pictures = stream["pictures"]
    if not pictures:
        raise FixtureError("stream has no pictures")
    checks = dict(DEFAULT_CHECKS if checks is None else checks)
    advertised = tuple(
        advertised if advertised is not None else stream.get(
            "advertised", DEFAULT_ADVERTISED)
    )
    ff_profile = ffmpeg_profile_from_sps(pictures[0]["sps"])
    scan = pictures if checks.get("scan_all_pictures", True) else pictures[:1]

    def _reject(reason, picture_index=None):
        result = {
            "status": "reject",
            "reason": reason,
            "va_profile": None,
            "ffmpeg_profile": ff_profile,
            "exact_match": False,
            "path": "proposed",
            "decoded_frame_evidence": False,
        }
        if picture_index is not None:
            result["picture_index"] = picture_index
        return result

    for index, picture in enumerate(scan):
        reason = picture_disallowed(picture, checks)
        if reason:
            return _reject(reason, index)
        if checks.get("slice_types", True):
            reason = picture_slice_disallowed(picture, ff_profile)
            if reason:
                return _reject(reason, index)
    va_profile, why = proposed_va_for_safe_stream(ff_profile, scan)
    if va_profile is None:
        return _reject(why)
    if checks.get("sps_compat", True):
        for index, picture in enumerate(scan):
            reason = sps_incompatible_with_va(picture.get("sps") or {}, va_profile)
            if reason:
                return _reject(reason, index)
    if va_profile not in advertised:
        return {
            "status": "reject",
            "reason": "va_profile_not_advertised",
            "va_profile": None,
            "ffmpeg_profile": ff_profile,
            "wanted_va_profile": va_profile,
            "path": "proposed",
            "decoded_frame_evidence": False,
        }
    exact = why == "exact_profile_match"
    return {
        "status": "select",
        "reason": why,
        "va_profile": va_profile,
        "ffmpeg_profile": ff_profile,
        "exact_match": exact,
        "path": "proposed",
        "decoded_frame_evidence": False,
    }


def run_fixture(doc, checks=None):
    if not isinstance(doc, dict):
        raise FixtureError("fixture is not an object")
    if doc.get("schema") != SCHEMA:
        raise FixtureError("unsupported or missing schema")
    path = doc.get("path")
    if path not in ("current", "proposed"):
        raise FixtureError("path must be current or proposed")
    if "pictures" not in doc or not isinstance(doc["pictures"], list):
        raise FixtureError("pictures must be a list")
    expected = doc.get("expected")
    if not isinstance(expected, dict) or "status" not in expected:
        raise FixtureError("expected.status is required")
    advertised = doc.get("advertised", list(DEFAULT_ADVERTISED))
    if path == "current":
        if doc.get("allow_profile_mismatch") and (
                checks or DEFAULT_CHECKS).get("forbid_blanket_mismatch", True):
            # Current path may still *model* mismatch; proposed tests must not
            # treat it as the recommended default.
            pass
        got = select_current(doc, advertised=advertised)
    else:
        got = select_proposed(doc, advertised=advertised, checks=checks)
    ok = got.get("status") == expected.get("status")
    if "va_profile" in expected:
        ok = ok and got.get("va_profile") == expected.get("va_profile")
    if "reason" in expected:
        ok = ok and got.get("reason") == expected.get("reason")
    got["ok"] = ok
    got["id"] = doc.get("id")
    got["classification"] = doc.get("classification")
    got["evidence_class"] = "model_not_decoded_frames"
    return got
