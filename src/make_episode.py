"""单集豆包配音视频制作 —— 封装从字幕到成品 MP4 的完整流程。

流程：
  1. prep   读 SRT → 分块（断句+语气+语速）→ 生成 txt 待扩展发送
  2. 扩展   使用豆包网页原生输入框逐块发送并等待回复
  3. bridge 扩展完成后触发 build
  4. build  精确匹配回复 → 朗读 → 字幕 → 拼音频 → 出 MP4

用法：
  # 默认生成分块
  python make_episode.py --episode 2

  # 仅 prep（生成分块 txt 供发送）
  python make_episode.py --episode 2 --step prep

  # 手动恢复自动构建
  python make_episode.py --episode 2 --step build

依赖：doubao_pipeline.py + make_cover_video.py + doubao_reader.py
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = Path(__file__).resolve().parent
FFMPEG = str(ROOT / "work" / "video-tools" / "ffmpeg.exe")
FFPROBE = str(ROOT / "work" / "video-tools" / "ffprobe.exe")

# venv launcher (.venv-ocr/Scripts/python.exe) 会 spawn base python 子进程，
# 两个进程跑同一脚本写同一文件会互相覆盖。直接用 base python + PYTHONPATH 绕过。
VENV_PY = str(ROOT / "work" / ".venv-ocr" / "Scripts" / "python.exe")
BASE_PY = r"C:\Python311\python.exe"
PY = BASE_PY if Path(BASE_PY).exists() else VENV_PY
_VENV_SITE = str(ROOT / "work" / ".venv-ocr" / "Lib" / "site-packages")

# 字幕源目录
SUBTITLE_BASE = ROOT / "subtitles"

# 字幕延后秒数（用户反馈：字幕快了 0.5 秒）
SUBTITLE_DELAY = 0.5
WATERMARK = "wzx"
CHUNK_SIZE = 120


def _configure_stdio() -> None:
    """让 Windows 控制台也能稳定输出中文和 Unicode 状态符号。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def find_srt(episode: int) -> Path:
    """找到指定集的已复核中文字幕。"""
    srt = SUBTITLE_BASE / f"episode-{episode:02d}.zh-CN.srt"
    if srt.exists():
        return srt
    sys.exit(f"[✗] 找不到第{episode}集的中文字幕")


def _subprocess_env(cmd: list[str]) -> dict | None:
    """为 base Python 子进程注入依赖路径和 UTF-8 标准输出。"""
    if cmd and str(cmd[0]) == BASE_PY:
        env = os.environ.copy()
        env["PYTHONPATH"] = _VENV_SITE + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env
    return None


def run(cmd: list[str], **kw) -> str:
    """运行命令，返回 stdout。"""
    print(f"  $ {' '.join(str(c) for c in cmd[:4])}...", file=sys.stderr)
    env = _subprocess_env(cmd)
    if env:
        kw.setdefault("env", env)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"[✗] 命令失败: {' '.join(cmd)}\n{r.stderr[-500:]}")
    return r.stdout


def shift_srt(srt_path: Path, delay: float, output: Path) -> None:
    """字幕整体延后 delay 秒。"""
    def to_sec(ts):
        h, m, r = ts.split(":")
        s, ms = r.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    def to_ts(sec):
        sec = max(0, sec)
        ms = round(sec * 1000)
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1_000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = srt_path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        m = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})", line
        )
        if m:
            start = to_sec(m.group(1)) + delay
            end = to_sec(m.group(2)) + delay
            out.append(f"{to_ts(start)} --> {to_ts(end)}")
        else:
            out.append(line)
    output.write_text("\n".join(out) + "\n", encoding="utf-8")


def _atomic_write_json(path: Path, value: dict) -> None:
    """写 JSON 检查点，避免进程中断留下半个 manifest。"""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _probe_media_duration(path: Path) -> float:
    result = subprocess.run(
        [
            FFPROBE, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise RuntimeError(f"媒体时长无效: {path.name}")
    return duration


def _js_fingerprint(text: str) -> str:
    """与扩展 sender-core.js 相同的 UTF-16 FNV-1a 指纹。"""
    value = str(text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    units = value.encode("utf-16-le", errors="surrogatepass")
    result = 2166136261
    for offset in range(0, len(units), 2):
        code_unit = units[offset] | (units[offset + 1] << 8)
        result ^= code_unit
        result = (result * 16777619) & 0xFFFFFFFF
    return f"{result:08x}:{len(units) // 2}"


def _epoch(value: object) -> float:
    """解析浏览器 ISO 时间；也兼容秒/毫秒/微秒数字。"""
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("空时间")
        result = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    while result > 100_000_000_000:
        result /= 1000
    return result


def _conversation_id(record: dict) -> str:
    value = str(record.get("conversation_id") or "")
    if value:
        return value
    parsed = urlparse(str(record.get("conversation_url") or ""))
    parts = [part for part in parsed.path.split("/") if part]
    return parts[1] if len(parts) == 2 and parts[0] == "chat" else ""


def _select_replies(
    replies: list[dict],
    manifest: dict,
    chunks_dir: Path,
    record: dict | None = None,
) -> list[dict]:
    """返回按 chunk 顺序排列的唯一回复，拒绝缺失、重复和跨会话错配。"""
    chunks = manifest["chunks"]
    total = len(chunks)
    if record:
        expected_conversation = _conversation_id(record)
        if not expected_conversation:
            raise RuntimeError("发送记录没有有效 conversation_id")
        scoped = [
            reply for reply in replies
            if str(reply.get("conversation_id", "")) == expected_conversation
        ]
        record_items = {
            int(item["chunk_index"]): item
            for item in record.get("items", [])
            if isinstance(item, dict) and str(item.get("chunk_index", "")).isdigit()
        }
        if len(record_items) != total:
            raise RuntimeError("发送记录没有覆盖全部分块")

        selected = []
        used: set[str] = set()
        ordered = sorted(chunks, key=lambda chunk: int(chunk["chunk_index"]))
        for position, chunk in enumerate(ordered):
            index = int(chunk["chunk_index"])
            item = record_items.get(index)
            if not item or item.get("status") != "done":
                raise RuntimeError(f"分块 {index} 没有成功发送记录")
            txt_path = chunks_dir / str(chunk.get("txt_file") or "")
            if not txt_path.is_file():
                raise RuntimeError(f"分块文件不存在: {txt_path.name}")
            expected_fp = str(item.get("fingerprint") or "")
            if _js_fingerprint(txt_path.read_text(encoding="utf-8")) != expected_fp:
                raise RuntimeError(f"分块 {index} 本地文本已变化，拒绝继续")
            sent_at = _epoch(item.get("sent_at"))
            reply_at = _epoch(item.get("reply_at"))
            next_item = record_items.get(int(ordered[position + 1]["chunk_index"])) \
                if position + 1 < len(ordered) else None
            upper_base = _epoch(next_item.get("sent_at")) if next_item else _epoch(record.get("completed_at"))
            lower = sent_at - 45
            upper = min(upper_base + 30, reply_at + 30)

            candidates = []
            for reply in scoped:
                message_id = str(reply.get("message_id", ""))
                if not message_id or message_id in used:
                    continue
                question_text = str(reply.get("question_text") or "").strip()
                if not question_text or _js_fingerprint(question_text) != expected_fp:
                    continue
                question_time = reply.get("question_create_time") or reply.get("create_time")
                reply_time = reply.get("create_time")
                try:
                    question_epoch = _epoch(question_time)
                    reply_epoch = _epoch(reply_time)
                except (TypeError, ValueError, OverflowError):
                    continue
                if (lower <= question_epoch <= upper
                        and question_epoch <= reply_epoch
                        and reply_at - 120 <= reply_epoch <= reply_at + 120):
                    candidates.append(reply)
            if len(candidates) != 1:
                raise RuntimeError(
                    f"分块 {index} 的回复匹配{'缺失' if not candidates else '不唯一'} "
                    f"（候选 {len(candidates)} 条）"
                )
            selected.append(candidates[0])
            used.add(str(candidates[0]["message_id"]))
        return selected

    # 没有 sidecar 时保留手动 build 的兼容路径，但仍然要求完整数量。
    cutoff = time.time() - 1800
    recent = [
        reply for reply in replies
        if _epoch(reply.get("create_time")) > cutoff
        and sum(1 for char in reply.get("tts_content", "") if char in "，。？！") > 50
    ]
    recent.sort(key=lambda reply: _epoch(reply.get("create_time")))
    if len(recent) < total:
        raise RuntimeError(f"只找到 {len(recent)} 条候选回复，需要 {total} 条")
    return recent[-total:]


def _select_replies_auto(replies: list[dict], total: int) -> list[dict]:
    """自动匹配：最近 30 分钟内、标点 > 50 的回复，按时间排序取最后 N 条。"""
    cutoff = time.time() - 1800
    recent = [
        reply for reply in replies
        if _epoch(reply.get("create_time")) > cutoff
        and sum(1 for char in reply.get("tts_content", "") if char in "，。？！") > 50
    ]
    recent.sort(key=lambda reply: _epoch(reply.get("create_time")))
    if len(recent) < total:
        raise RuntimeError(f"自动匹配只找到 {len(recent)} 条候选回复，需要 {total} 条")
    return recent[-total:]


def harvest_auto(ep: int, chunks_dir: Path, send_record: Path | None = None) -> None:
    """按发送 sidecar 精确匹配回复并逐块保存朗读音频。"""
    import asyncio

    # 延迟导入 doubao_reader，便于 prep 和纯函数测试不要求凭据。
    sys.path.insert(0, str(TOOL_DIR))
    import doubao_reader as dr
    from doubao_pipeline import _fetch_all_recent_replies, _probe_duration, strip_boilerplate

    manifest_path = chunks_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = sorted(manifest["chunks"], key=lambda chunk: int(chunk["chunk_index"]))
    total_chunks = len(chunks)
    expected_indices = [int(chunk["chunk_index"]) for chunk in chunks]

    record_path = send_record or (chunks_dir.parent / "doubao-send.json")
    record = None
    if record_path.is_file():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        print(f"  使用发送记录：{record_path}")

    def complete_indices() -> set[int]:
        complete = set()
        for chunk in chunks:
            index = int(chunk["chunk_index"])
            wav = chunks_dir / f"{index:02d}.wav"
            if not chunk.get("tts_content") or not wav.is_file() or wav.stat().st_size <= 0:
                continue
            try:
                if _probe_media_duration(wav) > 0:
                    complete.add(index)
            except (ValueError, subprocess.SubprocessError):
                continue
        return complete

    def metadata_is_current(chunk: dict) -> bool:
        if not record:
            return True
        try:
            audio_duration = float(chunk.get("audio_duration") or 0)
        except (TypeError, ValueError):
            return False
        return (
            chunk.get("send_run_id") == record.get("run_id")
            and bool(chunk.get("reply_message_id"))
            and bool(chunk.get("conversation_id"))
            and bool(chunk.get("reply_unique_key"))
            and audio_duration > 0
        )

    complete = complete_indices()
    if complete == set(expected_indices) and (
        record is None or (
            manifest.get("send_run_id") == record.get("run_id")
            and all(metadata_is_current(chunk) for chunk in chunks)
        )
    ):
        manifest["harvested_chunks"] = expected_indices
        _atomic_write_json(manifest_path, manifest)
        print(f"  harvest 已完成：{total_chunks}/{total_chunks} 块（跳过联网匹配）")
        return

    print("  拉取豆包回复...")
    per_conv = min(100, max(20, total_chunks * 2 + 4))
    replies = _fetch_all_recent_replies(conv_limit=40, per_conv=per_conv)
    try:
        matched = _select_replies(replies, manifest, chunks_dir, record)
        print(f"  精确匹配到 {len(matched)} 条回复")
    except RuntimeError as error:
        print(f"  ⚠ 精确匹配失败（{error}），回退到自动匹配...")
        matched = _select_replies_auto(replies, total_chunks)
        print(f"  自动匹配到 {len(matched)} 条回复")

    ffmpeg = str(ROOT / "work" / "video-tools" / "ffmpeg.exe")
    failures = []
    harvested = set(complete)
    for chunk, reply in zip(chunks, matched):
        index = int(chunk["chunk_index"])
        message_id = str(reply["message_id"])
        ogg = chunks_dir / f"{index:02d}.ogg"
        wav = chunks_dir / f"{index:02d}.wav"
        if index in complete:
            if record and not metadata_is_current(chunk):
                # An old WAV without a binding is not trusted for a new run.
                ogg.unlink(missing_ok=True)
                wav.unlink(missing_ok=True)
                complete.discard(index)
                harvested.discard(index)
            elif chunk.get("reply_message_id") not in (None, "", message_id):
                failures.append(f"块{index:02d}: 已有音频绑定到另一条回复")
                continue
            else:
                chunk.update({
                    "reply_message_id": message_id,
                    "conversation_id": reply.get("conversation_id", ""),
                    "reply_unique_key": reply.get("reply_unique_key", ""),
                    "reply_create_time": reply.get("create_time", 0),
                })
                continue

        print(f"  [块{index:02d}] 朗读中... msg={message_id}")
        temporary_ogg = ogg.with_suffix(".ogg.part")
        temporary_wav = wav.with_name(f"{wav.stem}.part{wav.suffix}")
        temporary_ogg.unlink(missing_ok=True)
        temporary_wav.unlink(missing_ok=True)
        try:
            n = asyncio.run(dr.read_reply(reply, str(temporary_ogg)))
            if not n:
                print("    未收到音频，90 秒后重试...")
                time.sleep(90)
                n = asyncio.run(dr.read_reply(reply, str(temporary_ogg)))
            if not n:
                raise RuntimeError("朗读接口没有返回音频")
            subprocess.run([
                ffmpeg, "-y", "-loglevel", "error", "-i", str(temporary_ogg), str(temporary_wav)
            ], check=True)
            if not temporary_wav.is_file() or temporary_wav.stat().st_size <= 0:
                raise RuntimeError("ffmpeg 没有生成有效 WAV")
            duration = _probe_duration(temporary_wav)
            if duration <= 0:
                raise RuntimeError("WAV 时长无效")
            if not str(reply.get("tts_content") or "").strip():
                raise RuntimeError("回复没有可朗读文本")
            os.replace(temporary_ogg, ogg)
            os.replace(temporary_wav, wav)
            print(f"    ✓ {n // 1024}KB, {duration:.0f}s")
            harvested.add(index)
            chunk.update({
                "tts_content": strip_boilerplate(reply.get("tts_content", "")),
                "reply_message_id": message_id,
                "conversation_id": reply.get("conversation_id", ""),
                "reply_unique_key": reply.get("reply_unique_key", ""),
                "reply_create_time": reply.get("create_time", 0),
                "audio_bytes": n,
                "audio_duration": duration,
                "send_run_id": record.get("run_id") if record else None,
            })
            if record:
                manifest["send_run_id"] = record.get("run_id")
            manifest["harvested_chunks"] = sorted(harvested)
            _atomic_write_json(manifest_path, manifest)
        except Exception as error:
            temporary_ogg.unlink(missing_ok=True)
            temporary_wav.unlink(missing_ok=True)
            failures.append(f"块{index:02d}: {error}")
        if index != chunks[-1]["chunk_index"]:
            time.sleep(3)

    if record:
        manifest["send_run_id"] = record.get("run_id")
    manifest["harvested_chunks"] = sorted(harvested)
    _atomic_write_json(manifest_path, manifest)
    if failures:
        sys.exit("[✗] harvest 有失败块：" + "; ".join(failures))
    if harvested != set(expected_indices):
        missing = sorted(set(expected_indices) - harvested)
        sys.exit(f"[✗] harvest 不完整，缺少块：{missing}")
    print(f"  harvest 完成：{total_chunks}/{total_chunks} 块")


def main() -> None:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="单集豆包配音视频制作")
    parser.add_argument("--episode", type=int, required=True, help="集数（如 2）")
    parser.add_argument("--step", choices=["prep", "build", "audio", "video"],
                        default="prep", help="执行阶段：prep=分块, audio=配音+字幕, video=渲染, build=audio+video")
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="工作目录（默认 ep-XX/）")
    parser.add_argument("--subtitle-delay", type=float, default=SUBTITLE_DELAY)
    parser.add_argument("--watermark", default=WATERMARK)
    parser.add_argument("--no-asr-align", action="store_true",
                        help="跳过 ASR 字幕对齐（默认启用，用配音音频真实节奏）")
    parser.add_argument("--title", default=None, help="封面标题（默认自动）")
    parser.add_argument("--send-record", type=Path, default=None,
                        help="扩展导出的发送记录（用于精确匹配回复）")
    args = parser.parse_args()

    ep = args.episode
    srt_src = find_srt(ep)
    work_dir = args.work_dir or (ROOT / "work" / f"ep-{ep:02d}")
    work_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir = work_dir / "chunks"
    clips_dir = work_dir / "clips"

    title = args.title or f"哈佛积极心理学 · 第{ep}讲"

    print(f"=== 第{ep:02d}集制作 ===")
    print(f"字幕源: {srt_src}")
    print(f"工作目录: {work_dir}")
    print()

    # ---------- 步骤 1: prep ----------
    if args.step == "prep":
        print("[1/4] prep: 分块生成待发送文本")
        run([
            PY, str(TOOL_DIR / "doubao_pipeline.py"), "prep",
            str(srt_src),
            "--chunks-dir", str(chunks_dir),
            "--chunk-size", str(CHUNK_SIZE),
        ])
        n_chunks = len(list(chunks_dir.glob("*.txt")))
        print(f"\n✓ prep 完成：{n_chunks} 个分块 → {chunks_dir}/")
        print()
        print("=" * 50)
        print(f"请在扩展中选择 manifest.json 和全部 {n_chunks} 个 TXT")
        print(f"  文件位置: {chunks_dir}/01.txt ~ {n_chunks:02d}.txt")
        print("发送完成后，扩展会通过本地桥接自动执行 build")
        print(f"  桥接启动: python {TOOL_DIR / 'doubao_bridge.py'} start")
        print("=" * 50)
        return

    # ---------- 步骤 2: harvest（自动匹配回复 + 朗读 + 保存文本）----------
    if args.step in ("build", "audio"):
        print("[audio] harvest: 自动匹配并朗读豆包回复")
        harvest_auto(ep, chunks_dir, args.send_record)
        manifest_path = chunks_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = sorted(int(chunk["chunk_index"]) for chunk in manifest["chunks"])
        harvested = sorted(int(index) for index in manifest.get("harvested_chunks", []))
        if harvested != expected:
            sys.exit(f"[✗] harvest 不完整：{harvested} / {expected}")

    # ---------- 步骤 3: gen-srt + 字幕延后 + 拼音频 ----------
    if args.step in ("build", "audio"):
        print("[audio] gen-srt + 拼音频")
    raw_srt = work_dir / f"episode-{ep:02d}-raw.srt"
    run([
        PY, str(TOOL_DIR / "doubao_pipeline.py"), "gen-srt",
        "--chunks-dir", str(chunks_dir),
        "-o", str(raw_srt),
        "--max-chars", "35",
    ])

    # 字幕延后
    final_srt = work_dir / f"episode-{ep:02d}.srt"
    shift_srt(raw_srt, args.subtitle_delay, final_srt)
    print(f"  字幕延后 {args.subtitle_delay}s → {final_srt.name}")

    # 拼接音频（所有 wav → mp3）
    manifest = json.loads((chunks_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = sorted(int(chunk["chunk_index"]) for chunk in manifest["chunks"])
    harvested = sorted(int(index) for index in manifest.get("harvested_chunks", []))
    if harvested != expected:
        sys.exit(f"[✗] manifest 音频不完整：{harvested} / {expected}")
    # 先确保所有块都有 wav
    for idx in harvested:
        ogg = chunks_dir / f"{idx:02d}.ogg"
        wav = chunks_dir / f"{idx:02d}.wav"
    manifest = json.loads((chunks_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = sorted(int(chunk["chunk_index"]) for chunk in manifest["chunks"])
    harvested = sorted(int(index) for index in manifest.get("harvested_chunks", []))
    if harvested != expected:
        sys.exit(f"[✗] manifest 音频不完整：{harvested} / {expected}")
    # 先确保所有块都有 wav
    for idx in harvested:
        ogg = chunks_dir / f"{idx:02d}.ogg"
        wav = chunks_dir / f"{idx:02d}.wav"
        if not wav.exists() and ogg.exists():
            wav_tmp = wav.with_name(f"{wav.stem}.part{wav.suffix}")
            wav_tmp.unlink(missing_ok=True)
            subprocess.run([FFMPEG, "-y", "-loglevel", "error",
                            "-i", str(ogg), str(wav_tmp)], check=True)
            if wav_tmp.is_file() and wav_tmp.stat().st_size > 0:
                _probe_media_duration(wav_tmp)
                os.replace(wav_tmp, wav)
            else:
                wav_tmp.unlink(missing_ok=True)
        if not wav.exists() or wav.stat().st_size <= 0:
            sys.exit(f"[✗] 缺少有效音频块：{idx:02d}")
    # concat
    list_file = work_dir / "concat-list.txt"
    list_file.write_text(
        "\n".join(f"file '{(chunks_dir / f'{idx:02d}.wav').as_posix()}'"
                  for idx in harvested) + "\n",
        encoding="utf-8",
    )
    audio_mp3 = work_dir / f"episode-{ep:02d}-audio.mp3"
    audio_tmp = audio_mp3.with_name(f"{audio_mp3.stem}.part{audio_mp3.suffix}")
    audio_tmp.unlink(missing_ok=True)
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-codec:a", "libmp3lame", "-b:a", "192k", str(audio_tmp),
    ], check=True)
    if not audio_tmp.is_file() or audio_tmp.stat().st_size <= 0:
        sys.exit("[✗] ffmpeg 未生成有效 MP3")
    _probe_media_duration(audio_tmp)
    os.replace(audio_tmp, audio_mp3)
    list_file.unlink(missing_ok=True)
    print(f"  音频拼接 → {audio_mp3.name} ({audio_mp3.stat().st_size // 1024 // 1024}MB)")

    # ---------- 步骤 3.5: ASR 字幕（直接用配音音频的语音识别做字幕，时间戳最准）----------
    if args.step in ("build", "audio") and not args.no_asr_align:
        print("[audio] ASR 字幕生成（配音音频→语音识别→字幕）")
        asr_srt = work_dir / f"episode-{ep:02d}-asr.srt"
        run([
            PY, str(TOOL_DIR / "align_srt_asr.py"),
            str(audio_mp3), "-o", str(asr_srt), "--asr-only",
        ])
        final_srt = asr_srt  # 后续用 ASR 字幕出视频
        print(f"  ASR 字幕 → {final_srt.name}")

    # ---------- 步骤 4: 出 MP4 ----------
    if args.step in ("build", "video"):
        # video 步骤单独跑时，定位已有的音频和字幕
        if args.step == "video":
            audio_mp3 = work_dir / f"episode-{ep:02d}-audio.mp3"
            asr_srt = work_dir / f"episode-{ep:02d}-asr.srt"
            final_srt = asr_srt if asr_srt.exists() else work_dir / f"episode-{ep:02d}.srt"
            if not audio_mp3.exists():
                sys.exit(f"[✗] 音频不存在: {audio_mp3}，请先运行 --step audio")
            if not final_srt.exists():
                sys.exit(f"[✗] 字幕不存在: {final_srt}，请先运行 --step audio")

        print("[video] make_cover_video: 封面图 + 字幕 + 水印 → MP4")
        output_mp4 = ROOT / "videos" / f"episode-{ep:02d}.mp4"
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        output_tmp = output_mp4.with_name(f"{output_mp4.stem}.part{output_mp4.suffix}")
        output_tmp.unlink(missing_ok=True)
        # 每集独立封面（带集数标题）
        cover = ROOT / "videos" / f"cover-ep{ep:02d}.jpg"
        cmd = [
            PY, str(TOOL_DIR / "make_cover_video.py"),
            "--cover", str(cover),
            "--gen-cover",  # 封面不存在时自动生成
            "--audio", str(audio_mp3),
            "--srt", str(final_srt),
            "--watermark", args.watermark,
            "--title", title,
            "-o", str(output_tmp),
        ]
        subprocess.run(cmd, check=True, env=_subprocess_env(cmd) or None)
        if not output_tmp.is_file() or output_tmp.stat().st_size <= 0:
            sys.exit("[✗] 未生成有效 MP4")
        _probe_media_duration(output_tmp)
        os.replace(output_tmp, output_mp4)

        # ---------- 步骤 5: 归档产物到 episodes/ ----------
        print("[归档] 保存音频+字幕+分块到 episodes/")
        ep_archive = ROOT / "episodes" / f"ep-{ep:02d}"
        ep_archive.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(audio_mp3, ep_archive / audio_mp3.name)
        shutil.copy2(final_srt, ep_archive / final_srt.name)
        if raw_srt.exists():
            shutil.copy2(raw_srt, ep_archive / raw_srt.name)
        shutil.copy2(chunks_dir / "manifest.json", ep_archive / "manifest.json")
        for txt in chunks_dir.glob("*.txt"):
            shutil.copy2(txt, ep_archive / txt.name)
        print(f"  归档 → {ep_archive}/")

        print(f"\n[✓✓] 第{ep:02d}集完成: {output_mp4}")
    elif args.step == "audio":
        print(f"\n[✓] 第{ep:02d}集音频完成: {audio_mp3}")
        print(f"    下一步: --episode {ep} --step video")


if __name__ == "__main__":
    main()
