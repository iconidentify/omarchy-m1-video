#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive bounded campaign targets and Gst capacity from locked evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "omarchy.hevc.target-evidence/v1"
ASSOCIATION_SHA256 = {
    ("gst", "B"): "ecf96ada51bb2ca854b4442f1810ed597fcd66ca8ea46ae263c20c130f191875",
    ("gst", "E"): "b86f1c3411ecf68f62b10bf69cb52a5a88f2ac4ca95e539f0dff4881b2ee6a03",
    ("va", "B"): "5e36692af48ff06345c6d288ae290e6daadb4fa9522ef4a871ef387e0a0b32dd",
    ("va", "E"): "d25b9c19de2f3e387d255d711d380f3fd8a424f730b686fb141f2436381318dc",
}
SELECTED_OUTPUTS = {
    ("gst", "B"): (20,),
    ("gst", "E"): (26, 28, 29),
    ("va", "B"): (20,),
    ("va", "E"): (31, 73, 74),
}


class TargetError(ValueError):
    pass


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise TargetError(reason)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_association(path: Path, client: str, vector: str) -> list[dict]:
    expected = ASSOCIATION_SHA256[(client, vector)]
    need(digest(path) == expected, f"{client}/{vector} association hash drift")
    value = json.loads(path.read_text())
    need(type(value) is list and len(value) == 300,
         f"{client}/{vector} association must contain 300 outputs")
    need([row.get("output_index") for row in value] == list(range(300)),
         f"{client}/{vector} output indices are not complete and ordered")
    return value


def gst_ordinary_pool(path: Path) -> tuple[int, dict[str, object]]:
    # v4l2-tracer serializes unused ioctl padding as display strings; historical
    # private traces can therefore contain non-UTF-8 bytes outside the fields
    # consumed here. Replacement is deterministic and the raw-byte digest stays
    # authoritative.
    trace = json.loads(path.read_text(errors="replace"))
    need(type(trace) is list, "Gst trace is not an event array")
    indices: list[int] = []
    for event in trace:
        if type(event) is not dict or event.get("ioctl") != "VIDIOC_CREATE_BUFS" or \
                "errno" in event:
            continue
        user = event.get("from_userspace", {}).get("v4l2_create_buffers", {})
        driver = event.get("from_driver", {}).get("v4l2_create_buffers", {})
        format_ = driver.get("format", {})
        if format_.get("type") != "V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE":
            continue
        if user.get("count") == 1 and driver.get("count") == 1:
            index = driver.get("index")
            need(type(index) is int and index >= 0, "invalid Gst capture allocation index")
            indices.append(index)
    need(indices == list(range(len(indices))) and indices,
         "Gst capture allocations are not one contiguous initial pool")
    return len(indices), {
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "capture_create_indices": indices,
    }


def parameter_set_evidence(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    starts: list[tuple[int, int]] = []
    index = 0
    while index + 3 <= len(raw):
        if raw[index:index + 4] == b"\x00\x00\x00\x01":
            starts.append((index, 4)); index += 4
        elif raw[index:index + 3] == b"\x00\x00\x01":
            starts.append((index, 3)); index += 3
        else:
            index += 1
    need(starts, "stream has no Annex-B NAL units")
    types: list[int] = []
    for number, (start, prefix) in enumerate(starts):
        end = starts[number + 1][0] if number + 1 < len(starts) else len(raw)
        need(start + prefix < end, "empty Annex-B NAL unit")
        types.append((raw[start + prefix] >> 1) & 0x3f)
    need(all(value in types for value in (32, 33, 34)),
         "stream lacks initial VPS/SPS/PPS")
    first_vcl = next((number for number, value in enumerate(types) if value <= 31), None)
    need(first_vcl is not None, "stream has no VCL NAL units")
    late = [{"nal_index": number, "nal_type": value}
            for number, value in enumerate(types)
            if number > first_vcl and value in (32, 33, 34)]
    need(not late, "stream has an in-band parameter-set NAL after decoding begins")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "nal_units": len(types),
        "initial_parameter_set_types": sorted({value for value in types[:first_vcl]
                                                if value in (32, 33, 34)}),
        "parameter_set_nals_after_first_vcl": late,
    }


def derive(association_root: Path, gst_traces: dict[str, Path],
           streams: dict[str, Path]) -> dict:
    associations: dict[tuple[str, str], list[dict]] = {}
    association_sources: dict[str, dict[str, object]] = {}
    for vector in ("B", "E"):
        for client in ("gst", "va"):
            path = association_root / f"{vector}-{client}.json"
            associations[(client, vector)] = read_association(path, client, vector)
            association_sources[f"{vector}-{client}"] = {
                "path": f"experiments/hevc-controls/captures/2026-09-17/associations/{vector}-{client}.json",
                "sha256": ASSOCIATION_SHA256[(client, vector)],
                "outputs": 300,
            }

    ordinary: dict[str, int] = {}
    trace_sources: dict[str, dict[str, object]] = {}
    for vector in ("B", "E"):
        ordinary[vector], source = gst_ordinary_pool(gst_traces[vector])
        source["private_name"] = gst_traces[vector].name
        source["ordinary_pool_size"] = ordinary[vector]
        trace_sources[vector] = source

    stream_sources = {vector: parameter_set_evidence(streams[vector])
                      for vector in ("B", "E")}

    targets: list[dict[str, object]] = []
    selected_records: dict[str, list[dict]] = {}
    for vector in ("B", "E"):
        for client in ("gst", "va"):
            rows = associations[(client, vector)]
            wanted = SELECTED_OUTPUTS[(client, vector)]
            selected = [rows[index] for index in wanted]
            need([row["output_index"] for row in selected] == list(wanted),
                 f"{client}/{vector} selected output lookup drift")
            selectors = ([row["system_frame_number"] for row in selected]
                         if client == "gst" else list(wanted))
            need(all(type(row.get("pic")) is int and row["pic"] > 0 for row in selected),
                 f"{client}/{vector} selected picture input is invalid")
            reserve = len(selectors) if client == "gst" else None
            targets.append({
                "client": client,
                "vector": vector,
                "selector_domain": ("system_frame_number" if client == "gst"
                                    else "output_ordinal"),
                "selectors": selectors,
                "last_input": max(row["pic"] - 1 for row in selected),
                "output_count": len(rows),
                "gst_pool_size": ordinary[vector] + reserve if reserve is not None else None,
                "gst_reserve": reserve,
                "parameter_set_change_inputs": [],
            })
            selected_records[f"{vector}-{client}"] = selected

    return {
        "schema": SCHEMA,
        "sources": {"associations": association_sources, "gst_traces": trace_sources,
                    "streams": stream_sources},
        "derivation": {
            "selected_output_indices": {
                f"{vector}-{client}": list(SELECTED_OUTPUTS[(client, vector)])
                for vector in ("B", "E") for client in ("gst", "va")
            },
            "selected_associations": selected_records,
            "gst_capacity_rule": "negotiated_pool=ordinary_capture_pool+selected_reserve",
            "gst_reserve_rule": "one_never_published_allocation_per_selected_frame",
            "input_rule": "zero_based_input_index=one_based_picture_number-1",
            "parameter_set_change_inputs": {"B": [], "E": []},
        },
        "targets": targets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--associations", required=True, type=Path)
    parser.add_argument("--gst-b-trace", required=True, type=Path)
    parser.add_argument("--gst-e-trace", required=True, type=Path)
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        document = derive(args.associations.resolve(strict=True), {
            "B": args.gst_b_trace.resolve(strict=True),
            "E": args.gst_e_trace.resolve(strict=True),
        }, {
            vector: (args.corpus_root / f"RPS_{vector}_qualcomm_5" /
                     f"RPS_{vector}_qualcomm_5" /
                     f"RPS_{vector}_qualcomm_5.bit").resolve(strict=True)
            for vector in ("B", "E")
        })
    except (OSError, json.JSONDecodeError, TargetError) as error:
        print(f"TARGET REFUSED: {error}")
        return 125
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
