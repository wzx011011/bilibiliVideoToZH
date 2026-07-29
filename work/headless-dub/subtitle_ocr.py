"""硬字幕 OCR 提取工具。

把视频画面里烧录的中英双语硬字幕提取成带精确时间戳的中文 SRT。
质量优于 Whisper 听写 + NLLB 机翻的方案：字幕是专业人工翻译，时间戳
来自画面字幕本身（而非英文转写段）。

流程三阶段：
  A. 变化检测 —— 沿时间轴每步抽底部字幕带，帧间像素差定位每条字幕的
     出现/消失时刻，得到 [start, end] 时间戳。
  B. 文字 OCR —— 对每条字幕的稳定期抽一帧，裁字幕带放大，用 RapidOCR
     识别文字，过滤掉英文行只留中文。
  C. 生成 SRT/Cue JSON —— 按现有 dub_pipeline 的格式输出。

断点恢复：阶段产物落到中间 JSON，重跑跳过已完成阶段。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np


# --- 路径常量（与 dub_pipeline.py 保持一致）---
ROOT = Path(__file__).resolve().parents[2]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"

# --- 字幕带几何（已在 p16 实测确认）---
# 画面 948x720，底部硬字幕：英文行 y≈82%~87%，中文行 y≈88%~94%。
# 变化检测扫描覆盖中英两行；OCR 只裁中文行。
BAND_TOP_RATIO = 0.78      # 变化检测扫描带顶（含中英两行）
BAND_BOTTOM_RATIO = 0.97
# OCR 裁切：字幕布局不固定（通常英+中两行，偶尔英+中1+中2 三行），
# 故裁整个字幕带交给模型逐行读中文，而非固定裁单行。窄裁会在双行中文时
# 把多行糊在一起导致模型识别失败（实测 117s 三行字幕窄裁读不出）。
OCR_BAND_TOP_RATIO = 0.76
OCR_BAND_BOTTOM_RATIO = 0.98
OCR_SCALE = 2              # 宽裁放大 2 倍即可（带子本身较宽）

# --- 变化检测参数 ---
SAMPLE_INTERVAL = 0.2      # 抽帧步长（秒）；越小越准但越慢
MIN_EVENT_GAP = 0.4        # 间隔小于此值的相邻事件合并（秒）
MIN_EVENT_DURATION = 0.3   # 短于此长度的事件丢弃（噪声）
# 字幕存在判别：白像素（亮度>200）占字幕带面积的比例。
# 实测 p16 信号呈双峰分布——无字幕帧 ≈0.000，有字幕帧 ≥0.07，中间几乎无值。
# 用绝对阈值 0.04 即可清晰区分，无需基线归一化。
WHITE_RATIO_THRESHOLD = 0.04
SCAN_ENGINE_VERSION = "ffmpeg-rawvideo-v1"


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SubtitleEvent:
    """一条字幕的出现区间。text 在阶段 B 填入。"""
    start: float
    end: float
    text: str = ""


# =====================================================================
# 阶段 A：字幕变化检测
# =====================================================================

def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _probe_video_dimensions(path: Path) -> tuple[int, int]:
    """Return the first video stream's dimensions for a rawvideo frame size."""
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    try:
        stream = json.loads(result.stdout)["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not determine video dimensions: {path}") from exc
    if width <= 0 or height <= 0:
        raise RuntimeError(f"invalid video dimensions {width}x{height}: {path}")
    return width, height


def _read_exact(stream, byte_count: int) -> bytes:
    """Read one raw frame, allowing for short reads from a pipe."""
    chunks: list[bytes] = []
    remaining = byte_count
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _scan_subtitle_signals(video: Path, duration: float, interval: float,
                           progress: Callable[[int, int], None] | None = None
                           ) -> tuple[np.ndarray, list[float]]:
    """Sample subtitle-band white-pixel signals through one ffmpeg process.

    The source files use AV1, which the installed OpenCV build cannot decode.
    Streaming raw grayscale frames from ffmpeg avoids one process and temporary
    PNG per sample while retaining ffmpeg's AV1 support.
    """
    if interval <= 0:
        raise ValueError("subtitle sampling interval must be positive")
    if duration <= 0:
        return np.array([], dtype=float), []

    width, height = _probe_video_dimensions(video)
    band_top = round(height * BAND_TOP_RATIO)
    band_height = round(height * (BAND_BOTTOM_RATIO - BAND_TOP_RATIO))
    if band_height <= 0 or band_top < 0 or band_top + band_height > height:
        raise RuntimeError(f"invalid subtitle crop for {width}x{height}")

    sample_rate = 1.0 / interval
    filter_graph = (
        # Convert before cropping so an odd-height band is not truncated to an
        # even YUV chroma boundary.
        f"fps={sample_rate:.12g},format=gray,crop={width}:{band_height}:0:{band_top}"
    )
    command = [
        str(FFMPEG), "-hide_banner", "-v", "error", "-nostdin",
        "-i", str(video), "-t", f"{duration:.9g}", "-map", "0:v:0",
        "-an", "-vf", filter_graph, "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise RuntimeError("could not open ffmpeg output pipes")

    frame_bytes = width * band_height
    expected_samples = math.ceil(duration / interval)
    signals: list[float] = []
    try:
        while True:
            raw = _read_exact(process.stdout, frame_bytes)
            if not raw:
                break
            if len(raw) != frame_bytes:
                raise RuntimeError(
                    f"ffmpeg produced an incomplete subtitle frame "
                    f"({len(raw)}/{frame_bytes} bytes)"
                )
            band = np.frombuffer(raw, dtype=np.uint8).reshape(band_height, width)
            signals.append(float((band > 200).mean()))
            if progress is not None:
                progress(len(signals), expected_samples)

        stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
        returncode = process.wait()
        if returncode != 0:
            detail = f": {stderr}" if stderr else ""
            raise RuntimeError(f"ffmpeg subtitle scan failed ({returncode}){detail}")
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stderr.close()

    timestamps = np.arange(len(signals), dtype=float) * interval
    return timestamps, signals


def _grab_subtitle_band(video: Path, timestamp: float) -> np.ndarray:
    """抽指定时刻的底部字幕带（中英两行），返回灰度图。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    try:
        band_height = BAND_BOTTOM_RATIO - BAND_TOP_RATIO
        subprocess.run(
            [str(FFMPEG), "-y", "-ss", f"{timestamp}", "-i", str(video),
             "-frames:v", "1", "-nostdin",
             "-vf", f"crop=iw:'ih*{band_height}':0:'ih*{BAND_TOP_RATIO}'",
             str(tmp)],
            capture_output=True, check=False,
        )
        img = cv2.imread(str(tmp), cv2.IMREAD_GRAYSCALE)
        return img if img is not None else np.zeros((10, 10), dtype=np.uint8)
    finally:
        tmp.unlink(missing_ok=True)


def detect_events(video: Path, duration: float | None = None,
                  interval: float = SAMPLE_INTERVAL,
                  anchor_cues: list[Cue] | None = None,
                  progress: Callable[[int, int], None] | None = None
                  ) -> list[SubtitleEvent]:
    """阶段 A：定位每条字幕的出现/消失时刻。

    两种模式：
      - 有 anchor_cues（推荐）：直接采用 Whisper 语音时间戳作为字幕事件边界。
        实测每个 cue 的中点都落在该句画面字幕的稳定显示期内（前面已逐条验证
        跨句 diff=44~65、同句稳定），因此中点抽帧可稳定 OCR。语音时间戳与字幕
        显示边界有 0.6~2.5s 偏差，但对字幕可读性影响很小；曾尝试用白像素精修
        边界，但连续字幕间隔过短导致重叠，收益不抵复杂度，故回退采用锚点时间戳。
      - 无 anchor_cues：全局盲扫，白像素占比超阈值的连续帧合并为事件。

    返回按时间排序的 SubtitleEvent 列表（text 暂空）。
    """
    if anchor_cues is not None and anchor_cues:
        return [SubtitleEvent(start=c.start, end=c.end) for c in anchor_cues]

    total = duration if duration is not None else _probe_duration(video)
    timestamps, signals = _scan_subtitle_signals(
        video, total, interval=interval, progress=progress,
    )
    return _segment_events(timestamps, signals)


def _white_ratios(bands: list[np.ndarray]) -> list[float]:
    """每帧字幕带的白像素（亮度>200）面积占比，0~1。

    实测无字幕帧 ≈0.000，有字幕帧 ≥0.07，双峰分明，绝对阈值即可区分。
    """
    return [float((band > 200).mean()) for band in bands]


def _segment_events(timestamps: np.ndarray, signals: list[float]
                    ) -> list[SubtitleEvent]:
    """把信号序列切成字幕事件。

    判定每帧是否"有字幕"：白像素占比 > WHITE_RATIO_THRESHOLD。
    连续的有字幕帧合并为一个事件。
    """
    if not signals:
        return []

    events: list[SubtitleEvent] = []
    in_event = False
    start = 0.0
    last_active_t = 0.0
    for t, sig in zip(timestamps, signals, strict=True):
        active = sig > WHITE_RATIO_THRESHOLD
        if active and not in_event:
            start = float(t)
            in_event = True
        if active:
            last_active_t = float(t)
        elif in_event and not active:
            events.append(SubtitleEvent(start=start, end=last_active_t))
            in_event = False
    if in_event:
        events.append(SubtitleEvent(start=start, end=last_active_t))

    # 合并间隔过小的相邻事件，丢弃过短事件
    return _merge_and_filter(events)


def _merge_and_filter(events: list[SubtitleEvent]
                      ) -> list[SubtitleEvent]:
    merged: list[SubtitleEvent] = []
    for ev in events:
        if (ev.end - ev.start) < MIN_EVENT_DURATION:
            continue
        if merged and (ev.start - merged[-1].end) <= MIN_EVENT_GAP:
            # 合并：取前一个的 start 和当前的 end
            prev = merged.pop()
            merged.append(SubtitleEvent(start=prev.start, end=ev.end))
        else:
            merged.append(ev)
    return merged


# =====================================================================
# 阶段 B：视觉 OCR
# =====================================================================

def _grab_subtitle_for_ocr(video: Path, timestamp: float, out: Path) -> bool:
    """抽指定时刻的整个字幕带（含中英所有行，裁切+放大），写入 out。

    裁整个字幕带而非单行：字幕行数不固定（双行中文时窄裁会把多行糊在一起），
    交给模型逐行读中文更鲁棒。成功返回 True。
    """
    band_height = OCR_BAND_BOTTOM_RATIO - OCR_BAND_TOP_RATIO
    result = subprocess.run(
        [str(FFMPEG), "-y", "-ss", f"{timestamp}", "-i", str(video),
         "-frames:v", "1",
         "-vf",
         f"crop=iw:'ih*{band_height}':0:'ih*{OCR_BAND_TOP_RATIO}',"
         f"scale=iw*{OCR_SCALE}:ih*{OCR_SCALE}",
         "-nostdin", str(out)],
        capture_output=True, check=False,
    )
    return result.returncode == 0 and out.exists() and out.stat().st_size > 0


_rapidocr_engine = None  # 模块级单例，首次识别时懒加载，后续复用


def _get_rapidocr():
    """懒加载 RapidOCR 单例引擎（首次约 0.5s 初始化，之后复用）。"""
    global _rapidocr_engine
    if _rapidocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapidocr_engine = RapidOCR()
    return _rapidocr_engine


def _rapidocr_chinese_lines(engine, img_path: Path) -> str:
    """用 RapidOCR 识别一张截图，只返回含中文的行（换行分隔）。

    RapidOCR 返回 [(box, text, score), ...]，会读出全部文字（这套视频是
    双语字幕，含中英文）。靠"是否含中文字符"过滤掉英文行——实测对本课程
    白字黑描边硬字幕 100% 有效。多行中文用换行符分隔（双行中文是合法的）。
    """
    result, _ = engine(str(img_path))
    if not result:
        return ""
    chinese_lines = []
    for _box, text, _score in result:
        text = text.strip()
        if text and re.search(r"[\u4e00-\u9fff]", text):
            chinese_lines.append(text)
    return "\n".join(chinese_lines)


def _sample_timestamps(ev: SubtitleEvent, max_gap: float = 1.5) -> list[float]:
    """对事件区间按 max_gap 间隔采样抽帧时刻。

    画面字幕逐句滚动显示，单帧只能抓到一屏。按时长决定帧数：
      - 时长 ≤ max_gap：抽 1 帧（中点）
      - 时长 > max_gap：每约 max_gap 一帧，覆盖 start..end

    max_gap=1.5s：实测字幕最快约1-2秒换一屏，3秒间隔会跳过中间屏
    （如"没有什么东西"在41.6s，3秒采样点40.7/43.6恰好跳过）。
    """
    duration = ev.end - ev.start
    if duration <= max_gap:
        return [(ev.start + ev.end) / 2]
    # 均匀采样：n 帧，间隔约 max_gap
    n = max(2, int(duration / max_gap) + 1)
    step = duration / n
    return [ev.start + step * (k + 0.5) for k in range(n)]


def _merge_fragment_texts(fragments: list[str]) -> str:
    """把同一事件多帧识别的文本片段按时序合并，去重相邻重复。

    字幕滚动时相邻屏可能有重叠（同一短语在两屏都出现），用包含关系去重。
    每个片段也可能是一页双行中文；必须先按整页去重，否则每次采样都会把
    第一行、第二行交替追加，造成静态字幕重复。
    """
    pages: list[str] = []
    for frag in fragments:
        lines = [line.strip() for line in frag.split("\n") if line.strip()]
        page = "\n".join(lines)
        if not page:
            continue
        if not pages:
            pages.append(page)
            continue
        prev = pages[-1]
        # 当前页是上一页的子串（重复屏），跳过。
        if page in prev:
            continue
        # 上一页是当前页的子串（当前更完整），替换。
        if prev in page:
            pages[-1] = page
            continue
        # 处理滚动字幕的后缀/前缀重叠；无重叠则保留为下一页。
        overlap = _overlap_len(prev, page)
        if overlap > 0:
            pages[-1] = prev + page[overlap:]
        else:
            pages.append(page)
    if not pages:
        return ""
    return pages[0] if len(pages) == 1 else " ".join(pages)


def _overlap_len(a: str, b: str, min_overlap: int = 2) -> int:
    """a 的后缀与 b 的前缀的最大重叠长度（至少 min_overlap 才算）。"""
    max_check = min(len(a), len(b), 12)
    for n in range(max_check, min_overlap - 1, -1):
        if a[-n:] == b[:n]:
            return n
    return 0


def ocr_events(events: list[SubtitleEvent], video: Path, model: str,
               base_url: str | None = None,
               progress: Callable[[int, int], None] | None = None,
               on_result: Callable[[int, SubtitleEvent], None] | None = None,
               ) -> list[SubtitleEvent]:
    """阶段 B：对每个事件抽帧（长事件多帧），用 RapidOCR 识别中文行并合并。

    画面字幕逐句滚动，单帧只能抓到一屏；长事件按 ~3s 间隔抽多帧，分别识别后
    去重合并成完整句。

    model：OCR 引擎标识（目前仅 "rapidocr"，参数保留为兼容指纹/CLI，未实际使用）。
    base_url：已废弃（原 ollama 端点），仅为向后兼容保留参数，不再使用。
    on_result(index, event)：每条识别完成后回调，用于即时持久化（细粒度断点恢复）。
    """
    engine = _get_rapidocr()
    out: list[SubtitleEvent] = []
    n = len(events)
    for i, ev in enumerate(events):
        fragments: list[str] = []
        for t in _sample_timestamps(ev):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                img_path = Path(f.name)
            try:
                ok = _grab_subtitle_for_ocr(video, t, img_path)
                if ok:
                    fragments.append(_rapidocr_chinese_lines(engine, img_path))
            finally:
                img_path.unlink(missing_ok=True)
        text = _merge_fragment_texts(fragments)
        result = SubtitleEvent(start=ev.start, end=ev.end, text=text)
        out.append(result)
        if on_result is not None:
            on_result(i, result)
        if progress is not None:
            progress(i + 1, n)
    return out


# =====================================================================
# 阶段 C：生成 SRT / Cue JSON
# =====================================================================

def _srt_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_text(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{_srt_timestamp(c.start)} --> {_srt_timestamp(c.end)}\n{c.text}"
        for i, c in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def events_to_cues(events: list[SubtitleEvent]) -> list[Cue]:
    """丢弃空文本事件，转成 Cue（兼容 dub_pipeline 的格式）。"""
    return [Cue(e.start, e.end, e.text) for e in events if e.text.strip()]


def cues_to_jsonable(cues: list[Cue]) -> list[dict]:
    return [asdict(c) for c in cues]


# =====================================================================
# 持久化与断点恢复
# =====================================================================

def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _fingerprint_file(path: Path) -> str:
    st = path.stat()
    payload = f"{path.resolve()}:{st.st_size}:{st.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _events_to_jsonable(events: list[SubtitleEvent]) -> list[dict]:
    return [{"start": e.start, "end": e.end, "text": e.text} for e in events]


def _events_from_jsonable(items: list[dict]) -> list[SubtitleEvent]:
    return [SubtitleEvent(start=float(it["start"]), end=float(it["end"]),
                          text=it.get("text", "")) for it in items]


# =====================================================================
# 主流程
# =====================================================================


def _detect_stage(video: Path, output_dir: Path, duration: float | None,
                  anchor_cues: list[Cue] | None
                  ) -> tuple[Path, list[SubtitleEvent], str]:
    """Run or resume Stage A and return its cache path, events, and fingerprint."""
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / f"{video.stem}.events.json"
    fp_video = _fingerprint_file(video)
    anchor_tag = "anchored" if anchor_cues else f"blind:{SCAN_ENGINE_VERSION}"
    fp_detect = hashlib.sha256(
        f"{fp_video}:{duration}:{anchor_tag}:{SAMPLE_INTERVAL}:{BAND_TOP_RATIO}:{BAND_BOTTOM_RATIO}".encode()
    ).hexdigest()
    events: list[SubtitleEvent] = []
    if events_path.exists():
        try:
            blob = json.loads(events_path.read_text(encoding="utf-8"))
            if blob.get("fingerprint") == fp_detect:
                events = _events_from_jsonable(blob["events"])
                print(f"[A] 复用已有边界检测结果：{len(events)} 条事件", file=sys.stderr)
                return events_path, events, fp_detect
        except (json.JSONDecodeError, KeyError):
            pass

    if anchor_cues:
        print(f"[A] 采用 {len(anchor_cues)} 条 Whisper 锚点作为字幕时间戳...", file=sys.stderr)
    else:
        print(f"[A] 全局盲扫字幕边界（步长 {SAMPLE_INTERVAL}s）...", file=sys.stderr)
    events = detect_events(video, duration=duration, anchor_cues=anchor_cues,
                           progress=lambda i, n: _print_progress("A", i, n))
    _write_json(events_path, {"fingerprint": fp_detect, "events": _events_to_jsonable(events)})
    print(f"\n[A] 完成：{len(events)} 条字幕事件", file=sys.stderr)
    return events_path, events, fp_detect


def detect_stage(video: Path, output_dir: Path, duration: float | None = None,
                 anchor_cues: list[Cue] | None = None) -> Path:
    """Run only Stage A and return the resumable event-cache JSON path."""
    events_path, _, _ = _detect_stage(video, output_dir, duration, anchor_cues)
    return events_path


def run(video: Path, output_dir: Path, duration: float | None = None,
        model: str = "rapidocr",
        base_url: str | None = None,
        anchor_cues: list[Cue] | None = None) -> tuple[Path, Path]:
    """完整提取流程，返回 (srt_path, json_path)。带断点恢复。

    anchor_cues：可选的 Whisper 英文时间戳，作为字幕定位锚点。提供时会精修
    每条字幕的真实显示边界（画面检测）；不提供则全局盲扫。
    """
    stem = video.stem
    srt_path = output_dir / f"{stem}.zh-CN-ocr.srt"
    json_path = output_dir / f"{stem}.zh-CN-ocr.json"

    # --- 阶段 A：字幕边界检测（断点：events.json 存在则跳过）---
    events_path, events, fp_detect = _detect_stage(
        video, output_dir, duration, anchor_cues,
    )

    # --- 阶段 B：视觉 OCR（对缺 text 的事件逐条补齐，每条即时持久化）---
    todo = [i for i, e in enumerate(events) if not e.text.strip()]
    if todo:
        print(f"[B] 用 {model} 识别 {len(todo)} 条字幕...", file=sys.stderr)
        to_ocr = [events[i] for i in todo]

        def on_result(idx: int, result: SubtitleEvent) -> None:
            # idx 是在 to_ocr 中的位置，映射回 events 的全局位置
            events[todo[idx]] = SubtitleEvent(
                start=events[todo[idx]].start,
                end=events[todo[idx]].end,
                text=result.text,
            )
            _write_json(events_path, {"fingerprint": fp_detect,
                                      "events": _events_to_jsonable(events)})

        ocr_events(
            to_ocr, video, model, on_result=on_result,
            progress=lambda i, n: _print_progress("B", i, n),
        )
        print(f"\n[B] 完成", file=sys.stderr)
    else:
        print(f"[B] 全部字幕已识别，跳过", file=sys.stderr)

    # --- 阶段 C：生成 SRT / Cue JSON ---
    cues = events_to_cues(events)
    _write_text(srt_path, srt_text(cues))
    _write_json(json_path, cues_to_jsonable(cues))
    print(f"[C] 输出 {len(cues)} 条字幕：{srt_path.name}", file=sys.stderr)
    return srt_path, json_path


def _print_progress(stage: str, i: int, n: int) -> None:
    if i % 50 == 0 or i == n:
        print(f"\r[{stage}] {i}/{n}", end="", file=sys.stderr, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从视频中提取烧录的硬字幕（中文行），输出带时间戳的 SRT。")
    parser.add_argument("--input", required=True, type=Path, help="输入视频")
    parser.add_argument("--output", required=True, type=Path, help="输出目录")
    parser.add_argument("--duration", type=float, default=None,
                        help="只处理前 N 秒（默认全部）")
    parser.add_argument("--stage", choices=["all", "detect", "ocr"], default="all",
                        help="all=检测、OCR、导出字幕；detect=只生成事件缓存；"
                             "ocr=复用缓存后执行 OCR/导出")
    parser.add_argument("--model", default="rapidocr",
                        help="OCR 引擎名（目前固定 rapidocr，保留参数为兼容）")
    parser.add_argument("--anchors", type=Path, default=None,
                        help="Whisper 英文 cue JSON（dub_pipeline 的 *.en.json），"
                             "用于精修字幕真实显示边界")
    args = parser.parse_args()
    anchor_cues: list[Cue] | None = None
    if args.anchors:
        items = json.loads(args.anchors.read_text(encoding="utf-8"))
        anchor_cues = [Cue(start=float(it["start"]), end=float(it["end"]),
                           text=it.get("text", "")) for it in items]
    if args.stage == "detect":
        print(detect_stage(args.input, args.output, duration=args.duration,
                           anchor_cues=anchor_cues))
        return
    srt, js = run(args.input, args.output, duration=args.duration,
                  model=args.model, anchor_cues=anchor_cues)
    print(srt)
    print(js)


if __name__ == "__main__":
    main()
