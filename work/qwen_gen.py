# -*- coding: utf-8 -*-
"""Qwen-Image 本地生图(ComfyUI GGUF):秦汉前传试播集专用。

配方来自 work/probe-qwen-image/README.md:
UnetLoaderGGUF + CLIPLoader(qwen_image, device=cpu) + ModelSamplingAuraFlow(shift=3.1)
+ euler/simple 20 步 cfg 2.5 + VAEDecodeTiled(tile 512)。

用法:
  work/.venv-ocr/Scripts/python.exe work/qwen_gen.py --job work/qh_ep00_images.json
job 文件: [{"out": "work/broll/qh-00-shangyang/s1_bg.png", "prompt": "...", "seed": 33}, ...]
已有输出且非 --force 时跳过(断点续跑)。
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import requests

COMFY = "http://127.0.0.1:8188"

# 模型预设:qwen2512(第一代,2025-12)/ qwen21(第二代 Q8_0 GGUF)/
# qwen21-turbo(第二代 turbo int8,官方推荐 8 步 CFG1.0,速度约 2.5 倍)
PRESETS = {
    "qwen2512": {
        "loader": "gguf", "unet": "qwen-image-2512-Q4_K_S.gguf",
        "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
        "vae": "qwen_image_vae.safetensors", "steps": 20, "cfg": 2.5,
    },
    "qwen21": {
        "loader": "gguf", "unet": "qwen_image_2.1_Q8_0.gguf",
        "clip": "qwen3vl_8b_int8_convrot.safetensors",
        "vae": "qwen_image_2.1_vae_bf16.safetensors", "steps": 20, "cfg": 2.5,
    },
    "qwen21-turbo": {
        "loader": "unet", "unet": "qwen_image_2.1_turbo_int8_convrot.safetensors",
        "clip": "qwen3vl_8b_int8_convrot.safetensors",
        "vae": "qwen_image_2.1_vae_bf16.safetensors", "steps": 8, "cfg": 1.0,
    },
}
NEGATIVE = ("photorealistic, painterly brushwork, oil painting, 3D render, gradient "
            "shading, glossy highlights, text, letters, watermark, blurry, low quality, "
            "extra limbs, extra fingers, deformed hands, bad anatomy, duplicate faces, "
            "fused bodies, cropped heads, twisted torso")


def ensure_comfy() -> None:
    s = _session()
    try:
        s.get(f"{COMFY}/system_stats", timeout=5)
        return
    except requests.exceptions.RequestException:
        pass
    print("[comfy] 服务未启动,自动拉起...", flush=True)
    import subprocess
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-lc",
                    "cd ~/ComfyUI && HSA_ENABLE_DXG_DETECTION=1 setsid nohup "
                    "/home/comfy/cosy-gpu-venv/bin/python main.py "
                    "--listen 127.0.0.1 --port 8188 > /tmp/comfy.log 2>&1 < /dev/null & sleep 5"],
                   capture_output=True, timeout=120)
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            s.get(f"{COMFY}/system_stats", timeout=5)
            print("[comfy] 已就绪", flush=True)
            return
        except requests.exceptions.RequestException:
            time.sleep(3)
    raise RuntimeError("ComfyUI 拉起超时(300s),查看 WSL /tmp/comfy.log")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 本机服务不走代理
    return s


def generate(prompt: str, size: str, seed: int, timeout: int = 1800,
             preset: str = "qwen2512") -> bytes:
    p = PRESETS[preset]
    w, h = (int(x) for x in size.lower().split("x"))
    if p["loader"] == "gguf":
        loader = {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": p["unet"]}}
    else:
        loader = {"class_type": "UNETLoader",
                  "inputs": {"unet_name": p["unet"], "weight_dtype": "default"}}
    graph = {
        "1": loader,
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": p["clip"], "type": "qwen_image", "device": "cpu"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": p["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["2", 0]}},
        "6": {"class_type": "ModelSamplingAuraFlow",
              "inputs": {"shift": 3.1, "model": ["1", 0]}},
        "7": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": p["steps"], "cfg": p["cfg"],
                         "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
                         "model": ["6", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecodeTiled",
              "inputs": {"samples": ["8", 0], "vae": ["3", 0], "tile_size": 512,
                         "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["9", 0], "filename_prefix": f"qwen_{preset}"}},
    }
    s = _session()
    r = s.post(f"{COMFY}/prompt", json={"prompt": graph}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI 校验拒绝({r.status_code}): {r.text[:500]}")
    prompt_id = r.json()["prompt_id"]
    print(f"[qwen] 已提交 {prompt_id} seed={seed}", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        h = s.get(f"{COMFY}/history/{prompt_id}", timeout=30).json()
        entry = h.get(prompt_id)
        if entry:
            for node in entry.get("outputs", {}).values():
                for img in node.get("images", []):
                    v = s.get(f"{COMFY}/view", params={
                        "filename": img["filename"], "subfolder": img.get("subfolder", ""),
                        "type": img.get("type", "output")}, timeout=120)
                    v.raise_for_status()
                    return v.content
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(f"ComfyUI 执行失败: {json.dumps(entry.get('status'))[:300]}")
        time.sleep(5)
    raise TimeoutError(f"Qwen 生图超时 {timeout}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True, help="任务 JSON 路径")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--preset", default="qwen21-turbo", choices=sorted(PRESETS),
                    help="模型预设(默认 2.1-turbo:8步CFG1,质量近基座、速度快2.5倍)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    jobs = json.loads(Path(args.job).read_text(encoding="utf-8"))
    ensure_comfy()
    ok = 0
    for i, job in enumerate(jobs):
        out = Path(job["out"])
        if out.exists() and not args.force:
            print(f"[qwen] 跳过(已存在): {out}", flush=True)
            ok += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        seed = job.get("seed", random.randint(0, 2**31))
        used_preset = job.get("preset", args.preset)
        print(f"[qwen] ({i + 1}/{len(jobs)}) {out.name} preset={used_preset} seed={seed}",
              flush=True)
        try:
            data = generate(job["prompt"], job.get("size", args.size), seed,
                            preset=used_preset)
        except Exception as exc:
            # 已知坑:turbo 个别 seed 会触发 ROCm 采样死锁(服务端任务永远不结束)。
            # 超时类失败自动换种子重试一次(需先重启 ComfyUI 清掉卡死的任务)。
            if "超时" in str(exc):
                import subprocess
                # 实证(2026-10-13 ep00 三连超时):GPU/WSL 坏态普通重启救不回,
                # 必须 wsl --shutdown 整机重置后才恢复——自愈直接上整机关机。
                subprocess.run(["wsl", "--shutdown"], timeout=120)
                import time as _t; _t.sleep(6)
                ensure_comfy()
                seed = seed + 1
                print(f"[qwen] 采样死锁,换 seed={seed} 重试", flush=True)
                try:
                    data = generate(job["prompt"], job.get("size", args.size), seed,
                                    preset=used_preset)
                except Exception as exc2:
                    print(f"[qwen] 失败: {out.name}: {exc2}", flush=True)
                    continue
            else:
                print(f"[qwen] 失败: {out.name}: {exc}", flush=True)
                continue
        out.write_bytes(data)
        ok += 1
        print(f"[qwen] 完成: {out}", flush=True)
    print(f"[qwen] 全部结束 {ok}/{len(jobs)}", flush=True)
    return 0 if ok == len(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
