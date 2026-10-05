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


def parse_h265_pps_id(nal: bytes) -> int | None:
    """pps_pic_parameter_set_id: first ue(v) after the 2-byte NAL header."""
    try:
        v = BitReader(unescape(nal[2:])).ue()
        return v if v <= 63 else None
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


# ---- parameter-set syntax validation -----------------------------------------------------------
# Random or fake bytes behind a plausible NAL header must not start a clip. These checks follow the
# H.264 / H.265 SPS/PPS/VPS syntax orders and range limits (profile/level tables, id ranges,
# picture size limits). They validate syntax up to the point a fixed-layout parse is practical
# (stopping before VUI), not full conformance. Source for the syntax order: the standards' syntax
# tables as implemented in FFmpeg's h264_ps.c / hevc ps parsers; the ITU texts were not available.

H264_PROFILES = {66, 77, 88, 100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}
H264_LEVELS = {9, 10, 11, 12, 13, 20, 21, 22, 30, 31, 32, 40, 41, 42, 50, 51, 52, 60, 61, 62}
H265_LEVELS = {30, 60, 63, 90, 93, 120, 123, 150, 153, 156, 180, 183, 186}


def validate_h264_sps(nal: bytes) -> H264Sps | None:
    """Strict SPS check (nal includes the header byte). Returns the parsed SPS or None."""
    try:
        r = BitReader(unescape(nal[1:]))
        profile = r.u(8)
        cons = r.u(8)
        level = r.u(8)
        if profile not in H264_PROFILES or cons & 0x03 or level not in H264_LEVELS:
            return None
        sps_id = r.ue()
        sep = False
        if profile in _HIGH_PROFILES:
            chroma = r.ue()
            if chroma > 3:
                return None
            if chroma == 3:
                sep = bool(r.u(1))
            if r.ue() > 6 or r.ue() > 6:
                return None
            r.u(1)
            if r.u(1):
                for i in range(12 if chroma == 3 else 8):
                    if r.u(1):
                        _skip_scaling_list(r, 16 if i < 6 else 64)
        log2_fn = r.ue() + 4
        poc_type = r.ue()
        if poc_type > 2 or sps_id > 31 or log2_fn > 16:
            return None
        if poc_type == 0:
            if r.ue() > 12:
                return None
        elif poc_type == 1:
            r.u(1)
            r.se()
            r.se()
            n = r.ue()
            if n > 255:
                return None
            for _ in range(n):
                r.se()
        if r.ue() > 16:  # max_num_ref_frames
            return None
        r.u(1)  # gaps_in_frame_num_value_allowed_flag
        w, h = r.ue() + 1, r.ue() + 1
        if not (1 <= w <= 1024 and 1 <= h <= 1024):
            return None
        if not r.u(1):  # frame_mbs_only_flag == 0
            r.u(1)
        r.u(1)  # direct_8x8_inference_flag
        if r.u(1):  # frame_cropping_flag
            for _ in range(4):
                if r.ue() > 8192:
                    return None
        return H264Sps(profile, sps_id, log2_fn, sep)
    except BitError:
        return None


def validate_h264_pps(nal: bytes, sps_ids: set[int]) -> int | None:
    """Strict PPS check; returns pps_id when valid and referencing one of `sps_ids`."""
    try:
        r = BitReader(unescape(nal[1:]))
        pps_id, sps_id = r.ue(), r.ue()
        if pps_id > 255 or sps_id not in sps_ids:
            return None
        r.u(2)  # entropy_coding_mode_flag, bottom_field_pic_order_in_frame_present_flag
        if r.ue() > 7:  # num_slice_groups_minus1
            return None
        if r.ue() > 31 or r.ue() > 31:
            return None
        r.u(1)
        if r.u(2) > 2:  # weighted_bipred_idc
            return None
        if not -26 <= r.se() <= 25:  # pic_init_qp_minus26 (8-bit video)
            return None
        r.se()
        if not -12 <= r.se() <= 12:  # chroma_qp_index_offset
            return None
        return pps_id
    except BitError:
        return None


def _h265_ptl_ok(r: BitReader) -> bool:
    if r.u(2) != 0:  # general_profile_space
        return False
    r.u(1)
    if not 1 <= r.u(5) <= 11:  # general_profile_idc
        return False
    r.u(32)
    r.u(4)
    r.u(44)
    return r.u(8) in H265_LEVELS


def validate_h265_vps(nal: bytes) -> int | None:
    try:
        r = BitReader(unescape(nal[2:]))
        vps_id = r.u(4)
        r.u(2)
        r.u(6)
        if r.u(3) > 6:
            return None
        r.u(1)
        return vps_id if r.u(16) == 0xFFFF else None  # vps_reserved_0xffff_16bits
    except BitError:
        return None


def validate_h265_sps(nal: bytes, vps_ids: set[int]) -> int | None:
    try:
        r = BitReader(unescape(nal[2:]))
        vps_id = r.u(4)
        sub = r.u(3)
        r.u(1)
        if vps_id not in vps_ids or sub > 6 or not _h265_ptl_ok(r):
            return None
        if sub == 0:  # sub-layer flags only follow when max_sub_layers_minus1 > 0
            sps_id = r.ue()
            chroma = r.ue()
            if sps_id > 15 or chroma > 3:
                return None
            if chroma == 3:
                r.u(1)
            w, h = r.ue(), r.ue()
            if not (8 <= w <= 16384 and 8 <= h <= 16384):
                return None
            return sps_id
        return -1  # accepted without further checks (sub-layer syntax not parsed)
    except BitError:
        return None


def validate_h265_pps(nal: bytes, sps_ids: set[int]) -> int | None:
    try:
        r = BitReader(unescape(nal[2:]))
        pps_id, sps_id = r.ue(), r.ue()
        if pps_id > 63 or (sps_id not in sps_ids and -1 not in sps_ids) or sps_id > 15:
            return None
        r.u(1)
        r.u(1)
        r.u(3)
        r.u(1)
        r.u(1)
        if r.ue() > 14 or r.ue() > 14:
            return None
        if not -38 <= r.se() <= 25:
            return None
        r.u(3)  # constrained_intra_pred, transform_skip, cu_qp_delta_enabled
        return pps_id
    except BitError:
        return None
