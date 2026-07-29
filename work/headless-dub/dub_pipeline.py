from __future__ import annotations

import argparse
import asyncio
from difflib import SequenceMatcher
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ScheduledAudio:
    start: float
    end: float
    tempo: float


DEFAULT_SPEECH_TEMPO = 0.98
DEFAULT_MAX_TEMPO = 1.05
# GPT-SoVITS 合成参数（经 A/B 调参定稿：speed 0.92 略放慢更从容，
# temp 1.0 保持自然起伏——低于 0.9 会让发音含糊听不清）。
DEFAULT_TTS_SPEED_FACTOR = 0.92
DEFAULT_TTS_TEMPERATURE = 1.0
DEFAULT_TTS_TOP_K = 15
DEFAULT_TTS_REPETITION_PENALTY = 1.35
_OCR_OVERLAP_MIN_CHARS = 5
_OCR_ARTIFACTS = (
    "（无中",
    "(无中",
    "内卡CC",
    "中字CC",
    "中十CC",
    "中古CC",
    "史卡CC",
    "由卡CC",
    "有卡CC",
    "内十CC",
    "内七CC",
    "中大CC",
    "水十CC",
    "南大CC",
    "南卡CC",
    "内卡",
    "内十",
    "CC",
)


def group_cues(cues: list[Cue]) -> list[Cue]:
    if not cues:
        return []

    groups: list[Cue] = []
    current = cues[0]
    for cue in cues[1:]:
        gap = cue.start - current.end
        combined_duration = cue.end - current.start
        if gap <= 0.35 and combined_duration <= 12.0:
            current = Cue(current.start, cue.end, f"{current.text} {cue.text}".strip())
        else:
            groups.append(current)
            current = cue
    groups.append(current)
    return groups


def _normalized_ocr_text(text: str) -> str:
    return "".join(char for char in text if char.isalnum())


def _collapse_repeated_ocr_tokens(text: str) -> str:
    """Remove exact adjacent OCR repetitions while preserving normal spacing."""
    tokens = text.split()
    while True:
        best: tuple[int, int, int] | None = None
        for boundary in range(1, len(tokens)):
            for left_start in range(max(0, boundary - 8), boundary):
                left = _normalized_ocr_text("".join(tokens[left_start:boundary]))
                if len(left) < _OCR_OVERLAP_MIN_CHARS:
                    continue
                for right_end in range(boundary + 1, min(len(tokens), boundary + 8) + 1):
                    if left == _normalized_ocr_text("".join(tokens[boundary:right_end])):
                        candidate = (len(left), boundary, right_end)
                        if best is None or candidate[0] > best[0]:
                            best = candidate
        if best is None:
            break
        _, start, end = best
        del tokens[start:end]

    result: list[str] = []
    for token in tokens:
        normalized = _normalized_ocr_text(token)
        if result:
            previous = _normalized_ocr_text(result[-1])
            if (
                len(normalized) >= 8
                and len(previous) >= 8
                and SequenceMatcher(None, previous, normalized).ratio() >= 0.94
            ):
                continue
        result.append(token)
    return " ".join(result)


def _remove_ocr_artifacts(text: str) -> str:
    for artifact in _OCR_ARTIFACTS:
        text = text.replace(artifact, "")
    return re.sub(r"\s+", " ", text).lstrip(" \t\r\n，。！？；：、").rstrip()


def _suffix_prefix_overlap(previous: str, current: str) -> str:
    maximum = min(len(previous), len(current))
    for length in range(maximum, _OCR_OVERLAP_MIN_CHARS - 1, -1):
        if previous[-length:] == current[:length]:
            return current[:length]
    return ""


def _strip_normalized_prefix(text: str, normalized_prefix: str) -> str:
    consumed = 0
    for index, char in enumerate(text):
        if char.isalnum():
            consumed += 1
            if consumed == len(normalized_prefix):
                return text[index + 1:].lstrip(" \t\r\n，。！？；：、\"'“”《》（）【】")
    return text


def clean_ocr_cues(cues: list[Cue]) -> list[Cue]:
    """Remove high-confidence rolling-subtitle duplication before speech synthesis."""
    cleaned: list[Cue] = []
    for cue in cues:
        text = _remove_ocr_artifacts(_collapse_repeated_ocr_tokens(cue.text))
        normalized = _normalized_ocr_text(text)
        if not normalized:
            continue

        if cleaned:
            previous = cleaned[-1]
            overlap = _suffix_prefix_overlap(_normalized_ocr_text(previous.text), normalized)
            if overlap:
                text = _strip_normalized_prefix(text, overlap).strip()
                normalized = _normalized_ocr_text(text)
                if not normalized:
                    cleaned[-1] = Cue(previous.start, max(previous.end, cue.end), previous.text)
                    continue

        cleaned.append(Cue(cue.start, cue.end, text))
    return cleaned


def _cue_key(start: float) -> float:
    """Normalize timestamps used as stable review-file identifiers."""
    return round(float(start), 3)


def apply_review_overrides(cues: list[Cue], review_file: Path) -> list[Cue]:
    """Apply reviewed OCR corrections before synthesis.

    The review file stores text replacements keyed by cue start time, optional
    cue-end corrections, and optional restored cues. Every referenced source
    cue must exist so a stale review file fails loudly instead of silently
    applying edits to the wrong video version.
    """
    try:
        review = json.loads(review_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"review file does not exist: {review_file}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid review JSON: {review_file}") from exc
    if not isinstance(review, dict) or review.get("schema_version") != 1:
        raise ValueError("review file must use schema_version 1")

    def indexed_records(name: str, value_name: str) -> dict[float, object]:
        items = review.get(name, [])
        if not isinstance(items, list):
            raise ValueError(f"review field {name} must be a list")
        records: dict[float, object] = {}
        for item in items:
            if not isinstance(item, dict) or "start" not in item or value_name not in item:
                raise ValueError(f"invalid {name} entry")
            key = _cue_key(item["start"])
            if key in records:
                raise ValueError(f"duplicate {name} start: {key}")
            records[key] = item[value_name]
        return records

    overrides = indexed_records("overrides", "text")
    previous_ends = indexed_records("previous_ends", "end")
    seen: set[float] = set()
    reviewed: list[Cue] = []
    for cue in cues:
        key = _cue_key(cue.start)
        text = str(overrides.get(key, cue.text)).strip()
        end = float(previous_ends.get(key, cue.end))
        if key in overrides or key in previous_ends:
            seen.add(key)
        if not text or end <= cue.start:
            raise ValueError(f"review produced an invalid cue at {cue.start}")
        reviewed.append(Cue(cue.start, end, text))

    missing = (set(overrides) | set(previous_ends)) - seen
    if missing:
        raise ValueError(f"review references missing cue starts: {sorted(missing)}")

    restored_items = review.get("restored_cues", [])
    if not isinstance(restored_items, list):
        raise ValueError("review field restored_cues must be a list")
    for item in restored_items:
        if not isinstance(item, dict):
            raise ValueError("invalid restored_cues entry")
        try:
            cue = Cue(float(item["start"]), float(item["end"]), str(item["text"]).strip())
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid restored_cues entry") from exc
        if not cue.text or cue.end <= cue.start:
            raise ValueError("restored cue must have non-empty text and positive duration")
        reviewed.append(cue)

    reviewed.sort(key=lambda cue: (cue.start, cue.end, cue.text))
    for previous, current in zip(reviewed, reviewed[1:], strict=False):
        if current.start < previous.end - 0.001:
            raise ValueError(
                f"review creates overlapping cues at {previous.start} and {current.start}"
            )
    return reviewed


def tempo_for(actual_seconds: float, slot_seconds: float) -> float:
    if actual_seconds <= 0 or slot_seconds <= 0:
        raise ValueError("durations must be positive")

    if actual_seconds <= slot_seconds:
        return 1.0

    factor = round(actual_seconds / slot_seconds, 4)
    if factor > 1.25:
        raise ValueError(f"tempo {factor} is outside 0.80-1.25")
    return factor


def schedule_audio(
    cues: list[Cue],
    clip_durations: list[float],
    duration_seconds: float,
    preferred_tempo: float = DEFAULT_SPEECH_TEMPO,
    max_tempo: float = DEFAULT_MAX_TEMPO,
) -> list[ScheduledAudio]:
    if len(cues) != len(clip_durations):
        raise ValueError("cue and clip counts differ")
    if duration_seconds <= 0:
        raise ValueError("timeline duration must be positive")
    if not 0.5 <= preferred_tempo <= max_tempo <= 2.0:
        raise ValueError("tempo policy must satisfy 0.5 <= preferred <= max <= 2.0")

    scheduled: list[ScheduledAudio] = []
    previous_end = 0.0
    for index, (cue, clip_duration) in enumerate(
        zip(cues, clip_durations, strict=True)
    ):
        if clip_duration <= 0 or cue.end <= cue.start:
            raise ValueError("durations must be positive")
        if index and cue.start < cues[index - 1].start:
            raise ValueError("cues must be ordered")

        start = max(cue.start, previous_end)
        deadline = (
            cues[index + 1].start if index + 1 < len(cues) else duration_seconds
        )
        available = deadline - start
        if available <= 0:
            tempo = max_tempo
        else:
            tempo = min(max_tempo, max(preferred_tempo, clip_duration / available))
        end = start + clip_duration / tempo
        scheduled.append(ScheduledAudio(start=start, end=end, tempo=tempo))
        previous_end = end

    if scheduled and scheduled[-1].end > duration_seconds + 0.001:
        raise ValueError("scheduled audio exceeds timeline")
    return scheduled


def _srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def srt_text(cues: list[Cue]) -> str:
    blocks = [
        f"{index}\n{_srt_timestamp(cue.start)} --> {_srt_timestamp(cue.end)}\n{cue.text}"
        for index, cue in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def translate_with(
    cues: list[Cue], translator: Callable[[list[str]], list[str]]
) -> list[Cue]:
    translated = translator([cue.text for cue in cues])
    if len(translated) != len(cues):
        raise ValueError("translator returned a different number of texts")
    return [
        Cue(cue.start, cue.end, text.strip())
        for cue, text in zip(cues, translated, strict=True)
    ]


def stage_complete(state_path: Path, stage: str, fingerprint: str) -> bool:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return state.get(stage) == fingerprint


ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = Path(__file__).resolve().parent
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"
MODEL_CACHE = WORK_DIR / "model-cache"
APPROVED_REFERENCE_AUDIO = WORK_DIR / "voice-refs" / "cn-pro-ref.wav"
APPROVED_REFERENCE_TEXT = "欢迎来到积极心理学的课堂。在这里，我们将一起探索幸福的奥秘。"
DEFAULT_SUBTITLE_SOURCE = "ocr"
DEFAULT_TTS_ENGINE = "gpt-sovits"
DEFAULT_ARTIFACT_STEM = "episode"


def _command(arguments: list[str | Path]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(argument) for argument in arguments],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(str(argument) for argument in arguments)
            + "\n"
            + completed.stderr[-4_000:]
        )
    return completed


def _fingerprint_file(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fingerprint_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _mark_stage(state_path: Path, stage: str, fingerprint: str) -> None:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state[stage] = fingerprint
    _write_json(state_path, state)


def _probe_duration(path: Path) -> float:
    result = _command(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path,
        ]
    )
    return float(json.loads(result.stdout)["format"]["duration"])


_EXTERNAL_CLIP_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}


def normalize_external_audio(source: Path, output_wav: Path) -> None:
    """Convert an externally recorded track to the pipeline's WAV format."""
    if not source.is_file():
        raise ValueError(f"external audio file does not exist: {source}")

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_wav.with_suffix(".external.tmp.wav")
    try:
        _command(
            [
                FFMPEG,
                "-y",
                "-i",
                source,
                "-map",
                "0:a:0",
                "-vn",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                temporary_output,
            ]
        )
        temporary_output.replace(output_wav)
    finally:
        temporary_output.unlink(missing_ok=True)


def collect_external_clips(cues: list[Cue], clips_dir: Path) -> list[Path]:
    """Return one non-empty externally recorded clip for every subtitle cue."""
    if not clips_dir.is_dir():
        raise ValueError(f"external clips directory does not exist: {clips_dir}")

    clips: list[Path] = []
    for index in range(1, len(cues) + 1):
        stem = f"{index:04d}"
        matches = sorted(
            path
            for path in clips_dir.iterdir()
            if path.is_file()
            and path.stem == stem
            and path.suffix.lower() in _EXTERNAL_CLIP_SUFFIXES
        )
        if not matches:
            raise ValueError(
                f"missing external clip {stem} in {clips_dir}; "
                "expected a numbered audio file such as 0001.wav"
            )
        if len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            raise ValueError(f"multiple external clips match {stem}: {names}")
        clip = matches[0]
        if clip.stat().st_size == 0:
            raise ValueError(f"external clip is empty: {clip}")
        clips.append(clip)
    return clips


def _fingerprint_files(paths: list[Path]) -> str:
    return _fingerprint_text("\n".join(_fingerprint_file(path) for path in paths))


def _cues_to_json(cues: list[Cue]) -> list[dict[str, float | str]]:
    return [asdict(cue) for cue in cues]


def _cues_from_json(path: Path) -> list[Cue]:
    return [Cue(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _extract_source_segment(source: Path, duration_seconds: float, output: Path) -> None:
    _command(
        [
            FFMPEG,
            "-y",
            "-i",
            source,
            "-t",
            str(duration_seconds),
            "-c",
            "copy",
            output,
        ]
    )


def transcribe(video: Path, model_name: str) -> list[Cue]:
    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        download_root=str(MODEL_CACHE / "whisper"),
    )
    segments, _ = model.transcribe(
        str(video),
        language="en",
        beam_size=5,
        condition_on_previous_text=False,
        vad_filter=True,
        word_timestamps=True,
    )
    return [
        Cue(float(segment.start), float(segment.end), segment.text.strip())
        for segment in segments
        if segment.text.strip()
    ]


def _nllb_translator(texts: list[str]) -> list[str]:
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    cache_dir = MODEL_CACHE / "nllb"
    model_name = "facebook/nllb-200-distilled-600M"
    tokenizer = AutoTokenizer.from_pretrained(
        model_name, src_lang="eng_Latn", cache_dir=str(cache_dir)
    )
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name, cache_dir=str(cache_dir))
    target_token = tokenizer.convert_tokens_to_ids("zho_Hans")
    translations: list[str] = []
    for start in range(0, len(texts), 8):
        batch = texts[start : start + 8]
        inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            generated = model.generate(
                **inputs,
                forced_bos_token_id=target_token,
                max_new_tokens=256,
            )
        translations.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
    return translations


def translate(cues: list[Cue]) -> list[Cue]:
    return translate_with(cues, _nllb_translator)


async def _synthesize_one(text: str, voice: str, output: Path) -> None:
    import edge_tts

    communicator = edge_tts.Communicate(text, voice)
    await communicator.save(str(output))


def _synthesize_one_gptsovits(text: str, ref_audio: Path, ref_text: str,
                              output: Path, speed_factor: float = DEFAULT_TTS_SPEED_FACTOR,
                              temperature: float = DEFAULT_TTS_TEMPERATURE,
                              top_k: int = DEFAULT_TTS_TOP_K,
                              repetition_penalty: float = DEFAULT_TTS_REPETITION_PENALTY) -> None:
    """GPT-SoVITS Chinese synthesis with a Chinese reference recording."""
    import tts_gpt_sovits

    tts_gpt_sovits.synthesize_one(
        text=text, ref_audio=ref_audio, prompt_text=ref_text,
        output=output, text_lang="zh", prompt_lang="zh", output_format="mp3",
        speed_factor=speed_factor, temperature=temperature, top_k=top_k,
        repetition_penalty=repetition_penalty,
    )


def synthesize(cues: list[Cue], clips_dir: Path, voice: str,
               tts_engine: str = "edge", ref_audio: Path | None = None,
               ref_text: str = "",
               speed_factor: float = DEFAULT_TTS_SPEED_FACTOR,
               temperature: float = DEFAULT_TTS_TEMPERATURE,
               top_k: int = DEFAULT_TTS_TOP_K,
               repetition_penalty: float = DEFAULT_TTS_REPETITION_PENALTY) -> list[Path]:
    """合成每条 cue 的中文语音到 clips/{index:04d}.mp3。

    tts_engine: "edge"（edge-tts 通用预置音色）或 "gpt-sovits"（克隆 Tal 音色）。
    voice: edge 模式是预置音色名；gpt-sovits 模式仅参与 fingerprint（参考音频标识）。
    ref_audio/ref_text: gpt-sovits 模式必需（参考音频 + 对应转写文本）。
    speed_factor/temperature/top_k/repetition_penalty: 仅 gpt-sovits 生效，参与 fingerprint。
    """
    clips_dir.mkdir(parents=True, exist_ok=True)
    if tts_engine == "gpt-sovits" and ref_audio is None:
        raise ValueError("gpt-sovits 引擎需要 --ref-audio")
    total = len(cues)
    clips: list[Path] = []
    for index, cue in enumerate(cues, start=1):
        clip = clips_dir / f"{index:04d}.mp3"
        if not clip.exists() or clip.stat().st_size == 0:
            import time as _t
            t0 = _t.time()
            if tts_engine == "gpt-sovits":
                _synthesize_one_gptsovits(cue.text, ref_audio, ref_text, clip,
                                          speed_factor=speed_factor,
                                          temperature=temperature, top_k=top_k,
                                          repetition_penalty=repetition_penalty)
            else:
                asyncio.run(_synthesize_one(cue.text, voice, clip))
            dt = _t.time() - t0
            print(f"  [合成] {index}/{total} 完成 ({dt:.1f}s) \"{cue.text[:24]}\"",
                  file=sys.stderr, flush=True)
        else:
            print(f"  [合成] {index}/{total} 跳过(已存在)", file=sys.stderr, flush=True)
        clips.append(clip)
    return clips


def _tempo_adjusted_clip(source: Path, tempo: float, output: Path) -> None:
    _command(
        [
            FFMPEG,
            "-y",
            "-i",
            source,
            "-filter:a",
            f"atempo={tempo}",
            "-ar",
            "48000",
            "-ac",
            "1",
            output,
        ]
    )


def assemble_audio(
    cues: list[Cue],
    clips: list[Path],
    duration_seconds: float,
    output_wav: Path,
    preferred_tempo: float = DEFAULT_SPEECH_TEMPO,
    max_tempo: float = DEFAULT_MAX_TEMPO,
) -> None:
    if len(cues) != len(clips):
        raise ValueError("cue and clip counts differ")

    from pydub import AudioSegment

    AudioSegment.converter = str(FFMPEG)
    timeline = (
        AudioSegment.silent(duration=round(duration_seconds * 1000), frame_rate=48000)
        .set_channels(1)
        .set_sample_width(2)
    )
    scheduled = schedule_audio(
        cues,
        [_probe_duration(clip) for clip in clips],
        duration_seconds,
        preferred_tempo=preferred_tempo,
        max_tempo=max_tempo,
    )
    with tempfile.TemporaryDirectory(prefix="dub-tempo-") as temporary_directory:
        temporary_directory_path = Path(temporary_directory)
        previous_end_ms = 0
        for index, (clip, placement) in enumerate(
            zip(clips, scheduled, strict=True), start=1
        ):
            adjusted = temporary_directory_path / f"{index:04d}.wav"
            _tempo_adjusted_clip(clip, placement.tempo, adjusted)
            clip_audio = AudioSegment.from_file(adjusted).set_frame_rate(48000).set_channels(1)
            position_ms = max(round(placement.start * 1000), previous_end_ms)
            previous_end_ms = position_ms + len(clip_audio)
            if previous_end_ms > len(timeline):
                raise ValueError("scheduled audio exceeds timeline")
            timeline = timeline.overlay(clip_audio, position=position_ms)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    timeline.export(str(output_wav), format="wav", parameters=["-ar", "48000", "-ac", "1"])


def mux(
    source: Path,
    chinese_wav: Path,
    chinese_srt: Path,
    english_srt: Path,
    output_mp4: Path,
) -> None:
    """Create the approved two-audio, bilingual-subtitle MP4 layout."""
    _command(
        [
            FFMPEG,
            "-y",
            "-i",
            source,
            "-i",
            chinese_wav,
            "-i",
            chinese_srt,
            "-i",
            english_srt,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "0:a:0?",
            "-map",
            "2:0",
            "-map",
            "3:0",
            "-c:v",
            "copy",
            "-c:a:0",
            "aac",
            "-b:a:0",
            "160k",
            "-c:a:1",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:a:0",
            "title=Mandarin dub",
            "-metadata:s:a:0",
            "language=zho",
            "-metadata:s:a:1",
            "title=Original English",
            "-metadata:s:a:1",
            "language=eng",
            "-metadata:s:s:0",
            "title=Chinese subtitles",
            "-metadata:s:s:0",
            "language=zho",
            "-metadata:s:s:1",
            "title=English subtitles",
            "-metadata:s:s:1",
            "language=eng",
            "-disposition:a:0",
            "default",
            "-disposition:a:1",
            "0",
            "-disposition:s:0",
            "default",
            "-disposition:s:1",
            "0",
            output_mp4,
        ]
    )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _delivery_probe(video: Path) -> dict[str, object]:
    result = _command(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            video,
        ]
    )
    return json.loads(result.stdout)


def publish_delivery(
    source_segment: Path,
    video: Path,
    chinese_wav: Path,
    chinese_srt: Path,
    english_srt: Path,
    chinese_json: Path,
    delivery_dir: Path,
    artifact_stem: str,
    speech_tempo: float,
    max_tempo: float,
    subtitle_source: str,
    ocr_model: str,
    tts_engine: str,
    ref_audio: Path | None,
    review_file: Path | None,
) -> Path:
    """Atomically create a self-contained, checksummed delivery package."""
    required = (source_segment, video, chinese_wav, chinese_srt, english_srt, chinese_json)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError("cannot publish missing artifacts: " + ", ".join(missing))
    if review_file is not None and not review_file.is_file():
        raise ValueError(f"review file does not exist: {review_file}")
    if delivery_dir.exists():
        raise ValueError(f"delivery directory already exists: {delivery_dir}")

    delivery_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{delivery_dir.name}.staging-", dir=delivery_dir.parent)
    )
    video_name = f"{artifact_stem}.dual-audio.bilingual-subtitles.mp4"
    chinese_audio_name = f"{artifact_stem}.zh-CN.dub.m4a"
    english_audio_name = f"{artifact_stem}.en.original.m4a"
    try:
        video_dir = staging_dir / "video"
        audio_dir = staging_dir / "audio"
        subtitles_dir = staging_dir / "subtitles"
        metadata_dir = staging_dir / "metadata"
        for directory in (video_dir, audio_dir, subtitles_dir, metadata_dir):
            directory.mkdir(parents=True, exist_ok=True)

        delivery_video = video_dir / video_name
        delivery_chinese_audio = audio_dir / chinese_audio_name
        delivery_english_audio = audio_dir / english_audio_name
        shutil.copy2(video, delivery_video)
        shutil.copy2(chinese_srt, subtitles_dir / f"{artifact_stem}.zh-CN.srt")
        shutil.copy2(english_srt, subtitles_dir / f"{artifact_stem}.en.srt")
        shutil.copy2(chinese_json, metadata_dir / f"{artifact_stem}.reviewed-cues.json")
        if review_file is not None:
            shutil.copy2(review_file, metadata_dir / f"{artifact_stem}.review-overrides.json")

        _command(
            [
                FFMPEG,
                "-y",
                "-i",
                chinese_wav,
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                delivery_chinese_audio,
            ]
        )
        _command(
            [
                FFMPEG,
                "-y",
                "-i",
                source_segment,
                "-map",
                "0:a:0",
                "-vn",
                "-c:a",
                "copy",
                delivery_english_audio,
            ]
        )

        probe = _delivery_probe(delivery_video)
        _write_json(metadata_dir / "ffprobe.json", probe)
        streams = probe.get("streams", [])
        video_stream = next(
            (
                stream
                for stream in streams
                if isinstance(stream, dict) and stream.get("codec_type") == "video"
            ),
            {},
        )
        episode_match = re.fullmatch(r"episode-(\d+)", artifact_stem)
        manifest = {
            "schema_version": 1,
            "title": f"Harvard Positive Psychology - {artifact_stem}",
            "episode": int(episode_match.group(1)) if episode_match else artifact_stem,
            "source_duration_seconds": _probe_duration(source_segment),
            "video": {
                "path": f"video/{video_name}",
                "video_codec": video_stream.get("codec_name", "unknown"),
                "audio_tracks": [
                    {"language": "zho", "title": "Mandarin dub", "default": True},
                    {"language": "eng", "title": "Original English", "default": False},
                ],
                "subtitle_tracks": [
                    {"language": "zho", "title": "Chinese subtitles", "default": True},
                    {"language": "eng", "title": "English subtitles", "default": False},
                ],
            },
            "audio": [
                f"audio/{chinese_audio_name}",
                f"audio/{english_audio_name}",
            ],
            "subtitles": [
                f"subtitles/{artifact_stem}.zh-CN.srt",
                f"subtitles/{artifact_stem}.en.srt",
            ],
            "revision": {
                "subtitle_source": subtitle_source,
                "ocr_model": ocr_model if subtitle_source == "ocr" else None,
                "tts_engine": tts_engine,
                "reference_audio": ref_audio.name if ref_audio else None,
                "speech_tempo": speech_tempo,
                "max_tempo": max_tempo,
                "chinese_subtitle_cues": len(_cues_from_json(chinese_json)),
                "review_overlay": review_file.name if review_file else None,
            },
        }
        _write_json(metadata_dir / "manifest.json", manifest)
        _write_json(
            metadata_dir / "workflow.json",
            {
                "schema_version": 1,
                "subtitle_source": subtitle_source,
                "ocr_model": ocr_model if subtitle_source == "ocr" else None,
                "tts_engine": tts_engine,
                "reference_audio": ref_audio.name if ref_audio else None,
                "speech_tempo": speech_tempo,
                "max_tempo": max_tempo,
            },
        )

        checksum_lines: list[str] = []
        for asset in sorted(
            (path for path in staging_dir.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(staging_dir).as_posix(),
        ):
            relative = asset.relative_to(staging_dir).as_posix()
            checksum_lines.append(f"{_sha256_file(asset)}  {relative}")
        _write_text(metadata_dir / "SHA256SUMS.txt", "\n".join(checksum_lines) + "\n")

        staging_dir.replace(delivery_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return delivery_dir / "video" / video_name


def run_pilot(
    source: Path,
    duration_seconds: float,
    output_dir: Path,
    transcription_model: str,
    voice: str,
    subtitle_source: str = DEFAULT_SUBTITLE_SOURCE,
    ocr_model: str = "rapidocr",
    tts_engine: str = DEFAULT_TTS_ENGINE,
    ref_audio: Path | None = APPROVED_REFERENCE_AUDIO,
    ref_text: str = APPROVED_REFERENCE_TEXT,
    speech_tempo: float = DEFAULT_SPEECH_TEMPO,
    max_tempo: float = DEFAULT_MAX_TEMPO,
    review_file: Path | None = None,
    external_audio: Path | None = None,
    external_clips_dir: Path | None = None,
    artifact_stem: str = DEFAULT_ARTIFACT_STEM,
    stage: str = "all",
    delivery_dir: Path | None = None,
    speed_factor: float = DEFAULT_TTS_SPEED_FACTOR,
    temperature: float = DEFAULT_TTS_TEMPERATURE,
    top_k: int = DEFAULT_TTS_TOP_K,
    repetition_penalty: float = DEFAULT_TTS_REPETITION_PENALTY,
    skip_review: bool = False,
) -> Path:
    if external_audio is not None and external_clips_dir is not None:
        raise ValueError("--external-audio and --external-clips-dir cannot be used together")
    if external_audio is not None and not external_audio.is_file():
        raise ValueError(f"external audio file does not exist: {external_audio}")
    if stage not in {"subtitles", "all"}:
        raise ValueError("stage must be subtitles or all")
    if review_file is not None and subtitle_source != "ocr":
        raise ValueError("--review-file requires --subtitle-source ocr")
    if stage == "all" and subtitle_source == "ocr" and review_file is None and not skip_review:
        raise ValueError("final OCR delivery requires --review-file (或加 --skip-review 跳过人工复核)")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", artifact_stem):
        raise ValueError("artifact_stem may contain only letters, digits, dots, underscores, and hyphens")
    if delivery_dir is not None and stage != "all":
        raise ValueError("--delivery-dir requires --stage all")

    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "state.json"
    source_fingerprint = _fingerprint_file(source)
    segment_fingerprint = _fingerprint_text(f"{source_fingerprint}:{duration_seconds}")
    segment = output_dir / f"{artifact_stem}.source.mp4"
    if not (segment.exists() and stage_complete(state_path, "segment", segment_fingerprint)):
        _extract_source_segment(source, duration_seconds, segment)
        _mark_stage(state_path, "segment", segment_fingerprint)

    english_json = output_dir / f"{artifact_stem}.en.json"
    english_srt = output_dir / f"{artifact_stem}.en.srt"
    transcript_fingerprint = _fingerprint_text(
        f"{segment_fingerprint}:{transcription_model}:en"
    )
    if not (
        english_json.exists()
        and english_srt.exists()
        and stage_complete(state_path, "transcript", transcript_fingerprint)
    ):
        english_cues = group_cues(transcribe(segment, transcription_model))
        _write_json(english_json, _cues_to_json(english_cues))
        _write_text(english_srt, srt_text(english_cues))
        _mark_stage(state_path, "transcript", transcript_fingerprint)
    english_cues = _cues_from_json(english_json)

    chinese_json = output_dir / f"{artifact_stem}.zh-CN.json"
    chinese_srt = output_dir / f"{artifact_stem}.zh-CN.srt"
    if subtitle_source == "ocr":
        # OCR 路径：从画面硬字幕提取中文，质量远优于 NLLB 机翻。
        # fingerprint 依赖 segment（视频画面）而非 english_json——OCR 读画面不读英文转写。
        import subtitle_ocr

        review_fingerprint = _fingerprint_file(review_file) if review_file else "none"
        translation_fingerprint = _fingerprint_text(
            f"{segment_fingerprint}:ocr:{ocr_model}:clean-v3:{review_fingerprint}"
        )
        if not (
            chinese_json.exists()
            and chinese_srt.exists()
            and stage_complete(state_path, "translation", translation_fingerprint)
        ):
            # 用 Whisper 英文 cue 时间戳作为字幕定位锚点（已验证中点落在字幕稳定期）
            anchor_cues = [
                subtitle_ocr.Cue(c.start, c.end, c.text) for c in english_cues
            ]
            _, ocr_json_path = subtitle_ocr.run(
                segment, output_dir, model=ocr_model, anchor_cues=anchor_cues
            )
            # subtitle_ocr 输出的 cue 格式与 dub_pipeline 兼容（start/end/text）
            ocr_cues = [
                Cue(item["start"], item["end"], item["text"])
                for item in json.loads(ocr_json_path.read_text(encoding="utf-8"))
            ]
            ocr_cues = clean_ocr_cues(ocr_cues)
            if review_file is not None:
                ocr_cues = apply_review_overrides(ocr_cues, review_file)
            _write_json(chinese_json, _cues_to_json(ocr_cues))
            _write_text(chinese_srt, srt_text(ocr_cues))
            _mark_stage(state_path, "translation", translation_fingerprint)
    else:
        translation_fingerprint = _fingerprint_text(
            f"{_fingerprint_file(english_json)}:nllb-200-distilled-600M:eng_Latn:zho_Hans"
        )
        if not (
            chinese_json.exists()
            and chinese_srt.exists()
            and stage_complete(state_path, "translation", translation_fingerprint)
        ):
            chinese_cues = translate(english_cues)
            _write_json(chinese_json, _cues_to_json(chinese_cues))
            _write_text(chinese_srt, srt_text(chinese_cues))
            _mark_stage(state_path, "translation", translation_fingerprint)
    chinese_cues = _cues_from_json(chinese_json)
    if stage == "subtitles":
        return chinese_srt

    chinese_wav = output_dir / f"{artifact_stem}.zh-CN.wav"
    if external_audio is not None:
        audio_fingerprint = _fingerprint_text(
            f"external-audio-v1:{_fingerprint_file(external_audio)}:"
            "pcm_s16le:48000:mono"
        )
        if not (
            chinese_wav.exists()
            and stage_complete(state_path, "audio", audio_fingerprint)
        ):
            normalize_external_audio(external_audio, chinese_wav)
            _mark_stage(state_path, "audio", audio_fingerprint)
    else:
        if external_clips_dir is not None:
            clips = collect_external_clips(chinese_cues, external_clips_dir)
            synthesis_fingerprint = _fingerprint_text(
                f"external-clips-v1:{_fingerprint_file(chinese_json)}:"
                f"{_fingerprint_files(clips)}"
            )
        else:
            reference_fingerprint = _fingerprint_file(ref_audio) if ref_audio else ""
            synthesis_fingerprint = _fingerprint_text(
                f"{_fingerprint_file(chinese_json)}:{voice}:{tts_engine}:"
                f"{reference_fingerprint}:{ref_text}:prompt-lang-zh:"
                f"sp{speed_factor}:tp{temperature}:tk{top_k}:rp{repetition_penalty}:v3"
            )
            # A review can change cue text while keeping its number and index.
            # Cache clips by the full synthesis inputs so stale numbered clips
            # can never be reused after a subtitle or reference change.
            clips_dir = output_dir / "clips" / synthesis_fingerprint
            clips = synthesize(
                chinese_cues,
                clips_dir,
                voice,
                tts_engine=tts_engine,
                ref_audio=ref_audio,
                ref_text=ref_text,
                speed_factor=speed_factor,
                temperature=temperature,
                top_k=top_k,
                repetition_penalty=repetition_penalty,
            )
        _mark_stage(state_path, "synthesis", synthesis_fingerprint)

        segment_duration = _probe_duration(segment)
        audio_fingerprint = _fingerprint_text(
            f"{synthesis_fingerprint}:{segment_duration}:"
            f"schedule-v2:{speech_tempo:.3f}:{max_tempo:.3f}"
        )
        if not (
            chinese_wav.exists()
            and stage_complete(state_path, "audio", audio_fingerprint)
        ):
            assemble_audio(
                chinese_cues,
                clips,
                segment_duration,
                chinese_wav,
                preferred_tempo=speech_tempo,
                max_tempo=max_tempo,
            )
            _mark_stage(state_path, "audio", audio_fingerprint)

    output_mp4 = output_dir / f"{artifact_stem}.dual-audio.bilingual-subtitles.mp4"
    mux_fingerprint = _fingerprint_text(
        "mux-v2:"
        f"{_fingerprint_file(segment)}:{_fingerprint_file(chinese_wav)}:"
        f"{_fingerprint_file(chinese_srt)}:{_fingerprint_file(english_srt)}"
    )
    if not (output_mp4.exists() and stage_complete(state_path, "mux", mux_fingerprint)):
        mux(segment, chinese_wav, chinese_srt, english_srt, output_mp4)
        _mark_stage(state_path, "mux", mux_fingerprint)
    if delivery_dir is not None:
        return publish_delivery(
            segment,
            output_mp4,
            chinese_wav,
            chinese_srt,
            english_srt,
            chinese_json,
            delivery_dir,
            artifact_stem,
            speech_tempo,
            max_tempo,
            subtitle_source,
            ocr_model,
            tts_engine,
            ref_audio,
            review_file,
        )
    return output_mp4


def main() -> None:
    parser = argparse.ArgumentParser(description="Headless English-to-Mandarin dubbing pilot")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument(
        "--full",
        action="store_true",
        help="处理完整源视频；覆盖 --duration",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--transcription-model", default="large-v3-turbo")
    parser.add_argument(
        "--voice",
        default=APPROVED_REFERENCE_AUDIO.stem,
        help="语音配置标识；默认使用已批准的中文参考音色",
    )
    external_input = parser.add_mutually_exclusive_group()
    external_input.add_argument(
        "--external-audio",
        type=Path,
        help="Full externally recorded dub track; bypasses TTS and clip assembly.",
    )
    external_input.add_argument(
        "--external-clips-dir",
        "--external-clips",
        dest="external_clips_dir",
        type=Path,
        help="Directory of externally recorded 0001.ext, 0002.ext, ... clips.",
    )
    parser.add_argument(
        "--subtitle-source",
        choices=["nllb", "ocr"],
        default=DEFAULT_SUBTITLE_SOURCE,
        help="中文字幕来源：ocr=从画面硬字幕提取（默认、正式流程），nllb=旧机器翻译路径",
    )
    parser.add_argument(
        "--ocr-model",
        default="rapidocr",
        help="字幕 OCR 引擎名（仅 --subtitle-source ocr 时生效，默认 rapidocr 轻量文字识别）",
    )
    parser.add_argument(
        "--tts-engine",
        choices=["edge", "gpt-sovits"],
        default=DEFAULT_TTS_ENGINE,
        help="语音合成引擎：gpt-sovits=已批准的参考音色（默认），"
             "edge=edge-tts 旧预置音色路径",
    )
    parser.add_argument(
        "--ref-audio",
        type=Path,
        default=APPROVED_REFERENCE_AUDIO,
        help="GPT-SoVITS 参考音频 wav（默认：已批准的中文参考音频）",
    )
    parser.add_argument(
        "--ref-text",
        default=APPROVED_REFERENCE_TEXT,
        help="参考音频对应的转写文本（默认：已批准参考音频的文本）",
    )
    parser.add_argument(
        "--speech-tempo",
        type=float,
        default=DEFAULT_SPEECH_TEMPO,
        help="优先语速；小于 1.0 时略慢于原始 GPT-SoVITS 音频（默认 0.98）",
    )
    parser.add_argument(
        "--max-tempo",
        type=float,
        default=DEFAULT_MAX_TEMPO,
        help="为保持同步允许的最高加速倍数（默认 1.05）",
    )
    parser.add_argument(
        "--review-file",
        type=Path,
        default=None,
        help="OCR 人工复核 JSON；会在去重后、合成前应用文本和时间轴修正",
    )
    parser.add_argument(
        "--skip-review",
        action="store_true",
        help="跳过 OCR 人工复核强制门（OCR 原始结果直接进合成，质量自负）",
    )
    parser.add_argument(
        "--artifact-stem",
        default=DEFAULT_ARTIFACT_STEM,
        help="当前输出目录内的产物前缀；全集使用 episode-01 等稳定名称",
    )
    parser.add_argument(
        "--stage",
        choices=["subtitles", "all"],
        default="all",
        help="subtitles=只生成可复核字幕；all=字幕、配音和封装（默认）",
    )
    parser.add_argument(
        "--delivery-dir",
        type=Path,
        default=None,
        help="验证后发布的最终交付目录；会生成视频、双音轨、双字幕、元数据和 SHA256SUMS",
    )
    parser.add_argument(
        "--tts-speed",
        type=float,
        default=DEFAULT_TTS_SPEED_FACTOR,
        help=f"GPT-SoVITS 语速（默认 {DEFAULT_TTS_SPEED_FACTOR}；调参定稿值，略放慢更从容）",
    )
    parser.add_argument(
        "--tts-temperature",
        type=float,
        default=DEFAULT_TTS_TEMPERATURE,
        help=f"GPT-SoVITS 采样温度（默认 {DEFAULT_TTS_TEMPERATURE}；低于 0.9 会让发音含糊听不清）",
    )
    parser.add_argument(
        "--tts-top-k",
        type=int,
        default=DEFAULT_TTS_TOP_K,
        help=f"GPT-SoVITS top_k（默认 {DEFAULT_TTS_TOP_K}）",
    )
    parser.add_argument(
        "--tts-repetition-penalty",
        type=float,
        default=DEFAULT_TTS_REPETITION_PENALTY,
        help=f"GPT-SoVITS 重复抑制（默认 {DEFAULT_TTS_REPETITION_PENALTY}）",
    )
    args = parser.parse_args()
    duration_seconds = _probe_duration(args.input) if args.full else args.duration
    output = run_pilot(
        args.input,
        duration_seconds,
        args.output,
        args.transcription_model,
        args.voice,
        subtitle_source=args.subtitle_source,
        ocr_model=args.ocr_model,
        tts_engine=args.tts_engine,
        ref_audio=args.ref_audio,
        ref_text=args.ref_text,
        speech_tempo=args.speech_tempo,
        max_tempo=args.max_tempo,
        review_file=args.review_file,
        external_audio=args.external_audio,
        external_clips_dir=args.external_clips_dir,
        artifact_stem=args.artifact_stem,
        stage=args.stage,
        delivery_dir=args.delivery_dir,
        speed_factor=args.tts_speed,
        temperature=args.tts_temperature,
        top_k=args.tts_top_k,
        repetition_penalty=args.tts_repetition_penalty,
        skip_review=args.skip_review,
    )
    print(output)


if __name__ == "__main__":
    main()
