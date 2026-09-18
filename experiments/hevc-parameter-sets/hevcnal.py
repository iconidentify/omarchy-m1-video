"""Minimal H.265 Annex B helpers for building synthetic parameter-set fixtures.

Only the fields the fixtures rewrite are understood: the VPS id, the SPS's VPS
reference and SPS id, and the PPS's SPS reference. Slice headers are never
rewritten, so every fixture keeps PPS id 0 as produced by the encoder.
"""

HEVC_NAL_VPS = 32
HEVC_NAL_SPS = 33
HEVC_NAL_PPS = 34

START_CODE = b"\x00\x00\x00\x01"


def split_annexb(data):
    """Return the NAL units (without start codes) of an Annex B byte stream."""
    nals = []
    i = 0
    n = len(data)
    start = None
    while i + 2 < n:
        if data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 1:
            if start is not None:
                nals.append(data[start:i].rstrip(b"\x00"))
            i += 3
            start = i
        else:
            i += 1
    if start is not None:
        nals.append(data[start:].rstrip(b"\x00") if start < n else b"")
    return [nal for nal in nals if nal]


def join_annexb(nals):
    return b"".join(START_CODE + bytes(nal) for nal in nals)


def nal_type(nal):
    return (nal[0] >> 1) & 0x3F


def unescape(ebsp):
    out = bytearray()
    zeros = 0
    for b in ebsp:
        if zeros >= 2 and b == 3:
            zeros = 0
            continue
        out.append(b)
        zeros = zeros + 1 if b == 0 else 0
    return bytes(out)


def escape(rbsp):
    out = bytearray()
    zeros = 0
    for b in rbsp:
        if zeros >= 2 and b <= 3:
            out.append(3)
            zeros = 0
        out.append(b)
        zeros = zeros + 1 if b == 0 else 0
    return bytes(out)


class Bits:
    """A list of bits taken from an RBSP payload up to its rbsp_stop_one_bit."""

    def __init__(self, rbsp):
        bits = []
        for b in rbsp:
            bits.extend((b >> (7 - k)) & 1 for k in range(8))
        while bits and bits[-1] == 0:
            bits.pop()
        if not bits:
            raise ValueError("RBSP has no stop bit")
        bits.pop()
        self.bits = bits
        self.pos = 0

    def u(self, n):
        if self.pos + n > len(self.bits):
            raise ValueError("read past end of RBSP")
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bits[self.pos]
            self.pos += 1
        return v

    def ue(self):
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
            if zeros > 31:
                raise ValueError("invalid Exp-Golomb code")
        return (1 << zeros) - 1 + self.u(zeros)

    def replace(self, start, end, new_bits):
        self.bits[start:end] = new_bits
        self.pos = start + len(new_bits)

    def to_rbsp(self):
        bits = self.bits + [1]
        bits += [0] * (-len(bits) % 8)
        return bytes(
            int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)
        )


def ue_bits(value):
    if value < 0:
        raise ValueError("Exp-Golomb value must be non-negative")
    code = value + 1
    width = code.bit_length()
    return [0] * (width - 1) + [(code >> (width - 1 - k)) & 1 for k in range(width)]


def u_bits(value, n):
    if n < 0 or not 0 <= value < (1 << n):
        raise ValueError(f"{value} does not fit in {n} bits")
    return [(value >> (n - 1 - k)) & 1 for k in range(n)]


def _payload(nal):
    return Bits(unescape(nal[2:]))


def _rebuild(nal, bits):
    return nal[:2] + escape(bits.to_rbsp())


def _skip_ptl(bits, max_sub_layers):
    bits.u(96)  # general profile/tier (88 bits) and general_level_idc
    present = []
    for _ in range(max_sub_layers - 1):
        present.append((bits.u(1), bits.u(1)))
    if max_sub_layers > 1:
        bits.u(2 * (8 - (max_sub_layers - 1)))
    for profile, level in present:
        if profile:
            bits.u(88)
        if level:
            bits.u(8)


def vps_ids(nal):
    return {"vps_id": _payload(nal).u(4)}


def sps_ids(nal):
    bits = _payload(nal)
    vps_id = bits.u(4)
    max_sub_layers = bits.u(3) + 1
    if max_sub_layers > 7:
        raise ValueError("multi-layer SPS extension is not supported")
    bits.u(1)
    _skip_ptl(bits, max_sub_layers)
    return {"vps_id": vps_id, "sps_id": bits.ue()}


def pps_ids(nal):
    bits = _payload(nal)
    return {"pps_id": bits.ue(), "sps_id": bits.ue()}


def set_vps_id(nal, vps_id):
    assert nal_type(nal) == HEVC_NAL_VPS
    bits = _payload(nal)
    bits.replace(0, 4, u_bits(vps_id, 4))
    return _rebuild(nal, bits)


def set_sps_ids(nal, vps_id=None, sps_id=None):
    assert nal_type(nal) == HEVC_NAL_SPS
    bits = _payload(nal)
    old_vps = bits.u(4)
    bits.replace(0, 4, u_bits(old_vps if vps_id is None else vps_id, 4))
    max_sub_layers = bits.u(3) + 1
    if max_sub_layers > 7:
        raise ValueError("multi-layer SPS extension is not supported")
    bits.u(1)
    _skip_ptl(bits, max_sub_layers)
    start = bits.pos
    bits.ue()
    if sps_id is not None:
        bits.replace(start, bits.pos, ue_bits(sps_id))
    return _rebuild(nal, bits)


def set_pps_id(nal, pps_id):
    """Rewrite pps_pic_parameter_set_id. Slices still refer to the old id."""
    assert nal_type(nal) == HEVC_NAL_PPS
    bits = _payload(nal)
    bits.ue()
    bits.replace(0, bits.pos, ue_bits(pps_id))
    return _rebuild(nal, bits)


def set_pps_sps_id(nal, sps_id):
    assert nal_type(nal) == HEVC_NAL_PPS
    bits = _payload(nal)
    bits.ue()
    start = bits.pos
    bits.ue()
    bits.replace(start, bits.pos, ue_bits(sps_id))
    return _rebuild(nal, bits)


def set_sps_chroma_format_idc(nal, value):
    """Rewrite chroma_format_idc; 4 and above are invalid and make the SPS fail."""
    assert nal_type(nal) == HEVC_NAL_SPS
    bits = _payload(nal)
    bits.u(4)
    max_sub_layers = bits.u(3) + 1
    if max_sub_layers > 7:
        raise ValueError("multi-layer SPS extension is not supported")
    bits.u(1)
    _skip_ptl(bits, max_sub_layers)
    bits.ue()
    start = bits.pos
    bits.ue()
    bits.replace(start, bits.pos, ue_bits(value))
    return _rebuild(nal, bits)


def set_pps_num_ref_idx_l0_minus1(nal, value):
    """Rewrite num_ref_idx_l0_default_active_minus1; 15 is invalid in FFmpeg."""
    assert nal_type(nal) == HEVC_NAL_PPS
    bits = _payload(nal)
    bits.ue()
    bits.ue()
    bits.u(7)  # dependent slices, output flag, extra header bits, sign hiding, cabac init
    start = bits.pos
    bits.ue()
    bits.replace(start, bits.pos, ue_bits(value))
    return _rebuild(nal, bits)


def drop_payload_bits(nal, count):
    """Remove the last count payload bits before rbsp_stop_one_bit."""
    bits = _payload(nal)
    if count > len(bits.bits):
        raise ValueError("payload is shorter than the bits to drop")
    del bits.bits[len(bits.bits) - count:]
    return _rebuild(nal, bits)


def set_sps_empty_extensions(nal):
    """Turn a final sps_extension_present_flag 0 into 1 with every extension flag
    and sps_extension_4bits zero, which parses to the same SPS."""
    assert nal_type(nal) == HEVC_NAL_SPS
    bits = _payload(nal)
    if bits.bits[-1] != 0:
        raise ValueError("SPS does not end with sps_extension_present_flag 0")
    bits.bits[-1:] = [1] + [0] * 8
    return _rebuild(nal, bits)


def pad_payload(nal, count):
    """Append count filler bytes (0xAA) of payload before rbsp_stop_one_bit.

    SPS and PPS parsing ignores bits after the extension flags, so this only
    makes the NAL larger."""
    bits = _payload(nal)
    for _ in range(count):
        bits.bits.extend((1, 0, 1, 0, 1, 0, 1, 0))
    return _rebuild(nal, bits)


def truncate_rbsp(nal, keep_bytes):
    """Keep the header and the first keep_bytes RBSP bytes, then add a stop bit."""
    rbsp = unescape(nal[2:])[:keep_bytes] + b"\x80"
    return nal[:2] + escape(rbsp)
