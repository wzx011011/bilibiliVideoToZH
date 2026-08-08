"""Local loopback bridge between the browser extension and episode builder.

The extension cannot launch local processes directly. This service accepts one
strictly validated, idempotent build request, stores the send record, and starts
``make_episode.py --step audio`` in a detached worker process (harvest + concat only;
ASR subtitle and video render are run manually via --step subtitle / --step video).

Only fixed repository paths and commands are used. The HTTP server listens on
127.0.0.1 and accepts browser requests only from extension origins.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = Path(__file__).resolve().parent
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765
BRIDGE_SERVICE = "doubao-build-bridge"
BRIDGE_VERSION = 1
BRIDGE_DIR = ROOT / "work" / "doubao-bridge"
JOBS_DIR = BRIDGE_DIR / "jobs"
PID_FILE = BRIDGE_DIR / "bridge.pid"
BRIDGE_LOG = BRIDGE_DIR / "bridge.log"
MAX_REQUEST_BYTES = 256 * 1024
JOB_STARTING_SECONDS = 5 * 60
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
TOTAL_EPISODES = 23


def _file_mb(path: Path) -> float:
    try:
        return round(path.stat().st_size / 1048576, 1) if path.is_file() else 0
    except OSError:
        return 0


def scan_pipeline_status() -> dict:
    """扫描所有集的流水线状态，基于文件存在性判断。"""
    episodes = []
    video_done = audio_done = subtitle_done = 0

    for ep in range(1, TOTAL_EPISODES + 1):
        ep_s = f"{ep:02d}"
        work_dir = ROOT / "work" / f"ep-{ep_s}"
        chunks_dir = work_dir / "chunks"
        srt_src = ROOT / "subtitles" / f"episode-{ep_s}.zh-CN.srt"
        manifest = chunks_dir / "manifest.json"
        send_record = work_dir / "doubao-send.json"
        audio_mp3 = work_dir / f"episode-{ep_s}-audio.mp3"
        asr_srt = work_dir / f"episode-{ep_s}-asr.srt"
        video_mp4 = ROOT / "videos" / f"episode-{ep_s}.mp4"

        stages = {
            "subtitle_source": srt_src.is_file(),
            "prep": manifest.is_file(),
            "sent": send_record.is_file(),
            "audio": audio_mp3.is_file(),
            "subtitle": asr_srt.is_file(),
            "video": video_mp4.is_file(),
        }

        sizes = {
            "audio_mb": _file_mb(audio_mp3),
            "subtitle_mb": _file_mb(asr_srt),
            "video_mb": _file_mb(video_mp4),
        }

        chunks_info = {"total": 0, "harvested": 0}
        if manifest.is_file():
            try:
                m = load_json(manifest)
                chunks_info = {
                    "total": len(m.get("chunks", [])),
                    "harvested": len(m.get("harvested_chunks", [])),
                }
            except (OSError, ValueError):
                pass

        if stages["video"]:
            video_done += 1
        if stages["audio"]:
            audio_done += 1
        if stages["subtitle"]:
            subtitle_done += 1

        episodes.append({
            "episode": ep,
            "stages": stages,
            "sizes": sizes,
            "chunks": chunks_info,
        })

    # 正在运行的 job
    running = []
    try:
        for job_file in JOBS_DIR.glob("*.json"):
            job = load_json(job_file)
            if job.get("status") in ("queued", "running"):
                running.append({
                    "job_id": job.get("job_id"),
                    "episode": job.get("episode"),
                    "status": job.get("status"),
                })
    except OSError:
        pass

    return {
        "episodes": episodes,
        "summary": {
            "total": TOTAL_EPISODES,
            "video_done": video_done,
            "audio_done": audio_done,
            "subtitle_done": subtitle_done,
        },
        "running": running,
    }
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,100}$")
READER_CREDENTIALS = {
  "DOUBAO_COOKIE",
  "DOUBAO_API_APP_KEY",
  "DOUBAO_DEVICE_ID",
  "DOUBAO_UID",
  "DOUBAO_WEB_TAB_ID",
}
BASE_PYTHON = Path(r"C:\Python311\python.exe")
VENV_PYTHON = ROOT / "work" / ".venv-ocr" / "Scripts" / "python.exe"
VENV_SITE = ROOT / "work" / ".venv-ocr" / "Lib" / "site-packages"

_job_lock = Lock()


class BridgeRequestError(ValueError):
    """A client-visible request validation error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def javascript_fingerprint(text: str) -> str:
    """Return the FNV-1a fingerprint used by sender-core.js."""
    value = str(text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    units = value.encode("utf-16-le", errors="surrogatepass")
    result = 2166136261
    for offset in range(0, len(units), 2):
        code_unit = units[offset] | (units[offset + 1] << 8)
        result ^= code_unit
        result = (result * 16777619) & 0xFFFFFFFF
    return f"{result:08x}:{len(units) // 2}"


def conversation_id_from_url(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "https" or parsed.hostname != "www.doubao.com":
        raise BridgeRequestError("conversation_url 不是豆包 HTTPS 对话地址")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "chat" or not CONVERSATION_ID_RE.fullmatch(parts[1]):
        raise BridgeRequestError("conversation_url 缺少有效会话 ID")
    return parts[1]


def _require_iso(value: object, field: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise BridgeRequestError(f"{field} 不是有效 ISO 时间") from error
    if parsed.tzinfo is None:
        raise BridgeRequestError(f"{field} 必须包含时区")
    return text


def _parse_iso_epoch(value: str) -> float:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def credential_status(root: Path = ROOT) -> tuple[bool, list[str]]:
    """Check credential names without returning any secret values."""
    values = {key: os.environ.get(key, "").strip() for key in READER_CREDENTIALS}
    env_path = root / ".env"
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key in READER_CREDENTIALS and not values[key]:
                    values[key] = value.strip().strip('"').strip("'").strip()
        except (OSError, UnicodeError):
            pass
    missing = sorted(key for key, value in values.items() if not value)
    return not missing, missing


def validate_build_request(payload: object, root: Path = ROOT) -> dict:
    """Validate a request and return a secret-free send record."""
    if not isinstance(payload, dict):
        raise BridgeRequestError("请求正文必须是 JSON 对象")
    if payload.get("credentials"):
        raise BridgeRequestError("构建请求不接受凭据，请先将扩展凭据复制到项目 .env")

    run_id = str(payload.get("run_id") or "")
    if not JOB_ID_RE.fullmatch(run_id):
        raise BridgeRequestError("run_id 格式无效")

    episode = payload.get("episode")
    if not isinstance(episode, int) or isinstance(episode, bool) or not 1 <= episode <= 999:
        raise BridgeRequestError("episode 必须是 1 到 999 的整数")

    if payload.get("status") != "completed":
        raise BridgeRequestError("只有已完成的发送队列可以构建")

    conversation_url = str(payload.get("conversation_url") or "")
    conversation_id = conversation_id_from_url(conversation_url)
    started_at = _require_iso(payload.get("started_at"), "started_at")
    completed_at = _require_iso(payload.get("completed_at"), "completed_at")
    started_epoch = _parse_iso_epoch(started_at)
    completed_epoch = _parse_iso_epoch(completed_at)
    if completed_epoch < started_epoch:
        raise BridgeRequestError("completed_at 早于 started_at")

    chunks_dir = root / "work" / f"ep-{episode:02d}" / "chunks"
    manifest_path = chunks_dir / "manifest.json"
    if not manifest_path.is_file():
        raise BridgeRequestError(f"第 {episode} 集尚未执行 prep")
    manifest = load_json(manifest_path)
    if manifest.get("episode") not in (None, episode):
        raise BridgeRequestError("请求集数与本地 manifest 不一致")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise BridgeRequestError("本地 manifest 没有有效 chunks")
    if manifest.get("total_chunks") not in (None, len(chunks)):
        raise BridgeRequestError("manifest total_chunks 与 chunks 数量不一致")

    items = payload.get("items")
    if not isinstance(items, list) or len(items) != len(chunks):
        raise BridgeRequestError("发送记录数量与本地 manifest 不一致")

    local_by_index = {chunk.get("chunk_index"): chunk for chunk in chunks}
    if len(local_by_index) != len(chunks):
        raise BridgeRequestError("本地 manifest 的 chunk_index 重复")

    validated_items = []
    seen_indices: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            raise BridgeRequestError("发送记录 item 必须是对象")
        index = item.get("chunk_index")
        if not isinstance(index, int) or isinstance(index, bool) or index in seen_indices:
            raise BridgeRequestError("发送记录的 chunk_index 无效或重复")
        local = local_by_index.get(index)
        if local is None:
            raise BridgeRequestError(f"本地 manifest 不包含分块 {index}")
        if item.get("status") != "done":
            raise BridgeRequestError(f"分块 {index} 未正常完成，不能自动构建")

        expected_name = str(local.get("txt_file") or "")
        name = str(item.get("name") or "")
        if name != expected_name:
            raise BridgeRequestError(f"分块 {index} 文件名与 manifest 不一致")
        txt_path = chunks_dir / expected_name
        if txt_path.parent != chunks_dir or not txt_path.is_file():
            raise BridgeRequestError(f"分块文件不存在: {expected_name}")

        local_fingerprint = javascript_fingerprint(txt_path.read_text(encoding="utf-8"))
        fingerprint = str(item.get("fingerprint") or "")
        if fingerprint != local_fingerprint:
            raise BridgeRequestError(f"分块 {index} 指纹与本地文件不一致")

        validated_items.append({
            "name": name,
            "chunk_index": index,
            "fingerprint": fingerprint,
            "status": "done",
            "sent_at": _require_iso(item.get("sent_at"), f"items[{index}].sent_at"),
            "reply_at": _require_iso(item.get("reply_at"), f"items[{index}].reply_at"),
            "error": None,
        })
        seen_indices.add(index)

    validated_items.sort(key=lambda item: item["chunk_index"])
    expected_indices = sorted(local_by_index)
    if [item["chunk_index"] for item in validated_items] != expected_indices:
        raise BridgeRequestError("发送记录没有完整覆盖本地分块")
    previous_sent = started_epoch - 1
    for item in validated_items:
        sent_epoch = _parse_iso_epoch(item["sent_at"])
        reply_epoch = _parse_iso_epoch(item["reply_at"])
        if sent_epoch < started_epoch - 120 or sent_epoch > completed_epoch + 120:
            raise BridgeRequestError(f"分块 {item['chunk_index']} 的发送时间超出队列范围")
        if reply_epoch < sent_epoch or reply_epoch > completed_epoch + 120:
            raise BridgeRequestError(f"分块 {item['chunk_index']} 的回复时间无效")
        if sent_epoch < previous_sent:
            raise BridgeRequestError("分块发送时间不是递增顺序")
        previous_sent = sent_epoch

    record = {
        "schema_version": 1,
        "run_id": run_id,
        "episode": episode,
        "status": "completed",
        "conversation_url": conversation_url,
        "conversation_id": conversation_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "total": len(validated_items),
        "items": validated_items,
        "validated_at": utc_now(),
    }
    return record


def python_command() -> str:
    if BASE_PYTHON.is_file():
        return str(BASE_PYTHON)
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    if VENV_SITE.is_dir():
        previous = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = str(VENV_SITE) + (os.pathsep + previous if previous else "")
    return environment


def public_job(job: dict) -> dict:
    allowed = {
        "job_id", "run_id", "episode", "status", "created_at", "started_at",
        "completed_at", "exit_code", "error", "pid", "log_file", "output_mp4",
    }
    return {key: job.get(key) for key in allowed if key in job}


def _process_is_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


def _job_is_stale(job: dict) -> bool:
    if job.get("status") not in {"queued", "running"}:
        return False
    try:
        created = _parse_iso_epoch(str(job.get("created_at")))
        age = time.time() - created
    except (TypeError, ValueError, OverflowError):
        return True
    if job.get("status") == "queued":
        return age > JOB_STARTING_SECONDS
    if job.get("status") == "running":
        pid = job.get("pid")
        if not pid:
            return age > JOB_STARTING_SECONDS
        return not _process_is_running(pid)
    return False


def _mark_job_stale(path: Path, job: dict) -> dict:
    job["status"] = "failed"
    job["completed_at"] = utc_now()
    job["error"] = "检测到上一次构建进程已失效，可重试"
    atomic_write_json(path, job)
    return job


def _active_job_for_episode(episode: int, exclude: str | None = None) -> dict | None:
    if not JOBS_DIR.is_dir():
        return None
    for path in JOBS_DIR.glob("*.json"):
        if exclude and path.stem == exclude:
            continue
        try:
            job = load_json(path)
        except (OSError, ValueError):
            continue
        if job.get("episode") != episode or job.get("status") not in {"queued", "running"}:
            continue
        if _job_is_stale(job):
            _mark_job_stale(path, job)
            continue
        return job
    return None


def _launch_job(job_path: Path) -> None:
    command = [python_command(), str(Path(__file__).resolve()), "_run-job", str(job_path)]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(
        command,
        cwd=ROOT,
        env=child_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=creation_flags,
    )


def enqueue_build(payload: object) -> tuple[dict, bool]:
    record = validate_build_request(payload)
    job_id = record["run_id"]
    job_path = JOBS_DIR / f"{job_id}.json"

    with _job_lock:
        if job_path.is_file():
            existing = load_json(job_path)
            if existing.get("status") != "failed":
                if _job_is_stale(existing):
                    _mark_job_stale(job_path, existing)
                else:
                    return existing, False
        active = _active_job_for_episode(record["episode"], exclude=job_id)
        if active:
            raise BridgeRequestError(
                f"第 {record['episode']} 集已有构建任务 {active.get('job_id')} 在运行"
            )

        record_path = ROOT / "work" / f"ep-{record['episode']:02d}" / "doubao-send.json"
        atomic_write_json(record_path, record)
        previous = load_json(job_path) if job_path.is_file() else {}
        job = {
            "schema_version": 1,
            "job_id": job_id,
            "run_id": job_id,
            "episode": record["episode"],
            "status": "queued",
            "created_at": utc_now(),
            "retried_at": utc_now() if previous else None,
            "started_at": None,
            "completed_at": None,
            "exit_code": None,
            "error": None,
            "pid": None,
            "record_file": str(record_path),
            "log_file": str(JOBS_DIR / f"{job_id}.log"),
            "output_mp4": str(ROOT / "videos" / f"episode-{record['episode']:02d}.mp4"),
        }
        atomic_write_json(job_path, job)
        try:
            _launch_job(job_path)
        except Exception:
            job["status"] = "failed"
            job["completed_at"] = utc_now()
            job["error"] = "无法启动本地构建进程，可重试"
            atomic_write_json(job_path, job)
        # The worker writes its own PID and running state. Avoid a parent/worker
        # write race here by leaving the already persisted queued state alone.
        return job, True


def _gen_job_id() -> str:
    return uuid.uuid4().hex[:16]


def enqueue_pipeline_job(episode: int, step: str) -> dict:
    """触发单集指定步骤（subtitle/video/audio/build），不带 send-record。"""
    job_id = f"pipe-{episode:02d}-{step}-{_gen_job_id()}"
    job_path = JOBS_DIR / f"{job_id}.json"

    with _job_lock:
        active = _active_job_for_episode(episode)
        if active:
            raise BridgeRequestError(
                f"第 {episode} 集已有任务 {active.get('job_id')} 在运行"
            )
        job = {
            "schema_version": 1,
            "job_id": job_id,
            "run_id": job_id,
            "episode": episode,
            "step": step,
            "status": "queued",
            "created_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "exit_code": None,
            "error": None,
            "pid": None,
            "log_file": str(JOBS_DIR / f"{job_id}.log"),
            "output_mp4": str(ROOT / "videos" / f"episode-{episode:02d}.mp4"),
        }
        atomic_write_json(job_path, job)
        try:
            _launch_job(job_path)
        except Exception:
            job["status"] = "failed"
            job["completed_at"] = utc_now()
            job["error"] = "无法启动进程，可重试"
            atomic_write_json(job_path, job)
        return job


def enqueue_batch_job(episodes: list, step: str) -> dict:
    """批量串行：写一个 batch job，worker 内部串行跑各集。"""
    episodes = [e for e in episodes if isinstance(e, int) and 1 <= e <= TOTAL_EPISODES]
    if not episodes:
        raise BridgeRequestError("没有有效的集数")

    job_id = f"batch-{step}-{_gen_job_id()}"
    job_path = JOBS_DIR / f"{job_id}.json"

    with _job_lock:
        # 检查这些集是否有正在运行的任务
        for ep in episodes:
            active = _active_job_for_episode(ep)
            if active:
                raise BridgeRequestError(
                    f"第 {ep} 集已有任务 {active.get('job_id')} 在运行"
                )
        job = {
            "schema_version": 1,
            "job_id": job_id,
            "run_id": job_id,
            "episode": episodes[0],
            "episodes": episodes,
            "step": step,
            "status": "queued",
            "created_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "exit_code": None,
            "error": None,
            "pid": None,
            "log_file": str(JOBS_DIR / f"{job_id}.log"),
            "output_mp4": "",
        }
        atomic_write_json(job_path, job)
        try:
            _launch_job(job_path)
        except Exception:
            job["status"] = "failed"
            job["completed_at"] = utc_now()
            job["error"] = "无法启动进程，可重试"
            atomic_write_json(job_path, job)
        return job


def run_job(job_path: Path) -> int:
    resolved = job_path.resolve()
    jobs_root = JOBS_DIR.resolve()
    if resolved.parent != jobs_root or not JOB_ID_RE.fullmatch(resolved.stem):
        raise SystemExit("invalid job path")

    job = load_json(resolved)
    job["status"] = "running"
    job["started_at"] = utc_now()
    job["pid"] = os.getpid()
    atomic_write_json(resolved, job)

    result_code = -1
    error_message = None
    try:
        step = job.get("step", "audio")
        episodes_list = job.get("episodes")  # batch job
        log_path = Path(job["log_file"])
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if episodes_list:
            # batch job：串行跑多集
            result_code = 0
            with log_path.open("w", encoding="utf-8", newline="\n") as log:
                for ep in episodes_list:
                    cmd = [
                        python_command(),
                        str(TOOL_DIR / "make_episode.py"),
                        "--episode", str(ep),
                        "--step", step,
                    ]
                    log.write(f"\n[{utc_now()}] EP{ep:02d} {step}: {' '.join(cmd)}\n")
                    log.flush()
                    r = subprocess.run(cmd, cwd=ROOT, env=child_environment(),
                                       stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, text=True, shell=False)
                    if r.returncode != 0:
                        result_code = r.returncode
                        error_message = f"EP{ep:02d} {step} 失败 (exit {r.returncode})"
                        break
                    log.write(f"[{utc_now()}] EP{ep:02d} {step} 完成\n")
        elif "record_file" in job and step == "audio":
            # 原有 build job（带 send-record）
            record_path = Path(job["record_file"])
            command = [
                python_command(),
                str(TOOL_DIR / "make_episode.py"),
                "--episode", str(job["episode"]),
                "--step", "audio",
                "--send-record", str(record_path),
            ]
            with log_path.open("w", encoding="utf-8", newline="\n") as log:
                log.write(f"[{utc_now()}] {' '.join(command)}\n")
                log.flush()
                result = subprocess.run(command, cwd=ROOT, env=child_environment(),
                                        stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=subprocess.STDOUT, text=True, shell=False)
            result_code = result.returncode
        else:
            # pipeline job（subtitle/video/audio/build，无 send-record）
            command = [
                python_command(),
                str(TOOL_DIR / "make_episode.py"),
                "--episode", str(job["episode"]),
                "--step", step,
            ]
            with log_path.open("w", encoding="utf-8", newline="\n") as log:
                log.write(f"[{utc_now()}] {' '.join(command)}\n")
                log.flush()
                result = subprocess.run(command, cwd=ROOT, env=child_environment(),
                                        stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=subprocess.STDOUT, text=True, shell=False)
            result_code = result.returncode
    except Exception:
        error_message = "worker 异常退出，查看日志或重试"

    try:
        job = load_json(resolved)
        job["exit_code"] = result_code
        job["completed_at"] = utc_now()
        output_path = Path(job["output_mp4"])
        if result_code == 0 and output_path.is_file() and output_path.stat().st_size > 0:
            job["status"] = "completed"
            job["error"] = None
        else:
            job["status"] = "failed"
            job["error"] = error_message or (
                f"构建进程退出码 {result_code}，查看日志获取详情"
            )
        atomic_write_json(resolved, job)
    except Exception:
        # There is no safe path left to persist a damaged job file.
        pass
    return result_code


def origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    if origin.startswith("chrome-extension://") or origin.startswith("edge-extension://"):
        return True
    # Allow same-origin dashboard (http://127.0.0.1:8765)
    return origin in ("http://127.0.0.1:8765", "http://localhost:8765")


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "DoubaoBridge/1.0"

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}", flush=True)

    def _authorized(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        if host not in {"127.0.0.1", "localhost"}:
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Host 被拒绝"})
            return False
        if not origin_allowed(self.headers.get("Origin")):
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Origin 被拒绝"})
            return False
        return True

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin_allowed(origin) and origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        if self.path in ("/dashboard", "/dashboard/"):
            dashboard_html = TOOL_DIR / "dashboard.html"
            if not dashboard_html.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "dashboard.html 不存在"})
                return
            body = dashboard_html.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/status":
            self._send_json(HTTPStatus.OK, {"ok": True, **scan_pipeline_status()})
            return
        if self.path == "/api/health":
            ready, missing = credential_status()
            self._send_json(HTTPStatus.OK, {
                "ok": True,
                "service": BRIDGE_SERVICE,
                "version": BRIDGE_VERSION,
                "credentials_ready": ready,
                "missing_credentials": missing,
            })
            return
        match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]{8,100})", self.path)
        if match:
            path = JOBS_DIR / f"{match.group(1)}.json"
            if not path.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "任务不存在"})
                return
            try:
                with _job_lock:
                    job = load_json(path)
                    if _job_is_stale(job):
                        job = _mark_job_stale(path, job)
            except (OSError, ValueError):
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {
                    "ok": False, "error": "任务状态损坏",
                })
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "job": public_job(job)})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "接口不存在"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return

        # /api/run — 触发单集指定步骤
        if self.path == "/api/run":
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "Content-Type 必须是 application/json"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(max(0, min(length, MAX_REQUEST_BYTES))).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "JSON 无效"})
                return
            episode = payload.get("episode")
            step = payload.get("step")
            if not isinstance(episode, int) or not (1 <= episode <= TOTAL_EPISODES):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "episode 无效"})
                return
            if step not in ("subtitle", "video", "audio", "build"):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "step 无效"})
                return
            try:
                job = enqueue_pipeline_job(episode, step)
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "job": job})
                return
            except BridgeRequestError as e:
                self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(e)})
                return

        # /api/batch — 批量串行
        if self.path == "/api/batch":
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "Content-Type 必须是 application/json"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(max(0, min(length, MAX_REQUEST_BYTES))).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "JSON 无效"})
                return
            step = payload.get("step")
            episodes = payload.get("episodes")
            if step not in ("subtitle", "video", "audio", "build") or not isinstance(episodes, list):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "参数无效"})
                return
            try:
                job = enqueue_batch_job(episodes, step)
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "job": job})
                return
            except BridgeRequestError as e:
                self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(e)})
                return

        if self.path != "/api/build":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "接口不存在"})
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {
                "ok": False, "error": "Content-Type 必须是 application/json",
            })
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {
                "ok": False, "error": "请求正文为空或过大",
            })
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            job, created = enqueue_build(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "JSON 无效"})
            return
        except BridgeRequestError as error:
            self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(error)})
            return
        except Exception as error:
            self.log_error("enqueue failed: %s", error)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "ok": False, "error": "本地构建服务内部错误",
            })
            return
        self._send_json(
            HTTPStatus.ACCEPTED if created else HTTPStatus.OK,
            {"ok": True, "created": created, "job": public_job(job)},
        )


def health_check(timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/health", timeout=timeout
        ) as response:
            if response.status != 200:
                return False
            data = json.loads(response.read().decode("utf-8"))
            return data.get("service") == BRIDGE_SERVICE and data.get("version") == BRIDGE_VERSION
    except (OSError, urllib.error.URLError, ValueError):
        return False


def serve() -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    PID_FILE.write_text(f"{os.getpid()}\n", encoding="ascii")
    print(f"豆包本地构建服务: http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/health", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        PID_FILE.unlink(missing_ok=True)


def start_background() -> int:
    if health_check():
        print(f"本地构建服务已运行: http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/health")
        return 0
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    command = [python_command(), str(Path(__file__).resolve()), "serve"]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    with BRIDGE_LOG.open("a", encoding="utf-8", newline="\n") as log:
        subprocess.Popen(
            command,
            cwd=ROOT,
            env=child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=creation_flags,
        )
    for _ in range(30):
        if health_check():
            print(f"本地构建服务已启动: http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/health")
            return 0
        time.sleep(0.1)
    print(f"[✗] 本地构建服务启动失败，查看 {BRIDGE_LOG}", file=sys.stderr)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="豆包扩展本地音频/视频构建桥接")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start", help="后台启动本地桥接服务")
    subparsers.add_parser("serve", help="前台运行本地桥接服务")
    runner = subparsers.add_parser("_run-job", help=argparse.SUPPRESS)
    runner.add_argument("job_file", type=Path)
    args = parser.parse_args()

    if args.command == "start":
        raise SystemExit(start_background())
    if args.command == "serve":
        serve()
        return
    raise SystemExit(run_job(args.job_file))


if __name__ == "__main__":
    main()
