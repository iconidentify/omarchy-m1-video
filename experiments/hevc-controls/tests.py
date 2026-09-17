#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic source-format fixtures; no captured media or hardware results."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import normalize as n


def ioctl(op, direction=None, obj=None, fd=10):
    e = dict(fd=fd, ioctl=op)
    if direction:
        e[direction] = obj
    return e


def ctl(name, value):
    return dict(id=n.CID + name, size=n.SIZES[name], **{"v4l2_ctrl_hevc_" + name.lower(): value})


def fixture():
    """Decode POC 0,2,1,3; display 0,1,2,3; reuse buffer 4 on picture 4."""
    events = [dict(package_version="1.32.0"), dict(fd=10, open=dict(path="/private/device"))]
    for i, (poc, target) in enumerate(((0, 4), (2, 5), (1, 6), (3, 4))):
        prev = max(0, i - 1)
        prev_poc = (0, 2, 1, 3)[prev]
        dp = dict(pic_order_cnt_val=poc, num_active_dpb_entries=int(i > 0),
                  num_poc_st_curr_before=0, num_poc_st_curr_after=0,
                  num_poc_lt_curr=int(i > 0),
                  poc_st_curr_before=[0] * 16, poc_st_curr_after=[0] * 16,
                  poc_lt_curr=[0] * 16,
                  dpb=[dict(timestamp=prev * 1000, flags="V4L2_HEVC_PPS_FLAG_DEPENDENT_SLICE_SEGMENT_ENABLED",
                            field_pic=0, pic_order_cnt_val=prev_poc)] * 16,
                  flags="V4L2_HEVC_DECODE_PARAM_FLAG_IRAP_PIC|V4L2_HEVC_DECODE_PARAM_FLAG_IDR_PIC" if not i else "")
        sl = dict(slice_type=2 if not i else 1, nal_unit_type=19 if not i else 1,
                  num_ref_idx_l0_active_minus1=0, num_ref_idx_l1_active_minus1=0,
                  ref_idx_l0=[0] * 16, ref_idx_l1=[0] * 16,
                  collocated_ref_idx=0,
                  flags="V4L2_HEVC_SLICE_PARAMS_FLAG_SLICE_TEMPORAL_MVP_ENABLED" if i else "")
        cs = [ctl("DECODE_PARAMS", dp), ctl("SLICE_PARAMS", sl)]
        if not i:
            cs.append(ctl("SPS", dict(flags="V4L2_HEVC_SPS_FLAG_LONG_TERM_REF_PICS_PRESENT")))
        if not i:
            events.append(ioctl("MEDIA_IOC_REQUEST_ALLOC", "from_driver", dict(request_fd=20), fd=11))
        events.append(ioctl("VIDIOC_S_EXT_CTRLS", "from_userspace", dict(v4l2_ext_controls=dict(
            which="V4L2_CTRL_WHICH_REQUEST_VAL", count=len(cs), request_fd=20, controls=cs))))
        def buf(kind, bi):
            return dict(type=kind, index=bi, length=1, timestamp_ns=i * 1000,
                        timestamp=dict(tv_sec=0, tv_usec=i), request_fd=20,
                        flags="V4L2_BUF_FLAG_TIMESTAMP_COPY|V4L2_BUF_FLAG_TSTAMP_SRC_EOF|V4L2_BUF_FLAG_REQUEST_FD",
                        m=dict(planes=[dict(bytesused=32)]))
        for kind, bi in ((n.CAP, target), (n.OUT, 0)):
            events.append(ioctl("VIDIOC_QBUF", "from_userspace", dict(v4l2_buffer=buf(kind, bi))))
        events.append(ioctl("MEDIA_REQUEST_IOC_QUEUE", fd=20))
        for kind, bi in ((n.OUT, 0), (n.CAP, target)):
            events.append(ioctl("VIDIOC_DQBUF", "from_driver", dict(v4l2_buffer=buf(kind, bi))))
        events.append(ioctl("MEDIA_REQUEST_IOC_REINIT", fd=20))
    events.extend([ioctl("VIDIOC_STREAMOFF"), dict(fd=10, close="/private/device")])
    return events


def log():
    return "".join("0:00:00 123 0xffff DEBUG v4l2codecs gstv4l2codech265dec.c:1369:"
                   f"gst_v4l2_codec_h265_dec_output_picture:<v4l2slh265dec0> Output picture {i}\n"
                   for i in (0, 2, 1, 3))


def convert(events):
    # Round trip through the public loader; fixtures must not bypass source shape checks.
    return n.normalize(n.parse(json.dumps(events).encode()), 4, "1234567890abcdef")


def selected(events, op):
    return [e for e in events if e.get("ioctl") == op]


def ext(events, picture=0):
    return selected(events, "VIDIOC_S_EXT_CTRLS")[picture]["from_userspace"]["v4l2_ext_controls"]


def control(events, name, picture=0):
    return next(c for c in ext(events, picture)["controls"] if c["id"] == n.CID + name)


class Tests(unittest.TestCase):
    def test_zero_timestamp_reordering_reuse_and_flag_bug(self):
        records, pics = convert(fixture())
        self.assertEqual([r["poc"] for r in records], [0, 2, 1, 3])
        self.assertEqual([r["target"] for r in records], [4, 5, 6, 4])
        self.assertEqual(records[1]["dpb"][0], dict(i=0, buf=4, poc=0, lt=1, field=0))
        self.assertEqual(records[0]["ltr_sps"], 1)
        self.assertEqual(records[0]["lt_curr"], [])
        self.assertEqual(records[1]["slices"][0]["col_l0"], 0)  # P uses L0 implicitly.
        mapped = n.associate(log(), pics, 4, 0)
        self.assertEqual([r["poc"] for r in mapped], [0, 1, 2, 3])
        self.assertEqual([r["pic"] for r in mapped], [1, 3, 2, 4])
        output = json.dumps([records, mapped])
        for private in ("/private", "0xffff", '"fd"', "bytesused", "mmap"):
            self.assertNotIn(private, output)

    def test_parallel_pending_requests(self):
        events = fixture()
        # Keep first request pending while second is submitted with its own fd.
        first_done = events[6:9]
        del events[6:9]
        # Second controls now at 6; use request 21 until its REINIT.
        events.insert(6, ioctl("MEDIA_IOC_REQUEST_ALLOC", "from_driver", dict(request_fd=21), fd=11))
        for e in events[7:14]:
            if e.get("fd") == 20:
                e["fd"] = 21
            for direction in ("from_userspace", "from_driver"):
                for obj in e.get(direction, {}).values():
                    if isinstance(obj, dict) and "request_fd" in obj:
                        obj["request_fd"] = 21
                    if isinstance(obj, dict) and obj.get("type") == n.OUT:
                        obj["index"] = 1
        events[11:11] = first_done
        self.assertEqual(len(convert(events)[0]), 4)

    def test_adversarial(self):
        def mutate(name, edit):
            events = fixture()
            edit(events)
            with self.subTest(name=name), self.assertRaises((n.Reject, KeyError, TypeError)):
                convert(events)
        mutate("missing queue", lambda e: e.remove(selected(e, "MEDIA_REQUEST_IOC_QUEUE")[0]))
        mutate("missing capture completion", lambda e: e.remove(selected(e, "VIDIOC_DQBUF")[1]))
        mutate("missing output completion", lambda e: e.remove(selected(e, "VIDIOC_DQBUF")[0]))
        mutate("failed queue", lambda e: selected(e, "MEDIA_REQUEST_IOC_QUEUE")[0].update(errno="EIO"))
        mutate("failed controls", lambda e: selected(e, "VIDIOC_S_EXT_CTRLS")[0].update(errno="EINVAL"))
        mutate("multi-slice", lambda e: control(e, "SLICE_PARAMS").update(size=560))
        mutate("missing SPS", lambda e: (ext(e)["controls"].pop(), ext(e).update(count=2)))
        mutate("bad SPS size", lambda e: control(e, "SPS").update(size=39))
        mutate("unknown DPB flag", lambda e: control(e, "DECODE_PARAMS", 1)["v4l2_ctrl_hevc_decode_params"]["dpb"][0].update(flags="V4L2_HEVC_PPS_FLAG_OUTPUT_FLAG_PRESENT"))
        mutate("unresolved reference", lambda e: control(e, "DECODE_PARAMS", 1)["v4l2_ctrl_hevc_decode_params"]["dpb"][0].update(timestamp=99000))
        mutate("future reference", lambda e: control(e, "DECODE_PARAMS", 1)["v4l2_ctrl_hevc_decode_params"]["dpb"][0].update(timestamp=2000))
        mutate("bad POC", lambda e: control(e, "DECODE_PARAMS", 1)["v4l2_ctrl_hevc_decode_params"]["dpb"][0].update(pic_order_cnt_val=9))
        mutate("active reference range", lambda e: control(e, "SLICE_PARAMS", 1)["v4l2_ctrl_hevc_slice_params"]["ref_idx_l0"].__setitem__(0, 3))
        mutate("collocated reference", lambda e: control(e, "SLICE_PARAMS", 1)["v4l2_ctrl_hevc_slice_params"].update(collocated_ref_idx=3))
        mutate("control count", lambda e: ext(e).update(count=2))
        mutate("duplicate control", lambda e: (ext(e)["controls"].append(copy.deepcopy(ext(e)["controls"][0])), ext(e).update(count=4)))
        mutate("missing allocation", lambda e: e.remove(selected(e, "MEDIA_IOC_REQUEST_ALLOC")[0]))
        mutate("timestamp disagreement", lambda e: selected(e, "VIDIOC_QBUF")[1]["from_userspace"]["v4l2_buffer"].update(timestamp_ns=1))
        mutate("capture error", lambda e: selected(e, "VIDIOC_DQBUF")[1]["from_driver"]["v4l2_buffer"].update(flags="V4L2_BUF_FLAG_ERROR"))
        mutate("partial picture", lambda e: selected(e, "VIDIOC_QBUF")[1]["from_userspace"]["v4l2_buffer"].update(flags="V4L2_BUF_FLAG_M2M_HOLD_CAPTURE_BUF"))
        mutate("orphan capture", lambda e: selected(e, "VIDIOC_DQBUF")[1]["from_driver"]["v4l2_buffer"].update(index=99))
        mutate("unrecorded capture plane", lambda e: selected(e, "VIDIOC_DQBUF")[1]["from_driver"]["v4l2_buffer"].update(length=2))
        mutate("duplicate queue", lambda e: e.insert(6, copy.deepcopy(selected(e, "MEDIA_REQUEST_IOC_QUEUE")[0])))
        mutate("duplicate capture", lambda e: e.insert(8, copy.deepcopy(selected(e, "VIDIOC_DQBUF")[1])))
        mutate("missing close", lambda e: e.pop())
        mutate("missing streamoff", lambda e: e.pop(-2))
        mutate("reopen", lambda e: e.append(dict(fd=10, open=dict(path="/private/reopen"))))
        mutate("second context", lambda e: selected(e, "VIDIOC_S_EXT_CTRLS")[1].update(fd=11))
        mutate("truncated picture extent", lambda e: e.__delitem__(slice(23, 30)))
        mutate("early stop", lambda e: e.insert(5, ioctl("VIDIOC_STREAMOFF")))
        mutate("reconfiguration", lambda e: e.insert(9, ioctl("VIDIOC_S_FMT")))
        mutate("missing userspace args", lambda e: selected(e, "VIDIOC_S_EXT_CTRLS")[0].pop("from_userspace"))
        mutate("wrong tracer version", lambda e: e[0].update(package_version="1.30.0"))
        mutate("boolean count", lambda e: ext(e).update(count=True))

    def test_association_rejects_incomplete_or_ambiguous(self):
        _, pics = convert(fixture())
        for name, text, count, status in (
            ("short", log().splitlines()[0], 4, 0),
            ("duplicate", log().replace("picture 3", "picture 0"), 4, 0),
            ("unknown", log().replace("picture 3", "picture 99"), 4, 0),
            ("two elements", log().replace("<v4l2slh265dec0> Output picture 3", "<other> Output picture 3"), 4, 0),
            ("short raw output", log(), 3, 0),
            ("pipeline failure", log(), 4, 1),
            ("unrecognized", log() + "Output picture 4\n", 4, 0)):
            with self.subTest(name=name), self.assertRaises(n.Reject):
                n.associate(text, pics, count, status)

    def test_json_rejections(self):
        for data in (b'{"x":1,"x":2}', b'[NaN]', b'[]', b'[', b'[[[[]]]]', b'\xff',
                     b'[' * 2000 + b']' * 2000):
            with self.subTest(data=data[:30]), self.assertRaises(n.Reject):
                n.parse(data)
        old = n.MAX_BYTES
        try:
            n.MAX_BYTES = 16
            with self.assertRaises(n.Reject):
                n.parse(b' ' * 17)
        finally:
            n.MAX_BYTES = old

    def test_cli_and_driver_interoperability(self):
        checker = os.environ.get("HEVC_REFTRACE_CHECKER")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, out, logs, mapping = [root / x for x in ("raw.json", "refs.jsonl", "gst.log", "map.json")]
            source.write_text(json.dumps(fixture()))
            logs.write_text(log())
            cmd = [sys.executable, str(Path(n.__file__)), str(source), "--expected-pictures", "4",
                   "--output", str(out), "--gst-log", str(logs), "--association", str(mapping),
                   "--decoded-frames", "4", "--tracee-status", "0", "--gstreamer-version", "1.28.7"]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(len(json.loads(mapping.read_text())["frames"]), 4)
            before = out.read_bytes()
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)
            self.assertEqual(out.read_bytes(), before)
            if checker:
                for args in (["validate", str(out)], ["compare", str(out), str(out), "--expected-pictures", "4"]):
                    result = subprocess.run([sys.executable, checker] + args, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                # Allocation identities can differ while references stay equivalent.
                other = fixture()
                for event in other:
                    for direction in ("from_userspace", "from_driver"):
                        buf = event.get(direction, {}).get("v4l2_buffer", {})
                        if buf.get("type") == n.CAP:
                            buf["index"] += 10
                records, _ = convert(other)
                second = root / "second.jsonl"
                def compare():
                    second.write_text("".join(json.dumps(r) + "\n" for r in records))
                    return subprocess.run([sys.executable, checker, "compare", str(out), str(second),
                                           "--expected-pictures", "4"], capture_output=True).returncode
                self.assertEqual(compare(), 0)
                records[1]["dpb"][0]["lt"] = 0
                self.assertEqual(compare(), 1)
                records.pop()
                self.assertEqual(compare(), 2)
            else:
                print("driver checker interoperability NOT RUN (set HEVC_REFTRACE_CHECKER)", file=sys.stderr)
            source.write_bytes(b'[{"secret/private":"payload",')
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("secret", result.stderr)


if __name__ == "__main__":
    unittest.main()
