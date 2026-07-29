"""Prepare plain reading text from an SRT file for manual playback in an app."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


TIMESTAMP_LINE = re.compile(
    r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*"
)


def subtitle_texts(source: Path) -> list[str]:
    """Extract non-empty subtitle text blocks while discarding SRT metadata."""
    content = source.read_text(encoding="utf-8-sig")
    texts: list[str] = []
    for block in re.split(r"\r?\n\s*\r?\n", content.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines and lines[0].isdigit():
            lines.pop(0)
        if lines and TIMESTAMP_LINE.match(lines[0]):
            lines.pop(0)
        text = " ".join(lines).strip()
        if text:
            texts.append(text)
    return texts


def split_texts(texts: list[str], maximum_chars: int) -> list[str]:
    """Pack whole subtitle cues into paste-friendly chunks without splitting cues."""
    if maximum_chars <= 0:
        raise ValueError("maximum chars must be positive")

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for text in texts:
        separator_length = 1 if current else 0
        if current and current_length + separator_length + len(text) > maximum_chars:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(text)
        current_length += separator_length + len(text)
    if current:
        chunks.append("\n".join(current))
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract subtitle text for manual text-to-speech playback"
    )
    parser.add_argument("--input", required=True, type=Path, help="Source SRT file")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="One combined plain-text output file",
    )
    parser.add_argument(
        "--chunks-dir",
        type=Path,
        default=None,
        help="Write numbered paste-sized text files to this directory",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=800,
        help="Maximum characters per chunk when --chunks-dir is used",
    )
    args = parser.parse_args()
    if args.output is None and args.chunks_dir is None:
        parser.error("specify --output, --chunks-dir, or both")

    texts = subtitle_texts(args.input)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(texts) + ("\n" if texts else ""), encoding="utf-8")
        print(args.output)

    if args.chunks_dir is not None:
        args.chunks_dir.mkdir(parents=True, exist_ok=True)
        chunks = split_texts(texts, args.max_chars)
        for index, chunk in enumerate(chunks, start=1):
            output = args.chunks_dir / f"{index:04d}.txt"
            output.write_text(chunk + "\n", encoding="utf-8")
            print(output)


if __name__ == "__main__":
    main()
