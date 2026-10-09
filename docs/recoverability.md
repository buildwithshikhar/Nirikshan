# Per-clip recoverability estimate

*Round D stream 2d. Code: `backend/app/recover/`. Tests: `backend/tests/test_recover_estimate.py`. Measurement: `docs/validation/recoverability.json` (`python -m app.recover.measure --seed 20260101 --trials 10 --out ../docs/validation/recoverability.json`). **All numbers below are on SYNTHETIC reference images built from published research and open-source format documentation; they do not predict behaviour on real DVR/NVR images.***

## The rule (version 1)

`GET /api/clips/{id}/recoverability` applies a fixed rule to what the analysis run stored for the clip. There are no learned weights and nothing was fitted to ground truth; the constants were chosen before the measurement below and have not been changed after it.

```
estimate = decode_factor x irap_factor x continuity_factor x header_factor
```

| Component | Stored evidence | Factor |
|---|---|---|
| decode test | `decode_status` of the `ffmpeg -f null` test on the carved bitstream | ok 1.0, decode_errors 0.5, export_failed 0.0; not exported: **no estimate** (`available:false`) |
| IRAP present | `irap_count` | >= 1: 1.0, else 0.0 (nothing decodes before the first IRAP) |
| NAL continuity | `reassembled` flag (fragment reassembler joined a gap) | joined 0.5, one contiguous run 1.0 |
| header validity | parameter sets syntax-checked by the carver (`validate_params`) or accepted by the decoder | yes 1.0, no 0.75 |

Bands: **high** >= 0.9, **medium** >= 0.5, **low** < 0.5. Orphan ranges get 0.0. The 0.5 for `decode_errors` is a midpoint, because the stored decode test records *that* errors occurred, not how many frames were affected.

The response lists each component with its evidence and reason, an `explanation` string (`decode_test 1.0 x irap_present 1.0 x ... = 1.0`), per-clip **limitations** text (generic carving gives no vendor/channel/time attribution and may mix interleaved channels; non-zero garbage between NAL units is absorbed undetectably; H.265 has no continuity check; reassembly is a heuristic with its measured false-accept rate; decode errors; missing IRAP; durations assume the stream frame rate; why the clip ended) and the measured agreement summary below.

## How agreement was measured

For every scenario of the validation harness that runs the generic engine with export (39 scenarios, 33 of which produced at least one clip; including the per-paper DHAV, Hikvision and Honeywell layouts carved generically), 10 seeded trials (seed 20260101) were built, carved and exported exactly as in analysis; the rule was applied to the same features the API uses. Ground truth per clip:

> **actual** = recoverable VCL NAL units of the clip's attributed truth clip (largest byte overlap) lying wholly inside the clip's extents / VCL NAL units the carver counted in the clip, capped at 1.

"Recoverable" is the harness definition (the NAL unit, its GOP's parameter sets and every earlier VCL NAL unit of that GOP survived intact). The measure is "what fraction of the frames this clip claims are genuine, decodable frames of one recording". Only generic-engine clips are measured; **parser clips are not measured**.

## Result (817 clips, ffmpeg 9.0.2)

| Statistic | Value |
|---|---|
| Pearson r (estimate vs actual) | **0.44** |
| Spearman rho | **0.56** |
| Mean absolute error | 0.069 |
| Mean signed error (estimate - actual) | +0.015 |
| Band agreement (band of estimate = band of actual) | 86.8% |

| Band | Clips | Mean estimate | Mean actual | actual >= 0.9 | actual < 0.5 |
|---|---|---|---|---|---|
| high | 746 | 1.00 | 0.97 | 708 | 21 |
| medium | 71 | 0.50 | 0.65 | 46 | 24 |
| low | 0 | - | - | - | - |

**Reading it honestly: the rule is weak.** Its average error is small only because most clips on these images are intact and the rule says 1.0. Where it matters it often fails:

- **Over-estimates mixed-channel clips.** In `multi_channel_gop` and `multi_channel_frame` (raw and DHAV layouts) the carver merges interleaved channels into one clip that still decodes, so the rule says high (1.0) while only 30-50% of the clip's frames belong to one recording. 37 such clips are in the high band; the decode test cannot see channel mixing.
- **Under-estimates correct reassembly.** In `fragmented_zero_join_on` (raw and DHAV) 21 clips were joined correctly (actual 1.0) but get 0.5 because every join is penalised.
- **Midpoint for decode errors is uninformative.** Medium-band clips split between actual near 1.0 (minor damage at a clip edge, e.g. `partial_overwrite_zero`) and actual 0.0 (`partial_overwrite_foreign`, `fully_overwritten`, `neg_encrypted_slices_params_clear`: decodable-looking clips whose slices are foreign or encrypted). The stored decode test does not separate them.
- **The low band is never used** on carved clips: the generic carver only starts clips at an IRAP with valid parameter sets, and export failures did not occur, so the factors that produce "low" never fire.

Use the estimate as an explained triage hint with its listed limitations, not as a probability. Better signals would need data the pipeline does not store today (decoded-frame counts from the decode test, a channel-consistency check); adding them is future work and would need a new, separately reported measurement.

Per-scenario statistics and every clip row are in `docs/validation/recoverability.json`; a test recomputes the summary from the rows so the file cannot be hand-edited consistently.

## Fragment reassembly false-accept rate

Fragment reassembly (H.264 joins across gaps, `join_gap > 0`) stays **off by default** (`CarveParams.join_gap = 0`). `GET /api/recovery/fragment-reassembly` exposes its measured false-accept rate straight from the committed validation results (`docs/validation/results.json`, digest included); if that file is missing it returns `available:false` with the reason. Current values (seed 20260101):

| Scenario | False accept (wrong joins accepted / wrong candidates) | True accept |
|---|---|---|
| `fragmented_zero_join_on` | 0/3 (0%) | 38/38 (100%) |
| `fragmented_decoy_join_on` | 35/297 (11.8%) | n/a |
| `fragmented_zero_join_on@dhav[generic]` | 35/38 (92.1%) | n/a |
| `fragmented_decoy_join_on@dhav[generic]` | 21/281 (7.5%) | n/a |

The DHAV rows show the generic reassembler joining across vendor headers it cannot see as such: on that layout most of its joins are wrong by the harness definition. That is one more reason the default is off.
