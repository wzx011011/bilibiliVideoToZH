"""多流水线管理后台 —— 多种视频类型的统一制作管理。

产品形态统一为:封面(或指定画面)+ 中文配音音频 + 中文字幕 → MP4。
差异在三种资源的生成方式,由维度组合决定流水线:

    源语言(zh/en) × 字幕来源(画面硬字幕OCR / 语音ASR) × 说话人(1 / 2+)

内置流水线:
  course       课程·中文·硬字幕·单人  (OCR→分块→豆包润色朗读→ASR字幕→渲染)
  interview_en 访谈·英文·无字幕·多人 (英文ASR→说话人分离→分块翻译→多音色朗读→ASR字幕→渲染)
  interview_zh 访谈·中文·无字幕·多人 (中文ASR→说话人分离→分块润色→多音色朗读→ASR字幕→渲染)

半自动环节与现有课程流程一致:分块完成后需要用户在浏览器扩展里手动发送
(绕豆包签名风控),本服务轮询 doubao-send.json 自动感知发送完成。

服务只监听 127.0.0.1:8766(与 doubao_bridge 的 8765 并存,互不影响)。

用法:
  work/.venv-ocr/Scripts/python.exe src/pipeline_admin.py
  打开 http://127.0.0.1:8766
"""
from __future__ import annotations

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

import interview_lib as ilib

ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "src"
VENV_PY = str(ROOT / "work" / ".venv-ocr" / "Scripts" / "python.exe")
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
STATE_DIR = ROOT / "work" / "pipeline-admin"
TASKS_DIR = STATE_DIR / "tasks"
PORT = 8766
LOG_TAIL_LINES = 120

# 默认音色(doubao_reader 模块级默认为桃桃女声;可在建任务时按说话人指定)
DEFAULT_SPEAKERS_MAP = {"A": "", "B": ""}  # 空 = 用默认桃桃


# =====================================================================
# 流水线定义(维度 → 阶段序列)
# =====================================================================

PIPELINES: dict[str, dict] = {
    "course": {
        "key": "course",
        "name": "课程 · 中文硬字幕 · 单人",
        "desc": "B站课程视频(画面自带中文字幕)。OCR 提取字幕 → 分块 → 豆包润色朗读 → ASR 字幕 → 封面渲染。",
        "dims": {"lang": "zh", "subtitle_source": "ocr", "speakers": 1},
        "params": [
            {"key": "episode", "label": "集数", "type": "int", "required": True,
             "hint": "如 22,对应 work/ep-22"},
            {"key": "url", "label": "B站URL(可选,缺原片时下载)", "type": "str", "required": False},
        ],
        "stages": [
            {"key": "ensure_source", "label": "准备原片", "type": "auto"},
            {"key": "ocr_subtitle", "label": "OCR 提取字幕", "type": "auto"},
            {"key": "chunk_prep", "label": "分块", "type": "auto"},
            {"key": "send_chunks", "label": "扩展发送(手动)", "type": "manual"},
            {"key": "harvest_audio", "label": "朗读配音", "type": "auto"},
            {"key": "asr_subtitle", "label": "ASR 字幕", "type": "auto"},
            {"key": "render", "label": "渲染视频", "type": "auto"},
        ],
    },
    "interview_en": {
        "key": "interview_en",
        "name": "访谈 · 英文 · 多人",
        "desc": "英文访谈(YouTube 等,画面无字幕)。英文 ASR → 说话人分离 → 分角色翻译 → 多音色朗读 → ASR 字幕 → 封面渲染。",
        "dims": {"lang": "en", "subtitle_source": "asr", "speakers": 2},
        "params": [
            {"key": "video_path", "label": "视频路径", "type": "str", "required": True,
             "hint": "如 youtube/elon-musk/xxx.mp4"},
            {"key": "slug", "label": "任务代号", "type": "str", "required": True,
             "hint": "英文短名,如 musk-lex400"},
            {"key": "title", "label": "封面标题", "type": "str", "required": False},
            {"key": "speaker_A_name", "label": "说话人A(先开口,通常是主持人)", "type": "str", "required": False},
            {"key": "speaker_B_name", "label": "说话人B(嘉宾)", "type": "str", "required": False},
            {"key": "speaker_A_voice", "label": "A音色ID(空=默认女声)", "type": "str", "required": False},
            {"key": "speaker_B_voice", "label": "B音色ID(空=默认女声)", "type": "str", "required": False},
        ],
        "stages": [
            {"key": "ensure_source", "label": "检查视频", "type": "auto"},
            {"key": "extract_audio", "label": "提取音频", "type": "auto"},
            {"key": "asr_source", "label": "英文转写", "type": "auto"},
            {"key": "diarize", "label": "说话人分离", "type": "auto"},
            {"key": "chunk_by_speaker", "label": "分角色分块", "type": "auto"},
            {"key": "send_chunks", "label": "扩展发送翻译(手动)", "type": "manual"},
            {"key": "harvest_multi_voice", "label": "多音色朗读", "type": "auto"},
            {"key": "asr_subtitle", "label": "ASR 字幕", "type": "auto"},
            {"key": "render", "label": "渲染视频", "type": "auto"},
        ],
    },
    "interview_zh": {
        "key": "interview_zh",
        "name": "访谈 · 中文 · 多人",
        "desc": "中文访谈(画面无字幕)。中文 ASR → 说话人分离 → 分角色润色 → 多音色朗读 → ASR 字幕 → 封面渲染。",
        "dims": {"lang": "zh", "subtitle_source": "asr", "speakers": 2},
        "params": [
            {"key": "video_path", "label": "视频路径", "type": "str", "required": True},
            {"key": "slug", "label": "任务代号", "type": "str", "required": True},
            {"key": "title", "label": "封面标题", "type": "str", "required": False},
            {"key": "speaker_A_name", "label": "说话人A名称", "type": "str", "required": False},
            {"key": "speaker_B_name", "label": "说话人B名称", "type": "str", "required": False},
            {"key": "speaker_A_voice", "label": "A音色ID(空=默认女声)", "type": "str", "required": False},
            {"key": "speaker_B_voice", "label": "B音色ID(空=默认女声)", "type": "str", "required": False},
        ],
        "stages": [
            {"key": "ensure_source", "label": "检查视频", "type": "auto"},
            {"key": "extract_audio", "label": "提取音频", "type": "auto"},
            {"key": "asr_source", "label": "中文转写", "type": "auto"},
            {"key": "diarize", "label": "说话人分离", "type": "auto"},
            {"key": "chunk_by_speaker", "label": "分角色分块", "type": "auto"},
            {"key": "send_chunks", "label": "扩展发送润色(手动)", "type": "manual"},
            {"key": "harvest_multi_voice", "label": "多音色朗读", "type": "auto"},
            {"key": "asr_subtitle", "label": "ASR 字幕", "type": "auto"},
            {"key": "render", "label": "渲染视频", "type": "auto"},
        ],
    },
}


# =====================================================================
# 任务存储与状态机
# =====================================================================

STAGE_PENDING = "pending"
STAGE_RUNNING = "running"
STAGE_WAITING = "waiting_user"
STAGE_DONE = "done"
STAGE_FAILED = "failed"

TASK_RUNNING = "running"        # 自动阶段执行中
TASK_WAITING = "waiting_user"   # 等待用户(扩展发送)
TASK_DONE = "done"
TASK_FAILED = "failed"

_lock = threading.Lock()


class Task:
    def __init__(self, pipeline_key: str, name: str, params: dict):
        self.id = time.strftime("%Y%m%d-") + uuid.uuid4().hex[:8]
        self.pipeline = pipeline_key
        self.name = name
        self.params = params
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.status = TASK_RUNNING
        self.stages = [dict(s, status=STAGE_PENDING, started_at=None,
                            ended_at=None, error=None, note=None)
                       for s in PIPELINES[pipeline_key]["stages"]]
        self.current = 0
        self.log_path = TASKS_DIR / f"{self.id}.log"
        self.dir = TASKS_DIR / self.id

    # ---------- 持久化 ----------

    @property
    def json_path(self) -> Path:
        return TASKS_DIR / f"{self.id}.json"

    def save(self) -> None:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "id": self.id, "pipeline": self.pipeline, "name": self.name,
            "params": self.params, "created_at": self.created_at,
            "status": self.status, "current": self.current,
            "stages": self.stages,
        }
        self.json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Task":
        data = json.loads(path.read_text(encoding="utf-8"))
        t = cls.__new__(cls)
        t.id = data["id"]
        t.pipeline = data["pipeline"]
        t.name = data["name"]
        t.params = data["params"]
        t.created_at = data["created_at"]
        t.status = data["status"]
        t.current = data["current"]
        t.stages = data["stages"]
        t.log_path = TASKS_DIR / f"{t.id}.log"
        t.dir = TASKS_DIR / t.id
        return t

    # ---------- 日志 ----------

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(f"[{self.id}] {line}", flush=True)
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def log_tail(self, n: int = LOG_TAIL_LINES) -> list[str]:
        if not self.log_path.exists():
            return []
        return self.log_path.read_text(encoding="utf-8").splitlines()[-n:]

    # ---------- 状态 ----------

    def stage(self, key: str) -> dict | None:
        return next((s for s in self.stages if s["key"] == key), None)

    def mark(self, key: str, status: str, error: str | None = None,
             note: str | None = None) -> None:
        s = self.stage(key)
        if not s:
            return
        if status == STAGE_RUNNING:
            s["started_at"] = time.strftime("%H:%M:%S")
        if status in (STAGE_DONE, STAGE_FAILED):
            s["ended_at"] = time.strftime("%H:%M:%S")
        s["status"] = status
        if error is not None:
            s["error"] = error
        if note is not None:
            s["note"] = note
        self.save()

    def brief(self) -> dict:
        return {"id": self.id, "pipeline": self.pipeline, "name": self.name,
                "status": self.status, "created_at": self.created_at,
                "stages": [{"key": s["key"], "label": s["label"],
                            "type": s["type"], "status": s["status"]}
                           for s in self.stages],
                "products": self.products()}

    def detail(self) -> dict:
        d = self.brief()
        d["params"] = self.params
        d["log"] = self.log_tail()
        d["products"] = self.products()
        return d

    def products(self) -> dict:
        """汇总本任务产物(存在才报)。"""
        out: dict[str, str] = {}
        if self.pipeline.startswith("interview"):
            w = ROOT / "work" / "interview" / self.params.get("slug", "")
            for key, p in [("audio", w / "audio.mp3"),
                           ("subtitle", w / "asr.srt"),
                           ("video", ROOT / "videos" / f"{self.params.get('slug','')}.mp4"),
                           ("chunks_dir", w / "chunks")]:
                if p.exists():
                    out[key] = str(p.relative_to(ROOT))
        else:
            ep = int(self.params.get("episode", 0))
            for key, p in [("audio", ROOT / "work" / f"ep-{ep:02d}" / f"episode-{ep:02d}-audio.mp3"),
                           ("subtitle", ROOT / "work" / f"ep-{ep:02d}" / f"episode-{ep:02d}-asr.srt"),
                           ("video", ROOT / "videos" / f"episode-{ep:02d}.mp4"),
                           ("chunks_dir", ROOT / "work" / f"ep-{ep:02d}" / "chunks")]:
                if p.exists():
                    out[key] = str(p.relative_to(ROOT))
        return out


# =====================================================================
# 阶段执行器
# =====================================================================

def _run(cmd: list[str], task: Task, cwd: Path = ROOT) -> str:
    """跑子进程,输出实时进日志,失败抛 RuntimeError。"""
    task.log("$ " + " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.stdout:
        task.log(proc.stdout.rstrip())
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        task.log("[stderr] " + "\n".join(err[-15:]))
        raise RuntimeError("命令失败(exit %d): %s" % (proc.returncode, cmd[0]))
    return proc.stdout


def _mk(argv: list[str], task: Task) -> None:
    """make_episode 系列子进程。"""
    _run([VENV_PY, str(TOOL_DIR / "make_episode.py")] + argv, task)


# ---------- course 流水线 ----------

def _ep_dir(task: Task) -> Path:
    ep = int(task.params["episode"])
    return ROOT / "work" / f"ep-{ep:02d}"


def ex_course_ensure_source(task: Task) -> str:
    ep = int(task.params["episode"])
    video = ROOT / "downloads" / f"episode-{ep:02d}.mp4"
    if video.exists():
        return f"原片已存在: {video.name}"
    url = task.params.get("url")
    if not url:
        raise RuntimeError(f"原片不存在且未提供 URL: {video}")
    _run([VENV_PY, str(TOOL_DIR / "download.py"), url,
          "--episode", str(ep)], task)
    if not video.exists():
        raise RuntimeError("下载完成但未找到预期文件 " + video.name)
    return "已下载原片"


def ex_course_ocr(task: Task) -> str:
    ep = int(task.params["episode"])
    final_srt = ROOT / "subtitles" / f"episode-{ep:02d}.zh-CN.srt"
    if final_srt.exists():
        return f"字幕已存在,跳过: {final_srt.name}"
    video = ROOT / "downloads" / f"episode-{ep:02d}.mp4"
    out_dir = _ep_dir(task)
    _run([VENV_PY, str(TOOL_DIR / "subtitle_ocr.py"),
          "--input", str(video), "--output", str(out_dir)], task)
    ocr_srt = out_dir / f"episode-{ep:02d}.zh-CN-ocr.srt"
    if not ocr_srt.exists():
        raise RuntimeError("OCR 未产出 srt")
    final_srt.parent.mkdir(exist_ok=True)
    shutil.copy2(ocr_srt, final_srt)
    return f"OCR 完成 → {final_srt.name}"


def ex_course_chunk_prep(task: Task) -> str:
    ep = task.params["episode"]
    _mk(["--episode", str(ep), "--step", "prep"], task)
    return "分块完成,待扩展发送"


def ex_course_send_chunks(task: Task) -> None:
    pass  # manual 阶段,由 poll/manual gate 推进


def ex_course_harvest_audio(task: Task) -> str:
    ep = task.params["episode"]
    _mk(["--episode", str(ep), "--step", "audio"], task)
    return "配音音频完成"


def ex_course_asr_subtitle(task: Task) -> str:
    ep = int(task.params["episode"])
    try:
        _mk(["--episode", str(ep), "--step", "subtitle"], task)
        return "ASR 字幕完成"
    except RuntimeError as e:
        # 个别集缺 harvested_chunks 记录 → 绕过 gen-srt 直接 ASR-only
        task.log(f"make_episode subtitle 失败({e}),回退直接 ASR-only")
        audio = _ep_dir(task) / f"episode-{ep:02d}-audio.mp3"
        out = _ep_dir(task) / f"episode-{ep:02d}-asr.srt"
        _run([VENV_PY, str(TOOL_DIR / "align_srt_asr.py"),
              str(audio), "-o", str(out), "--asr-only"], task)
        return "ASR 字幕完成(回退路径)"


def ex_course_render(task: Task) -> str:
    ep = task.params["episode"]
    _mk(["--episode", str(ep), "--step", "video"], task)
    # Windows Defender 偶发锁 rename:.part 已生成时手动救回
    out = ROOT / "videos" / f"episode-{int(ep):02d}.mp4"
    part = out.with_suffix(".part.mp4")
    if not out.exists() and part.exists():
        time.sleep(3)
        shutil.move(str(part), str(out))
        task.log("rename 被占用,已手动救回 .part.mp4")
    if not out.exists():
        raise RuntimeError("渲染后未找到成品 " + out.name)
    return f"成品: {out.name}"


# ---------- interview 流水线 ----------

def _iv_dir(task: Task) -> Path:
    return ROOT / "work" / "interview" / task.params["slug"]


def _iv_lang(task: Task) -> str:
    return PIPELINES[task.pipeline]["dims"]["lang"]


def ex_iv_ensure_source(task: Task) -> str:
    p = Path(task.params["video_path"])
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise RuntimeError(f"视频不存在: {p}")
    task.params["_video_abs"] = str(p)
    return f"视频就绪: {p.name} ({p.stat().st_size // 1048576}MB)"


def ex_iv_extract_audio(task: Task) -> str:
    w = _iv_dir(task)
    w.mkdir(parents=True, exist_ok=True)
    audio = w / "source-audio.mp3"
    _run([str(FFMPEG), "-y", "-i", task.params["_video_abs"],
          "-vn", "-q:a", "4", str(audio)], task)
    return f"音频: {audio.name}"


def ex_iv_asr_source(task: Task) -> str:
    import align_srt_asr as asr
    w = _iv_dir(task)
    lang = _iv_lang(task)
    cache = w / f"source-audio.mp3.{lang}.asr.json"
    segments = asr.transcribe(w / "source-audio.mp3",
                              language=lang, cache_path=cache)
    (w / "source-segments.json").write_text(
        json.dumps([{"start": s, "end": e, "text": t} for s, e, t in segments],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(t) for _, _, t in segments)
    return f"{lang} 转写: {len(segments)} 段 / {total} 字符"


def ex_iv_diarize(task: Task) -> str:
    w = _iv_dir(task)
    data = json.loads((w / "source-segments.json").read_text(encoding="utf-8"))
    segs = [(d["start"], d["end"], d["text"]) for d in data]
    turns = ilib.diarize_alternating(segs, speakers=2)
    ilib.save_turns(turns, w / "turns.json")
    n_a = sum(1 for t in turns if t["speaker"] == "A")
    n_b = len(turns) - n_a
    chars_a = sum(len(t["text"]) for t in turns if t["speaker"] == "A")
    chars_b = sum(len(t["text"]) for t in turns if t["speaker"] == "B")
    return f"turns: {len(turns)} (A:{n_a}/{chars_a}字, B:{n_b}/{chars_b}字)"


def ex_iv_chunk_by_speaker(task: Task) -> str:
    w = _iv_dir(task)
    turns = ilib.load_turns(w / "turns.json")
    chunks = ilib.build_chunks(turns)
    cdir = w / "chunks"
    cdir.mkdir(parents=True, exist_ok=True)
    roles = {}
    if task.params.get("speaker_A_name"):
        roles["A"] = task.params["speaker_A_name"]
    if task.params.get("speaker_B_name"):
        roles["B"] = task.params["speaker_B_name"]
    for c in chunks:
        prompt = ilib.build_prompt(c["text"], c["speaker"], _iv_lang(task), roles)
        (cdir / f"{c['chunk_index']:02d}.txt").write_text(prompt, encoding="utf-8")
    (cdir / "manifest.json").write_text(json.dumps(
        {"slug": task.params["slug"], "lang": _iv_lang(task),
         "total_chunks": len(chunks),
         "roles": roles,
         "chunks": chunks}, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"{len(chunks)} 块 → {cdir}"


def ex_iv_send_chunks(task: Task) -> None:
    pass  # manual 阶段


def _send_record_path(task: Task) -> Path:
    if task.pipeline.startswith("interview"):
        return _iv_dir(task) / "doubao-send.json"
    return _ep_dir(task) / "doubao-send.json"


def send_record_completed(task: Task) -> bool:
    """轮询扩展发送记录:全部 done 且校验过 → True。"""
    p = _send_record_path(task)
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    items = d.get("items", [])
    if not items:
        return False
    if d.get("status") == "completed" and all(i.get("status") == "done" for i in items):
        return True
    # 扩展逐块写 done;全部 done 也算完成(兼容无顶层 status 的情况)
    return all(i.get("status") == "done" for i in items)


def ex_iv_harvest_multi_voice(task: Task) -> str:
    import doubao_reader as dr
    w = _iv_dir(task)
    manifest = json.loads((w / "chunks" / "manifest.json").read_text(encoding="utf-8"))
    chunks = manifest["chunks"]

    rec = _send_record_path(task)
    if not rec.exists():
        raise RuntimeError("未找到发送记录 doubao-send.json,请先用扩展发送")
    record = json.loads(rec.read_text(encoding="utf-8"))
    n = len(chunks)

    # 拉取最近回复,按发送记录的顺序对齐(扩展按块顺序发送,回复按顺序返回)
    msgs = dr.fetch_messages(limit=n + 10, per_conv=n + 5)
    replies = [m for m in msgs if m.get("tts_content")]
    task.log(f"消息列表拉到 {len(msgs)} 条,其中含朗读文本 {len(replies)} 条")
    if len(replies) < n:
        raise RuntimeError(f"回复数不足: 需要 {n},实际 {len(replies)};请确认全部发送完成")
    # fetch_messages 返回最新在前 → 取前 n 条并反转成时间顺序
    replies = list(reversed(replies[:n]))

    speakers_map = {}
    if task.params.get("speaker_A_voice"):
        speakers_map["A"] = task.params["speaker_A_voice"]
    if task.params.get("speaker_B_voice"):
        speakers_map["B"] = task.params["speaker_B_voice"]

    out_audio = w / "audio.mp3"
    result = ilib.harvest_multi_voice(chunks, replies, w, speakers_map, out_audio)
    return f"多音色配音: {result['clips']} 段 → {out_audio.name}"


def ex_iv_asr_subtitle(task: Task) -> str:
    w = _iv_dir(task)
    _run([VENV_PY, str(TOOL_DIR / "align_srt_asr.py"),
          str(w / "audio.mp3"), "-o", str(w / "asr.srt"), "--asr-only"], task)
    return "ASR 字幕完成"


def ex_iv_render(task: Task) -> str:
    w = _iv_dir(task)
    slug = task.params["slug"]
    title = task.params.get("title") or slug
    out = ROOT / "videos" / f"{slug}.mp4"
    part = out.with_suffix(".part.mp4")
    _run([VENV_PY, str(TOOL_DIR / "make_cover_video.py"),
          "--gen-cover", "--audio", str(w / "audio.mp3"),
          "--srt", str(w / "asr.srt"),
          "--title", title, "--watermark", "wzx",
          "-o", str(part)], task)
    if part.exists() and not out.exists():
        shutil.move(str(part), str(out))
    if not out.exists():
        raise RuntimeError("渲染未产出成品")
    return f"成品: {out.name}"


EXECUTORS = {
    "course": {
        "ensure_source": ex_course_ensure_source,
        "ocr_subtitle": ex_course_ocr,
        "chunk_prep": ex_course_chunk_prep,
        "send_chunks": ex_course_send_chunks,
        "harvest_audio": ex_course_harvest_audio,
        "asr_subtitle": ex_course_asr_subtitle,
        "render": ex_course_render,
    },
    "interview": {
        "ensure_source": ex_iv_ensure_source,
        "extract_audio": ex_iv_extract_audio,
        "asr_source": ex_iv_asr_source,
        "diarize": ex_iv_diarize,
        "chunk_by_speaker": ex_iv_chunk_by_speaker,
        "send_chunks": ex_iv_send_chunks,
        "harvest_multi_voice": ex_iv_harvest_multi_voice,
        "asr_subtitle": ex_iv_asr_subtitle,
        "render": ex_iv_render,
    },
}


# =====================================================================
# 任务运行器
# =====================================================================

def executor_group(task: Task) -> dict:
    return EXECUTORS["interview" if task.pipeline.startswith("interview") else "course"]


def run_task(task: Task) -> None:
    """从 current 阶段开始推进,直到 manual 等待 / 失败 / 完成。"""
    group = executor_group(task)
    while task.current < len(task.stages):
        st = task.stages[task.current]
        if st["status"] == STAGE_DONE:
            task.current += 1
            continue
        if st["type"] == "manual":
            task.mark(st["key"], STAGE_WAITING,
                      note=f"请在扩展中发送 {task.params.get('slug', task.params.get('episode', ''))} 的分块")
            task.status = TASK_WAITING
            task.save()
            return
        fn = group.get(st["key"])
        if fn is None:
            task.mark(st["key"], STAGE_FAILED, error="执行器缺失")
            task.status = TASK_FAILED
            task.save()
            return
        task.mark(st["key"], STAGE_RUNNING)
        task.status = TASK_RUNNING
        task.save()
        try:
            note = fn(task) or "完成"
            task.mark(st["key"], STAGE_DONE, note=note)
            task.log(f"✓ {st['label']}: {note}")
            task.current += 1
        except Exception as e:  # noqa: BLE001
            task.mark(st["key"], STAGE_FAILED, error=str(e))
            task.status = TASK_FAILED
            task.save()
            task.log(f"✗ {st['label']} 失败: {e}")
            return
    task.status = TASK_DONE
    task.save()
    task.log("任务完成")


def start_runner(task: Task) -> None:
    t = threading.Thread(target=run_task, args=(task,), daemon=True)
    t.start()


def advance_manual(task: Task, force: bool) -> bool:
    """manual 门:发送记录完成(或用户强制确认)→ 标记完成并继续。"""
    st = task.stages[task.current] if task.current < len(task.stages) else None
    if not st or st["type"] != "manual" or st["status"] != STAGE_WAITING:
        return False
    if not force and not send_record_completed(task):
        return False
    task.mark(st["key"], STAGE_DONE,
              note="发送确认完成" + ("(自动检测)" if not force else "(手动确认)"))
    task.current += 1
    task.save()
    start_runner(task)
    return True


def retry_stage(task: Task) -> bool:
    """从失败阶段重试。"""
    if task.status != TASK_FAILED:
        return False
    for i, st in enumerate(task.stages):
        if st["status"] == STAGE_FAILED:
            st["status"] = STAGE_PENDING
            st["error"] = None
            task.current = i
            task.status = TASK_RUNNING  # 立即离开 failed,后台线程接手
            task.save()
            start_runner(task)
            return True
    return False


def list_tasks() -> list[Task]:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    tasks = [Task.load(p) for p in sorted(TASKS_DIR.glob("*.json"))]
    return sorted(tasks, key=lambda t: t.created_at, reverse=True)


def load_task(task_id: str) -> Task | None:
    p = TASKS_DIR / f"{task_id}.json"
    return Task.load(p) if p.exists() else None


# =====================================================================
# HTTP 服务
# =====================================================================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    def _json(self, obj, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # ---------- GET ----------

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/admin", "/admin/"):
            return self._serve_html()
        if self.path == "/api/pipelines":
            return self._json(PIPELINES)
        if self.path == "/api/tasks":
            # 顺带轮询 manual 门(页面每 3s 拉一次,即自动检测发送完成)
            for t in list_tasks():
                if t.status == TASK_WAITING:
                    advance_manual(t, force=False)
            return self._json([t.brief() for t in list_tasks()])
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9-]+)", self.path)
        if m:
            t = load_task(m.group(1))
            if not t:
                return self._json({"ok": False, "error": "任务不存在"},
                                  HTTPStatus.NOT_FOUND)
            if t.status == TASK_WAITING:
                advance_manual(t, force=False)
            return self._json(t.detail())
        return self._json({"ok": False, "error": "not found"},
                          HTTPStatus.NOT_FOUND)

    def _serve_html(self) -> None:
        p = TOOL_DIR / "admin.html"
        body = p.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- POST ----------

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/tasks":
            return self._create_task()
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9-]+)/action", self.path)
        if m:
            return self._task_action(m.group(1))
        return self._json({"ok": False, "error": "not found"},
                          HTTPStatus.NOT_FOUND)

    def _create_task(self) -> None:
        data = self._body()
        key = data.get("pipeline", "")
        if key not in PIPELINES:
            return self._json({"ok": False, "error": f"未知流水线 {key}"}, 400)
        params = data.get("params", {})
        # 必填校验
        for spec in PIPELINES[key]["params"]:
            if spec["required"] and not params.get(spec["key"]):
                return self._json(
                    {"ok": False, "error": f"缺少必填参数 {spec['label']}"}, 400)
        if key.startswith("interview"):
            slug = params["slug"].strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{2,40}", slug):
                return self._json({"ok": False, "error": "slug 仅限字母数字-_"}, 400)
            if (ROOT / "work" / "interview" / slug / "chunks").exists():
                return self._json({"ok": False,
                                   "error": f"代号 {slug} 已存在"}, 400)
        name = data.get("name") or params.get("slug") or f"第{params.get('episode')}集"
        task = Task(key, name, params)
        task.save()
        task.log(f"创建任务: {PIPELINES[key]['name']} / {name}")
        start_runner(task)
        return self._json({"ok": True, "task": task.brief()})

    def _task_action(self, task_id: str) -> None:
        t = load_task(task_id)
        if not t:
            return self._json({"ok": False, "error": "任务不存在"}, 404)
        action = self._body().get("action")
        if action == "confirm_send":
            ok = advance_manual(t, force=True)
            return self._json({"ok": ok, "error": None if ok else "当前不在等待发送状态"})
        if action == "retry":
            ok = retry_stage(t)
            return self._json({"ok": ok, "error": None if ok else "任务不在失败状态"})
        return self._json({"ok": False, "error": f"未知 action {action}"}, 400)


def main() -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    addr = ("127.0.0.1", PORT)
    srv = ThreadingHTTPServer(addr, Handler)
    print(f"[pipeline-admin] http://127.0.0.1:{PORT}  (流水线:{', '.join(PIPELINES)})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[pipeline-admin] 退出")


if __name__ == "__main__":
    main()
