# -*- coding: utf-8 -*-
"""经过人工试听定案的栏目音色 Profile。

Profile 把音色、语速和后期目标绑定为一个可追溯版本。生产任务可以显式
指定 voice_profile；没有 Profile 的历史任务仍按原有 voice_A/voice_B 逻辑运行。
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES_PATH = ROOT / "src" / "voice-profiles.json"


def _load() -> dict[str, dict]:
    if not PROFILES_PATH.exists():
        return {}
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    profiles = data.get("profiles", data)
    if not isinstance(profiles, dict):
        raise ValueError("voice-profiles.json: profiles 必须是对象")
    return profiles


def get(name: str) -> dict | None:
    if not name:
        return None
    return _load().get(name.strip())


def list_profiles() -> list[dict]:
    return [{"name": name, **profile} for name, profile in _load().items()]


def profile_hash(name: str) -> str:
    profile = get(name)
    if profile is None:
        raise KeyError(f"音色 Profile 不存在: {name}")
    raw = json.dumps(profile, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def resolve(name: str, speakers: list[str]) -> dict[str, str]:
    """返回说话人到音色的映射，并拒绝未批准或缺失的 Profile。"""
    profile = get(name)
    if profile is None:
        raise KeyError(f"音色 Profile 不存在: {name}")
    if profile.get("status") != "approved":
        raise ValueError(f"音色 Profile 未批准: {name}")
    voices = profile.get("voices") or {}
    default = profile.get("voice")
    out = {}
    for speaker in speakers:
        voice = voices.get(speaker) or default
        if not voice:
            raise ValueError(f"Profile {name} 未为说话人 {speaker} 配置音色")
        out[speaker] = voice
    return out


def apply_to_params(params: dict, speakers: list[str]) -> dict[str, str] | None:
    """按 Profile 回填任务参数；未指定 Profile 时返回 None。"""
    name = params.get("voice_profile")
    if not name:
        return None
    voices = resolve(name, speakers)
    for speaker, voice in voices.items():
        params[f"voice_{speaker}"] = voice
    params["_voice_profile"] = name
    params["_voice_profile_hash"] = profile_hash(name)
    return voices
