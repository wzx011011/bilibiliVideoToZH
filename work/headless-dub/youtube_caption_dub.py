"""Create a Mandarin delivery from downloaded YouTube caption tracks.

YouTube auto captions are emitted as rolling, cumulative text.  This utility
turns each visible-text update into the newly spoken fragment, then delegates
audio scheduling, muxing, and delivery checksums to ``dub_pipeline``.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re

import dub_pipeline


_TIMESTAMP = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)
_TAG = re.compile(r"<[^>]+>")
_NON_SPEECH = re.compile(r"^[\[(（].{0,30}[\])）]$")
_TRIMMABLE = " \t\r\n，。！？；：、,.!?;:"


def _seconds(timestamp: str) -> float:
    hours, minutes, seconds = timestamp.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _caption_text(lines: list[str]) -> str:
    text = html.unescape(_TAG.sub("", " ".join(lines)))
    # Auto-translated tracks occasionally contain invisible web-format markers
    # that the local GPT-SoVITS Windows endpoint cannot encode.
    text = text.replace("\ufeff", "").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_srt(path: Path) -> list[dub_pipeline.Cue]:
    """Read the standard SRT subset produced by yt-dlp."""
    cues: list[dub_pipeline.Cue] = []
    active_match: re.Match[str] | None = None
    active_lines: list[str] = []

    def flush() -> None:
        if active_match is None:
            return
        cues.append(
            dub_pipeline.Cue(
                _seconds(active_match.group("start")),
                _seconds(active_match.group("end")),
                _caption_text(active_lines),
            )
        )

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        match = _TIMESTAMP.match(raw_line.strip())
        if match is not None:
            flush()
            active_match = match
            active_lines = []
        elif active_match is not None and raw_line.strip() and not raw_line.strip().isdigit():
            active_lines.append(raw_line.strip())
    flush()
    return cues


def _compact(text: str) -> str:
    return "".join(character for character in text if not character.isspace())


def _strip_compact_prefix(text: str, prefix: str) -> str:
    """Remove a whitespace-insensitive known prefix from the original text."""
    if not prefix:
        return text
    consumed = ""
    for index, character in enumerate(text):
        if not character.isspace():
            consumed += character
        if consumed == prefix:
            return text[index + 1 :].lstrip(_TRIMMABLE)
    return text


def _newly_visible(previous: str, current: str) -> str:
    """Return the newly appended part of a rolling caption update."""
    prior = _compact(previous)
    visible = _compact(current)
    if not prior or not visible:
        return current
    if visible.startswith(prior):
        return _strip_compact_prefix(current, prior)
    maximum = min(len(prior), len(visible))
    for length in range(maximum, 2, -1):
        if prior[-length:] == visible[:length]:
            return _strip_compact_prefix(current, visible[:length])
    return current


def unfold_rolling_captions(cues: list[dub_pipeline.Cue]) -> list[dub_pipeline.Cue]:
    """Collapse repeated/cumulative YouTube captions into non-overlapping cues."""
    output: list[dub_pipeline.Cue] = []
    shown = ""
    for cue in cues:
        text = cue.text.strip()
        if not text:
            continue
        compact = _compact(text)
        if not compact or compact == _compact(shown):
            continue
        if cue.end - cue.start < 0.05:
            # YouTube emits 10 ms replacement markers between rolling updates.
            shown = text
            continue
        fragment = _newly_visible(shown, text).strip()
        shown = text
        if not fragment or _NON_SPEECH.fullmatch(fragment):
            continue
        if output:
            preceding = output[-1]
            output[-1] = dub_pipeline.Cue(
                preceding.start, max(preceding.start + 0.01, cue.start), preceding.text
            )
        output.append(dub_pipeline.Cue(cue.start, max(cue.end, cue.start + 0.01), fragment))

    for previous, current in zip(output, output[1:], strict=False):
        if previous.end > current.start + 0.001:
            raise ValueError("caption normalisation created overlapping cues")
    return output


def _write_cues(cues: list[dub_pipeline.Cue], json_path: Path, srt_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps([{"start": cue.start, "end": cue.end, "text": cue.text} for cue in cues], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    srt_path.write_text(dub_pipeline.srt_text(cues), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dub a YouTube video from downloaded caption tracks")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--chinese-srt", type=Path, required=True)
    parser.add_argument("--english-srt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-stem", default="youtube-video")
    parser.add_argument("--title", required=True)
    parser.add_argument("--stage", choices=["subtitles", "all"], default="all")
    parser.add_argument("--delivery-dir", type=Path)
    parser.add_argument("--ref-audio", type=Path, default=dub_pipeline.APPROVED_REFERENCE_AUDIO)
    parser.add_argument("--speech-tempo", type=float, default=dub_pipeline.DEFAULT_SPEECH_TEMPO)
    parser.add_argument("--max-tempo", type=float, default=dub_pipeline.DEFAULT_MAX_TEMPO)
    args = parser.parse_args()

    chinese_cues = unfold_rolling_captions(parse_srt(args.chinese_srt))
    english_cues = unfold_rolling_captions(parse_srt(args.english_srt))
    if not chinese_cues or not english_cues:
        raise ValueError("caption inputs did not contain spoken cues")
    if args.delivery_dir is not None and args.stage != "all":
        raise ValueError("--delivery-dir requires --stage all")

    args.output.mkdir(parents=True, exist_ok=True)
    chinese_json = args.output / f"{args.artifact_stem}.zh-CN.json"
    chinese_srt = args.output / f"{args.artifact_stem}.zh-CN.srt"
    english_json = args.output / f"{args.artifact_stem}.en.json"
    english_srt = args.output / f"{args.artifact_stem}.en.srt"
    _write_cues(chinese_cues, chinese_json, chinese_srt)
    _write_cues(english_cues, english_json, english_srt)
    print(f"Chinese cues: {len(chinese_cues)}")
    print(f"English cues: {len(english_cues)}")
    if args.stage == "subtitles":
        return

    duration = dub_pipeline._probe_duration(args.input)
    speech_cues = dub_pipeline.group_cues(chinese_cues)
    clips = dub_pipeline.synthesize(
        speech_cues,
        args.output / "speech-clips",
        voice=args.ref_audio.stem,
        tts_engine="gpt-sovits",
        ref_audio=args.ref_audio,
        ref_text=dub_pipeline.APPROVED_REFERENCE_TEXT,
    )
    chinese_wav = args.output / f"{args.artifact_stem}.zh-CN.wav"
    dub_pipeline.assemble_audio(
        speech_cues, clips, duration, chinese_wav, args.speech_tempo, args.max_tempo
    )
    output_mp4 = args.output / f"{args.artifact_stem}.dual-audio.bilingual-subtitles.mp4"
    dub_pipeline.mux(args.input, chinese_wav, chinese_srt, english_srt, output_mp4)
    if args.delivery_dir is not None:
        delivery_video = dub_pipeline.publish_delivery(
            args.input,
            output_mp4,
            chinese_wav,
            chinese_srt,
            english_srt,
            chinese_json,
            args.delivery_dir,
            args.artifact_stem,
            args.speech_tempo,
            args.max_tempo,
            "youtube-auto-zh-Hans",
            "",
            "gpt-sovits",
            args.ref_audio,
            None,
            args.title,
        )
        print(delivery_video)
    else:
        print(output_mp4)


if __name__ == "__main__":
    main()
