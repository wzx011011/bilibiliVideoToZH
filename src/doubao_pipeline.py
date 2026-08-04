"""豆包朗读配音流水线 —— 半自动分块 + 比例切割。

绕过豆包发消息的 a_bogus 签名风控：由用户在浏览器手动发送分块字幕（带
浏览器原生签名），脚本只负责朗读已生成的回复 + 按字符比例切割成编号 mp3。

工作流（每集）：
  1. prep     读 zh-CN.srt → 按 chunk-size 条/块拼成带提示词的文本块
              → 输出 chunks/01.txt、02.txt... + chunks/manifest.json
  2. 用户     在豆包网页手动发送每个文本块（浏览器原生签名，不被风控）
  3. harvest  列出最近回复 → 用户确认序号 → 逐个朗读 → ogg
  4. split    每个长 ogg 按字符比例 + 安全余量切割 → clips/0001.mp3 ...
  5. pipeline dub_pipeline.py --external-clips-dir clips/ 收尾对齐封装

用法：
  python doubao_pipeline.py prep <zh-CN.srt> --chunks-dir chunks/ [--chunk-size 60]
  python doubao_pipeline.py harvest --chunks-dir chunks/ --clips-dir clips/
  python doubao_pipeline.py split --chunks-dir chunks/ --clips-dir clips/

依赖：doubao_reader.py（同目录）+ ffmpeg（work/video-tools/）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# 复用 doubao_reader 的配置加载和朗读/列表函数
import doubao_reader as dr

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"

# 提示词：让豆包断句加标点，以心理学讲师的语气自然朗读。
# 针对课程内容优化：亲切、娓娓道来、引人入胜，让人听得进去。
PROMPT_TEMPLATE = (
    "这是一段哈佛大学《积极心理学》课程的中文字幕，需要你帮忙处理成适合语音朗读的文本。\n\n"
    "请完成以下工作：\n"
    "1. 给文字加上正确的标点符号（逗号、句号、问号等），让朗读者知道在哪里停顿断句\n"
    "2. 微调措辞使语句更通顺自然，但不要增删实质内容\n"
    "3. 语气要亲切温暖、娓娓道来，像一位耐心的老师在和学生聊天，"
    "让听众感到被鼓励、愿意听下去。语速适中偏慢，在句号处充分停顿\n\n"
    "你的回复只能包含处理好的朗读文本本身，"
    "不要加\"好的\"\"以下是\"等任何前后缀和解释。\n\n"
    "待处理的字幕文字：\n\n{text}"
)


# =====================================================================
# SRT 解析
# =====================================================================

def parse_srt(srt_path: Path) -> list[dict]:
    """解析 SRT，返回 [{start, end, text}, ...]，start/end 为秒。"""
    content = srt_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", content.strip())
    cues = []
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        # 第1行序号，第2行时间戳，第3行起文本
        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
            lines[1],
        )
        if not time_match:
            continue
        text = " ".join(lines[2:]).strip()
        cues.append({
            "start": _srt_time_to_seconds(time_match.group(1)),
            "end": _srt_time_to_seconds(time_match.group(2)),
            "text": text,
        })
    return cues


def _srt_time_to_seconds(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


# =====================================================================
# 阶段 1：prep —— SRT 分块
# =====================================================================

def cmd_prep(args: argparse.Namespace) -> None:
    srt_path: Path = args.srt
    chunks_dir: Path = args.chunks_dir
    chunk_size: int = args.chunk_size

    cues = parse_srt(srt_path)
    if not cues:
        sys.exit(f"[✗] SRT 无有效字幕: {srt_path}")

    # --limit：只取前 N 条字幕（用于小规模端到端验证，避免处理全集）
    if args.limit:
        cues = cues[:args.limit]

    chunks_dir.mkdir(parents=True, exist_ok=True)

    # 分块：每 chunk_size 条拼一块
    chunks_meta = []
    for i in range(0, len(cues), chunk_size):
        chunk_cues = cues[i:i + chunk_size]
        chunk_idx = len(chunks_meta) + 1
        # 拼文本：每条字幕之间加空格（豆包朗读会自然停顿）
        joined_text = " ".join(c["text"] for c in chunk_cues)
        prompt = PROMPT_TEMPLATE.format(text=joined_text)

        txt_path = chunks_dir / f"{chunk_idx:02d}.txt"
        txt_path.write_text(prompt, encoding="utf-8")

        chunks_meta.append({
            "chunk_index": chunk_idx,
            "cue_start": i + 1,          # 1-based，对应 clips 编号
            "cue_end": i + len(chunk_cues),
            "cue_count": len(chunk_cues),
            "texts": [c["text"] for c in chunk_cues],
            "txt_file": txt_path.name,
        })

    manifest = {
        "srt_source": str(srt_path),
        "total_cues": len(cues),
        "chunk_size": chunk_size,
        "total_chunks": len(chunks_meta),
        "chunks": chunks_meta,
    }
    manifest_path = chunks_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[✓] prep 完成：{len(cues)} 条字幕 → {len(chunks_meta)} 块")
    print(f"    目录：{chunks_dir}")
    print(f"    清单：{manifest_path.name}")
    print()
    print("下一步：在豆包网页依次发送每个 .txt 的内容（全部复制粘贴发送），")
    print("       然后运行 harvest 抓取并朗读这些回复。")


# =====================================================================
# 阶段 2：harvest —— 列回复 → 朗读
# =====================================================================

def cmd_harvest(args: argparse.Namespace) -> None:
    chunks_dir: Path = args.chunks_dir
    clips_dir: Path = args.clips_dir

    manifest = _load_manifest(chunks_dir)
    total_chunks = manifest["total_chunks"]

    print(f"正在拉取最近的豆包回复（需要最近的 {total_chunks} 条是你发送的字幕块）...")
    try:
        replies = _fetch_all_recent_replies()
    except Exception as e:
        sys.exit(f"[✗] 拉取失败: {e}\n    常见原因：cookie 失效")

    if not replies:
        sys.exit("[✗] 没拉到任何回复")

    print(f"\n找到 {len(replies)} 条豆包回复（按时间倒序）:\n")
    print(f"{'序号':<5} {'时间':<19} {'预览':<60}")
    print("-" * 85)
    for i, r in enumerate(replies):
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["create_time"]))
        prev = _preview(r["brief"] or r["tts_content"], 55)
        print(f"{i + 1:<5} {t:<19} {prev}")

    print(f"\n请输入要朗读的回复序号（对应你发送的 {total_chunks} 个字幕块，"
          f"用逗号分隔，如 1,2,3）：")
    raw = input("> ").strip()
    try:
        indices = [int(x.strip()) for x in raw.split(",")]
    except ValueError:
        sys.exit("[✗] 无效的序号输入")

    if len(indices) != total_chunks:
        print(f"[!] 警告：manifest 需要 {total_chunks} 块，你选了 {len(indices)} 个。"
              " 继续按你选的为准。")

    chunks_dir.mkdir(parents=True, exist_ok=True)
    selected = []
    for order, idx in enumerate(indices, 1):
        if idx < 1 or idx > len(replies):
            print(f"[✗] 序号 {idx} 超出范围，跳过")
            continue
        r = replies[idx - 1]
        ogg_path = chunks_dir / f"{order:02d}.ogg"
        print(f"\n[{order}/{len(indices)}] 朗读 message_id={r['message_id']}")
        print(f"    预览: {_preview(r['tts_content'], 50)}")
        n = asyncio.run(dr.read_reply(r, str(ogg_path)))
        if n:
            print(f"    [✓] {ogg_path.name} ({n / 1024:.1f} KB)")
            selected.append(order)
            # 保存豆包回复的带标点文本（作为字幕内容）
            for c in manifest["chunks"]:
                if c["chunk_index"] == order:
                    c["tts_content"] = r["tts_content"]
                    break
        else:
            print(f"    [✗] 未收到音频（可能刚读过被去重，等 1-2 分钟再试）")
        if order < len(indices):
            time.sleep(2)

    # 更新 manifest 记录哪些块已朗读成功
    manifest["harvested_chunks"] = selected
    (chunks_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n[✓] harvest 完成：{len(selected)}/{len(indices)} 块朗读成功")
    print("下一步：运行 split 把 ogg 切成编号 mp3。")


# =====================================================================
# 阶段 3：split —— 字符比例切割
# =====================================================================

def _char_weight(text: str) -> float:
    """字幕的朗读时长权重：字符数 + 标点加权。

    标点（逗号/句号/顿号等）会带来停顿，适当增加权重。
    """
    weight = float(len(text))
    # 中文标点加权（停顿）：句号/问号/感叹号 +0.5，逗号/顿号/分号 +0.3
    weight += len(re.findall(r"[。？！]", text)) * 0.5
    weight += len(re.findall(r"[，、；]", text)) * 0.3
    return max(weight, 1.0)


def _probe_duration(path: Path) -> float:
    """探测音频时长。豆包 ogg 流拼接有复用瑕疵，ffprobe 可能返回 N/A，
    此时先转 wav 再探测。"""
    r = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    out = r.stdout.strip()
    if out and out != "N/A":
        return float(out)
    # ogg 探测失败 → 转 wav 再探测
    wav_tmp = path.with_suffix(".probe.wav")
    subprocess.run(
        [str(FFMPEG), "-y", "-loglevel", "error",
         "-i", str(path), str(wav_tmp)],
        capture_output=True, check=True,
    )
    r2 = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(wav_tmp)],
        capture_output=True, text=True, check=True,
    )
    dur = float(r2.stdout.strip())
    wav_tmp.unlink(missing_ok=True)
    return dur


def _split_one_ogg(ogg: Path, texts: list[str], out_dir: Path,
                   start_index: int, safety_ms: float = 120) -> list[Path]:
    """把一个 ogg 按字符比例切成 len(texts) 个 mp3，编号从 start_index 起。

    safety_ms：安全余量，每个片段前后各留一点，避免边界吞字。
    """
    total = _probe_duration(ogg)
    weights = [_char_weight(t) for t in texts]
    total_weight = sum(weights)

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    cum_weight = 0.0
    for i, w in enumerate(weights):
        start_frac = cum_weight / total_weight
        cum_weight += w
        end_frac = cum_weight / total_weight

        safety = safety_ms / 1000
        start_s = max(0.0, start_frac * total - safety)
        end_s = min(total, end_frac * total + safety)
        # 保证最小时长，避免 ffmpeg 报错
        if end_s - start_s < 0.1:
            end_s = start_s + 0.1

        out_index = start_index + i
        out_path = out_dir / f"{out_index:04d}.mp3"
        subprocess.run(
            [str(FFMPEG), "-y", "-loglevel", "error",
             "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}",
             "-i", str(ogg),
             "-codec:a", "libmp3lame", "-b:a", "192k",
             str(out_path)],
            capture_output=True, check=True,
        )
        results.append(out_path)
    return results


def cmd_split(args: argparse.Namespace) -> None:
    chunks_dir: Path = args.chunks_dir
    clips_dir: Path = args.clips_dir

    manifest = _load_manifest(chunks_dir)
    harvested = manifest.get("harvested_chunks", [])
    if not harvested:
        sys.exit("[✗] manifest 未记录已朗读的块，请先运行 harvest")

    clips_dir.mkdir(parents=True, exist_ok=True)
    total_mp3 = 0

    for chunk in manifest["chunks"]:
        idx = chunk["chunk_index"]
        if idx not in harvested:
            print(f"[跳过] 块 {idx:02d} 未朗读")
            continue
        ogg = chunks_dir / f"{idx:02d}.ogg"
        if not ogg.exists():
            print(f"[跳过] 块 {idx:02d} 的 ogg 不存在: {ogg}")
            continue

        print(f"[块 {idx:02d}] 切割 {chunk['cue_count']} 条 "
              f"(字幕 {chunk['cue_start']}-{chunk['cue_end']})...")
        mp3s = _split_one_ogg(
            ogg, chunk["texts"], clips_dir, chunk["cue_start"],
            safety_ms=args.safety_ms,
        )
        total_mp3 += len(mp3s)
        print(f"        → {len(mp3s)} 个 mp3")

    print(f"\n[✓] split 完成：共 {total_mp3} 个 mp3 → {clips_dir}")
    print(f"    期望总数：{manifest['total_cues']}")
    if total_mp3 != manifest["total_cues"]:
        print(f"    [!] 警告：数量不一致，检查是否有块未朗读")
    print()
    print("下一步：用 dub_pipeline.py --external-clips-dir 收尾：")
    print(f"  python dub_pipeline.py ... --external-clips-dir {clips_dir}")


# =====================================================================
# 阶段 4：gen-srt —— 按豆包朗读节奏生成字幕
# =====================================================================

# 句子结束标点（在这些标点处分句）
_SENTENCE_END = re.compile(r"[。？！；\n]")
# 句内停顿标点（也可作为较短字幕的分界）
_CLAUSE_END = re.compile(r"[，、：]")


def _split_into_lines(text: str, max_chars: int = 40) -> list[str]:
    """把带标点的朗读文本分成适合字幕显示的行。

    优先在句号/问号/感叹号处断句；过长则在逗号处断；仍过长则硬切。
    每行不超过 max_chars 字符（字幕可读性）。
    """
    # 先按句子结束标点分句
    parts = _SENTENCE_END.split(text)
    puncts = _SENTENCE_END.findall(text)
    sentences = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        # 补回句末标点
        if i < len(puncts):
            part += puncts[i]
        sentences.append(part)

    # 对每个句子，若超过 max_chars，按逗号再分
    lines = []
    for sent in sentences:
        if len(sent) <= max_chars:
            lines.append(sent)
        else:
            # 按逗号分
            sub_parts = _CLAUSE_END.split(sent)
            sub_puncts = _CLAUSE_END.findall(sent)
            cur = ""
            for j, sub in enumerate(sub_parts):
                if j < len(sub_puncts):
                    sub += sub_puncts[j]
                if len(cur) + len(sub) <= max_chars:
                    cur += sub
                else:
                    if cur:
                        lines.append(cur)
                    # 单个子句仍超长，硬切
                    while len(sub) > max_chars:
                        lines.append(sub[:max_chars])
                        sub = sub[max_chars:]
                    cur = sub
            if cur:
                lines.append(cur)
    return lines


def _char_weight_srt(text: str) -> float:
    """字幕时长权重：字符数 + 标点停顿加权。"""
    w = float(len(text))
    w += len(_SENTENCE_END.findall(text)) * 0.4
    w += len(_CLAUSE_END.findall(text)) * 0.2
    return max(w, 1.0)


def cmd_gen_srt(args: argparse.Namespace) -> None:
    """按豆包朗读音频的实际节奏生成字幕 SRT。

    每块的 tts_content（带标点）按可读行宽分句，结合该块音频时长，
    按字符比例估算每句的起止时间。最终 SRT 的时间轴贴合朗读节奏。
    """
    chunks_dir: Path = args.chunks_dir
    srt_path: Path = args.output

    manifest = _load_manifest(chunks_dir)
    harvested = manifest.get("harvested_chunks", [])
    if not harvested:
        sys.exit("[✗] manifest 未记录已朗读的块，请先运行 harvest")

    all_entries = []  # [(start_sec, end_sec, text), ...]
    time_offset = 0.0  # 累计时间偏移（每块音频首尾相接）

    for chunk in manifest["chunks"]:
        idx = chunk["chunk_index"]
        if idx not in harvested:
            continue
        tts = chunk.get("tts_content", "")
        if not tts:
            print(f"[跳过] 块{idx:02d} 无 tts_content")
            continue

        # 该块音频时长
        wav = chunks_dir / f"{idx:02d}.wav"
        ogg = chunks_dir / f"{idx:02d}.ogg"
        audio = wav if wav.exists() else ogg
        if not audio.exists():
            print(f"[跳过] 块{idx:02d} 音频不存在")
            continue
        duration = _probe_duration(audio)

        # 分句
        lines = _split_into_lines(tts, max_chars=args.max_chars)
        weights = [_char_weight_srt(l) for l in lines]
        total_weight = sum(weights)

        cum = 0.0
        for line, w in zip(lines, weights):
            start_frac = cum / total_weight
            cum += w
            end_frac = cum / total_weight
            start_s = time_offset + start_frac * duration
            end_s = time_offset + end_frac * duration
            all_entries.append((start_s, end_s, line))

        time_offset += duration
        print(f"[块{idx:02d}] {len(lines)} 句, {duration:.1f}s")

    # 写 SRT
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_lines = []
    for i, (start, end, text) in enumerate(all_entries, 1):
        srt_lines.append(str(i))
        srt_lines.append(f"{_sec_to_srt(start)} --> {_sec_to_srt(end)}")
        srt_lines.append(text)
        srt_lines.append("")
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    print(f"\n[✓] gen-srt 完成：{len(all_entries)} 条字幕 → {srt_path}")
    print(f"    总时长：{time_offset:.0f}s ({time_offset / 60:.1f}分钟)")


def _sec_to_srt(sec: float) -> str:
    """秒 → SRT 时间戳 HH:MM:SS,mmm"""
    ms = round(sec * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# =====================================================================
# 工具函数
# =====================================================================

def _load_manifest(chunks_dir: Path) -> dict:
    manifest_path = chunks_dir / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"[✗] manifest 不存在: {manifest_path}，请先运行 prep")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _fetch_all_recent_replies(conv_limit: int = 30, per_conv: int = 15) -> list[dict]:
    """拉多个会话的回复，扁平化去重后按时间倒序返回。

    dr.fetch_messages 默认只覆盖少数会话；用户发的新字幕块可能在新建会话里。
    这里拉更多会话、每会话取最近几条，跨会话合并后统一排序。
    """
    import requests
    import uuid

    params = {
        "version_code": "20800", "language": "zh", "device_platform": "web",
        "doubao_device_platform": "web", "aid": "497858", "real_aid": "497858",
        "device_id": dr.DEVICE_ID, "web_id": dr.WEB_ID,
        "tea_uuid": dr.TEA_UUID, "web_tab_id": dr.WEB_TAB_ID,
        "region": "CN", "sys_region": "CN", "samantha_web": "1",
        "web_platform": "browser", "use-olympus-account": "1",
        "pc_version": "3.29.14", "pkg_type": "release_version",
    }
    data = {
        "cmd": 3200,
        "uplink_body": {"pull_recent_conv_chain_uplink_body": {
            "limit": conv_limit, "message_count_per_conv": per_conv,
            "api_version": 1, "conv_version": 0, "direction": 3,
            "option": {
                "not_need_message": False, "need_complete_conversation": True,
                "need_coco_conversation": True, "need_coco_bot": True,
                "need_pc_pin_chain": True, "pc_pin_query_type": 0,
            },
        }},
        "sequence_id": str(uuid.uuid4()), "channel": 2, "version": "1",
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "agw-js-conv": "str",
        "content-type": "application/json; encoding=utf-8",
        "origin": "https://www.doubao.com",
        "referer": "https://www.doubao.com/",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0"),
        "cookie": dr.COOKIE,
    }
    r = requests.post(
        "https://www.doubao.com/im/chain/recent_conv",
        params=params, headers=headers, json=data, timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("status_code") != 0:
        raise RuntimeError(f"接口错误: {d.get('status_desc')}")

    cells = d["downlink_body"]["pull_recent_conv_chain_downlink_body"]["cells"]
    seen_ids: set[str] = set()
    replies: list[dict] = []
    for cell in cells:
        conv = cell.get("conversation") or {}
        if isinstance(conv, str):
            try:
                conv = json.loads(conv)
            except json.JSONDecodeError:
                continue
        conv_id = conv.get("conversation_id", "")
        for m in conv.get("messages", []):
            if str(m.get("user_type")) != "2":  # 只取豆包回复
                continue
            mid = str(m.get("message_id", ""))
            if not mid or mid in seen_ids:
                continue
            ext = m.get("ext") or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except json.JSONDecodeError:
                    ext = {}
            ruk = ext.get("reply_unique_key", "")
            if not ruk:
                continue
            seen_ids.add(mid)
            try:
                ct = int(m.get("create_time", 0))
            except (TypeError, ValueError):
                ct = 0
            replies.append({
                "message_id": mid,
                "bot_reply_message_id": str(m.get("bot_reply_message_id", "")),
                "conversation_id": str(conv_id),
                "section_id": str(m.get("section_id", "")),
                "reply_unique_key": ruk,
                "tts_content": (m.get("tts_content") or "").strip(),
                "brief": (m.get("brief") or "").strip(),
                "create_time": ct,
            })
    replies.sort(key=lambda x: x["create_time"], reverse=True)
    return replies


def _preview(text: str, n: int = 80) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:n] + ("…" if len(t) > n else "")


# =====================================================================
# CLI
# =====================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="豆包朗读配音流水线：prep → harvest → split")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prep", help="读 SRT 分块，生成待发送的文本块")
    p_prep.add_argument("srt", type=Path, help="中文字幕 SRT 文件")
    p_prep.add_argument("--chunks-dir", type=Path, default=Path("chunks"),
                        help="分块输出目录（默认 chunks/）")
    p_prep.add_argument("--chunk-size", type=int, default=60,
                        help="每块字幕条数（默认 60）")
    p_prep.add_argument("--limit", type=int, default=None,
                        help="只取前 N 条字幕（用于端到端验证，默认全部）")

    p_harvest = sub.add_parser("harvest", help="抓取并朗读豆包回复")
    p_harvest.add_argument("--chunks-dir", type=Path, default=Path("chunks"))
    p_harvest.add_argument("--clips-dir", type=Path, default=Path("clips"))

    p_split = sub.add_parser("split", help="把朗读 ogg 切成编号 mp3")
    p_split.add_argument("--chunks-dir", type=Path, default=Path("chunks"))
    p_split.add_argument("--clips-dir", type=Path, default=Path("clips"))
    p_split.add_argument("--safety-ms", type=float, default=120,
                         help="切割安全余量毫秒（默认 120）")

    p_gensrt = sub.add_parser("gen-srt", help="按朗读节奏生成字幕 SRT")
    p_gensrt.add_argument("--chunks-dir", type=Path, default=Path("chunks"))
    p_gensrt.add_argument("--output", "-o", type=Path, default=Path("episode.srt"),
                          help="输出 SRT 路径（默认 episode.srt）")
    p_gensrt.add_argument("--max-chars", type=int, default=40,
                          help="每条字幕最大字符数（默认 40）")

    args = parser.parse_args()
    if args.cmd == "prep":
        cmd_prep(args)
    elif args.cmd == "harvest":
        cmd_harvest(args)
    elif args.cmd == "split":
        cmd_split(args)
    elif args.cmd == "gen-srt":
        cmd_gen_srt(args)


if __name__ == "__main__":
    main()
