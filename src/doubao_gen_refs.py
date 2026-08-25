# -*- coding: utf-8 -*-
"""为两个豆包音色合成克隆参考音频。

流程:发两条参考文本 → 拉最近回复 → 指定音色 WS 朗读抓取 ogg → 转 wav。
音色:主持人=渊博小叔,Hinton=深夜播客。
"""
import asyncio
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doubao_autosend import DoubaoAutoSender  # noqa: E402
import doubao_reader as dr  # noqa: E402
from doubao_reader import read_reply  # noqa: E402

HOST_TEXT = ("欢迎回到本期节目。今天这场对话，我等了整整一年。"
             "我们聊的不是新闻头条，而是每个人未来十年都会面对的问题。"
             "好了，不说废话，我们马上开始。")
HINTON_TEXT = ("我研究神经网络，已经快五十年了。很多人问我，机器真的会思考吗。"
               "我的答案是，它们理解世界的方式，和我们没有本质区别。"
               "这一点，让我既兴奋，又担忧。")

VOICES = {
    "host-yuanboxiaoshu": "zh_male_m219_conversation_wvae_bigtts",   # 渊博小叔
    "hinton-shenyeboker": "zh_male_shenyeboke_wvae_bigtts",          # 深夜播客
}


def send_and_wait(sender, text):
    """让豆包逐字复述文本(朗读的是 AI 回复,不是输入)。"""
    prompt = ("请一字不差地重复输出下面的文字，不要加任何前言、后语、引号或标点改动：\n" + text)
    try:
        sender.send_one(prompt)
    except RuntimeError as e:
        print(f"  (形态校验拒绝,忽略: {str(e)[:60]}...)")
    sender.page.wait_for_timeout(1500)


def main():
    out_dir = ROOT / "work/doubao-refs"
    out_dir.mkdir(exist_ok=True)

    sender = DoubaoAutoSender(headless=False)
    try:
        sender.open_chat()
        print("[1/4] 发送两条参考文本...")
        send_and_wait(sender, HOST_TEXT)
        time.sleep(2)
        send_and_wait(sender, HINTON_TEXT)
    finally:
        sender.close()

    print("[2/4] 拉取最近回复...")
    replies = dr.fetch_messages(limit=5, per_conv=10)
    by_prefix = {}
    for r in replies:
        content = re.sub(r"\s+", "", r.get("tts_content") or r.get("content") or "")
        for key, text in (("host", HOST_TEXT), ("hinton", HINTON_TEXT)):
            want = re.sub(r"\s+", "", text)[:20]
            if want in content:
                by_prefix.setdefault(key, r)
    assert "host" in by_prefix and "hinton" in by_prefix, \
        f"没匹配到两条回复: {list(by_prefix)}"

    print("[3/4] 指定音色朗读并抓取...")
    for key, meta in by_prefix.items():
        voice_key = "host-yuanboxiaoshu" if key == "host" else "hinton-shenyeboker"
        ogg = out_dir / f"{key}.ogg"
        n = asyncio.run(read_reply(meta, ogg, speaker=VOICES[voice_key]))
        print(f"  {key}: {n} bytes -> {ogg.name}")

    print("[4/4] 转 wav...")
    ffmpeg = str(ROOT / "work/video-tools/ffmpeg.exe")
    import subprocess
    for key in ("host", "hinton"):
        src, dst = out_dir / f"{key}.ogg", out_dir / f"{key}.wav"
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)], check=True)
        print(f"  {dst.name}")
    print("[✓] 完成 ->", out_dir)


if __name__ == "__main__":
    main()
