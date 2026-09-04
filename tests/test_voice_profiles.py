"""音色选角 Profile 的稳定性与审批边界。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import voice_profiles as vp


def _profile_file(tmp_path, monkeypatch, profile):
    path = tmp_path / "voice-profiles.json"
    path.write_text(json.dumps({"schema": 1, "profiles": {"p": profile}}), encoding="utf-8")
    monkeypatch.setattr(vp, "PROFILES_PATH", path)


def test_approved_profile_resolves_all_speakers(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, {
        "status": "approved", "voice": "voice-a", "voices": {"B": "voice-b"}
    })
    assert vp.resolve("p", ["A", "B"]) == {"A": "voice-a", "B": "voice-b"}


def test_unapproved_profile_is_rejected(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, {"status": "draft", "voice": "voice-a"})
    with pytest.raises(ValueError, match="未批准"):
        vp.resolve("p", ["A"])


def test_missing_profile_voice_is_rejected(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, {"status": "approved", "voices": {"B": "voice-b"}})
    with pytest.raises(ValueError, match="说话人 A"):
        vp.resolve("p", ["A"])


def test_apply_records_profile_and_hash(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, {"status": "approved", "voice": "voice-a"})
    params = {"voice_profile": "p"}
    voices = vp.apply_to_params(params, ["A"])
    assert voices == {"A": "voice-a"}
    assert params["voice_A"] == "voice-a"
    assert params["_voice_profile"] == "p"
    assert len(params["_voice_profile_hash"]) == 16


def test_profile_hash_changes_when_approval_record_changes(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, {
        "status": "approved", "voice": "voice-a", "approved_at": "2026-08-27"
    })
    first = vp.profile_hash("p")
    _profile_file(tmp_path, monkeypatch, {
        "status": "approved", "voice": "voice-a", "approved_at": "2026-08-28"
    })
    assert vp.profile_hash("p") != first
