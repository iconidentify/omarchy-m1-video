#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract HEVC control field reads from named functions in patched avd-hevc.c."""
from __future__ import annotations

import re
from pathlib import Path

TARGETS = (
    "set_scaling_lists",
    "hevc_set_flags",
    "set_header",
    "stream_weights",
    "stream_slice_dqtblk",
    "set_slice",
    "submit_slice_segment",
    "stream_slices",
    "compute_tiles_uniform",
    "compute_tiles_non_uniform",
    "compute_bd",
    "compute_rs_to_ts",
    "compute_tile_ids",
)

# Already measured by companion #61 / schema-2 campaign.
MEASURED = (
    "stream_refs",
    "stream_slice_mv",
)

FIELD = re.compile(
    r"""(?x)
    (?:
        (?:sps|pps|decode|sl|s|pred)->([A-Za-z_][A-Za-z0-9_]*)
        | run->sl\[0\]\.([A-Za-z_][A-Za-z0-9_]*)
        | run->([A-Za-z_][A-Za-z0-9_]*)
        | sl->pred_weight_table\.([A-Za-z_][A-Za-z0-9_]*)
        | ctx->decomp
        | ctx->decoded_fmt
        | avd->variant
    )
    """
)


def functions(text: str):
    lines = text.splitlines()
    starts = []
    for i, line in enumerate(lines):
        for name in TARGETS + MEASURED:
            if re.search(r"\b%s\s*\(" % re.escape(name), line) and (
                "static" in line or i > 0 and "static" in lines[i - 1]
            ):
                starts.append((i, name))
    starts.sort()
    out = {}
    for idx, (start, name) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        # clip to next function that is actually a definition at column 0-ish
        body_end = end
        for j in range(start + 1, end):
            if lines[j].startswith("static ") and "(" in lines[j]:
                body_end = j
                break
        out[name] = "\n".join(lines[start:body_end])
    return out


def fields_in(body: str):
    found = set()
    for match in FIELD.finditer(body):
        for group in match.groups():
            if group:
                found.add(group)
    if "ctx->decomp" in body:
        found.add("ctx.decomp")
    if "ctx->decoded_fmt" in body:
        found.add("ctx.decoded_fmt")
    if "avd->variant" in body:
        found.add("avd.variant")
    return sorted(found)


def scan(path: Path):
    text = path.read_text()
    funcs = functions(text)
    missing = [name for name in TARGETS if name not in funcs]
    if missing:
        raise SystemExit("functions not found: %s" % ", ".join(missing))
    return {name: fields_in(funcs[name]) for name in TARGETS}
