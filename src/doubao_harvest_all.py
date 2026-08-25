# -*- coding: utf-8 -*-
"""收割豆包全部音色到本地音色库(work/studio/voices/doubao-<名字>/)。

流程:发一条复述指令 → 拿到回复元数据 → 对 49 个音色逐个 WS 朗读抓取。
同一回复文本,每个音色各读一遍;每次间隔数秒降低风控风险;断点续跑。

运行:work/.venv-ocr/Scripts/python.exe src/doubao_harvest_all.py
"""
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doubao_autosend import DoubaoAutoSender  # noqa: E402
import doubao_reader as dr  # noqa: E402
from doubao_reader import read_reply  # noqa: E402

REF_TEXT = ("我研究神经网络，已经快五十年了。很多人问我，机器真的会思考吗。"
            "我的答案是，它们理解世界的方式，和我们没有本质区别。"
            "这一点，让我既兴奋，又担忧。")
ECHO_PROMPT = "请一字不差地重复输出下面的文字，不要加任何前言、后语、引号或标点改动：\n" + REF_TEXT
LIB = ROOT / "work/studio/voices"
FFMPEG = str(ROOT / "work/video-tools/ffmpeg.exe")
SLEEP_BETWEEN = 3.5


def sanitize(name: str, used: set) -> str:
    base = re.sub(r"[\\/:*?\"<>|\s（）()]+", "", name) or "voice"
    out = f"doubao-{base}"
    i = 2
    while out in used:
        out = f"doubao-{base}-{i}"
        i += 1
    used.add(out)
    return out


def main():
    # 计划来自库内目录的 meta(含修正过的 doubao_speaker_id);缺 ID 的从列表补
    voices = json.loads((ROOT / "src/doubao-voices.json").read_text(encoding="utf-8"))
    id2name = voices
    plan = []
    for d in sorted(LIB.glob("doubao-*")):
        meta_p = d / "meta.json"
        if not meta_p.exists():
            continue
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        sid = meta.get("doubao_speaker_id")
        cname = meta.get("doubao_name") or id2name.get(sid) or d.name[8:]
        if not sid or sid == cname:  # ID 缺失或仍是颠倒的中文名 -> 从列表反查
            sid = next((k for k, v in voices.items() if v == cname), None)
        if not sid:
            print(f"跳过(无 ID): {d.name}")
            continue
        plan.append((d.name, cname, sid))
    done = sum(1 for d, _, _ in plan if (LIB / d / "ref.wav").exists())
    print(f"共 {len(plan)} 个音色,已完成 {done},待抓取 {len(plan) - done}")

    sender = None
    reply = None
    if done < len(plan):
        sender = DoubaoAutoSender(headless=False)
        try:
            sender.open_chat()
            try:
                sender.send_one(ECHO_PROMPT)
            except RuntimeError as e:
                print(f"  (形态校验拒绝,忽略: {str(e)[:50]}...)")
            time.sleep(2)
            replies = dr.fetch_messages(limit=3, per_conv=10)
            want = re.sub(r"\s+", "", REF_TEXT)[:20]
            for r in replies:
                if want in re.sub(r"\s+", "", r.get("tts_content") or ""):
                    reply = r
                    break
            assert reply, "没找到复述回复"
            print("复述回复就绪:", (reply.get("tts_content") or "")[:30], "...")
        finally:
            # 同步 Playwright 与 asyncio.run 事件循环冲突:
            # 浏览器阶段(发消息拿元数据)完成后必须先关闭,收割才能跑 asyncio
            sender.close()

    ok = fail = skip = 0
    for i, (dir_name, name, sid) in enumerate(plan, 1):
            vdir = LIB / dir_name
            if (vdir / "ref.wav").exists() and (vdir / "ref.wav").stat().st_size > 50000:
                skip += 1
                continue
            print(f"[{i}/{len(plan)}] {name} ({sid})", flush=True)
            try:
                ogg = vdir / "ref.ogg"
                ogg.parent.mkdir(parents=True, exist_ok=True)
                asyncio.run(read_reply(reply, ogg, speaker=sid))
                wav = vdir / "ref.wav"
                subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                                "-i", str(ogg), "-ar", "16000", "-ac", "1", str(wav)], check=True)
                ogg.unlink()
                dur = 0.0
                try:
                    out = subprocess.run(
                        [str(ROOT / "work/video-tools/ffprobe.exe"), "-v", "error",
                         "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)],
                        capture_output=True, text=True, check=True).stdout.strip()
                    dur = float(out)
                except Exception:
                    pass
                if dur < 5:
                    raise RuntimeError(f"时长过短 {dur:.1f}s")
                (vdir / "ref.txt").write_text(REF_TEXT, encoding="utf-8")
                (vdir / "meta.json").write_text(json.dumps(
                    {"name": dir_name, "doubao_name": name, "doubao_speaker_id": sid,
                     "note": f"豆包音色[{name}]克隆参考", "ref_duration": round(dur, 1),
                     "created_at": time.strftime("%Y-%m-%d %H:%M")},
                    ensure_ascii=False, indent=1), encoding="utf-8")
                ok += 1
                print(f"    ✓ {dur:.1f}s", flush=True)
            except Exception as e:
                fail += 1
                print(f"    ✗ {str(e)[:80]}", flush=True)
            time.sleep(SLEEP_BETWEEN)
    print(f"\n[✓] 成功 {ok} / 失败 {fail} / 跳过(已存在) {skip}")


if __name__ == "__main__":
    main()
