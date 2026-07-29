"""Record the Windows default playback device through WASAPI loopback.

This is intended for capturing audio played by a locally opened app or browser.
It deliberately does not automate any third-party service.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np


DEFAULT_SAMPLE_RATE = 48_000
CHUNK_SECONDS = 0.25


def _soundcard():
    try:
        import soundcard as sc
    except ImportError as error:
        raise RuntimeError(
            "soundcard is required. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from error
    return sc


def loopback_devices() -> list[dict[str, int | str]]:
    """Return Windows playback devices that can also be captured by loopback."""
    sc = _soundcard()
    return [
        {
            "id": str(speaker.id),
            "name": str(speaker.name),
            "channels": int(speaker.channels),
        }
        for speaker in sc.all_speakers()
    ]


def _select_loopback(device: str | None):
    sc = _soundcard()
    if device is None:
        speaker = sc.default_speaker()
    else:
        speaker = next(
            (
                candidate
                for candidate in sc.all_speakers()
                if device in {str(candidate.id), str(candidate.name)}
            ),
            None,
        )
        if speaker is None:
            raise ValueError(
                f"No playback device matches {device!r}. "
                "Use --list-devices to see valid values."
            )

    microphone = sc.get_microphone(str(speaker.id), include_loopback=True)
    if microphone is None:
        raise RuntimeError(f"Could not create a loopback recorder for {speaker.name!r}")
    return speaker, microphone


def pcm16(samples: np.ndarray) -> np.ndarray:
    """Convert SoundCard's floating point frames into interleaved PCM16."""
    frames = np.asarray(samples)
    if frames.ndim != 2:
        raise ValueError("recorded samples must have shape (frames, channels)")
    clipped = np.clip(frames, -1.0, 1.0)
    return np.rint(clipped * 32767.0).astype("<i2")


def record_loopback(
    output: Path,
    duration: float | None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    device: str | None = None,
    channels: int | None = None,
) -> Path:
    """Record a speaker's loopback stream until duration elapses or Ctrl+C."""
    if duration is not None and duration <= 0:
        raise ValueError("duration must be positive when supplied")
    if sample_rate <= 0:
        raise ValueError("sample rate must be positive")

    speaker, microphone = _select_loopback(device)
    channel_count = int(channels or speaker.channels)
    if not 1 <= channel_count <= microphone.channels:
        raise ValueError(
            f"{speaker.name!r} supports 1-{microphone.channels} capture channels, "
            f"not {channel_count}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    chunk_frames = max(1, round(sample_rate * CHUNK_SECONDS))
    print(
        f"Recording system audio from: {speaker.name} "
        f"({channel_count}ch, {sample_rate} Hz)",
        file=sys.stderr,
    )
    print("Start playback now. Press Ctrl+C to stop.", file=sys.stderr)

    try:
        with wave.open(str(output), "wb") as destination:
            destination.setnchannels(channel_count)
            destination.setsampwidth(2)
            destination.setframerate(sample_rate)
            with microphone.recorder(
                samplerate=sample_rate, channels=channel_count
            ) as recorder:
                started = time.monotonic()
                while True:
                    elapsed = time.monotonic() - started
                    if duration is not None and elapsed >= duration:
                        break
                    frames = chunk_frames
                    if duration is not None:
                        frames = min(
                            frames,
                            max(1, round((duration - elapsed) * sample_rate)),
                        )
                    destination.writeframes(pcm16(recorder.record(numframes=frames)).tobytes())
    except KeyboardInterrupt:
        print("\nRecording stopped.", file=sys.stderr)

    print(f"Saved: {output}", file=sys.stderr)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record Windows playback audio through WASAPI loopback"
    )
    parser.add_argument("--output", type=Path, help="Destination WAV file")
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop automatically after this many seconds; omit and use Ctrl+C",
    )
    parser.add_argument(
        "--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE, help="WAV sample rate"
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Playback device name or ID; defaults to the Windows default speaker",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=None,
        help="Capture channel count; defaults to the selected speaker's channel count",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List playback devices that can be captured through loopback",
    )
    args = parser.parse_args()

    if args.list_devices:
        for item in loopback_devices():
            print(f"{item['name']}\t{item['channels']}ch\t{item['id']}")
        return
    if args.output is None:
        parser.error("--output is required unless --list-devices is used")

    record_loopback(
        output=args.output,
        duration=args.duration,
        sample_rate=args.sample_rate,
        device=args.device,
        channels=args.channels,
    )


if __name__ == "__main__":
    main()
