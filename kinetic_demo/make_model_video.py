# -*- coding: utf-8 -*-
"""国产大模型科普视频管线:文案 JSON → CosyVoice 配音 → 时间轴数据 →
HTML 场景逐帧渲染 → 成片。

用法:
  python make_model_video.py <slug> [--tts-only] [--render-only] [--smoke]

slug 对应 content/<slug>.json:
{
  "brand": "DEEPSEEK · 一口气看懂",
  "voice": "doubao-东方浩然",
  "content": { ... model_stage.html 的 CONTENT ... },
  "items": [{"id":0,"text":"..."}, ...],       # 解说文案
  "order": [0,1,2,...],                         # 播放顺序
  "scenes": [{"scene":"title","color":"#22d3ee","label":"开场"}, ...]
}
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import wave as _wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
FFMPEG = ROOT / "work/video-tools/ffmpeg.exe"
FFPROBE = ROOT / "work/video-tools/ffprobe.exe"
WSL_PY = "/home/comfy/cosy-gpu-venv/bin/python"
WSL_ENV = ("HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 "
           "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1")
VC_PY = ROOT / "work/voice-clone-demo/.venv/Scripts/python.exe"
GEN_VOICE = ROOT / "work/voice-clone-demo/generate_voice.py"
FPS = 30
LEAD_IN = 0.5
GAP = 0.55


def wsl(p: Path) -> str:
    s = str(p).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)", s)
    return f"/mnt/{m.group(1).lower()}/{m.group(2)}" if m else s


def dur_of(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def tokenize(text):
    return re.findall(r"[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*|[\u4e00-\u9fff]|[0-9]+(?:\.[0-9]+)?|\s+|.", text)


def weight(tok):
    if re.fullmatch(r"[\u4e00-\u9fff]", tok):
        return 1.0
    if re.fullmatch(r"[A-Za-z0-9.\-]+", tok):
        return 0.85 * len(tok)
    if tok.strip() == "":
        return 0.25
    return 0.35


def split_cues(text, max_w=26.0):
    sents, cur = [], ''
    for ch in text:
        cur += ch
        if ch in '。?!?!;；':
            sents.append(cur); cur = ''
    if cur.strip():
        sents.append(cur)

    def width(t):
        return sum(0.55 if c.isascii() else 1.0 for c in t)

    cues = []
    for sent in sents:
        if not sent.strip():
            continue
        if width(sent) <= max_w:
            cues.append(sent)
            continue
        parts, buf = [], ''
        for ch in sent:
            buf += ch
            if ch in ',,、:：——' and width(buf) >= max_w * 0.45:
                parts.append(buf); buf = ''
        if buf.strip():
            parts.append(buf)
        block = ''
        for piece in parts:
            if block and width(block) + width(piece) > max_w:
                cues.append(block); block = piece
            else:
                block += piece
        if block.strip():
            cues.append(block)
    return [c for c in cues if c.strip()]


def run_tts(slug: str, cfg: dict, work: Path) -> None:
    """CosyVoice 逐段配音 + 重采样 16k(build 用)。"""
    work = work.resolve()  # WSL 侧需要绝对路径
    items = [{"id": it["id"], "speaker": it.get("speaker", "A"),
              "text": it["text"]} for it in cfg["items"]]
    (work / "items.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    voice = cfg.get("voice", "doubao-东方浩然")
    vdir = ROOT / "work/studio/voices" / voice
    refs = {"A": {
        "ref_wav": str(vdir / "ref.wav"),
        "ref_text_en": (vdir / "ref.txt").read_text(encoding="utf-8").strip(),
    }}
    (work / "refs.json").write_text(
        json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")

    args = ["--items-json", wsl(work / "items.json"),
            "--refs-json", wsl(work / "refs.json"),
            "--out-dir", wsl(work / "parts")]
    inner = (f"cd {wsl(ROOT)} && env {WSL_ENV} "
             f"{WSL_PY} work/voice-clone-demo/generate_voice.py "
             + " ".join(f'"{a}"' for a in args))
    r = subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-c", inner])
    if r.returncode != 0:
        raise RuntimeError("WSL TTS 失败(见上方输出)")
    p16 = work / "parts16"
    p16.mkdir(exist_ok=True)
    for wav in sorted((work / "parts").glob("item_*.wav")):
        subprocess.run([str(FFMPEG), "-y", "-v", "error", "-i", str(wav),
                        "-ar", "16000", "-ac", "1", str(p16 / wav.name)],
                       check=True)


def build(slug: str, cfg: dict, work: Path) -> tuple[Path, Path]:
    """拼装音频时间轴 + 逐字权重字幕 → <slug>_data.json / <slug>_audio.wav。"""
    items = {it["id"]: it for it in cfg["items"]}
    order = cfg["order"]
    scenes = cfg["scenes"]
    segs, t = [], LEAD_IN
    pcm_out, sr_ref, nch, sw = [], None, None, None
    for pos, sid in enumerate(order):
        wav = work / "parts16" / f"item_{sid:04d}.wav"
        d = dur_of(wav)
        with _wave.open(str(wav), "rb") as w:
            sr = w.getframerate()
            pcm = w.readframes(w.getnframes())
            nch, sw = w.getnchannels(), w.getsampwidth()
        assert sr_ref in (None, sr), f"sample rate mismatch @{sid}"
        sr_ref = sr
        if pos == 0:
            pcm_out.append(b"\x00" * int(sr * LEAD_IN) * nch * sw)
        pcm_out.append(pcm)
        if pos < len(order) - 1:
            pcm_out.append(b"\x00" * int(sr * GAP) * nch * sw)

        text = items[sid]["text"]
        pieces = split_cues(text)
        wsum = sum(weight(x) for p_ in pieces for x in tokenize(p_))
        sub, acc = [], t
        for p_ in pieces:
            toks = tokenize(p_)
            pw = sum(weight(x) for x in toks)
            dur = d * pw / wsum
            sub.append({"start": round(acc, 3), "end": round(acc + dur, 3),
                        "text": p_})
            acc += dur
        sc = scenes[pos]
        segs.append({"pos": pos, "id": sid, "start": round(t, 3),
                     "end": round(t + d, 3), "scene": sc["scene"],
                     "color": sc["color"], "label": sc["label"], "cues": sub})
        print(f"seg{pos:02d} id={sid} [{t:6.2f} -> {t+d:6.2f}] {text[:18]}…")
        t += d + GAP

    total = t - GAP + float(cfg.get("_tail", 3.0))
    pcm_out.append(b"\x00" * int(sr_ref * float(cfg.get("_tail", 3.0))) * nch * sw)
    audio = work / f"{slug}_audio.wav"
    with _wave.open(str(audio), "wb") as w:
        w.setnchannels(nch); w.setsampwidth(sw); w.setframerate(sr_ref)
        w.writeframes(b"".join(pcm_out))
    data = {"fps": FPS, "duration": round(total, 3), "segments": segs}
    data_path = HERE / f"{slug}_data.json"
    data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"total {total}s -> {data_path.name} + {audio.name}")
    return data_path, audio


def render(slug: str, cfg: dict, data_path: Path, audio: Path,
           smoke: bool = False) -> None:
    from playwright.sync_api import sync_playwright
    data = json.loads(data_path.read_text(encoding="utf-8"))
    n = 6 if smoke else int(data["duration"] * FPS) + 1
    # 舞台选择:content.stage 指定 > <slug>_stage.html > 通用模板
    stage = HERE / cfg.get("stage", f"{slug}_stage.html")
    if not stage.exists():
        stage = HERE / "model_stage.html"
    html = stage.read_text(encoding="utf-8")
    html = html.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__CONTENT_JSON__",
                        json.dumps(cfg["content"], ensure_ascii=False))
    built = HERE / f"_{slug}_built.html"
    built.write_text(html, encoding="utf-8")

    frames = HERE / f"_{slug}_frames"
    frames.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=[
            "--enable-unsafe-swiftshader", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--disable-lcd-text"])
        pg = b.new_page(viewport={"width": 1920, "height": 1080},
                        device_scale_factor=1)
        pg.on("pageerror", lambda e: print("[pageerror]", str(e)[:300]))
        pg.goto(built.resolve().as_uri())
        pg.wait_for_function("window.__READY__ === true", timeout=15000)
        ts = ([seg["start"] + (seg["end"] - seg["start"]) * 0.75
               for seg in data["segments"]] if smoke else
              [i / FPS for i in range(n)])
        for i, t in enumerate(ts):
            pg.evaluate("t => renderFrame(t)", t)
            pg.screenshot(path=str(frames / f"f_{i:05d}.jpg"),
                          type="jpeg", quality=92)
            if not smoke and i % 300 == 0:
                print(f"  frame {i}/{n}")
        b.close()
    if smoke:
        print(f"[ok] smoke {len(ts)} frames -> {frames}")
        return
    out = HERE / f"{slug}_video.mp4"
    subprocess.run([
        str(FFMPEG), "-y", "-v", "error",
        "-framerate", str(FPS), "-i", str(frames / "f_%05d.jpg"),
        "-i", str(audio),
        "-c:v", "libx264", "-crf", "19", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out)], check=True)
    print(f"[ok] {out} ({out.stat().st_size // 1048576}MB)")


def main():
    slug = sys.argv[1]
    smoke = "--smoke" in sys.argv
    cfg = json.loads((HERE / "content" / f"{slug}.json").read_text(
        encoding="utf-8"))
    work = HERE / f"{slug}_video"
    work.mkdir(exist_ok=True)

    have_parts = all((work / "parts16" / f"item_{sid:04d}.wav").exists()
                     for sid in cfg["order"])
    if not have_parts:
        print(f"[tts] {slug} ...")
        run_tts(slug, cfg, work)
    else:
        print("[tts] 已有配音,跳过")
    data_path, audio = build(slug, cfg, work)
    render(slug, cfg, data_path, audio, smoke=smoke)


if __name__ == "__main__":
    main()
