"""pipeline_admin v2 单测:类型路由矩阵、任务模型、文本切块、SRT 解析。"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import pipeline_admin as pa


# ======================== 类型路由矩阵 ========================

def test_all_type_combinations_route_to_legal_workflows():
    """每个类型:阶段序列非空、标签齐全、每个阶段有执行器、渲染在最后。"""
    for key, t in pa.VIDEO_TYPES.items():
        stages = t["stages"]
        assert stages and stages[-1] == "render", key
        for s in stages:
            assert s in pa.EXECUTORS, f"{key}/{s} 缺执行器"
            assert s in pa.STAGE_LABELS, f"{key}/{s} 缺标签"
        # 五件套闭合:产物槽被阶段覆盖(zh_hard 无英文字幕槽除外)
        dims = t["dims"]
        has_en = dims["subtitle"] != "zh_hard"
        assert has_en == ("en_slots" in stages), key


def test_type_matrix_covers_declared_dimensions():
    combos = {(t["dims"]["subtitle"], t["dims"]["speakers"])
              for t in pa.VIDEO_TYPES.values()}
    assert combos == {("en_vtt", 1), ("en_vtt", 2), ("none", 1),
                      ("none", 2), ("zh_hard", 1)}


def test_none_2_podcast_workflow():
    """无字幕多人播客版:语义段+精修+props 在渲染前,Remotion 渲染默认。"""
    t = pa.VIDEO_TYPES["none_2_podcast"]
    s = t["stages"]
    assert s.index("en_slots") < s.index("align_speakers") < \
        s.index("translate") < s.index("narration_runs") < \
        s.index("gen_audio") < s.index("polish_audio") < \
        s.index("podcast_props") < s.index("render")
    assert "assemble_audio" not in s and "assemble_narration" not in s
    assert t["dims"] == {"subtitle": "none", "speakers": 2, "mode": "podcast"}
    assert t["default_render"] == "podcast_remotion"
    anchors = next(f for f in t["params"] if f["key"] == "anchors")
    assert anchors["required"]
    vtt = next(f for f in t["params"] if f["key"] == "vtt_path")
    assert not vtt["required"]  # 可选:无则 whisper 转写


def test_zh_hard_workflow_skips_translation_and_audio_extract():
    t = pa.VIDEO_TYPES["zh_hard_1"]
    assert "translate" not in t["stages"]
    assert "extract_audio" not in t["stages"]
    assert "assemble_audio" not in t["stages"]  # gen_audio 直接 concat
    assert t["default_render"] == "cover"
    assert pa.VIDEO_TYPES["en_vtt_2"]["default_render"] == "original"


# ======================== 任务模型 ========================

def _mk_task(tmp_path, monkeypatch, type_key="en_vtt_1", params=None):
    monkeypatch.setattr(pa, "STATE_DIR", tmp_path)
    monkeypatch.setattr(pa, "STUDIO", tmp_path.parent)
    p = {"slug": "t1", "source_path": "x.mp4",
         "vtt_path": "a.vtt", **(params or {})}
    return pa.Task(type_key, p)


def test_task_artifacts_have_all_five_slots(tmp_path, monkeypatch):
    task = _mk_task(tmp_path, monkeypatch)
    assert set(task.artifacts) == set(pa.ARTIFACT_SLOTS)
    assert all(v["status"] == "pending" for v in task.artifacts.values())


def test_task_json_roundtrip(tmp_path, monkeypatch):
    task = _mk_task(tmp_path, monkeypatch)
    task.save()
    loaded = pa.Task.load(task.json_path)
    assert loaded.type == task.type
    assert [s["key"] for s in loaded.stages] == \
        [s["key"] for s in task.stages]
    assert loaded.stages[0]["key"] == "ensure_source"


def test_legacy_schema_tasks_filtered(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "STATE_DIR", tmp_path)
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"schema": 1, "id": "x"}), encoding="utf-8")
    assert pa.list_tasks() == []  # 不崩、跳过


def test_run_task_mock_stages(tmp_path, monkeypatch):
    """状态机端到端(mock 执行器,含产物落槽与失败重试)。"""
    monkeypatch.setattr(pa, "STATE_DIR", tmp_path)
    monkeypatch.setattr(pa, "STUDIO", tmp_path.parent)
    calls = []

    def ok(task):
        calls.append("ensure")
        task.set_artifact("source_video", _touch(tmp_path / "src.mp4"))
        return "ok"

    def bad(task):
        raise RuntimeError("boom")

    # 先注册 mock 类型(2 阶段),再构造任务(stages 按类型展开)
    monkeypatch.setitem(pa.VIDEO_TYPES, "mock", dict(
        pa.VIDEO_TYPES["en_vtt_1"], stages=["ensure_source", "render"]))
    monkeypatch.setitem(pa.EXECUTORS, "ensure_source", ok)
    monkeypatch.setitem(pa.EXECUTORS, "render", bad)
    task = pa.Task("mock", {"slug": "t1", "source_path": "x.mp4"})
    task.save()

    pa.run_task(task)
    assert task.status == pa.S_FAILED
    assert task.artifacts["source_video"]["status"] == "done"
    assert task.artifacts["source_video"]["local_path"]

    monkeypatch.setitem(pa.EXECUTORS, "render", lambda t: "fixed")
    assert pa.retry_stage(task)
    _wait_terminal(task)
    assert task.status == pa.S_DONE and calls == ["ensure"]


def _wait_terminal(task, timeout=5.0):
    deadline = time.time() + timeout
    while task.status not in (pa.S_DONE, pa.S_FAILED) and time.time() < deadline:
        time.sleep(0.05)


def _touch(p: Path) -> Path:
    p.write_bytes(b"x" * 1024)
    return p


def test_set_artifact_upload_failure_not_blocking(tmp_path, monkeypatch):
    task = _mk_task(tmp_path, monkeypatch)
    task.save()

    def boom(slot, path):
        raise RuntimeError("ssh down")

    monkeypatch.setattr(task, "upload_to_nas", boom)
    path = _touch(tmp_path / "a.wav")
    task.set_artifact("zh_audio", path)  # 不应抛
    assert task.artifacts["zh_audio"]["status"] == "done"
    assert task.artifacts["zh_audio"]["nas_path"] is None


# ======================== 文本处理 ========================

def test_parse_srt_roundtrip(tmp_path):
    srt = tmp_path / "t.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,500\n你好 世界\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\n第二句\n", encoding="utf-8")
    cues = pa._parse_srt(srt)
    assert len(cues) == 2
    assert abs(cues[0][0] - 1.0) < 0.01 and abs(cues[0][1] - 3.5) < 0.01
    assert cues[1][2] == "第二句"


def test_cut_items_dual_cap(tmp_path, monkeypatch):
    """OCR 切块:条数+字符双上限,ep-22 教训的纯文本版。"""
    task = _mk_task(tmp_path, monkeypatch, "zh_hard_1")
    w = tmp_path.parent / "t1" / "work"
    w.mkdir(parents=True, exist_ok=True)
    # 200 条 × 30 字 = 6000 字 → 至少 3 块(3000 上限)
    (w / "x-ocr.srt").write_text(
        "\n\n".join(f"{i+1}\n00:00:{i%60:02d},000 --> 00:00:{(i+1)%60:02d},000\n"
                    + "字" * 30 for i in range(200)), encoding="utf-8")
    note = pa.ex_cut_items(task)
    items = json.loads((w / "items.json").read_text(encoding="utf-8"))
    assert len(items) >= 3
    assert all(len(i["text"]) <= 3200 for i in items)
    assert sum(len(i["text"]) for i in items) >= 5800  # 内容不丢
    assert "块" in note
