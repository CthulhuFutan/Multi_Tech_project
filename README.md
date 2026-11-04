# CS5185 content adaptive encoding experiment

The project implements the pipeline described in [Design.md](Design.md): exact 5%/2% file budgets, frame feature analysis, rule based x264 settings, FFmpeg two pass encoding, bounded retries, decode and duration verification, luma PSNR and MS-SSIM, and comparative plots.

## Requirements

Python 3.10+, FFmpeg/ffprobe with `libx264`, and `pip install -r requirements.txt`. The dataset folder should be next to this `work` directory, or supplied with `--dataset`. On this machine, the bundled executable is under `vendor/win32`; `vendor` is intentionally excluded from Git.

## Run

```powershell
python experiment.py --dataset "..\CS5185_Project_Video_Dataset" --ffmpeg "vendor\win32\ffmpeg.exe" --ffprobe "vendor\win32\ffprobe.exe"
python analyze.py
```

Use `--videos 01 06 09`, `--ratios 0.05`, or `--modes baseline` for smaller runs. To reproduce the current machine's run, set `PYTHONPATH` to `vendor` when packages are installed there. The local Conda environment requires `KMP_DUPLICATE_LIB_OK=TRUE` due to duplicate OpenMP runtimes; a clean virtual environment is recommended for independent reproduction.

`results/summary.csv` contains one row per task. Detailed JSON includes exact bytes, hashes, all FFmpeg commands, selected attempt, feature summary, timing, quality and integrity. `Analysis.md` and PNGs are generated from those logs. The MP4 outputs remain locally in `results/` and are ignored by Git because they are large. No GitHub remote or push is performed here.

## Design notes

The adaptive rule uses frame difference P90 and mean edge fraction. When neither threshold is reached, its settings equal the baseline; these rows test the fallback and should not be presented as a quality gain from adaptation. Budget checks use MP4 file bytes, including container overhead. Three encoding attempts is the maximum, and the smallest valid overbudget candidate is retained if none meets budget; its `within_budget=false` status remains explicit.
