"""Create Bilibili-compatible H.264/AAC upload copies from delivery packages."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DELIVERY_ROOT = ROOT / "outputs" / "harvard-positive-psychology"
OUTPUT_ROOT = DELIVERY_ROOT / "bilibili-upload-h264-aac"
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"
LOG_PATH = OUTPUT_ROOT / "conversion.log"
LOG_LOCK = threading.Lock()


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    with LOG_LOCK:
        print(line, flush=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def delivery_dir(episode: int) -> Path:
    if episode == 1:
        return DELIVERY_ROOT / "episode-01-delivery-revised"
    return DELIVERY_ROOT / f"episode-{episode:02d}-delivery"


def delivery_video(episode: int) -> Path:
    video_dir = delivery_dir(episode) / "video"
    matches = sorted(video_dir.glob("*.mp4"))
    if len(matches) != 1:
        raise FileNotFoundError(f"episode {episode:02d}: expected one delivery MP4 in {video_dir}")
    return matches[0]


def output_video(episode: int) -> Path:
    return OUTPUT_ROOT / "video" / f"episode-{episode:02d}.bilibili-h264-aac.mp4"


def output_subtitle(episode: int) -> Path:
    return OUTPUT_ROOT / "subtitles" / f"episode-{episode:02d}.zh-CN.srt"


def probe_streams(path: Path) -> list[dict[str, object]]:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(path)],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(result.stdout).get("streams", [])


def is_ready(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        streams = probe_streams(path)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return False
    return any(stream.get("codec_type") == "video" and stream.get("codec_name") == "h264" for stream in streams) and any(
        stream.get("codec_type") == "audio" and stream.get("codec_name") == "aac" for stream in streams
    )


def convert_episode(episode: int, threads: int) -> dict[str, object]:
    source = delivery_video(episode)
    destination = output_video(episode)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if is_ready(destination):
        log(f"episode {episode:02d}: upload video already exists; skipped")
        return {"episode": episode, "status": "skipped", "video": str(destination)}

    temporary = destination.with_suffix(".part.mp4")
    temporary.unlink(missing_ok=True)
    log(f"episode {episode:02d}: transcoding")
    started = time.monotonic()
    command = [
        str(FFMPEG),
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-maxrate",
        "8M",
        "-bufsize",
        "16M",
        "-profile:v",
        "high",
        "-level:v",
        "4.1",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        str(threads),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(temporary),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        detail = result.stderr[-1500:].replace("\n", " ")
        log(f"episode {episode:02d}: failed: {detail}")
        return {"episode": episode, "status": "failed", "error": detail}
    temporary.replace(destination)
    if not is_ready(destination):
        destination.unlink(missing_ok=True)
        log(f"episode {episode:02d}: output validation failed")
        return {"episode": episode, "status": "failed", "error": "H.264/AAC validation failed"}

    subtitle = delivery_dir(episode) / "subtitles" / f"episode-{episode:02d}.zh-CN.srt"
    if subtitle.is_file():
        target_subtitle = output_subtitle(episode)
        target_subtitle.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(subtitle, target_subtitle)
    elapsed = (time.monotonic() - started) / 60
    log(f"episode {episode:02d}: completed in {elapsed:.1f} minutes")
    return {"episode": episode, "status": "completed", "video": str(destination)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Bilibili H.264/AAC upload videos")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--threads-per-worker", type=int, default=5)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=23)
    args = parser.parse_args()
    if args.workers < 1 or args.threads_per_worker < 1:
        raise ValueError("worker counts must be positive")
    if not 1 <= args.start <= args.end <= 23:
        raise ValueError("episode range must be within 1 through 23")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    log(
        "batch started: MP4/H.264/yuv420p/AAC 192k stereo, Chinese dub, "
        f"workers={args.workers}, threads-per-worker={args.threads_per_worker}"
    )
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="bilibili-transcode") as pool:
        futures = {
            pool.submit(convert_episode, episode, args.threads_per_worker): episode
            for episode in range(args.start, args.end + 1)
        }
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: int(item["episode"]))
    manifest = {
        "schema_version": 1,
        "format": {
            "container": "mp4",
            "video": "h264/high/yuv420p",
            "audio": "aac/192k/stereo",
            "audio_track": "Mandarin dub",
            "resolution": "preserved from delivery source",
        },
        "episodes": results,
    }
    (OUTPUT_ROOT / "upload-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    failed = [item["episode"] for item in results if item["status"] == "failed"]
    log(f"batch finished: completed={len(results) - len(failed)}, failed={failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
