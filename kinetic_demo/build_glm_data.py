# -*- coding: utf-8 -*-
"""构建 GLM-5.3-Flash 讲解视频时间轴数据。

输入:items.json(11 段)、parts/item_XXXX.wav(CosyVoice 产物)
输出:glm_data.json——每段起止时间 + 逐字权重时间轴 + 场景主题。
播放顺序:[0..7] + [9,10](体感/钱包)+ [8](彩蛋)。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
FFPROBE = HERE.parents[0] / "work/video-tools/ffprobe.exe"
PARTS = HERE / "glm_video/parts"

ORDER = [0, 1, 2, 3, 4, 5, 6, 7, 9, 10]
LEAD_IN = 0.5     # 开头留白
GAP = 0.55        # 段间停顿

# 每个播放位置的场景配置:scene 名 + 主题色 + 底部小标签
SCENES = [
    ("title",    "#22d3ee", "开场"),
    ("moe",      "#34d399", "MoE 基本盘"),
    ("shrink",   "#60a5fa", "瘦身对比"),
    ("attn",     "#a78bfa", "混合注意力"),
    ("perf",     "#f472b6", "性能与成本"),
    ("vision",   "#fbbf24", "视觉闭环"),
    ("price",    "#fb923c", "价格"),
    ("summary",  "#38bdf8", "小结"),
    ("wallet_1", "#22d3ee", "用量体感"),
    ("wallet_2", "#34d399", "钱包解放"),
]


def tokenize(text):
    return re.findall(r"[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*|[\u4e00-\u9fff]|[0-9]+(?:\.[0-9]+)?|\s+|.", text)


def weight(tok):
    if re.fullmatch(r"[\u4e00-\u9fff]", tok):
        return 1.0
    if re.fullmatch(r"[A-Za-z0-9.\-]+", tok):
        return 0.85 * len(tok)
    if tok.strip() == "":
        return 0.25
    return 0.35


def split_cues(text, max_w=26.0):
    """切段→单行字幕条:先按句末标点切句,超宽句再按逗号等分块。"""
    sents, cur = [], ''
    for ch in text:
        cur += ch
        if ch in '。?!?!;；':
            sents.append(cur); cur = ''
    if cur.strip():
        sents.append(cur)

    def width(t):
        return sum(0.55 if c.isascii() else 1.0 for c in t)

    cues = []
    for sent in sents:
        if not sent.strip():
            continue
        if width(sent) <= max_w:
            cues.append(sent)
            continue
        # 按逗号/顿号/冒号切分,贪心聚合成 ≤max_w 的块
        parts, buf = [], ''
        for ch in sent:
            buf += ch
            if ch in ',,、:：——' and width(buf) >= max_w * 0.45:
                parts.append(buf); buf = ''
        if buf.strip():
            parts.append(buf)
        block = ''
        for piece in parts:
            if block and width(block) + width(piece) > max_w:
                cues.append(block); block = piece
            else:
                block += piece
        if block.strip():
            cues.append(block)
    return [c for c in cues if c.strip()]


def dur_of(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def main():
    items = {it["id"]: it for it in json.loads(
        (HERE / "glm_video/items.json").read_text(encoding="utf-8"))}
    segs, t = [], LEAD_IN
    import wave as _wave
    pcm_out, sr_ref = [], None
    for pos, sid in enumerate(ORDER):
        wav = HERE / "glm_video/parts16" / f"item_{sid:04d}.wav"
        d = dur_of(wav)
        with _wave.open(str(wav), "rb") as w:
            sr = w.getframerate()
            pcm = w.readframes(w.getnframes())
            nch, sw = w.getnchannels(), w.getsampwidth()
        assert sr_ref in (None, sr), f"sample rate mismatch @{sid}"
        sr_ref = sr
        if pos == 0:
            gap_bytes = int(sr * LEAD_IN) * nch * sw
            pcm_out.append(b"\x00" * gap_bytes)
        pcm_out.append(pcm)
        if pos < len(ORDER) - 1:
            pcm_out.append(b"\x00" * int(sr * GAP) * nch * sw)

        text = items[sid]["text"]
        pieces = split_cues(text)
        wsum = sum(weight(x) for p_ in pieces for x in tokenize(p_))
        sub = []
        acc = t
        for p_ in pieces:
            toks = tokenize(p_)
            pw = sum(weight(x) for x in toks)
            dur = d * pw / wsum
            sub.append({"start": round(acc, 3), "end": round(acc + dur, 3),
                        "text": p_})
            acc += dur
        scene, color, label = SCENES[pos]
        segs.append({"pos": pos, "id": sid, "start": round(t, 3),
                     "end": round(t + d, 3), "scene": scene,
                     "color": color, "label": label, "cues": sub})
        print(f"seg{pos:02d} id={sid} [{t:6.2f} -> {t+d:6.2f}] {text[:18]}…")
        t += d + GAP

    total = t - GAP + 3.0
    pcm_out.append(b"\x00" * int(sr_ref * 0.8) * nch * sw)
    audio = HERE / "glm_video/glm_audio.wav"
    with _wave.open(str(audio), "wb") as w:
        w.setnchannels(nch); w.setsampwidth(sw); w.setframerate(sr_ref)
        w.writeframes(b"".join(pcm_out))

    data = {"fps": 30, "duration": round(total, 3), "segments": segs}
    (HERE / "glm_data.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"total {data['duration']}s -> glm_data.json + glm_audio.wav")


if __name__ == "__main__":
    main()
