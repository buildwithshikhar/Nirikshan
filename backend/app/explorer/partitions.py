"""Partition-table and file-system signature detection from public specifications only.

Sources (docs/storage-explorer.md lists them with what each states):
  [UEFI]  UEFI Specification 2.10, section 5.2 (legacy MBR / protective MBR) and 5.3 (GPT header
          at LBA 1 with signature "EFI PART", header and entry-array CRC32, partition entries).
  [EXT4]  Linux kernel documentation, "ext4 Data Structures and Algorithms", super block:
          s_magic 0xEF53 at superblock offset 0x38; the superblock starts at byte 1024.
  [FAT]   Microsoft "FAT: General Overview of On-Disk Format" (fatgen103): BS_FilSysType at 54
          (FAT12/16) and 82 (FAT32), boot sector signature 0x55AA at 510.
  [NTFS]  NTFS boot sector OEM ID "NTFS    " at offset 3 (as documented by the Linux-NTFS
          project's NTFS documentation and Microsoft's boot-sector descriptions).
  [EXFAT] Microsoft "exFAT file system specification", 3.1.2 FileSystemName "EXFAT   " at 3.
  [XFS]   "XFS Algorithms & Data Structures", superblock sb_magicnum "XFSB" at offset 0.
Only signatures are checked; no file system is mounted or walked. A signature match says the
bytes look like the start of that structure, nothing more.
"""

import struct
import uuid
import zlib

# Well-known GPT partition type GUIDs (UEFI 2.10 table 5.7 for the ESP; the others are the
# published Microsoft basic data and Linux filesystem data GUIDs).
GPT_TYPES = {
    "c12a7328-f81f-11d2-ba4b-00a0c93ec93b": "EFI System Partition",
    "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7": "Microsoft basic data",
    "0fc63daf-8483-4772-8e79-3d69d8477de4": "Linux filesystem data",
}
MBR_TYPES = {
    0x00: "empty",
    0xEE: "GPT protective",
    0x07: "NTFS/exFAT/IFS",
    0x0B: "FAT32 CHS",
    0x0C: "FAT32 LBA",
    0x83: "Linux",
    0x05: "extended CHS",
    0x0F: "extended LBA",
}
MAX_GPT_ENTRIES = 1024
SECTOR_SIZES = (512, 4096)


def _rd(f, off: int, n: int, size: int) -> bytes:
    if off < 0 or off >= size or n <= 0:
        return b""
    f.seek(off)
    return f.read(min(n, size - off))


def fs_signatures(f, base: int, size: int) -> list[dict]:
    """File-system signatures at `base` (a partition start or the image start)."""
    out = []
    boot = _rd(f, base, 512, size)
    sb = _rd(f, base + 1024, 1024, size)

    def hit(name, off, source, note=""):
        out.append({"fs": name, "offset": off, "source": source, "note": note})

    if len(sb) >= 0x3A and sb[0x38:0x3A] == b"\x53\xef":
        log_bs = struct.unpack_from("<I", sb, 0x18)[0]
        note = (
            f"block size {1024 << log_bs} bytes" if log_bs < 8 else "block size field out of range"
        )
        hit(
            "ext2/3/4",
            base + 1080,
            "[EXT4] s_magic 0xEF53",
            note + "; revision/features not interpreted",
        )
    if boot[3:11] == b"NTFS    ":
        hit("NTFS", base + 3, "[NTFS] OEM ID")
    if boot[3:11] == b"EXFAT   ":
        hit("exFAT", base + 3, "[EXFAT] FileSystemName")
    if boot[82:90] == b"FAT32   ":
        hit("FAT32", base + 82, "[FAT] BS_FilSysType (FAT32)")
    if boot[54:62] in (b"FAT12   ", b"FAT16   ", b"FAT     "):
        hit(boot[54:62].decode().strip(), base + 54, "[FAT] BS_FilSysType (FAT12/16)")
    if boot[:4] == b"XFSB":
        hit("XFS", base, "[XFS] sb_magicnum")
    return out


def _mbr(f, size: int, anomalies: list) -> dict | None:
    s0 = _rd(f, 0, 512, size)
    if len(s0) < 512 or s0[510:512] != b"\x55\xaa":
        return None
    parts = []
    for i in range(4):
        e = s0[446 + 16 * i : 462 + 16 * i]
        status, ptype = e[0], e[4]
        lba, count = struct.unpack_from("<II", e, 8)
        if ptype == 0 and lba == 0 and count == 0:
            continue
        p = {
            "index": i,
            "status": f"0x{status:02X}",
            "type": f"0x{ptype:02X}",
            "type_name": MBR_TYPES.get(ptype, "other (not interpreted)"),
            "first_lba": lba,
            "sectors": count,
            "start_offset": lba * 512,
            "end_offset": (lba + count) * 512,
        }
        if status not in (0x00, 0x80):
            anomalies.append(
                {
                    "kind": "mbr_invalid_status",
                    "entry": i,
                    "detail": p["status"],
                    "source": "[UEFI] 5.2.1: boot indicator 0x00 or 0x80",
                }
            )
        if ptype != 0xEE and p["end_offset"] > size:
            anomalies.append(
                {
                    "kind": "mbr_partition_beyond_image",
                    "entry": i,
                    "offset": p["start_offset"],
                    "detail": f"ends at {p['end_offset']}",
                }
            )
        parts.append(p)
    ordered = sorted((p for p in parts if p["type"] != "0xEE"), key=lambda p: p["start_offset"])
    for a, b in zip(ordered, ordered[1:], strict=False):
        if b["start_offset"] < a["end_offset"]:
            anomalies.append(
                {
                    "kind": "mbr_partitions_overlap",
                    "entry": b["index"],
                    "offset": b["start_offset"],
                    "detail": f"overlaps entry {a['index']}",
                }
            )
    return {
        "signature_offset": 510,
        "protective": any(p["type"] == "0xEE" for p in parts),
        "partitions": parts,
        "source": "[UEFI] 5.2 legacy MBR",
    }


def _gpt_header(raw: bytes) -> dict | None:
    if len(raw) < 92 or raw[:8] != b"EFI PART":
        return None
    (rev, hsize, hcrc, _r, my, alt, first, last) = struct.unpack_from("<IIIIQQQQ", raw, 8)
    disk = uuid.UUID(bytes_le=raw[56:72])
    ent_lba, n, esize, ecrc = struct.unpack_from("<QIII", raw, 72)
    ok_hsize = 92 <= hsize <= len(raw)
    calc = None
    if ok_hsize:
        h = bytearray(raw[:hsize])
        h[16:20] = b"\x00\x00\x00\x00"
        calc = zlib.crc32(bytes(h)) & 0xFFFFFFFF
    return {
        "revision": f"0x{rev:08X}",
        "header_size": hsize,
        "header_crc32": f"0x{hcrc:08X}",
        "header_crc32_ok": calc == hcrc,
        "my_lba": my,
        "alternate_lba": alt,
        "first_usable_lba": first,
        "last_usable_lba": last,
        "disk_guid": str(disk),
        "entries_lba": ent_lba,
        "entry_count": n,
        "entry_size": esize,
        "entries_crc32": f"0x{ecrc:08X}",
        "_ecrc": ecrc,
    }


def _gpt(f, size: int, anomalies: list) -> dict | None:
    for ss in SECTOR_SIZES:
        hdr = _gpt_header(_rd(f, ss, ss, size))
        if hdr is None:
            continue
        src = "[UEFI] 5.3.2 GPT header"
        if not hdr["header_crc32_ok"]:
            anomalies.append({"kind": "gpt_header_crc_mismatch", "offset": ss, "source": src})
        if hdr["my_lba"] != 1:
            anomalies.append({"kind": "gpt_my_lba_not_1", "offset": ss, "detail": hdr["my_lba"]})
        parts = []
        n, esize = hdr["entry_count"], hdr["entry_size"]
        if not (128 <= esize <= 4096 and esize % 8 == 0) or n > MAX_GPT_ENTRIES:
            anomalies.append(
                {
                    "kind": "gpt_entry_array_implausible",
                    "offset": ss,
                    "detail": f"{n} entries of {esize} bytes (not read)",
                }
            )
        else:
            arr_off = hdr["entries_lba"] * ss
            arr = _rd(f, arr_off, n * esize, size)
            if len(arr) < n * esize:
                anomalies.append({"kind": "gpt_entry_array_truncated", "offset": arr_off})
            elif zlib.crc32(arr) & 0xFFFFFFFF != hdr["_ecrc"]:
                anomalies.append(
                    {
                        "kind": "gpt_entries_crc_mismatch",
                        "offset": arr_off,
                        "source": "[UEFI] 5.3.2 PartitionEntryArrayCRC32",
                    }
                )
            for i in range(len(arr) // esize):
                e = arr[i * esize : (i + 1) * esize]
                if e[:16] == bytes(16):
                    continue
                t = str(uuid.UUID(bytes_le=e[:16]))
                first, last, attrs = struct.unpack_from("<QQQ", e, 32)
                name = e[56:128].decode("utf-16-le", "replace").split("\x00")[0]
                p = {
                    "index": i,
                    "type_guid": t,
                    "type_name": GPT_TYPES.get(t, "not interpreted"),
                    "unique_guid": str(uuid.UUID(bytes_le=e[16:32])),
                    "first_lba": first,
                    "last_lba": last,
                    "attributes": f"0x{attrs:016X}",
                    "name": name,
                    "start_offset": first * ss,
                    "end_offset": (last + 1) * ss,
                }
                if p["end_offset"] > size:
                    anomalies.append(
                        {
                            "kind": "gpt_partition_beyond_image",
                            "entry": i,
                            "offset": p["start_offset"],
                            "detail": f"ends at {p['end_offset']}",
                        }
                    )
                if last < first:
                    anomalies.append(
                        {
                            "kind": "gpt_partition_negative_length",
                            "entry": i,
                            "offset": p["start_offset"],
                        }
                    )
                parts.append(p)
        alt = hdr["alternate_lba"] * ss
        backup = "outside image"
        if 0 < alt < size:
            backup = "present" if _rd(f, alt, 8, size) == b"EFI PART" else "missing"
            if backup == "missing":
                anomalies.append(
                    {
                        "kind": "gpt_backup_header_missing",
                        "offset": alt,
                        "source": "[UEFI] 5.3.1 backup GPT header at AlternateLBA",
                    }
                )
        hdr.pop("_ecrc")
        return {
            "sector_size": ss,
            "header_offset": ss,
            "header": hdr,
            "backup_header": backup,
            "partitions": parts,
            "source": src,
        }
    return None


def detect(f, size: int) -> dict:
    anomalies: list[dict] = []
    mbr = _mbr(f, size, anomalies)
    gpt = _gpt(f, size, anomalies)
    if mbr and mbr["protective"] and gpt is None:
        anomalies.append(
            {
                "kind": "protective_mbr_without_gpt",
                "offset": 0,
                "source": "[UEFI] 5.2.3 protective MBR implies a GPT",
            }
        )
    starts = sorted(
        {p["start_offset"] for p in (gpt or {}).get("partitions", [])}
        | {p["start_offset"] for p in (mbr or {}).get("partitions", []) if p["type"] != "0xEE"}
    )
    filesystems = []
    for base in [0] + [s for s in starts if 0 < s < size]:
        for h in fs_signatures(f, base, size):
            filesystems.append({"partition_start": base, **h})
    return {
        "mbr": mbr,
        "gpt": gpt,
        "filesystems": filesystems,
        "anomalies": anomalies,
        "scheme": "gpt" if gpt else "mbr" if mbr else "none detected",
        "note": "Signatures from public specifications only (docs/storage-explorer.md); "
        "vendor file systems are reported by the vendor parsers, not here.",
    }
