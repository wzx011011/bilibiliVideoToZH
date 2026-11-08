# -*- coding: utf-8 -*-
"""构建 kinetic demo 数据:SRT 逐字时间轴 + 音频频谱能量 → demo_data.json

输入:Hinton 旁白版任务产物(字幕/说话人分段/音频),取 58s-118s 共 60s 窗口。
输出:kinetic_demo/demo_data.json,供 stage.html 逐帧渲染。
"""
from __future__ import annotations

import json
import re
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "work/studio/hinton-medicine-v2"
SRT = TASK / "03-中文字幕/hinton-中文旁白.srt"
RUNS = TASK / "work/runs.json"
AUDIO = Path(__file__).resolve().parent / "demo_audio.wav"  # 已切好的 60s

T0, T1 = 58.0, 118.0
FPS = 30
MAX_LINE = 13          # 竖屏每行最多字符数
N_SPEC = 24            # 波形环频谱条数


def parse_srt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)", lines[1])
        if not m:
            continue
        g = list(map(int, m.groups()))
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        cues.append({"start": start, "end": end, "text": "".join(lines[2:]).strip()})
    return cues


def char_weight(tok: str) -> float:
    if re.fullmatch(r"[\u4e00-\u9fff]", tok):
        return 1.0
    if tok.isascii() and tok.isalnum():
        return 0.85  # 英文按词元整体给权重
    if tok.strip() == "":
        return 0.25
    return 0.4  # 标点


def tokenize(text: str) -> list[str]:
    """中文按字、英文按词、空格/标点单独成元。"""
    return re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?|[\u4e00-\u9fff]|\s+|.", text)


def wrap_lines(tokens: list[str]) -> list[list[str]]:
    """按显示宽度折行(中文 1 宽、ASCII 词近似 0.6/字符)。"""
    lines, cur, w = [], [], 0.0
    for tok in tokens:
        tw = sum(0.6 if c.isascii() else 1.0 for c in tok)
        if w + tw > MAX_LINE and cur:
            while cur and cur[-1].strip() == "":
                cur.pop()
            lines.append(cur)
            cur, w = [], 0.0
            if tok.strip() == "":
                continue
        cur.append(tok)
        w += tw
    while cur and cur[-1].strip() == "":
        cur.pop()
    if cur:
        lines.append(cur)
    return lines


def build_cues(runs: list[dict]) -> list[dict]:
    out = []
    for cue in parse_srt(SRT):
        s, e = max(cue["start"], T0), min(cue["end"], T1)
        if e <= s:
            continue
        mid = (cue["start"] + cue["end"]) / 2
        spk = next((r["speaker"] for r in runs if r["start"] <= mid < r["end"]), "A")
        toks = tokenize(cue["text"])
        lines = wrap_lines(toks)
        # 逐元时间轴:cue 内按权重均分
        flat = [t for line in lines for t in line]
        wsum = sum(char_weight(t) for t in flat)
        chars, acc = [], s
        for t in flat:
            dur = (e - s) * char_weight(t) / wsum
            chars.append({"t": t, "s": acc, "e": acc + dur})
            acc += dur
        out.append({"start": s, "end": e, "speaker": spk, "lines": lines, "chars": chars})
    return out


def build_audio_frames() -> dict:
    with wave.open(str(AUDIO), "rb") as w:
        assert w.getframerate() == 48000 and w.getnchannels() == 1
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768

    sr, hop, nfft = 48000, 1600, 4800
    n_frames = int((T1 - T0) * FPS)
    win = np.hanning(nfft).astype(np.float32)
    freqs = np.fft.rfftfreq(nfft, 1 / sr)

    def band_mask(lo, hi):
        return (freqs >= lo) & (freqs < hi)

    bass_m, mid_m, treb_m = band_mask(40, 250), band_mask(250, 2000), band_mask(2000, 8000)
    spec_edges = np.exp(np.linspace(np.log(80), np.log(8000), N_SPEC + 1))
    spec_masks = [(freqs >= spec_edges[i]) & (freqs < spec_edges[i + 1]) for i in range(N_SPEC)]

    rms, bass, mid, treble, spec = [], [], [], [], []
    for i in range(n_frames):
        c = i * hop
        seg = x[c:c + nfft]
        if len(seg) < nfft:
            seg = np.pad(seg, (0, nfft - len(seg)))
        rms.append(float(np.sqrt(np.mean(seg ** 2))))
        mag = np.abs(np.fft.rfft(seg * win))
        def m(mask):
            v = float(np.sqrt(np.mean(mag[mask] ** 2))) if mask.any() else 0.0
            return v
        bass.append(m(bass_m)); mid.append(m(mid_m)); treble.append(m(treb_m))
        spec.append([min(1.0, m(mk) / 30) for mk in spec_masks])

    def norm(v):
        v = np.array(v, dtype=np.float32)
        p = max(np.percentile(v, 98), 1e-4)
        return np.clip(v / p, 0, 1)

    def punch(v, att=0.65, rel=0.30):
        out, env = [], 0.0
        for s in v:
            env = s if s > env else env * (1 - rel) + s * rel
            out.append(env)
        return out

    def ema(v, a=0.5):
        out, e = [], v[0]
        for s in v:
            e = a * s + (1 - a) * e
            out.append(e)
        return out

    return {
        "rms": [round(float(min(1, v * 3)), 3) for v in ema(norm(rms))],
        "bass": [round(float(v), 3) for v in punch(norm(bass))],
        "mid": [round(float(v), 3) for v in ema(norm(mid))],
        "treble": [round(float(v), 3) for v in ema(norm(treble))],
        "spec": [[round(v, 3) for v in row] for row in spec],
    }


def build_speaker_frames(runs: list[dict], n: int) -> list[int]:
    out = []
    for i in range(n):
        t = T0 + i / FPS
        spk = next((r["speaker"] for r in runs if r["start"] <= t < r["end"]), "A")
        out.append(0 if spk == "A" else 1)
    return out


def main():
    runs = json.loads(RUNS.read_text(encoding="utf-8"))
    n_frames = int((T1 - T0) * FPS)
    data = {
        "fps": FPS, "t0": T0, "duration": T1 - T0, "n_frames": n_frames,
        "speakers": ["主持人", "Hinton"],
        "cues": build_cues(runs),
        "speaker_frames": build_speaker_frames(runs, n_frames),
        **build_audio_frames(),
    }
    out = Path(__file__).resolve().parent / "demo_data.json"
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] {out.name}: {len(data['cues'])} cues, {n_frames} frames, "
          f"{out.stat().st_size // 1024}KB")


if __name__ == "__main__":
    main()
