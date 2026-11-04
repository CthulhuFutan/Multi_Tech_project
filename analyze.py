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
OUT = ROOT / "Analysis.md"


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
    lines = ["# CS5185 实验结果与 PPT 分析素材", "", "本报告从 `results/` 中实际编码与评估日志自动生成。图像为同时间戳画面，质量指标基于 Y 通道。", "",
             "## 汇总", "", f"已完成 {len(rows)} 个编码任务，{len(complete)} 组基线/自适应配对；目标为 12 视频 × 2 档 × 2 模式，共 48 个编码任务。", "",
             "| 视频 | 目标 | 基线大小/目标 | 自适应大小/目标 | ΔPSNR (dB) | ΔMS-SSIM | 自适应决策 |", "|---|---:|---:|---:|---:|---:|---|"]
    for (vid, ratio), p in complete:
        b, a = p["baseline"], p["adaptive"]
        lines.append(f"| {vid} | {ratio:.0%} | {b['actual_bytes']/b['target_bytes']:.2%} | {a['actual_bytes']/a['target_bytes']:.2%} | {a['psnr_y_db']-b['psnr_y_db']:+.2f} | {a['ms_ssim_y']-b['ms_ssim_y']:+.4f} | AQ {a['settings']['aq_mode']}, strength {a['settings']['aq_strength']} |")
    valid = [r for r in rows if r["decode_ok"]]
    budget = [r for r in rows if r["within_budget"]]
    changed = [(k,p) for k,p in complete if p["adaptive"]["settings"] != p["baseline"]["settings"]]
    wins = sum(p["adaptive"]["psnr_y_db"] > p["baseline"]["psnr_y_db"] for _,p in changed)
    lines += ["", "## 适合 PPT 的结论", "",
              f"1. 完整性：{len(valid)}/{len(rows)} 个已完成输出通过解码、时长、帧数、分辨率和帧率检查；{len(budget)}/{len(rows)} 个输出在精确字节预算内。",
              f"2. 内容决策：在 {len(changed)} 组参数真正改变的配对中，自适应方案的 Y-PSNR 提高了 {wins} 组；这说明规则并非对所有内容都有同样收益，应结合画面对照解释。",
              "3. 大小控制：两方案使用相同目标字节、两遍编码和反馈公式；文件大小图中的 100% 虚线就是硬预算。PSNR 与 MS-SSIM 请与该图一起看，避免把更大的文件误判为纯粹的编码优势。",
              "4. 耗时：总时间包含 metadata、特征分析、所有编码轮次、解码检查、质量评估和日志写入；运行时间图可说明自适应决策的实际成本。", "",
              "## 图表", ""]
    for name in plots:
        lines.append(f"![{name}]({name})")
        lines.append("")
    lines += ["## 方法和局限", "",
              "基线固定 preset=medium、AQ mode=1、strength=1.0；自适应只根据帧差 P90 和平均边缘比例选择 AQ。两方案均用 libx264 双遍平均码率，目标字节相同。规则阈值为预设启发式，不能保证每个视频都优于基线。",
              "PSNR(Y) 对全部对应帧累计平方误差后计算；MS-SSIM(Y) 使用 pytorch-msssim 1.0.0、data_range=255、默认 5 个尺度，在每 30 帧取一帧并作算术平均。整片其余帧仍参与 PSNR 与完整性检查。",
              "报告中显示的实验时间与数值仅对当前硬件和环境有效。每条任务的输入/输出 SHA-256、FFmpeg 命令、逐轮决策、失败信息与精确数值见 `results/*.json`。", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    data = load()
    files = charts(data)
    report(data, files)
    print(f"Generated {OUT}, {len(data)} runs, {len(files)} plots")
