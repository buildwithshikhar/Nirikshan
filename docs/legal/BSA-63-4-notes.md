# Notes on Section 63(4), Bharatiya Sakshya Adhiniyam, 2023 (not legal advice)

Purpose: record what we found while building the DRAFT certificate generator, and exactly what we could not confirm. Nirikshan asserts nothing about legal sufficiency. A lawyer must review any use.

## What we found (accessed 2026-10-09)

The official Gazette / India Code PDF (https://www.indiacode.nic.in/bitstream/123456789/20063/1/aa202347.pdf) answered HTTP 403 to our fetch tool, so **we did not read the official text**. All text below comes from third-party reproductions.

* Section 63(4) (reproduced at https://vidhijudicial.com/section-63-of-the-bharatiya-sakshya-adhiniyam,-2023.html): a certificate "shall be submitted along with the electronic record at each instance where it is being submitted for admission", (a) identifying the electronic record and describing the manner of production, (b) giving particulars of any device involved, (c) dealing with the conditions in sub-section (2), "purporting to be signed by a person in charge of the computer or communication device or the management of the relevant activities (whichever is appropriate) and an expert".
* The Schedule certificate (reproduced at https://www.advocatekhoj.com/library/bareacts/bharatiyaaakshya2023/b.php): Part A (party / person in charge) with name, relation, residence or place of employment, source (Computer, Storage media, DVR, Mobile, Flash drive, CD/DVD, Server, Cloud, Other), make and model, colour, serial number, IMEI/UIN/UID/MAC/Cloud ID, other information, and a hash line "The HASH value/s of the electronic/digital record/s is ____, obtained through the following algorithm: SHA1 / SHA256 / MD5 / Other"; Part B (expert) with a similar structure and the same hash line; date (DD/MM/YYYY), time (IST, 24 h) and place. The tool-read summary of that page said the hash line appears in both parts.
* Supreme Court, reported as Pune Bar Association v. Union of India, 2026 SCC OnLine SC 1297, three-judge bench, 22 May 2026 (https://www.scconline.com/blog/post/2026/07/08/sc-upholds-admissibility-of-electronic-evidence-under-section-63-4-bsa/): the hash value is described as an electronic fingerprint; the requirement was upheld; a Section 79A notified examiner may sign Part B but the requirement is not exclusive to such examiners. We have not read the judgment itself.
* Other sources consulted, all secondary: https://www.livelaw.in/articles/bharatiya-sakshya-adhiniyam-transformed-digital-evidence-552681, https://blog.ipleaders.in/electronic-evidence-under-the-bsa-2023/, https://ksandk.com/litigation/section-63-bharatiya-sakshya-adhiniyam-2023/, https://bhattandjoshiassociates.com/... (HTTP 522, not read).

## Not confirmed

1. The official wording, order and numbering of the Schedule fields (we saw reproductions only, summarised by a fetch tool, not verbatim).
2. Which Schedule fields are mandatory.
3. Who must sign Part A and Part B in a given case, and what qualifies as an "expert". Sources disagree on where the hash belongs (Part A only, or both parts); the draft puts it in both so the examiner can delete one.
4. Whether MD5 is acceptable in practice (the Schedule lists it as an option in the reproductions we saw).
5. Whether anything Nirikshan records (hashes, acquisition steps, custody chain) would satisfy a court. The tool makes no such claim.
6. Whether the 2026 Supreme Court summary above is accurate; verify against the judgment.

## What the generator does

Pre-fills image MD5 and SHA-256, label, source, acquisition time and examiner, write-blocker attestation (marked unverified), custody chain state, tool version. Leaves identity, device particulars, manner of production, statements on Section 63(2), the expert's statement, dates and signatures blank. Every page carries the banner "DRAFT for examiner and legal review, not legal advice. Nirikshan does not assert that this satisfies Section 63(4)." The generator is a drafting aid only.
