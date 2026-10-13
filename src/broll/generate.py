# -*- coding: utf-8 -*-
"""B-roll 插图批量生成:扫描内容 JSON 的 broll 节拍,生成插画。

双后端:
- local(默认优先): 本机 ComfyUI API(127.0.0.1:8188, SDXL, 零边际成本)
- icu: OpenRouter ICU (tokenadvent.com) 的 gpt-image-2(按量计费,作回退)
--backend auto=先 local 后 icu;--backend local/icu 指定单一后端。

文件名确定性:`<章节kind>_<序号>.png`,与 vector_render 的解析保持一致。
指纹缓存:sha256(backend+model+size+完整提示词) 命中且文件存在则跳过。
用法:
  python src/broll/generate.py --content src/mzx_story/ming-02-zhuyuanzhang.json
key(ICU 用):环境变量 ICU_API_KEY > icu-key.txt > --key。

人名标注(2026-09-12):broll 节拍可带 cast 字段,如 "cast": ["左·于谦", "右·朱祁钰"]
(位置前缀 左/中/右 可省略)。cast 节拍强制走 ICU(gpt-image-2 能写中文;SDXL 不能),
提示词去掉风格里的 no text 约束并追加姓名签指令;生成后 RapidOCR 回读校验姓名全部
命中,未命中自动重试,连续失败则不落正式文件名(渲染端缺图报错门禁自然拦截),
最后一张留在 <name>.reject.png 供人工检查。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://tokenadvent.com/v1"
COMFY = "http://127.0.0.1:8188"
KEY_FILE = Path.home() / ".zcode" / "icu-key.txt"
CLASH = "http://127.0.0.1:7897"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

CAST_ATTEMPTS = 3  # 人名标注 OCR 校验的总生图次数(1 次首生成 + 2 次重试)
_POS_EN = {"左": "left", "中": "center", "右": "right"}
_OCR_LOCK = threading.Lock()
_OCR_ENGINE = None


def cast_names(beat: dict) -> list[str]:
    """节拍 cast 字段解析:["左·于谦", "于谦"] -> ["于谦", "于谦"](名字本体)。"""
    out = []
    for entry in beat.get("cast") or []:
        name = str(entry).strip().split("·")[-1].strip()
        if name:
            out.append(name)
    return out


# 易混字部件提示:模型高频把某字写成同音形近字时在此登记(2026-09-14 "杨涟"三连画成
# "杨连" 后加;OCR 门禁按整字比对,部件提示能显著降低重试失败率)
_CHAR_HINTS = {
    "涟": ('the character "涟" must contain the three-dot water radical 氵 '
           'on its left, followed by "连" — do NOT write "连" alone'),
}


def _char_hints(names: list[str]) -> str:
    hints = []
    for ch in dict.fromkeys("".join(names)):
        if ch in _CHAR_HINTS:
            hints.append(_CHAR_HINTS[ch])
    return (" Character notes: " + "; ".join(hints) + ".") if hints else ""


def cast_clause(cast_entries: list[str]) -> str:
    """cast 字段 -> 姓名签英文指令。位置前缀(左/中/右)映射到画面人物。"""
    items = []
    for entry in cast_entries:
        pos, _, name = str(entry).strip().partition("·")
        name = name.strip() if name else pos.strip()
        en = _POS_EN.get(pos.strip())
        if en:
            target = f"the {en} figure"
        elif len(cast_entries) == 1:
            target = "the figure"
        else:
            target = "the corresponding figure"
        items.append(f'a small rectangular parchment paper slip pinned beside {target} '
                     f'with the Chinese characters "{name}" written on it in clear '
                     f"legible regular script (kaishu) black ink")
    names = "、".join(str(e).strip().split("·")[-1].strip() for e in cast_entries)
    return (f"{', '.join(items)}. These name slips are the ONLY text in the image; "
            f"render the Chinese characters {names} accurately and completely."
            f"{_char_hints(names)}")


def build_prompt(style: str, beat: dict) -> str:
    """节拍完整提示词:风格前缀 + 场景;cast 节拍去掉 no text 约束并追加姓名签指令。"""
    prompt = str(beat.get("prompt", "")).strip()
    cast_entries = [str(c).strip() for c in (beat.get("cast") or []) if str(c).strip()]
    if not cast_entries:
        return (style + ". " if style else "") + prompt
    style_nc = re.sub(r",?\s*no text\s*(?=[,.]|$)", "", style,
                      flags=re.IGNORECASE).strip().rstrip(", ")
    head = style_nc + ". " if style_nc else ""
    return f"{head}{prompt.rstrip('. ')}. {cast_clause(cast_entries)}"


def names_missing(ocr_text: str, names: list[str]) -> list[str]:
    """OCR 全文里没找到的名字。空白与常见装饰符剔除后做包含匹配。"""
    joined = re.sub(r"\s+|[/|、,，.。·:：()（）\[\]【】《》_-]", "", ocr_text or "")
    return [n for n in names if n not in joined]


def ocr_image_text(image_path: Path) -> str:
    """RapidOCR 回读图片全部文字(rapidocr_onnxruntime,懒加载单例)。"""
    global _OCR_ENGINE
    with _OCR_LOCK:
        if _OCR_ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR
            _OCR_ENGINE = RapidOCR()
        res, _ = _OCR_ENGINE(str(image_path))
        return "".join((r[1] or "") for r in (res or []))


def resolve_key(cli: str | None) -> str:
    if cli and cli.strip():
        return cli.strip()
    env = os.environ.get("ICU_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return line
    print("缺少 ICU API key(ICU_API_KEY / icu-key.txt / --key)", file=sys.stderr)
    raise SystemExit(2)


def _ensure_comfy() -> None:
    """ComfyUI API 不通时自动拉起(WSL 内 nohup,自愈)。"""
    s = requests.Session()
    s.trust_env = False
    try:
        s.get(f"{COMFY}/system_stats", timeout=5)
        return
    except requests.exceptions.RequestException:
        pass
    print("[comfy] 服务未启动,自动拉起...", flush=True)
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-lc",
                    "cd ~/ComfyUI && HSA_ENABLE_DXG_DETECTION=1 setsid nohup "
                    "/home/comfy/cosy-gpu-venv/bin/python main.py "
                    "--listen 127.0.0.1 --port 8188 > /tmp/comfy.log 2>&1 < /dev/null & sleep 5"],
                   capture_output=True, timeout=120)
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            s.get(f"{COMFY}/system_stats", timeout=5)
            print("[comfy] 已就绪", flush=True)
            return
        except requests.exceptions.RequestException:
            time.sleep(3)
    raise RuntimeError("ComfyUI 拉起超时(120s),查看 WSL /tmp/comfy.log")


def generate_local(model: str, prompt: str, size: str, timeout: int = 900) -> bytes:
    """本机 ComfyUI SDXL 生图(零成本)。size 如 1536x1024。

    Lightning/Turbo 精调检查点自动使用少步数+低 CFG。
    """
    _ensure_comfy()
    w, h = (int(x) for x in size.lower().split("x"))
    # SDXL 原生桶:限制到最近支持分辨率,防伪影
    buckets = [(1024, 1024), (1344, 768), (768, 1344), (1152, 896), (896, 1152)]
    w, h = min(buckets, key=lambda b: abs(b[0] / b[1] - w / h))
    ml = model.lower()
    if "lightning" in ml or "turbo" in ml or "schnell" in ml:
        steps, cfg, sampler = 8, 1.8, "dpmpp_sde"
    else:
        steps, cfg, sampler = 28, 6.5, "dpmpp_2m"
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": model}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "text, letters, watermark, blurry, low quality, deformed",
                         "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": random.randint(0, 2**31), "steps": steps, "cfg": cfg,
                         "sampler_name": sampler, "scheduler": "karras", "denoise": 1.0,
                         "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0],
                                                    "filename_prefix": "broll"}},
    }
    s = requests.Session()
    s.trust_env = False  # 本机服务不走代理
    r = s.post(f"{COMFY}/prompt", json={"prompt": graph}, timeout=60)
    r.raise_for_status()
    prompt_id = r.json()["prompt_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        h = s.get(f"{COMFY}/history/{prompt_id}", timeout=30).json()
        entry = h.get(prompt_id)
        if entry:
            outputs = entry.get("outputs", {})
            for node in outputs.values():
                for img in node.get("images", []):
                    v = s.get(f"{COMFY}/view", params={"filename": img["filename"],
                                                       "subfolder": img.get("subfolder", ""),
                                                       "type": img.get("type", "output")},
                              timeout=120)
                    v.raise_for_status()
                    return v.content
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(f"ComfyUI 执行失败: {json.dumps(entry.get('status'))[:200]}")
        time.sleep(2)
    raise TimeoutError(f"ComfyUI 生图超时 {timeout}s")


def generate_icu(model: str, prompt: str, size: str, key: str, timeout: int = 600) -> bytes:
    """OpenRouter ICU gpt-image-2 生图(按量计费,作回退)。"""
    attempts = []
    direct = requests.Session()
    direct.trust_env = False
    attempts.append(direct)
    with_env = requests.Session()
    attempts.append(with_env)
    clash = requests.Session()
    clash.proxies = {"http": CLASH, "https": CLASH}
    attempts.append(clash)
    last: Exception | None = None
    for s in attempts:
        try:
            r = s.post(f"{BASE}/images/generations",
                       json={"model": model, "prompt": prompt, "size": size},
                       headers={"User-Agent": UA, "Authorization": f"Bearer {key}"},
                       timeout=timeout)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            d0 = (r.json().get("data") or [{}])[0]
            if d0.get("b64_json"):
                return base64.b64decode(d0["b64_json"])
            if d0.get("url"):
                img = s.get(d0["url"], timeout=300)
                img.raise_for_status()
                return img.content
            raise RuntimeError(f"响应无图片数据: {json.dumps(r.json())[:200]}")
        except requests.exceptions.RequestException as exc:
            last = exc
    raise RuntimeError(f"直连与环境代理均失败: {type(last).__name__}: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", required=True)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--size", default="1344x768")
    parser.add_argument("--model", default="gpt-image-2", help="ICU 后端的模型名")
    parser.add_argument("--ckpt", default="DreamShaperXL_Lightning.safetensors",
                        help="local 后端的 ComfyUI checkpoint 文件名")
    parser.add_argument("--backend", default="auto", choices=["auto", "local", "icu"])
    parser.add_argument("--concurrency", type=int, default=4, help="ICU 并发请求数")
    parser.add_argument("--key", default=None)
    parser.add_argument("--force", action="store_true", help="忽略缓存强制重生成")
    args = parser.parse_args()

    content_path = Path(args.content)
    content = json.loads(content_path.read_text(encoding="utf-8"))
    style = str(content.get("broll_style", "")).strip()
    out_dir = Path(args.out_dir) if args.out_dir else \
        ROOT / "work" / "broll" / content_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = []
    for chapter in content["chapters"]:
        for i, beat in enumerate(chapter.get("broll") or []):
            name = f"{chapter['kind']}_{i}"
            jobs.append((name, build_prompt(style, beat), beat))
        bg_prompt = chapter.get("bg")
        if bg_prompt:
            full_prompt = (style + ". " if style else "") + \
                "Extremely subtle low-contrast background plate, pale and quiet, " \
                "background texture only, no focal subject, no figures, no action. " + str(bg_prompt)
            jobs.append((f"{chapter['kind']}_bg", full_prompt, {"at": 0, "hold": 1}))
    if not jobs:
        print("内容 JSON 没有 broll 节拍,无事可做")
        return 0

    key = resolve_key(args.key)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {key}"})

    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) \
        if manifest_path.exists() else {}
    failed = 0
    # 后端优先级: --backend 显式指定 > 内容 JSON 的 broll_backend(系列级) > 节拍 backend > 本地优先
    series_backend = str(content.get("broll_backend", "")).strip() or None
    resolved = []
    for name, prompt, beat in jobs:
        be = args.backend if args.backend != "auto" else \
            (series_backend or str(beat.get("backend", "")) or "auto")
        if cast_names(beat):
            # 姓名签要写中文,SDXL 画不了:cast 节拍强制 ICU;显式 local 视为配置错误
            if be == "local":
                raise SystemExit(f"{name}: cast 人名标注仅支持 ICU 生图,当前后端 local")
            be = "icu"
        fp = hashlib.sha256(f"{be}|{prompt}".encode()).hexdigest()[:16]
        target = out_dir / f"{name}.png"
        if target.exists() and not args.force and manifest.get(name, {}).get("fp") == fp:
            print(f"[cache] {name}.png", flush=True)
            continue
        resolved.append((name, be, fp, prompt, target, beat))
    if not resolved:
        print("全部命中缓存,无事可做")
        return 0

    # 并发生成:ICU 远程接口 I/O 密集,4 路并发;纯本地(GPU)退化为串行
    workers = 1 if all(be == "local" for _, be, *_ in resolved) else args.concurrency
    lock = threading.Lock()
    icu_dead = threading.Event()  # ICU 额度耗尽后置位,后续自动回退本地

    def worker(item):
        name, be, fp, prompt, target, beat = item
        if icu_dead.is_set() and be in ("auto", "icu"):
            if be == "icu" or series_backend == "icu":
                raise RuntimeError(
                    "ICU 额度不足,且该系列配置为纯 ICU(不用本地模型降级)——按用户要求停止")
            be = "local-first"
        data = None
        if be in ("auto", "local-first", "local"):
            try:
                data = generate_local(args.ckpt, prompt, args.size)
                print(f"[local] {name}", flush=True)
            except Exception as exc:
                if be == "local":
                    raise
                print(f"[warn] local 失败({type(exc).__name__}),回退 ICU", flush=True)
        if data is None:
            try:
                data = generate_icu(args.model, prompt, args.size, key, timeout=600)
                print(f"[icu] {name}", flush=True)
            except RuntimeError as exc:
                msg = str(exc)
                if any(c in msg[:60] for c in ("402", "429", "403")):
                    icu_dead.set()
                    if series_backend == "icu":
                        raise RuntimeError(
                            "ICU 额度不足,且该系列配置为纯 ICU(不用本地模型降级)——按用户要求停止")
                    if cast_names(beat):
                        raise RuntimeError(
                            f"{name}: ICU 额度不足,cast 人名标注无法降级本地(SDXL 画不了中文)")
                    print(f"[warn] ICU 额度不足,本张及后续回退本地: {msg[:100]}", flush=True)
                    data = generate_local(args.ckpt, prompt, args.size)
                    print(f"[local] {name}", flush=True)
                else:
                    raise
        if cast_names(beat):
            _finish_cast(name, beat, cast_names(beat), data, target, fp, prompt,
                         manifest, lock, args, key)
            return
        target.write_bytes(data)
        with lock:
            manifest[name] = {"fp": fp, "bytes": len(data), "prompt": prompt,
                              "at": beat.get("at"), "hold": beat.get("hold")}
        print(f"[ok] {name}.png ({len(data) // 1024} KB)", flush=True)

    def _finish_cast(name, beat, cast, data, target, fp, prompt,
                     manifest, lock, args, key) -> None:
        """姓名签节拍:OCR 校验未命中自动重试;全部失败不落正式文件名。"""
        missing: list[str] = []
        for attempt in range(1, CAST_ATTEMPTS + 1):
            tmp = target.with_suffix(".tmp.png")
            tmp.write_bytes(data)
            missing = names_missing(ocr_image_text(tmp), cast)
            if not missing:
                tmp.replace(target)
                break
            tmp.replace(target.with_suffix(".reject.png"))
            print(f"[ocr] {name} 第{attempt}/{CAST_ATTEMPTS} 次未命中: 缺{missing}",
                  flush=True)
            if attempt < CAST_ATTEMPTS:
                data = generate_icu(args.model, prompt, args.size, key, timeout=600)
                print(f"[icu] {name} 重试生成", flush=True)
        if missing:
            with lock:
                manifest[name] = {"fp": fp, "prompt": prompt, "at": beat.get("at"),
                                  "hold": beat.get("hold"), "cast": cast,
                                  "cast_check": {"ok": False, "missing": missing}}
            raise RuntimeError(f"{name}: 人名标注 OCR 校验连续 {CAST_ATTEMPTS} 次"
                               f"未通过 {missing},末张留 {name}.reject.png 供人工检查")
        with lock:
            manifest[name] = {"fp": fp, "bytes": target.stat().st_size,
                              "prompt": prompt, "at": beat.get("at"),
                              "hold": beat.get("hold"), "cast": cast,
                              "cast_check": {"ok": True}}
        print(f"[ok] {name}.png cast={cast} OCR 全命中 ({target.stat().st_size // 1024} KB)",
              flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        errors = [f.exception() for f in
                  [pool.submit(worker, it) for it in resolved] if f.exception()]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    if errors:
        for exc in errors:
            print(f"[fail] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        print(f"{len(errors)}/{len(resolved)} 张失败", file=sys.stderr)
        return 1
    print(f"全部完成: {len(resolved)} 张 -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
