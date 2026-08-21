"""Sequentially generate the remaining Harvard Positive Psychology episodes.

Each episode has its own resumable working directory and delivery package.
The shared GPT-SoVITS service is intentionally used by one episode at a time.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "outputs" / "harvard-positive-psychology"
SOURCE_DIR = ROOT / "work" / "原版视频"
PIPELINE_DIR = Path(__file__).resolve().parent
LOG_PATH = OUTPUT_ROOT / "batch-13-23.log"


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def find_source(episode: int) -> Path | None:
    pattern = re.compile(rf"p{episode:02d}\b", re.IGNORECASE)
    return next((path for path in sorted(SOURCE_DIR.glob("*.mp4")) if pattern.search(path.name)), None)


def delivery_video(episode: int) -> Path:
    stem = f"episode-{episode:02d}.dual-audio.bilingual-subtitles.mp4"
    return OUTPUT_ROOT / f"episode-{episode:02d}-delivery" / "video" / stem


def episode_paths(episode: int) -> tuple[str, Path, Path]:
    stem = f"episode-{episode:02d}"
    return stem, OUTPUT_ROOT / f"{stem}-work", OUTPUT_ROOT / f"{stem}-delivery"


def pipeline_command(
    source: Path, work_dir: Path, delivery_dir: Path, stem: str, stage: str
) -> list[str]:
    command = [
        sys.executable,
        "-u",
        "dub_pipeline.py",
        "--input",
        str(source),
        "--full",
        "--output",
        str(work_dir),
        "--subtitle-source",
        "ocr",
        "--ocr-model",
        "rapidocr",
        "--artifact-stem",
        stem,
        "--stage",
        stage,
        "--skip-review",
        "--tts-speed",
        "0.92",
    ]
    if stage == "all":
        command.extend(["--delivery-dir", str(delivery_dir)])
    return command


def tail(path: Path, limit: int = 800) -> str:
    if not path.is_file():
        return "no stderr log was written"
    return path.read_text(encoding="utf-8", errors="replace")[-limit:].replace("\n", " ")


def preprocess_episode(episode: int) -> bool:
    """Prepare transcription and OCR subtitles without using GPT-SoVITS."""
    if delivery_video(episode).is_file():
        return True
    source = find_source(episode)
    if source is None:
        log(f"episode {episode:02d}: preflight source video not found")
        return False

    stem, work_dir, delivery_dir = episode_paths(episode)
    work_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = work_dir / "preflight.stdout.log"
    stderr_log = work_dir / "preflight.stderr.log"
    log(f"episode {episode:02d}: subtitle preflight started")
    started_at = time.monotonic()
    with stdout_log.open("w", encoding="utf-8") as stdout, stderr_log.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(
            pipeline_command(source, work_dir, delivery_dir, stem, "subtitles"),
            cwd=PIPELINE_DIR,
            stdout=stdout,
            stderr=stderr,
        )
    elapsed_minutes = (time.monotonic() - started_at) / 60
    subtitles = work_dir / f"{stem}.zh-CN.srt"
    if result.returncode == 0 and subtitles.is_file() and subtitles.stat().st_size > 0:
        log(f"episode {episode:02d}: subtitle preflight completed in {elapsed_minutes:.1f} minutes")
        return True
    log(
        f"episode {episode:02d}: subtitle preflight failed (exit={result.returncode}, "
        f"{elapsed_minutes:.1f} minutes): {tail(stderr_log)}"
    )
    return False


def run_episode(episode: int) -> bool:
    video = delivery_video(episode)
    if video.is_file() and video.stat().st_size > 0:
        log(f"episode {episode:02d}: delivery already exists; skipped")
        return True

    source = find_source(episode)
    if source is None:
        log(f"episode {episode:02d}: source video not found")
        return False

    stem, work_dir, delivery_dir = episode_paths(episode)
    work_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = work_dir / "build.stdout.log"
    stderr_log = work_dir / "build.stderr.log"
    log(f"episode {episode:02d}: started ({source.name})")
    started_at = time.monotonic()
    with stdout_log.open("w", encoding="utf-8") as stdout, stderr_log.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(
            pipeline_command(source, work_dir, delivery_dir, stem, "all"),
            cwd=PIPELINE_DIR,
            stdout=stdout,
            stderr=stderr,
        )
    elapsed_minutes = (time.monotonic() - started_at) / 60

    if result.returncode == 0 and video.is_file() and video.stat().st_size > 0:
        log(f"episode {episode:02d}: completed in {elapsed_minutes:.1f} minutes")
        return True

    log(
        f"episode {episode:02d}: failed (exit={result.returncode}, "
        f"{elapsed_minutes:.1f} minutes): {tail(stderr_log)}"
    )
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Harvard episodes 13 through 23")
    parser.add_argument("--start", type=int, default=13)
    parser.add_argument("--end", type=int, default=23)
    args = parser.parse_args()
    if args.start > args.end:
        raise ValueError("--start must be no greater than --end")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log(f"batch started: episodes {args.start:02d}-{args.end:02d}; CPU subtitle preflight runs in parallel")
    succeeded: list[int] = []
    failed: list[int] = []
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="subtitle-preflight") as pool:
        preflights: dict[int, Future[bool]] = {
            episode: pool.submit(preprocess_episode, episode)
            for episode in range(args.start + 1, args.end + 1)
        }
        for episode in range(args.start, args.end + 1):
            future = preflights.get(episode)
            if future is not None and not future.result():
                log(f"episode {episode:02d}: preflight unavailable; full run will regenerate its missing stages")
            (succeeded if run_episode(episode) else failed).append(episode)

    log(f"batch finished: succeeded={succeeded}; failed={failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
