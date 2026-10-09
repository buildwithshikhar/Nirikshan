# Round D UI map (saved verbatim; Part 2 builds the frontend from this)

6 groups, 15 modules, 25 screens, 56 subscreens.

**OVERVIEW:** 1 Dashboard (screen Dashboard; tabs Case stats, Recent activity, Integrity health).

**ACQUIRE:** 2 Cases (screens Case list, Case detail; tabs Overview, Evidence list, Activity). 3 Evidence & Acquisition (screens New acquisition wizard, Evidence detail; tabs Source and attestation, Hash and verify, Custody entries; includes resume, bad-sector map, native-export ingest). 4 Device Intelligence (screen Identification result; tabs Signature matches with confidence, Parser selection, Unknown-device view).

**RECOVER:** 5 Storage Explorer (screen Offset map; tabs Layout map, Vendor structures, Anomalies; plus bounded read-only hex view). 6 Recovery Lab (screens Run console, Clip detail and player, Orphans and failed decodes; tabs Parser results, Generic carving, Cross-check, Player, Bitstream and hash info, Recovery limits with recoverability estimate).

**ANALYSE:** 7 Timeline (screens Time settings, Timeline; tabs Device timezone, Reference times, Drift fit, Chart, Gaps and overlaps, Unplaceable clips). 8 AI Triage (screens Run, Results; tabs Motion, Objects, Faces, Error rates; plus event search and summaries). 9 Correlation (screen Link suggestions; tabs Suggested links, Camera map; accept/reject, external log import).

**ASSURE:** 10 Integrity Center (screens Custody log, Verification; tabs Chain view, head_hash, Audit trail, Hash re-verify). 11 Report Studio (screens Builder, Exports; tabs PDF report, Draft BSA 63(4) certificate, JSON-LD and CSV, Evidence package with approval status). 12 Validation & Compatibility (screens Validation Center, Compatibility Registry; tabs Results, Tier table, Error rates, OEM matrix for all 16 targets, Open conflicts, Parser versions).

**SYSTEM:** 13 Jobs (screen Job list; tabs Running, History). 14 Admin (screens Users and roles, System settings; tabs Users, Roles, Keys, Config and audit). 15 Help (screen Help; tabs SOPs, Manual, Limits and tiers).
