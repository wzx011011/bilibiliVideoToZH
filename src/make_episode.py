"""单集豆包配音视频制作 —— 封装从字幕到成品 MP4 的完整流程。

流程（半自动）：
  1. prep   读 SRT → 分块（新提示词：断句+语气+语速）→ 生成 txt 待发送
  2. 用户   在豆包网页手动发送 txt（浏览器签名绕过风控）
  3. 自动   harvest(朗读+存文本) → gen-srt(字幕延后0.5秒) → 拼音频 → 出MP4(含水印)

用法：
  # 单集完整制作（交互式：列出回复让你选序号）
  python make_episode.py --episode 2

  # 仅 prep（生成分块 txt 供发送）
  python make_episode.py --episode 2 --step prep

  # 仅合成（已有 ogg/wav，跳到 harvest+出视频）
  python make_episode.py --episode 2 --step build

依赖：doubao_pipeline.py + make_cover_video.py + doubao_reader.py
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = Path(__file__).resolve().parent
PY = str(ROOT / "work" / ".venv-ocr" / "Scripts" / "python.exe")
FFMPEG = str(ROOT / "work" / "video-tools" / "ffmpeg.exe")

# 字幕源目录
SUBTITLE_BASE = ROOT / "subtitles"

# 字幕延后秒数（用户反馈：字幕快了 0.5 秒）
SUBTITLE_DELAY = 0.5
WATERMARK = "wzx"
CHUNK_SIZE = 120


def find_srt(episode: int) -> Path:
    """找到指定集的已复核中文字幕。"""
    srt = SUBTITLE_BASE / f"episode-{episode:02d}.zh-CN.srt"
    if srt.exists():
        return srt
    sys.exit(f"[✗] 找不到第{episode}集的中文字幕")


def run(cmd: list[str], **kw) -> str:
    """运行命令，返回 stdout。"""
    print(f"  $ {' '.join(str(c) for c in cmd[:4])}...", file=sys.stderr)
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


def harvest_auto(ep: int, chunks_dir: Path) -> None:
    """自动匹配豆包回复并朗读。

    匹配策略：找最近 30 分钟内、带大量标点的回复（新提示词会让豆包加标点），
    按时间正序对应各分块。这是第1、2集验证过的方式，比交互式选序号可靠。
    """
    import time as _time
    # 延迟导入 doubao_reader（它在 doubao-tts-tool 目录下）
    sys.path.insert(0, str(TOOL_DIR))
    import doubao_reader as dr
    sys.path.insert(0, str(TOOL_DIR))
    from doubao_pipeline import _fetch_all_recent_replies, _probe_duration
    import asyncio
    import subprocess

    manifest = json.loads((chunks_dir / "manifest.json").read_text(encoding="utf-8"))
    total_chunks = manifest["total_chunks"]

    # 拉取最近回复
    print("  拉取豆包回复...")
    replies = _fetch_all_recent_replies(conv_limit=40, per_conv=15)

    # 筛选：最近 30 分钟 + 带标点（新提示词产生大量标点）
    cutoff = _time.time() - 1800
    recent = [r for r in replies
              if r["create_time"] > cutoff
              and sum(1 for ch in r["tts_content"] if ch in "，。？！") > 50]
    recent.sort(key=lambda r: r["create_time"])

    if len(recent) < total_chunks:
        print(f"  [!] 只找到 {len(recent)} 条候选回复，需要 {total_chunks} 条")
        print(f"      确认已在豆包发送所有 {total_chunks} 个分块")
        if not recent:
            sys.exit("[✗] 没找到任何候选回复")

    # 取最近 total_chunks 条，按时间正序对应块01-NN
    matched = recent[-total_chunks:] if len(recent) >= total_chunks else recent
    print(f"  匹配到 {len(matched)} 条回复")

    FFMPEG = str(ROOT / "work" / "video-tools" / "ffmpeg.exe")
    harvested = []
    for i, c in enumerate(manifest["chunks"]):
        if i >= len(matched):
            break
        idx = c["chunk_index"]
        r = matched[i]
        print(f"  [块{idx:02d}] 朗读中... msg={r['message_id']}")

        ogg = chunks_dir / f"{idx:02d}.ogg"
        wav = chunks_dir / f"{idx:02d}.wav"
        # 跳过已完成的
        if wav.exists() and wav.stat().st_size > 0 and c.get("tts_content"):
            print(f"    跳过（已完成）")
            harvested.append(idx)
            continue

        n = asyncio.run(dr.read_reply(r, str(ogg)))
        if not n:
            print(f"    未收到音频，等 90 秒重试...")
            _time.sleep(90)
            n = asyncio.run(dr.read_reply(r, str(ogg)))
        if n:
            subprocess.run([FFMPEG, "-y", "-loglevel", "error",
                            "-i", str(ogg), str(wav)], check=True)
            dur = _probe_duration(wav)
            print(f"    ✓ {n // 1024}KB, {dur:.0f}s")
            c["tts_content"] = r["tts_content"]
            harvested.append(idx)
        else:
            print(f"    ✗ 朗读失败")
        _time.sleep(3)

    manifest["harvested_chunks"] = harvested
    (chunks_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  harvest 完成：{len(harvested)}/{total_chunks} 块")


def main() -> None:
    parser = argparse.ArgumentParser(description="单集豆包配音视频制作")
    parser.add_argument("--episode", type=int, required=True, help="集数（如 2）")
    parser.add_argument("--step", choices=["all", "prep", "build"],
                        default="all", help="执行阶段（默认 all）")
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="工作目录（默认 ep-XX/）")
    parser.add_argument("--subtitle-delay", type=float, default=SUBTITLE_DELAY)
    parser.add_argument("--watermark", default=WATERMARK)
    parser.add_argument("--title", default=None, help="封面标题（默认自动）")
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
    if args.step in ("all", "prep"):
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
        print(f"请手动操作：在豆包网页依次发送 {n_chunks} 个 txt 的内容")
        print(f"  文件位置: {chunks_dir}/01.txt ~ {n_chunks:02d}.txt")
        print("发完后运行（或告诉我 都发了）：")
        print(f'  python make_episode.py --episode {ep} --step build')
        print("=" * 50)
        if args.step == "prep":
            return

    # ---------- 步骤 2: harvest（自动匹配回复 + 朗读 + 保存文本）----------
    if args.step in ("all", "build"):
        print("[2/4] harvest: 自动匹配并朗读豆包回复")
        harvest_auto(ep, chunks_dir)
        # harvest 完成后检查是否已有 wav，跳过已完成的
        manifest_path = chunks_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not manifest.get("harvested_chunks"):
            sys.exit("[✗] harvest 未成功，检查豆包回复是否已发送")

    # ---------- 步骤 3: gen-srt + 字幕延后 + 拼音频 ----------
    print("[3/4] gen-srt + 拼音频")
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
    harvested = manifest.get("harvested_chunks", [])
    if not harvested:
        sys.exit("[✗] manifest 无已朗读块，检查 harvest 是否成功")
    # 先确保所有块都有 wav
    for idx in harvested:
        ogg = chunks_dir / f"{idx:02d}.ogg"
        wav = chunks_dir / f"{idx:02d}.wav"
        if not wav.exists() and ogg.exists():
            subprocess.run([FFMPEG, "-y", "-loglevel", "error",
                            "-i", str(ogg), str(wav)], check=True)
    # concat
    list_file = work_dir / "concat-list.txt"
    list_file.write_text(
        "\n".join(f"file '{(chunks_dir / f'{idx:02d}.wav').as_posix()}'"
                  for idx in harvested) + "\n",
        encoding="utf-8",
    )
    audio_mp3 = work_dir / f"episode-{ep:02d}-audio.mp3"
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-codec:a", "libmp3lame", "-b:a", "192k", str(audio_mp3),
    ], check=True)
    list_file.unlink(missing_ok=True)
    print(f"  音频拼接 → {audio_mp3.name} ({audio_mp3.stat().st_size // 1024 // 1024}MB)")

    # ---------- 步骤 4: 出 MP4 ----------
    print("[4/4] make_cover_video: 封面图 + 字幕 + 水印 → MP4")
    output_mp4 = ROOT / "videos" / f"episode-{ep:02d}.mp4"
    # 复用封面图
    cover = ROOT / "videos" / "cover.jpg"
    cmd = [
        PY, str(TOOL_DIR / "make_cover_video.py"),
        "--cover", str(cover),
        "--audio", str(audio_mp3),
        "--srt", str(final_srt),
        "--watermark", args.watermark,
        "--title", title,
        "-o", str(output_mp4),
    ]
    subprocess.run(cmd, check=True)

    # ---------- 步骤 5: 归档产物到 episodes/ ----------
    print("[归档] 保存音频+字幕+分块到 episodes/")
    ep_archive = ROOT / "episodes" / f"ep-{ep:02d}"
    ep_archive.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(audio_mp3, ep_archive / audio_mp3.name)
    shutil.copy2(final_srt, ep_archive / final_srt.name)
    shutil.copy2(raw_srt, ep_archive / raw_srt.name)
    shutil.copy2(chunks_dir / "manifest.json", ep_archive / "manifest.json")
    for txt in chunks_dir.glob("*.txt"):
        shutil.copy2(txt, ep_archive / txt.name)
    print(f"  归档 → {ep_archive}/")

    print(f"\n[✓✓] 第{ep:02d}集完成: {output_mp4}")


if __name__ == "__main__":
    main()
