"""豆包页面朗读抓取器 —— 通过真实页面点"朗读"获取豆包语音。

背景:直连 voicegenie WS 的脚本调用被风控(3003),但真实页面点朗读
正常(页面自己的 WS 环境)。本模块:
  1. Playwright 打开会话页,逐条 hover AI 回复 → 点"朗读"按钮;
  2. CDP Network.webSocketFrameReceived 监听页面 voicegenie WS;
     帧是 base64 包裹的 protobuf(与 doubao_reader 同协议,fn=8 为音频),
     在此解码、拼接成 ogg;
  3. 完成判定:音频字节静默 15s(实测整段音频点击后 ~30s 内推完)。

注意:
  - Playwright sync API 下必须用 page.wait_for_timeout 驱动事件,
    time.sleep 会饿死 CDP 回调(实测踩坑)。
  - 朗读按钮只在 hover 的消息块上渲染;逐块遍历识别 AI 消息。
  - 点朗读后按钮先变"正在生成语音朗读";完成后恢复"朗读",
    必须等恢复再点下一条(否则点到的是停止)。
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

from doubao_autosend import DoubaoAutoSender, load_env

SILENCE_S = 15        # 音频静默判定
POLL_MS = 1500        # 轮询间隔(驱动事件)
MIN_AUDIO_BYTES = 50_000  # 低于此视为异常(正常一条 ≥1MB)


class _FrameAudioTap:
    """CDP 帧监听:base64 protobuf → fn=8 音频块累积。"""

    def __init__(self, page):
        import doubao_reader as dr
        self._dr = dr
        self.parts: list[bytes] = []
        self.total = 0
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Network.webSocketFrameReceived", self._on_frame)
        self.cdp.send("Network.enable")

    def _on_frame(self, params):
        pd = params.get("response", {}).get("payloadData", "")
        if not pd:
            return
        try:
            raw = base64.b64decode(pd)
        except Exception:
            return
        try:
            for fn, val in self._dr.parse_fields(raw):
                if fn == 8 and val:
                    self.parts.append(val)
                    self.total += len(val)
        except Exception:
            pass

    def reset(self):
        self.parts, self.total = [], 0

    def save(self, path: Path) -> int:
        if self.total < MIN_AUDIO_BYTES:
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(self.parts))
        return self.total


def read_conversation(conv_url: str, out_dir: Path,
                      expect_replies: int | None = None,
                      skip_first: int = 0) -> list[Path]:
    """抓取整个会话的 AI 回复朗读音频,按消息顺序存 clips/NN.ogg。

    skip_first: 跳过前 N 条 AI 回复(断点续抓)。
    关键实现(实测踩坑):
    - locator.hover 会卡在 React 重渲染元素的可见性检查上,改用
      bounding_box + mouse.move 坐标 hover;
    - 不等页面播放完(音频点击后 ~30s 推完即可抓,播放要实时时长)——
      抓完直接处理下一条,若上一条还在播,先点它的停止按钮。
    """
    out_files: list[Path] = []
    with DoubaoAutoSender(headless=False) as s:
        tap = _FrameAudioTap(s.page)
        s.page.goto(conv_url, wait_until="domcontentloaded")
        for _ in range(4):
            s.page.wait_for_timeout(1500)

        # 触发懒加载:底→顶→底滚动两轮,让全部消息渲染(否则长会话
        # 底部消息不加载,实测漏掉 06/07)
        for _ in range(2):
            s.page.keyboard.press("End")
            for _ in range(4):
                s.page.wait_for_timeout(800)
            s.page.keyboard.press("Home")
            for _ in range(4):
                s.page.wait_for_timeout(800)
        s.page.keyboard.press("End")
        for _ in range(3):
            s.page.wait_for_timeout(800)

        msgs = s.page.locator("[class*=message]")
        count = msgs.count()
        print(f"消息块总数: {count}")
        ai_seq = 0
        for i in range(count):
            blk = msgs.nth(i)
            try:
                blk.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                continue
            s.page.wait_for_timeout(500)
            try:
                box = blk.bounding_box(timeout=2000)
            except Exception:
                continue
            if not box:
                continue
            # 坐标 hover:块顶部 1/4 处(动作栏位置),绕开 locator 稳定性检查
            s.page.mouse.move(box["x"] + box["width"] / 2,
                              box["y"] + min(box["height"] / 4, 300))
            s.page.wait_for_timeout(1200)
            btn = s.page.locator('button[aria-label="朗读"]')
            if btn.count() == 0:
                continue  # 用户提问等无朗读按钮的块
            ai_seq += 1
            if ai_seq <= skip_first:
                continue  # 已抓过
            tap.reset()
            # JS 原子点击:按钮被 action-bar 层"遮挡",Playwright 常规点击会
            # 因 actionability 检查卡死(实测 retry 57 次超时)
            s.page.evaluate(
                '() => { const b = document.querySelector("button[aria-label=\'朗读\']");'
                ' if (b) b.click(); }')
            print(f"  [AI {ai_seq}] 已点朗读,收流...")
            last, quiet = 0, 0
            for _ in range(240):  # 最长 6 分钟
                s.page.wait_for_timeout(POLL_MS)
                if tap.total == last:
                    quiet += POLL_MS
                    if quiet >= SILENCE_S * 1000 and tap.total >= MIN_AUDIO_BYTES:
                        break
                else:
                    quiet, last = 0, tap.total
            path = out_dir / "clips" / f"{ai_seq:02d}.ogg"
            n = tap.save(path)
            if n > 0:
                out_files.append(path)
                print(f"    ✓ {n//1024}KB → {path.name}")
            else:
                print("    ✗ 音频不足,跳过")
            # 上条可能还在播:点"停止/正在生成"按钮终止播放(不影响已抓音频)
            try:
                s.page.evaluate(
                    "() => { const b = [...document.querySelectorAll('button')]"
                    ".find(x => /停止|正在生成/.test(x.getAttribute('aria-label') || ''));"
                    " if (b) b.click(); }")
                s.page.wait_for_timeout(800)
            except Exception:
                pass
            if expect_replies and ai_seq >= expect_replies:
                break
    return out_files


def concat_to_mp3(oggs: list[Path], out_mp3: Path, gap_ms: int = 250) -> None:
    from pydub import AudioSegment
    # pydub 需要显式指向项目自带 ffmpeg/ffprobe(不在 PATH)
    tools = Path(__file__).resolve().parents[1] / "work" / "video-tools"
    AudioSegment.converter = str(tools / "ffmpeg.exe")
    AudioSegment.ffmpeg = str(tools / "ffmpeg.exe")
    AudioSegment.ffprobe = str(tools / "ffprobe.exe")
    silence = AudioSegment.silent(duration=gap_ms)
    combined = AudioSegment.empty()
    for i, p in enumerate(oggs):
        seg = AudioSegment.from_file(p)  # opus/ogg
        combined += seg if i == 0 else silence + seg
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(out_mp3), format="mp3", bitrate="128k")


if __name__ == "__main__":
    import sys
    # 用法: python doubao_page_tts.py <会话URL> <输出目录> [期望条数] [跳过前N条]
    conv, outdir = sys.argv[1], Path(sys.argv[2])
    expect = int(sys.argv[3]) if len(sys.argv) > 3 else None
    skip = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    import os
    for k in ("all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)
    for k, v in load_env().items():
        os.environ.setdefault(k, v)
    files = read_conversation(conv, outdir, expect, skip)
    print(f"完成 {len(files)} 条")
    # 拼接全部已有 clips(含本次与续抓的)
    all_clips = sorted((outdir / "clips").glob("*.ogg"))
    if all_clips:
        concat_to_mp3(all_clips, outdir / "audio.mp3")
        print(f"拼接 {len(all_clips)} 条 →", outdir / "audio.mp3")
