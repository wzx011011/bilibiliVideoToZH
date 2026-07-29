from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from srt_to_reading_text import split_texts, subtitle_texts


def test_subtitle_texts_discards_srt_indexes_and_timestamps(tmp_path: Path):
    source = tmp_path / "sample.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nFirst line\nSecond line\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nNext cue\n",
        encoding="utf-8",
    )

    assert subtitle_texts(source) == ["First line Second line", "Next cue"]


def test_split_texts_keeps_each_cue_intact():
    assert split_texts(["1234", "56", "7890"], maximum_chars=7) == [
        "1234\n56",
        "7890",
    ]
