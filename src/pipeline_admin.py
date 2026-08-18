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

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import voice_lib

ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "src"
VENV_PY = str(ROOT / "work" / ".venv-ocr" / "Scripts" / "python.exe")
VC_DIR = ROOT / "work" / "voice-clone-demo"
VC_PY = str(VC_DIR / ".venv" / "Scripts" / "python.exe")
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"
STUDIO = ROOT / "work" / "studio"
STATE_DIR = STUDIO / "tasks"
PORT = 8766
NAS_BASE = "/volume1/share/视频"
WSL_PY = "/home/comfy/cosy-gpu-venv/bin/python"
WSL_ENV = ("HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 "
           "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1")
DEFAULT_TRANSLATE_MODEL = "qwen3:14b"

# =====================================================================
# 五件套槽位定义
# =====================================================================

ARTIFACT_SLOTS = {
    "source_video": {"label": "视频源", "nas_dir": "01-视频源"},
    "en_subtitle": {"label": "英文字幕", "nas_dir": "02-英文字幕"},
    "zh_subtitle": {"label": "中文字幕", "nas_dir": "03-中文字幕"},
    "zh_audio": {"label": "中文音频", "nas_dir": "04-中文音频"},
    "final_video": {"label": "成品", "nas_dir": "05-成品"},
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
    {"key": "render_mode", "label": "渲染模式", "type": "choice",
     "choices": ["original", "cover"], "required": False},
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
            {"key": "voice_A", "label": "说话人A音色", "type": "voice",
             "required": False},
            {"key": "voice_B", "label": "说话人B音色", "type": "voice",
             "required": False},
            {"key": "translate_model", "label": "翻译模型", "type": "str",
             "required": False},
        ],
        "stages": ["ensure_source", "extract_audio", "en_slots", "translate",
                   "gen_audio", "assemble_audio", "zh_subtitle", "render"],
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
            {"key": "voice_A", "label": "音色", "type": "voice",
             "required": False},
            {"key": "translate_model", "label": "翻译模型", "type": "str",
             "required": False},
        ],
        "stages": ["ensure_source", "extract_audio", "en_slots", "translate",
                   "gen_audio", "assemble_audio", "zh_subtitle", "render"],
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
        "stages": ["ensure_source", "extract_audio", "en_slots", "translate",
                   "gen_audio", "assemble_audio", "zh_subtitle", "render"],
    },
    "none_2": {
        "key": "none_2", "name": "无字幕多人视频",
        "desc": "无字幕多人视频。当前按单音色整片处理(多人声纹分离需锚点,"
                "暂不自动;可先按单人跑或后续增强)。",
        "dims": {"subtitle": "none", "speakers": 2},
        "default_render": "original",
        "params": _TYPE_COMMON_PARAMS + [
            {"key": "voice_A", "label": "音色", "type": "voice",
             "required": False},
            {"key": "translate_model", "label": "翻译模型", "type": "str",
             "required": False},
        ],
        "stages": ["ensure_source", "extract_audio", "en_slots", "translate",
                   "gen_audio", "assemble_audio", "zh_subtitle", "render"],
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
    "translate": "Ollama 翻译",
    "ocr_zh": "OCR 中文字幕",
    "cut_items": "文本切块",
    "gen_audio": "CosyVoice 配音",
    "assemble_audio": "时间轴合成",
    "zh_subtitle": "ASR 中文字幕",
    "render": "渲染成品",
}


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
        s = next(x for x in self.stages if x["key"] == key)
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
        nas_dir = f"{NAS_BASE}/{slug}/{sub}"
        try:
            subprocess.run(["ssh", "nas", f"mkdir -p '{nas_dir}'"],
                           check=True, timeout=30, capture_output=True)
            subprocess.run(["scp", str(path), f"nas:{nas_dir}/"],
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
    inner = (f"cd /mnt/e/ai/bilibiliVideoToZH && env {WSL_ENV} "
             f"{WSL_PY} {script_rel} " + " ".join(f'"{a}"' for a in args))
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
    if dims["subtitle"] == "en_vtt":
        anchors = task.params.get("anchors") or '{"A": [3.5, 18.8]}'
        vtt = Path(task.params["vtt_path"])
        if not vtt.is_absolute():
            vtt = ROOT / vtt
        _run([VC_PY, str(VC_DIR / "prepare_fine_slots.py"),
              "--vtt", str(vtt),
              "--audio", str(w / "audio16k.wav"),
              "--anchors", anchors,
              "--out", str(slots_path)], task, timeout=1800)
    else:  # none → whisper
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
    _run([VC_PY, str(VC_DIR / "translate_fine_batches.py"),
          "--slots", str(w / "slots.json"), "--out", str(zh_path),
          "--model", model], task, timeout=24 * 3600)
    zh = json.loads(zh_path.read_text(encoding="utf-8"))
    slots = json.loads((w / "slots.json").read_text(encoding="utf-8"))
    if len(zh) < len(slots) * 0.9:
        raise RuntimeError(f"翻译不完整: {len(zh)}/{len(slots)}")
    return f"{len(zh)}/{len(slots)} 槽已译({model})"


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
    m = re.search(r"episode-(\d+)", task.params.get("source_path", ""))
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


def _build_voice_inputs(task: Task) -> tuple[Path, Path]:
    """构造 generate_voice 的 items/refs 输入。"""
    w = task.dir / "work"
    dims = VIDEO_TYPES[task.type]["dims"]
    if dims["subtitle"] == "zh_hard":
        items = json.loads((w / "items.json").read_text(encoding="utf-8"))
    else:
        slots = json.loads((w / "slots.json").read_text(encoding="utf-8"))
        zh = json.loads((w / "slots_zh.json").read_text(encoding="utf-8"))
        items = [{"id": s["id"], "speaker": s["speaker"],
                  "text": zh[str(s["id"])]} for s in slots]
        (w / "items.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    speakers = sorted({i["speaker"] for i in items})
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
    base_args = ["--items-json", str(items_path),
                 "--refs-json", str(refs_path),
                 "--out-dir", str(w / "parts")]
    args = list(base_args) + (["--concat-out", str(concat)] if concat else [])
    try:
        _wsl_run("work/voice-clone-demo/generate_voice.py", args, task)
    except RuntimeError as e:
        task.log(f"WSL GPU 失败({str(e)[:80]}),Windows CPU 回退(慢)")
        _run([VC_PY, str(VC_DIR / "generate_voice.py")] + args, task,
             timeout=48 * 3600)
    n = len(list((w / "parts").glob("*.wav")))
    return f"{n} 段配音" + ("(已拼接整轨)" if concat else "")


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
    audio = task.dir / "04-中文音频" / f"{slug}-zh.wav"
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


def ex_render(task: Task) -> str:
    t = VIDEO_TYPES[task.type]
    mode = task.params.get("render_mode") or t["default_render"]
    slug = task.params["slug"]
    out = task.dir / "05-成品" / f"{slug}-final.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    audio = task.dir / "04-中文音频" / f"{slug}-zh.wav"
    srt = task.dir / "03-中文字幕" / f"{slug}-zh.srt"
    if mode == "original":
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
    "translate": ex_translate,
    "ocr_zh": ex_ocr_zh,
    "cut_items": ex_cut_items,
    "gen_audio": ex_gen_audio,
    "assemble_audio": ex_assemble_audio,
    "zh_subtitle": ex_zh_subtitle,
    "render": ex_render,
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
            start_runner(task)
            return True
    return False


def list_tasks() -> list[Task]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(STATE_DIR.glob("*.json"), reverse=True):
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
            return self._json(voice_lib.list_voices())
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
            return self._json(env_selftest(self._body().get("model")))
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
        if not re.fullmatch(r"[A-Za-z0-9_-]{2,40}", slug):
            return self._json({"ok": False, "error": "代号仅限字母数字-_"}, 400)
        if (STUDIO / slug).exists():
            return self._json({"ok": False,
                               "error": f"代号 {slug} 已存在"}, 400)
        task = Task(tkey, params)
        task.save()
        task.log(f"创建: {spec['name']} / {slug}")
        start_runner(task)
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
    voice_lib.seed_defaults()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[studio] http://127.0.0.1:{args.port}")
    for ip in _lan_ips():
        print(f"[studio] 局域网: http://{ip}:{args.port}")
    print(f"[studio] 类型: {', '.join(VIDEO_TYPES)}")
    print(f"[studio] NAS: {NAS_BASE} | 翻译默认: {DEFAULT_TRANSLATE_MODEL}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[studio] 退出")


if __name__ == "__main__":
    main()
