# -*- coding: utf-8 -*-
"""成片逐章尾句转写核对(发布前必做,配合 av_qc)。

av_qc 的逐章转写用的是未混音的 parts,发现不了 assemble/polish 环节的损伤
(ep08 "教导"被 polish 砍尾即漏网)。本脚本直接从成片 audio.wav 按章节时间轴
抽每章结尾 9 秒转写,核对解说尾句是否完整出现。

用法(work/.venv-ocr 环境,需 faster-whisper):
  work/.venv-ocr/Scripts/python.exe work/tail_check.py \
    --content src/mzx_story/ming-10-jiajing1.json --audio D:/mzx-ming10-cv3/audio.wav
退出码: 0=全部命中  1=有章节缺失
"""
import argparse
import json
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from av_qc import normalize_spoken, is_hallucination, _pinyin  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--content", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--model", default=str(ROOT / "work/models/faster-whisper-large-v3-turbo"))
    ap.add_argument("--win", type=float, default=9.0, help="每章尾部转写窗口秒数")
    args = ap.parse_args()

    tl_path = Path(args.audio).parent / "timeline.json"
    tl = json.load(open(tl_path, encoding="utf-8"))
    audio_dur = tl["audio_duration"]
    bounds = [(c["index"], c["title"], c["end"]) for c in tl["chapters"]]

    content = json.load(open(args.content, encoding="utf-8"))
    expected_tails = {}
    for i, ch in enumerate(content["chapters"]):
        spoken = ch.get("tts_narration") or ch["narration"]
        expected_tails[i] = normalize_spoken(spoken)[-12:]

    tmp_dir = Path(args.audio).parent / "_tails"
    tmp_dir.mkdir(exist_ok=True)

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    ffmpeg = ROOT / "work/video-tools/ffmpeg.exe"
    fails = 0
    for idx, title, end in bounds:
        t_end = min(end + 1.0, audio_dur)
        t_start = max(0.0, t_end - args.win)
        wav = tmp_dir / f"tail_{idx}.wav"
        subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                        "-ss", f"{t_start:.2f}", "-t", f"{t_end - t_start:.2f}",
                        "-i", str(args.audio), "-ar", "16000", "-ac", "1", str(wav)], check=True)
        segs, _ = model.transcribe(str(wav), language="zh", vad_filter=True)
        segs = [(s.start, s.end, s.text) for s in segs]
        text = "".join(t for _, _, t in segs if not is_hallucination(t))
        got = normalize_spoken(text)
        exp = expected_tails[idx]
        # 拼音层比对:ASR 同音选字(嘉靖→家境)不算错,只有真缺音节才 FAIL
        exp_py, got_py = _pinyin(exp), _pinyin(got)
        if exp_py in got_py:
            verdict, ratio = "PASS", 1.0
        else:
            window = got_py[-(len(exp_py) + 6):]
            ratio = SequenceMatcher(None, exp_py, window).ratio()
            verdict = "PASS" if ratio >= 0.85 else "FAIL"
        if verdict == "FAIL":
            fails += 1
        print(f"[{verdict}] s{idx + 1} {title}: 期望尾音 {exp_py!r} | 转写尾音 {got_py[-24:]!r} (相似 {ratio:.2f})")

    print("全部命中" if fails == 0 else f"{fails} 章未命中")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
