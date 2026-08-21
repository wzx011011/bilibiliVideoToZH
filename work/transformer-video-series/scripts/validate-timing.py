"""Validate a neural narration timing sidecar before rendering.

The renderer uses this file as the single source of truth for chapter,
subtitle, and semantic-focus timing. Keep the check dependency-free so it can
run in CI and on a clean machine.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"timing validation failed: {message}")


def positive_number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        fail(f"{label} must be a positive finite number")
    return float(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("timing", type=Path)
    parser.add_argument("--expected-duration", type=float)
    args = parser.parse_args()

    if not args.timing.is_file():
        fail(f"file does not exist: {args.timing}")

    try:
        payload = json.loads(args.timing.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"could not read JSON: {error}")

    duration = positive_number(payload.get("duration"), "duration")
    paragraph_durations = payload.get("paragraphDurations")
    cues = payload.get("subtitleCues")
    if not isinstance(paragraph_durations, list) or not paragraph_durations:
        fail("paragraphDurations must be a non-empty array")
    if not isinstance(cues, list) or not cues:
        fail("subtitleCues must be a non-empty array")

    chapter_total = sum(positive_number(value, f"paragraphDurations[{index}]") for index, value in enumerate(paragraph_durations))
    if abs(chapter_total - duration) > 0.02:
        fail(f"chapter durations sum to {chapter_total:.6f}, expected {duration:.6f}")

    previous_end = 0.0
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict) or not isinstance(cue.get("text"), str) or not cue["text"].strip():
            fail(f"subtitleCues[{index}] has no text")
        start = cue.get("from")
        cue_duration = cue.get("duration")
        if not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0:
            fail(f"subtitleCues[{index}].from must be a non-negative finite number")
        cue_duration = positive_number(cue_duration, f"subtitleCues[{index}].duration")
        start = float(start)
        if start + 0.02 < previous_end:
            fail(f"subtitleCues[{index}] overlaps the previous cue")
        if start + cue_duration > duration + 0.02:
            fail(f"subtitleCues[{index}] ends after duration")
        previous_end = start + cue_duration

    if args.expected_duration is not None and abs(duration - args.expected_duration) > 0.08:
        fail(f"sidecar duration {duration:.6f} differs from expected {args.expected_duration:.6f}")

    print(
        f"timing ok: {args.timing} | duration={duration:.3f}s | "
        f"chapters={len(paragraph_durations)} | cues={len(cues)}"
    )


if __name__ == "__main__":
    main()
