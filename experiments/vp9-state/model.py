#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Queue/reference-state model for AVD VP9 resize (omarchy-m1-video#42).

This is an offline contract checker. It does not decode frames, open a
device, or establish firmware behaviour. Accepted proposed sequences are
explicitly not decoded-frame evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = "omarchy-m1-video.vp9-state/1"
KERNEL_COMMIT = "94fb23346d522edf53722357c426a3e58030beea"
SOURCE_MAP = json.loads((HERE / "source-map.json").read_text())
INVARIANTS = {item["id"]: item for item in SOURCE_MAP["invariants"]}

ALIGN_W, ALIGN_H, MIN_DIM = 64, 16, 64
# Userspace dest timestamps in the design: (capture_index + 1) * 1000.
TS_SCALE = 1000
# Proposed registrations use a separate identity space so they cannot
# collide with index-derived dest timestamps after a generation bump.
REG_TS_BASE = 1_000_000


class FixtureError(ValueError):
    """Malformed or truncated fixture; not a modelled kernel/userspace reject."""


# Validate values before changing state: Python truthiness and numeric coercion
# must not turn malformed fixture data into an accepted contract sequence.
EVENT_FIELDS = {
    "open": ((), ("session",)),
    "output_s_fmt": (("width", "height"), ()),
    "capture_s_fmt": (("width", "height"), ("bit_depth",)),
    "proposed_reconfigure": (("width", "height"), ("bit_depth",)),
    "capture_reqbufs": (("count",), ()),
    "queue_dst": (("dst",), ("backing_bytes",)),
    "decode": (("dst", "width", "height"), ("bit_depth", "key", "refs", "backing_bytes", "force_kernel_lookup")),
    "export": (("name",), ("backing_bytes",)),
    "register": (("name",), ("timestamp", "index")),
    "inject_failure": ((), ("phase",)),
    "ask_firmware": ((), ("question",)),
    **{op: ((), ()) for op in ("output_streamon", "output_streamoff",
                              "capture_streamon", "capture_streamoff", "snapshot")},
}
EVENT_FIELDS["submit"] = EVENT_FIELDS["decode"]


def validate_event(event):
    if not isinstance(event, dict) or not isinstance(event.get("op"), str):
        raise FixtureError("event requires a string op")
    op = event["op"]
    if op not in EVENT_FIELDS:
        raise FixtureError(f"unknown op {op!r}")
    required, optional = EVENT_FIELDS[op]
    if set(required) - event.keys() or event.keys() - {"op", *required, *optional}:
        raise FixtureError(f"invalid or missing fields for {op}")
    for key, value in event.items():
        if key in ("width", "height", "bit_depth", "count", "backing_bytes", "timestamp", "index"):
            if type(value) is not int or value < 0 or value > (1 << 64) - 1:
                raise FixtureError(f"{key} must be an unsigned integer")
        elif key in ("key", "force_kernel_lookup"):
            if type(value) is not bool:
                raise FixtureError(f"{key} must be boolean")
        elif key == "refs":
            if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
                raise FixtureError("refs must be a list of buffer names")
        elif not isinstance(value, str) or not value:
            raise FixtureError(f"{key} must be a nonempty string")


class Reject(Exception):
    def __init__(self, code, message, invariant):
        super().__init__(message)
        self.code = code
        self.message = message
        self.invariant = invariant
        self.kind = INVARIANTS[invariant]["kind"]


def round_up(n, a):
    return (n + a - 1) // a * a


def align(n, a):
    return round_up(n, a)


def div_round_up(n, d):
    return (n + d - 1) // d


def roundup_pow_of_two(n):
    if n <= 1:
        return 1 if n else 0
    return 1 << (n - 1).bit_length()


def calc_tile_meta(w, h, bpb, tile_dim, meta_hdr_bytes):
    """Match avd-drv.c:26-38 calc_tile_meta (invariant fill_comp_layout)."""
    tiles_w = div_round_up(w, tile_dim)
    tiles_h = div_round_up(h, tile_dim)
    tile_bytes = tile_dim * tile_dim * div_round_up(bpb, 8)
    tile = align(tiles_w * tiles_h * tile_bytes, 16)
    meta_w = roundup_pow_of_two(tiles_w)
    meta_h = roundup_pow_of_two(tiles_h)
    meta = align(meta_w * meta_h * meta_hdr_bytes, 16)
    return tile, meta


def fill_comp(width, height, bit_depth):
    """Return (size, offsets) matching avd-drv.c:41-69."""
    y, y_meta = calc_tile_meta(width, height, bit_depth, 32, 32)
    uv, uv_meta = calc_tile_meta(width // 2, height // 2, bit_depth * 2, 16, 8)
    offsets = [y, 0, y + y_meta + uv, y + y_meta]
    return y_meta + y + uv_meta + uv, offsets


def pixel_plane(width, height, bit_depth):
    bpp = 2 if bit_depth == 10 else 1
    return width * height * bpp + (width * height * bpp) // 2


def era_sizeimage(aligned_w, aligned_h, bit_depth):
    comp_size, _ = fill_comp(aligned_w, aligned_h, bit_depth)
    return pixel_plane(aligned_w, aligned_h, bit_depth) + comp_size


def fourcc_for(bit_depth):
    return "P010" if bit_depth == 10 else "NV12"


class Era:
    def __init__(self, era_id, width, height, bit_depth):
        self.id = era_id
        self.width = width
        self.height = height
        self.bit_depth = bit_depth
        self.aligned_w = round_up(width, ALIGN_W)
        self.aligned_h = round_up(height, ALIGN_H)
        self.fourcc = fourcc_for(bit_depth)
        self.sizeimage = era_sizeimage(self.aligned_w, self.aligned_h, bit_depth)
        self.comp_size, self.comp_offsets = fill_comp(
            self.aligned_w, self.aligned_h, bit_depth)
        self.start_offset = pixel_plane(self.aligned_w, self.aligned_h, bit_depth)


class Buffer:
    def __init__(self, name, era, backing_bytes=None):
        self.name = name
        self.era_id = era.id
        self.width = era.width
        self.height = era.height
        self.bit_depth = era.bit_depth
        self.sizeimage = era.sizeimage
        self.backing_bytes = era.sizeimage if backing_bytes is None else backing_bytes
        self.index = None
        self.generation = None
        self.timestamp = None
        self.decoded_ok = False
        self.exported = False
        self.queued_as_dst = False
        self.wrapper_alive = False
        self.content_id = name


class Session:
    """One decoder session. Profile/device never key entropy or references."""

    def __init__(self, path, session_id="s1", profile=0, bit_depth=8):
        if path not in ("stock", "proposed"):
            raise FixtureError(f"unknown path {path!r}")
        if type(profile) is not int or profile not in (0, 2):
            raise FixtureError("only advertised VP9 profiles 0 and 2 are modelled")
        if type(bit_depth) is not int or bit_depth not in (8, 10):
            raise FixtureError("bit_depth must be 8 or 10")
        if (profile == 0 and bit_depth != 8) or (profile == 2 and bit_depth != 10):
            raise FixtureError("profile 0 is 8-bit NV12; profile 2 is 10-bit P010")
        self.path = path
        self.session_id = session_id
        self.profile = profile
        self.bit_depth = bit_depth
        self.failed = False
        self.destructive_done = False
        self.output_streaming = False
        self.capture_streaming = False
        self.capture_slots = 0
        self.capture_generation = 0
        self.current_era = None
        self.coded_w = None
        self.coded_h = None
        self.eras = {}
        self.buffers = {}
        self.slot = {}  # index -> name in the current generation
        self.ts_index = {}  # (generation, timestamp) -> name
        self.registrations = {}
        self.probabilities = False
        self.last_present = False
        self.scratch_present = False
        self.scratch_w = None
        self.scratch_h = None
        self.scratch_depth = None
        self.seg_present = False
        self.seg_policy = "absent"
        self.next_reg_ts = REG_TS_BASE
        self.events_applied = 0

    def snapshot(self):
        lost = []
        if not any(b.wrapper_alive for b in self.buffers.values()):
            if self.buffers:
                lost.append("wrapper_metadata")
        if not self.probabilities:
            lost.append("frame_context")
        if not self.last_present:
            lost.append("last_frame_info")
        if not self.scratch_present:
            lost.append("scratch")
        if self.seg_policy in ("lost", "absent"):
            lost.append("seg_map")
        elif self.seg_policy == "unknown":
            lost.append("seg_map_policy_unknown")
        return {
            "path": self.path,
            "session": self.session_id,
            "generation": self.capture_generation,
            "output_streaming": self.output_streaming,
            "capture_streaming": self.capture_streaming,
            "capture_slots": self.capture_slots,
            "probabilities": self.probabilities,
            "last_present": self.last_present,
            "scratch_present": self.scratch_present,
            "seg_policy": self.seg_policy,
            "failed": self.failed,
            "destructive_done": self.destructive_done,
            "era": None if self.current_era is None else {
                "id": self.current_era.id,
                "width": self.current_era.width,
                "height": self.current_era.height,
                "aligned": [self.current_era.aligned_w, self.current_era.aligned_h],
                "bit_depth": self.current_era.bit_depth,
                "fourcc": self.current_era.fourcc,
                "sizeimage": self.current_era.sizeimage,
            },
            "lost": lost,
            "decoded_frame_evidence": False,
        }

    def apply(self, event):
        validate_event(event)
        op = event["op"]
        handler = getattr(self, f"op_{op}", None)
        if handler is None:
            raise FixtureError(f"unknown op {op!r}")
        if self.failed and op not in ("snapshot",):
            # Further work on a failed session is the partial-failure case
            # except for explicit observation.
            if op in ("decode", "submit", "register", "queue_dst",
                      "proposed_reconfigure", "capture_streamon"):
                raise Reject("partial_failure_reuse",
                             "session is failed after an incomplete destructive phase",
                             "failed_session_no_submit")
        handler(event)
        self.events_applied += 1

    def _need_era(self, width, height, bit_depth=None):
        bit_depth = self.bit_depth if bit_depth is None else bit_depth
        if width < MIN_DIM or height < MIN_DIM:
            raise Reject("sub64",
                         f"coded {width}x{height} is below the AVD minimum",
                         "validate_dec_params_min64")
        era_id = 0 if not self.eras else max(self.eras) + 1
        era = Era(era_id, width, height, bit_depth)
        self.eras[era_id] = era
        return era

    def _capture_busy(self):
        return self.capture_slots > 0

    def op_open(self, event):
        # Already constructed; allow an explicit no-op for fixture readability.
        if event.get("session"):
            if self.events_applied and event["session"] != self.session_id:
                raise Reject("session_identity_change", "cannot inherit another session's state",
                             "session_not_profile_key")
            self.session_id = event["session"]

    def op_output_s_fmt(self, event):
        w, h = event["width"], event["height"]
        if self.output_streaming:
            raise Reject("streaming_output_s_fmt",
                         "S_FMT OUTPUT while streaming is -EBUSY on stock AVD",
                         "output_s_fmt_streaming")
        if self._capture_busy():
            raise Reject("busy_capture_s_fmt",
                         "S_FMT OUTPUT while CAPTURE is busy is -EBUSY",
                         "output_s_fmt_capture_busy")
        self.coded_w, self.coded_h = w, h

    def op_capture_s_fmt(self, event):
        if self._capture_busy():
            raise Reject("busy_capture_s_fmt",
                         "S_FMT CAPTURE while buffers are allocated is -EBUSY",
                         "capture_s_fmt_busy")
        w, h = event["width"], event["height"]
        depth = event.get("bit_depth", self.bit_depth)
        if depth != self.bit_depth:
            raise Reject("mixed_depth",
                         "image-format/bit-depth change is not a legal mid-session mix",
                         "image_fmt_busy")
        era = self._need_era(w, h, depth)
        self.current_era = era

    def op_output_streamon(self, event):
        if self.output_streaming:
            return  # Repeated STREAMON does not allocate a fresh codec context.
        if self.coded_w is None:
            raise FixtureError("OUTPUT STREAMON before S_FMT")
        self.output_streaming = True
        self.probabilities = True
        self.last_present = True
        self.scratch_present = True
        self.scratch_w = self.coded_w
        self.scratch_h = self.coded_h
        self.scratch_depth = self.bit_depth
        self.seg_present = True
        self.seg_policy = "present"

    def op_output_streamoff(self, event):
        self.output_streaming = False
        self.probabilities = False
        self.last_present = False
        self.scratch_present = False
        self.scratch_w = self.scratch_h = self.scratch_depth = None
        self.seg_present = False
        self.seg_policy = "lost"

    def op_capture_streamon(self, event):
        if self.capture_slots <= 0:
            raise FixtureError("CAPTURE STREAMON without buffers")
        self.capture_streaming = True

    def op_capture_streamoff(self, event):
        self.capture_streaming = False

    def op_capture_reqbufs(self, event):
        count = event["count"]
        if count < 0:
            raise FixtureError("capture_reqbufs count must be >= 0")
        if self.capture_streaming:
            raise Reject("streaming_reqbufs", "REQBUFS requires CAPTURE STREAMOFF",
                         "reqbufs_replaces_queue")
        if count == 0 or self.capture_slots:
            for buf in self.buffers.values():
                buf.wrapper_alive = False
                buf.queued_as_dst = False
                buf.index = None
                buf.generation = None
                # timestamp is left on the object so aliasing can be named,
                # but it is no longer in the current-generation index.
            self.slot.clear()
            self.capture_slots = 0
            self.capture_generation += 1
            self.destructive_done = True
            self.registrations.clear()
            if count == 0:
                return
        if self.current_era is None:
            raise FixtureError("REQBUFS before CAPTURE S_FMT")
        self.capture_slots = count
        self.slot = {}

    def _alloc_index(self, name):
        if self.capture_slots <= 0:
            raise FixtureError("decode/queue without CAPTURE buffers")
        used = set(self.slot)
        for i in range(self.capture_slots):
            if i not in used:
                self.slot[i] = name
                return i
        raise Reject("no_capture_buffer",
                     "no free CAPTURE index in this generation",
                     "queue_setup_sizeimage")

    def op_queue_dst(self, event):
        name = event["dst"]
        buf = self.buffers.get(name)
        if buf is None:
            if self.current_era is None:
                raise FixtureError("queue_dst before CAPTURE S_FMT")
            backing = event.get("backing_bytes", self.current_era.sizeimage)
            buf = Buffer(name, self.current_era, backing)
            self.buffers[name] = buf
        if name in self.registrations:
            raise Reject("reference_queued_as_destination",
                         "a registered reference must not be queued as a destination",
                         "ref_not_queued_as_dst")
        if buf.queued_as_dst:
            raise Reject("duplicate_destination", "destination already has a live CAPTURE slot",
                         "unique_destination_slot")
        if buf.backing_bytes < self.current_era.sizeimage:
            raise Reject("short_backing",
                         "imported plane is shorter than current sizeimage/min_length",
                         "vb2_dmabuf_min_length")
        idx = self._alloc_index(name)
        buf.index = idx
        buf.generation = self.capture_generation
        buf.timestamp = (idx + 1) * TS_SCALE
        buf.wrapper_alive = True
        buf.queued_as_dst = True
        key = (self.capture_generation, buf.timestamp)
        if key in self.ts_index and self.ts_index[key] != name:
            raise Reject("old_generation_alias",
                         "index-derived timestamp already names different content",
                         "generation_scoped_timestamps")
        self.ts_index[key] = name

    def op_decode(self, event):
        if self.failed:
            raise Reject("partial_failure_reuse",
                         "decode on a failed session",
                         "failed_session_no_submit")
        if not self.output_streaming or not self.probabilities:
            raise Reject("state_loss",
                         "VP9 context is not alive (OUTPUT not streaming)",
                         "stop_on_output_streamoff")
        if not self.capture_streaming or not self.capture_slots:
            raise Reject("capture_not_streaming", "decode completion requires both streaming queues",
                         "both_queues_streaming")
        w, h = event["width"], event["height"]
        if w < MIN_DIM or h < MIN_DIM:
            raise Reject("sub64",
                         f"coded {w}x{h} is below the AVD minimum",
                         "validate_dec_params_min64")
        if self.current_era is None:
            raise FixtureError("decode before CAPTURE S_FMT")
        if (round_up(w, ALIGN_W) != self.current_era.aligned_w or
                round_up(h, ALIGN_H) != self.current_era.aligned_h):
            raise Reject("unexpected_resolution",
                         "bitstream aligned size does not match CAPTURE format",
                         "validate_dec_params_aligned")
        depth = event.get("bit_depth", self.bit_depth)
        if depth != self.bit_depth:
            raise Reject("mixed_depth",
                         "mixed NV12/P010 references or destinations are rejected",
                         "image_fmt_busy")
        key_frame = bool(event.get("key", False))
        refs = list(event.get("refs") or [])
        if key_frame and refs:
            raise FixtureError("key frames do not take inter references in this model")
        if not key_frame:
            self._resolve_refs(refs, event)
        if (not self.scratch_present or self.scratch_depth != depth or
                any(div_round_up(w, a) > div_round_up(self.scratch_w, a) or
                    div_round_up(h, a) > div_round_up(self.scratch_h, a)
                    for a in (8, 16, 64))):
            raise Reject("scratch_bounds", "frame exceeds the allocated scratch geometry",
                         "scratch_capacity_contract")
        name = event["dst"]
        if name not in self.buffers or not self.buffers[name].queued_as_dst:
            # Implicit queue as destination at current era size.
            self.op_queue_dst({"dst": name, "backing_bytes": event.get("backing_bytes")})
        buf = self.buffers[name]
        buf.decoded_ok = True
        buf.era_id = self.current_era.id
        buf.width = w
        buf.height = h
        buf.bit_depth = depth
        self.last_present = True

    def _resolve_refs(self, refs, event):
        force_kernel = bool(event.get("force_kernel_lookup", False))
        dst_name = event["dst"]
        for ref_name in refs:
            if ref_name == dst_name:
                raise Reject("reference_queued_as_destination",
                             "decode cannot overwrite its own live reference",
                             "ref_not_queued_as_dst")
            if self.path == "stock" and not force_kernel:
                self._resolve_stock_userspace(ref_name)
            elif self.path == "stock" and force_kernel:
                self._resolve_stock_kernel(ref_name, dst_name)
            else:
                self._resolve_proposed(ref_name)

    def _resolve_stock_userspace(self, ref_name):
        buf = self.buffers.get(ref_name)
        if (buf is None or not buf.wrapper_alive or not buf.decoded_ok or
                buf.generation != self.capture_generation):
            raise Reject("unavailable_reference",
                         "r10+ userspace rejects an inter picture whose "
                         "reference is not bound to this CAPTURE generation",
                         "wrapper_on_queue")

    def _resolve_stock_kernel(self, ref_name, dst_name):
        """Reproduce avd_get_ref_buf. Used only to name the r9 fault; never accept."""
        buf = self.buffers.get(ref_name)
        ts = None if buf is None else buf.timestamp
        found = self.ts_index.get((self.capture_generation, ts)) if ts is not None else None
        if found is None:
            raise Reject("destination_fallback",
                         "timestamp miss returns the destination buffer "
                         "(avd_get_ref_buf fallback)",
                         "get_ref_fallback_dst")
        if found != ref_name:
            raise Reject("old_generation_alias",
                         "current-generation timestamp hit different content",
                         "generation_scoped_timestamps")

    def _resolve_proposed(self, ref_name):
        buf = self.buffers.get(ref_name)
        if buf is None:
            raise Reject("orphaned_retained_buffer",
                         "reference name is unknown to the session",
                         "explicit_ref_registration")
        if buf.bit_depth != self.bit_depth:
            raise Reject("mixed_depth",
                         "old-size reference depth/fourcc does not match the session",
                         "image_fmt_busy")
        era = self.eras[buf.era_id]
        if buf.backing_bytes < era.sizeimage:
            raise Reject("short_backing",
                         "reference backing is shorter than its own era sizeimage",
                         "era_sizing_dst_vs_ref")
        reg = self.registrations.get(ref_name)
        if reg is not None:
            # Imported references stay off the destination queue.
            if buf.queued_as_dst:
                raise Reject("reference_queued_as_destination",
                             "a registered reference must not be queued as a destination",
                             "ref_not_queued_as_dst")
            if reg["generation"] != self.capture_generation:
                raise Reject("stale_registration",
                             "registration is for a previous CAPTURE generation",
                             "generation_scoped_timestamps")
            return
        # Unregistered in-era DPB: a current-generation decoded dest is a
        # legal reference. Cross-generation use requires register().
        if (buf.wrapper_alive and buf.decoded_ok and
                buf.generation == self.capture_generation):
            return
        if buf.exported and not buf.wrapper_alive:
            raise Reject("orphaned_retained_buffer",
                         "exported backing was not registered after queue replacement",
                         "explicit_ref_registration")
        raise Reject("unavailable_reference",
                     "proposed path has no destination fallback; unregistered ref",
                     "no_destination_fallback")

    def op_export(self, event):
        name = event["name"]
        buf = self.buffers.get(name)
        if buf is None or not buf.decoded_ok:
            raise FixtureError(f"export of undecoded buffer {name!r}")
        buf.exported = True
        # Pixel backing survives wrapper destruction (preserve_capture).
        if "backing_bytes" in event:
            buf.backing_bytes = event["backing_bytes"]

    def op_register(self, event):
        if self.path != "proposed":
            raise Reject("stock_has_no_registration",
                         "stock AVD has no imported-reference registration control",
                         "explicit_ref_registration")
        name = event["name"]
        buf = self.buffers.get(name)
        if buf is None or not buf.exported:
            raise Reject("orphaned_retained_buffer",
                         "registration requires an exported backing",
                         "explicit_ref_registration")
        if not buf.decoded_ok:
            raise Reject("unavailable_reference",
                         "registration requires a successful original decode",
                         "explicit_ref_registration")
        if buf.queued_as_dst:
            raise Reject("reference_queued_as_destination",
                         "registration cannot silently remove a live destination slot",
                         "ref_not_queued_as_dst")
        era = self.eras[buf.era_id]
        if buf.backing_bytes < era.sizeimage:
            raise Reject("short_backing",
                         "registered backing is shorter than its era sizeimage",
                         "era_sizing_dst_vs_ref")
        ts = event.get("timestamp", self.next_reg_ts)
        self.next_reg_ts = max(self.next_reg_ts, ts) + 1
        key = (self.capture_generation, ts)
        if key in self.ts_index:
            raise Reject("duplicate_timestamp",
                         "registration timestamp already used in this generation",
                         "generation_scoped_timestamps")
        idx = event.get("index")
        if idx is not None and idx in self.slot:
            raise Reject("reference_queued_as_destination",
                         "registration index is already a destination slot",
                         "ref_not_queued_as_dst")
        self.ts_index[key] = name
        buf.timestamp = ts
        buf.queued_as_dst = False
        self.registrations[name] = {
            "generation": self.capture_generation,
            "timestamp": ts,
            "era_id": buf.era_id,
            "index": idx,
        }

    def op_submit(self, event):
        # Alias of decode for fixtures that want an explicit submission step.
        self.op_decode(event)

    def op_proposed_reconfigure(self, event):
        if self.path != "proposed":
            raise Reject("stock_has_no_reconfigure",
                         "stock S_FMT cannot reconfigure a live OUTPUT stream",
                         "output_s_fmt_streaming")
        if not self.output_streaming:
            raise Reject("state_loss",
                         "proposed reconfigure requires OUTPUT to stay streaming",
                         "stop_on_output_streamoff")
        if self.capture_streaming or self._capture_busy():
            raise Reject("busy_capture_s_fmt",
                         "reconfigure requires CAPTURE STREAMOFF and REQBUFS(0)",
                         "capture_s_fmt_busy")
        w, h = event["width"], event["height"]
        depth = event.get("bit_depth", self.bit_depth)
        if depth != self.bit_depth:
            raise Reject("mixed_depth",
                         "do not transfer state across a profile/depth change",
                         "image_fmt_busy")
        # Formats and scratch bounds update; durable entropy is kept.
        self.coded_w, self.coded_h = w, h
        self.current_era = self._need_era(w, h, depth)
        self.scratch_w, self.scratch_h = w, h
        self.scratch_depth = depth
        self.scratch_present = True
        self.probabilities = True
        self.last_present = True
        # Segmentation-map interpretation on a changed grid is experiment B.
        self.seg_policy = "unknown"

    def op_inject_failure(self, event):
        phase = event.get("phase", "after_destructive")
        if phase == "preflight":
            # Error before destructive queue changes: old session remains usable.
            return
        if phase != "after_destructive":
            raise FixtureError(f"unknown inject_failure phase {phase!r}")
        if not self.destructive_done:
            raise FixtureError("after_destructive inject requires REQBUFS(0) first")
        self.failed = True

    def op_ask_firmware(self, event):
        which = event.get("question", "firmware_live_resize")
        if which not in INVARIANTS or INVARIANTS[which]["kind"] != "firmware_unknown":
            raise FixtureError(f"{which} is not a firmware_unknown invariant")
        raise Reject("firmware_unknown",
                     INVARIANTS[which]["text"],
                     which)

    def op_snapshot(self, event):
        return


def load_source_map():
    return SOURCE_MAP


def run_events(path, events, session_id="s1", profile=0, bit_depth=8):
    for event in events:
        validate_event(event)
    session = Session(path, session_id, profile, bit_depth)
    for i, event in enumerate(events):
        try:
            session.apply(event)
        except Reject as exc:
            return {
                "status": "unknown" if exc.code == "firmware_unknown" else "reject",
                "code": exc.code,
                "message": exc.message,
                "kind": exc.kind,
                "invariant": exc.invariant,
                "at_event": i,
                "snapshot": session.snapshot(),
                "decoded_frame_evidence": False,
            }
    snap = session.snapshot()
    return {
        "status": "model_accept" if path == "proposed" else "observe",
        "code": None,
        "message": "sequence completed in the model",
        "kind": "proposed_contract" if path == "proposed" else "source_observed",
        "invariant": None,
        "at_event": None,
        "snapshot": snap,
        "decoded_frame_evidence": False,
    }


def run_fixture(doc):
    if not isinstance(doc, dict):
        raise FixtureError("fixture must be a JSON object")
    if doc.get("schema") != SCHEMA:
        raise FixtureError("missing or incompatible schema")
    for field in ("id", "path", "classification", "expect", "events"):
        if field not in doc:
            raise FixtureError(f"fixture missing {field}")
    if doc["path"] not in ("stock", "proposed"):
        raise FixtureError("path must be stock or proposed")
    if doc["classification"] not in ("legal_stream", "adversarial_api",
                                     "firmware_unknown"):
        raise FixtureError("classification must be legal_stream, adversarial_api "
                           "or firmware_unknown")
    events = doc["events"]
    if not isinstance(events, list) or not events:
        raise FixtureError("events must be a non-empty list")
    expect = doc["expect"]
    if not isinstance(expect, dict) or "status" not in expect:
        raise FixtureError("expect.status is required")
    if expect["status"] not in ("observe", "model_accept", "reject", "unknown"):
        raise FixtureError("invalid expected status")
    if expect["status"] in ("reject", "unknown") and not isinstance(expect.get("code"), str):
        raise FixtureError("reject/unknown fixtures must name the expected code")
    profile = doc.get("profile", 0)
    bit_depth = doc.get("bit_depth", 8 if profile == 0 else 10)
    result = run_events(doc["path"], events, doc.get("session", "s1"),
                        profile, bit_depth)
    result["id"] = doc["id"]
    result["classification"] = doc["classification"]
    result["evidence_class"] = "model_not_decoded_frames"
    _check_expect(expect, result, doc)
    result["ok"] = True
    return result


def _check_expect(expect, result, doc):
    want = expect["status"]
    if result["status"] != want:
        raise FixtureError(
            f"{doc['id']}: expected status {want!r}, got {result['status']!r}"
            f" code={result.get('code')!r} {result.get('message')}")
    if "code" in expect and result.get("code") != expect["code"]:
        raise FixtureError(
            f"{doc['id']}: expected code {expect['code']!r}, got {result.get('code')!r}")
    if "lost" in expect:
        lost = result["snapshot"]["lost"]
        missing = [item for item in expect["lost"] if item not in lost]
        if missing:
            raise FixtureError(
                f"{doc['id']}: expected lost {expect['lost']}, snapshot {lost}")
    if result["decoded_frame_evidence"]:
        raise FixtureError(f"{doc['id']}: model must not claim decoded-frame evidence")
    if want == "model_accept" and doc["path"] != "proposed":
        raise FixtureError("model_accept is only valid on the proposed path")
    if want == "model_accept" and result["kind"] != "proposed_contract":
        raise FixtureError("model_accept must stay labeled proposed_contract")
