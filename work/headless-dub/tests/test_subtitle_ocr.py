"""subtitle_ocr 的单元测试。

覆盖不依赖视觉模型的核心逻辑：变化检测的事件分段、事件合并/过滤、
SRT 生成、Cue 转换、清洗函数。视觉 OCR（阶段 B）需要真实模型，由端到
端脚本验证，此处不测。
"""

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

# 让测试能 import subtitle_ocr
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import subtitle_ocr as so
from subtitle_ocr import Cue, SubtitleEvent


# ---------------------------------------------------------------------
# 阶段 A：变化检测
# ---------------------------------------------------------------------

def test_segment_events_basic_two_blocks():
    """两段有字幕区间，应切成两个事件。"""
    timestamps = np.arange(0.0, 10.0, 0.2)
    signals = [0.0] * len(timestamps)
    # 用精确索引构造两段激活区间，避免 arange 浮点边界干扰
    # 区间1: 索引 5~12 (1.0s~2.4s)
    for i in range(5, 13):
        signals[i] = 0.9
    # 区间2: 索引 25~33 (5.0s~6.6s)
    for i in range(25, 34):
        signals[i] = 0.8
    events = so._segment_events(timestamps, signals)
    assert len(events) == 2
    assert events[0].start == pytest.approx(timestamps[5], abs=1e-6)
    assert events[0].end == pytest.approx(timestamps[12], abs=1e-6)
    assert events[1].start == pytest.approx(timestamps[25], abs=1e-6)
    assert events[1].end == pytest.approx(timestamps[33], abs=1e-6)


def test_segment_events_empty_when_no_subtitle():
    """全程无字幕，返回空。"""
    timestamps = np.arange(0.0, 5.0, 0.2)
    signals = [0.0] * len(timestamps)
    assert so._segment_events(timestamps, signals) == []


def test_segment_events_ignores_below_threshold():
    """低于绝对阈值（0.04）的信号不被当作字幕。"""
    timestamps = np.arange(0.0, 5.0, 0.2)
    signals = [0.0] * len(timestamps)
    # 一段信号在阈值以下（0.02 < 0.04），全程无字幕
    for i in range(10, 15):
        signals[i] = 0.02
    assert so._segment_events(timestamps, signals) == []


def test_segment_events_detects_above_threshold():
    """高于阈值（0.04）的连续信号被当作一个事件。"""
    timestamps = np.arange(0.0, 5.0, 0.2)
    signals = [0.0] * len(timestamps)
    # 一段信号在阈值以上（0.08 > 0.04）
    for i, t in enumerate(timestamps):
        if 1.0 <= t <= 2.0:
            signals[i] = 0.08
    events = so._segment_events(timestamps, signals)
    assert len(events) == 1
    assert events[0].start == 1.0


def test_merge_and_filter_drops_short_events():
    """短于 MIN_EVENT_DURATION 的事件被丢弃。"""
    events = [
        SubtitleEvent(start=0.0, end=0.1),   # 太短，丢弃
        SubtitleEvent(start=1.0, end=2.0),   # 保留
    ]
    result = so._merge_and_filter(events)
    assert len(result) == 1
    assert result[0].start == 1.0


def test_merge_and_filter_merges_close_events():
    """间隔小于 MIN_EVENT_GAP 的相邻事件合并。"""
    events = [
        SubtitleEvent(start=1.0, end=2.0),
        SubtitleEvent(start=2.2, end=3.0),   # 间隔 0.2 < 0.4，合并
    ]
    result = so._merge_and_filter(events)
    assert len(result) == 1
    assert result[0].start == 1.0
    assert result[0].end == 3.0


def test_merge_and_filter_keeps_distant_events():
    """间隔足够大的事件保持独立。"""
    events = [
        SubtitleEvent(start=1.0, end=2.0),
        SubtitleEvent(start=3.0, end=4.0),   # 间隔 1.0 > 0.4，独立
    ]
    result = so._merge_and_filter(events)
    assert len(result) == 2


def test_sample_timestamps_short_event_single_frame():
    """短事件（≤1.5s）只抽中点一帧。"""
    ev = SubtitleEvent(start=10.0, end=11.0)
    ts = so._sample_timestamps(ev)
    assert ts == [10.5]


def test_sample_timestamps_long_event_multiple_frames():
    """长事件（>3s）抽多帧，覆盖整个区间。"""
    ev = SubtitleEvent(start=10.0, end=22.0)  # 12秒
    ts = so._sample_timestamps(ev)
    assert len(ts) >= 3
    assert ts[0] >= 10.0
    assert ts[-1] <= 22.0
    # 各帧间隔约 1.5 秒（max_gap），允许 1~2.5 秒浮动
    gaps = [ts[i+1] - ts[i] for i in range(len(ts)-1)]
    assert all(1.0 <= g <= 2.5 for g in gaps)


def test_merge_fragment_texts_drops_duplicate_screen():
    """相邻屏重复（当前是上一片段子串）时跳过。"""
    assert so._merge_fragment_texts(["这个学期不错", "这个学期不错"]) == "这个学期不错"


def test_merge_fragment_texts_drops_duplicate_multiline_page():
    page = "第16讲\n哈佛幸福课"
    assert so._merge_fragment_texts([page, page, page]) == page


def test_merge_fragment_texts_concatenates_distinct():
    """无重叠的不同片段直接拼接。"""
    assert so._merge_fragment_texts(["早上好", "完美主义"]) == "早上好 完美主义"


def test_merge_fragment_texts_overlap_join():
    """后缀/前缀重叠时智能拼接。"""
    # 上一片段以"后悔"结尾，当前以"后悔"开头 → 合并去重
    result = so._merge_fragment_texts(["让我后悔", "后悔做过的事"])
    assert "做过的事" in result
    assert result.count("后悔") == 1


def test_merge_fragment_texts_empty():
    assert so._merge_fragment_texts([]) == ""
    assert so._merge_fragment_texts(["", "  "]) == ""


def test_merge_fragment_texts_replaces_with_fuller():
    """当前片段包含上一片段时，用更完整的替换。"""
    result = so._merge_fragment_texts(["学期不错", "这个学期不错"])
    assert result == "这个学期不错"
    """信号是白像素占比（绝对值）。"""
    bg = np.full((50, 100), 50, dtype=np.uint8)
    white = np.full((50, 100), 50, dtype=np.uint8)
    white[20:30, 20:80] = 250
    signals = so._white_ratios([bg, bg, white, white])
    assert len(signals) == 4
    assert signals[0] == 0.0
    assert signals[2] > 0.0
    assert signals[2] > signals[0]


def test_detect_events_uses_anchor_timestamps_directly(monkeypatch):
    """有 anchor_cues 时直接采用锚点时间戳作为事件边界（不抽帧精修）。"""
    monkeypatch.setattr(
        so.subprocess, "Popen",
        lambda *args, **kwargs: pytest.fail("anchor mode must not start ffmpeg"),
    )
    anchors = [Cue(4.0, 11.0, "a"), Cue(19.0, 26.0, "b")]
    events = so.detect_events(Path("fake"), anchor_cues=anchors)
    assert len(events) == 2
    assert events[0].start == 4.0
    assert events[0].end == 11.0
    assert events[1].start == 19.0
    assert events[1].end == 26.0
    assert all(e.text == "" for e in events)


class FakeFfmpegProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.waited = False
        self.killed = False

    def wait(self):
        self.waited = True
        return self.returncode

    def poll(self):
        return self.returncode if self.waited else None

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_detect_events_blind_mode_streams_one_ffmpeg_process(monkeypatch):
    """Blind mode reads sampled raw subtitle bands from one persistent ffmpeg."""
    # With a 10x10 source, the configured subtitle crop is 10x2.
    dark = np.zeros((2, 10), dtype=np.uint8).tobytes()
    bright = np.full((2, 10), 255, dtype=np.uint8).tobytes()
    process = FakeFfmpegProcess(dark + bright + bright + bright + dark + dark)
    commands = []

    def fake_popen(command, **kwargs):
        commands.append(command)
        return process

    monkeypatch.setattr(so, "_probe_video_dimensions", lambda _video: (10, 10))
    monkeypatch.setattr(so.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        so.subprocess, "run",
        lambda *args, **kwargs: pytest.fail("blind scan must not invoke one ffmpeg per sample"),
    )
    progress = []

    events = so.detect_events(
        Path("fake"), duration=1.2, interval=0.2,
        progress=lambda current, total: progress.append((current, total)),
    )

    assert [(event.start, event.end) for event in events] == [
        (pytest.approx(0.2), pytest.approx(0.6)),
    ]
    assert len(commands) == 1
    assert "fps=5,format=gray,crop=10:2:0:8" in commands[0]
    assert progress[-1] == (6, 6)
    assert process.killed is False


def test_scan_subtitle_signals_keeps_only_signal_values(monkeypatch):
    dark = np.zeros((2, 10), dtype=np.uint8).tobytes()
    bright = np.full((2, 10), 255, dtype=np.uint8).tobytes()
    process = FakeFfmpegProcess(dark + bright)
    monkeypatch.setattr(so, "_probe_video_dimensions", lambda _video: (10, 10))
    monkeypatch.setattr(so.subprocess, "Popen", lambda *args, **kwargs: process)

    timestamps, signals = so._scan_subtitle_signals(
        Path("fake"), duration=0.4, interval=0.2,
    )

    assert timestamps.tolist() == [0.0, 0.2]
    assert signals == [0.0, 1.0]
    assert all(isinstance(signal, float) for signal in signals)


def test_blind_scan_surfaces_ffmpeg_error(monkeypatch):
    process = FakeFfmpegProcess(b"", stderr=b"AV1 decoder failed", returncode=1)
    monkeypatch.setattr(so, "_probe_video_dimensions", lambda _video: (10, 10))
    monkeypatch.setattr(so.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(RuntimeError, match="AV1 decoder failed"):
        so._scan_subtitle_signals(Path("fake"), duration=1.0, interval=0.2)


def test_run_invalidates_old_blind_cache_after_scan_engine_change(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    old_fingerprint = hashlib.sha256(
        f"{so._fingerprint_file(video)}:1.0:blind:{so.SAMPLE_INTERVAL}:"
        f"{so.BAND_TOP_RATIO}:{so.BAND_BOTTOM_RATIO}".encode()
    ).hexdigest()
    events_path = output_dir / "source.events.json"
    events_path.write_text(
        '{"fingerprint": "' + old_fingerprint +
        '", "events": [{"start": 0.0, "end": 1.0, "text": "旧字幕"}]}',
        encoding="utf-8",
    )
    calls = []

    def fake_detect(*args, **kwargs):
        calls.append((args, kwargs))
        return [SubtitleEvent(0.0, 1.0, "新字幕")]

    monkeypatch.setattr(so, "detect_events", fake_detect)
    _, json_path = so.run(video, output_dir, duration=1.0)

    assert len(calls) == 1
    assert json.loads(json_path.read_text(encoding="utf-8")) == [
        {"start": 0.0, "end": 1.0, "text": "新字幕"}
    ]


def test_detect_stage_writes_events_without_running_ocr(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source")
    output_dir = tmp_path / "output"

    monkeypatch.setattr(
        so, "detect_events",
        lambda *args, **kwargs: [SubtitleEvent(1.0, 2.0)],
    )
    monkeypatch.setattr(
        so, "ocr_events",
        lambda *args, **kwargs: pytest.fail("detect stage must not invoke OCR"),
    )

    events_path = so.detect_stage(video, output_dir, duration=3.0)

    assert events_path == output_dir / "source.events.json"
    blob = json.loads(events_path.read_text(encoding="utf-8"))
    assert blob["events"] == [{"start": 1.0, "end": 2.0, "text": ""}]
    assert not (output_dir / "source.zh-CN-ocr.srt").exists()


def test_main_detect_stage_skips_full_ocr_pipeline(tmp_path, monkeypatch, capsys):
    expected = tmp_path / "source.events.json"
    calls = []

    def fake_detect_stage(video, output_dir, duration=None, anchor_cues=None):
        calls.append((video, output_dir, duration, anchor_cues))
        return expected

    monkeypatch.setattr(
        sys, "argv",
        ["subtitle_ocr.py", "--input", "source.mp4", "--output", "output", "--stage", "detect"],
    )
    monkeypatch.setattr(so, "detect_stage", fake_detect_stage)
    monkeypatch.setattr(
        so, "run",
        lambda *args, **kwargs: pytest.fail("--stage detect must not invoke the full pipeline"),
    )

    so.main()

    assert calls == [(Path("source.mp4"), Path("output"), None, None)]
    assert capsys.readouterr().out.strip() == str(expected)


# ---------------------------------------------------------------------
# 阶段 C：SRT / Cue 生成
# ---------------------------------------------------------------------

def test_srt_timestamp_format():
    assert so._srt_timestamp(0.0) == "00:00:00,000"
    assert so._srt_timestamp(1.5) == "00:00:01,500"
    assert so._srt_timestamp(3661.234) == "01:01:01,234"


def test_srt_text_format():
    cues = [Cue(start=1.0, end=2.5, text="你好"), Cue(start=3.0, end=4.0, text="世界")]
    out = so.srt_text(cues)
    assert "1\n00:00:01,000 --> 00:00:02,500\n你好" in out
    assert "2\n00:00:03,000 --> 00:00:04,000\n世界" in out
    assert out.endswith("\n")


def test_srt_text_empty():
    assert so.srt_text([]) == ""


def test_events_to_cues_drops_empty_text():
    """空文本的事件被丢弃（OCR 失败的条目）。"""
    events = [
        SubtitleEvent(start=1.0, end=2.0, text="你好"),
        SubtitleEvent(start=3.0, end=4.0, text=""),       # 空，丢弃
        SubtitleEvent(start=5.0, end=6.0, text="   "),    # 空白，丢弃
    ]
    cues = so.events_to_cues(events)
    assert len(cues) == 1
    assert cues[0].text == "你好"
    assert cues[0].start == 1.0


def test_cues_to_jsonable_format():
    """JSON 格式兼容 dub_pipeline 的 _cues_from_json（start/end/text）。"""
    cues = [Cue(start=1.0, end=2.0, text="测试")]
    data = so.cues_to_jsonable(cues)
    assert data == [{"start": 1.0, "end": 2.0, "text": "测试"}]


# ---------------------------------------------------------------------
# OCR 输出清洗
# ---------------------------------------------------------------------

def test_clean_strips_think_block():
    raw = "<think>这是思考</think>有什么消息吗"
    assert so._clean_ocr_output(raw) == "有什么消息吗"


def test_clean_strips_quotes_and_prefixes():
    assert so._clean_ocr_output('"早上好"') == "早上好"
    assert so._clean_ocr_output("图中字幕：今天") == "今天"
    assert so._clean_ocr_output("文字内容：你好") == "你好"


def test_clean_preserves_multiple_lines():
    """多行中文（双行字幕）被保留，用换行分隔。"""
    assert so._clean_ocr_output("第一行\n第二行") == "第一行\n第二行"


def test_clean_drops_empty_lines():
    assert so._clean_ocr_output("你好\n\n\n世界") == "你好\n世界"


def test_clean_preserves_normal_text():
    assert so._clean_ocr_output("这学期过得不错") == "这学期过得不错"


# ---------------------------------------------------------------------
# 持久化往返
# ---------------------------------------------------------------------

def test_events_json_roundtrip():
    events = [
        SubtitleEvent(start=1.0, end=2.0, text="你好"),
        SubtitleEvent(start=3.0, end=4.0, text=""),
    ]
    items = so._events_to_jsonable(events)
    restored = so._events_from_jsonable(items)
    assert restored == events
