"""GPT-SoVITS 语音克隆 TTS 引擎封装。

职责：
  - 管理 GPT-SoVITS api_v2.py 服务的生命周期（按需启动、健康检查、复用）
  - 提供与 edge-tts 等价的"文本→音频文件"合成接口（dub_pipeline._synthesize_one 调用）

GPT-SoVITS 是常驻 HTTP 服务（监听 9880），加载 ~2.7GB 模型需 30-60 秒。
首次合成前自动启动服务并等待就绪；服务保活，后续合成复用。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

# --- 路径常量 ---
ROOT = Path(__file__).resolve().parents[2]
# GPT-SoVITS 实际安装在 Codex 工作区（非 D:\work\wzx\work 下）。
GPT_SOVITS_DIR = Path(os.environ.get("GPT_SOVITS_DIR", ROOT / "work" / "gpt-sovits"))
GPT_SOVITS_VENV_PYTHON = Path(
    os.environ.get(
        "GPT_SOVITS_PYTHON",
        GPT_SOVITS_DIR / ".venv" / "Scripts" / "python.exe",
    )
)
GPT_SOVITS_API = GPT_SOVITS_DIR / "api_v2.py"
GPT_SOVITS_CONFIG = Path(
    os.environ.get(
        "GPT_SOVITS_CONFIG",
        GPT_SOVITS_DIR / "GPT_SoVITS" / "configs" / "tts_infer.yaml",
    )
)
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9880
SERVER_STARTUP_TIMEOUT = 180   # 模型加载最多等 180 秒
HEALTH_POLL_INTERVAL = 2

# 服务进程句柄（模块级，保活复用）
_server_process: subprocess.Popen | None = None
_startup_announced: bool = False   # 避免重复打印"服务已在运行"


def server_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}"


def is_server_running(url: str | None = None) -> bool:
    """检测服务是否在监听。api_v2.py 没有根路由，用 TCP 连接 + /control 探测。

    分两步：先 TCP 连端口确认进程在监听，再发 HTTP 请求确认 FastAPI 就绪
    （模型加载完前进程在但 HTTP 还不通）。
    """
    import socket
    url = url or server_url()
    # 解析 host:port
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port
    # 1. TCP 连接检测（进程是否监听端口）
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError:
        return False
    # 2. HTTP 就绪检测（FastAPI 是否响应；模型加载完才就绪）
    try:
        # /control 是 GET 端点，参数缺失会返回 422（FastAPI 校验错误），
        # 但只要 FastAPI 起来了就会响应，422 也算服务就绪
        resp = requests.get(url + "/control", timeout=3)
        return resp.status_code in (200, 400, 422)
    except requests.RequestException:
        return False


def ensure_server_running(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                          verbose: bool = True) -> str:
    """确保 GPT-SoVITS 服务在运行；若否则启动并等待就绪。返回服务 URL。"""
    global _server_process, _startup_announced
    url = server_url(host, port)

    if is_server_running(url):
        if verbose and not _startup_announced:
            print(f"[gpt-sovits] 服务已在运行：{url}", file=sys.stderr)
            _startup_announced = True
        return url

    if not GPT_SOVITS_VENV_PYTHON.exists():
        raise FileNotFoundError(
            f"GPT-SoVITS venv 不存在：{GPT_SOVITS_VENV_PYTHON}。"
            "请先按计划搭建 work/gpt-sovits/.venv"
        )
    if not GPT_SOVITS_API.exists():
        raise FileNotFoundError(f"api_v2.py 不存在：{GPT_SOVITS_API}")

    if verbose:
        print(f"[gpt-sovits] 启动服务（加载模型需 30-60 秒）...", file=sys.stderr)

    import os
    env = os.environ.copy()
    env["is_half"] = "false"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"

    _server_process = subprocess.Popen(
        [
            str(GPT_SOVITS_VENV_PYTHON), str(GPT_SOVITS_API),
            "-a", host, "-p", str(port),
            "-c", str(GPT_SOVITS_CONFIG),
        ],
        cwd=str(GPT_SOVITS_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 轮询等待服务就绪
    deadline = time.time() + SERVER_STARTUP_TIMEOUT
    while time.time() < deadline:
        if _server_process.poll() is not None:
            raise RuntimeError(
                f"GPT-SoVITS 服务进程意外退出（exit={_server_process.returncode}）。"
                "请手动运行 api_v2.py 查看错误。"
            )
        if is_server_running(url):
            if verbose:
                print(f"[gpt-sovits] 服务就绪：{url}", file=sys.stderr)
            _startup_announced = True
            return url
        time.sleep(HEALTH_POLL_INTERVAL)

    raise TimeoutError(
        f"GPT-SoVITS 服务在 {SERVER_STARTUP_TIMEOUT}s 内未就绪。"
    )


def synthesize_one(text: str, ref_audio: Path, prompt_text: str,
                   output: Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                   text_lang: str = "zh", prompt_lang: str = "en",
                   speed_factor: float = 1.0, temperature: float = 1.0,
                   top_k: int = 15, top_p: float = 1.0,
                   repetition_penalty: float = 1.35, seed: int = 42,
                   text_split_method: str = "cut5",
                   output_format: str = "mp3") -> None:
    """合成一段文本到音频文件。

    text: 要合成的目标文本（中文）
    ref_audio: 参考音频路径（绝对路径，服务端可达）
    prompt_text: 参考音频对应的转写文本（与 ref_audio 内容逐字对应）
    output: 输出文件（.mp3 或 .wav）。GPT-SoVITS 返回 wav，需要 mp3 时用 ffmpeg 转
    speed_factor: 语速（1.0=参考音原速）；temperature: 采样随机性（低更稳但易含糊）；
    top_k/top_p: 采样范围；repetition_penalty: 抑制重复卡壳。
    """
    url = ensure_server_running(host, port)
    ref_audio_abs = str(ref_audio.resolve())

    payload = {
        "text": text,
        "text_lang": text_lang,
        "ref_audio_path": ref_audio_abs,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
        "text_split_method": text_split_method,
        "media_type": "wav",
        "speed_factor": speed_factor,
        "temperature": temperature,
        "top_k": top_k,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
        "seed": seed,
        "streaming_mode": False,
        "parallel_infer": True,
    }

    resp = requests.post(url + "/tts", json=payload, timeout=600)
    if resp.status_code != 200:
        raise RuntimeError(
            f"GPT-SoVITS /tts 失败 HTTP {resp.status_code}: "
            f"{resp.text[:500]}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "wav":
        output.write_bytes(resp.content)
    else:
        # GPT-SoVITS 返回 wav，转成 mp3 保持与 edge-tts 产物格式一致（下游零改动）
        tmp_wav = output.with_suffix(".tmp.wav")
        try:
            tmp_wav.write_bytes(resp.content)
            subprocess.run(
                [str(FFMPEG), "-y", "-i", str(tmp_wav), "-nostdin",
                 "-codec:a", "libmp3lame", "-b:a", "192k", str(output)],
                capture_output=True, check=True,
            )
        finally:
            tmp_wav.unlink(missing_ok=True)


def shutdown_server() -> None:
    """关闭服务进程（可选，通常保活复用）。"""
    global _server_process
    if _server_process is not None and _server_process.poll() is None:
        _server_process.terminate()
        try:
            _server_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server_process.kill()
    _server_process = None
