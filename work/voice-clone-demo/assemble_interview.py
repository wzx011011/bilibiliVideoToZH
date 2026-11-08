"""时间轴拼接:轮次配音按原片时间轴放置(超时槽 atempo 收紧,不足补静音)。"""

import json
import subprocess
import tempfile
from pathlib import Path

import torch
import torchaudio

PILOT = Path(__file__).resolve().parent / "interview-pilot"
FFMPEG = Path(__file__).resolve().parent.parent / "video-tools" / "ffmpeg.exe"
TOTAL = 2193.15   # 原片时长(秒)
ATEMPO_CAP = 1.25


def fit_wav(path: Path, atempo: float, sr: int) -> torch.Tensor:
    """atempo>1 时用 ffmpeg 提速(保音高);超上限则截断淡出。"""
    wav, wsr = torchaudio.load(str(path))
    if wsr != sr:
        wav = torchaudio.functional.resample(wav, wsr, sr)
    if atempo <= 1.001:
        return wav
    rate = min(atempo, ATEMPO_CAP)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp = Path(tf.name)
    subprocess.run([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(path), "-af", f"atempo={rate:.4f}",
                    "-ar", str(sr), str(tmp)], check=True)
    wav, _ = torchaudio.load(str(tmp))
    tmp.unlink()
    return wav


def main() -> None:
    manifest = json.loads((PILOT / "audio_manifest.json").read_text(encoding="utf-8"))
    ref_sr = torchaudio.load(str(PILOT / "parts" / f"turn_{manifest[0]['id']:02d}.wav"))[1]
    canvas = torch.zeros(1, int(TOTAL * ref_sr))

    placed, truncated, speedups = 0, 0, 0
    for m in manifest:
        wav = fit_wav(PILOT / "parts" / f"turn_{m['id']:02d}.wav", m["atempo"], ref_sr)
        dur = wav.shape[1] / ref_sr
        offset = int(m["start"] * ref_sr)
        slot_samples = int(m["slot"] * ref_sr)
        if wav.shape[1] > slot_samples:
            print(f"turn {m['id']:02d}: TRUNCATE {dur:.1f}s -> slot {m['slot']:.1f}s")
            fade = int(0.05 * ref_sr)
            wav[:, -fade:] *= torch.linspace(1, 0, fade)
            wav = wav[:, :slot_samples]
            truncated += 1
        if m["atempo"] > 1.001:
            speedups += 1
        end = min(offset + wav.shape[1], canvas.shape[1])
        canvas[:, offset:end] += wav[:, : end - offset]
        placed += 1

    out = PILOT / "interview-zh.wav"
    torchaudio.save(str(out), canvas, ref_sr)
    print(f"placed={placed} speedup={speedups} truncated={truncated} "
          f"total={canvas.shape[1]/ref_sr:.1f}s -> {out}")


if __name__ == "__main__":
    main()
