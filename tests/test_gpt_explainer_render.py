from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from gpt_explainer.render import (  # noqa: E402
    build_subtitle_cues,
    build_timeline,
    format_srt_timestamp,
    wrap_subtitle,
)


def test_wrap_subtitle_preserves_text_and_two_line_limit():
    text = "这是一个很长的中文旁白句子，用于验证字幕不会丢失字符，也不会生成难以阅读的超长单行。"
    cues = wrap_subtitle(text)
    assert "".join(cues).replace("\n", "") == text
    assert all(len(part.replace("\n", "")) <= 26 for part in cues)
    assert all(len(line) <= 13 for part in cues for line in part.split("\n"))


def test_srt_timestamp_rounding_and_rollover():
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(61.2346) == "00:01:01,235"
    assert format_srt_timestamp(3661.5) == "01:01:01,500"


def test_timeline_has_lead_gaps_tail():
    content = {"chapters": [{"title": "A", "kind": "cover"}, {"title": "B", "kind": "bars"}]}
    timeline = build_timeline(content, [2.0, 3.5])
    assert timeline["chapters"][0]["start"] == 0.5
    assert timeline["chapters"][0]["end"] == 2.5
    assert timeline["chapters"][1]["start"] == 3.5
    assert timeline["chapters"][1]["end"] == 7.0
    assert timeline["audio_duration"] == 9.0


def test_subtitle_cues_are_proportional_and_exact():
    content = {"chapters": [{"title": "A", "narration": "甲乙。丙丁戊己。"}]}
    timeline = build_timeline(content, [6.0], lead=0.5, gap=0.6, tail=2.0)
    cues = build_subtitle_cues(content, timeline, max_chars=4)
    assert "".join(cue["text"].replace("\n", "") for cue in cues) == "甲乙。丙丁戊己。"
    assert cues[0]["start"] == 0.5
    assert cues[-1]["end"] == 6.5
    assert all(cue["start"] < cue["end"] for cue in cues)
    assert all(len(line) <= 2 for cue in cues for line in cue["text"].split("\n"))


def test_timeline_json_is_serializable():
    content = {"chapters": [{"title": "A", "narration": "测试"}]}
    timeline = build_timeline(content, [1.25])
    json.dumps(timeline, ensure_ascii=False)


def test_polish_frames_keeps_tail_syllables_when_compressing_pause():
    """停顿压缩只在停顿处收窄,句尾内容必须完整(ep08 "好生教导" 被砍事故回归)。"""
    import math
    from array import array

    from gpt_explainer.render import _polish_frames

    sr = 16000
    amp, quiet_amp = 3000, 50  # 均值整流后分别高于话音阈值/低于静音阈值

    def voiced(sec: float) -> array:
        n = int(sr * sec)
        return array("h", (int(amp * math.sin(2 * math.pi * 220 * i / sr)) for i in range(n)))

    def silence(sec: float) -> array:
        return array("h", [quiet_amp] * int(sr * sec))

    # 话音 0.5s + 超长停顿 1.5s + 话音 0.5s:结尾字必须原样保留
    frames = voiced(0.5) + silence(1.5) + voiced(0.5)
    out = _polish_frames(frames, sr)

    assert len(out) > int(sr * 1.2)  # 两段话音 + 压缩后的停顿
    win = sr // 50
    tail_rms = math.sqrt(sum(v * v for v in out[-win:]))  # 最末窗口仍是话音能量
    head_rms = math.sqrt(sum(v * v for v in out[:win]))
    assert tail_rms > 800 and head_rms > 800
