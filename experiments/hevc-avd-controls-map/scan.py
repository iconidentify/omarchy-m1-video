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
    "avd_hevc_compute_tiles",
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
    # Narrow, hash-locked C source scanner, not a general C parser. Mask
    # comments/strings before matching balanced function braces.
    clean = mask(text)
    out = {}
    for name in TARGETS + MEASURED:
        matches = list(re.finditer(r'\bstatic\s+[^;{}]*?\b'+name+r'\s*\([^;{}]*?\)\s*\{', clean))
        if len(matches) != 1:
            raise ValueError('missing/duplicate function: '+name)
        m = matches[0]; start = m.start(); depth = 1
        for j in range(m.end(), len(clean)):
            depth += (clean[j] == '{') - (clean[j] == '}')
            if depth == 0:
                out[name] = clean[start:j+1]
                break
        else:
            raise ValueError('unclosed function: '+name)
    return out


def mask(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"',
                  lambda m: re.sub(r'[^\n]', ' ', m.group()), text, flags=re.S)


def coverage(text):
    """Exact function-local expressions, flag constants, calls and source lines."""
    clean = mask(text); result = {}
    for name, body in functions(text).items():
        if name not in TARGETS:
            continue
        start = clean.index(body); line = clean[:start].count('\n')+1
        reads = {}
        for m in re.finditer(r'\b(?:sps|pps|decode|sl|s|pred|run|ctx|avd)->[A-Za-z_]\w*(?:\s*\[[^\]]*\])?(?:\s*\.\s*[A-Za-z_]\w*)*', body):
            key = re.sub(r'\s+', '', m.group())
            reads.setdefault(key, []).append(line+body[:m.start()].count('\n'))
        inner = body[body.index('{')+1:]
        calls = set(re.findall(r'\b([A-Za-z_]\w*)\s*\(',inner))-{'if','for','while','switch','sizeof'}
        flags = sorted(set(re.findall(r'\bV4L2_HEVC_[A-Z0-9_]+',body)))
        result[name] = dict(first_line=line,last_line=line+body.count('\n'),
                            members=fields_in(body),reads=reads,calls=sorted(calls),flags=flags)
    return result


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
