"""Scenario matrix. Every scenario builds SYNTHETIC images from a seeded rng; classes are scored
separately. `kind` is 'positive' (clips expected) or 'negative' (must yield no decodable clip)."""

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.validation.image import Builder, noise
from app.validation.streams import NalInfo, Stream, StreamPool, aux_stream, derived


@dataclass
class Scenario:
    id: str
    title: str
    kind: str
    description: str
    build: Callable[[random.Random, StreamPool, int], Builder]
    carve: dict = field(default_factory=dict)  # CarveParams overrides
    trials: int | None = None  # override of the global trial count
    export: bool = True
    group: str = ""  # scenarios with the same group share seeds (identical images)
    layout: str = "raw"
    layout_label: str = ""  # per-paper label for vendor layouts
    engines: tuple = ("generic",)


def pick(rng: random.Random, pool: StreamPool, n: int, codec: str | None = None) -> list[Stream]:
    """n streams; neighbours always have different variants (different parameter sets)."""
    pop = pool.by_codec(codec) if codec else pool.all()
    out: list[Stream] = []
    for _ in range(n):
        choices = [s for s in pop if not out or s.variant.name != out[-1].variant.name]
        out.append(rng.choice(choices))
    return out


def _clips(b: Builder, streams: list[Stream], expected="recover", state="live") -> list[str]:
    ids = []
    for s in streams:
        cid = f"c{len(b.clips)}"
        b.clip(cid, s, expected, state=state)
        ids.append(cid)
    return ids


# ---- positive scenarios ------------------------------------------------------------------------


def clean_live(rng, pool, _i):
    b = Builder(rng)
    b.zeros(2048)
    for cid in _clips(b, pick(rng, pool, 3)):
        b.place(cid)
    b.zeros(4096)
    return b


def deleted_intact_zero(rng, pool, _i):
    b = Builder(rng)
    b.noise(rng.randrange(500, 3000))
    for i, cid in enumerate(_clips(b, pick(rng, pool, 3))):
        b.clips[cid].state = "live" if i == 0 else "deleted"
        b.place(cid)
        b.zeros(-b.pos() % 4096 + 4096)  # sector-aligned zero padding
    b.noise(rng.randrange(500, 3000))
    return b


def zero_gaps(rng, pool, _i):
    b = Builder(rng)
    for cid in _clips(b, pick(rng, pool, 3)):
        b.zeros(rng.choice([1, 16, 100, 1000, 65536]))
        b.place(cid)
    b.zeros(rng.choice([1, 100, 5000]))
    return b


def _place_padded(b: Builder, cid: str, rng: random.Random, lo: int, hi: int) -> None:
    t = b.clips[cid]
    for n in t.stream.nals:
        s = len(b.buf)
        b.buf += t.stream.data[n.start : n.end]
        from app.validation.image import Piece

        t.pieces.append(Piece(s, len(b.buf), n.start, cid))
        b.zeros(rng.randrange(lo, hi + 1))


def zero_pad_inside_narrow(rng, pool, _i):
    b = Builder(rng)
    b.zeros(1024)
    for cid in _clips(b, pick(rng, pool, 2)):
        _place_padded(b, cid, rng, 1, 48)  # within the default 64-byte max_pad
        b.zeros(2048)
    return b


def zero_pad_inside_wide(rng, pool, _i):
    b = Builder(rng)
    b.zeros(1024)
    for cid in _clips(b, pick(rng, pool, 2)):
        _place_padded(b, cid, rng, 100, 300)  # beyond max_pad: documented limitation
        b.zeros(2048)
    return b


def random_gaps_between(rng, pool, _i):
    b = Builder(rng)
    b.zeros(1024)
    for cid in _clips(b, pick(rng, pool, 3)):
        b.place(cid)
        b.noise(rng.randrange(100, 5000))
    b.zeros(1024)
    return b


def random_gaps_inside(rng, pool, _i):
    from app.validation.image import Piece

    b = Builder(rng)
    b.zeros(1024)
    for cid in _clips(b, pick(rng, pool, 2)):
        t = b.clips[cid]
        cuts = sorted(rng.sample(range(1, len(t.stream.nals)), 2))
        for k, n in enumerate(t.stream.nals):
            s = len(b.buf)
            b.buf += t.stream.data[n.start : n.end]
            t.pieces.append(Piece(s, len(b.buf), n.start, cid))
            if k in cuts:
                b.noise(rng.randrange(50, 600))
        b.zeros(2048)
    return b


def _nal_cut(rng, s: Stream, parts: int) -> list[int]:
    """Stream offsets (NAL boundaries) splitting the stream into `parts` pieces."""
    cand = [n.start for n in s.nals[1:] if not n.param]
    cuts = sorted(rng.sample(cand, parts - 1))
    return [0, *cuts, len(s.data)]


def _overwritten(rng, pool, mode):
    b = Builder(rng)
    b.zeros(2048)
    surv = pick(rng, pool, 1)[0]
    b.clip("S", surv)
    b.place("S")
    b.zeros(4096)
    victim = pick(rng, pool, 1)[0]
    if victim.variant.name == surv.variant.name:
        victim = next(s for s in pool.all() if s.variant.name != surv.variant.name)
    b.clip("V", victim, state="deleted")
    s, e = b.place("V")
    b.zeros(4096)
    n = e - s
    frac = rng.choice([0.2, 0.4, 0.6])
    where = rng.choice(["head", "middle", "tail"])
    length = int(n * frac)
    start = {"head": 0, "middle": (n - length) // 2, "tail": n - length}[where]
    if mode == "zero":
        b.overwrite(s + start, b"\x00" * length)
    else:  # a newer recording overwrote the region
        new = next(
            x
            for x in pool.all()
            if x.variant.name != victim.variant.name and x.variant.name != surv.variant.name
        )
        b.clip("N", new, state="live")
        b.foreign("N", s + start, length)
    b.notes.append(f"{mode} overwrite of {where} {frac:.0%}")
    return b


def partial_overwrite_zero(rng, pool, _i):
    return _overwritten(rng, pool, "zero")


def partial_overwrite_foreign(rng, pool, _i):
    return _overwritten(rng, pool, "foreign")


def fully_overwritten(rng, pool, i):
    b = Builder(rng)
    b.zeros(2048)
    surv = pick(rng, pool, 1)[0]
    b.clip("S", surv)
    b.place("S")
    b.zeros(4096)
    victim = next(s for s in pool.all() if s.variant.name != surv.variant.name)
    b.clip("V", victim, expected="none", state="deleted")
    s, e = b.place("V")
    mode = ["zeros", "noise", "foreign"][i % 3]
    if mode == "zeros":
        b.overwrite(s, b"\x00" * (e - s))
    elif mode == "noise":
        b.overwrite(s, noise(rng, e - s))
    else:
        new = next(
            x for x in pool.all() if x.variant.name not in (victim.variant.name, surv.variant.name)
        )
        b.clip("N", new)
        b.foreign("N", s, e - s)
    b.zeros(4096)
    b.notes.append(f"fully overwritten with {mode}")
    return b


def fragmented_zero(rng, pool, _i):
    """One clip in 2-4 NAL-aligned fragments, in order, separated by zero-filled gaps."""
    b = Builder(rng)
    b.zeros(1024)
    s = pick(rng, pool, 1, "h264")[0]
    b.clip("A", s)
    cuts = _nal_cut(rng, s, rng.randrange(2, 5))
    for a, z in zip(cuts, cuts[1:], strict=False):
        b.place("A", a, z)
        b.zeros(rng.randrange(1000, 50000))
    return b


def fragmented_decoy(rng, pool, _i):
    """A1 | zeros | other recording B | zeros | A2: A2 only continues A, never B."""
    b = Builder(rng)
    b.zeros(1024)
    a, other = pick(rng, pool, 2, "h264")
    b.clip("A", a)
    b.clip("B", other)
    cuts = _nal_cut(rng, a, 2)
    b.place("A", cuts[0], cuts[1])
    b.zeros(rng.randrange(1000, 20000))
    b.place("B")
    b.zeros(rng.randrange(1000, 20000))
    b.place("A", cuts[1], cuts[2])
    b.zeros(2048)
    return b


def _fake_h264_group(rng) -> bytes:
    sc = b"\x00\x00\x00\x01"
    return (
        sc
        + b"\x67"
        + noise(rng, 12)
        + sc
        + b"\x68"
        + noise(rng, 4)
        + sc
        + b"\x65"
        + noise(rng, rng.randrange(40, 400))
    )


def _fake_h265_group(rng) -> bytes:
    sc = b"\x00\x00\x00\x01"
    return (
        sc
        + b"\x40\x01"
        + noise(rng, 20)
        + sc
        + b"\x42\x01"
        + noise(rng, 30)
        + sc
        + b"\x44\x01"
        + noise(rng, 6)
        + sc
        + b"\x26\x01"
        + noise(rng, rng.randrange(40, 400))
    )


def _junk(rng, n: int) -> bytes:
    """Noise peppered with false start codes, fake headers and fake parameter-set groups."""
    out = bytearray()
    while len(out) < n:
        r = rng.random()
        if r < 0.5:
            out += b"\x00\x00\x01" + noise(rng, rng.randrange(2, 60))
        elif r < 0.7:
            out += _fake_h264_group(rng)
        elif r < 0.85:
            out += _fake_h265_group(rng)
        else:
            out += noise(rng, rng.randrange(20, 500))
    return bytes(out[:n])


def adversarial_noise_with_clips(rng, pool, _i):
    b = Builder(rng)
    b.zeros(512)
    b.raw(_junk(rng, rng.randrange(20000, 60000)))
    b.zeros(1024)
    for cid in _clips(b, pick(rng, pool, 2)):
        b.place(cid)
        b.zeros(256)
        b.raw(_junk(rng, rng.randrange(5000, 30000)))
        b.zeros(1024)
    return b


def _interleave(rng, pool, unit_level: bool):
    b = Builder(rng)
    b.zeros(1024)
    base = rng.choice(pool.by_codec("h264")).variant.name
    chans = [derived(pool, base, h) for h in (10, 120, 230)][: rng.choice([2, 3])]
    for i, s in enumerate(chans):
        b.clip(f"ch{i}", s, state="live")
        b.clips[f"ch{i}"].channel = i
    units = []  # per channel: list of (stream_start, stream_end)
    for s in chans:
        u, cur = [], None
        for n in s.nals:
            if cur is None:
                cur = [n.start, n.end]
            else:
                cur[1] = n.end
            if n.vcl:
                u.append(tuple(cur))
                cur = None
        units.append(u)
    if unit_level:
        order = max(len(u) for u in units)
        for k in range(order):
            for i, u in enumerate(units):
                if k < len(u):
                    b.place(f"ch{i}", *u[k])
    else:  # GOP level: whole GOPs alternate
        gops = []
        for s in chans:
            g: dict[int, list[NalInfo]] = {}
            for n in s.nals:
                g.setdefault(n.gop, []).append(n)
            gops.append([(v[0].start, v[-1].end) for v in g.values()])
        for k in range(max(len(g) for g in gops)):
            for i, g in enumerate(gops):
                if k < len(g):
                    b.place(f"ch{i}", *g[k])
    b.zeros(2048)
    b.notes.append(
        f"{len(chans)} channels with identical parameter sets, interleaved by {'frame' if unit_level else 'GOP'}"
    )
    return b


def multi_channel_gop(rng, pool, _i):
    return _interleave(rng, pool, False)


def multi_channel_frame(rng, pool, _i):
    return _interleave(rng, pool, True)


# ---- negative scenarios ------------------------------------------------------------------------


def _ctr(rng: random.Random, data: bytes) -> bytes:
    key, nonce = rng.randbytes(16), rng.randbytes(16)
    enc = Cipher(algorithms.AES(key), modes.CTR(nonce)).encryptor()
    return enc.update(data) + enc.finalize()


def _neg(rng, payload: bytes) -> Builder:
    b = Builder(rng)
    b.zeros(2048)
    b.raw(payload)
    b.zeros(4096)
    return b


def neg_noise_start_codes(rng, pool, _i):
    return _neg(rng, _junk(rng, rng.randrange(200_000, 600_000)))


def neg_encrypted_whole(rng, pool, _i):
    return _neg(rng, _ctr(rng, pick(rng, pool, 1)[0].data))


def _encrypt_nals(rng, s: Stream, keep_params: bool) -> bytes:
    hdr = 1 if s.variant.codec == "h264" else 2
    out = bytearray()
    for n in s.nals:
        raw = s.data[n.start : n.end]
        i = raw.index(b"\x01") + 1 + hdr  # start code + NAL header stay in clear
        if keep_params and n.param:
            out += raw
        else:
            out += raw[:i] + _ctr(rng, raw[i:])
    return bytes(out)


def neg_encrypted_slices_params_clear(rng, pool, _i):
    return _neg(rng, _encrypt_nals(rng, pick(rng, pool, 1)[0], True))


def neg_encrypted_all_payloads(rng, pool, _i):
    return _neg(rng, _encrypt_nals(rng, pick(rng, pool, 1)[0], False))


def neg_mjpeg(rng, pool, _i):
    return _neg(rng, aux_stream("mjpeg"))


def neg_mpeg4(rng, pool, _i):
    return _neg(rng, aux_stream("mpeg4"))


SCENARIOS: list[Scenario] = [
    Scenario(
        "clean_live",
        "Clean live clips, back to back",
        "positive",
        "Three adjacent recordings with distinct parameter sets, zero padding at both ends.",
        clean_live,
    ),
    Scenario(
        "deleted_intact_zero",
        "Deleted-then-intact, zero-padded",
        "positive",
        "One live and two deleted-but-intact clips, 4 KiB-aligned zero padding, noise outside.",
        deleted_intact_zero,
    ),
    Scenario(
        "zero_gaps",
        "Zero-filled gaps between clips",
        "positive",
        "Gaps of 1 B to 64 KiB of zeros between clips.",
        zero_gaps,
    ),
    Scenario(
        "zero_pad_inside_narrow",
        "Zero padding inside a clip (<= 48 B)",
        "positive",
        "Zero bytes between NAL units within the default 64-byte limit.",
        zero_pad_inside_narrow,
    ),
    Scenario(
        "zero_pad_inside_wide",
        "Zero padding inside a clip (100-300 B)",
        "positive",
        "Padding beyond max_pad: documented limitation, expected to lose data.",
        zero_pad_inside_wide,
    ),
    Scenario(
        "random_gaps_between",
        "Random-garbage gaps between clips",
        "positive",
        "100-5000 bytes of random data (no zero runs) after each clip; absorbed into the last NAL.",
        random_gaps_between,
    ),
    Scenario(
        "random_gaps_inside",
        "Random garbage inserted inside a clip",
        "positive",
        "50-600 random bytes inserted between NAL units, twice per clip.",
        random_gaps_inside,
    ),
    Scenario(
        "partial_overwrite_zero",
        "Partially overwritten by zeros",
        "positive",
        "Head/middle/tail 20-60% of a deleted clip zeroed; survivors scored on recoverable frames.",
        partial_overwrite_zero,
    ),
    Scenario(
        "partial_overwrite_foreign",
        "Partially overwritten by a newer recording",
        "positive",
        "Region replaced by the start of another clip (itself a truth clip).",
        partial_overwrite_foreign,
    ),
    Scenario(
        "fully_overwritten",
        "Fully overwritten clip (negative component)",
        "positive",
        "One intact survivor plus a clip fully overwritten (zeros, noise or another clip); the destroyed clip must not appear.",
        fully_overwritten,
    ),
    Scenario(
        "fragmented_zero_join_off",
        "Fragmented, zero gaps, reassembly off",
        "positive",
        "Clip in 2-4 NAL-aligned fragments with zero gaps.",
        fragmented_zero,
        group="frag_zero",
    ),
    Scenario(
        "fragmented_zero_join_on",
        "Fragmented, zero gaps, reassembly on (join_gap 100 KB)",
        "positive",
        "Same images as above with the heuristic reassembler enabled.",
        fragmented_zero,
        {"join_gap": 100_000},
        group="frag_zero",
    ),
    Scenario(
        "fragmented_decoy_join_off",
        "Fragments split by another recording, reassembly off",
        "positive",
        "A1, other clip B, A2.",
        fragmented_decoy,
        group="frag_decoy",
    ),
    Scenario(
        "fragmented_decoy_join_on",
        "Fragments split by another recording, reassembly on",
        "positive",
        "Same images; every join candidate is a wrong one (false-accept study).",
        fragmented_decoy,
        {"join_gap": 100_000},
        trials=300,
        export=False,
        group="frag_decoy",
    ),
    Scenario(
        "adversarial_noise_with_clips",
        "Adversarial noise around real clips",
        "positive",
        "False start codes, fake H.264/H.265 parameter-set groups and fake IDRs around two real clips.",
        adversarial_noise_with_clips,
    ),
    Scenario(
        "multi_channel_gop",
        "Multi-channel, GOP-interleaved, identical parameter sets",
        "positive",
        "2-3 cameras, whole GOPs alternate. No channel metadata: demultiplexing is out of scope for the generic carver.",
        multi_channel_gop,
    ),
    Scenario(
        "multi_channel_frame",
        "Multi-channel, frame-interleaved, identical parameter sets",
        "positive",
        "2-3 cameras interleaved per frame. Expected to fail for the generic carver.",
        multi_channel_frame,
    ),
    Scenario(
        "neg_noise_start_codes",
        "Negative: noise with false start codes",
        "negative",
        "No real video; must yield no decodable clip.",
        neg_noise_start_codes,
    ),
    Scenario(
        "neg_encrypted_whole",
        "Negative: whole stream encrypted (AES-CTR)",
        "negative",
        "Looks random; must yield nothing.",
        neg_encrypted_whole,
    ),
    Scenario(
        "neg_encrypted_slices_params_clear",
        "Negative: slice payloads encrypted, parameter sets clear",
        "negative",
        "Headers and parameter sets readable, slices encrypted.",
        neg_encrypted_slices_params_clear,
    ),
    Scenario(
        "neg_encrypted_all_payloads",
        "Negative: all NAL payloads encrypted, headers clear",
        "negative",
        "Start codes and NAL headers clear.",
        neg_encrypted_all_payloads,
    ),
    Scenario(
        "neg_mjpeg",
        "Negative: MJPEG stream",
        "negative",
        "Not NAL-based; must yield nothing.",
        neg_mjpeg,
    ),
    Scenario(
        "neg_mpeg4",
        "Negative: MPEG-4 Part 2 stream",
        "negative",
        "Different start-code scheme; must yield nothing.",
        neg_mpeg4,
    ),
]


DHAV_SET = (
    "clean_live",
    "deleted_intact_zero",
    "zero_gaps",
    "random_gaps_between",
    "partial_overwrite_zero",
    "partial_overwrite_foreign",
    "fully_overwritten",
    "fragmented_zero_join_on",
    "fragmented_decoy_join_on",
    "multi_channel_gop",
    "multi_channel_frame",
)


def _dhav_variants() -> list[Scenario]:
    out = []
    for sc in SCENARIOS:
        if sc.id in DHAV_SET:
            out.append(
                Scenario(
                    f"{sc.id}@dhav",
                    sc.title + " (DHAV per-paper layout)",
                    sc.kind,
                    sc.description + " Frames wrapped in DHAV headers/trailers per dhav.c.",
                    sc.build,
                    sc.carve,
                    sc.trials,
                    sc.export,
                    sc.group + "@dhav" if sc.group else sc.id + "@dhav",
                    "dhav",
                    ("generic", "dahua"),
                )
            )
    return out


SCENARIOS += _dhav_variants()


def _vendor_variants(module: str, suffix: str, engine: str) -> list[Scenario]:
    """Scenarios from a vendor layout module (SCENARIOS dict + LAYOUT label). Images come from
    the module's per-paper layout builder, never from a real device."""
    import importlib

    try:
        mod = importlib.import_module(f"app.validation.{module}")
    except ImportError:
        return []
    base = {s.id: s for s in SCENARIOS if s.layout == "raw"}
    out = []
    for key, fn in mod.SCENARIOS.items():
        ref = base.get(key)
        out.append(
            Scenario(
                f"{key}@{suffix}",
                (ref.title if ref else key) + f" ({suffix} per-paper layout)",
                ref.kind if ref else "positive",
                (ref.description if ref else key) + " Image built from documented fields only.",
                fn,
                trials=None,
                export=True,
                group=f"{key}@{suffix}",
                layout=suffix,
                layout_label=mod.LAYOUT,
                engines=("generic", engine),
            )
        )
    return out


SCENARIOS += _vendor_variants("layouts_hikvision", "hik", "hikvision")
SCENARIOS += _vendor_variants("layouts_honeywell", "honeywell", "honeywell")
