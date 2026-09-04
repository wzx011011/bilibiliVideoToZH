"""队列可靠性回归测试:声纹窗口 carry、翻译批次校验、审查覆盖率、
租约所有权、恢复/取消语义、子进程取消与编码。

背景(2026-08 队列大面积失败复盘):
  - jensen-huang-nvidia: diarize carry 嵌套列表 TypeError
  - ian-silber-openai:  GBK 控制台打印 ✓ UnicodeEncodeError
  - sam/yann/demis/fei-fei: 翻译批次错位 → 审查大量 MISMATCH
  - dario-anthropic-452: 审查 6h 超时无可靠检查点
  - naval/elon-war: 代理心跳超时后状态悬挂
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
VC = Path(__file__).resolve().parents[1] / "work" / "voice-clone-demo"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(VC))

import pipeline_admin as pa
import diarize_core
import audit_translation
import translate_fine_batches as tf


def _slot(i, start, end, text="hello"):
    return {"id": i, "start": start, "end": end,
            "duration": round(end - start, 2), "text": text,
            "speaker": "A"}


# ======================== diarize_core ========================

def test_build_windows_split_on_gap_and_length():
    slots = [_slot(0, 0, 3), _slot(1, 3, 6),
             _slot(2, 20, 24),                       # gap>2s → 切窗
             _slot(3, 24, 38)]                       # 超过 12s → 自成窗
    ws = diarize_core.build_windows(slots)
    assert [[s["id"] for s in w] for w in ws] == [[0, 1], [2], [3]]


def test_label_windows_carry_flattens_slots_not_windows():
    """首窗低置信进 carry 后,写回必须逐槽展开(jensen 崩溃回归)。"""
    def classify(w):
        if w[0]["id"] == 0:
            return "B", 0.01  # 低置信且无前窗 → carry
        return "A", 0.30
    slots = [_slot(i, i * 10, i * 10 + 5) for i in range(4)]
    windows = [[s] for s in slots]
    stats = diarize_core.label_windows(windows, classify)
    assert [s["speaker"] for s in slots] == ["A", "A", "A", "A"]
    assert all(s["relabel_evidence"] == "campplus-window" for s in slots)
    assert stats == {"A": 20.0}


def test_label_windows_eof_carry_gets_fallback():
    """整段开头低置信且再无高置信窗:EOF 兜底默认说话人,不留悬空槽。"""
    slots = [_slot(i, i * 10, i * 10 + 5) for i in range(3)]
    windows = [[s] for s in slots]
    diarize_core.label_windows(windows, lambda w: ("B", 0.001))
    assert [s["speaker"] for s in slots] == ["A", "A", "A"]
    assert all(s["relabel_evidence"].endswith("-eof") for s in slots)


def test_label_windows_low_conf_inherits_prev():
    slots = [_slot(i, i * 10, i * 10 + 5) for i in range(3)]
    windows = [[s] for s in slots]
    verdicts = {0: ("A", 0.5), 1: ("B", 0.01), 2: ("A", 0.5)}
    diarize_core.label_windows(windows, lambda w: verdicts[w[0]["id"]])
    assert [s["speaker"] for s in slots] == ["A", "A", "A"]


# ======================== 翻译批次校验 ========================

def test_validate_batch_accepts_exact_match():
    assert tf.validate_batch({1: "好", 2: "可以"}, [1, 2]) == ""


def test_validate_batch_rejects_missing_and_extra_ids():
    assert "ID 不匹配" in tf.validate_batch({1: "好"}, [1, 2])
    assert "ID 不匹配" in tf.validate_batch({1: "好", 2: "行", 3: "多"}, [1, 2])


def test_validate_batch_rejects_empty_translation():
    assert "空译文" in tf.validate_batch({1: "好", 2: "   "}, [1, 2])
    assert tf.validate_batch({1: None}, [1]) != ""


# ======================== 审查报告汇总 ========================

def test_compute_summary_counts_exclude_summary_key():
    result = {"0": {"verdict": "MATCH"}, "1": {"verdict": "MISMATCH"},
              audit_translation.SUMMARY_KEY: {"mode": "sample"}}
    s = audit_translation.compute_summary(result, ["0", "1", "2"],
                                          ["0", "1", "2"], "full")
    assert s["counts"] == {"MATCH": 1, "MISMATCH": 1}
    assert s["mismatch"] == 1
    assert not s["complete"]  # 缺槽 2


def test_compute_summary_sample_mode_only_needs_sampled_keys():
    result = {"0": {"verdict": "MATCH"}, "2": {"verdict": "MATCH"}}
    s = audit_translation.compute_summary(result, [str(i) for i in range(4)],
                                          ["0", "2"], "sample")
    assert s["complete"] and s["covered"] == 2 and s["needed"] == 2


def test_compute_summary_full_escalation_partial_report_not_complete():
    """全量升级中途:抽样集虽全覆盖,但按全量目标算 complete 必须为 False。"""
    result = {str(i): {"verdict": "MATCH"} for i in range(4)}  # 仅抽样集
    s = audit_translation.compute_summary(result, [str(i) for i in range(8)],
                                          [str(i) for i in range(8)], "partial")
    assert not s["complete"]
    assert s["covered"] == 4 and s["needed"] == 8


# ======================== 译文覆盖校验 ========================

def test_validate_zh_coverage():
    slots = [_slot(0, 0, 2), _slot(1, 2, 4)]
    assert pa._validate_zh_coverage({"0": "好", "1": "行"}, slots) == ""
    assert "缺 1 槽" in pa._validate_zh_coverage({"0": "好"}, slots)
    assert "残留" in pa._validate_zh_coverage({"0": "好", "1": "行", "9": "旧"},
                                              slots)
    assert "空译文" in pa._validate_zh_coverage({"0": " ", "1": "行"}, slots)


# ======================== 租约所有权 ========================

@pytest.fixture()
def studio_env(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "STATE_DIR", tmp_path / "tasks")
    monkeypatch.setattr(pa, "STUDIO", tmp_path)
    monkeypatch.setattr(pa, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pa, "ACTIVE_PATH", tmp_path / "active.json")
    monkeypatch.setattr(pa, "AGENT_STATE_PATH", tmp_path / "agent-state.json")
    return tmp_path


def _mk_queued_task(slug="t1"):
    t = pa.Task("en_vtt_1", {"slug": slug, "source_path": "x.mp4",
                             "vtt_path": "a.vtt"})
    t.save()
    return t


def test_claim_returns_task_with_lease_token(studio_env):
    t = _mk_queued_task()
    got, token = pa.agent_claim_task("pc1")
    assert got and got.id == t.id and token
    assert pa._read_active().get("token") == token
    # 租约新鲜:第二个代理领不到
    assert pa.agent_claim_task("pc2") == (None, None)


def test_lease_token_guards_heartbeat_and_release(studio_env):
    t = _mk_queued_task()
    _, token = pa.agent_claim_task("pc1")
    assert not pa.agent_heartbeat(t.id, "wrong-token")
    assert pa.agent_heartbeat(t.id, token)
    # 错 token 不能释放别人的锁
    pa.agent_release(t.id, "wrong-token")
    assert pa._read_active().get("task_id") == t.id
    pa.agent_release(t.id, token)
    assert pa._read_active() == {}


def test_claim_reclaims_expired_lease_and_requeues(studio_env):
    t = _mk_queued_task()
    _, token = pa.agent_claim_task("pc1")
    # 模拟代理失联:心跳拨回 2 小时前
    act = pa._read_active()
    import datetime
    act["heartbeat"] = (datetime.datetime.now()
                        - datetime.timedelta(hours=2)).isoformat()
    pa._write_json(pa.ACTIVE_PATH, act)
    t.mark_stage("extract_audio", pa.P_RUNNING)
    # 回收后同一任务重新排队(无人值守,不需要人点重试)
    got2, token2 = pa.agent_claim_task("pc2")
    assert got2 and got2.id == t.id
    reloaded = pa.load_task(t.id)
    assert reloaded.status == pa.S_RUNNING
    interrupted = next(s for s in reloaded.stages
                       if s["key"] == "extract_audio")
    assert interrupted["status"] == pa.P_PENDING
    assert token2 != token


def test_claim_converts_queued_cancel_to_canceled(studio_env):
    t = _mk_queued_task()
    t.cancel_requested = True
    t.save()
    got, _ = pa.agent_claim_task("pc1")
    assert got is None
    assert pa.load_task(t.id).status == pa.S_CANCELED


def test_claim_self_heals_zombie_running_with_no_pending(studio_env):
    t = _mk_queued_task()
    for s in t.stages:
        s["status"] = pa.P_DONE
    t.save()  # 全 done 但状态 running
    got, _ = pa.agent_claim_task("pc1")
    assert got is None
    assert pa.load_task(t.id).status == pa.S_DONE


def test_corrupt_active_json_is_reclaimable(studio_env):
    t = _mk_queued_task()
    pa.ACTIVE_PATH.write_text('{"task_id": "x", "heartbeat": "not-a-date"}',
                              encoding="utf-8")
    got, _ = pa.agent_claim_task("pc1")
    assert got and got.id == t.id


# ======================== 恢复/取消语义 ========================

def test_normalize_resets_stale_running_and_failed(studio_env):
    t = _mk_queued_task()
    t.mark_stage("ensure_source", pa.P_DONE)
    t.mark_stage("extract_audio", pa.P_RUNNING)   # 中断残留
    t.mark_stage("en_slots", pa.P_FAILED, error="x")
    idx = pa._normalize_for_run(t)
    assert idx == 1  # 从残留处续跑
    assert [s["status"] for s in t.stages[:3]] == \
        [pa.P_DONE, pa.P_PENDING, pa.P_PENDING]


def test_retry_on_stale_running_failure_requeues(studio_env, monkeypatch):
    t = _mk_queued_task()
    t.mark_stage("ensure_source", pa.P_RUNNING)
    t.status = pa.S_FAILED
    t.save()
    monkeypatch.setattr(pa, "MODE", "server")  # 不起本地线程
    assert pa.retry_stage(t)
    reloaded = pa.load_task(t.id)
    assert reloaded.status == pa.S_RUNNING
    assert reloaded.stages[0]["status"] == pa.P_PENDING
    assert reloaded.current == 0


def test_reclaim_rejects_when_lease_fresh_allows_when_stale(studio_env,
                                                            monkeypatch):
    monkeypatch.setattr(pa, "MODE", "server")  # 不起本地 runner 线程
    t = _mk_queued_task()
    _, token = pa.agent_claim_task("pc1")
    assert not pa.reclaim_task(t)  # 租约新鲜 → 拒绝
    act = pa._read_active()
    act["heartbeat"] = "2000-01-01T00:00:00"
    pa._write_json(pa.ACTIVE_PATH, act)
    assert pa.reclaim_task(t)
    reloaded = pa.load_task(t.id)
    assert reloaded.status == pa.S_RUNNING


def test_retranslate_only_for_audit_failures(studio_env, monkeypatch):
    t = _mk_queued_task("tret")
    for s in t.stages:
        if s["key"] in ("ensure_source", "extract_audio", "en_slots",
                        "translate"):
            s["status"] = pa.P_DONE
        elif s["key"] == "audit_translation":
            s["status"] = pa.P_FAILED
    t.status = pa.S_FAILED
    t.save()
    w = t.dir / "work"
    w.mkdir(parents=True, exist_ok=True)
    (w / "slots_zh.json").write_text("{}", encoding="utf-8")
    (w / "audit_translation.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pa, "MODE", "server")
    assert pa.retranslate_task(t)
    reloaded = pa.load_task(t.id)
    assert reloaded.current == 3  # translate 下标
    assert reloaded.stages[3]["status"] == pa.P_PENDING
    assert not (w / "slots_zh.json").exists()
    assert not (w / "audit_translation.json").exists()


# ======================== 子进程执行 ========================

def _run_task_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "STATE_DIR", tmp_path / "tasks")
    t = pa.Task("en_vtt_1", {"slug": "trun", "source_path": "x.mp4",
                             "vtt_path": "a.vtt"})
    t.save()
    return t


def test_run_reports_stderr_tail_and_nonzero_exit(tmp_path, monkeypatch):
    t = _run_task_stub(tmp_path, monkeypatch)
    cmd = [sys.executable, "-c",
           "import sys; print('boom-detail', file=sys.stderr); sys.exit(3)"]
    with pytest.raises(RuntimeError) as ei:
        pa._run(cmd, t, timeout=60)
    assert "exit 3" in str(ei.value)
    assert "boom-detail" in str(ei.value)


def test_run_utf8_child_output_survives_gbk_console(tmp_path, monkeypatch):
    t = _run_task_stub(tmp_path, monkeypatch)
    cmd = [sys.executable, "-c", "print('[OK] 中文+符号')"]
    out = pa._run(cmd, t, timeout=60)
    assert "中文" in out


def test_run_kills_process_on_cancel(tmp_path, monkeypatch):
    t = _run_task_stub(tmp_path, monkeypatch)
    t.cancel_requested = True  # 直接置位:_poll_cancel 首查对象属性
    cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
    t0 = time.time()
    with pytest.raises(pa.StageCanceled):
        pa._run(cmd, t, timeout=600)
    assert time.time() - t0 < 30


def test_run_timeout_kills_and_reports(tmp_path, monkeypatch):
    t = _run_task_stub(tmp_path, monkeypatch)
    cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
    with pytest.raises(RuntimeError) as ei:
        pa._run(cmd, t, timeout=3)
    assert "超时" in str(ei.value)
