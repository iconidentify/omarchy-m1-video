#!/usr/bin/env python3
"""Software-only regression for delayed HEVC parameter-set dependencies.

Compares a pinned FFmpeg n9.0.1 build with the same build plus
ffmpeg-n9.0.1-hevc-pending-parameter-sets.patch. No VA device, sudo or
installation is used; see README.md.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import hevcnal as nal  # noqa: E402

SOURCE = json.loads((HERE / "source.json").read_text())
VECTOR = SOURCE["vector"]

# Every decode is run in each threading mode; the patch copies pending state
# between frame threads, so frame threading is exercised explicitly.
THREAD_MODES = {
    "auto": [],
    "single": ["-threads", "1"],
    "frame4": ["-threads", "4", "-thread_type", "frame"],
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decode(ffmpeg, stream, threads="auto", timeout=120):
    """Decode at native size. Returns frames, dimensions, MD5 of all output."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "out.yuv"
        fmd5 = Path(tmp) / "out.framemd5"
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "info",
               *THREAD_MODES[threads], "-i", str(stream), "-noautoscale",
               "-fps_mode", "passthrough", "-map", "0:v:0",
               "-f", "rawvideo", "-pix_fmt", "yuv420p", str(raw),
               "-map", "0:v:0", "-noautoscale", "-fps_mode", "passthrough",
               "-vf", "showinfo", "-f", "framemd5", str(fmd5)]
        start = time.monotonic()
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            _, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return {"rc": "timeout", "frames": [], "dims": [], "md5": None,
                    "errors": [], "seconds": timeout, "sanitizer": False}
        seconds = time.monotonic() - start
        err = err.decode(errors="replace")
        frames = []
        if fmd5.exists():
            for line in fmd5.read_text().splitlines():
                if line and not line.startswith("#"):
                    parts = [p.strip() for p in line.split(",")]
                    frames.append((int(parts[4]), parts[5]))
        data = raw.read_bytes() if raw.exists() else b""
        return {
            "rc": proc.returncode,
            "frames": frames,
            "dims": re.findall(r"\bs:(\d+x\d+)\b", err),
            "md5": hashlib.md5(data).hexdigest(),
            "errors": sorted({re.sub(r"@ 0x[0-9a-f]+", "@", l) for l in err.splitlines()
                              if re.search(r"\[hevc @", l)})[:40],
            "seconds": round(seconds, 3),
            "sanitizer": "Sanitizer" in err or "runtime error:" in err,
        }


def max_rss_kib(ffmpeg, stream, timeout=120):
    """Peak RSS (KiB on Linux) of one single-threaded decode.

    Measured in a fresh interpreter so RUSAGE_CHILDREN covers only this decode.
    """
    probe = ("import resource, subprocess, sys; "
             "subprocess.run(sys.argv[1:], check=True, timeout=%d); "
             "print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)" % timeout)
    out = subprocess.run([sys.executable, "-c", probe, ffmpeg, "-nostdin", "-loglevel",
                          "quiet", "-threads", "1", "-i", str(stream), "-f", "null", "-"],
                         capture_output=True, text=True, check=True)
    return int(out.stdout.split()[-1])


# --------------------------------------------------------------------------
# Synthetic fixtures


def encode(encoder, out, size, frames, source, x265=""):
    subprocess.run([encoder, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"{source}=s={size}:r=25",
                    "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx265",
                    "-x265-params",
                    "log-level=error:pools=none:frame-threads=1:keyint=4" + x265,
                    "-f", "hevc", str(out)], check=True)
    return out


class Component:
    """A canonical encoder output split into parameter sets and the rest."""

    def __init__(self, path):
        self.path = path
        nals = nal.split_annexb(Path(path).read_bytes())
        # Repeated headers (one set per IDR) are allowed only if identical.
        self.vps = {n for n in nals if nal.nal_type(n) == nal.HEVC_NAL_VPS}
        self.sps = {n for n in nals if nal.nal_type(n) == nal.HEVC_NAL_SPS}
        self.pps = {n for n in nals if nal.nal_type(n) == nal.HEVC_NAL_PPS}
        if (len(self.vps), len(self.sps), len(self.pps)) != (1, 1, 1):
            raise SystemExit(f"{path}: expected one distinct VPS, SPS and PPS")
        (self.VPS,), (self.SPS,), (self.PPS,) = self.vps, self.sps, self.pps
        self.rest = [n for n in nals if nal.nal_type(n) not in
                     (nal.HEVC_NAL_VPS, nal.HEVC_NAL_SPS, nal.HEVC_NAL_PPS)]
        self.canonical = nals


class Oracle:
    """An expected-output stream decoded by the unpatched build, like a Component."""

    def __init__(self, path):
        self.path = path


# What the unpatched build must do with each fixture kind; None means no check.
UNPATCHED_MATCHES = {
    "unchanged": True, "same-as-base": True, "kept": True, "stale": True,
    "missing": True, "bounded": True, "delayed": False, "equivalent": None,
    "impact": True,
}


def build_fixtures(encoder, work):
    """Return {name: {stream, expected components (or None), kind, why}}."""
    work.mkdir(parents=True, exist_ok=True)
    A = Component(encode(encoder, work / "a.hevc", "176x144", 6, "testsrc2"))
    B = Component(encode(encoder, work / "b.hevc", "640x360", 6, "testsrc"))
    # 350x286 is not a multiple of the minimum coding block, so the SPS carries
    # a conformance (crop) window.
    C = Component(encode(encoder, work / "c.hevc", "350x286", 5, "smptebars"))
    # D's PPS signals diff_cu_qp_delta_depth 3, which FFmpeg rejects against E's
    # SPS (16x16 CTBs, 8x8 minimum coding blocks) but accepts against D's own.
    D = Component(encode(encoder, work / "d.hevc", "176x144", 6, "testsrc2",
                         ":ctu=64:qg-size=8"))
    E = Component(encode(encoder, work / "e.hevc", "176x144", 6, "testsrc2",
                         ":ctu=16:min-cu-size=8:qg-size=16"))
    # T has two temporal sub-layers; FFmpeg rejects its SPS against A's VPS.
    T = Component(encode(encoder, work / "t.hevc", "176x144", 6, "testsrc2",
                         ":temporal-layers=2"))
    # G: closed GOPs of 8 with headers repeated at each IDR.
    G = Component(encode(encoder, work / "g.hevc", "176x144", 17, "testsrc2",
                         ":keyint=8:min-keyint=8:open-gop=0:scenecut=0"))
    # H: B's size in closed GOPs of 8, so trailing pictures follow each IDR.
    H = Component(encode(encoder, work / "h.hevc", "640x360", 17, "testsrc",
                         ":keyint=8:min-keyint=8:open-gop=0:scenecut=0"))
    if A.SPS == B.SPS:
        raise SystemExit("components unexpectedly share an SPS")

    fx = {}

    def add(name, nals, expected, kind, why, forbid=()):
        path = work / f"{name}.hevc"
        path.write_bytes(nal.join_annexb(nals))
        fx[name] = {"stream": path, "expected": expected, "kind": kind, "why": why,
                    "forbid": forbid}

    add("canonical-a", A.canonical, [A], "unchanged",
        "encoder order; output must not change")
    add("canonical-crop-c", C.canonical, [C], "unchanged",
        "encoder order with a conformance window; output must not change")
    cut = A.canonical[:-1] + [A.canonical[-1][: len(A.canonical[-1]) // 2]]
    add("truncated-tail-a", cut, None, "same-as-base",
        "last slice cut in half; patched output must equal unpatched output")

    add("reversed-order", [A.PPS, A.SPS, A.VPS] + A.rest, [A], "delayed",
        "PPS before SPS before VPS")
    add("remapped-ids-delayed",
        [nal.set_pps_sps_id(A.PPS, 5), nal.set_sps_ids(A.SPS, vps_id=3, sps_id=5),
         nal.set_vps_id(A.VPS, 3)] + A.rest, [A], "delayed",
        "non-zero VPS/SPS ids, each referenced before it arrives")
    add("resolution-changes-delayed",
        A.canonical
        + [nal.set_pps_sps_id(B.PPS, 4), nal.set_sps_ids(B.SPS, vps_id=2, sps_id=4),
           nal.set_vps_id(B.VPS, 2)] + B.rest
        + [nal.set_sps_ids(C.SPS, vps_id=5, sps_id=6), nal.set_pps_sps_id(C.PPS, 6),
           nal.set_vps_id(C.VPS, 5)] + C.rest,
        [A, B, C], "delayed",
        "two native-size changes (one cropped) whose new parameter sets arrive out of order")
    add("pps-before-replacement-sps",
        A.canonical + [B.VPS, B.PPS, B.SPS] + B.rest, [A, B], "delayed",
        "a PPS sent before the SPS that replaces its SPS id is interpreted with the new SPS")
    if A.VPS == B.VPS:
        raise SystemExit("components unexpectedly share a VPS")
    add("sps-before-replacement-vps",
        A.canonical + [B.SPS, B.PPS, B.VPS] + B.rest, [A, B], "delayed",
        "an SPS sent before the VPS that replaces its VPS id is interpreted with the new VPS")
    first_slice = next(i for i, n in enumerate(A.canonical) if nal.nal_type(n) < 32)
    second_slice = next(i for i, n in enumerate(A.canonical)
                        if i > first_slice and nal.nal_type(n) < 32)
    add("pending-across-access-units",
        A.canonical[:second_slice]
        + [nal.set_sps_ids(B.SPS, vps_id=2, sps_id=4)]   # pending, unused by A
        + A.canonical[second_slice:]
        + [nal.set_vps_id(B.VPS, 2), nal.set_pps_sps_id(B.PPS, 4)] + B.rest,
        [A, B], "delayed",
        "pending state created in one access unit is resolved in a later one; "
        "with frame threads this crosses decoder thread contexts")
    add("pps-survives-incompatible-intermediate-sps",
        [D.VPS, D.PPS, E.SPS, D.SPS] + D.rest, [D], "delayed",
        "a pending PPS that fails against an intermediate incompatible SPS stays pending "
        "and resolves against the compatible replacement SPS before the first slice")
    add("pps-survives-present-incompatible-sps",
        [D.VPS, E.SPS, D.PPS, D.SPS] + D.rest, [D], "delayed",
        "a PPS that fails against the SPS already present resolves against the "
        "compatible replacement SPS before the first slice")
    add("sps-survives-present-incompatible-vps",
        [A.VPS, T.SPS, T.PPS, T.VPS] + T.rest, [T], "delayed",
        "an SPS that fails against the VPS already present resolves against the "
        "compatible replacement VPS, followed by its waiting PPS")
    add("invalid-replacement-sps-keeps-state",
        A.canonical
        + [nal.set_sps_chroma_format_idc(nal.set_sps_ids(A.SPS, vps_id=7), 4),
           nal.set_vps_id(A.VPS, 7)]         # the replacement fails to parse here
        + A.rest,
        [A, A], "kept",
        "a same-id SPS that fails once its VPS arrives leaves the valid SPS and PPS "
        "usable for later pictures")
    add("invalid-replacement-pps-keeps-state",
        A.canonical
        + [nal.set_pps_num_ref_idx_l0_minus1(nal.set_pps_sps_id(A.PPS, 9), 15),
           nal.set_sps_ids(A.SPS, sps_id=9)]  # the replacement fails to parse here
        + A.rest,
        [A, A], "kept",
        "a same-id PPS that fails once its SPS arrives leaves the valid PPS usable")
    add("unresolved-replacement-pps-not-stale",
        A.canonical
        + [nal.set_vps_id(B.VPS, 3), nal.set_pps_sps_id(B.PPS, 9)]
        + B.rest                             # must be rejected, not decoded with A's PPS
        + [nal.set_sps_ids(B.SPS, vps_id=3, sps_id=9)] + B.rest,
        [A, B], "delayed",
        "pictures activating a PPS id whose newest PPS still waits for its SPS are "
        "rejected instead of using the older stored PPS")
    add("unresolved-replacement-sps-not-stale",
        A.canonical
        + [nal.set_sps_ids(H.SPS, vps_id=3), H.PPS]
        + H.rest                             # must be refused, not decoded with A's SPS
        + [nal.set_vps_id(H.VPS, 3)] + H.rest,
        [A, H], "delayed",
        "an IRAP picture whose SPS id has a newer SPS still waiting for its VPS is "
        "refused, and so are the trailing pictures after it, instead of being decoded "
        "with the older stored SPS",
        # Trailing pictures decoded with the stale SPS fail on their references
        # instead of being refused; their output alone would not show it.
        forbid=("Error constructing the frame RPS", "Could not find ref"))
    add("stale-sps-not-revived",
        A.canonical
        + [nal.set_sps_ids(A.SPS, vps_id=7),  # pending on VPS 7, supersedes SPS 0
           B.VPS, B.SPS,                     # newer SPS 0 must discard the pending one
           nal.set_vps_id(A.VPS, 7),          # must not bring back A's SPS 0
           B.PPS] + B.rest,
        [A, B], "stale",
        "a pending SPS superseded by a newer SPS with the same id stays discarded")
    add("stale-pps-not-revived",
        A.canonical
        + [B.VPS, B.SPS,
           nal.set_pps_sps_id(A.PPS, 9),       # pending on SPS 9, supersedes PPS 0
           B.PPS,                              # newer PPS 0 must discard the pending one
           nal.set_sps_ids(A.SPS, sps_id=9)]   # must not bring back the stale PPS 0
        + B.rest,
        [A, B], "stale",
        "a pending PPS superseded by a newer PPS with the same id stays discarded")
    add("missing-dependency-never-arrives",
        [A.VPS, A.SPS, nal.set_pps_sps_id(A.PPS, 9)] + A.rest + B.canonical,
        [B], "missing",
        "slices whose PPS never gets its SPS produce no pictures; later valid data decodes")
    add("malformed-pending-sps",
        [A.VPS, nal.truncate_rbsp(nal.set_sps_ids(A.SPS, vps_id=7), 14),
         nal.set_vps_id(A.VPS, 7), A.PPS] + A.rest + [A.SPS] + A.rest,
        [A], "delayed",
        "a truncated pending SPS never produces pictures and is superseded by the later "
        "valid SPS, which the waiting PPS resolves against")

    # An SPS ending in empty extensions (sps_extension_4bits 0000), one payload bit
    # short. Parsed with its exact length it overreads by one bit and is rejected. A
    # parse over whole bytes would read the stop bit as the skipped last bit of
    # sps_extension_4bits and accept it, which can only happen when the shortened
    # payload does not end on a byte boundary; pick a component where it does not.
    X, short_sps = None, None
    for comp in (A, C, G, B, H, D, E):
        candidate = nal.drop_payload_bits(nal.set_sps_empty_extensions(comp.SPS), 1)
        if len(nal._payload(candidate).bits) % 8:
            X, short_sps = comp, candidate
            break
    if X is None:
        raise SystemExit("no component SPS gives a shortened payload off a byte boundary")
    on_time = work / "short-sps-on-time.hevc"
    on_time.write_bytes(nal.join_annexb([X.VPS, short_sps, X.PPS] + X.rest
                                        + [X.SPS, X.PPS] + X.rest))
    add("deferred-sps-uses-exact-length",
        [X.PPS, short_sps, X.VPS] + X.rest + [X.SPS, X.PPS] + X.rest,
        [Oracle(on_time)], "equivalent",
        "a deferred SPS whose payload ends one bit early is rejected exactly as it is when "
        "parsed on arrival, instead of reading the stop bit and padding; the valid copy "
        "that follows decodes")

    slices = [i for i, n in enumerate(G.canonical) if nal.nal_type(n) < 32]
    irap = [i for i in slices if 16 <= nal.nal_type(G.canonical[i]) <= 23]
    mid_gop = next(i for i in slices if i > irap[0] and i not in irap)
    if not any(i > mid_gop for i in irap):
        raise SystemExit("component G needs a second IRAP picture after a trailing one")
    add("corrupted-repeat-sps-mid-gop",
        G.canonical[:mid_gop] + [nal.set_sps_ids(G.SPS, vps_id=9)] + G.canonical[mid_gop:],
        [G], "kept",
        "a repeated SPS with a corrupted VPS id before a non-IRAP picture does not "
        "interrupt decoding, since an SPS can only change at an IRAP picture")
    add("corrupted-repeat-pps-mid-gop",
        G.canonical[:mid_gop] + [nal.set_pps_sps_id(G.PPS, 9)] + G.canonical[mid_gop:],
        [G], "impact",
        "a repeated PPS with a corrupted SPS id refuses the pictures up to the next PPS "
        "resend (a PPS may change at any picture); no stale or invented picture is output")

    flood = list(A.canonical[:3])
    for i in range(20000):
        flood.append(nal.set_pps_sps_id(nal.set_pps_id(A.PPS, 1 + i % 63), 1 + i % 15))
        flood.append(nal.set_sps_ids(A.SPS, vps_id=1 + i % 15, sps_id=1 + i % 15))
    for i in range(2000):  # replacement churn of the SPS that PPS 0 depends on
        flood.append(B.SPS if i % 2 == 0 else A.SPS)
    flood += [A.SPS, A.PPS] + A.rest
    add("flood-and-churn-bounded", flood, [A], "bounded",
        "20000 PPS and 20000 SPS whose dependencies never arrive, plus 2000 SPS "
        "replacements; memory and time stay bounded")

    churn = [A.VPS]
    churn += [nal.pad_payload(nal.set_sps_ids(A.SPS, sps_id=i), 60000) for i in range(16)]
    churn += [nal.pad_payload(nal.set_pps_sps_id(nal.set_pps_id(A.PPS, i), i % 16), 60000)
              for i in range(64)]
    for i in range(4000):  # alternate two versions of the VPS all of them depend on
        churn.append(B.VPS if i % 2 == 0 else A.VPS)
    churn += A.canonical
    add("vps-churn-large-dependants", churn, [A], "bounded",
        "16 SPS and 64 PPS of about 60 KiB each under 4000 alternating VPS versions; "
        "time and memory are compared with the unpatched build")
    return fx, [A, B, C, D, E, G, H, T]


def expected_output(base, components, threads):
    frames, data, dims = [], b"", []
    for comp in components:
        r = decode(base, comp.path, threads)
        frames += r["frames"]
        dims += r["dims"]
        with tempfile.NamedTemporaryFile() as tmp:
            subprocess.run([base, "-nostdin", "-loglevel", "error", "-y", "-i",
                            str(comp.path), "-noautoscale", "-fps_mode", "passthrough",
                            "-f", "rawvideo", "-pix_fmt", "yuv420p", tmp.name], check=True)
            data += Path(tmp.name).read_bytes()
    return {"frames": frames, "dims": dims, "md5": hashlib.md5(data).hexdigest()}


def same(result, expected):
    return (result["rc"] == 0 and result["frames"] == expected["frames"]
            and result["dims"] == expected["dims"] and result["md5"] == expected["md5"])


def run_fixtures(base, fixed, encoder, work, sanitized=None):
    fixtures, _ = build_fixtures(encoder, work / "fixtures")
    report, failures = {}, []
    for name, fx in fixtures.items():
        entry = {"kind": fx["kind"], "why": fx["why"], "synthetic": True, "modes": {}}
        for mode in THREAD_MODES:
            base_r = decode(base, fx["stream"], mode)
            fixed_r = decode(fixed, fx["stream"], mode)
            if fx["expected"] is None:
                exp = {k: base_r[k] for k in ("frames", "dims", "md5")}
            else:
                exp = expected_output(base, fx["expected"], mode)
            m = {
                "expected_frames": len(exp["frames"]),
                "expected_dims": exp["dims"],
                "base_frames": len(base_r["frames"]),
                "base_matches": same(base_r, exp),
                "fixed_frames": len(fixed_r["frames"]),
                "fixed_dims": fixed_r["dims"],
                "fixed_matches": same(fixed_r, exp),
                "fixed_md5": fixed_r["md5"],
                "fixed_errors": fixed_r["errors"],
                "fixed_seconds": fixed_r["seconds"],
            }
            m["base_seconds"] = base_r["seconds"]
            forbidden = [e for e in fixed_r["errors"] for f in fx["forbid"] if f in e]
            if forbidden:
                m["fixed_matches"] = False
                m["fixed_forbidden_errors"] = forbidden
            if fx["kind"] == "impact":
                # Refused pictures are allowed; anything output must be a picture of
                # the expected stream, in order.
                exp_frames = iter(exp["frames"])
                subset = all(f in exp_frames for f in fixed_r["frames"])
                # A proper, non-empty subsequence: neither a full stale decode nor
                # no output at all counts as refusing exactly the affected pictures.
                m["fixed_matches"] = (fixed_r["rc"] == 0 and subset
                                      and 0 < len(fixed_r["frames"]) < len(exp["frames"]))
                m["fixed_refused_frames"] = len(exp["frames"]) - len(fixed_r["frames"])
            if not m["fixed_matches"]:
                failures.append(f"{name}/{mode}: patched output differs from expectation")
            want = UNPATCHED_MATCHES[fx["kind"]]
            if want is not None and m["base_matches"] != want:
                failures.append(f"{name}/{mode}: unpatched build "
                                f"{'does not match' if want else 'already matches'} "
                                "the expectation; fixture premise is wrong")
            if sanitized:
                san_r = decode(sanitized, fx["stream"], mode, timeout=600)
                if fx["kind"] == "impact":
                    m["sanitized_matches"] = (san_r["frames"] == fixed_r["frames"]
                                              and san_r["rc"] == 0 and not san_r["sanitizer"])
                else:
                    m["sanitized_matches"] = same(san_r, exp) and not san_r["sanitizer"]
                if not m["sanitized_matches"]:
                    failures.append(f"{name}/{mode}: sanitizer build failed or differs")
            entry["modes"][mode] = m
        if fx["kind"] == "bounded":
            b, f = max_rss_kib(base, fx["stream"]), max_rss_kib(fixed, fx["stream"])
            entry["max_rss_kib"] = {"base": b, "fixed": f}
            base_s = decode(base, fx["stream"], "single")["seconds"]
            fixed_s = decode(fixed, fx["stream"], "single")["seconds"]
            entry["single_thread_seconds"] = {"base": base_s, "fixed": fixed_s}
            if f > b + 64 * 1024:
                failures.append(f"{name}: patched peak RSS {f} KiB exceeds base {b} KiB + 64 MiB")
            if fixed_s > 2 * base_s + 1:
                failures.append(f"{name}: patched decode took {fixed_s}s, unpatched {base_s}s "
                                "(limit twice unpatched + 1 s)")
        report[name] = entry
    return report, failures


# --------------------------------------------------------------------------
# Original conformance vector


def obtain_vector(args, work):
    if args.vector:
        path = Path(args.vector)
    else:
        path = work / "vector" / VECTOR["input_file"]
        if not path.exists():
            if not args.download:
                raise SystemExit("pass --vector PATH or --download (fetches from "
                                 f"{VECTOR['source']}; see README.md for terms)")
            import urllib.request
            path.parent.mkdir(parents=True, exist_ok=True)
            zpath = path.parent / "vector.zip"
            urllib.request.urlretrieve(VECTOR["source"], zpath)
            if hashlib.md5(zpath.read_bytes()).hexdigest() != VECTOR["source_md5"]:
                raise SystemExit("downloaded archive MD5 mismatch")
            with zipfile.ZipFile(zpath) as z:
                path.write_bytes(z.read(VECTOR["input_file"]))
    if sha256(path) != VECTOR["sha256"]:
        raise SystemExit(f"{path}: SHA-256 does not match the corpus manifest")
    return path


def run_vector(base, fixed, path, sanitized=None):
    report, failures = {}, []
    for mode in THREAD_MODES:
        b = decode(base, path, mode)
        f = decode(fixed, path, mode)
        m = {
            "base_md5": b["md5"], "base_frames": len(b["frames"]), "base_dims": b["dims"],
            "fixed_md5": f["md5"], "fixed_frames": len(f["frames"]), "fixed_dims": f["dims"],
            "fixed_errors": f["errors"],
        }
        if f["rc"] != 0 or f["md5"] != VECTOR["reference_md5"] or f["dims"] != VECTOR["dims"]:
            failures.append(f"vector/{mode}: patched output is not the complete reference")
        m["base_rc"] = b["rc"]
        if (b["rc"] != 0 or b["md5"] != VECTOR["unpatched_md5"]
                or len(b["frames"]) != VECTOR["unpatched_frames"]):
            failures.append(f"vector/{mode}: unpatched build does not reproduce the "
                            "documented failure")
        if sanitized:
            s = decode(sanitized, path, mode, timeout=600)
            m["sanitized_md5"] = s["md5"]
            m["sanitized_rc"] = s["rc"]
            m["sanitizer_report"] = s["sanitizer"]
            if (s["rc"] != 0 or s["md5"] != VECTOR["reference_md5"]
                    or s["dims"] != VECTOR["dims"] or s["sanitizer"]):
                failures.append(f"vector/{mode}: sanitizer build failed or differs")
        report[mode] = m
    return report, failures


# --------------------------------------------------------------------------
# Full Fluster suite (optional)


def ps_key(n):
    t = nal.nal_type(n)
    if t == nal.HEVC_NAL_VPS:
        return (t, nal.vps_ids(n)["vps_id"])
    if t == nal.HEVC_NAL_SPS:
        return (t, nal.sps_ids(n)["sps_id"])
    return (t, nal.pps_ids(n)["pps_id"])


def reorder_parameter_sets(data):
    """Reverse each run of consecutive VPS/SPS/PPS NAL units whose ids are distinct.

    Returns the new stream and the number of runs changed, or (None, 0) when no run
    can be reordered without changing which parameter set is newest for an id."""
    nals = nal.split_annexb(data)
    out, changed, i = [], 0, 0
    while i < len(nals):
        j = i
        while j < len(nals) and nal.nal_type(nals[j]) in (32, 33, 34):
            j += 1
        if j - i > 1:
            run = nals[i:j]
            try:
                keys = [ps_key(n) for n in run]
            except ValueError:
                keys = None
            if keys and len(set(keys)) == len(keys) and run[::-1] != run:
                run = run[::-1]
                changed += 1
            out += run
            i = j
        else:
            out.append(nals[i])
            i += 1
    return (nal.join_annexb(out), changed) if changed else (None, 0)


def decode_md5(binary, path, mode, pix):
    with tempfile.NamedTemporaryFile() as tmp:
        rc = subprocess.run([binary, "-nostdin", "-loglevel", "quiet", "-y",
                             *THREAD_MODES[mode], "-i", str(path),
                             "-noautoscale", "-fps_mode", "passthrough",
                             "-f", "rawvideo", "-pix_fmt", pix, tmp.name],
                            timeout=600).returncode
        return rc, hashlib.md5(Path(tmp.name).read_bytes()).hexdigest()


def run_suite(base, fixed, suite_json, resources, modes, reorder=False):
    suite = json.loads(Path(suite_json).read_text())
    report, failures = {}, []
    for vec in suite["test_vectors"]:
        path = Path(resources) / suite["name"] / vec["name"] / vec["input_file"]
        if not path.exists():
            failures.append(f"suite/{vec['name']}: resource missing at {path}")
            continue
        pix = vec.get("output_format", "yuv420p")
        row = {}
        for mode in modes:
            for label, binary in (("base", base), ("fixed", fixed)):
                rc, md5 = decode_md5(binary, path, mode, pix)
                # A decoder that crashes after writing matching bytes is not a pass.
                row[f"{label}_{mode}"] = {"rc": rc, "pass": rc == 0 and md5 == vec["result"],
                                          "md5": md5}
            b, f = row[f"base_{mode}"], row[f"fixed_{mode}"]
            if b["pass"] and not f["pass"]:
                failures.append(f"suite/{vec['name']}/{mode}: regression")
            if not b["pass"] and not f["pass"] and b["md5"] != f["md5"]:
                row[f"changed_failure_{mode}"] = True
        if reorder:
            # The same parameter sets, each run reversed, must decode identically:
            # this parses real-world parameter sets late.
            data, runs = reorder_parameter_sets(path.read_bytes())
            if data is not None:
                with tempfile.TemporaryDirectory() as tmp:
                    moved = Path(tmp) / "reordered.bit"
                    moved.write_bytes(data)
                    rc, md5 = decode_md5(fixed, moved, "single", pix)
                ref_rc, ref_md5 = decode_md5(fixed, path, "single", pix)
                # Equal exit status and output; a vector both orders fail to decode
                # identically also matches.
                same_out = rc == ref_rc and md5 == ref_md5
                row["reordered_single"] = {"runs": runs, "rc": rc, "md5": md5,
                                           "matches_original": same_out}
                if not same_out:
                    failures.append(f"suite/{vec['name']}: reordered parameter sets decode "
                                    "differently from the original order")
        report[vec["name"]] = row
    summary = {}
    for mode in modes:
        summary[mode] = {
            "total": len(report),
            "base_pass": sum(r[f"base_{mode}"]["pass"] for r in report.values()),
            "fixed_pass": sum(r[f"fixed_{mode}"]["pass"] for r in report.values()),
            "newly_passing": sorted(n for n, r in report.items()
                                    if r[f"fixed_{mode}"]["pass"] and not r[f"base_{mode}"]["pass"]),
            "regressions": sorted(n for n, r in report.items()
                                  if r[f"base_{mode}"]["pass"] and not r[f"fixed_{mode}"]["pass"]),
            "fixed_failing": sorted(n for n, r in report.items() if not r[f"fixed_{mode}"]["pass"]),
        }
    if reorder:
        rows = [r["reordered_single"] for r in report.values() if "reordered_single" in r]
        summary["reordered"] = {"vectors": len(rows),
                                "matching": sum(r["matches_original"] for r in rows)}
    return {"summary": summary, "vectors": report}, failures


# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=os.path.expanduser("~/.cache/omarchy-hevc-parameter-sets"),
                    help="build and fixture directory (default: %(default)s)")
    ap.add_argument("--base", help="prebuilt unpatched ffmpeg (skips the build)")
    ap.add_argument("--fixed", help="prebuilt patched ffmpeg (skips the build)")
    ap.add_argument("--sanitize", action="store_true",
                    help="also build and run the patched decoder under ASan/UBSan")
    ap.add_argument("--encoder", default="ffmpeg",
                    help="ffmpeg with libx265 used only to generate synthetic fixtures")
    ap.add_argument("--vector", help=f"path to {VECTOR['input_file']}")
    ap.add_argument("--download", action="store_true",
                    help="download the vector from its ITU source if not cached")
    ap.add_argument("--skip-fixtures", action="store_true")
    ap.add_argument("--suite-json", help="Fluster test_suites/h.265/JCT-VC-HEVC_V1.json")
    ap.add_argument("--suite-resources", help="Fluster resources directory for --suite-json")
    ap.add_argument("--suite-reorder", action="store_true",
                    help="also decode each suite vector with its parameter-set runs reversed")
    ap.add_argument("--suite-modes", default="auto",
                    help="comma-separated thread modes for the suite (default: auto)")
    ap.add_argument("--output", help="write the JSON report here as well")
    args = ap.parse_args()

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    if bool(args.base) != bool(args.fixed):
        raise SystemExit("--base and --fixed must be given together")
    if args.base:
        base, fixed = args.base, args.fixed
    else:
        out = subprocess.run(["sh", str(HERE / "build-ffmpeg.sh"), str(work)],
                             check=True, capture_output=True, text=True).stdout.split()
        base, fixed = out[-2], out[-1]
    sanitized = None
    if args.sanitize:
        out = subprocess.run(["sh", str(HERE / "build-ffmpeg.sh"), str(work), "--sanitize"],
                             check=True, capture_output=True, text=True).stdout.split()
        sanitized = out[-1]

    report = {
        "schema": "omarchy-m1-video.hevc-parameter-sets/1",
        "ffmpeg_commit": SOURCE["ffmpeg"]["commit"],
        "patch_sha256": sha256(HERE / SOURCE["patch"]["file"]),
        "hardware_decode": False,
        "va_device_used": False,
    }
    failures = []
    if report["patch_sha256"] != SOURCE["patch"]["sha256"]:
        failures.append("patch SHA-256 does not match source.json")

    report["vector"], f = run_vector(base, fixed, obtain_vector(args, work), sanitized)
    failures += f
    if not args.skip_fixtures:
        report["fixtures"], f = run_fixtures(base, fixed, args.encoder, work, sanitized)
        failures += f
    if args.suite_json:
        if not args.suite_resources:
            raise SystemExit("--suite-json needs --suite-resources")
        if sha256(args.suite_json) != SOURCE["suite"]["sha256"]:
            failures.append("suite JSON SHA-256 does not match source.json")
        report["suite"], f = run_suite(base, fixed, args.suite_json, args.suite_resources,
                                       args.suite_modes.split(","), args.suite_reorder)
        failures += f

    report["failures"] = failures
    report["result"] = "pass" if not failures else "fail"
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(text + "\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
