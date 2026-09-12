"""Render the GPT explainer editorial video from chapter audio and content JSON.

The renderer deliberately has no browser dependency. Pillow draws RGB frames and the
bundled ffmpeg encodes those frames while receiving them on stdin.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import wave
from array import array
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"
CONTENT = Path(__file__).with_name("content.json")
WIDTH, HEIGHT, FPS, SAMPLE_RATE = 1920, 1080, 30, 16000
FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

# Charcoal, warm white, restrained teal/coral editorial palette.
BG = (19, 24, 26)
PANEL = (29, 37, 39)
PANEL_2 = (36, 45, 46)
WHITE = (244, 243, 238)
MUTED = (154, 169, 166)
TEAL = (75, 190, 177)
CORAL = (232, 112, 97)
GOLD = (225, 191, 112)
GRID = (65, 79, 79)
DISCLAIMER = "第三方数据 / 非本次实测"
SOURCE_LABEL = "Artificial Analysis"  # 底部来源前缀,皮肤可覆盖


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
        return ImageFont.load_default()


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    return draw.textlength(text, font=font)


def _wrap_pixel(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
                width: int) -> list[str]:
    """Wrap text by rendered width while retaining every character."""
    lines: list[str] = []
    for paragraph in str(text).replace("\r", "").split("\n"):
        line = ""
        for char in paragraph:
            candidate = line + char
            if line and _text_width(draw, candidate, font) > width:
                lines.append(line)
                line = char
            else:
                line = candidate
        if line or not paragraph:
            lines.append(line)
    return lines or [""]


def wrap_subtitle(text: str, max_chars: int = 26, line_chars: int = 13) -> list[str]:
    """Return readable two-line subtitle text, preserving the narration exactly.

    Each returned string is one cue's display text; a newline separates its two
    visual lines. The limits count characters, which is appropriate for Chinese
    subtitles and deterministic in tests.
    """
    text = str(text).replace("\r", "").replace("\n", "")
    if max_chars < 1 or line_chars < 1:
        raise ValueError("subtitle limits must be positive")
    chunks = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    return ["\n".join(chunk[i:i + line_chars] for i in range(0, len(chunk), line_chars))
            for chunk in chunks] or [""]


def _subtitle_chunks(text: str, max_chars: int = 26) -> list[str]:
    """Split at sentence/phrase punctuation first, then hard-wrap long runs.

    Breaks prefer 。！？；：，、 (and ASCII peers); hard-split only when a single
    run exceeds max_chars.  Concatenation of returned chunks equals the input.
    """
    text = str(text).replace("\r", "").replace("\n", "")
    if not text:
        return []
    pieces = re.findall(r"[^，。！？；：.!?;]*[，。！？；：.!?;]?", text)
    runs: list[str] = []
    for piece in (p for p in pieces if p):
        while len(piece) > max_chars:
            runs.append(piece[:max_chars])
            piece = piece[max_chars:]
        if piece:
            runs.append(piece)
    chunks: list[str] = []
    pending = ""
    for run in runs:
        if pending and len(pending) + len(run) > max_chars:
            chunks.append(pending)
            pending = run
        else:
            pending += run
    if pending:
        chunks.append(pending)
    return chunks


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds as an SRT timestamp, rounding to the nearest millisecond."""
    ms = max(0, int(round(float(seconds) * 1000)))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


# Short alias useful to callers that use the common SRT naming.
fmt_srt = format_srt_timestamp

# 片头/章间/片尾静音,build_timeline 的期望与 assemble_audio 的拼接必须同源。
_LEAD_S, _GAP_S, _TAIL_S = 0.5, 1.0, 2.0


def build_timeline(content: dict[str, Any], durations: Iterable[float],
                   lead: float = _LEAD_S, gap: float = _GAP_S,
                   tail: float = _TAIL_S) -> dict[str, Any]:
    """Build chapter timing from audio durations and fixed editorial spacing."""
    chapters = content.get("chapters", [])
    durations = list(durations)
    if len(chapters) != len(durations):
        raise ValueError(f"expected {len(chapters)} audio parts, got {len(durations)}")
    cursor = float(lead)
    entries: list[dict[str, Any]] = []
    for index, (chapter, duration) in enumerate(zip(chapters, durations)):
        duration = max(0.0, float(duration))
        start, end = cursor, cursor + duration
        entries.append({
            "index": index,
            "title": chapter.get("title", ""),
            "kind": chapter.get("kind", "summary"),
            "start": round(start, 6),
            "end": round(end, 6),
            "duration": round(duration, 6),
            "narration": chapter.get("narration", ""),
            "source_ids": list(chapter.get("source_ids", [])),
        })
        cursor = end + (gap if index < len(chapters) - 1 else 0.0)
    total = cursor + float(tail)
    return {"fps": FPS, "sample_rate": SAMPLE_RATE, "lead": lead, "gap": gap,
            "tail": tail, "audio_duration": round(total, 6), "chapters": entries}


def build_subtitle_cues(content: dict[str, Any], timeline: dict[str, Any],
                        max_chars: int = 26,
                        line_chars: int | None = None,
                        by_sentence: bool = False) -> list[dict[str, Any]]:
    """Create proportional cues whose concatenated text equals each narration.

    line_chars controls the visual line wrap inside a cue; None keeps the
    legacy two-line behaviour ((max_chars+1)//2).  Pass line_chars >= max_chars
    for single-line cues.  by_sentence=True 以完整句(。！？；)为一条 cue,
    超长句回退到 _subtitle_chunks 的标点切分。
    """
    wrap_at = line_chars if line_chars is not None else max(1, (max_chars + 1) // 2)
    cues: list[dict[str, Any]] = []
    for chapter, entry in zip(content.get("chapters", []), timeline.get("chapters", [])):
        narration = str(chapter.get("narration", "")).replace("\r", "").replace("\n", "")
        if by_sentence:
            chunks = [s for s in re.findall(r"[^。！？；]*[。！？；]?", narration) if s]
            expanded: list[str] = []
            for sentence in chunks:
                if len(sentence) > max_chars:
                    expanded.extend(_subtitle_chunks(sentence, max_chars))
                else:
                    expanded.append(sentence)
            chunks = expanded
        else:
            chunks = _subtitle_chunks(narration, max_chars)
        if not chunks:
            continue
        total_chars = max(1, sum(len(c) for c in chunks))
        start = float(entry["start"])
        duration = float(entry["end"]) - start
        elapsed = 0.0
        for index, chunk in enumerate(chunks):
            cue_start = start + elapsed
            elapsed += duration * len(chunk) / total_chars
            cue_end = float(entry["end"]) if index == len(chunks) - 1 else start + elapsed
            cues.append({"start": cue_start, "end": cue_end,
                         "text": "\n".join(wrap_subtitle(chunk, max_chars, wrap_at)),
                         "chapter": entry["index"]})
    return cues


def write_srt(cues: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = []
    for index, cue in enumerate(cues, 1):
        lines.extend([str(index), f"{format_srt_timestamp(cue['start'])} --> "
                      f"{format_srt_timestamp(cue['end'])}", cue["text"], ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _part_files(out: Path) -> list[Path]:
    parts = sorted(out.joinpath("parts").glob("item_*.wav"))
    if not parts:
        raise FileNotFoundError(f"no audio parts found under {out / 'parts'}")
    return parts


def _audio_manifest(parts: list[Path]) -> list[dict[str, Any]]:
    return [{"name": p.name, "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
            for p in parts]


def _probe_duration(path: Path) -> float:
    try:
        result = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries",
                                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                                 str(path)], capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise RuntimeError(f"cannot probe audio {path}: {exc}") from exc


def _normalise_part(part: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-i", str(part),
                    "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le",
                    str(target)], check=True)


# ---- 拼接精修:首部静音修剪 + 句间停顿收紧 + 切点 8ms 去爆音微淡。
# 注意:CosyVoice 偶发把最后一字的尾音直接截断(话音响到文件尽头),
# 这属于生成缺陷,拼接层修不掉——由 work/fix_hot_tails.py 换种子重生成解决。
_QUIET_RMS = 150.0            # ≈-47dBFS,低于视为静音
_SPEECH_END_RMS = 840.0       # ≈-32dBFS,尾部最后一个高于它的帧视为话音结束
_KEEP_HEAD, _TAIL_GUARD = 0.20, 0.04
_GAP_CAP, _GAP_LONG = 0.55, 0.85   # 句间静音 >0.55s 压到 0.55s;>0.9s 压到 0.85s
_FADE = 0.008                 # 切点去爆音微淡,不可闻


def _polish_frames(frames: array, sr: int) -> array:
    win = max(1, sr // 50)
    n = len(frames) // win
    if n < 10:
        return frames
    rms = []
    for i in range(n):
        seg = frames[i * win:(i + 1) * win]
        acc = 0
        for v in seg:
            acc += v * v
        rms.append((acc / win) ** 0.5)
    quiet = [r < _QUIET_RMS for r in rms]

    head = 0
    while head < n and quiet[head]:
        head += 1
    lo = head - min(head, int(_KEEP_HEAD * 50))

    # 尾部只做"静音收敛":话音结束后留 40ms guard,其后的静音不保留(章间固定 0.6s)
    tail = n - 1
    while tail >= 0 and rms[tail] < _SPEECH_END_RMS:
        tail -= 1
    hi = min(n, tail + 1 + int(_TAIL_GUARD * 50)) if tail >= 0 else n

    audio = frames[lo * win:hi * win]
    # 句间长停顿按上限截短——必须在停顿位置拼接收窄;整段从尾部一刀切会剁掉结尾字
    shrinks = []  # (start_win, end_win, keep_win),音频窗口坐标
    run = 0
    total = hi - lo
    for i in range(total):
        run = run + 1 if quiet[lo + i] else 0
        if quiet[lo + i] and run >= 2 and (i + 1 == total or not quiet[lo + i + 1]):
            start, end = i + 1 - run, i + 1
            if start > 0 and end < total:
                length = run * 0.02
                cap = _GAP_CAP if length <= _GAP_CAP * 2 else _GAP_LONG
                keep = int(cap * 50)
                if run > keep:
                    shrinks.append((start, end, keep))
    if shrinks:
        pieces, prev = [], 0
        for start, end, keep in shrinks:
            pieces.append(audio[prev:(end - keep) * win])
            prev = end * win
        pieces.append(audio[prev:])
        audio = array(audio.typecode, b"".join(p.tobytes() for p in pieces))

    f = int(sr * _FADE)
    if f and len(audio) > f:
        for i in range(f):
            audio[i] = int(audio[i] * i / f)
            audio[-1 - i] = int(audio[-1 - i] * i / f)
    return audio


def _rewrite_polished(path: Path) -> None:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        frames = array("h", w.readframes(w.getnframes()))
    polished = _polish_frames(frames, sr)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(polished.tobytes())


def _read_wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def assemble_audio(out: Path, parts: list[Path] | None = None) -> tuple[Path, list[float]]:
    """Normalize and concatenate item WAVs, preserving a cache when inputs match.

    环境变量 GPTX_AUDIO_POLISH=0 跳过停顿/尾部精修(豆包等韵律自洽的引擎用 raw,
    保留原生句间停顿),manifest 记 polish:"raw" 与精修版缓存互斥。
    """
    out.mkdir(parents=True, exist_ok=True)
    parts = parts or _part_files(out)
    audio = out / "audio.wav"
    manifest_path = out / "audio_manifest.json"
    polish = os.environ.get("GPTX_AUDIO_POLISH", "1") != "0"
    manifest = {"polish": 3 if polish else "raw", "parts": _audio_manifest(parts)}
    if audio.exists() and manifest_path.exists():
        try:
            if json.loads(manifest_path.read_text(encoding="utf-8")) == manifest:
                cache_timeline = out / "timeline.json"
                if cache_timeline.exists():
                    data = json.loads(cache_timeline.read_text(encoding="utf-8"))
                    return audio, [c["duration"] for c in data.get("chapters", [])]
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    tmp = out / "_audio_normalized"
    tmp.mkdir(exist_ok=True)
    normalized: list[Path] = []
    for i, part in enumerate(parts):
        target = tmp / f"{i:04d}.wav"
        _normalise_part(part, target)
        if polish:
            _rewrite_polished(target)
        normalized.append(target)
    durations = [_read_wav_duration(path) for path in normalized]
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        silence = b"\0\0" * int(round(SAMPLE_RATE * _GAP_S))
        output.writeframes(b"\0\0" * int(round(SAMPLE_RATE * _LEAD_S)))
        for index, path in enumerate(normalized):
            with wave.open(str(path), "rb") as source:
                output.writeframes(source.readframes(source.getnframes()))
            if index < len(normalized) - 1:
                output.writeframes(silence)
        output.writeframes(b"\0\0" * int(round(SAMPLE_RATE * _TAIL_S)))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for path in normalized:
        path.unlink(missing_ok=True)
    tmp.rmdir()
    return audio, durations


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: tuple[int, ...], radius: int = 8,
             outline: tuple[int, ...] | None = None) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2 if outline else 1)


def _draw_notes(draw: ImageDraw.ImageDraw, notes: list[str], x: int, y: int, width: int) -> None:
    font = _font(27)
    cursor = y
    for note in notes[:5]:
        lines = _wrap_pixel(draw, f"•  {note}", font, width)
        draw.multiline_text((x, cursor), "\n".join(lines), font=font, fill=WHITE, spacing=8)
        cursor += len(lines) * 40 + 18


def _draw_bars(draw: ImageDraw.ImageDraw, bars: list[dict[str, Any]], x: int, y: int,
               width: int, reveal: float = 1.0) -> None:
    label_font, value_font = _font(27), _font(25, bold=True)
    for index, bar in enumerate(bars[:7]):
        yy = y + index * 74
        label = str(bar.get("label", ""))
        display = str(bar.get("display", bar.get("value", "")))
        draw.text((x, yy), label, font=label_font, fill=WHITE)
        draw.text((x + width - _text_width(draw, display, value_font), yy), display,
                  font=value_font, fill=TEAL)
        track = (x, yy + 39, x + width, yy + 55)
        _rounded(draw, track, GRID, 7)
        value, maximum = _as_number(bar.get("value")), _as_number(bar.get("max"))
        if value is not None and maximum and maximum > 0:
            ratio = max(0.0, min(1.0, value / maximum)) * max(0.0, min(1.0, reveal))
            _rounded(draw, (x, yy + 39, x + max(10, int(width * ratio)), yy + 55), TEAL, 7)


def render_scene(chapter: dict[str, Any], progress: float = 0.0, *, title: str = "",
                 as_of: str = "", index: int = 0, total: int = 1,
                 subtitle: str = "", width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """Render one full-frame editorial scene at a normalized chapter progress."""
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    progress = max(0.0, min(1.0, progress))
    kind = str(chapter.get("kind", "summary")).lower()
    headline = str(chapter.get("headline") or chapter.get("title") or "")
    kicker = str(chapter.get("kicker") or kind.upper())
    bars = chapter.get("bars") or []
    notes = [str(n) for n in chapter.get("notes", [])]
    sources = " · ".join(str(s) for s in chapter.get("source_ids", [])) or "—"

    # Persistent editorial chrome and chapter progress.
    draw.rectangle((0, 0, width, 8), fill=TEAL)
    draw.rectangle((0, 8, int(width * ((index + progress) / max(total, 1))), 14), fill=CORAL)
    draw.text((92, 52), title, font=_font(28, bold=True), fill=WHITE)
    date_text = f"截至 {as_of}" if as_of else ""
    draw.text((width - 92 - _text_width(draw, date_text, _font(25)), 56), date_text,
              font=_font(25), fill=MUTED)
    number_text = f"{index + 1:02d}  /  {total:02d}"
    draw.text((92, 132), number_text, font=_font(24, bold=True), fill=CORAL)
    draw.text((92 + _text_width(draw, number_text, _font(24, bold=True)) + 18, 132),
              kicker, font=_font(24, bold=True), fill=TEAL)
    draw.line((92, 182, width - 92, 182), fill=GRID, width=2)
    draw.text((92, 212), headline.replace('\n', ' · '), font=_font(46, bold=True), fill=WHITE)

    left, top, right, bottom = 92, 320, width - 92, 830
    _rounded(draw, (left, top, right, bottom), PANEL, 8)
    if kind == "cover":
        # 装饰环:原 GPT 模板的评分仪表视觉残留,默认保留旧行为;
        # 无数据含义的封面(如产品速览)可传 "ring": false 关掉。
        if chapter.get("ring", True):
            draw.ellipse((right - 520, top + 28, right - 85, bottom - 28), outline=TEAL, width=5)
            draw.arc((right - 520, top + 28, right - 85, bottom - 28), 210, 330, fill=CORAL, width=12)
        _draw_notes(draw, notes, left + 74, top + 120, 760)
    elif kind == "bars":
        _draw_bars(draw, bars, left + 74, top + 72, 1050, min(1.0, progress * 1.8 + 0.15))
        _draw_notes(draw, notes, left + 1210, top + 82, 460)
    elif kind == "flow":
        items = notes or [str(b.get("label", "")) for b in bars]
        count = min(5, len(items))
        for i, item in enumerate(items[:count]):
            x = left + 64 + i * ((right - left - 128) // max(count, 1))
            box_w = min(270, (right - left - 170) // max(count, 1))
            _rounded(draw, (x, top + 130, x + box_w, top + 340), PANEL_2,
                     8, TEAL if i / max(count, 1) <= progress else GRID)
            draw.text((x + 22, top + 155), f"{i + 1:02d}", font=_font(24, bold=True), fill=CORAL)
            lines = _wrap_pixel(draw, item, _font(28, bold=True), box_w - 44)
            draw.multiline_text((x + 22, top + 205), "\n".join(lines[:4]), font=_font(28, bold=True),
                                fill=WHITE, spacing=8)
            if i < count - 1:
                draw.line((x + box_w + 15, top + 235, x + box_w + 65, top + 235), fill=TEAL, width=5)
                draw.polygon([(x + box_w + 65, top + 235), (x + box_w + 48, top + 224),
                              (x + box_w + 48, top + 246)], fill=TEAL)
    elif kind == "hook":
        # 开场钩子:全幅产品图快切 + 超大字,按 progress 均分节拍,节拍内轻微推近。
        beats = chapter.get("beats") or []
        if beats:
            seg = 1.0 / max(len(beats), 1)
            idx = min(int(progress / seg), len(beats) - 1)
            local = (progress - idx * seg) / seg
            beat = beats[idx]
            src = Path(str(beat.get("src", "")))
            if not src.exists():
                src = ROOT / str(beat.get("src", ""))
            if src.exists():
                art = Image.open(src).convert("RGB")
                scale = max(width / art.width, height / art.height)
                art = art.resize((int(art.width * scale) + 1, int(art.height * scale) + 1),
                                 Image.LANCZOS)
                zoom = 1.0 + 0.06 * local
                crop_w, crop_h = max(2, int(width / zoom)), max(2, int(height / zoom))
                x0, y0 = (art.width - crop_w) // 2, (art.height - crop_h) // 2
                image.paste(art.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize(
                    (width, height), Image.LANCZOS), (0, 0))
                # 贴边渐变:顶部保页眉、底部保大字与字幕,不横穿画面主体
                for y0, h0, a0, a1 in ((0, 280, 170, 0), (640, 440, 0, 200)):
                    grad = Image.new("L", (1, h0))
                    for yy in range(h0):
                        grad.putpixel((0, yy), int(a0 + (a1 - a0) * yy / h0))
                    image.paste(Image.new("RGB", (width, h0), (0, 0, 0)),
                                (0, y0), grad.resize((width, h0)))
                draw = ImageDraw.Draw(image)
                # 重绘页眉与底部来源带(被全幅图覆盖);全幅图上不画分隔线
                draw.rectangle((0, 0, width, 8), fill=TEAL)
                draw.rectangle((0, 8, int(width * ((index + progress) / max(total, 1))), 14), fill=CORAL)
                draw.text((92, 52), title, font=_font(28, bold=True), fill=WHITE)
                if as_of:
                    date_text = f"截至 {as_of}"
                    draw.text((width - 92 - _text_width(draw, date_text, _font(25)), 56),
                              date_text, font=_font(25), fill=MUTED)
                head = f"{index + 1:02d}  /  {total:02d}"
                draw.text((92, 132), head, font=_font(24, bold=True), fill=CORAL)
                draw.text((92 + _text_width(draw, head, _font(24, bold=True)) + 18, 132),
                          kicker, font=_font(24, bold=True), fill=TEAL)
                draw.rectangle((0, 870, width, height), fill=(13, 17, 18))
                draw.text((92, 890), SOURCE_LABEL + ' | ' + sources,
                          font=_font(22, bold=True), fill=MUTED)
                # 超大字钩子(落在底部渐变区内)
                big, small = str(beat.get("big", "")), str(beat.get("small", ""))
                if big:
                    draw.text((92, 726), big, font=_font(116, bold=True), fill=WHITE,
                              stroke_width=10, stroke_fill=(0, 0, 0))
                if small:
                    draw.text((98, 676), small, font=_font(44, bold=True), fill=GOLD,
                              stroke_width=6, stroke_fill=(0, 0, 0))
    elif kind == "image":
        # Official product artwork, left; supporting notes, right.  A subtle
        # push-in driven by chapter progress keeps the still image alive.
        image_path = str(chapter.get("image", "") or "")
        if image_path:
            source = Path(image_path)
            if not source.exists():
                source = ROOT / image_path
            if source.exists():
                box_w, box_h = 1020, bottom - top - 20
                product = Image.open(source).convert("RGB")
                fit = min(box_w / product.width, box_h / product.height)
                width_i, height_i = max(2, int(product.width * fit)), max(2, int(product.height * fit))
                product = product.resize((width_i, height_i), Image.LANCZOS)
                zoom = 1.0 + 0.06 * progress
                crop_w, crop_h = max(2, int(width_i / zoom)), max(2, int(height_i / zoom))
                x0, y0 = (width_i - crop_w) // 2, (height_i - crop_h) // 2
                product = product.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize(
                    (width_i, height_i), Image.LANCZOS)
                mask = Image.new("L", (width_i, height_i), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, width_i, height_i), radius=16, fill=255)
                ix = left + 10 + (box_w - width_i) // 2
                iy = top + 10 + (box_h - height_i) // 2
                image.paste(product, (ix, iy), mask)
            else:
                draw.text((left + 64, top + 64), f"[missing image: {image_path}]",
                          font=_font(28), fill=CORAL)
        _draw_notes(draw, notes, left + 1080, top + 48, right - 40 - (left + 1080))
    elif kind == "price":
        draw.text((left + 78, top + 65), "成本构成", font=_font(30, bold=True), fill=GOLD)
        _draw_bars(draw, bars, left + 78, top + 125, 850, min(1.0, progress * 1.6 + .2))
        draw.text((left + 1040, top + 166), "→", font=_font(90, bold=True), fill=CORAL)
        total_label = '$' + format(sum(float(b['value']) for b in bars), '.2f')
        _rounded(draw, (left + 1160, top + 105, right - 70, top + 300), PANEL_2, 8, CORAL)
        draw.multiline_text((left + 1200, top + 145), "结论\n" + total_label, font=_font(36, bold=True),
                            fill=WHITE, spacing=14)
        _draw_notes(draw, notes, left + 80, top + 320, 1500)
    elif kind == "score":
        for i, note in enumerate(notes):
            yy = top + 45 + i * 112
            draw.text((left + 64, yy), f'{i + 1:02d}', font=_font(35, True), fill=TEAL)
            draw.text((left + 160, yy), note, font=_font(34, True), fill=WHITE)
            draw.line((left + 160, yy + 76, right - 70, yy + 76), fill=GRID, width=2)
    elif kind == "limits":
        _draw_notes(draw, notes, left + 90, top + 70, 1480)
    elif kind == "ruler": 
        # A ruler communicates thresholds without fabricating a metric.
        ruler_y = top + 220
        x0, x1 = left + 90, right - 90
        draw.line((x0, ruler_y, x1, ruler_y), fill=GRID, width=8)
        for i, bar in enumerate(bars[:5]):
            value, maximum = _as_number(bar.get("value")), _as_number(bar.get("max"))
            ratio = (value / maximum) if value is not None and maximum and maximum > 0 else (i + 1) / max(len(bars), 1)
            px = x0 + int((x1 - x0) * max(0, min(1, ratio)))
            draw.ellipse((px - 14, ruler_y - 14, px + 14, ruler_y + 14), fill=CORAL if i % 2 else TEAL)
            label = str(bar.get("display", bar.get("label", "")))
            draw.text((px - min(130, _text_width(draw, label, _font(23)) / 2), ruler_y + 42), label,
                      font=_font(23), fill=WHITE)
            draw.text((px - 80, ruler_y - 72), str(bar.get("label", "")), font=_font(22), fill=MUTED)
        _draw_notes(draw, notes, left + 90, top + 430, 1500)
    else:  # summary and unknown kinds
        for i, note in enumerate(notes[:4]):
            x = left + 70 + (i % 2) * 790
            y = top + 70 + (i // 2) * 205
            _rounded(draw, (x, y, x + 700, y + 145), PANEL_2, 8, TEAL if i == 0 else GRID)
            draw.text((x + 28, y + 24), f"{i + 1:02d}", font=_font(24, bold=True), fill=CORAL)
            draw.multiline_text((x + 92, y + 28), "\n".join(_wrap_pixel(draw, note, _font(27), 570)[:3]),
                                font=_font(27), fill=WHITE, spacing=7)
        if not notes:
            _draw_notes(draw, [chapter.get("narration", "")], left + 78, top + 90, 1500)

    # Bottom safe band keeps subtitles away from chart labels.
    draw.rectangle((0, 870, width, height), fill=(13, 17, 18))
    draw.text((92, 890), SOURCE_LABEL + ' | ' + sources, font=_font(22, bold=True), fill=MUTED)
    draw.text((width - 92 - _text_width(draw, DISCLAIMER, _font(20)), 892), DISCLAIMER,
              font=_font(20), fill=GOLD)
    if subtitle:
        subtitle_font = _font(34, bold=True)
        lines = subtitle.split("\n")[:2]
        text = "\n".join(lines)
        bbox = draw.multiline_textbbox((0, 0), text, font=subtitle_font, spacing=5, align="center")
        draw.multiline_text(((width - (bbox[2] - bbox[0])) / 2, 934), text, font=subtitle_font,
                            fill=WHITE, spacing=5, align="center")
    return image


def _cue_for(cues: list[dict[str, Any]], seconds: float) -> str:
    for cue in cues:
        if cue["start"] <= seconds < cue["end"] or (seconds == cue["end"] == cues[-1]["end"]):
            return cue["text"]
    return ""


def _probe_video(path: Path) -> dict[str, Any]:
    result = subprocess.run([str(FFPROBE), "-v", "error", "-show_streams", "-show_format",
                             "-of", "json", str(path)], capture_output=True, text=True, check=True)
    raw = json.loads(result.stdout)
    video = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in raw.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"duration": float(raw.get("format", {}).get("duration", 0)),
            "width": video.get("width"), "height": video.get("height"),
            "has_audio": bool(audio), "audio_duration": float(audio.get("duration", 0) or 0)}


def _save_representatives(out: Path, content: dict[str, Any], timeline: dict[str, Any], cues: list[dict[str, Any]]) -> list[Path]:
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    total = len(timeline["chapters"])
    for i, chapter in enumerate(content.get("chapters", [])):
        entry = timeline["chapters"][i]
        image = render_scene(chapter, .45, title=content.get("title", ""), as_of=content.get("as_of", ""),
                             index=i, total=total, subtitle=_cue_for(cues, entry["start"] + entry["duration"] * .45))
        path = frames_dir / f"chapter_{i:04d}.png"
        image.save(path, "PNG")
        paths.append(path)
    return paths


def _contact_sheet(paths: list[Path], output: Path) -> None:
    thumb_w, thumb_h = 480, 270
    cols = 2
    sheet = Image.new("RGB", (cols * thumb_w, math.ceil(len(paths) / cols) * thumb_h), BG)
    for i, path in enumerate(paths):
        with Image.open(path) as image:
            image.thumbnail((thumb_w, thumb_h))
            sheet.paste(image, ((i % cols) * thumb_w, (i // cols) * thumb_h))
    sheet.save(output, "PNG")


def render_video(out: Path, content: dict[str, Any], timeline: dict[str, Any], cues: list[dict[str, Any]],
                 output: Path) -> dict[str, Any]:
    audio = out / "audio.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(math.ceil(float(timeline["audio_duration"]) * FPS)))
    process = subprocess.Popen([str(FFMPEG), "-y", "-loglevel", "error", "-f", "rawvideo",
                                "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
                                "-i", "-", "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
                                str(output)], stdin=subprocess.PIPE)
    assert process.stdin is not None
    try:
        total = len(timeline["chapters"])
        for frame in range(frame_count):
            seconds = frame / FPS
            chapter_index = max((i for i, c in enumerate(timeline["chapters"])
                                 if c["start"] <= seconds), default=0)
            chapter_index = max(0, chapter_index)
            entry = timeline["chapters"][chapter_index]
            local = max(0.0, min(1.0, (seconds - entry["start"]) / max(entry["duration"], .001)))
            # Draw at 15 fps, duplicate each frame to produce a 30 fps stream.
            source_frame = frame // 2
            if frame % 2 == 0:
                image = render_scene(content["chapters"][chapter_index], local,
                                     title=content.get("title", ""), as_of=content.get("as_of", ""),
                                     index=chapter_index, total=total, subtitle=_cue_for(cues, seconds))
                cached = image.tobytes()
            process.stdin.write(cached)
    except BrokenPipeError as exc:
        raise RuntimeError("ffmpeg stopped while receiving frames") from exc
    finally:
        process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding the video")
    report = _probe_video(output)
    report.update({"output": str(output), "expected_duration": timeline["audio_duration"],
                   "fps": FPS, "verified": report["width"] == WIDTH and report["height"] == HEIGHT and report["has_audio"]})
    (out / "render_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["verified"]:
        raise RuntimeError(f"media verification failed: {report}")
    return report


def run(content_path: Path = CONTENT, out: Path = Path("D:/gpt-astra-explainer"), *, smoke: bool = False,
        render: bool = False) -> dict[str, Any]:
    content = json.loads(content_path.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    parts = _part_files(out)
    audio, durations = assemble_audio(out, parts)
    timeline = build_timeline(content, durations)
    cues = build_subtitle_cues(content, timeline)
    timeline["audio"] = str(audio)
    timeline["subtitle_cues"] = cues
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    write_srt(cues, out / "subtitles.srt")
    reps = _save_representatives(out, content, timeline, cues)
    result: dict[str, Any] = {"audio": str(audio), "srt": str(out / "subtitles.srt"),
                               "timeline": str(out / "timeline.json"), "frames": [str(p) for p in reps]}
    if smoke:
        sheet = out / "contact_sheet.png"
        _contact_sheet(reps, sheet)
        result["contact_sheet"] = str(sheet)
    if render:
        result["video"] = str(out / "gpt-astra-explainer.mp4")
        result["report"] = render_video(out, content, timeline, cues, Path(result["video"]))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, default=CONTENT)
    parser.add_argument("--out", type=Path, default=Path("D:/gpt-astra-explainer"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke", action="store_true", help="render representative frames and a contact sheet")
    mode.add_argument("--render", action="store_true", help="encode the full MP4")
    args = parser.parse_args(argv)
    try:
        result = run(args.content, args.out, smoke=args.smoke or not args.render, render=args.render)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
