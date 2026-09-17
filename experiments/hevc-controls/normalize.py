#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline, deliberately narrow v4l2-tracer 1.32.0 HEVC adapter.

See README.md for supported inputs, source pins and evidence limitations.
No device, subprocess, network or raw media output is used by this module.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SCHEMA = "libva-v4l2request.hevc-refs/1"
MAX_BYTES = 128 * 1024 * 1024
MAX_PICTURES = 10000
CID = "V4L2_CID_STATELESS_HEVC_"
OUT = "V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE"
CAP = "V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE"
SIZES = {"SPS": 40, "DECODE_PARAMS": 328, "SLICE_PARAMS": 280}
SPS_FLAGS = "SEPARATE_COLOUR_PLANE SCALING_LIST_ENABLED AMP_ENABLED SAMPLE_ADAPTIVE_OFFSET PCM_ENABLED PCM_LOOP_FILTER_DISABLED LONG_TERM_REF_PICS_PRESENT SPS_TEMPORAL_MVP_ENABLED STRONG_INTRA_SMOOTHING_ENABLED".split()
SLICE_FLAGS = "SLICE_SAO_LUMA SLICE_SAO_CHROMA SLICE_TEMPORAL_MVP_ENABLED MVD_L1_ZERO CABAC_INIT COLLOCATED_FROM_L0 USE_INTEGER_MV SLICE_DEBLOCKING_FILTER_DISABLED SLICE_LOOP_FILTER_ACROSS_SLICES_ENABLED DEPENDENT_SLICE_SEGMENT".split()


class Reject(ValueError):
    """Unavailable or ambiguous evidence; never interpret it as equality."""


def require(condition, message):
    if not condition:
        raise Reject(message)


def integer(value, low=0, high=2**32 - 1):
    require(type(value) is int and low <= value <= high, "invalid integer")
    return value


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def load(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "input exceeds byte limit")
    return raw


def parse(raw):
    require(len(raw) <= MAX_BYTES, "input exceeds byte limit")
    def constant(_):
        raise Reject("non-JSON numeric constant")
    try:
        # With -u, this pinned tracer serializes uninitialized QUERYCAP input
        # strings, even though QUERYCAP has no input fields. Keep the raw file
        # unchanged; discard only that meaningless pre-call argument object.
        events = json.loads(raw.decode("utf-8", "surrogateescape"),
                            object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise Reject("invalid JSON trace") from exc
    require(isinstance(events, list) and 0 < len(events) <= 500000,
            "expected bounded event array")
    require(all(isinstance(e, dict) for e in events), "non-object event")
    require(events[0].get("package_version") == "1.32.0",
            "only v4l2-tracer 1.32.0 is supported")
    for event in events:
        if event.get("ioctl") == "VIDIOC_QUERYCAP":
            event.pop("from_userspace", None)
    # No replacement decoding: invalid strings anywhere else still reject.
    try:
        json.dumps(events, ensure_ascii=False).encode("utf-8")
    except UnicodeError as exc:
        raise Reject("invalid UTF-8 outside unused QUERYCAP inputs") from exc
    return events


def flags(value, prefix, allowed):
    require(isinstance(value, str), "missing flags")
    tokens = value.split("|") if value else []
    tokens = [t.strip() for t in tokens]
    require(len(tokens) == len(set(tokens)), "duplicate flag")
    names = {prefix + name for name in allowed}
    require(set(tokens) <= names, "unknown flag encoding")
    return {t[len(prefix):] for t in tokens}


def buffer_flags(value):
    # Buffer flags outside this reference subset are ignored only when symbolic.
    require(isinstance(value, str), "missing buffer flags")
    tokens = [t.strip() for t in value.split("|")]
    require(all(re.fullmatch(r"V4L2_BUF_FLAG_[A-Z0-9_]+", t) for t in tokens),
            "unknown numeric buffer flag")
    require("V4L2_BUF_FLAG_ERROR" not in tokens, "buffer error")
    require("V4L2_BUF_FLAG_M2M_HOLD_CAPTURE_BUF" not in tokens,
            "partial/multi-request pictures are unsupported")
    return set(tokens)


def timestamp(buf):
    ns = integer(buf["timestamp_ns"], high=2**64 - 1)
    tv = buf["timestamp"]
    sec = integer(tv["tv_sec"], high=2**63 - 1)
    usec = integer(tv["tv_usec"], high=999999)
    require(ns == sec * 1000000000 + usec * 1000, "inconsistent timestamp")
    require(ns % 1000 == 0 and ns // 1000 <= 2**32 - 1,
            "not a GStreamer system-frame timestamp")
    return ns


def arguments(event, direction, key):
    result = event[direction][key]
    require(isinstance(result, dict), "missing ioctl arguments")
    return result


def controls(event):
    ext = arguments(event, "from_userspace", "v4l2_ext_controls")
    items = ext["controls"]
    require(isinstance(items, list) and len(items) == integer(ext["count"], high=64),
            "incomplete controls array")
    require(all(isinstance(c, dict) and isinstance(c.get("id"), str) for c in items),
            "invalid control")
    require(len({c["id"] for c in items}) == len(items), "duplicate control")
    return ext, {c["id"]: c for c in items}


def payload(ctrls, name):
    c = ctrls[CID + name]
    require(integer(c["size"]) == SIZES[name],
            "unsupported control size (multi-slice traces lose all but first slice)")
    p = c["v4l2_ctrl_hevc_" + name.lower()]
    require(isinstance(p, dict), "missing control payload")
    return p


def normalize(events, expected, run):
    """Return schema records and decode-order association metadata.

    Single opened video context; successful complete one-slice requests only.
    CAPTURE completions supply real buffer indices, not invented timestamp aliases.
    """
    integer(expected, 1, MAX_PICTURES)
    require(isinstance(run, str) and re.fullmatch(r"[0-9a-f]{16}", run), "invalid run")
    candidates = []
    for i, e in enumerate(events):
        if e.get("ioctl") == "VIDIOC_S_EXT_CTRLS":
            _, cs = controls(e)
            if CID + "DECODE_PARAMS" in cs:
                candidates.append((i, integer(e["fd"])))
    require(candidates and len({fd for _, fd in candidates}) == 1,
            "expected exactly one HEVC video context")
    fd = candidates[0][1]
    opens = [i for i, e in enumerate(events[:candidates[0][0]])
             if e.get("fd") == fd and ("open" in e or "open64" in e)]
    require(opens, "missing video open / truncated context")
    start = opens[-1]
    allocations = set()
    requests = {}
    output_buffers = {}
    capture_buffers = set()
    pictures = []
    by_timestamp = {}
    sps = None
    closed = False
    stopped = False
    for index, e in enumerate(events):
        op = e.get("ioctl")
        if op == "MEDIA_IOC_REQUEST_ALLOC":
            require("errno" not in e, "request allocation failed")
            reqfd = integer(e["from_driver"]["request_fd"])
            old = requests.get(reqfd)
            require(not old or old.get("complete"), "request fd reused while pending")
            allocations.add(reqfd)
            requests.pop(reqfd, None)
        if index <= start:
            continue
        if e.get("fd") == fd and ("open" in e or "open64" in e):
            raise Reject("video fd reused / multiple contexts")
        if e.get("fd") == fd and "close" in e:
            require(not closed, "duplicate video close")
            closed = True
        if op in ("MEDIA_REQUEST_IOC_QUEUE", "MEDIA_REQUEST_IOC_REINIT"):
            reqfd = integer(e["fd"])
            if reqfd not in requests:
                # Allocated request may be reinitialized before its first use.
                require(op == "MEDIA_REQUEST_IOC_REINIT" and reqfd in allocations
                        and "errno" not in e, "orphaned request operation")
                continue
            require("errno" not in e, "request operation failed")
            req = requests[reqfd]
            if op == "MEDIA_REQUEST_IOC_REINIT":
                require(req.get("complete"), "reinitialization before capture completion")
                del requests[reqfd]
                continue
            require(not closed and not stopped and not req.get("queued"),
                    "duplicate/late request queue")
            cs = req["controls"]
            dp = payload(cs, "DECODE_PARAMS")
            sl = payload(cs, "SLICE_PARAMS")
            if CID + "SPS" in cs:
                sps = payload(cs, "SPS")
            require(sps is not None, "missing initial SPS")
            ts = req["timestamp"]
            require(ts not in by_timestamp, "duplicate picture timestamp")
            require(len(pictures) < expected, "more requests than expected")
            req.update(queued=True, dp=dp, sl=sl, sps=sps, pic=len(pictures) + 1)
            pictures.append(req)
            by_timestamp[ts] = req
            continue
        if e.get("fd") != fd or not op:
            continue
        require(not closed, "ioctl after video close")
        if op not in ("VIDIOC_S_EXT_CTRLS", "VIDIOC_QBUF", "VIDIOC_DQBUF",
                      "VIDIOC_STREAMOFF", "VIDIOC_STREAMON", "VIDIOC_S_FMT", "VIDIOC_REQBUFS"):
            continue
        # A nonblocking DQBUF without a buffer does not lose evidence.
        if op == "VIDIOC_DQBUF" and e.get("errno") == "EAGAIN":
            continue
        require("errno" not in e, "selected ioctl failed")
        if op == "VIDIOC_STREAMOFF":
            require(pictures and len(pictures) == expected
                    and all(p.get("complete") for p in pictures),
                    "stream stopped before expected captures completed")
            stopped = True
            continue
        if op in ("VIDIOC_STREAMON", "VIDIOC_S_FMT", "VIDIOC_REQBUFS"):
            require(not pictures or (stopped and op == "VIDIOC_REQBUFS"),
                    "stream reconfiguration after submission")
            continue
        if op == "VIDIOC_S_EXT_CTRLS":
            ext, cs = controls(e)
            if ext["which"] != "V4L2_CTRL_WHICH_REQUEST_VAL":
                require(ext["which"] == "V4L2_CTRL_WHICH_CUR_VAL" and not pictures
                        and not any(CID + n in cs for n in ("DECODE_PARAMS", "SLICE_PARAMS")),
                        "non-request HEVC payload")
                if CID + "SPS" in cs:
                    payload(cs, "SPS")  # Negotiation only; first request must supply its own SPS.
                continue
            require(not stopped, "controls after stream stop")
            reqfd = integer(ext["request_fd"])
            require(reqfd in allocations, "missing request allocation")
            req = requests.setdefault(reqfd, {})
            require(not req.get("queued"), "controls changed after queue")
            dst = req.setdefault("controls", {})
            require(not (dst.keys() & cs.keys()), "controls set twice in request")
            dst.update(cs)
        elif op in ("VIDIOC_QBUF", "VIDIOC_DQBUF"):
            direction = "from_userspace" if op == "VIDIOC_QBUF" else "from_driver"
            b = arguments(e, direction, "v4l2_buffer")
            kind = b["type"]
            require(kind in (OUT, CAP), "unsupported buffer type")
            bi = integer(b["index"])
            bf = buffer_flags(b["flags"])
            if op == "VIDIOC_QBUF":
                require(not stopped, "buffer queued after stream stop")
                if kind == CAP:
                    require(bi not in capture_buffers, "capture buffer queued twice")
                    capture_buffers.add(bi)
                else:
                    require("V4L2_BUF_FLAG_REQUEST_FD" in bf, "non-request OUTPUT")
                    reqfd = integer(b["request_fd"])
                    require(reqfd in allocations, "unallocated OUTPUT request")
                    req = requests.setdefault(reqfd, {})
                    require("timestamp" not in req and bi not in output_buffers,
                            "OUTPUT/request reused before completion")
                    ts = timestamp(b)
                    req["timestamp"] = ts
                    output_buffers[bi] = ts
            else:
                ts = timestamp(b)
                require(ts in by_timestamp, "completion without queued picture")
                if kind == OUT:
                    require(output_buffers.pop(bi, None) == ts, "OUTPUT completion mismatch")
                else:
                    require(bi in capture_buffers, "CAPTURE completion without QBUF")
                    require("V4L2_BUF_FLAG_TIMESTAMP_COPY" in bf,
                            "CAPTURE timestamp is not copied from OUTPUT")
                    capture_buffers.remove(bi)
                    req = by_timestamp[ts]
                    require(not req.get("complete"), "duplicate CAPTURE timestamp")
                    planes = b["m"]["planes"]
                    require(integer(b["length"]) == 1
                            and isinstance(planes, list) and len(planes) == 1
                            and integer(planes[0]["bytesused"]) > 0, "empty/unsupported capture")
                    req.update(complete=True, target=bi)
    require(closed and stopped, "missing clean context teardown")
    require(len(pictures) == expected and all(p.get("complete") for p in pictures)
            and not output_buffers, "incomplete expected capture")
    require(all(p.get("queued") for p in requests.values()), "orphaned pending request")
    records = []
    associations = []
    last_writer = {}
    for req in pictures:
        dp, sl = req["dp"], req["sl"]
        sf = flags(req["sps"]["flags"], "V4L2_HEVC_SPS_FLAG_", SPS_FLAGS)
        df = flags(dp["flags"], "V4L2_HEVC_DECODE_PARAM_FLAG_",
                   ("IRAP_PIC", "IDR_PIC", "NO_OUTPUT_OF_PRIOR"))
        lf = flags(sl["flags"], "V4L2_HEVC_SLICE_PARAMS_FLAG_", SLICE_FLAGS)
        pic = req["pic"]
        poc = integer(dp["pic_order_cnt_val"], -(2**31), 2**31 - 1)
        entries = dp["dpb"]
        require(isinstance(entries, list) and len(entries) == 16, "incomplete DPB array")
        n = integer(dp["num_active_dpb_entries"], high=16)
        dpb = []
        for slot, ent in enumerate(entries[:n]):
            ts = integer(ent["timestamp"], high=2**64 - 1)
            ref = by_timestamp.get(ts)
            require(ref is not None and ref["pic"] < pic, "unresolved/future/self reference")
            target = ref["target"]
            require(last_writer.get(target) == ref["pic"] and target != req["target"],
                    "reference aliases a reused/destination capture buffer")
            rpoc = integer(ent["pic_order_cnt_val"], -(2**31), 2**31 - 1)
            require(rpoc == ref["dp"]["pic_order_cnt_val"], "reference POC mismatch")
            # Pinned tracer erroneously decodes DPB flags with the PPS flag table.
            ef = flags(ent["flags"], "V4L2_HEVC_PPS_FLAG_",
                       ("DEPENDENT_SLICE_SEGMENT_ENABLED",))
            dpb.append(dict(i=slot, buf=target, poc=rpoc, lt=int(bool(ef)),
                            field=integer(ent["field_pic"], high=1)))

        def refs(array, count):
            require(isinstance(array, list) and len(array) == 16, "incomplete reference array")
            require(all(type(v) is int and 0 <= v <= 255 for v in array), "invalid reference array")
            return [integer(v, high=n - 1) for v in array[:count]]

        lists = {}
        for key, suffix in (("st_before", "st_curr_before"), ("st_after", "st_curr_after"),
                            ("lt_curr", "lt_curr")):
            count = integer(dp["num_poc_" + suffix], high=16)
            lists[key] = refs(dp["poc_" + suffix], count)
        total = sum(map(len, lists.values()))
        require(total <= n, "current reference count exceeds DPB")
        typ = integer(sl["slice_type"], high=2)
        l0 = 0 if typ == 2 else integer(sl["num_ref_idx_l0_active_minus1"], high=15) + 1
        l1 = integer(sl["num_ref_idx_l1_active_minus1"], high=15) + 1 if typ == 0 else 0
        st = dict(i=0, type=("B", "P", "I")[typ], nal=integer(sl["nal_unit_type"], high=63),
                  l0=refs(sl["ref_idx_l0"], l0), l1=refs(sl["ref_idx_l1"], l1),
                  tmvp=int("SLICE_TEMPORAL_MVP_ENABLED" in lf))
        if st["tmvp"]:
            st.update(col_l0=int("COLLOCATED_FROM_L0" in lf), col=integer(sl["collocated_ref_idx"], high=255))
            selected = st["l0"] if typ == 1 or st["col_l0"] else st["l1"]
            # I slices can carry the flag, but do not use a collocated picture.
            require(typ == 2 or st["col"] < len(selected), "unresolved collocated reference")
        records.append(dict(schema=SCHEMA, run=run, seq=pic, ctx=1, va_context="direct-v4l2",
                            pic=pic, req=pic, first=1, last=1, target=req["target"], poc=poc,
                            irap=int("IRAP_PIC" in df), idr=int("IDR_PIC" in df),
                            ltr_sps=int("LONG_TERM_REF_PICS_PRESENT" in sf), reorder=0,
                            total_curr=total, dpb=dpb, slices=[st], **lists))
        associations.append(dict(pic=pic, poc=poc, system_frame_number=req["timestamp"] // 1000))
        last_writer[req["target"]] = pic
    return records, associations


def associate(log, pictures, decoded_frames, tracee_status):
    integer(decoded_frames, 1, MAX_PICTURES)
    integer(tracee_status, high=255)
    require(tracee_status == 0 and decoded_frames == len(pictures),
            "association requires successful pipeline and independent full frame count")
    require(len(log.encode("utf-8")) <= MAX_BYTES, "log exceeds byte limit")
    ids = []
    instances = set()
    for line in log.splitlines():
        if "Output picture" not in line:
            continue
        match = re.search(r"gst_v4l2_codec_h265_dec_output_picture:<([^>]+)> Output picture (\d+)\s*$", line)
        require(match is not None, "unrecognized output-picture event")
        instances.add(match[1])
        ids.append(integer(int(match[2])))
    require(len(instances) == 1 and len(ids) == len(pictures) and len(set(ids)) == len(ids),
            "missing/duplicate/multiple-context output events")
    by_id = {p["system_frame_number"]: p for p in pictures}
    require(set(ids) == set(by_id), "output/decode picture identities differ")
    return [dict(output_index=i, **by_id[f]) for i, f in enumerate(ids)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace", type=Path)
    ap.add_argument("--expected-pictures", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--gst-log", type=Path)
    ap.add_argument("--gstreamer-version", choices=["1.28.7"])
    ap.add_argument("--decoded-frames", type=int)
    ap.add_argument("--tracee-status", type=int)
    ap.add_argument("--association", type=Path)
    args = ap.parse_args()
    try:
        raw = load(args.trace)
        digest = hashlib.sha256(raw).hexdigest()
        records, pictures = normalize(parse(raw), args.expected_pictures, digest[:16])
        mapping = None
        require(bool(args.gst_log) == bool(args.association), "log and association output must be paired")
        if args.gst_log:
            require(args.gstreamer_version == "1.28.7", "pinned GStreamer version assertion required")
            log = load(args.gst_log)
            mapping = dict(schema="hevc-controls.output-association/1", trace_sha256=digest,
                           log_sha256=hashlib.sha256(log).hexdigest(),
                           evidence="log order plus caller-verified pipeline status/raw-frame count",
                           frames=associate(log.decode("utf-8"), pictures, args.decoded_frames, args.tracee_status))
        data = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)
        require(all(len(line.encode()) + 1 <= 4096 for line in data.splitlines()), "schema record too large")
        # Refuse overwrite, including accidental raw-input/output path aliasing.
        with args.output.open("x") as stream:
            stream.write(data)
        if mapping is not None:
            with args.association.open("x") as stream:
                json.dump(mapping, stream, indent=2)
                stream.write("\n")
        print(f"converted {len(records)} complete request captures; reference subset only")
        return 0
    except (ValueError, KeyError, TypeError, IndexError, OSError, UnicodeError, RecursionError) as exc:
        # Never print raw exception data: trace paths, payloads and addresses are private.
        print(f"rejected input ({type(exc).__name__}); see supported contract in README", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
