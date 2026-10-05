import io

import pytest

from app.vendors import TIER_C_VENDORS, default_registry
from app.vendors.base import (
    CONFIDENCE_ORDER,
    TIERS,
    CarveHints,
    Match,
    ParserRegistry,
    Probe,
    Signature,
    VendorParser,
    scan_image,
)
from tests import vendor_images as V
from tests.media import filler


def ident(data, chunk=1 << 20, registry=None):
    reg = registry or default_registry()
    return reg.identify(io.BytesIO(data), len(data), chunk)


# ---- identification ------------------------------------------------------------------------


def test_hikvision_master_sector_at_documented_offset():
    m = ident(V.hikvision())[0]
    assert m.vendor == "Hikvision" and m.tier == "B" and m.confidence == "medium"
    offs = {(h.signature, h.offset) for h in m.evidence}
    assert ("hik_master_0x200", 0x200) in offs and ("hik_master_any", 0x200) in offs
    assert any(s == "hik_rats_log" for s, _ in offs) and any(s == "hik_btree" for s, _ in offs)
    assert m.signature_counts["hik_rats_log"] == 2
    assert any("RESEARCH 3.1" in b for b in m.basis) and m.notes


def test_hikvision_btree_alone_is_only_low_confidence():
    m = ident(V.hikvision(master=False, rats=False))[0]
    assert m.confidence == "low"


def test_hikvision_rats_requires_documented_follower_bytes():
    img = bytearray(filler(1 << 16, 3))
    img[1000:1008] = b"RATS\xaa\xbb\xcc\xdd"
    assert ident(bytes(img)) == []


def test_dahua_frames_with_verified_trailers():
    m = ident(V.dahua(frames=5))[0]
    assert m.vendor == "Dahua" and m.tier == "B" and m.confidence == "medium"
    assert m.signature_counts["dahua_dhav_frame"] == 5
    assert all("trailer verified" in h.detail for h in m.evidence)


def test_dahua_few_frames_low_and_bad_trailer_rejected():
    assert ident(V.dahua(frames=2))[0].confidence == "low"
    assert ident(V.dahua(frames=5, bad_trailer=True)) == []


def test_bare_dhav_string_is_not_enough():
    img = bytearray(filler(10000, 5))
    img[100:105] = b"DHAV\xfd"
    assert ident(bytes(img)) == []


def test_dahua_exported_file_prefix_is_reported_as_such():
    m = ident(b"DAHUA" + b"\x00" * 1019 + V.dhav_frame())[0]
    assert any("exported DAV file" in h.detail for h in m.evidence)


def test_honeywell_headers_and_machine_data():
    m = ident(V.honeywell())[0]
    assert m.vendor == "Honeywell" and m.confidence == "medium"
    assert m.signature_counts["honeywell_custom_header"] == 5
    assert any("HN35080200" in h.detail for h in m.evidence)
    assert "single model" in " ".join(m.notes)


def test_honeywell_headers_without_machine_data_stay_low_and_junk_rejected():
    assert ident(V.honeywell(machine=False))[0].confidence == "low"
    img = bytearray(filler(8000, 6))
    img[500:503] = b"\x80\x01\x00"
    assert ident(bytes(img)) == []


@pytest.mark.parametrize("chunk", [1, 7, 61, 4096])
def test_signatures_across_chunk_boundaries(chunk):
    data = V.dahua(frames=4, noise=300)
    assert ident(data, chunk)[0].signature_counts == ident(data)[0].signature_counts


def test_unknown_vendor_returns_no_match_and_no_vendor_is_ever_high_confidence():
    assert ident(filler(100_000, 8)) == [] and ident(b"") == [] and ident(b"\x00" * 5000) == []
    for img in (V.hikvision(), V.dahua(), V.honeywell()):
        assert all(m.confidence in ("low", "medium") for m in ident(img))


def test_mixed_image_ranks_both_vendors():
    img = V.hikvision() + V.dahua(frames=5)
    ms = ident(img)
    assert {m.vendor for m in ms} == {"Hikvision", "Dahua"}
    assert [CONFIDENCE_ORDER[m.confidence] for m in ms] == sorted(
        [CONFIDENCE_ORDER[m.confidence] for m in ms], reverse=True
    )


def test_evidence_list_is_bounded_but_count_is_exact():
    data = b"".join(V.dhav_frame() for _ in range(50))
    m = ident(data)[0]
    assert m.signature_counts["dahua_dhav_frame"] == 50 and len(m.evidence) <= 40


# ---- plugin interface contract --------------------------------------------------------------


@pytest.mark.parametrize("parser", default_registry().parsers, ids=lambda p: p.vendor)
def test_builtin_parsers_honour_the_contract(parser):
    assert parser.vendor and parser.tier in TIERS and parser.tier != "A"
    assert parser.sources and all("RESEARCH" in s for s in parser.sources)
    assert all(isinstance(s, Signature) and s.pattern for s in parser.signatures())
    assert all(isinstance(p, Probe) for p in parser.probes())
    assert (
        isinstance(parser.carve_hints(), CarveHints) and parser.enumerate(io.BytesIO(b""), 0) == []
    )
    empty = parser.identify(scan_image(io.BytesIO(b""), 0, [parser]))
    assert isinstance(empty, Match) and empty.confidence == "none" and empty.vendor == parser.vendor


def test_tier_c_vendors_have_no_parser():
    names = {p.vendor for p in default_registry().parsers}
    assert not names & set(TIER_C_VENDORS)


class DummyParser(VendorParser):
    vendor, tier, sources = "DummyCo", "C", ("test only",)

    def signatures(self):
        return [Signature("dummy_magic", b"DUMMYMAGIC", lambda read, off: f"dummy at {off}")]

    def probes(self):
        return [Probe("dummy_head", 0, 4, lambda b: "head" if b == b"DUMM" else None)]

    def identify(self, scope):
        if not scope.counts:
            return self.empty_match()
        return Match(
            self.vendor, self.tier, "low", scope.hits.get("dummy_magic", []), self.own_counts(scope)
        )


def test_dummy_plugin_flows_through_the_registry_and_coexists():
    reg = ParserRegistry([DummyParser(), *default_registry().parsers])
    data = b"DUMMYMAGIC" + filler(5000, 9) + V.dhav_frame() * 4
    ms = ident(data, registry=reg)
    assert {m.vendor for m in ms} == {"DummyCo", "Dahua"}
    dummy = next(m for m in ms if m.vendor == "DummyCo")
    assert dummy.signature_counts == {"dummy_head": 1, "dummy_magic": 1}
    assert ident(filler(2000, 1), registry=reg) == []


def test_parser_that_raises_is_not_swallowed_silently():
    class Broken(DummyParser):
        def identify(self, scope):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        ident(b"x" * 100, registry=ParserRegistry([Broken()]))


def test_scan_memory_is_bounded_on_a_large_image(tmp_path):
    import tracemalloc

    p = tmp_path / "big.bin"
    with open(p, "wb") as f:
        for i in range(48):
            f.write(filler(1 << 20, i))
    tracemalloc.start()
    with open(p, "rb") as f:
        default_registry().identify(f, p.stat().st_size, 1 << 20)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < 16 * (1 << 20)
