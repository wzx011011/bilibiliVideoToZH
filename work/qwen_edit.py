# -*- coding: utf-8 -*-
"""Qwen-Image-2.1 图生图修复链:低强度重绘,外科手术式修图(治错字旗/露馅肢体/局部杂物)。

与整张重 roll 的区别:保留画面构图与人物,denoise 越低越接近原图。
用法:
  work/.venv-ocr/Scripts/python.exe work/qwen_edit.py \
    --img work/broll/qh-01-changping/s6_1.png \
    --prompt "同场景,把所有旗帜改成素色红旗,旗面不写任何字" \
    --out work/broll/_edit_test.png --denoise 0.55
"""
from __future__ import annotations

import argparse
import importlib.util
import time
from pathlib import Path

import requests


def _load_qwen():
    spec = importlib.util.spec_from_file_location("qgen", str(Path(__file__).with_name("qwen_gen.py")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def edit(img_path: Path, prompt: str, out: Path, *, denoise: float = 0.55,
         preset: str = "qwen21-turbo", seed: int = 7, size: str = "1536x864",
         timeout: int = 1800) -> Path:
    q = _load_qwen()
    q.ensure_comfy()
    p = q.PRESETS[preset]
    s = q._session()

    up = s.post(f"{q.COMFY}/upload/image",
                files={"image": (img_path.name, open(img_path, "rb"), "image/png")},
                data={"overwrite": "true"}, timeout=120)
    up.raise_for_status()
    img_ref = up.json()

    w, h = (int(x) for x in size.lower().split("x"))
    loader = ({"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": p["unet"]}}
              if p["loader"] == "gguf" else
              {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet"], "weight_dtype": "default"}})
    graph = {
        "1": loader,
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": p["clip"], "type": "qwen_image", "device": "cpu"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": p["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": q.NEGATIVE, "clip": ["2", 0]}},
        "6": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3.1, "model": ["1", 0]}},
        "7": {"class_type": "LoadImage", "inputs": {"image": img_ref["name"]}},
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "ImageScale", "inputs": {"upscale_method": "lanczos", "width": w,
                                                     "height": h, "crop": "center",
                                                     "image": ["7", 0]}},
        "10": {"class_type": "VAEEncode", "inputs": {"pixels": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "KSampler",
               "inputs": {"seed": seed, "steps": p["steps"], "cfg": p["cfg"],
                          "sampler_name": "euler", "scheduler": "simple",
                          "denoise": denoise, "model": ["6", 0],
                          "positive": ["4", 0], "negative": ["5", 0],
                          "latent_image": ["10", 0]}},
        "12": {"class_type": "VAEDecodeTiled",
               "inputs": {"samples": ["11", 0], "vae": ["3", 0], "tile_size": 512,
                          "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["12", 0], "filename_prefix": "qwen_edit"}},
    }
    r = s.post(f"{q.COMFY}/prompt", json={"prompt": graph}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI 校验拒绝({r.status_code}): {r.text[:400]}")
    pid = r.json()["prompt_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        hist = s.get(f"{q.COMFY}/history/{pid}", timeout=30).json().get(pid)
        if hist:
            for node in hist.get("outputs", {}).values():
                for im in node.get("images", []):
                    v = s.get(f"{q.COMFY}/view", params={
                        "filename": im["filename"], "subfolder": im.get("subfolder", ""),
                        "type": im.get("type", "output")}, timeout=120)
                    v.raise_for_status()
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(v.content)
                    return out
            if hist.get("status", {}).get("status_str") == "error":
                raise RuntimeError(f"执行失败: {str(hist.get('status'))[:300]}")
        time.sleep(5)
    raise TimeoutError(f"编辑超时 {timeout}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--img", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--denoise", type=float, default=0.55)
    ap.add_argument("--preset", default="qwen21-turbo")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--size", default="1536x864")
    a = ap.parse_args()
    p = edit(Path(a.img), a.prompt, Path(a.out), denoise=a.denoise,
             preset=a.preset, seed=a.seed, size=a.size)
    print("完成:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
