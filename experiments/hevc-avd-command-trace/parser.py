#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare selected command words to copied controls using pinned packing."""
from __future__ import annotations

OP_QP = 0x2d9 << 20
OP_DBLK = 0x2da << 20
OP_WT_HDR = 0x2dd << 20


class MissingInput(ValueError):
    pass


def predict_qp(ctrl):
    needed = ("init_qp_minus26", "slice_qp_delta", "pps_cb_qp_offset",
              "pps_cr_qp_offset", "slice_cb_qp_offset", "slice_cr_qp_offset")
    if any(k not in ctrl or ctrl[k] is None for k in needed):
        raise MissingInput("QP inputs missing")
    qp = (ctrl["init_qp_minus26"] + 26 + ctrl["slice_qp_delta"]) & 0xff
    cb = (ctrl["pps_cb_qp_offset"] + ctrl["slice_cb_qp_offset"]) & 0x1f
    cr = (ctrl["pps_cr_qp_offset"] + ctrl["slice_cr_qp_offset"]) & 0x1f
    return OP_QP | (qp << 10) | (cb << 5) | cr


def window_ok(row):
    expected = row.get("expected")
    if expected is None:
        raise MissingInput("no expected words")
    return row.get("words") == expected and row.get("nwords") == len(expected)


def classify_weights(row):
    if row.get("inactive"):
        return "skipped"
    n = row.get("nwords") or 0
    if n == 0:
        raise MissingInput("weights neither skipped nor present")
    if n == 1 and (row.get("words") or [0])[0] >> 20 == 0x2dd:
        return "default-header"
    return "weighted"
