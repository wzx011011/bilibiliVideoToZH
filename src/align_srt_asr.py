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
    # 关键约束：ASR 游标只往后走，不允许回溯（否则时间戳会倒退导致重叠）
    raw_matches = []  # [(asr_j, orig_text), ...]
    asr_idx = 0

    for orig_start, orig_end, orig_text in original_cues:
        best_score = 0.0
        best_j = -1

        # 只往后搜索，不允许回溯到已用过的 ASR 段
        search_start = asr_idx
        search_end = min(len(asr_segments), asr_idx + 10)

        for j in range(search_start, search_end):
            score = similarity(orig_text, asr_segments[j][2])
            if score > best_score:
                best_score = score
                best_j = j

        if best_score > 0.3 and best_j >= 0:
            raw_matches.append((best_j, orig_text))
            asr_idx = best_j + 1
        else:
            # 无匹配：不推进游标，后续字幕仍能搜索全部 ASR 段
            raw_matches.append((None, orig_text))

    # 第二遍：处理同一 ASR 段被多条字幕匹配的情况
    # 关键：多条字幕匹配同一 ASR 段时，合并成一条，用 ASR 段的完整时间戳。
    # 因为豆包朗读是一整段连读，字幕按标点分开会在语音还在说前半句时就显示后半句。
    # 第二遍：构建已匹配锚点，对无匹配字幕做时间插值
    # 锚点 = (orig_index, asr_start, asr_end)
    anchors = []
    for idx, (asr_j, _) in enumerate(raw_matches):
        if asr_j is not None:
            anchors.append((idx, asr_segments[asr_j][0], asr_segments[asr_j][1]))

    aligned = list(original_cues)  # 先复制原时间戳，后面替换已匹配的

    # 替换已匹配的字幕（含合并逻辑）
    i = 0
    n = len(raw_matches)
    replacements = {}  # orig_index → (start, end, text)
    while i < n:
        asr_j, text = raw_matches[i]
        if asr_j is None:
            i += 1
            continue
        group_indices = [i]
        group_texts = [text]
        while i + 1 < n and raw_matches[i + 1][0] == asr_j:
            group_indices.append(i + 1)
            group_texts.append(raw_matches[i + 1][1])
            i += 1

        asr_start, asr_end, _ = asr_segments[asr_j]
        merged_text = " ".join(group_texts)

        # 检查 ASR 段是否异常长（可能匹配错误）
        char_count = len(re.sub(r'[^\u4e00-\u9fff\w]', '', merged_text))
        expected_dur = max(char_count / 4.0, 1.0)  # 4字/秒
        actual_dur = asr_end - asr_start

        if actual_dur > expected_dur * 4:
            # 异常长：视为误匹配，当作无匹配处理（留给插值逻辑）
            # 不放入 replacements，让插值逻辑处理
            i += 1
            continue

        # 正常：第一条用完整时间段，其余条标记为待删除
        replacements[group_indices[0]] = (asr_start, asr_end, merged_text)
        for gi in group_indices[1:]:
            replacements[gi] = None  # 合并掉了
        i += 1

    # 对无匹配字幕：在前后锚点间按字符比例插值时间
    for idx in range(len(raw_matches)):
        if idx in replacements:
            continue
        if replacements.get(idx) is None:
            continue
        # 找前一个锚点
        prev_anchor = None
        for a in anchors:
            if a[0] < idx:
                prev_anchor = a
            else:
                break

        # 如果无匹配字幕的原始时间戳落在前锚点 ASR 段内，合并到前锚点
        orig_start = original_cues[idx][0]
        if prev_anchor:
            pa_start, pa_end = asr_segments[
                raw_matches[prev_anchor[0]][0]][0], asr_segments[
                raw_matches[prev_anchor[0]][0]][1]
            # 允许一定误差（原始时间戳可能不准）
            if pa_start - 2 <= orig_start <= pa_end + 2:
                # 合并到前锚点对应的已匹配字幕
                if prev_anchor[0] in replacements and replacements[prev_anchor[0]] is not None:
                    old_s, old_e, old_t = replacements[prev_anchor[0]]
                    replacements[prev_anchor[0]] = (old_s, old_e, old_t + " " + original_cues[idx][2])
                    replacements[idx] = None  # 标记为合并
                    continue

        # 找后一个锚点
        next_anchor = None
        for a in anchors:
            if a[0] > idx:
                next_anchor = a
                break
        # 找后一个锚点
        next_anchor = None
        for a in anchors:
            if a[0] > idx:
                next_anchor = a
                break
        if prev_anchor and next_anchor:
            # 在两个锚点间按字符比例分配时间
            gap_start = prev_anchor[2]  # 前锚点 ASR 段结束
            gap_end = next_anchor[1]    # 后锚点 ASR 段开始
            # 收集这个区间内所有无匹配字幕
            group = []
            j = idx
            while j < next_anchor[0]:
                if j not in replacements or replacements.get(j) is not None:
                    if raw_matches[j][0] is None:
                        group.append(j)
                j += 1
            if group:
                texts = [original_cues[g][2] for g in group]
                weights = [max(len(re.sub(r'[^\u4e00-\u9fff\w]', '', t)), 1.0) for t in texts]
                total_w = sum(weights)
                cum = 0.0
                for g, w in zip(group, weights):
                    frac = cum / total_w
                    cum += w
                    end_frac = cum / total_w
                    s_time = gap_start + frac * (gap_end - gap_start)
                    e_time = gap_start + end_frac * (gap_end - gap_start)
                    replacements[g] = (s_time, e_time, original_cues[g][2])

    # 应用替换，跳过被合并的
    final = []
    for idx in range(len(original_cues)):
        if idx in replacements:
            r = replacements[idx]
            if r is not None:
                final.append(r)
        else:
            final.append(original_cues[idx])

    return final


def write_srt(cues: list[tuple[float, float, str]], out_path: Path) -> None:
    """写 SRT 文件。

    - 强制时间戳单调递增（不允许重叠，否则播放器会同时显示多条）
    - 延长每条字幕的结束时间到下一条开始前 0.1s，避免消失太快看不全
    """
    lines = []
    n = len(cues)
    max_end = 0.0
    for i, (start, end, text) in enumerate(cues, 1):
        # 强制单调递增：start 不能小于上一条的 end
        start = max(start, max_end)
        # 延长结束时间：到下一条开始前 0.1s，但不超过原时长的 3 倍
        # （避免 gen-srt 时间戳和 ASR 时间戳混用时产生超长字幕）
        orig_dur = end - start
        if i < n:
            next_start = cues[i][0]
            extended = next_start - 0.1
            max_allowed = start + max(orig_dur * 3, 5.0)  # 至少允许延长到 5s
            end = min(max(end, extended), max_allowed)
        end = max(end, start + 0.5)  # 至少显示 0.5s
        max_end = end
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
    parser.add_argument("srt", type=Path, nargs="?", default=None,
                        help="原字幕 SRT（gen-srt 生成的）。--asr-only 时不需要")
    parser.add_argument("-o", "--output", type=Path, required=True,
                        help="输出 SRT 路径")
    parser.add_argument("--model", default="large-v3-turbo",
                        help="whisper 模型（默认 large-v3-turbo）")
    parser.add_argument("--asr-only", action="store_true",
                        help="直接用 ASR 识别文本做字幕（不引用原字幕，最准）")
    args = parser.parse_args()

    # ASR 识别（缓存到 audio 同目录的 .asr.json）
    cache_path = args.audio.with_suffix(args.audio.suffix + ".asr.json")
    asr_segments = transcribe(args.audio, model_size=args.model,
                              cache_path=cache_path)

    if args.asr_only:
        # 直接用 ASR 结果做字幕（时间戳和文本都来自语音识别，最准）
        cues = [(s, e, t) for s, e, t in asr_segments if t.strip()]
        print(f"ASR-only 模式：{len(cues)} 条字幕（直接来自语音识别）")
        write_srt(cues, args.output)
        return

    if not args.srt:
        sys.exit("[✗] 非 --asr-only 模式需要提供原字幕 SRT")

    # 1. 读原字幕
    original_cues = parse_srt(args.srt)
    print(f"原字幕：{len(original_cues)} 条")

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
