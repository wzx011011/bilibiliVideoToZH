"""Generate natural Chinese narration and its exact sentence timing sidecar.

Run through generate-preview-audio.ps1 so the project uses its configured Python.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import edge_tts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FFMPEG = PROJECT_ROOT.parent / "video-tools" / "ffmpeg.exe"
FFPROBE = PROJECT_ROOT.parent / "video-tools" / "ffprobe.exe"


def narration_paragraphs(path: Path, strip_leading_directive: bool) -> list[str]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if strip_leading_directive and len(lines) > 1 and not lines[1].strip():
        lines = lines[2:]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append("".join(current))
            current = []
    if current:
        paragraphs.append("".join(current))
    return paragraphs


def split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.findall(r"[^。！？]+[。！？]?", text) if sentence.strip()]


async def synthesize(text: str, output: Path, voice: str, rate: str) -> list[dict[str, object]]:
    boundaries: list[dict[str, object]] = []
    communicator = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        boundary="SentenceBoundary",
    )
    with output.open("wb") as audio:
        async for event in communicator.stream():
            if event["type"] == "audio":
                audio.write(event["data"])
            elif event["type"] == "SentenceBoundary":
                boundaries.append(event)
    return boundaries


def media_duration(path: Path) -> float:
    completed = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(completed.stdout.strip())


def normalize(input_file: Path, output_file: Path) -> None:
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_file),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "160k",
            str(output_file),
        ],
        check=True,
    )


def concatenate(input_files: list[Path], output_file: Path) -> None:
    playlist = output_file.with_suffix(".concat.txt")
    playlist.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in input_files),
        encoding="utf-8",
    )
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(playlist),
            "-codec:a",
            "copy",
            str(output_file),
        ],
        check=True,
    )


def event_intervals(boundaries: list[dict[str, object]], audio_duration: float) -> list[float]:
    if not boundaries:
        raise RuntimeError("The TTS service returned no sentence boundaries.")
    starts = [float(event["offset"]) / 10_000_000 for event in boundaries]
    starts[0] = 0.0
    intervals = [round(starts[index + 1] - starts[index], 6) for index in range(len(starts) - 1)]
    intervals.append(round(audio_duration - starts[-1], 6))
    if any(interval <= 0 for interval in intervals):
        raise RuntimeError(f"Invalid sentence intervals: {intervals}")
    return intervals


def compact(text: str) -> str:
    return re.sub(r"[\s“”\"']+", "", text)


def paragraph_intervals(
    paragraphs: list[str], boundaries: list[dict[str, object]], audio_duration: float
) -> list[float]:
    starts = [float(event["offset"]) / 10_000_000 for event in boundaries]
    starts[0] = 0.0
    intervals: list[float] = []
    boundary_index = 0

    for paragraph in paragraphs:
        expected = compact(paragraph)
        consumed = ""
        start = starts[boundary_index] if boundary_index < len(starts) else audio_duration

        while boundary_index < len(boundaries) and len(consumed) < len(expected):
            consumed += compact(str(boundaries[boundary_index]["text"]))
            boundary_index += 1

        if consumed != expected:
            raise RuntimeError(
                f"Could not align paragraph {len(intervals) + 1}: expected {expected!r}, got {consumed!r}."
            )

        end = starts[boundary_index] if boundary_index < len(starts) else audio_duration
        intervals.append(round(end - start, 6))

    if boundary_index != len(boundaries):
        raise RuntimeError("The final paragraph did not consume all sentence boundaries.")
    return intervals


def subtitle_cues(boundaries: list[dict[str, object]], audio_duration: float) -> list[dict[str, float | str]]:
    starts = [float(event["offset"]) / 10_000_000 for event in boundaries]
    starts[0] = 0.0
    cues: list[dict[str, float | str]] = []
    first_index = 0
    text = ""

    for index, event in enumerate(boundaries):
        text += str(event["text"])
        if text.rstrip().endswith(("。", "！", "？")):
            next_start = starts[index + 1] if index + 1 < len(starts) else audio_duration
            cues.append(
                {
                    "text": text,
                    "from": round(starts[first_index], 6),
                    "duration": round(next_start - starts[first_index], 6),
                }
            )
            first_index = index + 1
            text = ""

    if text:
        raise RuntimeError(f"The final subtitle cue has no terminal punctuation: {text!r}")
    return cues


def scale_timing(value: float, factor: float) -> float:
    return round(value * factor, 6)


async def synthesize_paragraphs(
    paragraphs: list[str], directory: Path, voice: str, rate: str
) -> list[tuple[Path, list[dict[str, object]], float]]:
    chunks: list[tuple[Path, list[dict[str, object]], float]] = []
    for index, paragraph in enumerate(paragraphs):
        output = directory / f"paragraph-{index:02d}.mp3"
        boundaries = await synthesize(paragraph, output, voice, rate)
        chunks.append((output, boundaries, media_duration(output)))
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", type=int, default=1)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strip-leading-directive", action="store_true")
    parser.add_argument("--split-paragraphs", action="store_true")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--rate", default="-4%")
    args = parser.parse_args()

    source = args.source or PROJECT_ROOT / "narration" / f"episode-{args.episode:02d}.txt"
    output = args.output or PROJECT_ROOT / "public" / "audio" / f"episode-{args.episode:02d}.neural.mp3"
    source = source if source.is_absolute() else PROJECT_ROOT / source
    output = output if output.is_absolute() else PROJECT_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar = output.with_suffix(".timing.json")

    paragraphs = narration_paragraphs(source, args.strip_leading_directive)
    text = "".join(paragraphs)
    if not split_sentences(text):
        raise RuntimeError(f"No sentences found in {source}")

    with tempfile.TemporaryDirectory(prefix="transformer-neural-") as directory:
        temp_dir = Path(directory)
        normalized_audio = temp_dir / "narration.normalized.mp3"

        if args.split_paragraphs:
            chunks = asyncio.run(synthesize_paragraphs(paragraphs, temp_dir, args.voice, args.rate))
            joined_audio = temp_dir / "narration.joined.mp3"
            concatenate([audio for audio, _, _ in chunks], joined_audio)
            normalize(joined_audio, normalized_audio)

            raw_duration = sum(chunk_duration for _, _, chunk_duration in chunks)
            duration = media_duration(normalized_audio)
            factor = duration / raw_duration
            offset = 0.0
            intervals: list[float] = []
            subtitle_texts: list[str] = []
            cues: list[dict[str, float | str]] = []
            paragraph_durations: list[float] = []

            for _, boundaries, chunk_duration in chunks:
                intervals.extend(scale_timing(value, factor) for value in event_intervals(boundaries, chunk_duration))
                subtitle_texts.extend(str(event["text"]) for event in boundaries)
                for cue in subtitle_cues(boundaries, chunk_duration):
                    cues.append(
                        {
                            "text": cue["text"],
                            "from": scale_timing(offset + float(cue["from"]), factor),
                            "duration": scale_timing(float(cue["duration"]), factor),
                        }
                    )
                paragraph_durations.append(scale_timing(chunk_duration, factor))
                offset += chunk_duration
        else:
            raw_audio = temp_dir / "narration.raw.mp3"
            boundaries = asyncio.run(synthesize(text, raw_audio, args.voice, args.rate))
            normalize(raw_audio, normalized_audio)
            duration = media_duration(normalized_audio)
            intervals = event_intervals(boundaries, duration)
            subtitle_texts = [str(event["text"]) for event in boundaries]
            cues = subtitle_cues(boundaries, duration)
            paragraph_durations = paragraph_intervals(paragraphs, boundaries, duration)

        payload = {
            "voice": args.voice,
            "rate": args.rate,
            "duration": round(duration, 6),
            "sentenceDurations": intervals,
            "subtitleTexts": subtitle_texts,
            "subtitleCues": cues,
            "paragraphDurations": paragraph_durations,
        }
        pending_output = output.with_suffix(output.suffix + ".pending")
        shutil.copyfile(normalized_audio, pending_output)
        pending_output.replace(output)

    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
