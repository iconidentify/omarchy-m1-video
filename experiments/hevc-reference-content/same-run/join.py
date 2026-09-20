#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Strictly join one client observer result to validated same-run kernel evidence.

This module is deliberately device-free.  ``validator.py`` constructs the
``KernelEvidence`` only after the raw V4L2 trace and both sealed kernel snapshots
pass their existing validators.  The code here then crosses the remaining two
identity domains without treating a POC, frame number, output ordinal or capture
index as an identity by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable


SCHEMA = "omarchy.hevc.same-run-join/v1"
VA_SCHEMA = "omarchy.hevc.va-observer-result/v1"
GST_SCHEMA = "omarchy.hevc.gst-observer-result/v1"
VA_TRACE_SCHEMA = "libva-v4l2request.hevc-refs/1"
MAX_QUEUE_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024
HEX16 = re.compile(r"[0-9a-f]{16}")
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX64 = re.compile(r"[0-9a-f]{64}")
GST_QUEUE = re.compile(
    r"observer-queue run=([0-9a-f]{16})([0-9a-f]{16}) "
    r"context=([0-9]+) allocation=([0-9]+) request=([0-9]+) "
    r"writer=([0-9]+) frame=([0-9]+) capture=([0-9]+)(?:\s|$)"
)
REPORT_COMMON_KEYS = frozenset({
    "run", "context_generation", "session", "allocation_generation", "writer",
    "submitted", "completed", "capture_index", "copied", "sha256",
})
VA_REPORT_KEYS = REPORT_COMMON_KEYS | {"output_ordinal", "surface"}
GST_REPORT_KEYS = REPORT_COMMON_KEYS | {"system_frame_number", "request"}


class JoinError(ValueError):
    """Evidence is incomplete, ambiguous, foreign, stale or malformed."""


def need(condition: object, message: str) -> None:
    if not condition:
        raise JoinError(message)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise JoinError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def json_document(raw: bytes, *, maximum: int, name: str) -> object:
    need(0 < len(raw) <= maximum, f"{name} size is outside the accepted bound")
    need(raw.endswith(b"\n") and b"\r" not in raw and b"\x00" not in raw,
         f"{name} is not canonical newline-terminated UTF-8")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              JoinError(f"non-JSON constant in {name}: {value}")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JoinError(f"invalid {name}: {error}") from error


def json_lines(raw: bytes, *, maximum: int, name: str) -> list[dict[str, object]]:
    need(0 < len(raw) <= maximum, f"{name} size is outside the accepted bound")
    need(raw.endswith(b"\n") and b"\r" not in raw and b"\x00" not in raw,
         f"{name} is not canonical newline-terminated UTF-8")
    rows: list[dict[str, object]] = []
    for number, line in enumerate(raw.splitlines(), 1):
        try:
            row = json.loads(line.decode("utf-8"), object_pairs_hook=_object,
                             parse_constant=lambda value: (_ for _ in ()).throw(
                                 JoinError(f"non-JSON constant in {name}: {value}")))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise JoinError(f"invalid {name} line {number}: {error}") from error
        need(type(row) is dict, f"{name} line {number} is not an object")
        rows.append(row)
    return rows


def _uint(value: object, bits: int, name: str, *, nonzero: bool = False) -> int:
    need(type(value) is int and 0 <= value < 1 << bits, f"{name} is not uint{bits}")
    result = int(value)
    need(not nonzero or result != 0, f"{name} must be nonzero")
    return result


def _decimal(value: str, name: str, *, bits: int = 64, nonzero: bool = True) -> int:
    need(value.isascii() and value.isdecimal() and len(value) <= 20,
         f"{name} is not canonical decimal")
    number = int(value)
    need(str(number) == value and 0 <= number < 1 << bits and (number != 0 or not nonzero),
         f"{name} is zero, oversized or noncanonical")
    return number


def _hex(value: object, digits: int, name: str, *, nonzero: bool = True) -> str:
    pattern = HEX16 if digits == 16 else HEX32 if digits == 32 else HEX64
    need(type(value) is str and pattern.fullmatch(value) is not None,
         f"{name} is not {digits} lowercase hexadecimal digits")
    need(not nonzero or int(value, 16) != 0, f"{name} must be nonzero")
    return value


@dataclass(frozen=True)
class KernelEvidence:
    """Output of the raw same-run validator, never deserialized from a claim."""

    run: int
    context: int
    child_pid: int
    requests: tuple[dict[str, object], ...]
    associations: tuple[dict[str, int], ...]
    reference_records: tuple[dict[str, object], ...]
    hashes: dict[str, str]

    def check(self) -> None:
        _uint(self.run, 64, "kernel run", nonzero=True)
        _uint(self.context, 64, "kernel context", nonzero=True)
        _uint(self.child_pid, 31, "child pid", nonzero=True)
        need(bool(self.requests), "kernel evidence has no requests")
        pictures = list(range(1, len(self.requests) + 1))
        need([row.get("pic") for row in self.requests] == pictures,
             "kernel request history is incomplete or reordered")
        need([row.get("pic") for row in self.associations] == pictures,
             "raw V4L2 association history is incomplete or reordered")
        need(len({row.get("system_frame_number") for row in self.associations}) == len(pictures),
             "raw V4L2 frame timestamps are ambiguous")
        need(set(self.hashes) >= {
            "execution", "v4l2_trace", "command_snapshot", "reference_snapshot"
        }, "kernel evidence digest inventory is incomplete")
        for name, digest in self.hashes.items():
            _hex(digest, 64, f"hash {name}", nonzero=False)


VA_BASE_KEYS = frozenset({
    "schema", "run", "seq", "ctx", "va_context", "pic", "req", "first",
    "last", "target", "poc", "irap", "idr", "ltr_sps", "reorder",
    "total_curr", "dpb", "slices", "st_before", "st_after", "lt_curr",
    "observer",
})
VA_OBSERVER_KEYS = frozenset({"run", "context", "allocation", "surface", "writer"})


def parse_va_queue(raw: bytes, expected: int) -> list[dict[str, object]]:
    rows = json_lines(raw, maximum=MAX_QUEUE_BYTES, name="VA queue trace")
    need(len(rows) == expected, "VA queue trace has the wrong request extent")
    common: tuple[str, int] | None = None
    tuples: set[tuple[object, ...]] = set()
    for index, row in enumerate(rows, 1):
        need(set(row) == VA_BASE_KEYS, f"VA queue row {index} has unexpected fields")
        need(row["schema"] == VA_TRACE_SCHEMA, f"VA queue row {index} has wrong schema")
        _hex(row["run"], 16, f"VA queue row {index} trace run")
        need(row["seq"] == row["pic"] == row["req"] == index,
             f"VA queue row {index} is not a complete one-request picture")
        need(row["first"] == row["last"] == 1,
             f"VA queue row {index} is outside the one-slice campaign domain")
        _uint(row["target"], 32, f"VA queue row {index} target")
        observer = row["observer"]
        need(type(observer) is dict and set(observer) == VA_OBSERVER_KEYS,
             f"VA queue row {index} has malformed observer identity")
        run = _hex(observer["run"], 32, f"VA queue row {index} observer run")
        context = _uint(observer["context"], 64, f"VA queue row {index} context", nonzero=True)
        allocation = _uint(observer["allocation"], 64,
                           f"VA queue row {index} allocation", nonzero=True)
        surface = _uint(observer["surface"], 64,
                        f"VA queue row {index} surface generation", nonzero=True)
        writer = _uint(observer["writer"], 64,
                       f"VA queue row {index} writer", nonzero=True)
        identity = (run, context)
        if common is None:
            common = identity
        need(identity == common, "VA queue trace mixes observer runs or contexts")
        joined = (run, context, allocation, surface, writer, row["target"])
        need(joined not in tuples, "VA queue trace duplicates an observer identity")
        tuples.add(joined)
    return rows


def _va_projection(row: dict[str, object]) -> dict[str, object]:
    """Fields that must equal the same process's normalized V4L2 request."""
    return {key: value for key, value in row.items()
            if key not in {"schema", "run", "ctx", "va_context", "observer"}}


GST_KEYS = frozenset({
    "run", "context", "allocation", "request", "writer", "frame", "capture"
})
GST_NUMBER_KEYS = ("context", "allocation", "request", "writer", "frame", "capture")


def parse_gst_queue(raw: bytes, expected: int) -> list[dict[str, object]]:
    need(0 < len(raw) <= MAX_QUEUE_BYTES and b"\x00" not in raw,
         "Gst queue log size/content is outside the accepted bound")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise JoinError(f"Gst queue log is not UTF-8: {error}") from error
    rows: list[dict[str, object]] = []
    malformed = 0
    for line in text.splitlines():
        if "observer-queue" not in line:
            continue
        matches = list(GST_QUEUE.finditer(line))
        if len(matches) != 1 or line[matches[0].end():].strip():
            malformed += 1
            continue
        match = matches[0]
        run0, run1, *numbers = match.groups()
        values = [_decimal(value, f"Gst queue {name}",
                           nonzero=name not in ("frame", "capture"))
                  for value, name in zip(numbers, GST_NUMBER_KEYS)]
        rows.append(dict(zip(GST_NUMBER_KEYS, values), run=[run0, run1]))
    need(not malformed, "Gst queue log contains malformed or duplicated observer records")
    need(len(rows) == expected, "Gst queue log has the wrong request extent")
    common: tuple[object, ...] | None = None
    identities: set[tuple[object, ...]] = set()
    frames: set[int] = set()
    requests: set[int] = set()
    for index, row in enumerate(rows):
        if set(row) != GST_KEYS:
            raise JoinError(f"Gst queue row {index} has unexpected fields")
        run = row["run"]
        need(type(run) is list and len(run) == 2, "Gst queue run shape")
        _hex(run[0], 16, "Gst queue run[0]")
        _hex(run[1], 16, "Gst queue run[1]")
        identity = (tuple(run), row["context"])
        if common is None:
            common = identity
        need(identity == common, "Gst queue log mixes observer runs or contexts")
        joined = (tuple(run), row["context"], row["allocation"], row["request"],
                  row["writer"], row["frame"], row["capture"])
        need(joined not in identities, "Gst queue log duplicates an observer identity")
        need(row["frame"] not in frames, "Gst queue log duplicates a frame identity")
        need(row["request"] not in requests, "Gst queue log duplicates a request generation")
        identities.add(joined); frames.add(row["frame"]); requests.add(row["request"])
    return rows


def parse_associations(document: object, expected: int) -> list[dict[str, int]]:
    need(type(document) is list and len(document) == expected,
         "output association has the wrong extent")
    rows: list[dict[str, int]] = []
    for index, row in enumerate(document):
        need(type(row) is dict and set(row) == {"output_index", "pic", "poc"},
             f"output association row {index} has unexpected fields")
        need(row["output_index"] == index, "output association indices are incomplete")
        pic = _uint(row["pic"], 32, f"association {index} picture", nonzero=True)
        need(pic <= expected, f"association {index} picture is outside the decode extent")
        poc = row["poc"]
        need(type(poc) is int and -(1 << 31) <= poc < 1 << 31,
             f"association {index} POC is invalid")
        rows.append({"output_index": index, "pic": pic, "poc": int(poc)})
    need(len({row["pic"] for row in rows}) == expected,
         "output association duplicates a decoded picture")
    return rows


def _report_identity(output: dict[str, object], prefix: str) -> tuple[tuple[str, str], str, str]:
    run = output.get("run")
    need(type(run) is list and len(run) == 2, f"{prefix}.run has wrong shape")
    run0 = _hex(run[0], 16, prefix + ".run[0]")
    run1 = _hex(run[1], 16, prefix + ".run[1]")
    context = _hex(output.get("context_generation"), 16, prefix + ".context_generation")
    session = _hex(output.get("session"), 16, prefix + ".session")
    return (run0, run1), context, session


def validate_report(document: object, client: str, selectors: tuple[int, ...],
                    copy: bool) -> list[dict[str, object]]:
    need(type(document) is dict and set(document) == {"schema", "count", "outputs"},
         "observer report has unexpected top-level fields")
    schema = VA_SCHEMA if client == "va" else GST_SCHEMA
    need(document["schema"] == schema, "observer report has wrong client schema")
    outputs = document["outputs"]
    need(type(outputs) is list and document["count"] == len(outputs) == len(selectors),
         "observer report count differs from the requested selection")
    need(1 <= len(selectors) <= 8 and len(set(selectors)) == len(selectors),
         "selectors are not one to eight unique values")
    coordinate = "output_ordinal" if client == "va" else "system_frame_number"
    observed: list[int] = []
    common: tuple[tuple[str, str], str, str] | None = None
    for index, output in enumerate(outputs):
        expected_keys = VA_REPORT_KEYS if client == "va" else GST_REPORT_KEYS
        need(type(output) is dict and set(output) == expected_keys,
             f"observer output {index} has unexpected fields")
        observed.append(_uint(output.get(coordinate), 64 if client == "va" else 32,
                              f"observer output {index} coordinate"))
        identity = _report_identity(output, f"outputs[{index}]")
        if common is None:
            common = identity
        need(identity == common, "observer report mixes run/context/session identity")
        for field in ("allocation_generation", "writer", "submitted", "completed"):
            _hex(output.get(field), 16, f"outputs[{index}].{field}")
        submitted = int(output["submitted"], 16)
        completed = int(output["completed"], 16)
        need(completed == submitted, f"outputs[{index}] is not at a drained completion frontier")
        _uint(output.get("capture_index"), 32, f"outputs[{index}].capture_index")
        need(output.get("copied") is copy, f"outputs[{index}] has the wrong copy mode")
        if copy:
            _hex(output.get("sha256"), 64, f"outputs[{index}].sha256", nonzero=False)
        else:
            need(output.get("sha256") is None, f"outputs[{index}] exposes a copy-off digest")
        if client == "gst":
            _hex(output.get("request"), 16, f"outputs[{index}].request")
        else:
            _uint(output.get("surface"), 32, f"outputs[{index}].surface")
    if client == "va":
        need(tuple(observed) == selectors, "VA observer ordinals differ from requested order")
    else:
        need(set(observed) == set(selectors), "Gst observer frames differ from requested set")
    return outputs


def _reference_pair(evidence: KernelEvidence, picture: int,
                    capture: int) -> tuple[dict[str, object], dict[str, object]]:
    # Full reference validation already checks the intervening table/list/motion
    # records. Select the lifetime pair without discarding duplicate endpoints.
    rows = [row for row in evidence.reference_records
            if row.get("picture") == picture and row.get("kind") in (1, 2)]
    need(len(rows) == 2 and rows[0].get("kind") == 1 and rows[1].get("kind") == 2,
         f"kernel picture {picture} has no complete reference lifetime")
    start, done = rows
    need(start.get("buffer") == done.get("buffer") == capture,
         f"kernel picture {picture} does not bind the selected capture")
    need(start.get("writer") == picture and start.get("completed") == 0,
         f"kernel picture {picture} has the wrong writer frontier")
    need(done.get("writer") == picture and done.get("completed") == 1 and done.get("result") == 5,
         f"kernel picture {picture} has no successful completion")
    for key in ("allocation", "length", "comp_start", "comp_size", "mv_size", "mv_offset"):
        need(start.get(key) == done.get(key),
             f"kernel picture {picture} changed {key} before completion")
    _uint(start.get("allocation"), 64, f"kernel picture {picture} allocation", nonzero=True)
    return start, done


def _client_public(output: dict[str, object], client: str) -> dict[str, object]:
    fields = ("run", "context_generation", "session", "allocation_generation", "writer",
              "submitted", "completed", "capture_index", "copied", "sha256")
    result = {key: output[key] for key in fields}
    if client == "va":
        result["surface"] = output["surface"]
    else:
        result["request"] = output["request"]
    return result


def join_va(evidence: KernelEvidence, report: object, queue_raw: bytes,
            associations: object, selectors: tuple[int, ...], copy: bool,
            queue_sha256: str) -> dict[str, object]:
    evidence.check()
    outputs = validate_report(report, "va", selectors, copy)
    queue = parse_va_queue(queue_raw, len(evidence.requests))
    output_rows = parse_associations(associations, len(evidence.requests))
    for number, (actual, expected) in enumerate(zip(queue, evidence.requests), 1):
        need(_va_projection(actual) == _va_projection(expected),
             f"VA queue row {number} is not the raw V4L2 request from this process")
    by_output = {row["output_index"]: row for row in output_rows}
    selected: list[dict[str, object]] = []
    for output in outputs:
        ordinal = output["output_ordinal"]
        association = by_output.get(ordinal)
        need(association is not None, f"VA output ordinal {ordinal} is not associated")
        picture = association["pic"]
        row = queue[picture - 1]
        observer = row["observer"]
        run = output["run"]
        need(observer["run"] == run[0] + run[1], "VA report/queue run mismatch")
        need(observer["context"] == int(output["context_generation"], 16),
             "VA report/queue context mismatch")
        need(observer["allocation"] == int(output["allocation_generation"], 16),
             "VA report/queue allocation mismatch")
        need(observer["writer"] == int(output["writer"], 16),
             "VA report/queue writer mismatch")
        need(row["target"] == output["capture_index"], "VA report/queue capture mismatch")
        need(row["poc"] == association["poc"], "VA queue/output POC mismatch")
        start, _ = _reference_pair(evidence, picture, output["capture_index"])
        selected.append({
            "selector": {"domain": "output_ordinal", "value": ordinal},
            "client": _client_public(output, "va"),
            "bridge": {"picture": picture, "poc": association["poc"],
                       "capture_index": output["capture_index"],
                       "client_surface_generation": str(observer["surface"]),
                       "kernel_allocation": str(start["allocation"]),
                       "kernel_writer": picture, "kernel_completed": True},
        })
    return _result(evidence, "va", copy, selected, queue_sha256)


def join_gst(evidence: KernelEvidence, report: object, queue_raw: bytes,
             associations: object, selectors: tuple[int, ...], copy: bool,
             queue_sha256: str) -> dict[str, object]:
    evidence.check()
    outputs = validate_report(report, "gst", selectors, copy)
    queue = parse_gst_queue(queue_raw, len(evidence.requests))
    output_rows = parse_associations(associations, len(evidence.requests))
    outputs_by_picture = {row["pic"]: row for row in output_rows}
    raw_by_frame = {row["system_frame_number"]: row for row in evidence.associations}
    requests_by_picture = {row["pic"]: row for row in evidence.requests}
    queue_by_frame: dict[int, dict[str, object]] = {}
    for row in queue:
        frame = row["frame"]
        raw = raw_by_frame.get(frame)
        need(raw is not None, f"Gst queue frame {frame} has no raw V4L2 timestamp bridge")
        request = requests_by_picture[raw["pic"]]
        need(request["target"] == row["capture"],
             f"Gst queue frame {frame} has the wrong raw V4L2 capture lifetime")
        need(raw["pic"] in outputs_by_picture,
             f"Gst queue frame {frame} was not delivered by the same process")
        queue_by_frame[frame] = row | {"picture": raw["pic"], "poc": raw["poc"]}
    need(len(queue_by_frame) == len(evidence.requests),
         "Gst queue/raw V4L2 bridge is incomplete")
    selected: list[dict[str, object]] = []
    for output in outputs:
        frame = output["system_frame_number"]
        row = queue_by_frame.get(frame)
        need(row is not None, f"Gst selected frame {frame} has no same-process queue record")
        expected = {
            "run": output["run"],
            "context": int(output["context_generation"], 16),
            "allocation": int(output["allocation_generation"], 16),
            "request": int(output["request"], 16),
            "writer": int(output["writer"], 16),
            "frame": frame,
            "capture": output["capture_index"],
        }
        need(all(row[key] == value for key, value in expected.items()),
             f"Gst report/queue identity mismatch for frame {frame}")
        picture = row["picture"]
        start, _ = _reference_pair(evidence, picture, output["capture_index"])
        selected.append({
            "selector": {"domain": "system_frame_number", "value": frame},
            "client": _client_public(output, "gst"),
            "bridge": {"picture": picture, "poc": row["poc"],
                       "capture_index": output["capture_index"],
                       "kernel_allocation": str(start["allocation"]),
                       "kernel_writer": picture, "kernel_completed": True},
        })
    return _result(evidence, "gst", copy, selected, queue_sha256)


def _result(evidence: KernelEvidence, client: str, copy: bool,
            selected: list[dict[str, object]], queue_sha256: str) -> dict[str, object]:
    digest = _hex(queue_sha256, 64, "queue trace hash", nonzero=False)
    result = {
        "schema": SCHEMA,
        "client": client,
        "copy": copy,
        "kernel": {"run": str(evidence.run), "context": str(evidence.context)},
        "selected": selected,
        "inputs": dict(sorted(evidence.hashes.items()) + [("client_queue", digest)]),
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    need(len(encoded) <= MAX_OUTPUT_BYTES, "normalized join result exceeds its bound")
    # Defense in depth: the public document cannot grow a raw identity channel.
    forbidden = {"timestamp", "fd", "dma", "pointer", "lease", "bytes"}
    def keys(value: object) -> Iterable[str]:
        if type(value) is dict:
            for key, child in value.items():
                yield key.lower()
                yield from keys(child)
        elif type(value) is list:
            for child in value:
                yield from keys(child)
    need(not any(any(word in key for word in forbidden) for key in keys(result)),
         "normalized join result contains a forbidden raw field")
    return result


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(result: dict[str, object]) -> bytes:
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    need(len(raw) <= MAX_OUTPUT_BYTES, "normalized join result exceeds its bound")
    return raw
