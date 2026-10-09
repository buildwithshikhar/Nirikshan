# Storage explorer (backend)

*Round D stream 2c. Code: `backend/app/explorer/`. Tests: `backend/tests/test_explorer.py` (reference images and hand-built MBR/GPT test images; no real disk).*

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/evidence/{id}/hex?offset=&length=` | bounded read-only bytes (hex + ASCII), `length` 1..4096, `offset` >= 0 and < image size (416 otherwise) |
| GET | `/api/evidence/{id}/regions?run_id=&scan_bytes=&max_regions=` | region map |
| GET | `/api/evidence/{id}/partitions` | MBR/GPT and file-system signatures |
| GET | `/api/evidence/{id}/anomalies?run_id=` | structural anomalies |

## Integrity gate for small reads

A full re-hash per 4 KiB page would re-read the whole image and custody-log every page. These endpoints use a **light gate** instead (`explorer/gate.py`): the evidence must be `acquired`, its **most recent full verification must have passed** (`last_verify_ok == 1`; set at acquisition, by `POST /api/evidence/{id}/verify` and by every analysis run, each custody-logged), and the stored copy must still have its recorded size and no write permission bit (it is made 0444 at acquisition). Otherwise HTTP 409. Every response carries the time of the last full verification.

**Limit:** the light gate does not prove that the bytes are unchanged since that verification (an attacker with filesystem access could change content and restore the mode). Re-verify before relying on a hex view in a report.

**Audit, not custody.** Each hex read is recorded in `raw_read_audit` (examiner, offset, length, SHA-256 of the returned bytes) and by the global API audit log; it is deliberately not a custody entry (reads change nothing).

## Region map

Computed from the selected (default: latest completed) analysis run plus a bounded scan. Precedence, highest first: `parser_clip` (vendor parser clips), `carved_clip` (generic), `orphan`, `structure` (vendor signature hits from the run's identification, with the signature's byte length; MBR sector; GPT header and entry array), then for the rest `zero` (all-zero 4 KiB blocks), `unknown` (scanned, not zero, unexplained) and `not_scanned` (beyond `scan_bytes`, default 64 MiB, max 1 GiB). Regions are contiguous and cover the whole image; `summary` gives bytes, region count and fraction per kind for all regions, the list is capped by `max_regions` (default 2000, max 10000, `truncated` flag).

Clip spans run from the first to the last payload extent, so vendor headers between payload extents lie inside them. The map says nothing about file-system allocation state ("unknown" is not "unallocated").

## Partition tables and file-system signatures

Only signatures from public specifications are checked. Nothing is mounted or walked; a signature match means the bytes look like the start of that structure.

| Structure | Check | Source |
|---|---|---|
| MBR | `55 AA` at 510; four 16-byte entries at 446 (boot indicator, type, starting LBA u32 LE, sector count u32 LE); type `0xEE` = protective MBR | UEFI Specification 2.10, section 5.2 (Legacy MBR, Protective MBR), https://uefi.org/specifications |
| GPT | `EFI PART` at LBA 1 (tried for 512- and 4096-byte sectors); header fields; header CRC32 over HeaderSize bytes with the CRC field zeroed; partition-entry-array CRC32; entries (type GUID, unique GUID, first/last LBA, attributes, UTF-16LE name); backup header at AlternateLBA | UEFI Specification 2.10, section 5.3 (GUID Partition Table) |
| GPT type names | only three well-known GUIDs are named: EFI System Partition (UEFI 2.10 table 5.7), Microsoft basic data, Linux filesystem data; all others "not interpreted" | UEFI 2.10; Microsoft and freedesktop.org Discoverable Partitions Specification GUID tables |
| ext2/3/4 | superblock at partition offset 1024, `s_magic` = `0xEF53` (LE) at superblock offset 0x38 (absolute +1080); `s_log_block_size` at 0x18 reported as block size | Linux kernel documentation, "ext4 Data Structures and Algorithms", The Super Block, https://docs.kernel.org/filesystems/ext4/ |
| NTFS | OEM ID `NTFS    ` at boot-sector offset 3 | NTFS boot sector layout (Microsoft NTFS boot-sector documentation; Linux-NTFS project documentation) |
| exFAT | FileSystemName `EXFAT   ` at offset 3 | Microsoft, exFAT file system specification, section 3.1.2 |
| FAT12/16/32 | BS_FilSysType at 54 (FAT12/16) or 82 (FAT32) | Microsoft, "FAT: General Overview of On-Disk Format" (fatgen103) |
| XFS | `XFSB` at superblock offset 0 | "XFS Algorithms & Data Structures", superblock `sb_magicnum` |

File-system signatures are checked at offset 0 and at every partition start. Vendor (proprietary) file systems are reported by the vendor parsers and device identification, not here.

## Anomalies

`/anomalies` merges, with a severity (`warning` or `info`) and the offset where one exists:

- parser `inconsistencies` (warning) and `warnings` (info) stored in the run's `parse_json`;
- parser-versus-generic cross-check disagreements stored in the run; `generic_includes_extra_bytes` and `frame_count_mismatch` are `info` (expected vendor-header absorption, the same benign set the validation harness uses), the rest `warning`;
- stored clips whose decode test reported errors or whose export failed (warning);
- partition-table anomalies: MBR invalid boot indicator, partition beyond the image, overlapping MBR partitions, protective MBR without GPT, GPT header CRC mismatch, entry-array CRC mismatch, MyLBA not 1, implausible or truncated entry array, partition beyond the image, negative length, backup header missing at AlternateLBA.

Nothing new is inferred: every item comes from a stored run or from a public-spec check.
