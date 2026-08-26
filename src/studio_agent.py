"""PC 执行代理 —— 轮询 NAS 控制面领任务,在本地跑重活(GPU/翻译/渲染)。

与 src/pipeline_admin.py 的 server 模式配对使用:
  NAS 容器(常开):网页 + 任务队列(唯一事实源)
  本代理(PC,开机自启):poll 领任务 → 逐阶段执行 EXECUTORS →
  状态/日志/产物上报;产物 scp 直达 NAS(控制面只记 nas_path)

用法:
  STUDIO_SERVER=http://192.168.100.78:8766 STUDIO_TOKEN=<token> \
    work/.venv-ocr/Scripts/python.exe src/studio_agent.py
  可选 STUDIO_POLL_SEC(默认 10)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SERVER = os.environ.get("STUDIO_SERVER", "http://192.168.100.78:8766")
TOKEN = os.environ.get("STUDIO_TOKEN", "")
POLL_SEC = int(os.environ.get("STUDIO_POLL_SEC", "10"))
AGENT_NAME = os.environ.get("COMPUTERNAME", "pc")

# local 模式的完整执行器(WSL GPU/ffmpeg/翻译都在 PC 本地)
import pipeline_admin as pa  # noqa: E402


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        SERVER + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "X-Agent-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


class AgentReporter:
    """替代 Task 本地 save/log 的上报版:所有状态写回控制面。"""

    def __init__(self, task: pa.Task):
        self.task = task
        self._log_buf: list[str] = []

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(f"[{self.task.id}] {line}", flush=True)
        self._log_buf.append(line)
        if len(self._log_buf) >= 10:
            self.flush()

    def flush(self) -> None:
        if self._log_buf:
            try:
                _post("/api/agent/log",
                      {"task_id": self.task.id, "lines": self._log_buf})
                self._log_buf = []
            except Exception:
                pass  # 下次重试

    def stage(self, key, status, note=None, error=None, advance=False):
        self.flush()
        _post("/api/agent/stage",
              {"task_id": self.task.id, "key": key, "status": status,
               "note": note, "error": error, "advance": advance})

    def artifact(self, slot: str, path: Path):
        nas = self.task.upload_to_nas(slot, path)  # PC 直 scp NAS
        try:
            rel = str(path.resolve().relative_to(pa.ROOT))
        except ValueError:
            rel = str(path)
        self.flush()
        _post("/api/agent/artifact",
              {"task_id": self.task.id, "slot": slot, "local_path": rel,
               "size": path.stat().st_size, "nas_path": nas,
               "error": None if nas else "NAS 上传失败"})
        return nas


def materialize_source(params: dict, rep=None) -> None:
    """source_path 为 nas:/<绝对路径> 时,把原片从 NAS 拉回 PC 本地缓存。"""
    src = params.get("source_path", "")
    m = re.match(r"^nas:(/.+)$", src)
    if not m:
        return
    remote = m.group(1)
    slug = params["slug"]
    dst_dir = pa.STUDIO / slug / "nas-source"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / Path(remote).name
    if not dst.exists():
        if rep:
            rep.log(f"从 NAS 拉取原片: {remote}")
        subprocess.run(["scp", f"nas:'{remote}'", str(dst)], check=True)
    params["source_path"] = str(dst)
    if rep:
        rep.log(f"原片就绪(本地缓存): {dst.name} "
                f"{dst.stat().st_size // 1048576}MB")


def run_one(detail: dict) -> None:
    """执行一个领到的任务(从控制面 detail 重建本地 Task 对象)。"""
    materialize_source(detail["params"])  # nas:// 源先拉回本地
    task = pa.Task(detail["type"], detail["params"])
    task.id = detail["id"]
    # 对齐控制面进度
    for st in detail["stages"]:
        local = next(x for x in task.stages if x["key"] == st["key"])
        local["status"] = st["status"]
    task.current = next(
        (i for i, s in enumerate(task.stages) if s["status"] == pa.P_PENDING),
        len(task.stages))
    task.dir = pa.STUDIO / task.params["slug"]
    task.log_path = pa.STATE_DIR / f"{task.id}.agent.log"

    rep = AgentReporter(task)
    rep.log(f"代理 {AGENT_NAME} 领取任务,从阶段 "
            f"{task.stages[task.current]['key'] if task.current < len(task.stages) else '-'} 继续")

    # 产物落槽走上报;执行器内部调用 task.set_artifact → 用上报版注入
    orig_set = task.set_artifact
    orig_log = task.log

    def set_artifact_report(slot: str, path: Path):
        orig_set(slot, path)  # 本地留档
        return rep.artifact(slot, path)

    def log_report(msg: str):
        orig_log(msg)
        rep.log(msg)

    task.set_artifact = set_artifact_report
    task.log = log_report

    while task.current < len(task.stages):
        st = task.stages[task.current]
        if st["status"] == pa.P_DONE:
            task.current += 1
            continue
        rep.stage(st["key"], pa.P_RUNNING)
        try:
            note = pa.EXECUTORS[st["key"]](task) or "完成"
            rep.stage(st["key"], pa.P_DONE, note=note, advance=True)
            task.mark_stage(st["key"], pa.P_DONE, note=note)  # 本地留档
            task.current += 1
        except Exception as e:  # noqa: BLE001
            rep.stage(st["key"], pa.P_FAILED, error=str(e)[:500])
            task.mark_stage(st["key"], pa.P_FAILED, error=str(e)[:500])
            task.status = pa.S_FAILED
            task.save()
            rep.flush()
            _post("/api/agent/done", {"task_id": task.id,
                                      "status": pa.S_FAILED})
            return
    task.status = pa.S_DONE
    task.save()
    rep.flush()
    _post("/api/agent/done", {"task_id": task.id, "status": pa.S_DONE})


def push_voices() -> None:
    try:
        voices = pa.voice_lib.list_voices()
        _post("/api/agent/voices", {"voices": voices})
    except Exception as e:  # noqa: BLE001
        print(f"[voices 上报失败] {e}")


def main() -> None:
    print(f"[agent] server={SERVER} name={AGENT_NAME} poll={POLL_SEC}s")
    last_voice_push = 0.0
    last_env_push = 0.0
    while True:
        try:
            env = None
            if time.time() - last_env_push > 600:
                env = pa.env_selftest()  # PC 真实干活环境,随 poll 上报
                last_env_push = time.time()
            if time.time() - last_voice_push > 600:
                push_voices()
                last_voice_push = time.time()
            r = _post("/api/agent/poll", {"agent": AGENT_NAME, "env": env})
            t = r.get("task")
            if t:
                print(f"[agent] 领到任务 {t['id']} {t.get('slug')}")
                run_one(t)
                continue  # 领完立刻再 poll
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print("[agent] token 无效:检查 STUDIO_TOKEN 与控制面 "
                      "DATA_DIR/.agent-token")
                time.sleep(60)
            else:
                print(f"[agent] server 错误 {e}")
                time.sleep(POLL_SEC)
        except Exception as e:  # noqa: BLE001
            print(f"[agent] 连接失败: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
