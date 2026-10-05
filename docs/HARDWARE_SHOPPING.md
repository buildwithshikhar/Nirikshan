# Hardware Shopping List for Real Ground-Truth Images (DRAFT)

*Audience: the Nirikshan team and whoever approves a small equipment purchase to create the first real DVR/NVR disk images.*

Purpose: a lean bill of materials for the procedure in [REAL_IMAGE_PLAYBOOK.md](REAL_IMAGE_PLAYBOOK.md), with what each choice lets us validate. **No purchase has been made and nothing here is a recommendation to buy a specific listing.** Prices are given **only** where a cited, dated source shows them; otherwise the text says "price not verified". There are no affiliate links. Web research was done on 2026-10-05; most retail pages gave no listing date, so no price from them is reproduced.

## 1. Bill of materials

| # | Item | Quantity | Selection criteria | What it lets us validate | Price |
|---|---|---|---|---|---|
| 1 | **Hikvision recorder**, DS-72xx/DS-76xx family (the 2015 paper tested DS-7204HVI-SV [S1]) | 1 (2 images per model needed for promotion) | Prefer a unit whose firmware is known and can be recorded; analog/TVI/AHD DVR types match the paper's DVR generation; note NVR/XVR generations are undocumented | Hikvision B to A (needs 2 images of 1 model); conflicts H1 to H5 in the playbook | price not verified |
| 2 | **Dahua recorder**: the Dragonas thesis names the tested units: NVR2108-4KS2, DHI-HCVR514C-S3, DH-XVR5216AN-4KL-I2, DH-XVR5104HS-I3 [S2]; XVR41xx/51xx families are the closest relatives | 1 | Prefer one of the thesis models or a close XVR sibling; check which disk layout it uses (DHFS only vs DHFS + XFS) | Dahua DHAV/DHFS: D1 to D3, G1 in the playbook; DHFS documentation (new) | price not verified |
| 3 | **Honeywell NVR**, HN35080200 (the only documented model [S5]) with PoE cameras HN40E-2030I per the paper | 1 if purchasable | The paper's exact model gives the only chance to test against its figures | Honeywell B to A; W1, W2 | price not verified |
| 4 | **CP Plus recorder** (Tier C exploration), e.g. a UVR 8-channel DVR | 1 | Cheapest unit that is clearly an Indian-market CP Plus; record the exact model and firmware | Whether any DHFS/DHAV or other signature appears; C to B only if a documented signature is found and tested | price not verified |
| 5 | **Small used HDD** | 2 per recorder (one image per scenario) or 1 reused after wiping with the recorder | 160 GB to 500 GB, SATA 3.5 inch, matching the recorder's compatibility list; record model, serial and SMART data. Smaller disks let the overwrite scenario complete in practical time. Arithmetic (ours): a 250 GB disk at one 4 Mbit/s stream takes about 5.8 days to fill, at eight such streams about 17 hours | Overwrite (S3) and format (S2) scenarios; fast imaging and hashing | price not verified |
| 6 | **Write blocker**, hardware, SATA | 1 | Preferred. Obtain the vendor's test or certification statement if any; do not assume | Defensible acquisition for the Tier A claim | price not verified |
| 7 | **SATA-USB dock** or adapter | 1 | Acceptable only after the dock test in the playbook section 4.1 (hash a sacrificial disk before and after write attempts, with a positive control) | Imaging path if no blocker; the dock's protection is **unverified until tested** | price not verified |
| 8 | **Camera(s) or test feed** | 2 channels minimum | A camera pointed at a screen showing an NTP-synchronised clock with seconds, plus a printed channel number card per channel. For analog DVRs a CVBS/AHD camera; for NVRs a PoE IP camera. If cameras are not purchasable, a test-pattern or looping video source into the recorder via an adapter | Ground truth for OSD versus metadata time; channel attribution | price not verified |
| 9 | **NTP reference** | 0 extra | A phone or laptop synchronised to NTP, noted by name; optionally a GPS/NTP time source if the lab has one | Clock offset for the time-basis questions (H2, SOP-04) | n/a |
| 10 | **Large storage** for images | 1 | Encrypted external disk, at least 2 times the sum of image sizes; second copy on separate media | Storage of evidence images (never committed) | price not verified |
| 11 | **Cabling and power** | as needed | SATA data and power cables, a UPS or surge protector, an isolated network switch for NVR use | Reliable recording and clean shutdown | price not verified |

## 2. Purchase order (suggested)
1. One Hikvision DVR of the paper's generation (the most documented target; settles three source conflicts).
2. One Dahua recorder from the thesis list (strongest container documentation, DHFS unknown).
3. Disks, write blocker or tested dock, camera/feed (needed for all).
4. Honeywell HN35080200 and CP Plus only if budget and availability allow.

## 3. Availability in India (what we found)

| Item | Finding | Confidence |
|---|---|---|
| Hikvision DS-7208HQHI-F2 (8-channel Turbo HD DVR) | Listed on Moglix (Prama Hikvision India Pvt. Ltd., Mumbai, shown as manufacturer/packer) as "available on request". The page showed an MRP, but gave no listing date, so it is not reproduced here. **Listing seen on 2026-10-05; actual availability was not tested.** | Medium for existence of a listing; none for stock |
| Hikvision DS-7204HVI-SV (the paper's model) | No current listing found. Search results turned up Hikvision discontinuation notices for other DS-7200 models (UK reseller blog), not this model. Likely old; treat as hard to obtain and plan with a current family instead | Low |
| Hikvision generally | IndiaMART pages list many resellers of Hikvision DVRs (search result snippets only, not opened) | Low |
| Dahua DH-XVR4108HS | Listed on an Airtel Infibeam page as "Coming Soon" (search summary; page not opened). IndiaMART directories list Dahua DVR sellers (snippets only) | Low |
| Dahua models named in the thesis | No India listing checked | Not assessed |
| Honeywell HN35080200 | Listed by UK retailers (networkwebcams.co.uk, use-ip.co.uk; pages returned 403 to our fetch tool, so only search snippets were seen; the listings describe an 8-channel 8MP H.265 NVR with built-in PoE, diskless, NDAA compliant). **No Indian listing found.** | Low (UK); none (India) |
| CP Plus CP-UVR-0801E1-CS (8-channel DVR, H.264) | Listed on an IndiaMART seller page (Saksham Technologies, Mathura) and on other IndiaMART, L&T-SuFin and IndustryBuying pages found by search. The seller page gave a price but no listing date, so it is not reproduced | Medium for the listing |

Honeywell note: the paper's model description (H.265 smart codec, PoE) comes from retailers' listings via snippets; the paper tested H.264 only [S5].

## 4. Indian certification context (UNVERIFIED unless stated)

A secondary source mentioned 2026 STQC/BIS/CCTV rules; whether they hold is checked here. What we found:

1. **Primary source located (partly read):** the STQC website notice at `stqc.gov.in/node/1042` states that certificates issued so far by STQC under its IoT System Certification Scheme shall not be deemed applicable or valid for the "PPO" of cameras as issued by MeitY through a Gazette Notification (we read the date as 6 March 2024 in the page text via our fetch tool; the notice appears to concern cameras only and does not mention DVRs or NVRs). We read it through a summarising fetch tool, not the raw page, and did not determine what "PPO" expands to. **Confidence: medium that a MeitY/STQC regime for CCTV cameras exists; low on its details.** Other STQC PDFs surfaced by search (CCTV test procedure, series guidelines, supply-chain guidance, Prama and Aditya Infotech certificates) were not read.
2. **Secondary sources (news and blogs, snippet or summary level):** several outlets state that from **1 April 2026** internet-connected CCTV cameras need STQC security certification, that applicants must disclose the origin of critical components such as the system-on-chip and firmware, and that Hikvision, Dahua and TP-Link have been denied certification and cannot sell such cameras (for example Medianama, which cites the Economic Times and MeitY's April 2024 Essential Requirements document; we read the Medianama article through a summarising fetch tool, and it did not address recorders or legacy products). **Confidence: low to medium. Not confirmed by a primary MeitY, STQC or BIS statement that we could read; the "denied certification" claim in particular rests on news reports.**
3. **Conflicting date:** an Aditya Infotech MD interview (DSIJ, 18 Sep 2025) says "STQC came into play on April 9, 2025". Reports therefore disagree about when the rules started (April 2025 vs April 2026), possibly different stages of the same regime; we did not reconcile them.
4. **BIS:** one search result headline says BIS compliance for CCTV by 2026; we did not open it or any BIS source. **UNVERIFIED.**
5. **Recorders:** the sources we read talk about cameras. We found no statement we could confirm on whether DVRs and NVRs are in scope. **Unknown.**
6. A search-engine summary claimed Dahua distribution in India ended because of the STQC rule; the article we opened (the DSIJ interview) contains no such statement. **Not verified and not used.**
7. One search result reported that the Prama brand (Hikvision's India entity) has STQC-certified camera models, which would conflict with the claim that Hikvision cannot sell certified products; it comes from a certificate-listing blog and a forum thread (snippet level). **Unresolved.**

**Implication for purchasing (not legal advice):** whether a forensic lab may import or buy a given Hikvision or Dahua unit, or whether used or existing-stock units are affected, was not determined. Ask the procurement and legal teams, and prefer a unit already in the lab, a used unit, or one from an authorised Indian distributor. None of this changes the technical plan.

## 5. Selection rules that protect the validity of the images
- One variable at a time: do not change firmware between the two images of a model.
- Record everything the playbook section 1 asks, including the firmware version.
- A recorder is a security-sensitive IoT device: keep it off the internet during recording and imaging; do not use cloud features for evidence.
- Do not buy a unit for a tier it cannot affect: unknown-OEM units (Uniview, TP-Link, Godrej, Matrix) are only worth buying after items 1 to 3 are in hand, each as a C to B exploration.

## 6. Sources (access date 2026-10-05)

| # | URL | Title / description | Read |
|---|---|---|---|
| 1 | https://stqc.gov.in/node/1042 | STQC notice on IoT System Certification Scheme certificates and the PPO of cameras | Partly (via summarising fetch) |
| 2 | https://www.stqc.gov.in/sites/default/files/2024-05/IoTSCS-P01-Procedure-for-CCTV-Testing-Evaluation-and-Certification.pdf | STQC procedure for CCTV testing, evaluation and certification | Snippet only (text extraction failed) |
| 3 | https://stqc.gov.in/sites/default/files/2024-10/STQC_IOTSCS_ER_009_Prama.pdf and the other STQC PDFs in the same search result (series guidelines, supply-chain guidance, application form) | STQC certificate and guideline documents | Snippet only |
| 4 | https://www.medianama.com/2026/04/223-india-bans-chinese-cctv-makers-april-2026/ | India Bans Chinese CCTV Under New Security Rules (Medianama, Apr 2026) | Partly (via summarising fetch) |
| 5 | https://www.thedailyjagran.com/technology/india-to-ban-chinese-cctv-cameras-from-april-1-2026-hikvision-tplink-and-others-denied-certification-10305808 ; https://www.certification-india.com/en/india-mandates-bis-er-compliance-for-cctv-cameras-by-2026/ ; https://cctvhelpdesk.net/chinese-cctv-ban-india-2026-stqc-rules/ | News and certification-consultancy pages on the 2026 rules | Snippet only |
| 6 | https://techenclave.com/t/has-govt-blocked-ip-cameras-from-big-brands-like-hikvision-and-dahua/411735 ; https://vucense.com/privacy-sovereignty/surveillance-biometrics/india-bans-chinese-cctv-hikvision-dahua-april-2026/ ; https://fgtechstore.com/blog/bis-stqc-certified-cctv-camera/ | Forum and blog pages on certification status of brands | Snippet only |
| 7 | https://insights.dsij.in/dsijarticledetail/in-conversation-with-aditya-khemka-managing-director-aditya-infotech-ltd-id004-52594 | In conversation with Aditya Khemka, MD, Aditya Infotech Ltd (DSIJ, 18 Sep 2025) | Partly (via summarising fetch) |
| 8 | https://www.moglix.com/hikvision-8-channel-turbo-hd-dvr-ds-7208hqhi-f2/mp/msn2km1ewm789v | Hikvision 8 Channel Turbo HD DVR DS-7208HQHI-F2 (Moglix listing) | Fully (summarising fetch) |
| 9 | https://m.indiamart.com/sakshamtechnologies/cp-plus-dvr.html | CP Plus 8 Channel DVR, CP-UVR-0801E1-CS (IndiaMART seller page) | Fully (summarising fetch) |
| 10 | https://airtel.infibeam.com/home-lifestyle/dahua-cctv-1mp-dh-xvr4108hs-8ch-dvr-1pcs/p-12032-99403798519-cat.html | Dahua DH-XVR4108HS 8CH DVR (Airtel Infibeam listing, "Coming Soon") | Snippet only |
| 11 | https://networkwebcams.co.uk/honeywell-hn35080200-8-channel-nvr ; https://www.use-ip.co.uk/honeywell-hn35080200.html | Honeywell HN35080200 retailer pages (UK) | Snippet only (both returned 403) |
| 12 | https://blog.ertech.co.uk/?p=2646 | Hikvision Product Discontinuation Notice of DS-7200 Series (reseller blog) | Snippet only |
| 13 | RESEARCH.md sources S1 (Han 2015), S2 (Dragonas thesis), S5 (Yoon and Hwang 2026), S14 (ICICI Securities Aditya Infotech IPO review) | Model names used in the table (see `docs/RESEARCH.md` section 10 for their read status) | As stated there |
