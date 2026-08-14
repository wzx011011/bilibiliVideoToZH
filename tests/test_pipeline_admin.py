"""pipeline_admin 单测:流水线定义完整性、manual 门检测、任务状态机端到端。"""
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


def _wait_terminal(task: pa.Task, timeout: float = 5.0) -> None:
    """等后台 runner 线程把任务带到终态(done/failed)。"""
    deadline = time.time() + timeout
    while task.status not in (pa.TASK_DONE, pa.TASK_FAILED) \
            and time.time() < deadline:
        time.sleep(0.05)


# ======================== 流水线定义完整性 ========================

def test_pipelines_define_all_three_types():
    assert set(pa.PIPELINES) == {"course", "interview_en", "interview_zh"}
    dims = {k: v["dims"] for k, v in pa.PIPELINES.items()}
    assert dims["course"] == {"lang": "zh", "subtitle_source": "ocr", "speakers": 1}
    assert dims["interview_en"] == {"lang": "en", "subtitle_source": "asr", "speakers": 2}
    assert dims["interview_zh"] == {"lang": "zh", "subtitle_source": "asr", "speakers": 2}


def test_every_auto_stage_has_executor():
    """每条流水线的每个 auto 阶段都能找到执行器(缺执行器=运行时必炸)。"""
    for key, pipe in pa.PIPELINES.items():
        group = pa.EXECUTORS["interview" if key.startswith("interview") else "course"]
        for st in pipe["stages"]:
            if st["type"] == "auto":
                assert st["key"] in group, f"{key}/{st['key']} 缺执行器"
            else:
                assert st["type"] == "manual"


def test_every_pipeline_has_send_stage_with_auto_executor():
    """发送环节默认全自动(Playwright),并有执行器。"""
    for key, pipe in pa.PIPELINES.items():
        sends = [s for s in pipe["stages"] if s["key"] == "send_chunks"]
        assert len(sends) == 1 and sends[0]["type"] == "auto", key
        group = pa.EXECUTORS["interview" if key.startswith("interview") else "course"]
        assert "send_chunks" in group, key


def test_fnv1a_fingerprint_matches_extension():
    """与 sender-core.js 的 fingerprint 算法一致(抽样对照 JS 实现手算值)。"""
    # JS: "你好" → 手动按 FNV-1a 逐字符算
    def js_fp(text):
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        return f"{h:08x}:{len(text)}"
    for sample in ("你好", "Hello world", "哈佛积极心理学第22讲字幕块" * 5):
        assert pa._fnv1a_fingerprint(sample) == js_fp(sample)


def test_send_mode_manual_keeps_gate(tmp_path, monkeypatch):
    """send_mode=manual 时发送环节仍走人工门(回退路径)。"""
    group = {"ensure": lambda t: "ok", "send_chunks": lambda t: "ok"}
    monkeypatch.setitem(pa.PIPELINES, "mock", dict(
        key="mock", name="m", desc="", dims={}, params=[],
        stages=[{"key": "send_chunks", "label": "发送", "type": "auto"}]))
    monkeypatch.setattr(pa, "executor_group", lambda t: group)
    monkeypatch.setattr(pa, "TASKS_DIR", tmp_path)
    monkeypatch.setattr(pa, "_ep_dir", lambda t: tmp_path)

    task = pa.Task("mock", "t", {"episode": 1, "send_mode": "manual"})
    task.save()
    pa.run_task(task)
    assert task.status == pa.TASK_WAITING  # 停在人工门,没自动发

    task2 = pa.Task("mock", "t2", {"episode": 1})  # 默认 auto
    pa.run_task(task2)
    assert task2.status == pa.TASK_DONE  # 直接自动完成


def test_unified_products_stages_present():
    """三条流水线都要产出到 asr_subtitle → render(统一产物:音频/字幕/视频)。"""
    for key, pipe in pa.PIPELINES.items():
        keys = [s["key"] for s in pipe["stages"]]
        assert "asr_subtitle" in keys and "render" in keys, key
        assert keys[-1] == "render"


# ======================== 发送记录检测 ========================

def _write_send_record(path: Path, status: str, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"status": status, "items": items}, ensure_ascii=False), encoding="utf-8")


def test_send_record_completed(tmp_path, monkeypatch):
    task = pa.Task("course", "t", {"episode": 22})
    monkeypatch.setattr(pa, "_ep_dir", lambda t: tmp_path)
    rec = tmp_path / "doubao-send.json"

    assert not pa.send_record_completed(task)  # 不存在
    _write_send_record(rec, "running", [{"status": "done"}, {"status": "pending"}])
    assert not pa.send_record_completed(task)  # 部分 done
    _write_send_record(rec, "completed",
                       [{"status": "done"}, {"status": "done"}])
    assert pa.send_record_completed(task)


def test_send_record_completed_interview_path(tmp_path, monkeypatch):
    task = pa.Task("interview_en", "t", {"slug": "musk"})
    monkeypatch.setattr(pa, "_iv_dir", lambda t: tmp_path)
    _write_send_record(tmp_path / "doubao-send.json", "completed",
                       [{"status": "done"}])
    assert pa.send_record_completed(task)


# ======================== 任务状态机(端到端,mock 执行器) ========================

def test_task_runs_to_manual_gate_and_completes(tmp_path, monkeypatch):
    """auto→manual 等待→手动确认→auto→完成 的完整状态流转。"""
    monkeypatch.setattr(pa, "TASKS_DIR", tmp_path)
    calls = []

    group = {
        "ensure_source": lambda t: calls.append("ensure_source") or "ok",
        "send_chunks": lambda t: None,
        "render": lambda t: calls.append("render") or "ok",
    }
    pipe = {"stages": [
        {"key": "ensure_source", "label": "准备", "type": "auto"},
        {"key": "send_chunks", "label": "发送", "type": "manual"},
        {"key": "render", "label": "渲染", "type": "auto"},
    ]}
    monkeypatch.setitem(pa.PIPELINES, "mock", dict(
        key="mock", name="mock", desc="", dims={}, params=[], **pipe))
    monkeypatch.setattr(pa, "EXECUTORS", {"interview": group, "course": group})
    monkeypatch.setattr(pa, "executor_group", lambda t: group)
    monkeypatch.setattr(pa, "_ep_dir", lambda t: tmp_path)  # 发送记录找不到 → 拒绝

    task = pa.Task("mock", "test", {"episode": 1})
    task.save()
    pa.run_task(task)  # 同步跑(auto→manual 停)

    assert task.status == pa.TASK_WAITING
    assert task.stages[0]["status"] == pa.STAGE_DONE
    assert task.stages[1]["status"] == pa.STAGE_WAITING
    assert calls == ["ensure_source"]

    # 未发送完成时 advance 应拒绝(无记录)
    assert not pa.advance_manual(task, force=False)
    # 手动确认 → 继续跑完(等后台线程到终态)
    assert pa.advance_manual(task, force=True)
    _wait_terminal(task)
    assert task.status == pa.TASK_DONE
    assert calls == ["ensure_source", "render"]


def test_task_failure_marks_stage_and_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "TASKS_DIR", tmp_path)

    def boom(task):
        raise RuntimeError("boom")

    group = {"bad": boom}
    monkeypatch.setitem(pa.PIPELINES, "mock", dict(
        key="mock", name="m", desc="", dims={}, params=[],
        stages=[{"key": "bad", "label": "坏", "type": "auto"}]))
    monkeypatch.setattr(pa, "executor_group", lambda t: group)

    task = pa.Task("mock", "t", {})
    pa.run_task(task)
    assert task.status == pa.TASK_FAILED
    assert "boom" in task.stages[0]["error"]

    # 修好执行器再重试
    group["bad"] = lambda t: "fixed"
    assert pa.retry_stage(task)
    _wait_terminal(task)
    assert task.status == pa.TASK_DONE


def test_task_json_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "TASKS_DIR", tmp_path)
    task = pa.Task("course", "EP22", {"episode": 22})
    task.save()
    loaded = pa.Task.load(task.json_path)
    assert loaded.id == task.id
    assert loaded.params == {"episode": 22}
    assert [s["key"] for s in loaded.stages] == \
        [s["key"] for s in pa.PIPELINES["course"]["stages"]]
