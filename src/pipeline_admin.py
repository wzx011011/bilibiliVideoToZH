"""统一视频汉化平台 v2 —— 类型路由工作流 + 五件套产物 + NAS 归档。

核心模型:
- 视频类型 = 字幕情况(en_vtt 有英文字幕 / none 无字幕 / zh_hard 中文硬字幕)
  × 说话人数(1 / 2) → 自动路由到阶段序列
- 每任务的充分必要产物(五件套):
  source_video / en_subtitle / zh_subtitle / zh_audio / final_video
  (zh_hard 型无英文字幕槽)
- 每个阶段产物落槽后自动 scp 到 NAS:
  /volume1/share/视频/<slug>/01-视频源 .. 05-成品/

配音引擎:CosyVoice2 零样本克隆(音色库复用,见 voice_lib)。
翻译:本地 Ollama(默认 qwen3:14b)。
v1 的豆包链已退役(代码保留于仓库,不再被本平台引用)。

用法:
  work/.venv-ocr/Scripts/python.exe src/pipeline_admin.py
  打开 http://127.0.0.1:8766 (默认 0.0.0.0,局域网可访问)
"""
from __future__ import annotations

import os

MODE = os.environ.get("STUDIO_MODE", "local")

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if MODE == "local":
    import voice_lib  # server 容器不带该模块(音色由代理上报)
else:
    voice_lib = None

ROOT = Path(__file__).resolve().parents[1]
# 数据目录(任务/锁/音色缓存):容器挂 /data,PC 默认 work/studio
DATA_DIR = Path(os.environ.get("STUDIO_DATA") or (ROOT / "work" / "studio"))
# 媒体根(NAS 容器挂载 /volume1/share/视频 → /media;PC local 模式无此功能)
MEDIA_ROOT = Path(os.environ["STUDIO_MEDIA"]) if os.environ.get("STUDIO_MEDIA") else None
MEDIA_SOURCE_DIR = os.environ.get("STUDIO_SOURCE_DIR", "原片库")  # 原片库子目录名
# 媒体根在 NAS 的真实绝对路径(供 nas: 前缀建任务;本地 local 模式无)
NAS_MEDIA_ABS = os.environ.get("STUDIO_NAS_MEDIA", "/volume1/share/视频汉化项目")
TOOL_DIR = ROOT / "src"
VENV_PY = str(ROOT / "work" / ".venv-ocr" / "Scripts" / "python.exe")
VC_DIR = ROOT / "work" / "voice-clone-demo"
VC_PY = str(VC_DIR / ".venv" / "Scripts" / "python.exe")
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"
PODCAST_STUDIO = ROOT / "work" / "podcast-studio"
STUDIO = DATA_DIR
STATE_DIR = DATA_DIR / "tasks"
PORT = 8766
NAS_BASE = "/volume1/share/视频汉化项目"
NAS_SOURCE_BASE = NAS_BASE + "/原片库"
NAS_PRODUCT_BASE = NAS_BASE + "/成品库"
WSL_PY = "/home/comfy/cosy-gpu-venv/bin/python"
WSL_ENV = ("HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 "
           "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1")
DEFAULT_TRANSLATE_MODEL = "qwen3:14b"

# =====================================================================
# 五件套槽位定义
# =====================================================================

ARTIFACT_SLOTS = {
    "source_video": {"label": "视频源", "nas_dir": "视频源"},
    "en_subtitle": {"label": "英文字幕", "nas_dir": "01-英文字幕"},
    "zh_subtitle": {"label": "中文字幕", "nas_dir": "02-中文字幕"},
    "zh_audio": {"label": "中文音频", "nas_dir": "03-中文音频"},
    "final_video": {"label": "成品", "nas_dir": "04-中文视频"},
}

# =====================================================================
# 视频类型 → 工作流注册表
# =====================================================================

_TYPE_COMMON_PARAMS = [
    {"key": "slug", "label": "任务代号", "type": "str", "required": True,
     "hint": "字母数字-_,将作为 NAS 目录名"},
    {"key": "source_path", "label": "原视频路径", "type": "str",
     "required": True, "hint": "本地路径,如 youtube/xxx/a.mp4"},
    {"key": "title", "label": "封面标题(cover 模式用)", "type": "str",
     "required": False},
    {"key": "render_mode", "label": "成片模式", "type": "choice",
     "choices": ["original", "narration", "podcast", "podcast_remotion",
                 "subtitle_only"],
     "required": False,
     "hint": "original=原片时间轴 narration=中文旁白 podcast=章节图播客 "
             "podcast_remotion=Remotion真人头像播客 subtitle_only=原声+中文字幕"},
]

VIDEO_TYPES: dict[str, dict] = {
    "en_vtt_2": {
        "key": "en_vtt_2", "name": "英文访谈(多人)",
        "desc": "有英文字幕(VTT)的多人物访谈。声纹分说话人 → Ollama 翻译 → "
                "CosyVoice 双音色克隆原声 → 时间轴对齐 → 原片保留渲染。",
        "dims": {"subtitle": "en_vtt", "speakers": 2},
        "default_render": "original",
        "params": _TYPE_COMMON_PARAMS + [
            {"key": "vtt_path", "label": "英文字幕 VTT 路径", "type": "str",
             "required": True},
            {"key": "anchors", "label": "声纹锚点 JSON", "type": "str",
             "required": True,
             "hint": '{"A":[起,止],"B":[起,止]} 从原片各选一段单人发言'},
            {"key": "clone_original", "label": "自动克隆原片人声", "type": "bool",
             "required": False,
             "hint": "开启后忽略音色选择,自动用锚点截原片人声做参考"},
            {"key": "voice_A", "label": "说话人A音色", "type": "voice",
             "required": False},
            {"key": "voice_B", "label": "说话人B音色", "type": "voice",
             "required": False,
             "hint": "多人必填(或开自动克隆),否则两人同声"},
            {"key": "translate_model", "label": "翻译模型", "type": "str",
             "required": False},
        ],
        "stages": ["ensure_source",
                   "extract_audio",
                   "en_slots",
                   "align_speakers",
                   "translate",
                   "audit_translation",
                   "gen_audio",
                   "assemble_audio",
                   "zh_subtitle",
                   "render",],
    },
    "en_vtt_2_narration": {
        "key": "en_vtt_2_narration", "name": "英文访谈·多人·中文旁白",
        "desc": "按语义合并成30~90秒段落,中文主音轨+英文原声低混,原片画面保留。",
        "dims": {"subtitle": "en_vtt", "speakers": 2, "mode": "narration"},
        "default_render": "original",
        "params": _TYPE_COMMON_PARAMS + [
            {"key": "vtt_path", "label": "英文字幕 VTT 路径", "type": "str", "required": True},
            {"key": "anchors", "label": "声纹锚点 JSON", "type": "str", "required": True,
             "hint": '{"A":[起,止],"B":[起,止]}'},
            {"key": "clone_original", "label": "自动克隆原片人声", "type": "bool", "required": False,
             "hint": "开启后自动用锚点截原片人声"},
            {"key": "voice_A", "label": "说话人A音色", "type": "voice", "required": False},
            {"key": "voice_B", "label": "说话人B音色", "type": "voice", "required": False},
            {"key": "translate_model", "label": "翻译模型", "type": "str", "required": False},
            {"key": "original_db", "label": "英文原声音量(dB)", "type": "str", "required": False,
             "hint": "默认 -22"},
        ],
        "stages": ["ensure_source",
                   "extract_audio",
                   "en_slots",
                   "align_speakers",
                   "translate",
                   "audit_translation",
                   "narration_runs",
                   "gen_audio",
                   "assemble_narration",
                   "zh_subtitle",
                   "render",],
    },
    "en_vtt_1": {
        "key": "en_vtt_1", "name": "英文演讲/讲座(单人)",
        "desc": "有英文字幕(VTT)的单人视频。Ollama 翻译 → CosyVoice 单音色"
                " → 时间轴对齐 → 原片保留渲染。",
        "dims": {"subtitle": "en_vtt", "speakers": 1},
        "default_render": "original",
        "params": _TYPE_COMMON_PARAMS + [
            {"key": "vtt_path", "label": "英文字幕 VTT 路径", "type": "str",
             "required": True},
            {"key": "anchors", "label": "声纹锚点 JSON(可选)", "type": "str",
             "required": False,
             "hint": '{"A":[起,止]};不填则不分说话人(全部按A)'},
            {"key": "clone_original", "label": "自动克隆原片人声", "type": "bool",
             "required": False,
             "hint": "开启后需填锚点,自动截原片人声做参考"},
            {"key": "voice_A", "label": "音色", "type": "voice",
             "required": False},
            {"key": "translate_model", "label": "翻译模型", "type": "str",
             "required": False},
        ],
        "stages": ["ensure_source",
                   "extract_audio",
                   "en_slots",
                   "translate",
                   "audit_translation",
                   "gen_audio",
                   "assemble_audio",
                   "zh_subtitle",
                   "render",],
    },
    "none_1": {
        "key": "none_1", "name": "无字幕单人视频",
        "desc": "无字幕视频。whisper 英文转写成槽 → 翻译 → CosyVoice 单音色"
                " → 原片保留渲染。",
        "dims": {"subtitle": "none", "speakers": 1},
        "default_render": "original",
        "params": _TYPE_COMMON_PARAMS + [
            {"key": "voice_A", "label": "音色", "type": "voice",
             "required": False},
            {"key": "translate_model", "label": "翻译模型", "type": "str",
             "required": False},
        ],
        "stages": ["ensure_source",
                   "extract_audio",
                   "en_slots",
                   "translate",
                   "audit_translation",
                   "gen_audio",
                   "assemble_audio",
                   "zh_subtitle",
                   "render",],
    },
    "none_2": {
        "key": "none_2", "name": "无字幕多人视频",
        "desc": "无字幕多人视频。whisper 英文转写 → campplus 声纹分离(需锚点)"
                " → 翻译 → 双音色配音 → 原片保留渲染。",
        "dims": {"subtitle": "none", "speakers": 2},
        "default_render": "original",
        "params": _TYPE_COMMON_PARAMS + [
            {"key": "anchors", "label": "声纹锚点 JSON", "type": "str",
             "required": True,
             "hint": '{"A":[起,止],"B":[起,止]} 从原片各选一段单人发言'},
            {"key": "clone_original", "label": "自动克隆原片人声", "type": "bool",
             "required": False},
            {"key": "voice_A", "label": "说话人A音色", "type": "voice",
             "required": False},
            {"key": "voice_B", "label": "说话人B音色", "type": "voice",
             "required": False,
             "hint": "多人必填(或开自动克隆)"},
            {"key": "translate_model", "label": "翻译模型", "type": "str",
             "required": False},
        ],
        "stages": ["ensure_source",
                   "extract_audio",
                   "en_slots",
                   "translate",
                   "audit_translation",
                   "gen_audio",
                   "assemble_audio",
                   "zh_subtitle",
                   "render",],
    },
    "none_2_podcast": {
        "key": "none_2_podcast", "name": "无字幕多人·播客版",
        "desc": "无字幕多人访谈的 Remotion 真人头像播客版。官方字幕/whisper "
                "转写 → 声纹分离 → 翻译审查 → 语义段合并 → 双音色配音精修 → "
                "播客画面(双头像+波形+滚动字幕)渲染。",
        "dims": {"subtitle": "none", "speakers": 2, "mode": "podcast"},
        "default_render": "podcast_remotion",
        "params": _TYPE_COMMON_PARAMS + [
            {"key": "vtt_path", "label": "英文字幕 VTT(可选)", "type": "str",
             "required": False,
             "hint": "YouTube 自动字幕;有则官方字幕成槽(优于本地 whisper)"
                     "并启用词级校声,无则 whisper 转写"},
            {"key": "anchors", "label": "声纹锚点 JSON", "type": "str",
             "required": True,
             "hint": "JSON如 {\"A\":[60,80],\"B\":[300,320]} 从原片各选一段"
                     "单人发言;A=主持人,B=嘉宾(头像/音色按此对应)"},
            {"key": "voice_A", "label": "主持人音色", "type": "voice",
             "required": False, "hint": "默认 doubao-yuanboxiaoshu"},
            {"key": "voice_B", "label": "嘉宾音色", "type": "voice",
             "required": False, "hint": "默认 doubao-shenyeboker"},
            {"key": "name_A", "label": "主持人显示名", "type": "str",
             "required": False},
            {"key": "name_B", "label": "嘉宾显示名", "type": "str",
             "required": False},
            {"key": "translate_model", "label": "翻译模型", "type": "str",
             "required": False},
        ],
        "stages": ["ensure_source",
                   "extract_audio",
                   "en_slots",
                   "align_speakers",
                   "translate",
                   "audit_translation",
                   "narration_runs",
                   "gen_audio",
                   "polish_audio",
                   "podcast_props",
                   "zh_subtitle",
                   "render",],
    },
    "zh_hard_1": {
        "key": "zh_hard_1", "name": "中文硬字幕视频(课程)",
        "desc": "画面自带中文字幕的单人视频(如 B站课程)。OCR 提取文本 → "
                "CosyVoice 音色朗读 → ASR 字幕 → 默认封面渲染(可切原片)。",
        "dims": {"subtitle": "zh_hard", "speakers": 1},
        "default_render": "cover",
        "params": _TYPE_COMMON_PARAMS + [
            {"key": "voice_A", "label": "音色", "type": "voice",
             "required": False, "hint": "默认 doubao-taotao"},
        ],
        "stages": ["ensure_source", "ocr_zh", "cut_items", "gen_audio",
                   "zh_subtitle", "render"],
    },
}

STAGE_LABELS = {
    "ensure_source": "准备原片",
    "extract_audio": "提取音频",
    "en_slots": "英文字幕成槽",
    "align_speakers": "词级对齐校声",
    "translate": "Ollama 翻译",
    "audit_translation": "译文审查",
    "ocr_zh": "OCR 中文字幕",
    "cut_items": "文本切块",
    "gen_audio": "CosyVoice 配音",
    "narration_runs": "语义段落合并",
    "polish_audio": "音频精修",
    "podcast_props": "播客素材构建",
    "assemble_narration": "旁白+原声混音",
    "assemble_audio": "时间轴合成",
    "zh_subtitle": "ASR 中文字幕",
    "render": "渲染成品",
}


# =====================================================================
# agent 分配(server 模式):单任务锁 + 心跳回收 + 代理上报的音色缓存
# =====================================================================

ACTIVE_PATH = DATA_DIR / "active.json"
AGENT_STATE_PATH = DATA_DIR / "agent-state.json"


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def agent_claim_task(agent: str):
    """取下一个可执行任务:无 active 锁且阶段未跑完的最老任务。
    心跳超时(15 分钟)的锁自动回收,任务置 failed 待重试。"""
    import datetime as _dt
    act = _read_json(ACTIVE_PATH, None)
    if act:
        hb = _dt.datetime.fromisoformat(act.get("heartbeat", "2000-01-01"))
        if _dt.datetime.now() - hb < _dt.timedelta(minutes=15):
            return None  # 已有代理在干活
        # 代理失联:回收
        t = load_task(act.get("task_id") or "")
        if t and t.status == S_RUNNING:
            t.status = S_FAILED
            cur = t.stages[t.current] if t.current < len(t.stages) else None
            if cur and cur["status"] == P_RUNNING:
                cur["status"], cur["error"] = P_FAILED, "代理失联(心跳超时)"
            t.save()
        _write_json(ACTIVE_PATH, {})
    # 领取=创建时间顺序(ID 随机后缀,文件名排序不等于创建顺序)
    for t in sorted(list_tasks(newest_first=False),
                    key=lambda t: t.created_at):
        if t.status != S_RUNNING:
            continue
        if any(s["status"] == P_PENDING for s in t.stages):
            _write_json(ACTIVE_PATH, {"task_id": t.id, "agent": agent,
                                      "heartbeat": _dt.datetime.now().isoformat()})
            return t
    return None


def agent_heartbeat(task_id: str) -> None:
    act = _read_json(ACTIVE_PATH, {})
    if act.get("task_id") == task_id:
        import datetime as _dt
        act["heartbeat"] = _dt.datetime.now().isoformat()
        _write_json(ACTIVE_PATH, act)


def agent_release(task_id: str) -> None:
    act = _read_json(ACTIVE_PATH, {})
    if act.get("task_id") == task_id:
        _write_json(ACTIVE_PATH, {})


# =====================================================================
# 任务模型(schema 2)
# =====================================================================

S_RUNNING, S_DONE, S_FAILED = "running", "done", "failed"
P_PENDING, P_RUNNING, P_DONE, P_FAILED = "pending", "running", "done", "failed"


class Task:
    SCHEMA = 2

    def __init__(self, type_key: str, params: dict):
        self.id = time.strftime("%Y%m%d-") + uuid.uuid4().hex[:8]
        self.type = type_key
        self.params = params
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.status = S_RUNNING
        self.current = 0
        self.stages = [{"key": k, "label": STAGE_LABELS.get(k, k),
                        "status": P_PENDING, "started_at": None,
                        "ended_at": None, "error": None, "note": None}
                       for k in VIDEO_TYPES[type_key]["stages"]]
        self.artifacts = {k: {"status": P_PENDING, "local_path": None,
                              "nas_path": None, "size": None, "error": None}
                          for k in ARTIFACT_SLOTS}
        self.dir = STUDIO / self.params["slug"]
        self.log_path = STATE_DIR / f"{self.id}.log"

    # ---------- 持久化 ----------

    @property
    def json_path(self) -> Path:
        return STATE_DIR / f"{self.id}.json"

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.json_path.write_text(json.dumps({
            "schema": self.SCHEMA, "id": self.id, "type": self.type,
            "params": self.params, "created_at": self.created_at,
            "status": self.status, "current": self.current,
            "stages": self.stages, "artifacts": self.artifacts,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Task":
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("schema") != 2:
            raise ValueError("legacy task")
        t = cls.__new__(cls)
        t.id, t.type, t.params = d["id"], d["type"], d["params"]
        t.created_at = d["created_at"]
        t.status, t.current = d["status"], d["current"]
        t.stages, t.artifacts = d["stages"], d["artifacts"]
        t.dir = STUDIO / t.params["slug"]
        t.log_path = STATE_DIR / f"{t.id}.log"
        return t

    # ---------- 日志/状态 ----------

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(f"[{self.id}] {line}", flush=True)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def log_tail(self, n=120):
        if not self.log_path.exists():
            return []
        return self.log_path.read_text(encoding="utf-8").splitlines()[-n:]

    def mark_stage(self, key, status, error=None, note=None) -> None:
        s = next((x for x in self.stages if x["key"] == key), None)
        if s is None:
            # 任务建于旧 stages 定义(代码升级新增阶段):动态追加,避免
            # 代理上报未知 key 时 StopIteration 把任务打成 failed
            s = {"key": key, "label": STAGE_LABELS.get(key, key),
                 "status": P_PENDING, "started_at": None, "ended_at": None,
                 "error": None, "note": None}
            self.stages.append(s)
        if status == P_RUNNING:
            s["started_at"] = time.strftime("%H:%M:%S")
        if status in (P_DONE, P_FAILED):
            s["ended_at"] = time.strftime("%H:%M:%S")
        s["status"] = status
        if error is not None:
            s["error"] = error
        if note is not None:
            s["note"] = note
        self.save()

    # ---------- 产物槽 ----------

    def set_artifact(self, slot: str, path: Path) -> str | None:
        """产物落槽 + 自动上传 NAS(失败不阻塞,记 error 供重传)。"""
        info = self.artifacts[slot]
        try:
            rel = str(path.relative_to(ROOT))
        except ValueError:  # 跨盘/外部路径,存绝对路径
            rel = str(path)
        info.update(status=P_DONE, local_path=rel,
                    size=path.stat().st_size, error=None)
        try:
            info["nas_path"] = self.upload_to_nas(slot, path)
        except Exception as e:  # noqa: BLE001 — 上传永不阻塞产物落槽
            info["nas_path"] = None
            info["error"] = f"NAS 上传失败: {str(e)[:80]}"
        self.save()
        return info["nas_path"]

    def upload_to_nas(self, slot: str, path: Path) -> str | None:
        slug = self.params["slug"]
        sub = ARTIFACT_SLOTS[slot]["nas_dir"]
        # 原片与生成资源分根:源→原片库,其余→成品库
        root = NAS_SOURCE_BASE if slot == "source_video" else NAS_PRODUCT_BASE
        nas_dir = f"{root}/{slug}/{sub}"
        # scp 会把 Windows 盘符 E: 解析成主机名,整路径变文件名(实测),
        # 必须用正斜杠相对路径 + cwd=ROOT 传输
        try:
            rel = str(path.resolve().relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            rel = None
        try:
            subprocess.run(["ssh", "nas", f"mkdir -p '{nas_dir}'"],
                           check=True, timeout=30, capture_output=True)
            if rel:
                subprocess.run(["scp", rel, f"nas:{nas_dir}/"],
                               cwd=str(ROOT), check=True, timeout=600,
                               capture_output=True)
            else:
                subprocess.run(["scp", str(path).replace("\\", "/"),
                                f"nas:{nas_dir}/"],
                               check=True, timeout=600, capture_output=True)
            self.log(f"NAS ✓ {slot}: {nas_dir}/{path.name}")
            return f"{nas_dir}/{path.name}"
        except Exception as e:  # noqa: BLE001
            self.artifacts[slot]["error"] = f"NAS 上传失败: {str(e)[:80]}"
            self.log(f"NAS ✗ {slot}: {str(e)[:100]}(不阻塞,可重传)")
            return None

    # ---------- 汇总 ----------

    def brief(self) -> dict:
        t = VIDEO_TYPES[self.type]
        done = sum(1 for s in self.stages if s["status"] == P_DONE)
        return {"id": self.id, "type": self.type, "type_name": t["name"],
                "slug": self.params["slug"], "status": self.status,
                "created_at": self.created_at,
                "progress": f"{done}/{len(self.stages)}",
                "stages": [{"key": s["key"], "label": s["label"],
                            "status": s["status"]} for s in self.stages],
                "artifacts": self.artifacts}

    def detail(self) -> dict:
        d = self.brief()
        d["params"] = self.params
        d["log"] = self.log_tail()
        return d


# =====================================================================
# 子进程工具
# =====================================================================

def _run(cmd: list[str], task: Task, timeout: int = 7200) -> str:
    task.log("$ " + " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if proc.stdout:
        task.log(proc.stdout.rstrip()[-4000:])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        task.log("[stderr] " + "\n".join(err[-15:]))
        raise RuntimeError(f"命令失败(exit {proc.returncode}): "
                           f"{Path(str(cmd[0])).name}")
    return proc.stdout


def _wsl_run(script_rel: str, args: list[str], task: Task,
             timeout: int = 24 * 3600) -> str:
    """WSL2 GPU 跑 CosyVoice(长任务,断点续跑在脚本侧)。"""
    quoted = " ".join(f'"{a}"' for a in args)
    # inner 整体作为 bash -c 的单参数;subprocess list 形式传参无需再嵌引号,
    # 之前手工拼 " 导致 && 把命令拆断(实测:cd 变裸命令)
    inner = (f"cd /mnt/e/ai/bilibiliVideoToZH && env {WSL_ENV} "
             f"{WSL_PY} {script_rel} {quoted}")
    cmd = ["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-c", inner]
    return _run(cmd, task, timeout=timeout)


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True,
        check=True).stdout.strip()
    return float(out)


# =====================================================================
# 阶段执行器 v2
# =====================================================================

def _src(task: Task) -> Path:
    suffix = Path(task.params["source_path"]).suffix or ".mp4"
    return task.dir / "01-视频源" / f"{task.params['slug']}-source{suffix}"


def ex_ensure_source(task: Task) -> str:
    src = Path(task.params["source_path"])
    if not src.is_absolute():
        src = ROOT / src
    if not src.exists():
        raise RuntimeError(f"原视频不存在: {src}")
    dst = _src(task)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)
    dur = _probe_duration(dst)
    task.set_artifact("source_video", dst)
    task.params["_duration"] = dur
    task.save()
    return f"{dst.name} ({dur/60:.1f} 分钟)"


def ex_extract_audio(task: Task) -> str:
    audio = task.dir / "work" / "audio16k.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    _run([str(FFMPEG), "-y", "-i", str(_src(task)), "-vn",
          "-ar", "16000", "-ac", "1", str(audio)], task)
    return "audio16k.wav"


def _slots_to_srt(slots: list[dict], out: Path) -> None:
    def ts(t: float) -> str:
        h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

    lines = []
    for i, s in enumerate(slots, 1):
        lines += [str(i), f"{ts(s['start'])} --> {ts(s['end'])}",
                  f"[{s['speaker']}] {s['text']}", ""]
    out.write_text("\n".join(lines), encoding="utf-8")


def ex_en_slots(task: Task) -> str:
    w = task.dir / "work"
    slots_path = w / "slots.json"
    dims = VIDEO_TYPES[task.type]["dims"]
    if dims["subtitle"] == "en_vtt" or task.params.get("vtt_path"):
        # 官方字幕成槽(YouTube auto captions 优于本地 whisper)
        anchors = task.params.get("anchors") or '{"A": [3.5, 18.8]}'
        vtt = Path(task.params["vtt_path"])
        if not vtt.is_absolute():
            vtt = ROOT / vtt
        _run([VC_PY, str(VC_DIR / "prepare_fine_slots.py"),
              "--vtt", str(vtt),
              "--audio", str(w / "audio16k.wav"),
              "--anchors", anchors,
              "--out", str(slots_path)], task, timeout=1800)
    elif dims["subtitle"] == "none" and dims["speakers"] >= 2:
        # 无字幕多人:whisper 成槽 → campplus 声纹标注
        _run([VENV_PY, str(TOOL_DIR / "whisper_slots.py"),
              str(w / "audio16k.wav"), "-o", str(slots_path)], task,
             timeout=24 * 3600)
        anchors_json = task.params.get("anchors") or '{"A": [3.5, 18.8]}'
        _run([VC_PY, str(TOOL_DIR / "diarize_slots.py"),
              "--audio", str(w / "audio16k.wav"),
              "--slots", str(slots_path),
              "--anchors", anchors_json,
              "--out", str(slots_path)], task, timeout=1800)
    else:  # none 单人 → whisper
        _run([VENV_PY, str(TOOL_DIR / "whisper_slots.py"),
              str(w / "audio16k.wav"), "-o", str(slots_path)], task,
             timeout=24 * 3600)
    slots = json.loads(slots_path.read_text(encoding="utf-8"))
    en_srt = task.dir / "02-英文字幕" / f"{task.params['slug']}-en.srt"
    en_srt.parent.mkdir(parents=True, exist_ok=True)
    _slots_to_srt(slots, en_srt)
    shutil.copy2(slots_path, en_srt.with_suffix(".slots.json"))
    task.set_artifact("en_subtitle", en_srt)
    return f"{len(slots)} 槽"


def ex_translate(task: Task) -> str:
    w = task.dir / "work"
    model = task.params.get("translate_model") or DEFAULT_TRANSLATE_MODEL
    zh_path = w / "slots_zh.json"
    args = [VC_PY, str(VC_DIR / "translate_fine_batches.py"),
            "--slots", str(w / "slots.json"), "--out", str(zh_path),
            "--model", model]
    # 播客链字数是软约束(自然语速),大批次换取更长语境
    if VIDEO_TYPES[task.type]["dims"].get("mode") == "podcast":
        args += ["--batch", "12"]
    _run(args, task, timeout=24 * 3600)
    zh = json.loads(zh_path.read_text(encoding="utf-8"))
    slots = json.loads((w / "slots.json").read_text(encoding="utf-8"))
    if len(zh) < len(slots) * 0.9:
        raise RuntimeError(f"翻译不完整: {len(zh)}/{len(slots)}")
    return f"{len(zh)}/{len(slots)} 槽已译({model})"


def ex_align_speakers(task: Task) -> str:
    """词级对齐(ForcedAligner,WSL CPU) + 停顿切 utterance 的 campplus 重标注。

    修复固定窗口声纹标注的边界归属错误;无 vtt 字幕源或未装对齐器时优雅跳过。
    """
    w = task.dir / "work"
    vtt = Path(task.params["vtt_path"]) if task.params.get("vtt_path") else None
    if vtt and not vtt.is_absolute():
        vtt = ROOT / vtt
    if not vtt:
        return "跳过(无 vtt 字幕源,沿用窗口声纹标注)"
    chk = _run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-c",
                "test -x ~/qwen-aligner-venv/bin/python && echo ok || echo missing"],
               task, timeout=60)
    if "missing" in chk:
        return "跳过(WSL 未装 qwen-aligner-venv,沿用 campplus 标注)"

    def wsl(p: Path) -> str:
        s = str(p).replace("\\", "/")
        m = re.match(r"^([A-Za-z]):/(.*)", s)
        return f"/mnt/{m.group(1).lower()}/{m.group(2)}" if m else s

    quoted = " ".join(f'"{a}"' for a in [
        "/mnt/e/ai/bilibiliVideoToZH/src/align_worker.py",
        "--audio", wsl(w / "audio16k.wav"),
        "--vtt", wsl(vtt),
        "--out", wsl(w / "words_align.json"),
    ])
    inner = (f"cd /mnt/e/ai/bilibiliVideoToZH && env HF_HUB_OFFLINE=1 "
             f"~/qwen-aligner-venv/bin/python {quoted}")
    _run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-c", inner], task, timeout=4 * 3600)
    anchors = task.params.get("anchors") or '{"A": [3.5, 18.8]}'
    _run([VC_PY, str(TOOL_DIR / "label_speakers.py"),
          "--words", str(w / "words_align.json"),
          "--audio", str(w / "audio16k.wav"),
          "--slots", str(w / "slots.json"),
          "--anchors", anchors,
          "--out", str(w / "slots.json")], task, timeout=1800)
    slots = json.loads((w / "slots.json").read_text(encoding="utf-8"))
    relabeled = sum(1 for s in slots if s.get("relabel_evidence"))
    return f"{len(slots)} 槽(词级证据修正归属 {relabeled} 个)"


def ex_audit_translation(task: Task) -> str:
    """qwen3 逐槽对照英文源审查译文;系统性串位(MISMATCH 达阈值)则置失败。"""
    w = task.dir / "work"
    audit = w / "audit_translation.json"
    audit.unlink(missing_ok=True)  # 每次重译后全量重审
    try:
        _run([VENV_PY, str(TOOL_DIR / "audit_translation.py"),
              "--slots", str(w / "slots.json"),
              "--zh", str(w / "slots_zh.json"),
              "--out", str(audit),
              "--jobs", "3", "--sample", "4"], task, timeout=6 * 3600)
    except RuntimeError:
        pass  # 退出码 2 = 审查不过;报告已落盘,下面读取后给出明确失败
    if not audit.exists():
        raise RuntimeError("译文审查未产出报告(检查 Ollama/qwen3 是否可用)")
    result = json.loads(audit.read_text(encoding="utf-8"))
    from collections import Counter
    c = Counter(v.get("verdict") for v in result.values())
    mm = c.get("MISMATCH", 0)
    if mm >= 5:
        raise RuntimeError(f"译文审查未通过: MISMATCH {mm} 项(疑似批量串位),"
                           f"报告见 work/audit_translation.json")
    return (f"{len(result)} 槽: MATCH {c.get('MATCH', 0)} / "
            f"PARTIAL {c.get('PARTIAL', 0)} / MISMATCH {mm}")


def _parse_srt(path: Path) -> list[tuple[float, float, str]]:
    content = path.read_text(encoding="utf-8")
    cues = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        m = re.match(
            r"(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)",
            lines[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        cues.append((start, end, " ".join(lines[2:])))
    return cues


def ex_ocr_zh(task: Task) -> str:
    w = task.dir / "work"
    # 复用历史 OCR:源是 downloads/episode-XX.mp4 且 subtitles/ 已有成品
    m = re.search(r"(?:episode-|第)(\d+)", task.params.get("source_path", ""))
    if m:
        hist = ROOT / "subtitles" / f"episode-{int(m.group(1)):02d}.zh-CN.srt"
        if hist.exists():
            w.mkdir(parents=True, exist_ok=True)
            dst = w / f"episode-{int(m.group(1)):02d}.zh-CN-ocr.srt"
            shutil.copy2(hist, dst)
            n = len(_parse_srt(dst))
            return f"复用历史 OCR {n} 条({hist.name})"
    _run([VENV_PY, str(TOOL_DIR / "subtitle_ocr.py"),
          "--input", str(_src(task)), "--output", str(w)], task,
         timeout=24 * 3600)
    ocr_srt = next(w.glob("*-ocr.srt"), None)
    if not ocr_srt:
        raise RuntimeError("OCR 未产出 srt")
    cues = _parse_srt(ocr_srt)
    total = sum(len(c[2]) for c in cues)
    # 源字幕归档到中文字幕槽目录(标注 source);最终槽由 ASR 产出
    src_srt = task.dir / "03-中文字幕" / f"{task.params['slug']}-ocr-source.srt"
    src_srt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ocr_srt, src_srt)
    task.log(f"OCR 源字幕归档: {src_srt.name}(不占最终槽)")
    return f"OCR {len(cues)} 条 / {total} 字"


def ex_cut_items(task: Task) -> str:
    """OCR 中文字幕 → 纯文本朗读块(条数+字符双上限,无 prompt)。

    冒烟参数(表单不暴露,API 创建时直接传):
      _smoke_blocks: 只保留前 N 块;_smoke_chars: 每块字符上限临时改小
    """
    MAX_CHARS = int(task.params.get("_smoke_chars") or 3000)
    MAX_CUES = 120
    w = task.dir / "work"
    ocr_srt = next(w.glob("*-ocr.srt"), None)
    if not ocr_srt:
        raise RuntimeError("work/ 下无 OCR srt")
    cues = _parse_srt(ocr_srt)
    items, buf, chars = [], [], 0
    for _, _, text in cues:
        if buf and (chars + len(text) + 1 > MAX_CHARS
                    or len(buf) >= MAX_CUES):
            items.append({"id": len(items), "speaker": "A",
                          "text": " ".join(buf)})
            buf, chars = [], 0
        buf.append(text)
        chars += len(text) + 1
    if buf:
        items.append({"id": len(items), "speaker": "A", "text": " ".join(buf)})
    smoke = task.params.get("_smoke_blocks")
    if smoke:
        items = items[:int(smoke)]
    (w / "items.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"{len(items)} 块"


def _clone_original_voices(task: Task) -> dict[str, str]:
    """自动克隆原片人声:锚点段截参考音频 + 覆盖槽的英文文本作 ref 文本,
    注册为 orig-<slug>-A/B 音色(持久入库可复用)。返回 {spk: 音色名}。"""
    import voice_lib as vl
    w = task.dir / "work"
    anchors = {k: tuple(v) for k, v in
               json.loads(task.params["anchors"]).items()}
    slots = json.loads((w / "slots.json").read_text(encoding="utf-8"))
    audio = w / "audio16k.wav"
    out = {}
    for spk, (a0, a1) in anchors.items():
        texts = [s["text"] for s in slots
                 if s["end"] > a0 and s["start"] < a1]
        if not texts:
            raise RuntimeError(f"锚点 {spk}[{a0},{a1}] 未覆盖任何字幕槽,"
                               "请检查时间段")
        ref_txt = " ".join(texts)[:600]
        ref_wav = w / f"clone-ref-{spk}.wav"
        _run([str(FFMPEG), "-y", "-i", str(audio), "-ss", str(a0),
              "-t", str(a1 - a0), str(ref_wav)], task)
        name = f"orig-{task.params['slug']}-{spk}".lower()[:40]
        vl.create(name, ref_wav, ref_txt,
                  note=f"自动克隆({task.params['slug']} 锚点)")
        out[spk] = name
        task.log(f"自动克隆音色 {name}(锚点 {a0}-{a1}s, ref {len(ref_txt)} 字)")
    return out


def ex_narration_runs(task: Task) -> str:
    """细槽译文合并成语义段。播客版用更短段(45s)保证听感节奏。"""
    from narration import build_runs, save_runs
    w = task.dir / "work"
    slots = json.loads((w / "slots.json").read_text(encoding="utf-8"))
    zh = json.loads((w / "slots_zh.json").read_text(encoding="utf-8"))
    max_dur = 45.0 if VIDEO_TYPES[task.type]["dims"].get("mode") == "podcast" \
        else 75.0
    runs = build_runs(slots, zh, max_duration=max_dur, max_gap=5.0)
    nd = w / "narration"
    nd.mkdir(parents=True, exist_ok=True)
    save_runs(runs, nd / "runs.json")
    items = [{"id": r["id"], "speaker": r["speaker"], "text": r["text"]} for r in runs]
    (nd / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    task.params["_narration"] = True
    task.save()
    return f"{len(slots)} 槽 → {len(runs)} 个语义段"


def _build_voice_inputs(task: Task) -> tuple[Path, Path]:
    """构造 generate_voice 的 items/refs 输入。"""
    w = task.dir / "work"
    dims = VIDEO_TYPES[task.type]["dims"]
    if task.params.get("_narration"):
        items = json.loads((w / "narration" / "items.json").read_text(encoding="utf-8"))
    elif dims["subtitle"] == "zh_hard":
        items = json.loads((w / "items.json").read_text(encoding="utf-8"))
    else:
        slots = json.loads((w / "slots.json").read_text(encoding="utf-8"))
        zh = json.loads((w / "slots_zh.json").read_text(encoding="utf-8"))
        items = [{"id": s["id"], "speaker": s["speaker"],
                  "text": zh[str(s["id"])]} for s in slots]
        (w / "items.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    speakers = sorted({i["speaker"] for i in items})
    if task.params.get("clone_original"):
        voices = {spk: nm for spk, nm in
                  _clone_original_voices(task).items() if spk in speakers}
    else:
        voices = {}
        for spk in speakers:
            name = task.params.get(f"voice_{spk}") or \
                task.params.get("voice_A") or "doubao-taotao"
            voices[spk] = name
    refs_path = w / "refs.json"
    refs_path.write_text(json.dumps(voice_lib.refs_json_for(voices),
                                    ensure_ascii=False, indent=1),
                         encoding="utf-8")
    task.log(f"音色分配: {voices}")
    return w / "items.json", refs_path


def ex_gen_audio(task: Task) -> str:
    items_path, refs_path = _build_voice_inputs(task)
    w = task.dir / "work"
    concat = None
    if VIDEO_TYPES[task.type]["dims"]["subtitle"] == "zh_hard":
        concat = task.dir / "04-中文音频" / f"{task.params['slug']}-zh.wav"
        concat.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = w / ("narration/parts" if task.params.get("_narration") else "parts")
    base_args = ["--items-json", str(items_path),
                 "--refs-json", str(refs_path),
                 "--out-dir", str(parts_dir)]
    args = list(base_args) + (["--concat-out", str(concat)] if concat else [])
    try:
        _wsl_run("work/voice-clone-demo/generate_voice.py", args, task)
    except RuntimeError as e:
        task.log(f"WSL GPU 失败({str(e)[:80]}),Windows CPU 回退(慢)")
        _run([VC_PY, str(VC_DIR / "generate_voice.py")] + args, task,
             timeout=48 * 3600)
    n = len(list(parts_dir.glob("*.wav")))
    return f"{n} 段配音" + ("(已拼接整轨)" if concat else "")


def ex_polish_audio(task: Task) -> str:
    """播客音频精修:高通+静音切除+loudnorm+淡入淡出,输出到 Remotion public 目录。"""
    w = task.dir / "work"
    slug = task.params["slug"]
    audio_rel = f"audio-{slug}"
    out_dir = PODCAST_STUDIO / "public" / audio_rel
    speed = task.params.get("_polish_speed") or "1.0"
    _run([VENV_PY, str(TOOL_DIR / "polish_parts.py"),
          "--parts-dir", str(w / "narration" / "parts"),
          "--out-dir", str(out_dir), "--speed", speed,
          "--jobs", "6"], task, timeout=12 * 3600)
    n = len(list(out_dir.glob("*.wav")))
    if not n:
        raise RuntimeError("精修未产出音频段")
    return f"{n} 段({out_dir.name}/)"


def _concat_podcast_audio(chapters: list[dict], audio_dir: Path,
                          out: Path, task: Task) -> None:
    """按 props 时间轴拼接完整中文音轨(parts + 停顿静音)。"""
    import tempfile
    sr = "24000"  # 与 polish_parts 输出一致
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        listf = td / "list.txt"
        lines = []
        for i, ch in enumerate(chapters):
            part = audio_dir / f"{int(ch['id']):04d}.wav"
            lines.append(f"file '{part.as_posix()}'")
            if i < len(chapters) - 1:
                gap = round(chapters[i + 1]["start"] - ch["end"], 3)
                if gap > 0.01:
                    g = td / f"gap_{i:04d}.wav"
                    _run([str(FFMPEG), "-y", "-hide_banner", "-loglevel",
                          "error", "-f", "lavfi", "-i",
                          f"anullsrc=r={sr}:cl=mono", "-t", str(gap),
                          str(g)], task)
                    lines.append(f"file '{g.as_posix()}'")
        listf.write_text("\n".join(lines), encoding="utf-8")
        _run([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
              "-f", "concat", "-safe", "0", "-i", str(listf),
              "-c:a", "pcm_s16le", str(out)], task, timeout=3600)


def ex_podcast_props(task: Task) -> str:
    """播客素材:锚点截头像 + props(章节时间轴) + 完整中文音轨。"""
    w = task.dir / "work"
    slug = task.params["slug"]
    audio_rel = f"audio-{slug}"
    audio_dir = PODCAST_STUDIO / "public" / audio_rel
    # 1) 头像(存在则跳过,人工替换后重跑 render 即可)
    _run([VENV_PY, str(TOOL_DIR / "extract_avatars.py"),
          "--video", str(_src(task)),
          "--anchors", task.params["anchors"],
          "--out-dir", str(PODCAST_STUDIO / "public" / "avatars" / slug)],
         task)
    # 2) props(换人 0.7s/同人 0.45s 顺序排布)
    props = PODCAST_STUDIO / f"props-{slug}.json"
    _run([VENV_PY, str(TOOL_DIR / "build_podcast_props.py"),
          "--runs", str(w / "narration" / "runs.json"),
          "--items", str(w / "narration" / "items.json"),
          "--audio-dir", str(audio_dir), "--audio-rel", audio_rel,
          "--avatar-rel", f"avatars/{slug}",
          "--name-a", task.params.get("name_A") or "主持人",
          "--name-b", task.params.get("name_B") or "嘉宾",
          "--title", task.params.get("title") or f"{slug} · 中文播客",
          "-o", str(props)], task, timeout=1800)
    # 3) 完整中文音轨(五件套 zh_audio 槽)
    chapters = json.loads(props.read_text(encoding="utf-8"))["chapters"]
    audio_out = task.dir / "04-中文音频" / f"{slug}-播客.wav"
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    _concat_podcast_audio(chapters, audio_dir, audio_out, task)
    task.set_artifact("zh_audio", audio_out)
    total = chapters[-1]["end"]
    return (f"{len(chapters)} 章 / {total/60:.1f} 分钟 "
            f"(音轨 {audio_out.stat().st_size // 1048576}MB)")


def ex_render_remotion_podcast(task: Task) -> str:
    """Remotion 播客成片:分块渲染(--frames)防 OOM,再 ffmpeg concat。"""
    slug = task.params["slug"]
    props = PODCAST_STUDIO / f"props-{slug}.json"
    if not props.exists():
        raise RuntimeError(f"props 不存在: {props.name}(先跑 podcast_props)")
    chapters = json.loads(props.read_text(encoding="utf-8"))["chapters"]
    total = chapters[-1]["end"]
    out_dir = PODCAST_STUDIO / "out" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    from build_podcast_props import chunk_bounds
    edges = chunk_bounds(chapters, total)
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise RuntimeError("npx 不在 PATH(node 环境异常)")

    def render_cmd(i: int, a: int, b: int) -> list[str]:
        return [npx, "remotion", "render", "Podcast",
                str((out_dir / f"chunk-{i:03d}.mp4").resolve()),
                f"--props={props.resolve()}", f"--frames={a}-{b}"]

    # 双路并行渲染(每路独立 Remotion 进程,互不依赖;再高会争内存)
    pending = [(i, edges[i], edges[i + 1] - 1)
               for i in range(len(edges) - 1)
               if not ((out_dir / f"chunk-{i:03d}.mp4").exists()
                       and (out_dir / f"chunk-{i:03d}.mp4").stat().st_size > 1024)]
    chunks = [out_dir / f"chunk-{i:03d}.mp4" for i in range(len(edges) - 1)]
    for k in pending:
        task.log(f"待渲染块 {k[0]+1}/{len(chunks)} "
                 f"(frames {k[1]}-{k[2]}, {((k[2]-k[1])/30/60):.0f} 分钟画面)")
    for j in range(0, len(pending), 2):
        wave = pending[j:j + 2]
        procs = [(k, subprocess.Popen(render_cmd(*k), cwd=str(PODCAST_STUDIO),
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True,
                                      encoding="utf-8", errors="replace"))
                 for k in wave]
        for k, p in procs:
            out_txt = (p.communicate() or ("",))[0] or ""
            if p.returncode != 0:
                task.log(f"[render 块{k[0]}] " + out_txt[-1500:])
                raise RuntimeError(f"Remotion 渲染块 {k[0]} 失败(exit {p.returncode})")
            task.log(f"块 chunk-{k[0]:03d}.mp4 完成")
    out = task.dir / "05-成品" / f"{slug}-podcast.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    lst = out_dir / "concat.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in chunks),
                   encoding="utf-8")
    _run([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
          "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c", "copy", str(out)], task, timeout=3600)
    task.set_artifact("final_video", out)
    return (f"播客版 {len(chapters)} 章 / {total/60:.1f} 分钟 "
            f"{out.stat().st_size // 1048576}MB")


def ex_assemble_narration(task: Task) -> str:
    w = task.dir / "work"
    outdir = task.dir / "04-中文音频"
    outdir.mkdir(parents=True, exist_ok=True)
    narration = outdir / f"{task.params['slug']}-旁白.wav"
    mixed = outdir / f"{task.params['slug']}-旁白-原声低混.wav"
    _run([VENV_PY, str(TOOL_DIR / "assemble_narration.py"),
          "--runs", str(w / "narration" / "runs.json"),
          "--parts-dir", str(w / "narration" / "parts"),
          "--video", str(_src(task)),
          "--narration-out", str(narration), "--mixed-out", str(mixed),
          "--original-db", str(task.params.get("original_db") or "-22")], task,
         timeout=3600)
    task.params["_audio_path"] = str(mixed)
    task.set_artifact("zh_audio", mixed)
    task.save()
    return f"旁白主轨+原声低混 {mixed.stat().st_size // 1048576}MB"


def ex_assemble_audio(task: Task) -> str:
    w = task.dir / "work"
    slots = json.loads((w / "slots.json").read_text(encoding="utf-8"))
    total = task.params.get("_duration") or max(s["end"] for s in slots)
    out = task.dir / "04-中文音频" / f"{task.params['slug']}-zh.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([VC_PY, str(VC_DIR / "assemble_fine_runs.py"),
          "--slots", str(w / "slots.json"), "--parts-dir", str(w / "parts"),
          "--total", str(total), "--out", str(out),
          "--runs-out", str(w / "runs.json")], task, timeout=1800)
    task.set_artifact("zh_audio", out)
    dur = _probe_duration(out)
    return f"{dur/60:.1f} 分钟音轨"


def ex_zh_subtitle(task: Task) -> str:
    slug = task.params["slug"]
    srt = task.dir / "03-中文字幕" / f"{slug}-zh.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    if VIDEO_TYPES[task.type]["dims"].get("mode") == "podcast":
        # 播客版:从 props 生成,时间轴与画面字幕严格一致(不跑 ASR)
        props = PODCAST_STUDIO / f"props-{slug}.json"
        if not props.exists():
            raise RuntimeError(f"props 不存在: {props.name}")
        _run([VENV_PY, str(TOOL_DIR / "podcast_srt.py"),
              "--props", str(props), "-o", str(srt)], task, timeout=600)
        task.set_artifact("zh_subtitle", srt)
        n = len(_parse_srt(srt))
        return f"{n} 条字幕(props 对齐)"
    audio = Path(task.params.get("_audio_path") or (task.dir / "04-中文音频" / f"{slug}-zh.wav"))
    if not audio.exists():
        raise RuntimeError(f"中文音频不存在: {audio.name}")
    if task.artifacts["zh_audio"]["status"] != P_DONE:
        task.set_artifact("zh_audio", audio)
    srt = task.dir / "03-中文字幕" / f"{slug}-zh.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    _run([VENV_PY, str(TOOL_DIR / "align_srt_asr.py"),
          str(audio), "-o", str(srt), "--asr-only"], task,
         timeout=24 * 3600)
    task.set_artifact("zh_subtitle", srt)
    n = len(_parse_srt(srt))
    return f"{n} 条字幕"


def ex_render_podcast(task: Task) -> str:
    """中文播客版:章节画面 + 双音色音频 + 中文字幕。"""
    from render_podcast import prepare_chapters, render_podcast as rp
    slug = task.params["slug"]
    w = task.dir / "work"
    runs = json.loads((w / "narration" / "runs.json").read_text(encoding="utf-8"))
    voices = {}
    for spk in sorted({r["speaker"] for r in runs}):
        name = task.params.get(f"voice_{spk}") or task.params.get("voice_A") or "doubao-taotao"
        voices[spk] = name
    title = task.params.get("title") or slug
    chapters = prepare_chapters(runs, voices, w / "chapters", title)
    audio = Path(task.params.get("_audio_path") or
                 (task.dir / "04-中文音频" / f"{slug}-zh.wav"))
    srt = task.dir / "03-中文字幕" / f"{slug}-zh.srt"
    out = task.dir / "05-成品" / f"{slug}-podcast.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    rp(chapters, audio, srt, out, task.params.get("watermark") or "wzx")
    task.set_artifact("final_video", out)
    return f"播客版 {out.stat().st_size // 1048576}MB"


def ex_render(task: Task) -> str:
    t = VIDEO_TYPES[task.type]
    mode = task.params.get("render_mode") or t["default_render"]
    slug = task.params["slug"]
    out = task.dir / "05-成品" / f"{slug}-final.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    audio = Path(task.params.get("_audio_path") or (task.dir / "04-中文音频" / f"{slug}-zh.wav"))
    srt = task.dir / "03-中文字幕" / f"{slug}-zh.srt"
    if mode == "podcast_remotion":
        return ex_render_remotion_podcast(task)
    if mode == "podcast":
        return ex_render_podcast(task)
    if mode == "subtitle_only":
        # 原声保留 + 中文字幕烧录(不替换音轨)
        srt_escaped = str(srt.resolve()).replace("\\", "/").replace(":", "\:")
        vf = (f"subtitles='{srt_escaped}':force_style='Fontname=Microsoft YaHei,"
              f"FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
              f"BorderStyle=3,Outline=2,Alignment=2,MarginV=30'")
        cmd = [str(FFMPEG), "-y", "-i", str(_src(task)),
               "-vf", vf, "-c:v", "libx264", "-crf", "20", "-preset", "medium",
               "-c:a", "copy", str(out)]
        task.log(f"$ subtitle_only 渲染: {out.name}")
        subprocess.run(cmd, check=True, timeout=24*3600)
    elif mode == "original":
        _run([VENV_PY, str(TOOL_DIR / "render_original.py"),
              "--video", str(_src(task)), "--audio", str(audio),
              "--srt", str(srt), "--watermark", "wzx", "-o", str(out)],
             task, timeout=24 * 3600)
    else:
        title = task.params.get("title") or slug
        part = out.with_suffix(".part.mp4")
        _run([VENV_PY, str(TOOL_DIR / "make_cover_video.py"),
              "--gen-cover", "--audio", str(audio), "--srt", str(srt),
              "--title", title, "--watermark", "wzx", "-o", str(part)],
             task, timeout=24 * 3600)
        if part.exists():
            shutil.move(str(part), str(out))
    task.set_artifact("final_video", out)
    return f"{mode} 模式 {out.stat().st_size // 1048576}MB"


EXECUTORS = {
    "ensure_source": ex_ensure_source,
    "extract_audio": ex_extract_audio,
    "en_slots": ex_en_slots,
    "align_speakers": ex_align_speakers,
    "translate": ex_translate,
    "audit_translation": ex_audit_translation,
    "ocr_zh": ex_ocr_zh,
    "cut_items": ex_cut_items,
    "gen_audio": ex_gen_audio,
    "narration_runs": ex_narration_runs,
    "polish_audio": ex_polish_audio,
    "podcast_props": ex_podcast_props,
    "assemble_narration": ex_assemble_narration,
    "assemble_audio": ex_assemble_audio,
    "zh_subtitle": ex_zh_subtitle,
    "render": ex_render,
    "render_podcast": ex_render_podcast,
}


# =====================================================================
# 运行器
# =====================================================================

def run_task(task: Task) -> None:
    while task.current < len(task.stages):
        st = task.stages[task.current]
        if st["status"] == P_DONE:
            task.current += 1
            continue
        task.mark_stage(st["key"], P_RUNNING)
        task.status = S_RUNNING
        task.save()
        try:
            note = EXECUTORS[st["key"]](task) or "完成"
            task.mark_stage(st["key"], P_DONE, note=note)
            task.log(f"✓ {st['label']}: {note}")
            task.current += 1
        except Exception as e:  # noqa: BLE001
            task.mark_stage(st["key"], P_FAILED, error=str(e)[:500])
            task.status = S_FAILED
            task.save()
            task.log(f"✗ {st['label']} 失败: {str(e)[:300]}")
            return
    task.status = S_DONE
    task.save()
    task.log("任务完成")


def start_runner(task: Task) -> None:
    threading.Thread(target=run_task, args=(task,), daemon=True).start()


def retry_stage(task: Task) -> bool:
    if task.status != S_FAILED:
        return False
    for i, st in enumerate(task.stages):
        if st["status"] == P_FAILED:
            st["status"], st["error"] = P_PENDING, None
            task.current = i
            task.status = S_RUNNING
            task.save()
            if MODE == "local":
                start_runner(task)  # server 模式:重置后等 PC 代理领取
            return True
    return False


def list_tasks(newest_first: bool = True) -> list[Task]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(STATE_DIR.glob("*.json"), reverse=newest_first):
        try:
            out.append(Task.load(p))
        except Exception:  # legacy schema 跳过
            continue
    return out


def load_task(task_id: str) -> Task | None:
    p = STATE_DIR / f"{task_id}.json"
    return Task.load(p) if p.exists() else None


# =====================================================================
# 环境自检
# =====================================================================

def env_selftest(need_model: str | None = None) -> dict:
    res = {"ollama": False, "ollama_model": False, "wsl_cosyvoice": False,
           "nas": False, "ffmpeg": False, "detail": []}
    model = need_model or DEFAULT_TRANSLATE_MODEL
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",
                                    timeout=5) as r:
            tags = json.loads(r.read())
        names = [m["name"] for m in tags.get("models", [])]
        res["ollama"] = True
        res["ollama_model"] = any(n.split(":")[0] == model.split(":")[0]
                                  for n in names)
        res["detail"].append(
            f"Ollama ✓ ({model}: 已就绪)" if res["ollama_model"] else
            f"Ollama ✓ 但 {model} 未拉取: ollama pull {model}")
    except Exception as e:
        res["detail"].append(f"Ollama ✗ {str(e)[:60]}(ollama serve?)")
    try:
        subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-c",
                        f"test -x {WSL_PY}"], check=True, timeout=30,
                       capture_output=True)
        res["wsl_cosyvoice"] = True
        res["detail"].append("WSL CosyVoice(GPU) ✓")
    except Exception:
        res["detail"].append("WSL CosyVoice ✗(将回退 Windows CPU,速度约 1/3)")
    try:
        subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-c",
                        "test -x ~/qwen-aligner-venv/bin/python"],
                       check=True, timeout=30, capture_output=True)
        res["force_aligner"] = True
        res["detail"].append("ForcedAligner 词级对齐 ✓(align_speakers 阶段可用)")
    except Exception:
        res["detail"].append("ForcedAligner ✗(align_speakers 阶段将自动跳过;"
                             "安装: WSL python3.12 -m venv ~/qwen-aligner-venv"
                             " && pip install qwen-asr)")
    try:
        subprocess.run(["ssh", "nas", "true"], check=True, timeout=15,
                       capture_output=True)
        res["nas"] = True
        res["detail"].append(f"NAS ssh ✓ ({NAS_BASE})")
    except Exception:
        res["detail"].append("NAS ssh ✗(产物将只留在本地)")
    res["ffmpeg"] = FFMPEG.exists()
    res["detail"].append(f"ffmpeg {'✓' if res['ffmpeg'] else '✗'}")
    return res


# =====================================================================
# HTTP 服务
# =====================================================================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/admin", "/admin/"):
            return self._html()
        if self.path == "/api/types":
            return self._json(VIDEO_TYPES)
        if self.path == "/api/voices":
            if MODE == "local":
                return self._json(voice_lib.list_voices())
            return self._json(_read_json(DATA_DIR / "voices.json", []))
        if self.path.startswith("/api/library"):
            return self._library()
        if self.path.startswith("/api/download"):
            return self._download()
        if self.path == "/api/status":
            act = _read_json(ACTIVE_PATH, {})
            ag = _read_json(AGENT_STATE_PATH, {})
            import datetime as _dt
            seen = ag.get("last_seen")
            online = bool(seen and _dt.datetime.now()
                          - _dt.datetime.fromisoformat(seen)
                          < _dt.timedelta(minutes=3))
            return self._json({"mode": MODE, "agent_online": online,
                               "agent_last_seen": seen,
                               "active_task": act.get("task_id")})
        if self.path == "/api/tasks":
            return self._json([t.brief() for t in list_tasks()])
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9-]+)", self.path)
        if m:
            t = load_task(m.group(1))
            if not t:
                return self._json({"ok": False, "error": "任务不存在"}, 404)
            return self._json(t.detail())
        return self._json({"ok": False, "error": "not found"}, 404)

    def _html(self):
        p = TOOL_DIR / "admin.html"
        body = p.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/api/tasks":
            return self._create()
        if self.path == "/api/voices":
            return self._create_voice()
        if self.path == "/api/selftest":
            if MODE == "server":
                ag = _read_json(AGENT_STATE_PATH, {})
                env = ag.get("env") or {}
                det = [f"控制面(NAS 容器) ✓ 媒体库: {'✓' if MEDIA_ROOT and MEDIA_ROOT.exists() else '✗ 未挂载'}"]
                det.append(f"PC 代理: {'✓ 在线' if ag.get('last_seen') else '✗ 未接入'}")
                if env:
                    det.append(f"代理环境: Ollama {'✓' if env.get('ollama_model') else '✗'}"
                               f" | CosyVoice {'✓' if env.get('wsl_cosyvoice') else '✗'}"
                               f" | NAS {'✓' if env.get('nas') else '✗'}")
                else:
                    det.append("(等待代理上报环境详情)")
                return self._json({"detail": det})
            return self._json(env_selftest(self._body().get("model")))
        if self.path.startswith("/api/agent/"):
            return self._agent(self.path)
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9-]+)/action", self.path)
        if m:
            t = load_task(m.group(1))
            if not t:
                return self._json({"ok": False, "error": "任务不存在"}, 404)
            body = self._body()
            action = body.get("action")
            if action == "retry":
                ok = retry_stage(t)
                return self._json(
                    {"ok": ok, "error": None if ok else "任务不在失败状态"})
            if action == "reupload":
                slot = body.get("slot")
                info = t.artifacts.get(slot or "")
                if info and info["local_path"]:
                    nas = t.upload_to_nas(slot, ROOT / info["local_path"])
                    t.save()
                    return self._json({"ok": bool(nas), "nas_path": nas})
                return self._json({"ok": False, "error": "槽位无产物"}, 400)
            return self._json({"ok": False, "error": f"未知 action"}, 400)
        return self._json({"ok": False, "error": "not found"}, 404)

    def _library(self):
        """浏览 NAS 媒体目录:?dir=<相对路径>(默认原片库)。
        限制在 MEDIA_ROOT 内防目录穿越;返回文件/子目录列表。"""
        if not MEDIA_ROOT or not MEDIA_ROOT.exists():
            return self._json({"ok": False,
                               "error": "未挂载媒体目录(STUDIO_MEDIA)"}, 400)
        from urllib.parse import urlparse, parse_qs, unquote
        q = parse_qs(urlparse(self.path).query)
        rel = unquote((q.get("dir") or [""])[0]).replace("\\", "/").lstrip("/")
        base = (MEDIA_ROOT / rel).resolve()
        if not str(base).startswith(str(MEDIA_ROOT.resolve())):
            return self._json({"ok": False, "error": "非法路径"}, 400)
        if not base.exists():
            return self._json({"ok": False, "error": "目录不存在"}, 404)
        items = []
        for p in sorted(base.iterdir()):
            if p.name.startswith((".", "@", "#")):
                continue
            is_dir = p.is_dir()
            if is_dir:
                items.append({"name": p.name, "dir": True})
            elif p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".avi",
                                      ".vtt", ".srt", ".mp3", ".wav", ".m4a"):
                items.append({"name": p.name, "dir": False,
                              "size": p.stat().st_size})
        # NAS 绝对路径(供建任务用 nas: 前缀)
        rel_clean = str((MEDIA_ROOT / rel).resolve().relative_to(
            MEDIA_ROOT.resolve())) if rel else ""
        nas_abs = (NAS_MEDIA_ABS + "/" + rel_clean).rstrip("/")
        return self._json({"ok": True, "dir": rel, "nas_abs": nas_abs,
                           "items": items})

    def _download(self):
        """流式下载媒体文件:?path=<相对 MEDIA_ROOT 的路径>。"""
        if not MEDIA_ROOT or not MEDIA_ROOT.exists():
            self._json({"ok": False, "error": "未挂载媒体目录"}, 400)
            return
        from urllib.parse import urlparse, parse_qs, unquote
        q = parse_qs(urlparse(self.path).query)
        rel = unquote((q.get("path") or [""])[0]).replace("\\", "/").lstrip("/")
        f = (MEDIA_ROOT / rel).resolve()
        if not str(f).startswith(str(MEDIA_ROOT.resolve())) or not f.is_file():
            self._json({"ok": False, "error": "非法路径"}, 400)
            return
        size = f.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition",
                         "attachment; filename*=UTF-8''" +
                         __import__("urllib.parse", fromlist=["quote"]).quote(f.name))
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(f, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except Exception:
                    break  # 客户端断开

    def _agent(self, path: str):
        """代理通道:poll 领任务 / stage / artifact / log / done / voices。
        鉴权:X-Agent-Token 与 DATA_DIR/.agent-token 一致。"""
        tok = self.headers.get("X-Agent-Token", "")
        want = _read_json(DATA_DIR / ".agent-token", {}).get("token")
        if not want:
            import secrets
            want = secrets.token_hex(8)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _write_json(DATA_DIR / ".agent-token", {"token": want})
        if tok != want:
            return self._json({"ok": False, "error": "bad token"}, 401)
        body = self._body()
        act = path.rsplit("/", 1)[-1]

        if act == "poll":
            state = _read_json(AGENT_STATE_PATH, {})
            state.update({
                "last_seen": __import__("datetime").datetime.now().isoformat(),
                "agent": body.get("agent", "?")})
            if body.get("env"):  # 代理上报的 PC 环境自检
                state["env"] = body["env"]
            _write_json(AGENT_STATE_PATH, state)
            t = agent_claim_task(body.get("agent", "?"))
            if t is None:
                return self._json({"task": None})
            return self._json({"task": t.detail()})

        if act == "voices":
            _write_json(DATA_DIR / "voices.json", body.get("voices", []))
            return self._json({"ok": True})

        task_id = body.get("task_id", "")
        t = load_task(task_id)
        if not t:
            return self._json({"ok": False, "error": "任务不存在"}, 404)
        agent_heartbeat(task_id)

        if act == "stage":
            t.mark_stage(body.get("key"), body.get("status"),
                         error=body.get("error"), note=body.get("note"))
            if body.get("advance"):
                t.current += 1
                t.save()
            return self._json({"ok": True})
        if act == "artifact":
            info = t.artifacts.get(body.get("slot") or "")
            if info is None:
                return self._json({"ok": False, "error": "未知槽"}, 400)
            info.update(status=P_DONE,
                        local_path=body.get("local_path"),
                        size=body.get("size"),
                        nas_path=body.get("nas_path"),
                        error=body.get("error"))
            t.save()
            return self._json({"ok": True})
        if act == "log":
            with open(t.log_path, "a", encoding="utf-8") as f:
                for line in body.get("lines", []):
                    f.write(line + chr(10))
            return self._json({"ok": True})
        if act == "done":
            t.status = body.get("status") or S_DONE
            t.save()
            agent_release(task_id)
            return self._json({"ok": True})
        return self._json({"ok": False, "error": f"未知 agent 动作 {act}"})

    def _create(self):
        d = self._body()
        tkey = d.get("type", "")
        if tkey not in VIDEO_TYPES:
            return self._json({"ok": False, "error": f"未知类型 {tkey}"}, 400)
        spec = VIDEO_TYPES[tkey]
        params = d.get("params", {})
        for p in spec["params"]:
            if p["required"] and not params.get(p["key"]):
                return self._json(
                    {"ok": False, "error": f"缺少必填参数 {p['label']}"}, 400)
        slug = params.get("slug", "").strip()
        # \w 在 Python3 默认含中文;允许中文任务名(NAS 目录名友好)
        if not re.fullmatch(r"[\w-]{2,40}", slug):
            return self._json({"ok": False,
                               "error": "代号仅限中文/字母/数字/-_"}, 400)
        if (STUDIO / slug).exists():
            return self._json({"ok": False,
                               "error": f"代号 {slug} 已存在"}, 400)
        # 多人类型:B 音色必填,或开启自动克隆原声(否则两人同声)
        if VIDEO_TYPES[tkey]["dims"].get("speakers") == 2 \
                and not params.get("clone_original") \
                and not params.get("voice_B"):
            return self._json({"ok": False, "error":
                               "多人视频需指定 voice_B(或开启自动克隆原声),"
                               "否则两位说话人会是同一个声音"}, 400)
        if params.get("clone_original") and not params.get("anchors"):
            return self._json({"ok": False, "error":
                               "自动克隆原声需要填声纹锚点 anchors"}, 400)
        task = Task(tkey, params)
        task.save()
        task.log(f"创建: {spec['name']} / {slug}")
        if MODE == "local":
            start_runner(task)
        else:
            task.log("排队等待 PC 代理领取")
        return self._json({"ok": True, "task": task.brief()})

    def _create_voice(self):
        d = self._body()
        try:
            meta = voice_lib.create(
                d["name"], Path(d["ref_audio"]), d["ref_text"],
                d.get("note", ""))
            return self._json({"ok": True, "voice": meta})
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": str(e)[:200]}, 400)


def _lan_ips() -> list[str]:
    import socket
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.", "172.2",
                                  "192.168.106.", "192.168.220.")):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="统一视频汉化平台 v2")
    ap.add_argument("--host", default="0.0.0.0",
                    help="默认 0.0.0.0 局域网可访问")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if MODE == "local":
        voice_lib.seed_defaults()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[studio] http://127.0.0.1:{args.port}")
    for ip in _lan_ips():
        print(f"[studio] 局域网: http://{ip}:{args.port}")
    print(f"[studio] 类型: {', '.join(VIDEO_TYPES)}")
    print(f"[studio] NAS: {NAS_BASE} | 翻译默认: {DEFAULT_TRANSLATE_MODEL}")
    if MODE == "server":
        tok = _read_json(DATA_DIR / ".agent-token", {}).get("token")
        print(f"[studio] server 模式:等待 PC 代理接入(数据目录 {DATA_DIR})")
        print(f"[studio] 代理 token: {tok}(PC 代理 STUDIO_TOKEN 环境变量)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[studio] 退出")


if __name__ == "__main__":
    main()
