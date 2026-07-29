"""tts_gpt_sovits 的单元测试。

只测不依赖真实 GPT-SoVITS 服务的逻辑：URL 构造、健康检查对无服务端口的返回、
服务进程未启动时的错误处理。真实合成由端到端脚本验证。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tts_gpt_sovits as tts


def test_server_url_construction():
    assert tts.server_url() == "http://127.0.0.1:9880"
    assert tts.server_url("0.0.0.0", 8000) == "http://0.0.0.0:8000"


def test_is_server_running_returns_false_for_dead_port():
    """没有服务监听的端口应返回 False（用一个肯定没被占用的端口）。"""
    # 端口 1 通常无服务且需要特权，适合做"无服务"探测
    assert tts.is_server_running("http://127.0.0.1:1") is False


def test_ensure_server_raises_if_venv_missing(monkeypatch, tmp_path):
    """venv 不存在时应抛 FileNotFoundError。"""
    # 把 GPT_SOVITS_VENV_PYTHON 指向不存在的路径
    monkeypatch.setattr(tts, "GPT_SOVITS_VENV_PYTHON", tmp_path / "nope.exe")
    # is_server_running 也应返回 False 才会触发启动逻辑
    monkeypatch.setattr(tts, "is_server_running", lambda url: False)
    try:
        tts.ensure_server_running(verbose=False)
        assert False, "应抛 FileNotFoundError"
    except FileNotFoundError:
        pass


def test_synthesize_one_payload_shape(monkeypatch, tmp_path):
    """synthesize_one 应构造正确的 payload 并写出文件（mock 服务响应）。"""
    captured = {}

    class FakeResp:
        status_code = 200
        content = b"FAKE_WAV_DATA"

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(tts, "is_server_running", lambda url=None: True)
    monkeypatch.setattr(tts.requests, "post", fake_post)

    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    out = tmp_path / "out.wav"

    tts.synthesize_one(
        text="你好世界",
        ref_audio=ref,
        prompt_text="hello world",
        output=out,
        prompt_lang="en",
        text_lang="zh",
        output_format="wav",
    )

    # payload 关键字段
    assert captured["payload"]["text"] == "你好世界"
    assert captured["payload"]["text_lang"] == "zh"
    assert captured["payload"]["prompt_lang"] == "en"
    assert captured["payload"]["prompt_text"] == "hello world"
    assert captured["payload"]["media_type"] == "wav"
    assert captured["url"].endswith("/tts")
    # 输出文件写入
    assert out.read_bytes() == b"FAKE_WAV_DATA"


def test_synthesize_one_raises_on_http_error(monkeypatch, tmp_path):
    class FakeResp:
        status_code = 500
        text = "model error"

    monkeypatch.setattr(tts, "is_server_running", lambda url=None: True)
    monkeypatch.setattr(tts.requests, "post",
                        lambda url, json=None, timeout=None: FakeResp())

    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    try:
        tts.synthesize_one("test", ref, "p", tmp_path / "o.wav", output_format="wav")
        assert False, "应抛 RuntimeError"
    except RuntimeError as e:
        assert "500" in str(e)
