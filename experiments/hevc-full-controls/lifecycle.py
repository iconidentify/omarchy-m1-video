# SPDX-License-Identifier: GPL-2.0-only
"""Copied lifecycle checker from ../hevc-controls/normalize.py at 3cdf66b.

One scoped change: accept final source buffers returned by successful OUTPUT
STREAMOFF after ALL expected CAPTURE completions. No DQBUF event is invented.
The original direct-client adapter and its historical contract stay unchanged.
"""
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("lifecycle_reference", Path(__file__).resolve().parent.parent / "hevc-controls/normalize.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
SCHEMA, MAX_PICTURES, CID, OUT, CAP = base.SCHEMA, base.MAX_PICTURES, base.CID, base.OUT, base.CAP
SPS_FLAGS, SLICE_FLAGS = base.SPS_FLAGS, base.SLICE_FLAGS
Reject, require, integer = base.Reject, base.require, base.integer
arguments, controls, payload = base.arguments, base.controls, base.payload
flags, timestamp, buffer_flags = base.flags, base.timestamp, base.buffer_flags
import re

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
            # Successful OUTPUT STREAMOFF cancels any final source buffers
            # the client did not dequeue; CAPTURE completion is still mandatory.
            if e.get("from_userspace", {}).get("type") == OUT:
                output_buffers.clear()
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

