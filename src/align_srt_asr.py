"""用 ASR（faster-whisper）给现有字幕重新打时间戳。

问题：gen-srt 按字符比例估算时间戳，与豆包实际朗读节奏不匹配（字幕偏快）。
解决：对配音音频做中文 ASR，得到每句话的真实起止时间，替换估算时间戳。

流程：
  1. faster-whisper 识别配音音频 → [(start, end, text), ...] 带时间戳的片段
  2. 现有字幕（gen-srt 生成的）按 ASR 片段逐句对齐（文本相似度）
  3. 输出新的 SRT，时间戳来自 ASR，文本来自原字幕

用法：
  python align_srt_asr.py <音频> <原SRT> -o <输出SRT>
  python align_srt_asr.py episodes/ep-02/episode-02-audio.mp3 episodes/ep-02/episode-02.srt -o work/ep-02-asr.srt
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from difflib import SequenceMatcher


def parse_srt(srt_path: Path) -> list[tuple[float, float, str]]:
    """解析 SRT → [(start_sec, end_sec, text), ...]"""
    content = srt_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", content.strip())
    cues = []
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        time_match = re.match(
            r"(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)", lines[1])
        if not time_match:
            continue
        text = " ".join(lines[2:]).strip()
        cues.append((_to_sec(time_match.group(1)),
                     _to_sec(time_match.group(2)), text))
    return cues


def _to_sec(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _to_ts(sec: float) -> str:
    ms = round(sec * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe(audio_path: Path, model_size: str = "large-v3-turbo",
               language: str = "zh",
               cache_path: Path | None = None) -> list[tuple[float, float, str]]:
    """用 faster-whisper 识别音频，返回 [(start, end, text), ...]

    cache_path：若提供，识别结果缓存为 JSON，下次直接读取（省去重跑 ASR）。
    """
    # 优先读缓存
    if cache_path and cache_path.exists():
        import json
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"[ASR] 复用缓存：{len(data)} 段（{cache_path.name}）", file=sys.stderr)
        return [(d["start"], d["end"], d["text"]) for d in data]

    print(f"[ASR] 加载模型 {model_size}...", file=sys.stderr)
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    print(f"[ASR] 识别音频 {audio_path.name}（语言={language}）...", file=sys.stderr)
    segments, info = model.transcribe(
        str(audio_path), language=language, beam_size=5,
        vad_filter=True,  # 过滤静音段，加速识别
    )
    print(f"[ASR] 音频时长 {info.duration:.0f}s, 检测语言={info.language}",
          file=sys.stderr)

    results = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            results.append((seg.start, seg.end, text))
            if len(results) % 50 == 0:
                print(f"  [ASR] 已识别 {len(results)} 段...",
                      file=sys.stderr)
    print(f"[ASR] 完成：{len(results)} 段", file=sys.stderr)

    # 写缓存
    if cache_path:
        import json
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(
            [{"start": s, "end": e, "text": t} for s, e, t in results],
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ASR] 缓存已保存：{cache_path}", file=sys.stderr)

    return results


def similarity(a: str, b: str) -> float:
    """计算两段中文文本的相似度（0~1）。去掉标点和空格后比较。"""
    clean_a = re.sub(r"[\s，。、！？；：""''（）()【】\[\].,!?;:\"]", "", a)
    clean_b = re.sub(r"[\s，。、！？；：""''（）()【】\[\].,!?;:\"]", "", b)
    if not clean_a or not clean_b:
        return 0.0
    return SequenceMatcher(None, clean_a, clean_b).ratio()


def align(original_cues: list[tuple[float, float, str]],
           asr_segments: list[tuple[float, float, str]]
           ) -> list[tuple[float, float, str]]:
    """把原字幕文本对齐到 ASR 时间戳。

    策略：对每条原字幕，在 ASR 片段中找文本最相似的，
    用该 ASR 片段的起止时间作为新时间戳。
    为避免错位，采用时间邻近约束（只匹配时间接近的 ASR 片段）。

    当多条原字幕匹配到同一个 ASR 段时（ASR 把多句话合成了一段），
    按字符比例在该段内细分时间，保证字幕不重叠。
    """
    # 第一遍：每条原字幕找到最佳匹配的 ASR 段
    raw_matches = []  # [(asr_j, orig_text), ...]
    asr_idx = 0

    for orig_start, orig_end, orig_text in original_cues:
        best_score = 0.0
        best_j = asr_idx

        search_start = max(0, asr_idx - 2)
        search_end = min(len(asr_segments), asr_idx + 10)

        for j in range(search_start, search_end):
            score = similarity(orig_text, asr_segments[j][2])
            if score > best_score:
                best_score = score
                best_j = j

        if best_score > 0.3:
            raw_matches.append((best_j, orig_text))
            asr_idx = best_j + 1
        else:
            raw_matches.append((None, orig_text))  # 无匹配

    # 第二遍：处理同一 ASR 段被多条字幕匹配的情况
    aligned = []
    i = 0
    n = len(raw_matches)
    while i < n:
        asr_j, text = raw_matches[i]
        if asr_j is None:
            # 无匹配，保留原时间戳
            aligned.append((original_cues[i][0], original_cues[i][1], text))
            i += 1
            continue

        # 收集所有匹配到同一 ASR 段的连续字幕
        group = [i]
        while i + 1 < n and raw_matches[i + 1][0] == asr_j:
            group.append(i + 1)
            i += 1

        asr_start, asr_end, _ = asr_segments[asr_j]
        seg_duration = asr_end - asr_start

        if len(group) == 1:
            # 单条匹配，直接用 ASR 时间戳
            aligned.append((asr_start, asr_end, text))
        else:
            # 多条匹配同一 ASR 段：按字符比例细分
            texts = [original_cues[g][2] for g in group]
            weights = [_char_weight(t) for t in texts]
            total_w = sum(weights)
            cum = 0.0
            for g, w, t in zip(group, weights, texts):
                start_frac = cum / total_w
                cum += w
                end_frac = cum / total_w
                s = asr_start + start_frac * seg_duration
                e = asr_start + end_frac * seg_duration
                aligned.append((s, e, t))

        i += 1

    return aligned


def _char_weight(text: str) -> float:
    """字符权重（用于多条字幕落到同一 ASR 段时细分时间）。"""
    return max(float(len(text)), 1.0)


def write_srt(cues: list[tuple[float, float, str]], out_path: Path) -> None:
    """写 SRT 文件。"""
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{_to_ts(start)} --> {_to_ts(end)}")
        lines.append(text)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[✓] 输出 {len(cues)} 条字幕 → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="用 ASR 给字幕重新打时间戳（对齐到配音实际节奏）")
    parser.add_argument("audio", type=Path, help="配音音频文件")
    parser.add_argument("srt", type=Path, help="原字幕 SRT（gen-srt 生成的）")
    parser.add_argument("-o", "--output", type=Path, required=True,
                        help="输出 SRT 路径")
    parser.add_argument("--model", default="large-v3-turbo",
                        help="whisper 模型（默认 large-v3-turbo）")
    args = parser.parse_args()

    # 1. 读原字幕
    original_cues = parse_srt(args.srt)
    print(f"原字幕：{len(original_cues)} 条")

    # 2. ASR 识别（缓存到 audio 同目录的 .asr.json）
    cache_path = args.audio.with_suffix(args.audio.suffix + ".asr.json")
    asr_segments = transcribe(args.audio, model_size=args.model,
                              cache_path=cache_path)

    # 3. 对齐
    print("\n[对齐] 把原字幕文本匹配到 ASR 时间戳...", file=sys.stderr)
    aligned = align(original_cues, asr_segments)

    # 统计对齐质量
    matched = sum(1 for a, o in zip(aligned, original_cues) if a[0] != o[0])
    print(f"[对齐] {matched}/{len(aligned)} 条字幕获得了 ASR 时间戳",
          file=sys.stderr)

    # 4. 输出
    write_srt(aligned, args.output)


if __name__ == "__main__":
    main()
