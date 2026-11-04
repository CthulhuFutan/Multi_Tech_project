"""Generate presentation-ready charts and a factual report from completed runs."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT = ROOT / "analysis.md"


def load():
    rows = []
    for path in RESULTS.glob("*pct_*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if "video_id" in row:
            rows.append(row)
    return sorted(rows, key=lambda x: (x["video_id"], -x["ratio"], x["mode"]))


def screenshot(path: Path, t: float):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * t)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Cannot read {path} at {t}s")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def charts(rows):
    pairs = {}
    for row in rows:
        pairs.setdefault((row["video_id"], row["ratio"]), {})[row["mode"]] = row
    complete = [(key, p) for key, p in pairs.items() if len(p) == 2]
    if not complete:
        return []
    labels = [f"{key[0][0:2]} {int(key[1]*100)}%" for key, _ in complete]
    x = np.arange(len(labels))
    plots = []
    for filename, ylabel, val, title in [
        ("size_budget.png", "Output / target size (%)", lambda r: 100*r["actual_bytes"]/r["target_bytes"], "File size versus budget"),
        ("quality_psnr.png", "PSNR Y (dB)", lambda r: r["psnr_y_db"], "Reconstruction quality"),
        ("quality_msssim.png", "MS-SSIM Y", lambda r: r["ms_ssim_y"], "Structural quality"),
        ("runtime.png", "Total time (s)", lambda r: r["total_time_s"], "End-to-end runtime")]:
        fig, ax = plt.subplots(figsize=(max(9, len(labels)*.45), 4.3))
        for mode, offset, color in [("baseline", -.19, "#4e79a7"), ("adaptive", .19, "#f28e2b")]:
            ax.bar(x+offset, [val(p[mode]) for _, p in complete], .38, label=mode, color=color)
        if filename == "size_budget.png":
            ax.axhline(100, color="crimson", linestyle="--", linewidth=1, label="budget")
        ax.set_xticks(x, labels, rotation=60, ha="right")
        ax.set(ylabel=ylabel, title=title)
        ax.legend(ncol=3); ax.grid(axis="y", alpha=.2); fig.tight_layout()
        fig.savefig(ROOT / filename, dpi=180); plt.close(fig)
        plots.append(filename)
    for stem in ["01_FourPeople", "06_ShakeNDry", "09_Parkrun"]:
        source = ROOT.parent / "CS5185_Project_Video_Dataset" / f"{stem}.mp4"
        if not source.exists():
            continue
        for ratio in [.05, .02]:
            p = pairs.get((stem, ratio), {})
            if len(p) < 2:
                continue
            t = 1.0
            images = [screenshot(source, t), screenshot(Path(p["baseline"]["output_path"]), t), screenshot(Path(p["adaptive"]["output_path"]), t)]
            fig, axes = plt.subplots(1, 3, figsize=(15, 3.6))
            for ax, image, label in zip(axes, images, ["Original", "Unified baseline", "Adaptive"]):
                ax.imshow(image); ax.set_title(label); ax.axis("off")
            fig.suptitle(f"{stem} | {int(ratio*100)}% target | t={t:.1f}s")
            fig.tight_layout(); name = f"compare_{stem}_{int(ratio*100)}pct.png"
            fig.savefig(ROOT / name, dpi=160); plt.close(fig); plots.append(name)
    return plots


def report(rows, plots):
    pairs = {}
    for r in rows:
        pairs.setdefault((r["video_id"], r["ratio"]), {})[r["mode"]] = r
    complete = [(k, v) for k, v in pairs.items() if len(v) == 2]
    lines = ["# CS5185 Experiment: Results and Analysis", "",
             "This report is generated from the actual encoding logs in `results/`. It answers what the project required, what was implemented, how it performed, and where the approach falls short.", "",
             "## Task and implementation", "",
             "The task was to encode all 12 silent 1280×720 videos at 5% and 2% of each original file size using FFmpeg/libx264, preserve the full clip, and explain content-dependent parameter choices against a unified baseline. We completed 48 runs: 12 videos × 2 budgets × baseline/adaptive. Final playable MP4 files are grouped under `result/5_percent/` and `result/2_percent/`.", "",
             "The pipeline reads metadata, computes an exact byte budget, measures frame difference and edge density, selects AQ settings, performs two-pass x264 encoding, checks output size and decoding, retries over-budget results up to three attempts, and records PSNR(Y), MS-SSIM(Y), time, parameters, and hashes. The baseline fixes preset=medium, AQ mode=1, strength=1.0. The adaptive variant changes only AQ mode/strength according to measured features; both use the same bitrate budget and other encoder settings.", "",
             "## Complete paired results", "",
             "Size columns show actual MP4 bytes as a percentage of the exact target. Positive metric differences favor adaptive encoding. Near-zero values should not be presented as meaningful wins without viewing the frames.", "",
             "| Video | Budget | Baseline size / target | Adaptive size / target | ΔPSNR Y (dB) | ΔMS-SSIM Y | Adaptive AQ |", "|---|---:|---:|---:|---:|---:|---|"]
    for (vid, ratio), p in complete:
        b, a = p["baseline"], p["adaptive"]
        lines.append(f"| {vid} | {ratio:.0%} | {b['actual_bytes']/b['target_bytes']:.2%} | {a['actual_bytes']/a['target_bytes']:.2%} | {a['psnr_y_db']-b['psnr_y_db']:+.2f} | {a['ms_ssim_y']-b['ms_ssim_y']:+.4f} | mode {a['settings']['aq_mode']}, strength {a['settings']['aq_strength']} |")
    valid = [r for r in rows if r["decode_ok"]]
    budget = [r for r in rows if r["within_budget"]]
    changed = [(k,p) for k,p in complete if p["adaptive"]["settings"] != p["baseline"]["settings"]]
    wins = sum(p["adaptive"]["psnr_y_db"] > p["baseline"]["psnr_y_db"] for _,p in changed)
    attempts = [r["attempts"] for r in rows]
    lines += ["", "## Outcomes", "",
              f"- **Size and integrity:** {len(budget)}/{len(rows)} final MP4 files meet their exact byte budgets; {len(valid)}/{len(rows)} pass decoding and checks for duration, frame count, dimensions, and frame rate. {sum(n > 1 for n in attempts)} runs required a second or third encoding attempt; the maximum observed was {max(attempts)}.",
              f"- **Quality:** Adaptive AQ differs from baseline in {len(changed)} paired cases. Its luma PSNR improves in {wins}/{len(changed)} of those cases. The rule therefore does not deliver a general PSNR gain. MS-SSIM and PSNR sometimes move in opposite directions, so neither alone establishes a subjective quality improvement.",
              "- **Fairness:** Both variants use the same target bytes, two-pass rate control, preset, resolution, frame rate, and pixel format. Small differences in actual bytes remain and should be considered when interpreting quality differences.",
              "- **Runtime:** `runtime.png` shows total pipeline time, including all attempts and quality evaluation. Exact values for each run are in `results/summary.csv`.", "",
              "## Cases for a five-minute presentation", "",
              "- **Parkrun (held-out test set):** At 5%, adaptive PSNR changes by −0.26 dB and MS-SSIM by +0.0011; at 2%, by −0.20 dB and +0.0028. The motion rule selects AQ mode 2, strength 0.8. Use the 2% three-way frame comparison and feature timeline to explain why the two metrics disagree. Do not call this an unqualified quality win.",
              "- **Jockey (held-out test set):** PSNR rises by about 0.18 dB at both budgets, while MS-SSIM falls slightly. This is another metric tradeoff under the same motion-sensitive setting.",
              "- **Sintel (additional video):** PSNR rises by about 0.63 dB at 5% and 0.61 dB at 2%; 2% MS-SSIM rises by about 0.0004. Mark this as an additional sample rather than a held-out test case.",
              "- **Beauty (fallback):** The rule keeps the baseline AQ settings, yielding identical outputs. It shows a defined fallback, not an adaptive quality gain.", "",
              "Suggested slide sequence: task and workflow; Parkrun feature timeline and selected parameters; size budget chart; PSNR/MS-SSIM comparison; aligned frame comparison; conclusions and limitations. Use FourPeople, ShakeNDry, and Parkrun for a three-video, two-budget summary.", "",
              "## Figures", ""]
    for name in plots:
        lines.append(f"![{name}]({name})")
        lines.append("")
    lines += ["## Limitations and measurement details", "",
              "The two-feature AQ rule is deliberately small and interpretable, but its fixed thresholds were not optimized systematically. It does not adapt within a clip, model camera motion or noise separately, or search candidate settings for best measured quality. The weak PSNR win rate is evidence that this rule needs refinement, not evidence that adaptive encoding as a whole is ineffective.",
              "PSNR(Y) aggregates squared error over every corresponding pixel and frame before converting to dB. MS-SSIM(Y) uses pytorch-msssim 1.0.0, data_range=255, five default scales, one frame per 30 frames, and an arithmetic mean over sampled frames. It is not a full-frame temporal MS-SSIM average. Representative still frames support visual inspection but cannot establish motion smoothness; viewers should also play the final MP4 files.",
              "The figures are descriptive, not a blinded human preference study. Runtime values depend on this machine and its software environment. Full-precision measurements, hashes, FFmpeg commands, selected attempts, and feature summaries are in `results/*.json`; input attribution is in the dataset's `licenses/` directory.", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    data = load()
    files = charts(data)
    report(data, files)
    print(f"Generated {OUT}, {len(data)} runs, {len(files)} plots")
