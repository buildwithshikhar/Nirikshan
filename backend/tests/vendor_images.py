"""SYNTHETIC images built only from fields documented in docs/RESEARCH.md. They are per-paper
layouts for testing identification, NOT images of real devices."""

import struct

from tests.media import filler

H264_NAL = b"\x65" + b"\x88" * 30  # IDR-looking NAL payload (not decodable; identification only)


def hikvision(size=1 << 20, *, master=True, btree=True, rats=True) -> bytes:
    img = bytearray(filler(size, 21))
    if master:
        img[0x200 : 0x200 + 18] = b"HIKVISION@HANGZHOU"
    if btree:
        img[size - 4096 : size - 4096 + 8] = b"HIKBTREE"
    if rats:
        img[0x3D13200 % size : 0x3D13200 % size + 8] = b"RATS" + b"\x14\x00\x00\x00"
        img[70000:70008] = b"RATS" + b"\x01\x00\x00\x00"
    return bytes(img)


def dhav_frame(ftype=0xFD, channel=1, payload=b"\x00\x00\x00\x01" + H264_NAL) -> bytes:
    hdr_len = 24
    length = hdr_len + len(payload) + 8
    h = b"DHAV" + bytes([ftype, 0, channel, 0]) + struct.pack("<III", 1, length, 0x5E0A1234)
    h += struct.pack("<H", 0) + bytes([0, 0])
    assert len(h) == 24
    return h + payload + b"dhav" + struct.pack("<I", length - 8)


def dahua(frames=5, noise=2000, bad_trailer=False) -> bytes:
    out = bytearray(filler(noise, 31))
    for i in range(frames):
        f = bytearray(dhav_frame(channel=i % 4))
        if bad_trailer:
            f[-4:] = struct.pack("<I", 7)
        out += f + filler(100, 40 + i)
    return bytes(out)


def honeywell_header(idr=True, length=31, ts_us=1_700_000_000_000_000) -> bytes:
    h = bytes([0x82 if idr else 0x02]) + b"\x80\x01\x00" + struct.pack("<HH", 1920, 1080)
    h += struct.pack("<I", length) + struct.pack("<Q", ts_us)
    assert len(h) == 20
    return h + b"\x00\x00\x00\x01" + H264_NAL


def honeywell(headers=5, machine=True, size=1 << 18) -> bytes:
    img = bytearray(filler(size, 51))
    if machine:
        img[34 * 512 : 34 * 512 + 10] = b"HN35080200"
    pos = 40 * 512
    for i in range(headers):
        blob = honeywell_header(idr=i == 0, ts_us=1_700_000_000_000_000 + i * 40_000)
        img[pos : pos + len(blob)] = blob
        pos += 4096
    return bytes(img)
