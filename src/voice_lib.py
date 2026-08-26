"""音色资源库 —— CosyVoice 零样本参考音色的注册与复用。

目录布局(work/studio/voices/):
  <name>/ref.wav      参考音频(几秒~十几秒,越干净越好)
  <name>/ref.txt      参考音频对应的原文文本(英文参考用于跨语克隆)
  <name>/meta.json    {name, ref_text, created_at, note}

generate_fine_audio.py 的 --refs-json 可直接引用音色库条目:
  {"A": voice_lib.ref_spec("doubao-taotao"), "B": ...}
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICES_DIR = ROOT / "work" / "studio" / "voices"


def voices_root() -> Path:
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    return VOICES_DIR


def list_voices() -> list[dict]:
    out = []
    for meta in sorted(voices_root().glob("*/meta.json")):
        d = json.loads(meta.read_text(encoding="utf-8"))
        d["has_audio"] = (meta.parent / "ref.wav").exists()
        out.append(d)
    return out


def get(name: str) -> dict | None:
    meta = voices_root() / name / "meta.json"
    if not meta.exists():
        return None
    return json.loads(meta.read_text(encoding="utf-8"))


def create(name: str, ref_audio: Path, ref_text: str, note: str = "") -> dict:
    """注册音色:复制参考音频到库并写元数据。name 限 [a-z0-9-]。"""
    if not name.replace("-", "").replace("_", "").isalnum() \
            or not name[0].isalnum():
        raise ValueError(f"音色名仅限字母数字-_: {name!r}")
    if not ref_audio.exists():
        raise FileNotFoundError(f"参考音频不存在: {ref_audio}")
    d = voices_root() / name
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ref_audio, d / "ref.wav")
    meta = {"name": name, "ref_text": ref_text,
            "created_at": time.strftime("%Y-%m-%d %H:%M"),
            "note": note}
    (d / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def ref_wav(name: str) -> Path:
    p = voices_root() / name / "ref.wav"
    if not p.exists():
        raise FileNotFoundError(f"音色 {name} 无参考音频")
    return p


def ref_spec(name: str) -> dict:
    """生成 generate_fine_audio 兼容的 refs 条目(ref_wav 为绝对路径)。"""
    meta = get(name)
    if not meta:
        raise KeyError(f"音色不存在: {name}")
    return {"ref_wav": str(ref_wav(name)), "ref_text_en": meta["ref_text"]}


def refs_json_for(voices: dict[str, str]) -> dict:
    """{"A": "doubao-taotao", "B": "orig-hinton"} → refs dict。"""
    return {spk: ref_spec(name) for spk, name in voices.items()}


def seed_defaults() -> list[str]:
    """预置音色(幂等):豆包桃桃(从课程克隆参考导入)。"""
    seeded = []
    taotao_src = ROOT / "work" / "voice-clone-demo" / "output" / "doubao-reference.wav"
    if taotao_src.exists() and not get("doubao-taotao"):
        ref_text = ("哈佛大学《积极心理学》课程,欢迎回来。我们今天继续学习"
                    "关于幸福的科学。")
        create("doubao-taotao", taotao_src, ref_text,
               note="豆包桃桃音色(CosyVoice 克隆参考,来自课程克隆链)")
        seeded.append("doubao-taotao")
    return seeded
