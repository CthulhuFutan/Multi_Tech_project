"""CS5185 reproducible content-adaptive H.264 experiment."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from pytorch_msssim import ms_ssim

ROOT = Path(__file__).resolve().parent
DATASET = ROOT.parent / "CS5185_Project_Video_Dataset"
DEV = {1, 2, 3, 4, 7, 8}
TEST = {5, 6, 9, 10}


def command(args: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode and not allow_failure:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}\n{result.stderr[-3000:]}")
    return result


def probe(ffprobe: str, path: Path) -> dict:
    return json.loads(command([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout)


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def frames(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield i, i / fps, frame
            i += 1
    finally:
        cap.release()


def features(path: Path) -> tuple[list[dict], dict]:
    timeline, previous = [], None
    for i, t, frame in frames(path):
        gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
        motion = float(np.mean(cv2.absdiff(gray, previous))) / 255 if previous is not None else 0.0
        edges = float(np.mean(cv2.Canny(gray, 80, 160) > 0))
        timeline.append({"frame": i, "time_s": t, "motion": motion, "edge_fraction": edges})
        previous = gray
    if not timeline:
        raise RuntimeError("No decodable input frames")
    motion_values = np.array([x["motion"] for x in timeline[1:]] or [0.0])
    summary = {"motion_mean": float(motion_values.mean()), "motion_p90": float(np.percentile(motion_values, 90)),
               "edge_mean": float(np.mean([x["edge_fraction"] for x in timeline])), "frames": len(timeline)}
    return timeline, summary


def decision(summary: dict, adaptive: bool) -> tuple[dict, str]:
    # Fixed thresholds are part of the reproducible protocol; revise only with development data.
    if not adaptive:
        return {"preset": "medium", "aq_mode": 1, "aq_strength": 1.0}, "Unified baseline"
    if summary["motion_p90"] >= 0.075:
        return {"preset": "medium", "aq_mode": 2, "aq_strength": 0.8}, "High temporal change; test automatic variance AQ"
    if summary["edge_mean"] >= 0.105:
        return {"preset": "medium", "aq_mode": 2, "aq_strength": 1.2}, "High edge density; allocate bits across detailed regions"
    return {"preset": "medium", "aq_mode": 1, "aq_strength": 1.0}, "Low measured complexity; retain baseline setting"


def encode(ffmpeg: str, source: Path, output: Path, job: Path, kbps: int, settings: dict) -> tuple[float, list[list[str]]]:
    common = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-map", "0:v:0", "-an",
              "-c:v", "libx264", "-preset", settings["preset"], "-pix_fmt", "yuv420p", "-b:v", f"{kbps}k",
              "-x264-params", f"aq-mode={settings['aq_mode']}:aq-strength={settings['aq_strength']}"]
    first = common + ["-pass", "1", "-passlogfile", str(job), "-f", "null", os.devnull]
    second = common + ["-pass", "2", "-passlogfile", str(job), "-movflags", "+faststart", str(output)]
    start = time.perf_counter()
    command(first)
    command(second)
    return time.perf_counter() - start, [first, second]


def validate(ffmpeg: str, ffprobe: str, source_info: dict, output: Path) -> dict:
    decoded = command([ffmpeg, "-v", "error", "-xerror", "-i", str(output), "-map", "0:v:0", "-f", "null", os.devnull], allow_failure=True)
    info = probe(ffprobe, output)
    s = next(x for x in source_info["streams"] if x["codec_type"] == "video")
    o = next(x for x in info["streams"] if x["codec_type"] == "video")
    duration = float(info["format"]["duration"])
    source_duration = float(source_info["format"]["duration"])
    valid = decoded.returncode == 0 and abs(duration - source_duration) <= 1 / 30 + 0.01
    valid &= (o["width"], o["height"], o.get("nb_frames"), o["avg_frame_rate"]) == (s["width"], s["height"], s.get("nb_frames"), s["avg_frame_rate"])
    return {"decode_ok": bool(valid), "duration_s": duration, "frame_count": o.get("nb_frames"), "width": o["width"], "height": o["height"], "fps": o["avg_frame_rate"], "probe": info, "decode_error": decoded.stderr[-1000:]}


def quality(reference: Path, output: Path) -> tuple[float, float, int]:
    # All corresponding frames contribute to aggregate luma PSNR; MS-SSIM samples every 30th frame.
    ref = frames(reference)
    out = frames(output)
    sse = 0.0
    pixels = 0
    ms_values = []
    count = 0
    for a, b in zip(ref, out):
        ia, ta, fa = a
        ib, tb, fb = b
        if ia != ib or abs(ta - tb) > 1 / 60 or fa.shape != fb.shape:
            raise RuntimeError("Reference/output frame alignment differs")
        ya = cv2.cvtColor(fa, cv2.COLOR_BGR2YCrCb)[:, :, 0].astype(np.float64)
        yb = cv2.cvtColor(fb, cv2.COLOR_BGR2YCrCb)[:, :, 0].astype(np.float64)
        sse += float(np.square(ya - yb).sum())
        pixels += ya.size
        if ia % 30 == 0:
            x = torch.from_numpy(ya.astype(np.float32))[None, None]
            y = torch.from_numpy(yb.astype(np.float32))[None, None]
            ms_values.append(float(ms_ssim(x, y, data_range=255, size_average=True)))
        count += 1
    if next(ref, None) is not None or next(out, None) is not None:
        raise RuntimeError("Reference/output frame counts differ")
    return (float("inf") if sse == 0 else 10 * math.log10(255**2 * pixels / sse), float(np.mean(ms_values)), count)


def plot_timeline(timeline: list[dict], output: Path, title: str):
    t = [x["time_s"] for x in timeline]
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(t, [x["motion"] for x in timeline], label="Frame difference / 255")
    ax.plot(t, [x["edge_fraction"] for x in timeline], label="Edge fraction")
    ax.set(xlabel="Time (s)", ylabel="Feature value", title=title)
    ax.legend(); ax.grid(alpha=.2); fig.tight_layout(); fig.savefig(output, dpi=160); plt.close(fig)


def run_one(args, source: Path, ratio: float, mode: str, result_dir: Path) -> dict:
    start = time.perf_counter()
    source_info = probe(args.ffprobe, source)
    duration = float(source_info["format"]["duration"])
    original_bytes = source.stat().st_size
    budget = math.floor(original_bytes * ratio)
    timeline, summary = features(source)
    settings, reason = decision(summary, mode == "adaptive")
    label = f"{source.stem}_{int(ratio * 100)}pct_{mode}"
    plot_timeline(timeline, result_dir / f"{source.stem}_features.png", source.stem)
    (result_dir / f"{source.stem}_features.json").write_text(json.dumps({"summary": summary, "timeline": timeline}, indent=2), encoding="utf-8")
    bitrate = max(1, round(.98 * 8 * budget / duration / 1000))
    attempts = []
    chosen = None
    for number in range(1, 4):
        candidate = result_dir / f"{label}_attempt{number}.mp4"
        elapsed, commands = encode(args.ffmpeg, source, candidate, result_dir / f"{label}_pass{number}", bitrate, settings)
        actual = candidate.stat().st_size
        integrity = validate(args.ffmpeg, args.ffprobe, source_info, candidate)
        entry = {"attempt": number, "target_video_kbps": bitrate, "actual_bytes": actual, "encode_time_s": elapsed,
                 "settings": settings, "ffmpeg_commands": commands, "decode_ok": integrity["decode_ok"], "decision_reason": reason}
        attempts.append(entry)
        if integrity["decode_ok"] and (chosen is None or (actual <= budget and (chosen["actual_bytes"] > budget or actual > chosen["actual_bytes"])) or (actual > budget and chosen["actual_bytes"] > budget and actual < chosen["actual_bytes"])):
            chosen = {**entry, "path": candidate, "integrity": integrity}
        if integrity["decode_ok"] and actual <= budget:
            break
        bitrate = max(1, math.floor(bitrate * budget / actual * .98))
    if chosen is None:
        raise RuntimeError(f"No valid candidate: {label}")
    category = "5_percent" if ratio == .05 else "2_percent" if ratio == .02 else f"{ratio:g}_ratio"
    final_dir = args.output / category
    final_dir.mkdir(parents=True, exist_ok=True)
    final = final_dir / f"{label}.mp4"
    shutil.copy2(chosen["path"], final)
    psnr, msssim, count = quality(source, final)
    packet_info = json.loads(command([args.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=size", "-of", "json", str(final)]).stdout)
    packet_bytes = sum(int(p["size"]) for p in packet_info["packets"])
    row = {"video_id": source.stem, "split": "development" if int(source.name[:2]) in DEV else "test" if int(source.name[:2]) in TEST else "additional",
           "mode": mode, "ratio": ratio, "original_bytes": original_bytes, "target_bytes": budget, "actual_bytes": final.stat().st_size,
           "within_budget": final.stat().st_size <= budget, "target_file_kbps": 8 * budget / duration / 1000,
           "actual_file_kbps": 8 * final.stat().st_size / duration / 1000, "actual_video_kbps": 8 * packet_bytes / duration / 1000,
           "duration_s": duration, "frame_count": count, "decode_ok": chosen["integrity"]["decode_ok"],
           "psnr_y_db": psnr, "ms_ssim_y": msssim, "ms_ssim_samples": math.ceil(count / 30), "total_time_s": time.perf_counter() - start,
           "encode_time_s": sum(x["encode_time_s"] for x in attempts), "attempts": len(attempts), "selected_attempt": chosen["attempt"],
           "settings": settings, "decision_reason": reason, "features": summary, "input_sha256": hash_file(source), "output_sha256": hash_file(final),
           "output_path": str(final), "attempt_log": attempts}
    (result_dir / f"{label}.json").write_text(json.dumps(row, indent=2, ensure_ascii=False, allow_nan=False, default=lambda x: str(x)), encoding="utf-8")
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path, default=DATASET)
    p.add_argument("--results", type=Path, default=ROOT / "results")
    p.add_argument("--output", type=Path, default=ROOT / "result", help="Final videos, grouped by target ratio")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--ffprobe", default="ffprobe")
    p.add_argument("--videos", nargs="*", help="Optional video IDs, e.g. 01 06")
    p.add_argument("--ratios", nargs="*", type=float, default=[.05, .02])
    p.add_argument("--modes", nargs="*", choices=["baseline", "adaptive"], default=["baseline", "adaptive"])
    args = p.parse_args()
    args.results.mkdir(parents=True, exist_ok=True)
    config = {"platform": platform.platform(), "python": platform.python_version(), "opencv": cv2.__version__, "numpy": np.__version__, "torch": torch.__version__,
              "ffmpeg": command([args.ffmpeg, "-version"]).stdout.splitlines()[0], "ffprobe": command([args.ffprobe, "-version"]).stdout.splitlines()[0],
              "threads": torch.get_num_threads(), "cache_policy": "read source each attempt; no cache", "dataset": str(args.dataset)}
    (args.results / "run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    videos = sorted(args.dataset.glob("[0-9][0-9]_*.mp4"))
    if args.videos:
        videos = [v for v in videos if v.name[:2] in args.videos]
    for video in videos:
        for ratio in args.ratios:
            for mode in args.modes:
                print(f"RUN {video.name} {ratio:.0%} {mode}", flush=True)
                try:
                    row = run_one(args, video, ratio, mode, args.results)
                    print(f"DONE {row['actual_bytes']}/{row['target_bytes']} PSNR={row['psnr_y_db']:.2f} MS-SSIM={row['ms_ssim_y']:.4f}", flush=True)
                except Exception as exc:
                    print(f"FAIL {video.name}: {exc}", flush=True)
    rows = [json.loads(x.read_text(encoding="utf-8")) for x in sorted(args.results.glob("*pct_*.json"))]
    if rows:
        fields = [k for k in rows[0] if k not in {"settings", "features", "attempt_log"}]
        with (args.results / "summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fields); w.writeheader(); w.writerows([{k: r[k] for k in fields} for r in rows])


if __name__ == "__main__":
    main()
