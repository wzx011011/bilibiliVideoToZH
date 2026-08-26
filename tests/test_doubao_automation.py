"""Pure tests for the extension-to-build bridge and reply matching."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import doubao_bridge as bridge
import doubao_pipeline as pipeline
import make_episode as episode


def _fixture(tmp_path: Path, count: int = 2) -> tuple[Path, dict, list[dict]]:
    chunks_dir = tmp_path / "work" / "ep-03" / "chunks"
    chunks_dir.mkdir(parents=True)
    chunks = []
    items = []
    for index in range(1, count + 1):
        name = f"{index:02d}.txt"
        text = f"第 {index} 块课程提示词"
        (chunks_dir / name).write_text(text, encoding="utf-8")
        chunks.append({"chunk_index": index, "txt_file": name})
        items.append({
            "name": name,
            "chunk_index": index,
            "fingerprint": bridge.javascript_fingerprint(text),
            "status": "done",
            "sent_at": f"2026-08-05T00:0{index}:00Z",
            "reply_at": f"2026-08-05T00:0{index}:30Z",
            "error": None,
        })
    manifest = {
        "total_chunks": count,
        "chunks": chunks,
    }
    (chunks_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return chunks_dir, manifest, items


def _payload(items: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "run_id": "12345678-abcd-4abc-8abc-123456789abc",
        "episode": 3,
        "status": "completed",
        "conversation_url": "https://www.doubao.com/chat/38436626777215234",
        "started_at": "2026-08-05T00:00:00Z",
        "completed_at": "2026-08-05T00:03:00Z",
        "items": items,
    }


def test_javascript_fingerprint_matches_sender_core_utf16() -> None:
    assert bridge.javascript_fingerprint("课程字幕") == "223d5d5a:4"
    assert bridge.javascript_fingerprint("A😀中") == "40e1361c:4"
    assert episode._js_fingerprint("A😀中") == "40e1361c:4"


def test_validate_build_request_binds_to_local_manifest(tmp_path: Path) -> None:
    _, _, items = _fixture(tmp_path)
    record = bridge.validate_build_request(_payload(items), root=tmp_path)
    assert record["episode"] == 3
    assert record["conversation_id"] == "38436626777215234"
    assert [item["chunk_index"] for item in record["items"]] == [1, 2]
    assert "credentials" not in record


@pytest.mark.parametrize("mutation, message", [
    (lambda payload: payload["items"][0].update(status="skipped"), "未正常完成"),
    (lambda payload: payload["items"][0].update(fingerprint="bad:1"), "指纹"),
    (lambda payload: payload.update(conversation_url="https://example.com/chat/123"), "豆包"),
])
def test_validate_build_request_rejects_unsafe_or_incomplete_input(
    tmp_path: Path, mutation, message: str,
) -> None:
    _, _, items = _fixture(tmp_path)
    payload = _payload(items)
    mutation(payload)
    with pytest.raises(bridge.BridgeRequestError, match=message):
        bridge.validate_build_request(payload, root=tmp_path)


def test_validate_build_request_never_accepts_credentials(tmp_path: Path) -> None:
    _, _, items = _fixture(tmp_path)
    payload = _payload(items)
    payload["credentials"] = {"DOUBAO_COOKIE": "secret"}
    with pytest.raises(bridge.BridgeRequestError, match="凭据"):
        bridge.validate_build_request(payload, root=tmp_path)


def test_select_replies_uses_conversation_prompt_and_question_link(tmp_path: Path) -> None:
    chunks_dir, manifest, items = _fixture(tmp_path)
    record = _payload(items)
    record["conversation_id"] = "38436626777215234"
    first_text = (chunks_dir / "01.txt").read_text(encoding="utf-8")
    second_text = (chunks_dir / "02.txt").read_text(encoding="utf-8")
    replies = [
        {
            "message_id": "reply-2",
            "bot_reply_message_id": "question-2",
            "conversation_id": "38436626777215234",
            "question_text": second_text,
            "question_create_time": "2026-08-05T00:02:02Z",
            "create_time": "2026-08-05T00:02:05Z",
            "tts_content": "第二块处理结果。",
        },
        {
            "message_id": "wrong-conversation",
            "bot_reply_message_id": "question-x",
            "conversation_id": "other",
            "question_text": first_text,
            "question_create_time": "2026-08-05T00:01:01Z",
            "create_time": "2026-08-05T00:01:04Z",
            "tts_content": "错误会话。",
        },
        {
            "message_id": "reply-1",
            "bot_reply_message_id": "question-1",
            "conversation_id": "38436626777215234",
            "question_text": first_text,
            "question_create_time": "2026-08-05T00:01:02Z",
            "create_time": "2026-08-05T00:01:05Z",
            "tts_content": "第一块处理结果。",
        },
    ]
    selected = episode._select_replies(replies, manifest, chunks_dir, record)
    assert [reply["message_id"] for reply in selected] == ["reply-1", "reply-2"]
    assert [reply["bot_reply_message_id"] for reply in selected] == ["question-1", "question-2"]


def test_select_replies_rejects_ambiguous_duplicate_prompt(tmp_path: Path) -> None:
    chunks_dir, manifest, items = _fixture(tmp_path, count=1)
    record = _payload(items)
    record["conversation_id"] = "38436626777215234"
    record["completed_at"] = "2026-08-05T00:02:00Z"
    text = (chunks_dir / "01.txt").read_text(encoding="utf-8")
    base = {
        "bot_reply_message_id": "question-1",
        "conversation_id": "38436626777215234",
        "question_text": text,
        "question_create_time": "2026-08-05T00:01:02Z",
        "create_time": "2026-08-05T00:01:05Z",
        "tts_content": "结果。",
    }
    replies = [{**base, "message_id": "reply-1"}, {**base, "message_id": "reply-2"}]
    with pytest.raises(RuntimeError, match="不唯一"):
        episode._select_replies(replies, manifest, chunks_dir, record)


def test_select_replies_honors_record_reply_time_window(tmp_path: Path) -> None:
    chunks_dir, manifest, items = _fixture(tmp_path, count=1)
    record = _payload(items)
    record["conversation_id"] = "38436626777215234"
    text = (chunks_dir / "01.txt").read_text(encoding="utf-8")
    replies = [{
        "message_id": "reply-too-early",
        "bot_reply_message_id": "question-1",
        "conversation_id": "38436626777215234",
        "question_text": text,
        "question_create_time": "2026-08-05T00:01:02Z",
        "create_time": "2026-08-05T00:00:01Z",
        "tts_content": "valid text",
    }]
    with pytest.raises(RuntimeError, match="缺失"):
        episode._select_replies(replies, manifest, chunks_dir, record)


def test_stale_running_job_can_be_retried() -> None:
    old = datetime.now(timezone.utc) - timedelta(seconds=bridge.JOB_STARTING_SECONDS + 1)
    job = {
        "status": "running",
        "created_at": old.isoformat().replace("+00:00", "Z"),
        "pid": None,
    }
    assert bridge._job_is_stale(job)


def test_stale_queued_job_can_be_retried() -> None:
    old = datetime.now(timezone.utc) - timedelta(seconds=bridge.JOB_STARTING_SECONDS + 1)
    assert bridge._job_is_stale({
        "status": "queued",
        "created_at": old.isoformat().replace("+00:00", "Z"),
        "pid": None,
    })


def test_process_liveness_detects_current_and_exited_process() -> None:
    assert bridge._process_is_running(os.getpid())
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=5)
    assert not bridge._process_is_running(process.pid)


def test_epoch_normalizes_seconds_milliseconds_and_microseconds() -> None:
    expected = episode._epoch("2026-08-05T00:01:00Z")
    assert episode._epoch(expected) == pytest.approx(expected)
    assert episode._epoch(expected * 1000) == pytest.approx(expected)
    assert episode._epoch(expected * 1_000_000) == pytest.approx(expected)


def test_prep_records_episode_and_removes_stale_txt(tmp_path: Path) -> None:
    source = tmp_path / "episode-07.zh-CN.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n第一句\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n第二句\n",
        encoding="utf-8",
    )
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    (chunks_dir / "old.txt").write_text("old", encoding="utf-8")
    pipeline.cmd_prep(
        type("Args", (), {
            "srt": source,
            "chunks_dir": chunks_dir,
            "chunk_size": 1,
            "limit": None,
        })()
    )
    manifest = json.loads((chunks_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["episode"] == 7
    assert not (chunks_dir / "old.txt").exists()
    assert sorted(path.name for path in chunks_dir.glob("*.txt")) == ["01.txt", "02.txt"]


def test_bridge_http_health_and_origin_guard() -> None:
    server = bridge.ThreadingHTTPServer(("127.0.0.1", 0), bridge.BridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
        assert data["service"] == "doubao-build-bridge"

        blocked = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"Origin": "https://evil.example"},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(blocked, timeout=2)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_bridge_http_job_poll_reconciles_dead_worker(tmp_path: Path, monkeypatch) -> None:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(bridge, "JOBS_DIR", jobs_dir)
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=5)
    job_id = "dead-worker-1234"
    job_path = jobs_dir / f"{job_id}.json"
    bridge.atomic_write_json(job_path, {
        "job_id": job_id,
        "run_id": job_id,
        "episode": 3,
        "status": "running",
        "created_at": bridge.utc_now(),
        "pid": process.pid,
    })

    server = bridge.ThreadingHTTPServer(("127.0.0.1", 0), bridge.BridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/jobs/{job_id}",
            headers={"Origin": "edge-extension://abcdefghijklmnopabcdefghijklmnop"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
        assert data["job"]["status"] == "failed"
        assert bridge.load_json(job_path)["status"] == "failed"
    finally:
        server.shutdown()
        server.server_close()
