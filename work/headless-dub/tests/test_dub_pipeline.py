from pathlib import Path
import json
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dub_pipeline
from dub_pipeline import (
    Cue,
    apply_review_overrides,
    clean_ocr_cues,
    collect_external_clips,
    group_cues,
    mux,
    normalize_external_audio,
    publish_delivery,
    run_pilot,
    schedule_audio,
    srt_text,
    stage_complete,
    tempo_for,
    translate_with,
)


def test_group_cues_merges_short_adjacent_utterances():
    cues = [
        Cue(0.0, 2.0, "One."),
        Cue(2.1, 4.0, "Two."),
        Cue(9.0, 10.0, "Three."),
    ]

    assert group_cues(cues) == [
        Cue(0.0, 4.0, "One. Two."),
        Cue(9.0, 10.0, "Three."),
    ]


def test_tempo_for_only_speeds_up_overlong_audio():
    assert tempo_for(5.0, 4.0) == 1.25
    assert tempo_for(5.0, 6.25) == 1.0

    try:
        tempo_for(5.0, 3.0)
    except ValueError as error:
        assert "outside" in str(error)
    else:
        raise AssertionError("tempo_for accepted an unsafe factor")


def test_schedule_audio_uses_the_gap_before_the_next_cue():
    cues = [Cue(0.0, 1.0, "One"), Cue(3.0, 4.0, "Two")]

    scheduled = schedule_audio(cues, [2.0, 1.0], duration_seconds=5.0)

    assert scheduled[0].start == 0.0
    assert scheduled[0].tempo == 0.98
    assert scheduled[0].end == 2.0 / 0.98
    assert scheduled[1].start == 3.0


def test_schedule_audio_caps_tempo_and_queues_without_overlap():
    cues = [
        Cue(0.0, 1.0, "One"),
        Cue(1.0, 2.0, "Two"),
        Cue(5.0, 6.0, "Three"),
    ]

    scheduled = schedule_audio(
        cues,
        [3.0, 1.0, 1.0],
        duration_seconds=7.0,
        preferred_tempo=1.0,
        max_tempo=1.25,
    )

    assert scheduled[0].tempo == 1.25
    assert scheduled[0].end == 2.4
    assert scheduled[1].start == 2.4
    assert scheduled[1].tempo == 1.0
    assert scheduled[1].end == 3.4
    assert scheduled[2].start == 5.0
    assert all(
        current.end <= following.start
        for current, following in zip(scheduled, scheduled[1:])
    )


def test_schedule_audio_defaults_to_a_slightly_slower_natural_rate():
    cues = [Cue(0.0, 1.0, "One"), Cue(3.0, 4.0, "Two")]

    scheduled = schedule_audio(cues, [1.0, 1.0], duration_seconds=5.0)

    assert [item.tempo for item in scheduled] == [0.98, 0.98]
    assert all(item.tempo <= 1.05 for item in scheduled)


def test_schedule_audio_limits_necessary_rushing_to_five_percent():
    cues = [Cue(0.0, 1.0, "One"), Cue(1.0, 2.0, "Two")]

    scheduled = schedule_audio(cues, [3.0, 1.0], duration_seconds=5.0)

    assert scheduled[0].tempo == 1.05
    assert scheduled[1].start == scheduled[0].end


def test_schedule_audio_rejects_audio_past_the_timeline():
    cues = [Cue(4.0, 5.0, "Too long")]

    try:
        schedule_audio(cues, [3.0], duration_seconds=5.0)
    except ValueError as error:
        assert "timeline" in str(error)
    else:
        raise AssertionError("schedule_audio accepted audio past the timeline")


def test_srt_text_numbers_cues_and_formats_timestamps():
    assert srt_text([Cue(1.25, 2.5, "hello")]) == (
        "1\n00:00:01,250 --> 00:00:02,500\nhello\n"
    )


def test_translate_with_preserves_time_ranges_and_translates_text():
    source = [Cue(1.0, 3.0, "Positive psychology")]

    result = translate_with(source, lambda texts: ["\u79ef\u6781\u5fc3\u7406\u5b66"])

    assert result == [Cue(1.0, 3.0, "\u79ef\u6781\u5fc3\u7406\u5b66")]


def test_clean_ocr_cues_removes_rolling_overlap_and_exact_repetition():
    cues = [
        Cue(0.0, 1.0, "今天 我们谈积极心理学"),
        Cue(1.0, 2.0, "积极心理学 如何改变生活"),
        Cue(2.0, 3.0, "如何改变生活"),
        Cue(3.0, 4.0, "在美国 超过二百所学校 在美国 超过二百所学校 都开设了"),
    ]

    assert clean_ocr_cues(cues) == [
        Cue(0.0, 1.0, "今天 我们谈积极心理学"),
        Cue(1.0, 3.0, "如何改变生活"),
        Cue(3.0, 4.0, "在美国 超过二百所学校 都开设了"),
    ]


def test_clean_ocr_cues_drops_known_ocr_watermark_artifacts():
    cues = [
        Cue(0.0, 1.0, "内卡CC 今天的课程开始"),
        Cue(1.0, 2.0, "内卡CC"),
        Cue(2.0, 3.0, "（无中 接下来继续"),
    ]

    assert clean_ocr_cues(cues) == [
        Cue(0.0, 1.0, "今天的课程开始"),
        Cue(2.0, 3.0, "接下来继续"),
    ]


def test_clean_ocr_cues_preserves_valid_book_title_punctuation():
    cues = [Cue(0.0, 1.0, "推荐阅读《积极心理学》")]

    assert clean_ocr_cues(cues) == cues


def test_apply_review_overrides_changes_text_and_restores_cue(tmp_path: Path):
    review_file = tmp_path / "review.json"
    review_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "overrides": [{"start": 1.0, "text": "已复核"}],
                "previous_ends": [{"start": 1.0, "end": 1.5}],
                "restored_cues": [{"start": 1.5, "end": 2.0, "text": "补回"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = apply_review_overrides(
        [Cue(0.0, 1.0, "原始"), Cue(1.0, 3.0, "待修改")], review_file
    )

    assert result == [
        Cue(0.0, 1.0, "原始"),
        Cue(1.0, 1.5, "已复核"),
        Cue(1.5, 2.0, "补回"),
    ]


def test_apply_review_overrides_rejects_unknown_cue_start(tmp_path: Path):
    review_file = tmp_path / "review.json"
    review_file.write_text(
        '{"schema_version": 1, "overrides": [{"start": 9, "text": "不存在"}]}',
        encoding="utf-8",
    )

    try:
        apply_review_overrides([Cue(0.0, 1.0, "原始")], review_file)
    except ValueError as error:
        assert "missing cue starts" in str(error)
    else:
        raise AssertionError("unknown review cue start was accepted")


def test_stage_complete_requires_matching_input_fingerprint(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text('{"transcript":"abc"}', encoding="utf-8")

    assert stage_complete(state, "transcript", "abc")
    assert not stage_complete(state, "transcript", "changed")
    assert not stage_complete(state, "translation", "abc")


def test_normalize_external_audio_converts_to_48k_mono_pcm_wav(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "doubao-recording.m4a"
    source.write_bytes(b"recording")
    output = tmp_path / "normalized.wav"
    commands: list[list[str | Path]] = []

    def fake_command(arguments: list[str | Path]):
        commands.append(arguments)
        Path(arguments[-1]).write_bytes(b"normalized")

    monkeypatch.setattr(dub_pipeline, "_command", fake_command)

    normalize_external_audio(source, output)

    assert output.read_bytes() == b"normalized"
    assert not output.with_suffix(".external.tmp.wav").exists()
    command = commands[0]
    assert command[command.index("-map") + 1] == "0:a:0"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-c:a") + 1] == "pcm_s16le"


def test_collect_external_clips_requires_each_numbered_audio_file(tmp_path: Path):
    clips_dir = tmp_path / "recorded-clips"
    clips_dir.mkdir()
    first = clips_dir / "0001.wav"
    second = clips_dir / "0002.m4a"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    cues = [Cue(0.0, 1.0, "first"), Cue(1.0, 2.0, "second")]

    assert collect_external_clips(cues, clips_dir) == [first, second]

    second.unlink()
    try:
        collect_external_clips(cues, clips_dir)
    except ValueError as error:
        assert "0002" in str(error)
    else:
        raise AssertionError("missing external clip was accepted")


def test_run_pilot_external_audio_bypasses_tts_and_rebuilds_after_re_recording(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    recording = tmp_path / "doubao-recording.m4a"
    recording.write_bytes(b"first recording")
    output_dir = tmp_path / "delivery"
    calls = {"normalize": 0, "mux": 0}

    def fake_extract(_source: Path, _duration: float, output: Path) -> None:
        output.write_bytes(b"segment")

    def fake_transcribe(_segment: Path, _model: str) -> list[Cue]:
        return [Cue(0.0, 1.0, "Hello")]

    def fake_translate(cues: list[Cue]) -> list[Cue]:
        return [Cue(cue.start, cue.end, "ni hao") for cue in cues]

    def fake_normalize(input_audio: Path, output: Path) -> None:
        calls["normalize"] += 1
        output.write_bytes(b"normalized:" + input_audio.read_bytes())

    def fake_mux(
        _source: Path,
        _audio: Path,
        _chinese_srt: Path,
        _english_srt: Path,
        output: Path,
    ) -> None:
        calls["mux"] += 1
        output.write_bytes(b"muxed")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("external full audio must not use the TTS assembly path")

    monkeypatch.setattr(dub_pipeline, "_extract_source_segment", fake_extract)
    monkeypatch.setattr(dub_pipeline, "transcribe", fake_transcribe)
    monkeypatch.setattr(dub_pipeline, "translate", fake_translate)
    monkeypatch.setattr(dub_pipeline, "normalize_external_audio", fake_normalize)
    monkeypatch.setattr(dub_pipeline, "mux", fake_mux)
    monkeypatch.setattr(dub_pipeline, "synthesize", unexpected)
    monkeypatch.setattr(dub_pipeline, "assemble_audio", unexpected)
    monkeypatch.setattr(dub_pipeline, "_probe_duration", unexpected)

    first_output = run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        external_audio=recording,
        subtitle_source="nllb",
    )
    second_output = run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        external_audio=recording,
        subtitle_source="nllb",
    )

    assert first_output == second_output
    assert calls == {"normalize": 1, "mux": 1}

    recording.write_bytes(b"replacement recording")
    run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        external_audio=recording,
        subtitle_source="nllb",
    )

    assert calls == {"normalize": 2, "mux": 2}


def test_run_pilot_external_clips_bypass_tts(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    clips_dir = tmp_path / "recorded-clips"
    clips_dir.mkdir()
    recorded_clip = clips_dir / "0001.wav"
    recorded_clip.write_bytes(b"recorded clip")
    output_dir = tmp_path / "delivery"
    assembled: list[Path] = []

    def fake_extract(_source: Path, _duration: float, output: Path) -> None:
        output.write_bytes(b"segment")

    def fake_transcribe(_segment: Path, _model: str) -> list[Cue]:
        return [Cue(0.0, 1.0, "Hello")]

    def fake_translate(cues: list[Cue]) -> list[Cue]:
        return [Cue(cue.start, cue.end, "ni hao") for cue in cues]

    def fake_assemble(
        _cues: list[Cue],
        clips: list[Path],
        _duration: float,
        output: Path,
        **_kwargs,
    ) -> None:
        assembled.extend(clips)
        output.write_bytes(b"assembled")

    def fake_mux(
        _source: Path,
        _audio: Path,
        _chinese_srt: Path,
        _english_srt: Path,
        output: Path,
    ) -> None:
        output.write_bytes(b"muxed")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("external clips must not use TTS")

    monkeypatch.setattr(dub_pipeline, "_extract_source_segment", fake_extract)
    monkeypatch.setattr(dub_pipeline, "transcribe", fake_transcribe)
    monkeypatch.setattr(dub_pipeline, "translate", fake_translate)
    monkeypatch.setattr(dub_pipeline, "_probe_duration", lambda _path: 5.0)
    monkeypatch.setattr(dub_pipeline, "assemble_audio", fake_assemble)
    monkeypatch.setattr(dub_pipeline, "mux", fake_mux)
    monkeypatch.setattr(dub_pipeline, "synthesize", unexpected)

    run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        external_clips_dir=clips_dir,
        subtitle_source="nllb",
    )

    assert assembled == [recorded_clip]


def test_run_pilot_uses_configurable_artifact_stem(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    recording = tmp_path / "recording.wav"
    recording.write_bytes(b"recording")
    output_dir = tmp_path / "output"

    monkeypatch.setattr(
        dub_pipeline,
        "_extract_source_segment",
        lambda _source, _duration, output: output.write_bytes(b"segment"),
    )
    monkeypatch.setattr(
        dub_pipeline,
        "transcribe",
        lambda _segment, _model: [Cue(0.0, 1.0, "Hello")],
    )
    monkeypatch.setattr(
        dub_pipeline,
        "translate",
        lambda cues: [Cue(cue.start, cue.end, "你好") for cue in cues],
    )
    monkeypatch.setattr(
        dub_pipeline,
        "normalize_external_audio",
        lambda _source, output: output.write_bytes(b"audio"),
    )
    monkeypatch.setattr(
        dub_pipeline,
        "mux",
        lambda _source, _audio, _chinese_srt, _english_srt, output: output.write_bytes(b"muxed"),
    )

    output = run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        external_audio=recording,
        artifact_stem="episode-02",
        subtitle_source="nllb",
    )

    assert output.name == "episode-02.dual-audio.bilingual-subtitles.mp4"
    assert (output_dir / "episode-02.source.mp4").exists()
    assert (output_dir / "episode-02.zh-CN.srt").exists()
    assert (output_dir / "episode-02.en.srt").exists()


def test_run_pilot_subtitles_stage_skips_synthesis_and_mux(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output_dir = tmp_path / "output"

    monkeypatch.setattr(
        dub_pipeline,
        "_extract_source_segment",
        lambda _source, _duration, output: output.write_bytes(b"segment"),
    )
    monkeypatch.setattr(
        dub_pipeline,
        "transcribe",
        lambda _segment, _model: [Cue(0.0, 1.0, "Hello")],
    )
    monkeypatch.setattr(
        dub_pipeline,
        "translate",
        lambda cues: [Cue(cue.start, cue.end, "你好") for cue in cues],
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("subtitle stage must not synthesize or mux")

    monkeypatch.setattr(dub_pipeline, "synthesize", unexpected)
    monkeypatch.setattr(dub_pipeline, "assemble_audio", unexpected)
    monkeypatch.setattr(dub_pipeline, "mux", unexpected)

    output = run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        artifact_stem="episode-02",
        stage="subtitles",
        subtitle_source="nllb",
    )

    assert output == output_dir / "episode-02.zh-CN.srt"
    assert output.read_text(encoding="utf-8") == "1\n00:00:00,000 --> 00:00:01,000\n你好\n"


def test_mux_builds_bilingual_delivery_with_language_and_default_tracks(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "source.mp4"
    chinese_wav = tmp_path / "dub.wav"
    chinese_srt = tmp_path / "episode.zh-CN.srt"
    english_srt = tmp_path / "episode.en.srt"
    output = tmp_path / "episode.dual-audio.bilingual-subtitles.mp4"
    commands: list[list[str | Path]] = []

    monkeypatch.setattr(dub_pipeline, "_command", lambda arguments: commands.append(arguments))

    mux(source, chinese_wav, chinese_srt, english_srt, output)

    command = commands[0]
    inputs = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "-i"]
    maps = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "-map"]
    metadata = [
        (command[index], command[index + 1])
        for index, value in enumerate(command[:-1])
        if isinstance(value, str) and value.startswith("-metadata:")
    ]
    dispositions = [
        (command[index], command[index + 1])
        for index, value in enumerate(command[:-1])
        if isinstance(value, str) and value.startswith("-disposition:")
    ]

    assert inputs == [source, chinese_wav, chinese_srt, english_srt]
    assert maps == ["0:v:0", "1:a:0", "0:a:0?", "2:0", "3:0"]
    assert command[command.index("-c:s") + 1] == "mov_text"
    assert ("-metadata:s:a:0", "language=zho") in metadata
    assert ("-metadata:s:a:1", "language=eng") in metadata
    assert ("-metadata:s:s:0", "title=Chinese subtitles") in metadata
    assert ("-metadata:s:s:0", "language=zho") in metadata
    assert ("-metadata:s:s:1", "title=English subtitles") in metadata
    assert ("-metadata:s:s:1", "language=eng") in metadata
    assert dispositions == [
        ("-disposition:a:0", "default"),
        ("-disposition:a:1", "0"),
        ("-disposition:s:0", "default"),
        ("-disposition:s:1", "0"),
    ]


def test_run_pilot_remuxes_when_english_subtitles_change(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    recording = tmp_path / "recording.m4a"
    recording.write_bytes(b"recording")
    output_dir = tmp_path / "work"
    mux_calls: list[str] = []

    monkeypatch.setattr(
        dub_pipeline,
        "_extract_source_segment",
        lambda _source, _duration, output: output.write_bytes(b"segment"),
    )
    monkeypatch.setattr(
        dub_pipeline,
        "transcribe",
        lambda _segment, _model: [Cue(0.0, 1.0, "Hello")],
    )
    monkeypatch.setattr(
        dub_pipeline,
        "translate",
        lambda cues: [Cue(cue.start, cue.end, "你好") for cue in cues],
    )
    monkeypatch.setattr(
        dub_pipeline,
        "normalize_external_audio",
        lambda _source, output: output.write_bytes(b"audio"),
    )

    def fake_mux(
        _source: Path,
        _audio: Path,
        _chinese_srt: Path,
        english_srt: Path,
        output: Path,
    ) -> None:
        mux_calls.append(english_srt.read_text(encoding="utf-8"))
        output.write_bytes(b"muxed")

    monkeypatch.setattr(dub_pipeline, "mux", fake_mux)

    run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        external_audio=recording,
        subtitle_source="nllb",
    )
    english_srt = output_dir / "episode.en.srt"
    english_srt.write_text(english_srt.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        external_audio=recording,
        subtitle_source="nllb",
    )

    assert len(mux_calls) == 2


def test_run_pilot_requires_review_for_final_ocr(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    try:
        run_pilot(source, 5.0, tmp_path / "work", "test-model", "test-voice")
    except ValueError as error:
        assert "--review-file" in str(error)
    else:
        raise AssertionError("final OCR run accepted an unreviewed subtitle set")


def test_review_change_uses_a_new_synthesis_clip_cache(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output_dir = tmp_path / "work"
    review_file = tmp_path / "review.json"
    synthesized: list[tuple[Path, str]] = []

    def write_review(text: str) -> None:
        review_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "overrides": [{"start": 0.0, "text": text}],
                    "previous_ends": [],
                    "restored_cues": [],
                }
            ),
            encoding="utf-8",
        )

    def fake_ocr_run(_segment, target_dir: Path, **_kwargs):
        raw_srt = target_dir / "raw.zh-CN.srt"
        raw_json = target_dir / "raw.zh-CN.json"
        raw_srt.write_text("", encoding="utf-8")
        raw_json.write_text(
            json.dumps([{"start": 0.0, "end": 1.0, "text": "原始文本"}]),
            encoding="utf-8",
        )
        return raw_srt, raw_json

    fake_ocr = SimpleNamespace(Cue=lambda *_args: None, run=fake_ocr_run)
    monkeypatch.setitem(sys.modules, "subtitle_ocr", fake_ocr)
    monkeypatch.setattr(
        dub_pipeline,
        "_extract_source_segment",
        lambda _source, _duration, output: output.write_bytes(b"segment"),
    )
    monkeypatch.setattr(
        dub_pipeline,
        "transcribe",
        lambda _segment, _model: [Cue(0.0, 1.0, "Hello")],
    )
    monkeypatch.setattr(dub_pipeline, "_probe_duration", lambda _path: 5.0)

    def fake_synthesize(cues, clips_dir: Path, *_args, **_kwargs):
        synthesized.append((clips_dir, cues[0].text))
        clips_dir.mkdir(parents=True, exist_ok=True)
        clip = clips_dir / "0001.mp3"
        clip.write_bytes(b"clip")
        return [clip]

    monkeypatch.setattr(dub_pipeline, "synthesize", fake_synthesize)
    monkeypatch.setattr(
        dub_pipeline,
        "assemble_audio",
        lambda _cues, _clips, _duration, output, **_kwargs: output.write_bytes(b"audio"),
    )
    monkeypatch.setattr(
        dub_pipeline,
        "mux",
        lambda _source, _audio, _chinese_srt, _english_srt, output: output.write_bytes(b"muxed"),
    )

    write_review("已复核文本一")
    run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        review_file=review_file,
        artifact_stem="episode-02",
    )
    write_review("已复核文本二二")
    run_pilot(
        source,
        5.0,
        output_dir,
        "test-model",
        "test-voice",
        review_file=review_file,
        artifact_stem="episode-02",
    )

    assert [text for _directory, text in synthesized] == ["已复核文本一", "已复核文本二二"]
    assert synthesized[0][0] != synthesized[1][0]


def test_main_uses_the_approved_production_defaults(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    review_file = tmp_path / "review.json"
    review_file.write_text('{"schema_version": 1}', encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_pilot(*arguments, **keywords):
        captured["arguments"] = arguments
        captured["keywords"] = keywords
        return tmp_path / "result.mp4"

    monkeypatch.setattr(dub_pipeline, "run_pilot", fake_run_pilot)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dub_pipeline.py",
            "--input",
            str(source),
            "--output",
            str(tmp_path / "work"),
            "--review-file",
            str(review_file),
            "--delivery-dir",
            str(tmp_path / "delivery"),
        ],
    )

    dub_pipeline.main()

    arguments = captured["arguments"]
    keywords = captured["keywords"]
    assert arguments[1] == 120.0
    assert keywords["subtitle_source"] == "ocr"
    assert keywords["tts_engine"] == "gpt-sovits"
    assert keywords["ref_audio"] == dub_pipeline.APPROVED_REFERENCE_AUDIO
    assert keywords["ref_text"] == dub_pipeline.APPROVED_REFERENCE_TEXT
    assert keywords["speech_tempo"] == 0.98
    assert keywords["max_tempo"] == 1.05
    assert keywords["stage"] == "all"
    assert keywords["delivery_dir"] == tmp_path / "delivery"


def test_publish_delivery_creates_a_self_contained_checked_package(
    tmp_path: Path, monkeypatch
):
    source_segment = tmp_path / "episode.source.mp4"
    video = tmp_path / "episode.dual-audio.bilingual-subtitles.mp4"
    chinese_wav = tmp_path / "episode.zh-CN.wav"
    chinese_srt = tmp_path / "episode.zh-CN.srt"
    english_srt = tmp_path / "episode.en.srt"
    chinese_json = tmp_path / "episode.zh-CN.json"
    review_file = tmp_path / "review.json"
    for path in (source_segment, video, chinese_wav):
        path.write_bytes(path.name.encode("utf-8"))
    chinese_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    english_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    chinese_json.write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "text": "你好"}]), encoding="utf-8"
    )
    review_file.write_text('{"schema_version": 1}', encoding="utf-8")

    def fake_command(arguments: list[str | Path]):
        if arguments[0] == dub_pipeline.FFMPEG:
            Path(arguments[-1]).write_bytes(b"encoded audio")
            return SimpleNamespace(stdout="")
        if "-show_entries" in arguments:
            return SimpleNamespace(stdout='{"format": {"duration": "5.0"}}')
        return SimpleNamespace(
            stdout='{"streams": [{"codec_type": "video", "codec_name": "av1"}]}'
        )

    monkeypatch.setattr(dub_pipeline, "_command", fake_command)

    delivery_dir = tmp_path / "episode-02-delivery"
    delivery_video = publish_delivery(
        source_segment,
        video,
        chinese_wav,
        chinese_srt,
        english_srt,
        chinese_json,
        delivery_dir,
        "episode-02",
        0.98,
        1.05,
        "ocr",
        "qwen3-vl:4b",
        "gpt-sovits",
        dub_pipeline.APPROVED_REFERENCE_AUDIO,
        review_file,
    )

    manifest = json.loads(
        (delivery_dir / "metadata" / "manifest.json").read_text(encoding="utf-8")
    )
    checksums = (delivery_dir / "metadata" / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert delivery_video == (
        delivery_dir / "video" / "episode-02.dual-audio.bilingual-subtitles.mp4"
    )
    assert (delivery_dir / "audio" / "episode-02.zh-CN.dub.m4a").exists()
    assert (delivery_dir / "audio" / "episode-02.en.original.m4a").exists()
    assert (delivery_dir / "subtitles" / "episode-02.zh-CN.srt").exists()
    assert (delivery_dir / "subtitles" / "episode-02.en.srt").exists()
    assert (delivery_dir / "metadata" / "episode-02.review-overrides.json").exists()
    assert manifest["episode"] == 2
    assert manifest["video"]["subtitle_tracks"][1]["language"] == "eng"
    assert "video/episode-02.dual-audio.bilingual-subtitles.mp4" in checksums
    assert "metadata/manifest.json" in checksums
