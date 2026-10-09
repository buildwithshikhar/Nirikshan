# Real DVR/NVR image search (2026-10-09, time-boxed)

## Conclusion
Real recorder image found (public, no account): NO. Nothing downloaded. Nothing under backend/data/real/ was created.

## Candidates
| Title | URL | Owner | Contains (verified?) | Licence | Size/format | No-account download | Real recorder image? |
|---|---|---|---|---|---|---|---|
| Honeywell-NVR-Filesystem-Tools (Yoon and Hwang, arXiv 2605.07430 / DFRWS USA 2026) | https://github.com/eraw1am/Honeywell-NVR-Filesystem-Tools | eraw1am (SKKU) | Verified via GitHub API: only README.md, compare_partition.py, dat_carving.py (a few KB), no releases. Tools only, no disk image. Paper has no data-availability statement. | none stated (not checked further) | KB | GitHub API 200, but no image | No (tools, not data) |
| Rzayeva et al., Information 2025, 16(11):983 | doi 10.3390/info16110983 | Rzayeva et al. | Paper (CC BY 4.0 per Crossref). MDPI page returned 403 to curl, so data availability statement NOT verified. No dataset link found in any search. | CC BY 4.0 (article only) | n/a | not verified | Unknown/no evidence |
| Dragonas et al. 2023/2024 (Hikvision, Dahua logs) | github.com/theAtropos4n6/HikvisionLogAnalyzer | Dragonas | Parser only (137 KB repo). No images in his repo list (10 repos checked). Thesis not found. | not checked | n/a | n/a | No |
| NIST NISTIR 8161 / 8172 (CCTV export profile) | https://doi.org/10.6028/NIST.IR.8172 | NIST | Report says it links sample exported MP4/H.264 files; PDFs downloaded (HTTP 200) but links are in compressed streams and I could not extract them. Exported video, not disk image. | NIST publication, public domain typical (not verified) | n/a | report 200 | No (exported video, URLs unverified) |
| NIST CFReDS (cfreds.nist.gov) | https://cfreds.nist.gov/ | NIST | Site returns 200; searches found no DVR/CCTV disk image entry. Not exhaustively browsed (JS site). | n/a | n/a | n/a | No evidence |
| Digital Corpora | https://digitalcorpora.org | Garfinkel et al. | Terms: freely available without prior authorization or IRB approval (snippet). No DVR/CCTV image found in search. | per site | n/a | n/a | No evidence |
| Zenodo API queries (DVR forensic disk image, NVR forensic, Dahua DHFS, Hikvision forensic, CCTV forensic dataset) | zenodo.org | various | 40 hits scanned by title: none is a DVR/NVR image. (BCF Disk Image, 4.5 GB, is unrelated generic forensics, not inspected.) | n/a | n/a | n/a | No |
| Han 2015, Sandeepa 2018, Yang 2015, IFIP "Data Recovery from Proprietary Formatted CCTV Hard Disks" | various | | Papers only; no dataset links found | | | | No |
| Amped validation datasets blog | blog.ampedsoftware.com | Amped | Image/video forensics datasets (VISION, LPR videos), no DVR images or .dav | | | | No |

Requires account (not used): Kaggle, IEEE DataPort, Mendeley Data were not searched into; none surfaced.

## Adjacent, not disk images
- No public sample .dav/DHAV files found (searches returned only format descriptions: fileinfo.com, docs.fileformat.com, PRONOM fmt/1851). Not verified that any host a sample.
- NIST 8172 sample exported MP4 files (unverified links).
- Dahua/Hikvision exploit repos (e.g. Nxychx/TVT-NVR, Unlicense) are PoCs, not data.

## Queries
WebSearch: DVR forensic disk image dataset Zenodo Dahua Hikvision CCTV; Dragonas DVR forensics dataset; Yoon Hwang 2605.07430; cfreds.nist.gov CCTV DVR; zenodo DHFS; sample .dav DHAV; Digital Corpora DVR/CCTV; Rzayeva data availability. Direct APIs: Zenodo records, GitHub repo/user/search.

## Read depth
arXiv 2605.07430 PDF: fetched (summarised, partial). Others: snippets only. DFRWS 2023/2026 PDFs, UCD PDF: not read in full (UCD binary unreadable).

## Caveats
Time-box and tooling (MDPI 403, no pdftotext) limited verification. Practical route: contact authors (Rzayeva, Yoon/Hwang, Dragonas) for images, or build own images from owned recorders.

Downloaded: nothing.
