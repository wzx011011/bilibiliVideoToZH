"""PC 执行代理 —— 轮询 NAS 控制面领任务,在本地跑重活(GPU/翻译/渲染)。

与 src/pipeline_admin.py 的 server 模式配对使用:
  NAS 容器(常开):网页 + 任务队列(唯一事实源)
  本代理(PC,开机自启):poll 领任务 → 逐阶段执行 EXECUTORS →
  状态/日志/产物上报;产物 scp 直达 NAS(控制面只记 nas_path)

生命周期保证(v2):
  领取任务后的一切(重建/前置/执行/上报)都包在外层 try/except/finally,
  任何路径退出都必须停心跳、尽最大努力上报终态 —— 否则服务端租约靠
  60 分钟超时兜底,任务会一直挂着"运行中"。
  租约 token:服务端 claim 时发放,所有上报携带;被回收/易主后收到 409
  立即放弃本地执行(LeaseLost),不误报终态。

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
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SERVER = os.environ.get("STUDIO_SERVER", "http://192.168.100.78:8766")
TOKEN = os.environ.get("STUDIO_TOKEN", "")
POLL_SEC = int(os.environ.get("STUDIO_POLL_SEC", "10"))
AGENT_NAME = os.environ.get("COMPUTERNAME", "pc")
DONE_RETRIES = 5  # 终态上报重试:失败会拖到服务端租约超时才回收

# local 模式的完整执行器(WSL GPU/ffmpeg/翻译都在 PC 本地)
import pipeline_admin as pa  # noqa: E402

# 阶段内取消探针:_run 每 10s 查一次控制面的 cancel_requested,
# 长阶段(翻译/审查/渲染)秒级响应取消,不再等整阶段跑完
pa.CANCEL_PROBE = lambda task_id: cancel_requested(task_id)


class LeaseLost(Exception):
    """服务端判定租约失效(409):任务已被回收或转给其他代理。"""


def _post(path: str, body: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        SERVER + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "X-Agent-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _post_maybe_lease_lost(path: str, body: dict) -> dict:
    """上报封装:409 视为租约失效,抛 LeaseLost 让执行循环立即放弃。"""
    try:
        return _post(path, body)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            raise LeaseLost(str(e)) from e
        raise


def post_done(task_id: str, lease: str, status: str,
              error: str | None = None) -> bool:
    """终态上报(带重试)。失败只告警不抛:调用方在 finally 里,不能 Mask
    原始异常;服务端租约超时是最后兜底。"""
    for i in range(DONE_RETRIES):
        try:
            _post("/api/agent/done", {"task_id": task_id, "lease": lease,
                                      "status": status, "error": error})
            return True
        except Exception as e:  # noqa: BLE001
            wait = 5 * (i + 1)
            print(f"[agent] done 上报失败({i + 1}/{DONE_RETRIES},"
                  f"{wait}s 后重试): {e}", flush=True)
            time.sleep(wait)
    print(f"[agent] !! 终态 {status} 上报失败,任务 {task_id} 将由服务端"
          f"租约超时回收", flush=True)
    return False


class AgentReporter:
    """替代 Task 本地 save/log 的上报版:所有状态写回控制面。"""

    def __init__(self, task: pa.Task, lease: str):
        self.task = task
        self.lease = lease
        self._log_buf: list[str] = []

    def _payload(self, extra: dict) -> dict:
        return {"task_id": self.task.id, "lease": self.lease, **extra}

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(f"[{self.task.id}] {line}", flush=True)
        self._log_buf.append(line)
        if len(self._log_buf) >= 10:
            self.flush()

    def flush(self) -> None:
        if self._log_buf:
            try:
                _post_maybe_lease_lost("/api/agent/log",
                                       self._payload({"lines": self._log_buf}))
                self._log_buf = []
            except LeaseLost:
                raise
            except Exception:
                pass  # 网络抖动:日志留在缓冲,下次随状态上报重试

    def stage(self, key, status, note=None, error=None, advance=False):
        self.flush()
        _post_maybe_lease_lost("/api/agent/stage", self._payload(
            {"key": key, "status": status,
             "note": note, "error": error, "advance": advance}))

    def artifact(self, slot: str, path: Path):
        nas = self.task.upload_to_nas(slot, path)  # PC 直 scp NAS
        try:
            rel = str(path.resolve().relative_to(pa.ROOT))
        except ValueError:
            rel = str(path)
        self.flush()
        _post_maybe_lease_lost("/api/agent/artifact", self._payload(
            {"slot": slot, "local_path": rel,
             "size": path.stat().st_size, "nas_path": nas,
             "error": None if nas else "NAS 上传失败"}))
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
        # 无超时的 scp 挂起会让任务永远卡在"领取后无输出"(实测),必须限时
        subprocess.run(["scp", f"nas:'{remote}'", str(dst)], check=True,
                       timeout=3600)
    params["source_path"] = str(dst)
    if rep:
        rep.log(f"原片就绪(本地缓存): {dst.name} "
                f"{dst.stat().st_size // 1048576}MB")


def cancel_requested(task_id: str) -> bool:
    try:
        req = urllib.request.Request(
            f"{SERVER}/api/tasks/{task_id}",
            headers={"X-Agent-Token": TOKEN} if TOKEN else {})
        return bool(json.loads(urllib.request.urlopen(req, timeout=15).read())
                    .get("cancel_requested"))
    except Exception:
        return False


def run_one(detail: dict, lease: str = "") -> None:
    """执行一个领到的任务。任何退出路径都保证:停心跳 + 尽力上报终态。"""
    tid = detail["id"]
    if detail.get("cancel_requested"):
        post_done(tid, lease, pa.S_CANCELED)
        print(f"[agent] 任务已取消(领取时): {tid}")
        return

    task: pa.Task | None = None
    rep: AgentReporter | None = None
    hb_stop = threading.Event()
    final: dict = {"status": None, "error": None}

    try:
        task = pa.Task(detail["type"], detail["params"])
        task.id = detail["id"]
        # 对齐控制面进度:非 DONE 的阶段(含中断残留的 running)一律回待执行
        for st in detail["stages"]:
            local = next(x for x in task.stages if x["key"] == st["key"])
            local["status"] = st["status"] if st["status"] == pa.P_DONE \
                else pa.P_PENDING
        task.current = next(
            (i for i, s in enumerate(task.stages) if s["status"] == pa.P_PENDING),
            len(task.stages))
        task.dir = pa.STUDIO / task.params["slug"]
        task.log_path = pa.STATE_DIR / f"{task.id}.agent.log"

        rep = AgentReporter(task, lease)
        rep.log(f"代理 {AGENT_NAME} 领取任务,从阶段 "
                f"{task.stages[task.current]['key'] if task.current < len(task.stages) else '-'} 继续")
        # NAS 原片拉取放在 rep 之后:拉片耗时数分钟,必须有日志可见 + 超时兜底
        materialize_source(detail["params"], rep)

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

        def _hb():
            while not hb_stop.wait(45):
                try:
                    k = task.stages[min(task.current,
                                        len(task.stages) - 1)]["key"]
                    _post_maybe_lease_lost("/api/agent/progress", rep._payload(
                        {"key": k, "status": pa.P_RUNNING}))
                except LeaseLost:
                    print(f"[agent] 租约失效,停止心跳: {tid}", flush=True)
                    return
                except Exception:
                    pass  # 心跳失败不致命,45s 后再试
        threading.Thread(target=_hb, daemon=True).start()

        while task.current < len(task.stages):
            if cancel_requested(task.id):
                _normalize_local(task, pa.S_CANCELED)
                rep.flush()
                final["status"] = pa.S_CANCELED
                print(f"[agent] 任务已取消: {tid}")
                return
            st = task.stages[task.current]
            if st["status"] == pa.P_DONE:
                task.current += 1
                continue
            rep.stage(st["key"], pa.P_RUNNING)
            try:
                note = pa.EXECUTORS[st["key"]](task) or "完成"
            except pa.StageCanceled:
                _normalize_local(task, pa.S_CANCELED)
                rep.flush()
                final["status"] = pa.S_CANCELED
                print(f"[agent] 任务已取消(阶段中断): {tid}")
                return
            except LeaseLost:
                raise
            except Exception as e:  # noqa: BLE001
                err = str(e)[:500]
                task.mark_stage(st["key"], pa.P_FAILED, error=err)
                task.status = pa.S_FAILED
                task.save()
                rep.stage(st["key"], pa.P_FAILED, error=err)
                final.update(status=pa.S_FAILED, error=err)
                print(f"[agent] 阶段失败 {st['key']}: {err[:160]}", flush=True)
                return
            rep.stage(st["key"], pa.P_DONE, note=note, advance=True)
            task.mark_stage(st["key"], pa.P_DONE, note=note)  # 本地留档
            task.current += 1
        task.status = pa.S_DONE
        task.save()
        final["status"] = pa.S_DONE
    except LeaseLost:
        # 所有权已易主:放弃执行、不报终态、不清租约(那不是我们的了)
        hb_stop.set()
        print(f"[agent] 租约失效,放弃本地执行: {tid}")
        return
    except Exception as e:  # noqa: BLE001
        err = str(e)[:500]
        final.update(status=pa.S_FAILED, error=err)
        print(f"[agent] 任务异常(未执行完): {tid}: {err[:200]}", flush=True)
        if task is not None and rep is not None:
            try:  # 尽力把当前阶段标失败,平台才能给出可重试的准确状态
                key = task.stages[min(task.current,
                                      len(task.stages) - 1)]["key"]
                task.mark_stage(key, pa.P_FAILED, error=err)
                task.status = pa.S_FAILED
                task.save()
                rep.stage(key, pa.P_FAILED, error=err)
            except Exception:
                pass
    finally:
        hb_stop.set()
        if final["status"]:
            post_done(tid, lease, final["status"], final["error"])


def _normalize_local(task: pa.Task, status: str) -> None:
    """取消收口:残留 running 阶段复位 pending,终态落盘。"""
    for st in task.stages:
        if st["status"] == pa.P_RUNNING:
            st.update(status=pa.P_PENDING, error=None, started_at=None)
    task.current = next((i for i, s in enumerate(task.stages)
                         if s["status"] == pa.P_PENDING), len(task.stages))
    task.status = status
    task.save()


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
                run_one(t, r.get("lease", ""))
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
