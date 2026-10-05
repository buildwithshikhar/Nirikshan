"""Bit-level helpers: emulation-prevention removal, Exp-Golomb, H.264 SPS/slice-header parsing.

Only the few fields the carver needs are parsed (frame_num width, slice sanity). Everything is
wrapped so truncated/garbage input yields None, never an exception.
"""

from dataclasses import dataclass


class BitError(ValueError):
    pass


def unescape(data: bytes) -> bytes:
    """Drop emulation-prevention bytes (00 00 03 -> 00 00)."""
    return data.replace(b"\x00\x00\x03", b"\x00\x00")


class BitReader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def u(self, n: int) -> int:
        if self.pos + n > len(self.data) * 8:
            raise BitError("out of bits")
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.data[self.pos >> 3] >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def ue(self) -> int:
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
            if zeros > 32:
                raise BitError("bad exp-golomb")
        return (1 << zeros) - 1 + (self.u(zeros) if zeros else 0)

    def se(self) -> int:
        k = self.ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)


@dataclass(frozen=True)
class H264Sps:
    profile_idc: int
    sps_id: int
    log2_max_frame_num: int
    separate_colour_plane: bool


_HIGH_PROFILES = {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}


def _skip_scaling_list(r: BitReader, size: int) -> None:
    last = nxt = 8
    for _ in range(size):
        if nxt != 0:
            nxt = (last + r.se() + 256) % 256
        last = last if nxt == 0 else nxt


def parse_h264_sps(nal: bytes) -> H264Sps | None:
    """nal includes the 1-byte NAL header."""
    try:
        r = BitReader(unescape(nal[1:]))
        profile = r.u(8)
        r.u(16)  # constraint flags + level_idc
        sps_id = r.ue()
        sep = False
        if profile in _HIGH_PROFILES:
            chroma = r.ue()
            if chroma == 3:
                sep = bool(r.u(1))
            r.ue()
            r.ue()
            r.u(1)
            if r.u(1):  # seq_scaling_matrix_present_flag
                for i in range(12 if chroma == 3 else 8):
                    if r.u(1):
                        _skip_scaling_list(r, 16 if i < 6 else 64)
        log2_fn = r.ue() + 4
        if sps_id > 31 or log2_fn > 16:
            return None
        return H264Sps(profile, sps_id, log2_fn, sep)
    except BitError:
        return None


def parse_h264_pps_id(nal: bytes) -> int | None:
    try:
        v = BitReader(unescape(nal[1:])).ue()
        return v if v <= 255 else None
    except BitError:
        return None


@dataclass(frozen=True)
class H264Slice:
    first_mb: int
    slice_type: int
    pps_id: int
    frame_num: int | None  # None when the SPS is unknown


def parse_h264_slice(head: bytes, sps: H264Sps | None) -> H264Slice | None:
    """Parse the leading slice-header fields. head starts at the NAL header byte."""
    try:
        r = BitReader(unescape(head[1:]))
        first_mb, slice_type, pps_id = r.ue(), r.ue(), r.ue()
        if first_mb > 139264 or slice_type > 9 or pps_id > 255:
            return None
        fn = None
        if sps is not None:
            if sps.separate_colour_plane:
                r.u(2)
            fn = r.u(sps.log2_max_frame_num)
        return H264Slice(first_mb, slice_type, pps_id, fn)
    except BitError:
        # head is only 16 bytes; a short SPS-dependent tail is fine, the leading fields are not
        try:
            r = BitReader(unescape(head[1:]))
            first_mb, slice_type, pps_id = r.ue(), r.ue(), r.ue()
            if first_mb > 139264 or slice_type > 9 or pps_id > 255:
                return None
            return H264Slice(first_mb, slice_type, pps_id, None)
        except BitError:
            return None


def parse_h265_slice_pps_id(head: bytes, nal_type: int) -> int | None:
    """first_slice_segment_in_pic_flag, [no_output_of_prior_pics_flag if IRAP], pps_id ue(v)."""
    try:
        r = BitReader(unescape(head[2:]))
        r.u(1)
        if 16 <= nal_type <= 23:
            r.u(1)
        v = r.ue()
        return v if v <= 63 else None
    except BitError:
        return None
