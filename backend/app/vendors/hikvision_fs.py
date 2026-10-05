"""Hikvision file-system structured parser (P4, Tier B). Per-paper, NOT validated on a real image.

Byte-level source of truth: docs/parsers/hikvision-fields.md (cited below as "fields s<N>"), which
quotes Han/Jeong/Lee 2015 [H] (one 2015 DS-7204HVI-SV, 160 GB) and Dragonas 2023 [D] (six devices)
with confidence tags. Only facts that document marks documented / partly documented are parsed;
everything the document marks unknown is tagged `unknown` and never interpreted.

What is parsed (fields s1-s4): Master Sector, backup Master Sector (searched, offset undocumented),
RATS system-log records (bounded sample + summary), HIKBTREE header / page list / footer / data
block entries, and the 'OFNI' IDR-table record signatures (count only). Video: HIKBTREE entries plus
the Master Sector block geometry locate the blocks; the generic Annex-B carver is run inside each
block range because [H] documents raw H.264 NAL units there (fields s5). The IDR-table record layout
(56 B) is only partly documented, so no index/channel/timestamp of an IDR record is read.

Open conflicts are exposed, never silently resolved:
  * data-block size 0x400000 (text) vs 1 GiB (text + Fig.2 bytes): fields s7, option block_size_mode
    and the always-emitted ParsedField `block_size_conflict_in_source`.
  * timestamp basis (Han: UTC for init/HIKBTREE; Dragonas: log times local): fields s6. Raw epoch
    values are returned with tz_basis "not assumed"; option time_basis_label only changes the label.
  * Master Sector base 0x200 (Han) vs 0x210 (Dragonas): fields s1, option master_sector_offset.

No checksum or CRC is documented for any of these structures; none is verified or claimed.
H.265 framing is undocumented for Hikvision: H.265 found by the carver is reported as an orphan.
"""

import re
import struct
from dataclasses import replace
from datetime import datetime, timedelta

from app.carving import nal
from app.carving.carve import CarveParams, Carver
from app.vendors.hikvision import MASTER, HikvisionParser
from app.vendors.parse import (
    ParsedClip,
    ParsedField,
    ParsedOrphan,
    ParseResult,
    RawTimestamp,
    fallback,
)

S = "docs/parsers/hikvision-fields.md"
BLOCK_SIZE_TEXT = 0x400000  # [H] p.191 text (fields s7 passage A)
BLOCK_SIZE_GIB = 0x40000000  # [H] p.192 text and Fig.2 bytes (fields s7 passage B)
PAGE_SIZE = 4096  # [H] p.194: "Page size: 4 KB" (fields s4.2)
ENTRY_STRIDE = 48  # fields s4.4: drawn as 48 bytes in Fig.6; never stated in the text
IDR_REC = 56  # fields s3: "fixed to 56 bytes for each record"
IDR_SIG = b"OFNI"
RATS_RE = re.compile(rb"RATS(?:\x01\x00\x00\x00|\x14\x00\x00\x00)")  # fields s2 header variants
SENTINEL = (0x7FFFFFFF, 0)  # FF FF FF 7F 00 00 00 00 as two LE u32 (fields s4.4)
MAX_IDR_SCAN = 4 * 1024 * 1024

# Major/minor names: Dragonas Appendix B (fields s2), single lab set; bytes in file order.
LOG_NAMES = {
    (3, 0x41): "Power On",
    (3, 0x42): "Local: Shutdown",
    (3, 0x43): "Local: Abnormal Shutdown",
    (3, 0x50): "Local: Login",
    (3, 0x51): "Local: Logout",
    (3, 0x52): "Local: Configure Parameters",
    (3, 0x5C): "Local: Initialize HDD",
    (3, 0x6E): "HDD Detect",
    (3, 0x70): "Remote: Login",
    (3, 0x71): "Remote: Logout",
    (3, 0x76): "Remote: Get Parameters",
    (3, 0x77): "Remote: Configure Parameters",
    (3, 0x78): "Remote: Get Working Status",
    (3, 0x79): "Remote: Alarm Arming",
    (3, 0x7A): "Remote: Alarm Disarming",
    (3, 0x80): "Remote: Playback by Time",
    (3, 0x82): "Remote: Initialize HDD",
    (3, 0x86): "Remote: Export Config File",
    (4, 0xA0): "Time Sync.",
    (4, 0xA1): "HDD Information",
    (4, 0xA2): "S.M.A.R.T. Information",
    (4, 0xA3): "Start Record",
    (4, 0xA4): "Stop Record",
    (4, 0xAA): "System Running State",
    (1, 0x03): "Start Motion Detection",
    (1, 0x04): "Stop Motion Detection",
    (1, 0x05): "Start Video Tampering",
    (1, 0x06): "Stop Video Tampering",
    (2, 0x22): "Illegal Login",
    (2, 0x24): "HDD Error",
    (2, 0x27): "Network Disconnected",
    (2, 0x54): "Hik-Connect Offline Exception",
}
MAJOR_NAMES = {1: "Alarm", 2: "Exception", 3: "Operation", 4: "Information"}  # [H] Table 1

OPTIONS = {
    "master_sector_offset": {
        "default": "auto",
        "doc": "auto | 0x200 | 0x210. Where the HIKVISION@HANGZHOU signature is expected "
        "(Han 0x200, Dragonas 0x210). auto tries 0x210, 0x200, then a search of 0x200-0x2FF.",
    },
    "block_size_mode": {
        "default": "field",
        "doc": "field | 0x400000 | 1gib. Data-block size used for geometry. field = value read "
        "from the Master Sector. The source conflict is always flagged.",
    },
    "time_basis_label": {
        "default": "unspecified",
        "doc": "unspecified | utc | local. Annotates RawTimestamp.tz_basis only; no conversion.",
    },
    "btree_first_entry_offset": {
        "default": "auto",
        "doc": "auto | integer. Offset of the first 48-byte entry in a 4 KB page (undocumented)."
        " auto picks the 8-byte-aligned offset in 0..0x40 giving the most plausible entries.",
    },
    "max_log_records": {"default": 200_000, "doc": "Cap on RATS records scanned."},
    "max_log_scan_bytes": {"default": 64 * 1024 * 1024, "doc": "Cap on log-area bytes scanned."},
    "log_sample_size": {"default": 10, "doc": "RATS records returned in the sample."},
    "max_btree_entries": {"default": 50_000, "doc": "Cap on HIKBTREE entries decoded."},
    "max_pages": {"default": 1024, "doc": "Page-count above which a HIKBTREE is rejected."},
    "max_blocks_scanned": {"default": 4096, "doc": "Cap on data blocks scanned for video."},
}


def wall(raw: int) -> str:
    """Plain decode of a stored Unix-seconds integer. NOT a timezone claim."""
    try:
        return (datetime(1970, 1, 1) + timedelta(seconds=raw)).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, ValueError):
        return ""


class _Win:
    """File-like view of f[base : base+length] so nal.scan can be restricted to one block."""

    def __init__(self, f, base: int, length: int):
        self.f, self.base, self.len, self.p = f, base, length, 0

    def seek(self, p: int, whence: int = 0) -> int:
        self.p = p
        return p

    def read(self, n: int = -1) -> bytes:
        n = self.len - self.p if n < 0 else min(n, self.len - self.p)
        if n <= 0:
            return b""
        self.f.seek(self.base + self.p)
        d = self.f.read(n)
        self.p += len(d)
        return d


def _shift(events, base: int):
    for ev in events:
        if isinstance(ev, nal.StartCode):
            yield replace(
                ev, run_start=ev.run_start + base, sc_start=ev.sc_start + base, hdr=ev.hdr + base
            )
        elif isinstance(ev, nal.ZeroRun):
            yield replace(ev, pos=ev.pos + base)
        else:
            yield nal.Eof(ev.size + base)


def _num(v, default):
    """Option value as int (accepts ints and '0x..' strings) or default."""
    try:
        return int(v, 0) if isinstance(v, str) else int(v)
    except (TypeError, ValueError):
        return default


def _u64(b: bytes, o: int) -> int:
    return struct.unpack_from("<Q", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


class HikvisionFsParser(HikvisionParser):
    options_schema = OPTIONS

    def parse(self, f, size, options=None):
        opts = {k: v["default"] for k, v in OPTIONS.items()} | (options or {})
        try:
            return _Run(self, f, size, opts).run()
        except Exception as exc:  # never raise: generic carving stands
            return fallback(
                self.vendor,
                self.vendor,
                self.tier,
                opts,
                f"parser error ({type(exc).__name__}: {exc}); generic carving stands",
            )


class _Run:
    def __init__(self, parser, f, size: int, opts: dict):
        self.p, self.f, self.size, self.opts = parser, f, size, opts
        self.fields: list[ParsedField] = []
        self.warnings: list[str] = []
        self.incons: list[str] = []
        self.stamps: list[RawTimestamp] = []
        self.stats: dict = {}
        self.clips: list[ParsedClip] = []
        self.orphans: list[ParsedOrphan] = []
        self.norm_options()

    # ---- helpers --------------------------------------------------------------------------
    def rd(self, off: int, n: int) -> bytes:
        if off < 0 or n <= 0 or off >= self.size:
            return b""
        self.f.seek(off)
        return self.f.read(min(n, self.size - off))

    def add(self, name, value, status, source="", note=""):
        self.fields.append(ParsedField(name, value, status, source, note))

    def bad(self, msg: str) -> None:
        if msg not in self.incons and len(self.incons) < 200:
            self.incons.append(msg)

    def tz(self) -> str:
        t = self.opts["time_basis_label"]
        if t == "unspecified":
            return "not assumed"
        return f"labelled '{t}' by examiner option time_basis_label (no conversion applied)"

    def stamp(self, name, off, raw, fmt, note="") -> RawTimestamp:
        return RawTimestamp(name, off, raw, fmt, wall(raw), self.tz(), note)

    def norm_options(self) -> None:
        o = self.opts

        def choice(key, allowed, default):
            if o[key] not in allowed:
                self.warnings.append(f"option {key}={o[key]!r} invalid; using {default!r}")
                o[key] = default

        ms = o["master_sector_offset"]
        if ms != "auto":
            ms = _num(ms, None)
        if ms not in ("auto", 0x200, 0x210):
            self.warnings.append(
                f"option master_sector_offset={o['master_sector_offset']!r} invalid; using 'auto'"
            )
            ms = "auto"
        o["master_sector_offset"] = ms
        choice("block_size_mode", ("field", "0x400000", "1gib"), "field")
        choice("time_basis_label", ("unspecified", "utc", "local"), "unspecified")
        fe = o["btree_first_entry_offset"]
        if fe != "auto":
            fe = _num(fe, None)
            if fe is None or not 0 <= fe < PAGE_SIZE - ENTRY_STRIDE:
                self.warnings.append("option btree_first_entry_offset invalid; using 'auto'")
                fe = "auto"
        o["btree_first_entry_offset"] = fe
        for k in (
            "max_log_records",
            "max_log_scan_bytes",
            "log_sample_size",
            "max_btree_entries",
            "max_pages",
            "max_blocks_scanned",
        ):
            v = _num(o[k], None)
            if v is None or v < 0:
                v = OPTIONS[k]["default"]
                self.warnings.append(f"option {k} invalid; using {v}")
            o[k] = v

    # ---- top level ------------------------------------------------------------------------
    def run(self) -> ParseResult:
        m = self.master()
        if m is None:
            return ParseResult(
                self.p.vendor,
                self.p.vendor,
                self.p.tier,
                "fallback",
                self.opts,
                warnings=self.warnings + ["no valid Master Sector found; generic carving stands"],
                inconsistencies=self.incons,
                stats=self.stats,
            )
        self.conflict_flags(m)
        self.backup_master(m)
        self.logs(m)
        entries = self.btree(m)
        self.video(m, entries)
        status = "parsed" if self.clips and not self.incons else "partial"
        if not self.clips:
            self.warnings.append(
                "no video clip emitted from HIKBTREE entries; generic carving stands"
            )
        return ParseResult(
            self.p.vendor,
            self.p.vendor,
            self.p.tier,
            status,
            self.opts,
            self.fields,
            self.clips,
            self.orphans,
            self.stamps[:12],
            self.warnings,
            self.incons,
            self.stats,
        )

    # ---- Master Sector (fields s1) --------------------------------------------------------
    def master(self) -> dict | None:
        want = self.opts["master_sector_offset"]
        cands = (0x210, 0x200) if want == "auto" else (want,)
        base = next((c for c in cands if self.rd(c, len(MASTER)) == MASTER), None)
        how = "documented offset"
        if base is None and want == "auto":
            i = self.rd(0x200, 0x100).find(MASTER)
            if i >= 0:
                base, how = 0x200 + i, "found by searching 0x200-0x2FF (fields s1 suggests search)"
                self.bad(f"Master Sector signature at unusual offset 0x{base:X}")
        if base is None:
            self.warnings.append(
                f"HIKVISION@HANGZHOU not found at {', '.join(hex(c) for c in cands)}"
            )
            return None
        other = [c for c in (0x200, 0x210) if c != base and self.rd(c, len(MASTER)) == MASTER]
        if other:
            self.bad(f"signature also present at 0x{other[0]:X}; ambiguous Master Sector base")
        raw = self.rd(base, 0x100)
        if len(raw) < 0xE4:
            self.warnings.append("Master Sector truncated by the end of the image")
            return None
        m = {
            "base": base,
            "capacity": _u64(raw, 0x38),
            "log_off": _u64(raw, 0x50),
            "log_size": _u64(raw, 0x58),
            "video_off": _u64(raw, 0x68),
            "block_size": _u64(raw, 0x78),
            "block_count": _u32(raw, 0x80),
            "hik1_off": _u64(raw, 0x88),
            "hik1_size": _u32(raw, 0x90),
            "hik2_off": _u64(raw, 0x98),
            "hik2_size": _u32(raw, 0xA0),
            "init": _u32(raw, 0xE0),
            "raw": raw,
        }
        h = "[H] p.190-191 + Fig.2"
        self.add(
            "master_sector_signature_offset",
            base,
            "parsed",
            f"{S} s1",
            f"{how}; Han says the sector starts at 0x200, Dragonas Fig.21 puts the signature at "
            "0x210; not settled without a real image",
        )
        self.add(
            "master_sector_pre_signature_bytes",
            f"{base - 0x200} bytes before the signature",
            "unknown",
            f"{S} s1",
            "Dragonas shows `86 21 00..` at 0x200; not explained; not interpreted",
        )
        ver = raw[0x20:0x30].rstrip(b"\x00").decode("ascii", "replace")
        self.add(
            "version_like_string",
            ver,
            "unknown",
            f"{S} s1",
            "text at +0x20 read, meaning not documented; not used",
        )
        for name, key, off, note in (
            ("capacity_bytes", "capacity", 0x38, "units inferred from 160 GB samples"),
            ("log_offset", "log_off", 0x50, ""),
            ("log_size", "log_size", 0x58, ""),
            ("video_area_offset", "video_off", 0x68, ""),
            ("block_size_field", "block_size", 0x78, "documented but self-contradictory (s7)"),
            ("block_count", "block_count", 0x80, "4-byte width from the figure box"),
            ("hikbtree1_offset", "hik1_off", 0x88, ""),
            ("hikbtree1_size", "hik1_size", 0x90, "4-byte width from the figure box"),
            ("hikbtree2_offset", "hik2_off", 0x98, ""),
            ("hikbtree2_size", "hik2_size", 0xA0, "4-byte width from the figure box"),
        ):
            self.add(name, m[key], "parsed", f"{h}; struct+0x{off:X}", note)
        self.add(
            "master_unlabelled_bytes",
            "+0x41, +0x48, +0x60, +0x70, +0xA4..+0xDF, +0xE4..",
            "unknown",
            f"{S} s1",
            "present in the sector; meaning undocumented; deliberately not read",
        )
        self.stamps.append(
            self.stamp(
                "master sector init time",
                base + 0xE0,
                m["init"],
                "unix seconds (u32 LE)",
                "Han p.191 calls it UTC; his text prints 0x37227754 in file-byte order, read here "
                "as little-endian per the figure (fields s1 caveat)",
            )
        )
        self.add(
            "init_time",
            m["init"],
            "parsed",
            f"{h}; struct+0xE0",
            "raw epoch seconds; timezone not assumed (s6)",
        )
        self.check_master(m)
        return m

    def check_master(self, m: dict) -> None:
        # fields "Corruption and consistency checks" 2-4
        cap = m["capacity"]
        if cap == 0:
            self.bad("Master Sector capacity is 0")
        elif cap < self.size:
            self.warnings.append(f"image ({self.size} B) is larger than the capacity field ({cap})")
        log_end = m["log_off"] + m["log_size"]
        if cap and log_end > cap:
            self.bad("log offset + size exceeds capacity")
        if m["video_off"] < log_end:
            self.bad("video-area offset lies before the end of the log area")
        if m["hik1_off"] < m["video_off"]:
            self.bad("HIKBTREE1 offset lies before the video area")
        if m["hik2_off"] < m["hik1_off"] + m["hik1_size"]:
            self.bad("HIKBTREE2 overlaps or precedes HIKBTREE1")
        if cap and m["hik2_off"] + m["hik2_size"] > cap:
            self.bad("HIKBTREE2 extends beyond capacity")
        for n, o in (
            ("log area", m["log_off"]),
            ("video area", m["video_off"]),
            ("HIKBTREE1", m["hik1_off"]),
            ("HIKBTREE2", m["hik2_off"]),
        ):
            if o >= self.size:
                self.bad(f"{n} offset 0x{o:X} lies beyond the image ({self.size} B)")
        span = max(0, m["hik1_off"] - m["video_off"])
        cand = {"field": m["block_size"], "0x400000": BLOCK_SIZE_TEXT, "1gib": BLOCK_SIZE_GIB}
        chk = {k: bool(v) and v * m["block_count"] <= span for k, v in cand.items()}
        self.add(
            "block_geometry_check",
            chk,
            "inferred",
            f"{S} corruption check 4",
            "block_count * size <= HIKBTREE1 - video offset, per candidate size; passing is not "
            "proof that it is the real size",
        )
        mode = self.opts["block_size_mode"]
        used = cand[mode]
        if mode == "field" and not 0 < used <= max(cap, self.size):
            self.bad(f"block size field {used} is zero or absurd; block geometry unusable")
            used = 0
        m["used"] = used
        if used and m["block_count"] and m["block_count"] * used > span:
            self.bad(
                f"block_count*block_size ({m['block_count']}*{used}) exceeds the span between the "
                "video area and HIKBTREE1 under the size in use"
            )

    def conflict_flags(self, m: dict) -> None:
        mode = self.opts["block_size_mode"]
        self.add(
            "block_size_conflict_in_source",
            "[H] text p.191: size of a data block (0x400000); [H] p.192: 'generally 1 GB "
            "(0x40000000 bytes)'; [H] Fig.2 bytes 00 00 00 40 00.. = 0x40000000. Value read from "
            f"this image: 0x{m['block_size']:X}. block_size_mode={mode}; size in use: "
            f"0x{m['used']:X}",
            "unknown",
            f"{S} s7",
            "open conflict, not resolved; field mode trusts this image's Master Sector value",
        )
        self.add("block_size_used", m["used"], "inferred", f"{S} s7", f"mode {mode}")
        self.add(
            "timestamp_basis_conflict_in_source",
            "[H] p.191/p.195: Master Sector init time and HIKBTREE entry times are 'UNIX time in "
            "UTC'; [D] p.66: RATS log times are 'stored in the local time zone ... not in UTC' "
            "(the same author's tool [A] comments the opposite). Different structures, never "
            "tested on one device.",
            "unknown",
            f"{S} s6",
            f"raw epoch values returned unconverted; label={self.opts['time_basis_label']!r}",
        )
        self.add(
            "time_basis_label",
            self.opts["time_basis_label"],
            "inferred",
            "examiner option",
            "annotation of tz_basis only; no conversion is performed",
        )
        self.add(
            "block_offset_base",
            "absolute disk offsets",
            "inferred",
            f"{S} s3/s4",
            "[H] does not state the base; sample entry offsets match absolute offsets",
        )
        self.add(
            "checksum",
            "none documented; none verified",
            "unknown",
            S,
            "no source documents a checksum/CRC for any Hikvision structure",
        )
        self.add("hevc_framing", "not parsed", "unknown", f"{S} s5", "H.265 framing undocumented")
        self.add(
            "video_nal_framing",
            "00 00 00 01 + NAL header; 00 00 01 BA/BC prefix headers before NAL units",
            "parsed",
            f"{S} s5",
            "BA/BC payload unknown; the generic carver's behaviour on real BA/BC data is untested",
        )

    def backup_master(self, m: dict) -> None:
        # [H] p.190: backup is "next to system logs", identical data; exact offset unknown (s1).
        lo = m["log_off"] + m["log_size"]
        hi = min(m["video_off"], lo + 0x10000, self.size)
        if not 0 < lo < hi:
            self.add(
                "backup_master_sector",
                "not searched (no valid log end / video start)",
                "unknown",
                f"{S} s1",
            )
            return
        i = self.rd(lo, hi - lo).find(MASTER)
        if i < 0:
            self.add(
                "backup_master_sector",
                f"not found in 0x{lo:X}..0x{hi:X}",
                "unknown",
                f"{S} s1",
                "location undocumented; absence is not claimed",
            )
            return
        off = lo + i
        n = min(len(m["raw"]), 0x100 - (m["base"] - 0x200))
        same = self.rd(off, n) == m["raw"][:n]
        self.add(
            "backup_master_sector",
            {"offset": off, "identical_to_primary": same},
            "inferred",
            f"{S} s1",
            "found by signature search after the log area; [H] says exactly the same data",
        )
        if not same:
            self.bad(f"backup Master Sector at 0x{off:X} differs from the primary")

    # ---- System logs (fields s2) ----------------------------------------------------------
    def logs(self, m: dict) -> None:
        start = m["log_off"]
        if m["log_size"] == 0 or start >= self.size:
            self.add("log_area", "not readable", "unknown", f"{S} s2")
            return
        end = min(start + m["log_size"], self.size, start + self.opts["max_log_scan_bytes"])
        if start + m["log_size"] > self.size:
            self.bad("log area extends beyond the image; scanned to the image end")
        elif end < start + m["log_size"]:
            self.warnings.append(f"log scan truncated at {self.opts['max_log_scan_bytes']} bytes")
        cap, ns = self.opts["max_log_records"], self.opts["log_sample_size"]
        sample: list[dict] = []
        majors: dict[int, int] = {}
        variants: dict[str, int] = {}
        n = trunc = 0
        tmin = tmax = first = None
        step = 1 << 20
        pos, prev, done = start, None, False
        while pos < end and not done:
            win = self.rd(pos, min(step + 64, end - pos))
            lim = min(step, end - pos)
            for mt in RATS_RE.finditer(win):
                if mt.start() >= lim:
                    break
                off = pos + mt.start()
                if n >= cap:
                    self.warnings.append(f"RATS record cap {cap} reached; remaining not scanned")
                    done = True
                    break
                n += 1
                first = off if first is None else first
                if prev is not None:
                    prev["len"] = off - prev["off"]
                    self.log_sample(prev, sample, ns)
                b = win[mt.start() : mt.start() + 0x24]
                rec = {"off": off, "len": None, "variant": b[4:8].hex(), "b": b}
                variants[rec["variant"]] = variants.get(rec["variant"], 0) + 1
                if len(b) >= 16 and off + 16 <= end:
                    t, ma, mi = struct.unpack_from("<IHH", b, 8)
                    rec.update(time=t, major=ma, minor=mi)
                    majors[ma] = majors.get(ma, 0) + 1
                    tmin = t if tmin is None else min(tmin, t)
                    tmax = t if tmax is None else max(tmax, t)
                    if len(self.stamps) < 5:
                        self.stamps.append(
                            self.stamp(
                                "log record created time",
                                off + 8,
                                t,
                                "unix seconds (u32 LE)",
                                "Dragonas p.66: local wall time in Unix-second form; Han gives "
                                "no timezone for logs",
                            )
                        )
                else:
                    trunc += 1
                    rec["cut"] = True
                prev = rec
            pos += lim
        if prev is not None:
            prev["len"] = end - prev["off"]
            self.log_sample(prev, sample, ns)
            if prev.get("cut"):
                self.bad("last RATS record is cut off by the end of the log area or image")
        self.stats.update(rats_records=n, rats_truncated=trunc)
        self.add("log_area", {"offset": start, "size": m["log_size"]}, "parsed", f"{S} s1/s2")
        self.add(
            "log_preamble",
            "first 2048 bytes undeciphered per Dragonas",
            "unknown",
            f"{S} s2",
            f"first RATS record at +0x{first - start:X}"
            if first is not None
            else "no RATS record found",
        )
        self.add(
            "rats_record_count",
            n,
            "inferred",
            f"{S} s2",
            "records delimited by the next RATS signature; no length field is documented",
        )
        self.add(
            "rats_header_variants",
            variants,
            "parsed",
            f"{S} s2",
            "bytes +0x04..+0x07 (01 vs 14): meaning unknown, not interpreted",
        )
        self.add(
            "rats_major_type_counts",
            {f"{k}:{MAJOR_NAMES.get(k, '?')}": v for k, v in sorted(majors.items())},
            "parsed",
            f"{S} s2",
            "[H] Table 1 / [D] p.66 names; majors outside 1-4 shown as '?'",
        )
        self.add(
            "rats_time_range_raw",
            [tmin, tmax],
            "parsed",
            f"{S} s2",
            "min/max raw epoch seconds over scanned records; timezone not assumed",
        )
        self.add(
            "rats_sample",
            sample,
            "parsed",
            f"{S} s2",
            f"first {ns} records; Details parsed only for Operation (user, IP) per Dragonas p.67; "
            "other Details layouts are undocumented",
        )
        if n == 0:
            self.warnings.append("no RATS records found in the log area")

    def log_sample(self, rec: dict, sample: list, cap: int) -> None:
        if len(sample) >= cap:
            return
        d = {"offset": rec["off"], "record_bytes": rec["len"], "header_variant": rec["variant"]}
        if rec.get("cut") or "time" not in rec:
            d["truncated"] = True
        else:
            ma, mi = rec["major"], rec["minor"]
            d.update(
                created_time_raw=rec["time"],
                created_wall=wall(rec["time"]),
                tz_basis=self.tz(),
                major=ma,
                major_name=MAJOR_NAMES.get(ma, "unrecognized"),
                minor=mi,
                minor_name=LOG_NAMES.get((ma, mi), "unmapped"),
            )
            b = rec["b"]
            if ma == 3 and len(b) >= 0x24 and (rec["len"] or 0) >= 0x24:
                d["user"] = b[0x10:0x20].split(b"\x00")[0].decode("ascii", "replace")
                d["ip"] = ".".join(str(x) for x in b[0x20:0x24])
        sample.append(d)

    # ---- HIKBTREE (fields s4) -------------------------------------------------------------
    def btree(self, m: dict) -> list[dict]:
        lo, hi = m["video_off"], min(m["hik1_off"], self.size)
        a = self.parse_btree(m["hik1_off"], m["hik1_size"], "HIKBTREE1", lo, hi)
        b = self.parse_btree(m["hik2_off"], m["hik2_size"], "HIKBTREE2", lo, hi)
        if a is None and b is not None:
            self.warnings.append("HIKBTREE1 unusable; entries taken from the backup HIKBTREE2")
        if a is not None and b is not None:

            def key(es):
                return [(e["block"], e["channel"], e["exists"], e["start"], e["end"]) for e in es]

            self.add(
                "hikbtree2_matches_hikbtree1",
                key(a) == key(b),
                "parsed",
                f"{S} s4",
                "entry-by-entry comparison; [H] only says HIKBTREE2 is a backup, so a difference "
                "is reported, not judged",
            )
        use = a if a is not None else b
        return use or []

    def parse_btree(self, base, size, tag, lo, hi) -> list[dict] | None:
        if not 0 < size <= 16 << 20 or base + 0x60 > self.size:
            self.bad(f"{tag}: offset 0x{base:X} / size {size} unusable")
            return None
        h = self.rd(base, 0x60)
        if len(h) < 0x60 or h[:8] != b"HIKBTREE":
            self.bad(f"{tag}: signature HIKBTREE not found at 0x{base:X}")
            return None
        end = base + size
        created = _u32(h, 0x2C)
        foot, plist, p1 = _u64(h, 0x30), _u64(h, 0x40), _u64(h, 0x48)
        if tag == "HIKBTREE1":
            self.stamps.append(
                self.stamp(
                    "hikbtree header created time",
                    base + 0x2C,
                    created,
                    "unix seconds (u32 LE)",
                    "[H] Fig.5 label; timezone not stated",
                )
            )
        self.add(
            f"{tag}_header",
            {"footer": foot, "page_list": plist, "page1": p1, "created_raw": created},
            "parsed",
            f"{S} s4.1",
            "+0x38 duplicate and +0x50/+0x58 unlabelled values are not interpreted",
        )
        for nm, o in (("footer", foot), ("page list", plist), ("page #1", p1)):
            if not base <= o < end:
                self.bad(f"{tag}: header {nm} offset 0x{o:X} is outside the HIKBTREE range")
                return None
        pl = self.rd(plist, 16)
        total = _u32(pl, 0) if len(pl) >= 4 else 0
        if total > self.opts["max_pages"] or total > size // PAGE_SIZE + 1:
            self.bad(f"{tag}: absurd page count {total}")
            return None
        stride, offs = 8, []
        for st in (8, 16):
            raw = self.rd(plist + 8, total * st)
            cand = [_u64(raw, k * st) for k in range(total) if (k + 1) * st <= len(raw)]
            if len(cand) == total and all(base <= c and c + PAGE_SIZE <= end for c in cand):
                stride, offs = st, cand
                break
        else:
            raw = self.rd(plist + 8, total * 8)
            offs = [_u64(raw, k * 8) for k in range(len(raw) // 8)][:total]
        if offs and offs[0] != p1:
            self.bad(f"{tag}: page list page #1 (0x{offs[0]:X}) != header page #1 (0x{p1:X})")
        pages, seen = [], {base, plist, foot}
        for k, o in enumerate(offs):
            if o in seen:
                self.bad(
                    f"{tag}: page {k + 1} offset 0x{o:X} repeats or references the header, page "
                    "list, footer or an earlier page (circular/self reference)"
                )
            elif not (base <= o and o + PAGE_SIZE <= end):
                self.bad(f"{tag}: page {k + 1} offset 0x{o:X} outside the HIKBTREE range")
            else:
                seen.add(o)
                pages.append((o, self.rd(o, PAGE_SIZE)))
        if len(offs) < total:
            self.bad(f"{tag}: page list shorter than its total-pages field ({total})")
        fl = self.rd(foot, 8)
        if len(fl) == 8 and offs and _u64(fl, 0) != offs[-1]:
            self.bad(f"{tag}: footer last-page offset 0x{_u64(fl, 0):X} != last listed page")
        self.add(
            f"{tag}_page_list",
            {"total_pages": total, "offsets": offs[:16], "slot_stride_chosen": stride},
            "parsed",
            f"{S} s4.2",
            "total pages and page #1 are documented; the stride of further offsets is not (8 or "
            "16 tried, first fully valid kept: inferred); next-page field position unknown",
        )
        entries = self.entries(tag, pages, lo, hi)
        self.stats[f"{tag}_pages"] = len(pages)
        self.stats[f"{tag}_entries"] = len(entries)
        return entries

    def entries(self, tag, pages, lo, hi) -> list[dict]:
        def kind(s: bytes) -> str:
            if len(s) < ENTRY_STRIDE or s == b"\x00" * ENTRY_STRIDE or s == b"\xff" * ENTRY_STRIDE:
                return "empty"
            ex = s[8:16]
            ok = len(set(ex)) == 1 and ex[0] in (0, 0xFF) and lo <= _u64(s, 0x20) < hi
            return "ok" if ok else "bad"

        def slots(first):
            for _o, pg in pages:
                for x in range(first, PAGE_SIZE - ENTRY_STRIDE + 1, ENTRY_STRIDE):
                    yield x, pg[x : x + ENTRY_STRIDE]

        fe = self.opts["btree_first_entry_offset"]
        best, best_n = None, 0
        for c in [fe] if fe != "auto" else range(0, 0x48, 8):
            n = sum(1 for _x, s in slots(c) if kind(s) == "ok")
            if n > best_n:
                best, best_n = c, n
        if best is None:
            if pages:
                self.warnings.append(f"{tag}: no plausible data-block entry found in any page")
            return []
        self.add(
            f"{tag}_entry_layout",
            {"first_entry_offset_in_page": best, "stride": ENTRY_STRIDE},
            "inferred",
            f"{S} s4.4",
            "stride 48 is read off Fig.6 (not stated in text); the first-entry offset inside a "
            "page is undocumented and was chosen by plausibility (see option)",
        )
        out, badn = [], 0
        for po, pg in pages:
            for x in range(best, PAGE_SIZE - ENTRY_STRIDE + 1, ENTRY_STRIDE):
                s = pg[x : x + ENTRY_STRIDE]
                k = kind(s)
                if k == "bad":
                    badn += 1
                elif k == "ok":
                    if len(out) >= self.opts["max_btree_entries"]:
                        self.warnings.append("HIKBTREE entry cap reached; list truncated")
                        return out
                    out.append(
                        {
                            "off": po + x,
                            "exists": s[8] == 0,
                            "channel": s[0x11],
                            "start": _u32(s, 0x18),
                            "end": _u32(s, 0x1C),
                            "block": _u64(s, 0x20),
                        }
                    )
        if badn:
            self.bad(
                f"{tag}: {badn} non-empty entry slot(s) implausible (existence flag not uniform "
                "00/FF or block offset outside the video area); skipped"
            )
        return out

    # ---- Video (fields s3, s5) ------------------------------------------------------------
    def video(self, m: dict, entries: list[dict]) -> None:
        used = m["used"]
        full = [e for e in entries if e["exists"]]
        self.stats.update(entries=len(entries), entries_with_video=len(full))
        for e in entries:
            sent = (e["start"], e["end"]) == SENTINEL
            if not e["exists"] and (e["channel"] != 0xFF or not sent):
                self.bad(
                    f"entry @0x{e['off']:X}: existence 0xFF but channel/times are not the "
                    "documented no-video values (fields check 7)"
                )
            if e["exists"] and e["channel"] == 0xFF:
                self.bad(f"entry @0x{e['off']:X}: existence 0x00 with channel 0xFF")
        if not full:
            return
        if not used:
            self.bad("block size unusable; no block can be located")
            return
        self.add(
            "hikbtree_entry_semantics",
            "existence 00 = block holds video; FF = none; real start/end times only on full "
            "blocks, else FF FF FF 7F 00 00 00 00",
            "parsed",
            f"{S} s4.4",
            "Fig.6 labels (Recording/Recorded) disagree with the text; start-before-end order is "
            "inferred from the sample",
        )
        by_block: dict[int, list[dict]] = {}
        for e in full:
            by_block.setdefault(e["block"], []).append(e)
        scanned_to = idr_total = idr_blocks = 0
        limit = self.opts["max_blocks_scanned"]
        for k, start in enumerate(sorted(by_block)):
            if k >= limit:
                self.warnings.append(f"block scan cap {limit} reached; remaining not scanned")
                break
            es = by_block[start]
            rel = start - m["video_off"]
            if rel < 0 or rel % used:
                self.bad(f"block 0x{start:X} is not video_offset + n*{used:#x} (size in use)")
                continue
            if m["block_count"] and rel // used >= m["block_count"]:
                self.bad(f"block 0x{start:X} index {rel // used} >= block count {m['block_count']}")
                continue
            if start < scanned_to:
                self.bad(
                    f"block 0x{start:X} overlaps an earlier scanned range (size in use too large "
                    "for the entry offsets)"
                )
                continue
            end, clamped = start + used, False
            lim = min(self.size, m["hik1_off"] if m["hik1_off"] > start else self.size)
            if end > lim:
                self.bad(f"block 0x{start:X}+{used:#x} extends past the image/HIKBTREE1; clamped")
                end, clamped = lim, True
            if end <= start:
                continue
            scanned_to = end
            nrec = 0 if clamped else self.idr_count(end, used)
            if nrec:
                idr_total, idr_blocks = idr_total + nrec, idr_blocks + 1
            chans = {e["channel"] for e in es}
            if len(chans) > 1:
                self.bad(
                    f"block 0x{start:X} referenced by entries with channels {sorted(chans)}; "
                    "channel attribution not possible"
                )
            times = {(e["start"], e["end"]) for e in es}
            real = len(times) == 1 and next(iter(times)) != SENTINEL
            if real and es[0]["start"] > es[0]["end"]:
                self.bad(f"entry @0x{es[0]['off']:X}: start time > end time; timestamps omitted")
                real = False
            ch = es[0]["channel"] if len(chans) == 1 else None
            self.carve_block(es[0], start, end, end - IDR_REC * nrec, nrec, ch, real)
        self.stats.update(idr_table_records=idr_total, idr_table_blocks=idr_blocks)
        self.add(
            "idr_table",
            {"blocks_with_table": idr_blocks, "records": idr_total},
            "parsed",
            f"{S} s3",
            "only the 'OFNI' signature at 56-byte stride downward from the block end was counted "
            "(documented); field offsets inside a record are unknown and not read",
        )
        self.add(
            "idr_table_record_fields",
            "not parsed",
            "unknown",
            f"{S} s3",
            "no source gives the field layout of the 56-byte record",
        )
        self.add(
            "video_region_end",
            "block end minus 56 * counted records",
            "inferred",
            f"{S} s3",
            "table position is partly documented; used only to bound the NAL scan",
        )

    def idr_count(self, end: int, block: int) -> int:
        n = min(block, MAX_IDR_SCAN) // IDR_REC * IDR_REC
        buf = self.rd(end - n, n)
        k = 0
        while (k + 1) * IDR_REC <= len(buf):
            o = len(buf) - (k + 1) * IDR_REC
            if buf[o : o + 4] != IDR_SIG:
                break
            k += 1
        return k

    def carve_block(self, e, start, end, vend, nrec, ch, real) -> None:
        def read_at(o, n):
            self.f.seek(o)
            return self.f.read(n)

        carver = Carver(read_at, CarveParams())
        win = _Win(self.f, start, vend - start)
        for item in carver.run(_shift(nal.scan(win, vend - start), start)):
            if not hasattr(item, "extents"):
                if len(self.orphans) < 1000:
                    self.orphans.append(
                        ParsedOrphan(ch, item.start, item.end, item.nal_count, item.reason)
                    )
                continue
            if item.codec != "h264":
                self.orphans.append(
                    ParsedOrphan(
                        ch,
                        item.start,
                        item.end,
                        item.vcl_count,
                        f"{item.codec}: Hikvision H.265 framing is undocumented; not claimed",
                    )
                )
                continue
            c = ParsedClip(
                "h264",
                [list(x) for x in item.extents],
                ch,
                item.vcl_count,
                item.irap_count,
                True,
                end_reason=item.end_reason,
            )
            if real:
                c.timestamps = [
                    self.stamp(
                        "hikbtree entry start",
                        e["off"] + 0x18,
                        e["start"],
                        "unix seconds (u32 LE)",
                        "start/end order inferred (s4.4); block-level time, not per clip",
                    ),
                    self.stamp(
                        "hikbtree entry end",
                        e["off"] + 0x1C,
                        e["end"],
                        "unix seconds (u32 LE)",
                        "block-level time; real values only when the block is full (s4.4)",
                    ),
                ]
            else:
                c.notes.append("entry times absent/sentinel or inconsistent: no timestamps")
            c.fields = [
                ParsedField(
                    "entry_channel",
                    e["channel"],
                    "parsed",
                    f"[H] Fig.6 +0x11; {S} s4.4",
                    "camera number in the HIKBTREE entry",
                ),
                ParsedField(
                    "channel_attribution",
                    ch,
                    "inferred",
                    f"{S} s3",
                    "[H] p.193: a block can also hold other channels' video; attribution to the "
                    "entry channel is not verified (IDR table layout unknown)",
                ),
                ParsedField(
                    "block",
                    [start, end],
                    "inferred",
                    f"{S} s3/s7",
                    "start = entry offset (parsed); end = start + size in use",
                ),
                ParsedField("idr_table_records_in_block", nrec, "parsed", f"{S} s3"),
                ParsedField(
                    "clip_boundaries",
                    "generic Annex-B carver inside the block",
                    "inferred",
                    "app.carving",
                    "NAL framing per [H] Table 2",
                ),
                ParsedField("idr_record_fields", "not parsed", "unknown", f"{S} s3"),
            ]
            self.clips.append(c)
