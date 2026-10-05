# Real-Image Playbook: Creating a Ground-Truth Image from a Real DVR/NVR

*Audience: the Nirikshan team members who will buy or borrow a recorder, create a disk image with known contents, and use it to settle open parser questions and to support a tier promotion.*

Why this exists: **no real DVR/NVR image has ever been examined by Nirikshan.** All parsers are Tier B, built from papers, and checked only against synthetic layouts built from the same papers (a circular check). This playbook produces the first independent evidence. It follows the promotion rule in `IMPLEMENTATION_PLAN.md` (B to A: at least 2 real images from at least 1 model, ground truth we created, imaged read-only, results reported with numbers) and the "to verify on real images" list in `docs/RESEARCH.md` section 9. Handling steps were written with reference to SWGDE 17-V-002-1.4 (page read) and NIST SP 800-86 (read); not audited against any standard.

Use only equipment and footage you own or have permission to record. Do not record people who have not consented. Images are large and sensitive: **never commit them** (section 9).

## 1. Preparation (before recording anything)

1. **Fix the plan.** Choose the model(s) (see `HARDWARE_SHOPPING.md`). Plan **two images per model** (the promotion rule needs 2), ideally with different configurations (for example one with the DVR time zone set to UTC+5:30 and one to UTC, so the time-basis question is separable).
2. **Record the recorder facts** in a lab notebook or a shared sheet (photograph each screen):
   - Make, model number, serial, hardware version, **firmware version** and build date (from the device's information screen).
   - Disk model and serial, capacity; whether the disk is new, formatted by the recorder, or previously used.
   - **Time settings**: configured time zone, DST on/off and rule, NTP on/off and server, date and time format, current displayed time.
   - Recording settings: channels used, stream type (main/sub), resolution, frame rate, codec (H.264/H.265/"smart" codec), recording mode (continuous/motion), overwrite on/off, any encryption or password feature **off** for the first image (encrypted recordings are untested; make a separate encrypted image later if desired).
3. **Choose the NTP reference.** A phone or laptop synchronised to NTP; note its source. Disable the recorder's NTP for at least one image so its clock is allowed to differ from the reference (a measurable offset is useful). Do not change the recorder's clock during the recording session once started (SWGDE practice).
4. **Clock evidence.** At the start and end of every recording session, photograph the **recorder's displayed clock next to the reference clock** in one shot, with the reference device identifiable. Record both readings and the real moment.
5. **Camera or feed.** Use a camera that sees a **screen showing a large clock with seconds and the true date** (NTP-synchronised), plus a distinct scene marker per channel (a printed channel number card). The footage then carries its own ground truth for the OSD-versus-metadata comparison.
6. **Lab hygiene.** Use a dedicated disk; label it; keep a written chain-of-custody sheet from this point (who handled the disk, when).

## 2. Recording with a written schedule

Write the schedule **before** you start, and do not deviate without noting it.

1. Record N clips (suggest N >= 12 per channel set, short, 2 to 5 minutes, with gaps of a few minutes) on known channels at known true times. Include a mix: continuous recording, recording started and stopped manually, and (if the model supports it) an event or motion recording.
2. Use at least 2 channels with different scenes (printed channel cards) so channel attribution can be checked.
3. Fill the ground-truth log (section 6) **as you go**: clip id, channel, scene, true start and end from the reference clock.
4. If you want to test a DST boundary or a time-zone change, do it as a separate, named experiment, never mid-image without noting it.

## 3. Deletion scenarios (state exactly which one you did)

Each scenario produces a different on-disk state and must be a **separate image** or a clearly ordered step with an image after each step.

| Scenario | Action on the recorder | What it tests |
|---|---|---|
| S0 baseline | None; disk contains only live recordings | Clean parsing, timestamp fields, channel attribution |
| S1 manual delete | Delete selected clips via the recorder's menu if the model offers it (Hikvision's design has no per-file delete per Han 2015 [S1]; record what the UI offers) | Behaviour of metadata after a user delete |
| S2 format / initialise | Format or initialise the disk from the menu | Cleared metadata with intact video (the case that blinds the Hikvision parser); Honeywell "format" (paper rates recoverability Medium [S5]) |
| S3 overwrite | Fill the disk (or use a small disk and long recording) until the recorder overwrites the oldest data, with overwrite enabled | Overwrite behaviour; Honeywell "overwrite" and "expiration" modes [S5]; Hikvision wrap-around indicators [S1] |
| S4 clear logs | Clear logs from the menu | Log recovery (Dahua SQLite, Hikvision RATS) |

Record, in the ground-truth log, **when** each deletion was done (true time) and exactly what was selected.

## 4. Powering down, removing the disk, imaging

1. Stop all recording; note the true time; photograph the clock pair once more.
2. **Shut the recorder down through its menu** (do not pull power), photograph the shutdown screen, then remove the disk. Never reconnect the disk to the recorder after imaging (Han 2015 warns reconnecting damages integrity).
3. **Write blocking.** Hardware write blocker preferred. A SATA-USB dock with a "write-protect" feature is **not assumed to block writes; its behaviour is unverified until you test it** (section 4.1). Use a Linux or macOS host with automount disabled, so the OS does not mount or write anything.
4. **Hash before.** If the blocker passes through the whole disk, compute SHA-256 of the entire device (`shasum -a 256 /dev/rdiskN` on macOS, `sha256sum /dev/sdX` on Linux) and record it, the byte count and the time.
5. **Image** with a standard tool (for example `dd` or `ddrescue` on Linux; `dd` with `bs=4m` on macOS) to a raw file on a different disk with enough space. Record the command line verbatim.
6. **Hash after.** Hash the device again and the image file; the device hash before, device hash after and image hash must be equal. Any difference stops the procedure: note it and re-check cabling and the disk.
7. Make the image file read-only (`chmod 444`); store a second copy on separate media; record where.

### 4.1 Testing a dock for write protection (do this once per dock, on a sacrificial disk, never the evidence disk)
1. Take a spare disk you do not need. Write a known pattern to it **directly** (not through the dock), compute its SHA-256 (hash A).
2. Connect it through the dock in the write-protected mode you intend to use. Without any imaging, try to write: mount it read-write if the OS allows and create a file, and/or `dd` a few KB over a known offset. Record each error message.
3. Disconnect, reconnect **directly** and compute SHA-256 again (hash B).
4. If B equals A and the write attempts failed, the dock blocked those specific writes in that mode on that host. If B differs, the dock does **not** protect; do not use it for evidence.
5. As a control, repeat the write attempt with the dock's protection off (or a direct connection) and confirm that the write **succeeds** and changes the hash; otherwise the test cannot detect a failure.
6. The result is valid for that dock, firmware, host OS and mode only. It is not a substitute for a hardware write blocker's own certification. Record the test in the lab notebook.

## 5. Acquire in Nirikshan and analyse

1. Copy the image into a folder listed in `NIRIKSHAN_EVIDENCE_ROOTS`.
2. Create a case; **Acquire** the image; set the **write-blocker attestation** to exactly what is true (`yes` only if a hardware blocker or a dock that passed section 4.1 was used; otherwise `no` or `unknown`). The tool does not verify it.
3. Check that Nirikshan's SHA-256 equals your image hash. Record both hashes and the case `head_hash` externally (SOP-01, SOP-02).
4. Run **Identify + carve** with default settings first (SOP-03), then with each parser option variation listed in section 7. Keep every run.
5. Save the analysis run export and the ground-truth log. Compare per clip (section 8).

Do **not** tune parser code against an image and then report results on the same image as validation. Settle conflicts (section 7), then score on a **second** image that was not used for tuning.

## 6. Ground-truth log template

One row per clip or event. Times are true times from the reference clock (UTC and local, with the zone stated).

| Clip id | Channel | Camera scene | True start (UTC) | True end (UTC) | Recorder-displayed start (as shown) | Deleted? (method per section 3) | Deleted at (true) | Expected recoverable? (why) | Recovered by Nirikshan? (engine, run id, clip id) | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C01 | 1 | channel card "1" + clock | | | | no | | yes | | |
| C02 | 2 | channel card "2" + clock | | | | S2 format | | video likely intact, metadata cleared | | |
| ... | | | | | | | | | | |

Also keep a header block per image: model, serial, firmware, disk, time zone and DST setting, NTP state, photo file names, device and image hashes, tool version and commit, scenario (S0 to S4).

"Expected recoverable?" must be written **before** running the tool, with the reason.

## 7. Checklist: resolving the open source conflicts

For each item record: observation, conclusion (settled / unsettled / not observable), image id, evidence (hex dump saved under `docs/` only if it contains no personal data; otherwise offsets and short excerpts). Parser option names are as implemented; options never change a conclusion, they only choose which interpretation the parser applies and echo it in results.

| # | Question (source conflict) | Exact observation that settles it | Where the parser option lives |
|---|---|---|---|
| H1 | **Hikvision data-block size**: 0x400000 (4 MiB) vs 1 GB (0x40000000), Han 2015 internal inconsistency | Read the Master Sector block-size field from the image (Master Sector bytes; `block_size_conflict_in_source` and `block_size_used` are emitted in the parser fields). Then check geometry: for a real image, `video_area_offset + block_count * size` must land at HIKBTREE1; find the real spacing between block starts (distance between video-block headers/`OFNI` tables or the offsets in HIKBTREE entries). The value whose geometry fits settles it | Parser option `block_size_mode` = `field` (default) / `0x400000` / `1gib`, passed as `{"Hikvision": {"block_size_mode": "1gib"}}` |
| H2 | **Hikvision UTC vs local** (Han: UTC for Master/HIKBTREE; Dragonas: local for log records) | With the recorder's zone known (section 1) and the true recording times in your log, compare the **raw epoch integers** in HIKBTREE entries, Master Sector init time, and RATS record times with the true times: the difference equals 0 (UTC) or the zone offset (local) for each field separately. Use two images with different zone settings to be sure. Account for any recorder clock offset measured by the clock photo | `time_basis_label` (`unspecified`/`utc`/`local`) **only relabels** `tz_basis`; it does not change values. The conclusion belongs in SOP-04 and the parser docs, not in an option |
| H3 | **Master Sector at 0x200 vs 0x210** | Look at the bytes at 0x200 to 0x21F on the real disk: which offset starts `HIKVISION@HANGZHOU` (48 49 4B 56 49 53 49 4F 4E 40 48 41 4E 47 5A 48 4F 55)? Note any pre-signature bytes (`86 21 00 00...` seen by Dragonas) and whether a partition table or GPT precedes it | `master_sector_offset` = `auto` (default) / `0x200` / `0x210` |
| H4 | **HIKBTREE page layout**: entry stride (48 from a figure), first-entry offset in a 4 KB page, page-list slot stride (8 or 16), next-page field position; the parser picks by plausibility | Dump a HIKBTREE page of a real image. Record: offset of the first 48-byte entry; whether entries really repeat at 48 bytes; the existence flag (00 / FF), channel, start/end epoch and block offset per entry; where the next-page field sits; what the page list slots look like. Verify each entry's block offset points at real video (`00 00 00 01 67`/`65` after the block start) | `btree_first_entry_offset` = `auto` (0 to 0x40, 8-byte aligned, most plausible) or an explicit offset; the stride and page-list stride are not options (code change if they differ) |
| H5 | **Hikvision cleared entries hide intact video** (parser blind spot) | After S2 (format/initialise) or S3, compare video found by the generic carver with clips explained by HIKBTREE entries. The cross-check kind `generic_clip_not_explained_by_parser` lists them. Confirm by decoding those clips and matching the footage to your ground-truth log. Record how an overwritten block's entry looks (`FF FF FF 7F 00 00 00 00` times, existence flag) | No option. The production pipeline already carves uncovered ranges generically; result lives in the cross-check output |
| W1 | **Honeywell header length semantic**: does the 4-byte length at header bytes 8-11 cover one NAL or the whole access unit (SPS+PPS+IDR under one 0x82 header)? | In a real image, take a 0x82 header followed by `00 00 00 01 67` (SPS). Compute where the next 20-byte header begins and compare with `header_offset + 20 + length`: equal means the length spans the whole access unit; if the next header begins right after the SPS, it is per NAL. Check also the bytes 4-7 resolution and the endianness of the length | No option. The parser accepts a frame only when length lands on the next header, the delimiter or the image end; a different semantic shows as `fallback` |
| W2 | **Honeywell 20-zero-byte delimiter ambiguity** (zeroed data vs real "End of Channel Data") | Find delimiters in real data and look at what follows (padding byte after the delimiter is documented as unknown). Check on an S2/S3 image whether zero-filled areas without a real delimiter occur and how the parser's `end_reason` reports them | No option; `end_reason` in the parser result states the ambiguity |
| D1 | **Dahua frame_number tolerance** (the demultiplexing check; Rzayeva's abstract reports +/-3, not read in full) | On a multi-channel recording, take the DHAV frame numbers per channel across a recording: the largest legitimate delta between consecutive frames of one channel (including dropped frames) and what happens at wrap-around. Decide whether 3 is adequate | `frame_gap_tolerance` (default 3) in `{"Dahua": {"frame_gap_tolerance": 3}}` |
| D2 | **Dahua header checksum byte** (byte 23; algorithm undocumented) | For many real DHAV frames, test candidate algorithms over header bytes 0 to 22 (and variants); the one that matches all frames settles it. Document the frames used | No option; the parser does not verify the byte today |
| D3 | **DHFS layout** (currently unparsed; no primary source read) | Dump the first MiB of a real Dahua disk: partition table (DHFS first, XFS second on some XVRs per Dragonas), the DHFS superblock/magic, index structures, how DHAV frames are located. Write the fields down in a new `docs/parsers/dahua-fields.md` with offsets and hex excerpts, marked as observed from one device | None; new parser work |
| G1 | **Does the DHAV `DAHUA` 0x400 prefix occur inside DHFS or only in exported files?** | Search the image for `DAHUA` and `DHAV` and record where each occurs | None |
| G2 | **H.265 layout** per vendor | Record a short H.265 session (if the model supports it) and locate its headers/prefix bytes per vendor | None; currently H.265 clips are orphans in vendor parsers |

## 8. How results feed tier promotion

Record per image:

| Metric | How to compute |
|---|---|
| Clip recall (parser, generic, parser-first pipeline) | Ground-truth clips with "expected recoverable = yes" that were recovered (>= 50% of recoverable frames; the same definition as `docs/VALIDATION.md`) divided by those expected |
| Clip precision | Carved clips overlapping genuine footage divided by carved clips (decode and watch each clip against the ground-truth log) |
| Byte-exact | Only where ground truth at byte level exists (for example by comparing with a clip exported by the recorder in its native format) |
| Timestamp error | Parser raw time, interpreted per the settled basis, minus the true time; report median, maximum and the basis assumed |
| Channel accuracy | Share of clips with the correct channel where a parser reports one |
| Conflicts | Each checklist item settled / unsettled / not observable |

Rules (from the plan): C to B needs a documented signature and an identification test against a real image; **B to A needs at least 2 real images of at least 1 model with ground truth we created, read-only imaging, hashes before and after, and recall, precision and timestamp error reported with numbers**; a second model or firmware strengthens the claim; claims are per model, never per brand. If a parser could not be validated, the tier stays B and the result is reported as it is, including failures. Update `docs/VALIDATION_REPORT.md` section 9 with the results table below and revise the OEM comparison.

Results table template:

| Vendor | Model / firmware | Image id (scenario) | N clips (ground truth) | Expected recoverable | Recovered: parser / generic / pipeline | Precision | Timestamp error median / max (basis) | Channel accuracy | Conflicts settled | Tier outcome |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |

## 9. What to commit and what not to

- **Never commit**: disk images, exported clips, photographs of people or locations, case databases, signing keys, evidence directories, device serials if the device is not yours.
- **May commit** (after review for personal data): the ground-truth log without personal data, the checklist results, short hex excerpts of structures (headers, signatures) saved under `docs/`, parser-field documents updated from observation, results tables, the image and run hashes, tool versions.
- Keep images and photographs on encrypted, access-controlled storage with the chain-of-custody sheet; keep the signing key separate (SOP-02).
- Before any commit run a search for IP addresses, user names, serial numbers and GPS metadata in what you are about to add.

## 10. Safety and scope notes

- Do not use the recorder's network features for evidence; keep the lab network isolated or off (security of recorders is a known concern; see `HARDWARE_SHOPPING.md` on certification status in India).
- A real image may contain firmware versions that behave differently from the papers: the correct result is then "papers do not apply to this firmware", which is valuable and should be recorded as such.
