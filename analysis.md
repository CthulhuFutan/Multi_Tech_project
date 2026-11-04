# CS5185 Experiment: Results and Analysis

This report is generated from the actual encoding logs in `results/`. It answers what the project required, what was implemented, how it performed, and where the approach falls short.

## Task and implementation

The task was to encode all 12 silent 1280×720 videos at 5% and 2% of each original file size using FFmpeg/libx264, preserve the full clip, and explain content-dependent parameter choices against a unified baseline. We completed 48 runs: 12 videos × 2 budgets × baseline/adaptive. Final playable MP4 files are grouped under `result/5_percent/` and `result/2_percent/`.

The pipeline reads metadata, computes an exact byte budget, measures frame difference and edge density, selects AQ settings, performs two-pass x264 encoding, checks output size and decoding, retries over-budget results up to three attempts, and records PSNR(Y), MS-SSIM(Y), time, parameters, and hashes. The baseline fixes preset=medium, AQ mode=1, strength=1.0. The adaptive variant changes only AQ mode/strength according to measured features; both use the same bitrate budget and other encoder settings.

## Complete paired results

Size columns show actual MP4 bytes as a percentage of the exact target. Positive metric differences favor adaptive encoding. Near-zero values should not be presented as meaningful wins without viewing the frames.

| Video | Budget | Baseline size / target | Adaptive size / target | ΔPSNR Y (dB) | ΔMS-SSIM Y | Adaptive AQ |
|---|---:|---:|---:|---:|---:|---|
| 01_FourPeople | 5% | 98.67% | 99.00% | -0.17 | +0.0001 | mode 2, strength 1.2 |
| 01_FourPeople | 2% | 96.80% | 96.87% | -0.22 | +0.0000 | mode 2, strength 1.2 |
| 02_Beauty | 5% | 89.96% | 89.96% | +0.00 | +0.0000 | mode 1, strength 1.0 |
| 02_Beauty | 2% | 99.45% | 99.45% | +0.00 | +0.0000 | mode 1, strength 1.0 |
| 03_Bosphorus | 5% | 98.32% | 98.47% | -0.11 | +0.0001 | mode 2, strength 1.2 |
| 03_Bosphorus | 2% | 98.66% | 98.90% | -0.08 | +0.0003 | mode 2, strength 1.2 |
| 04_HoneyBee | 5% | 96.86% | 99.58% | -0.06 | +0.0000 | mode 2, strength 1.2 |
| 04_HoneyBee | 2% | 87.28% | 86.95% | -0.12 | -0.0000 | mode 2, strength 1.2 |
| 05_Jockey | 5% | 97.84% | 98.16% | +0.18 | -0.0000 | mode 2, strength 0.8 |
| 05_Jockey | 2% | 98.29% | 97.82% | +0.18 | -0.0005 | mode 2, strength 0.8 |
| 06_ShakeNDry | 5% | 98.12% | 98.26% | -0.15 | +0.0001 | mode 2, strength 1.2 |
| 06_ShakeNDry | 2% | 99.11% | 98.97% | -0.13 | +0.0003 | mode 2, strength 1.2 |
| 07_Mobcal | 5% | 97.05% | 95.51% | -0.51 | +0.0000 | mode 2, strength 1.2 |
| 07_Mobcal | 2% | 95.23% | 95.54% | -0.46 | -0.0000 | mode 2, strength 1.2 |
| 08_Shields | 5% | 96.91% | 97.81% | -0.07 | +0.0000 | mode 2, strength 0.8 |
| 08_Shields | 2% | 97.70% | 97.75% | -0.04 | -0.0000 | mode 2, strength 0.8 |
| 09_Parkrun | 5% | 99.77% | 100.00% | -0.26 | +0.0011 | mode 2, strength 0.8 |
| 09_Parkrun | 2% | 98.74% | 99.09% | -0.20 | +0.0028 | mode 2, strength 0.8 |
| 10_Stockholm | 5% | 98.49% | 98.34% | -0.25 | +0.0003 | mode 2, strength 1.2 |
| 10_Stockholm | 2% | 99.04% | 98.22% | -0.26 | +0.0001 | mode 2, strength 1.2 |
| 11_Sintel | 5% | 98.36% | 97.99% | +0.63 | -0.0001 | mode 2, strength 0.8 |
| 11_Sintel | 2% | 98.55% | 98.08% | +0.61 | +0.0004 | mode 2, strength 0.8 |
| 12_ControlledBurn | 5% | 99.71% | 99.88% | -0.55 | +0.0001 | mode 2, strength 1.2 |
| 12_ControlledBurn | 2% | 98.16% | 98.18% | -0.64 | -0.0000 | mode 2, strength 1.2 |

## Outcomes

- **Size and integrity:** 48/48 final MP4 files meet their exact byte budgets; 48/48 pass decoding and checks for duration, frame count, dimensions, and frame rate. 19 runs required a second or third encoding attempt; the maximum observed was 3.
- **Quality:** Adaptive AQ differs from baseline in 22 paired cases. Its luma PSNR improves in 4/22 of those cases. The rule therefore does not deliver a general PSNR gain. MS-SSIM and PSNR sometimes move in opposite directions, so neither alone establishes a subjective quality improvement.
- **Fairness:** Both variants use the same target bytes, two-pass rate control, preset, resolution, frame rate, and pixel format. Small differences in actual bytes remain and should be considered when interpreting quality differences.
- **Runtime:** `runtime.png` shows total pipeline time, including all attempts and quality evaluation. Exact values for each run are in `results/summary.csv`.

## Cases for a five-minute presentation

- **Parkrun (held-out test set):** At 5%, adaptive PSNR changes by −0.26 dB and MS-SSIM by +0.0011; at 2%, by −0.20 dB and +0.0028. The motion rule selects AQ mode 2, strength 0.8. Use the 2% three-way frame comparison and feature timeline to explain why the two metrics disagree. Do not call this an unqualified quality win.
- **Jockey (held-out test set):** PSNR rises by about 0.18 dB at both budgets, while MS-SSIM falls slightly. This is another metric tradeoff under the same motion-sensitive setting.
- **Sintel (additional video):** PSNR rises by about 0.63 dB at 5% and 0.61 dB at 2%; 2% MS-SSIM rises by about 0.0004. Mark this as an additional sample rather than a held-out test case.
- **Beauty (fallback):** The rule keeps the baseline AQ settings, yielding identical outputs. It shows a defined fallback, not an adaptive quality gain.

Suggested slide sequence: task and workflow; Parkrun feature timeline and selected parameters; size budget chart; PSNR/MS-SSIM comparison; aligned frame comparison; conclusions and limitations. Use FourPeople, ShakeNDry, and Parkrun for a three-video, two-budget summary.

## Figures

![size_budget.png](size_budget.png)

![quality_psnr.png](quality_psnr.png)

![quality_msssim.png](quality_msssim.png)

![runtime.png](runtime.png)

![compare_01_FourPeople_5pct.png](compare_01_FourPeople_5pct.png)

![compare_01_FourPeople_2pct.png](compare_01_FourPeople_2pct.png)

![compare_06_ShakeNDry_5pct.png](compare_06_ShakeNDry_5pct.png)

![compare_06_ShakeNDry_2pct.png](compare_06_ShakeNDry_2pct.png)

![compare_09_Parkrun_5pct.png](compare_09_Parkrun_5pct.png)

![compare_09_Parkrun_2pct.png](compare_09_Parkrun_2pct.png)

## Limitations and measurement details

The two-feature AQ rule is deliberately small and interpretable, but its fixed thresholds were not optimized systematically. It does not adapt within a clip, model camera motion or noise separately, or search candidate settings for best measured quality. The weak PSNR win rate is evidence that this rule needs refinement, not evidence that adaptive encoding as a whole is ineffective.
PSNR(Y) aggregates squared error over every corresponding pixel and frame before converting to dB. MS-SSIM(Y) uses pytorch-msssim 1.0.0, data_range=255, five default scales, one frame per 30 frames, and an arithmetic mean over sampled frames. It is not a full-frame temporal MS-SSIM average. Representative still frames support visual inspection but cannot establish motion smoothness; viewers should also play the final MP4 files.
The figures are descriptive, not a blinded human preference study. Runtime values depend on this machine and its software environment. Full-precision measurements, hashes, FFmpeg commands, selected attempts, and feature summaries are in `results/*.json`; input attribution is in the dataset's `licenses/` directory.
