"""访谈类视频处理库 —— 说话人分离、按角色分块、多音色朗读拼接。

设计要点:
- 输入是 faster-whisper 的 segments [(start, end, text), ...](英文或中文)。
- 说话人分离用"停顿边界 + 交替"启发式:双人访谈(A 访 B)中,换人几乎总伴随
  停顿;whisper 的 segment 边界天然贴近换人点。这是轻量方案(无 pyannote 依赖,
  CPU 友好),局限:同一说话人长停顿会被误判换人、两人无停顿抢话不识别。
  后续如需更准可替换为 pyannote.audio 声纹聚类,接口不变。
- 分块:按说话人合并成 turn(连续同人段),turn 文本超上限再切;每个块记录
  speaker,供 harvest 阶段选择音色。
- 多音色朗读:doubao_reader.read_reply 已支持 speaker 参数;这里按块顺序朗读、
  拼接成单个 mp3(封面式成片不需要贴合原片时间轴,顺序拼接即可)。

独立于 doubao_pipeline,不引入其依赖;faster_whisper 等 heavy import 全部
延迟到函数内,保证本模块可被 pipeline_admin / pytest 轻量加载。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# turn 边界判定:相邻 segment 之间的停顿超过该值视为可能的换人点
TURN_GAP_SEC = 1.2
# 单个发送块的最大字符数(与课程流水线的安全上限一致量级;豆包单次输入保守值)
MAX_CHUNK_CHARS = 1800
# 拼接时 turn 之间的静音间隔
TURN_GAP_MS = 300

# ======================== 说话人分离(启发式) ========================

def diarize_alternating(segments: list[tuple[float, float, str]],
                        speakers: int = 2) -> list[dict]:
    """把 whisper segments 聚合成 turns,双人交替启发式。

    返回 [{"speaker": "A", "start", "end", "text"}],按时间排序。
    speakers=1 时全部归 A(退化为单音色)。
    """
    if not segments:
        return []
    segs = sorted(segments, key=lambda s: s[0])

    if speakers <= 1:
        return [{"speaker": "A", "start": segs[0][0], "end": segs[-1][1],
                 "text": " ".join(s[2].strip() for s in segs if s[2].strip())}]

    # 1) 找出所有"换人候选点"(停顿 > TURN_GAP_SEC 的 segment 边界)
    #    第一段固定 A(访谈通常是主持人先说)
    turns: list[dict] = []
    cur_speaker = "A"
    cur_start = segs[0][0]
    cur_texts: list[str] = [segs[0][2].strip()] if segs[0][2].strip() else []

    for prev, nxt in zip(segs, segs[1:]):
        gap = nxt[0] - prev[1]
        if gap > TURN_GAP_SEC:
            turns.append({"speaker": cur_speaker, "start": cur_start,
                          "end": prev[1], "text": " ".join(cur_texts)})
            cur_speaker = "B" if cur_speaker == "A" else "A"
            cur_start = nxt[0]
            cur_texts = []
        if nxt[2].strip():
            cur_texts.append(nxt[2].strip())
    turns.append({"speaker": cur_speaker, "start": cur_start,
                  "end": segs[-1][1], "text": " ".join(cur_texts)})

    # 2) 相邻同人 turn 合并(交替启发式在"同 speaker 连续两个 turn"时
    #    说明中间的停顿不是换人 —— 但交替赋值下不会出现;保留防御性合并)
    merged: list[dict] = []
    for t in turns:
        if merged and merged[-1]["speaker"] == t["speaker"]:
            merged[-1]["end"] = t["end"]
            merged[-1]["text"] = (merged[-1]["text"] + " " + t["text"]).strip()
        else:
            merged.append(dict(t))
    return merged


# ======================== 分块(按说话人) ========================

def split_turn_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """单个 turn 文本超上限时按句末标点切分。"""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts = re.split(r"(?<=[.!?。？！])\s+", text)
    chunks, cur = [], ""
    for p in parts:
        if not p:
            continue
        if len(cur) + len(p) + 1 <= max_chars:
            cur = f"{cur} {p}".strip()
        else:
            if cur:
                chunks.append(cur)
            while len(p) > max_chars:  # 单句超长,硬切
                chunks.append(p[:max_chars])
                p = p[max_chars:]
            cur = p
    if cur:
        chunks.append(cur)
    return chunks


def build_chunks(turns: list[dict], max_chars: int = MAX_CHUNK_CHARS) -> list[dict]:
    """turns → 发送块。每个块记录 speaker 与来源 turn 的起止时间。"""
    chunks = []
    for t in turns:
        for piece in split_turn_text(t["text"], max_chars):
            if not piece:
                continue
            chunks.append({
                "chunk_index": len(chunks) + 1,
                "speaker": t["speaker"],
                "turn_start": t["start"],
                "turn_end": t["end"],
                "text": piece,
            })
    return chunks


# ======================== 提示词 ========================

# 英文源:翻译成口语中文(访谈语境)
PROMPT_EN = (
    "这是一段{role_cn}在英文访谈中的发言,需要你翻译成适合中文语音朗读的文本。\n\n"
    "请完成以下工作:\n"
    "1. 翻译成自然流畅的口语化中文,像中文访谈节目里嘉宾/主持人说话的语气\n"
    "2. 专有名词(人名/公司/产品)用通用中文译名,首次出现可在括号里保留英文\n"
    "3. 语气生动自然,不要书面腔,不要翻译腔\n\n"
    "【重要】直接输出翻译后的中文,第一句就是正文。"
    "禁止输出任何承诺、说明、确认,例如'好的''以下是翻译'。"
    "你的回复只能包含翻译后的中文文本本身。\n\n"
    "待翻译的发言:\n\n{text}"
)

# 中文源:润色断句(与课程流水线同思路,访谈语气)
PROMPT_ZH = (
    "这是一段{role_cn}在中文访谈中的发言,需要你处理成适合语音朗读的文本。\n\n"
    "请完成以下工作:\n"
    "1. 给文字加上正确的标点,让朗读者知道在哪里停顿断句\n"
    "2. 微调措辞使语句更通顺自然,但不要增删实质内容\n"
    "3. 语气生动自然,像访谈节目中说话的感觉\n\n"
    "【重要】直接输出处理后的文本,第一句就是正文。"
    "禁止输出任何承诺、说明、确认。你的回复只能包含朗读文本本身。\n\n"
    "待处理的发言:\n\n{text}"
)


def build_prompt(text: str, speaker: str, lang: str,
                 role_names: dict[str, str] | None = None) -> str:
    """生成发送给豆包的提示词。lang=en 翻译,lang=zh 润色。

    默认角色:A=主持人(先开口),B=嘉宾;可用 role_names 覆盖。
    """
    roles = role_names or {}
    role_cn = roles.get(speaker, "主持人" if speaker == "A" else "嘉宾")
    tpl = PROMPT_EN if lang == "en" else PROMPT_ZH
    return tpl.format(role_cn=role_cn, text=text)


# ======================== 朗读与拼接 ========================

def harvest_multi_voice(chunks: list[dict], replies: list[dict],
                        out_dir: Path, speakers_map: dict[str, str],
                        out_audio: Path) -> dict:
    """按块顺序朗读豆包回复并拼接成单个音频。

    - replies: 与 chunks 一一对应的豆包回复对象(来自 doubao_reader 消息列表,
      顺序匹配:扩展按块顺序发送,回复按顺序返回)。
    - speakers_map: {"A": 音色ID, "B": 音色ID};缺失时回退默认桃桃。
    """
    import asyncio
    import doubao_reader as dr

    if len(replies) != len(chunks):
        raise RuntimeError(
            f"回复数({len(replies)})与分块数({len(chunks)})不一致,拒绝生成")

    ogg_dir = out_dir / "clips"
    ogg_dir.mkdir(parents=True, exist_ok=True)
    ogg_paths: list[Path] = []
    for i, (chunk, reply) in enumerate(zip(chunks, replies), 1):
        ogg = ogg_dir / f"{i:04d}.ogg"
        speaker = speakers_map.get(chunk["speaker"]) or None
        n = asyncio.run(dr.read_reply(reply, str(ogg), verbose=True,
                                      speaker=speaker))
        if n <= 0:
            raise RuntimeError(f"第 {i} 块朗读无音频产出(speaker={chunk['speaker']})")
        ogg_paths.append(ogg)

    concat_with_gap(ogg_paths, out_audio, TURN_GAP_MS)
    return {"audio": str(out_audio), "clips": len(ogg_paths)}


def concat_with_gap(ogg_paths: list[Path], out_path: Path, gap_ms: int) -> None:
    """顺序拼接 ogg 片段,turn 之间插入静音,导出 mp3。"""
    from pydub import AudioSegment

    silence = AudioSegment.silent(duration=gap_ms)
    combined = AudioSegment.empty()
    for i, p in enumerate(ogg_paths):
        seg = AudioSegment.from_file(p)
        combined += seg if i == 0 else silence + seg
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(out_path), format="mp3", bitrate="128k")


# ======================== 工件读写 ========================

def save_turns(turns: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(turns, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def load_turns(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))
