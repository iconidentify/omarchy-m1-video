#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Snapshot parser and predictors from copied controls plus pinned packing."""
from __future__ import annotations

import struct

OP_QP = 0x2d9 << 20
OP_DBLK = 0x2da << 20
OP_WT_HDR = 0x2dd << 20
CMD_PACKED = 1380
CMD_SITE_QP = 20
CMD_SITE_DBLK = 21
CMD_SITE_WT_HDR = 22
CMD_SITE_WT_SKIP = 27
CMD_SITE_SLICE_META = 31


class MissingInput(ValueError):
    pass


def _u8(b, i):
    return b[i], i + 1


def _s8(b, i):
    v = b[i]
    return (v - 256 if v > 127 else v), i + 1


def _u16(b, i):
    return b[i] | (b[i + 1] << 8), i + 2


def _u32(b, i):
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24), i + 4


def _s32(b, i):
    v, i = _u32(b, i)
    if v >= 2 ** 31:
        v -= 2 ** 32
    return v, i


def _u64(b, i):
    v = 0
    for k in range(8):
        v |= b[i + k] << (8 * k)
    return v, i + 8


def unpack_controls(buf):
    if buf is None or len(buf) < CMD_PACKED:
        raise MissingInput("control blob shorter than packed layout")
    i = 0
    c = {}
    c["video_parameter_set_id"], i = _u8(buf, i)
    c["seq_parameter_set_id"], i = _u8(buf, i)
    c["pic_width_in_luma_samples"], i = _u16(buf, i)
    c["pic_height_in_luma_samples"], i = _u16(buf, i)
    for name in ("bit_depth_luma_minus8", "bit_depth_chroma_minus8",
                 "log2_max_pic_order_cnt_lsb_minus4",
                 "sps_max_dec_pic_buffering_minus1", "sps_max_num_reorder_pics",
                 "sps_max_latency_increase_plus1",
                 "log2_min_luma_coding_block_size_minus3",
                 "log2_diff_max_min_luma_coding_block_size",
                 "log2_min_luma_transform_block_size_minus2",
                 "log2_diff_max_min_luma_transform_block_size",
                 "max_transform_hierarchy_depth_inter",
                 "max_transform_hierarchy_depth_intra",
                 "pcm_sample_bit_depth_luma_minus1",
                 "pcm_sample_bit_depth_chroma_minus1",
                 "log2_min_pcm_luma_coding_block_size_minus3",
                 "log2_diff_max_min_pcm_luma_coding_block_size",
                 "num_short_term_ref_pic_sets", "num_long_term_ref_pics_sps",
                 "chroma_format_idc", "sps_max_sub_layers_minus1"):
        c[name], i = _u8(buf, i)
    c["sps_flags"], i = _u64(buf, i)
    c["pic_parameter_set_id"], i = _u8(buf, i)
    c["num_extra_slice_header_bits"], i = _u8(buf, i)
    c["num_ref_idx_l0_default_active_minus1"], i = _u8(buf, i)
    c["num_ref_idx_l1_default_active_minus1"], i = _u8(buf, i)
    c["init_qp_minus26"], i = _s8(buf, i)
    c["diff_cu_qp_delta_depth"], i = _u8(buf, i)
    c["pps_cb_qp_offset"], i = _s8(buf, i)
    c["pps_cr_qp_offset"], i = _s8(buf, i)
    c["num_tile_columns_minus1"], i = _u8(buf, i)
    c["num_tile_rows_minus1"], i = _u8(buf, i)
    c["column_width_minus1"] = list(buf[i:i + 20]); i += 20
    c["row_height_minus1"] = list(buf[i:i + 22]); i += 22
    c["pps_beta_offset_div2"], i = _s8(buf, i)
    c["pps_tc_offset_div2"], i = _s8(buf, i)
    c["log2_parallel_merge_level_minus2"], i = _u8(buf, i)
    c["pps_flags"], i = _u64(buf, i)
    c["scaling_list_4x4"] = list(buf[i:i + 96]); i += 96
    c["scaling_list_8x8"] = list(buf[i:i + 384]); i += 384
    c["scaling_list_16x16"] = list(buf[i:i + 384]); i += 384
    c["scaling_list_32x32"] = list(buf[i:i + 128]); i += 128
    c["scaling_list_dc_coef_16x16"] = list(buf[i:i + 6]); i += 6
    c["scaling_list_dc_coef_32x32"] = list(buf[i:i + 2]); i += 2
    c["bit_size"], i = _u32(buf, i)
    c["data_byte_offset"], i = _u32(buf, i)
    c["num_entry_point_offsets"], i = _u32(buf, i)
    c["nal_unit_type"], i = _u8(buf, i)
    c["nuh_temporal_id_plus1"], i = _u8(buf, i)
    c["slice_type"], i = _u8(buf, i)
    c["colour_plane_id"], i = _u8(buf, i)
    c["slice_pic_order_cnt"], i = _s32(buf, i)
    c["num_ref_idx_l0_active_minus1"], i = _u8(buf, i)
    c["num_ref_idx_l1_active_minus1"], i = _u8(buf, i)
    c["collocated_ref_idx"], i = _u8(buf, i)
    c["five_minus_max_num_merge_cand"], i = _u8(buf, i)
    c["slice_qp_delta"], i = _s8(buf, i)
    c["slice_cb_qp_offset"], i = _s8(buf, i)
    c["slice_cr_qp_offset"], i = _s8(buf, i)
    c["slice_act_y_qp_offset"], i = _s8(buf, i)
    c["slice_act_cb_qp_offset"], i = _s8(buf, i)
    c["slice_act_cr_qp_offset"], i = _s8(buf, i)
    c["slice_beta_offset_div2"], i = _s8(buf, i)
    c["slice_tc_offset_div2"], i = _s8(buf, i)
    c["pic_struct"], i = _u8(buf, i)
    c["slice_segment_addr"], i = _u32(buf, i)
    c["ref_idx_l0"] = list(buf[i:i + 16]); i += 16
    c["ref_idx_l1"] = list(buf[i:i + 16]); i += 16
    c["short_term_ref_pic_set_size"], i = _u16(buf, i)
    c["long_term_ref_pic_set_size"], i = _u16(buf, i)
    c["slice_flags"], i = _u64(buf, i)
    c["luma_log2_weight_denom"], i = _u8(buf, i)
    c["delta_chroma_log2_weight_denom"], i = _s8(buf, i)
    i += 192  # weight arrays; named scalars above are enough for predictors
    c["decode_flags"], i = _u64(buf, i)
    if i != CMD_PACKED:
        raise MissingInput("packed length %d != %d" % (i, CMD_PACKED))
    return c


def pack_le(fields):
    """fields is a list of (kind, value) with kind in u8/s8/u16/u32/s32/u64/bytes."""
    out = bytearray()
    for kind, value in fields:
        if kind == "u8":
            out.append(value & 0xff)
        elif kind == "s8":
            out.append(value & 0xff)
        elif kind == "u16":
            out += struct.pack("<H", value & 0xffff)
        elif kind == "u32":
            out += struct.pack("<I", value & 0xffffffff)
        elif kind == "s32":
            out += struct.pack("<i", value)
        elif kind == "u64":
            out += struct.pack("<Q", value & ((1 << 64) - 1))
        elif kind == "bytes":
            out += bytes(value)
        else:
            raise MissingInput("bad pack kind")
    return bytes(out)


def predict_qp(ctrl):
    needed = ("init_qp_minus26", "slice_qp_delta", "pps_cb_qp_offset",
              "pps_cr_qp_offset", "slice_cb_qp_offset", "slice_cr_qp_offset")
    if any(k not in ctrl or ctrl[k] is None for k in needed):
        raise MissingInput("QP inputs missing")
    qp = (ctrl["init_qp_minus26"] + 26 + ctrl["slice_qp_delta"]) & 0xff
    cb = (ctrl["pps_cb_qp_offset"] + ctrl["slice_cb_qp_offset"]) & 0x1f
    cr = (ctrl["pps_cr_qp_offset"] + ctrl["slice_cr_qp_offset"]) & 0x1f
    return OP_QP | (qp << 10) | (cb << 5) | cr


def predict_dblk(ctrl):
    needed = ("slice_flags", "sps_flags", "pps_flags",
              "slice_tc_offset_div2", "slice_beta_offset_div2")
    if any(k not in ctrl or ctrl[k] is None for k in needed):
        raise MissingInput("deblock inputs missing")
    slf, spsf, ppsf = ctrl["slice_flags"], ctrl["sps_flags"], ctrl["pps_flags"]
    sao_c = slf & 2
    sao_l = slf & 1
    off0 = ctrl["slice_tc_offset_div2"] & 0xf
    off1 = ctrl["slice_beta_offset_div2"] & 0x1f
    en = (not (slf & 0x100)) and (
        (spsf & 0x100) or (slf & 1) or (ppsf & (1 << 19)) or (ppsf & (1 << 23)))
    word = OP_DBLK
    if sao_c:
        word |= 1 << 6
    if sao_l:
        word |= 1 << 7
    word |= (off0 & 0xf) << 8
    word |= (off1 & 0x1f) << 12
    if en:
        word |= 1 << 16
    return word


def parse_snapshot(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("H "):
        raise MissingInput("snapshot header missing")
    hdr = lines[0].split()
    if hdr[1] != "1":
        raise MissingInput("unsupported snapshot version")
    pictures = []
    windows = []
    i = 1
    while i < len(lines) and lines[i].startswith("P "):
        p = lines[i].split()
        pictures.append({"picture": int(p[1]), "poc": int(p[2]), "type": int(p[3]),
                         "target": int(p[4]), "flags": int(p[5]), "intra": int(p[6])})
        i += 1
    while i < len(lines) and lines[i].startswith("W "):
        wparts = lines[i].split()
        nwords = int(wparts[4])
        pairs = wparts[7:]
        if len(pairs) != 2 * nwords:
            raise MissingInput("window word/site extent mismatch")
        sites = [int(pairs[j]) for j in range(0, len(pairs), 2)]
        words = [int(pairs[j + 1]) for j in range(0, len(pairs), 2)]
        i += 1
        if i >= len(lines) or not lines[i].startswith("C "):
            raise MissingInput("window controls missing")
        ctrl = [int(x) for x in lines[i].split()[1:]]
        i += 1
        windows.append({
            "picture": int(wparts[1]), "poc": int(wparts[2]), "type": int(wparts[3]),
            "nwords": nwords, "nbytes": int(wparts[5]), "inactive": int(wparts[6]),
            "sites": sites, "words": words, "controls": ctrl,
        })
    if len(pictures) != 300:
        raise MissingInput("writer history is not 300 pictures")
    return {"header": hdr, "pictures": pictures, "windows": windows}


def window_ok(row, expected=None):
    if expected is None:
        expected = row.get("expected")
    if expected is None:
        raise MissingInput("no expected words")
    if row.get("sites") and row.get("expected_sites") and row["sites"] != row["expected_sites"]:
        return False
    return row.get("words") == expected and row.get("nwords") == len(expected)


def classify_weights(row):
    skip = 1 << (CMD_SITE_WT_SKIP % 32)
    if row.get("inactive", 0) & skip:
        return "skipped"
    if row.get("inactive") and not (row.get("inactive", 0) & skip):
        # Some other inactive bit is not a weight skip.
        pass
    n = row.get("nwords") or 0
    if n == 0:
        raise MissingInput("weights neither skipped nor present")
    if n == 1 and (row.get("words") or [0])[0] >> 20 == 0x2dd:
        return "default-header"
    return "weighted"


def scaling_word_count():
    return 1 + 2 + 2 + 24 + 96 + 96 + 32
