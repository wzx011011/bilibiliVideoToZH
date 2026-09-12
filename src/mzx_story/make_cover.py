# -*- coding: utf-8 -*-
"""《明朝故事》封面生成:gpt-image-2 出图 + 本地合成标题文字。

- API key 只从环境变量 OPENAI_API_KEY 或仓库根 .env 读取,绝不写入代码或提交。
- 网络走 Clash 代理(默认 127.0.0.1:7897,可用环境变量覆盖)。
- 原图按 模型+提示词+尺寸 指纹缓存到 work/studio/covers/,manifest 记录模型/
  提示词/时间/哈希,保证可追溯、可复现。
- 生成图统一 1536x1024 → 居中裁 16:9 → 1920x1080;标题文字本地绘制,
  不让图像模型渲染中文(避免错字)。

用法:
  python src/mzx_story/make_cover.py                # 调 API 生成+合成
  python src/mzx_story/make_cover.py --compose      # 只用缓存原图重新合成文字
  python src/mzx_story/make_cover.py --compose --raw X.png
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE_DIR = ROOT / "work" / "studio" / "covers"
OUT_JPG = ROOT / "videos" / "cover-ming01.jpg"

MODEL = "gpt-image-2"
FALLBACK_MODEL = "gpt-image-1"
SIZE = "1536x1024"
QUALITY = "high"
PROMPT = (
    "Horizontal cover illustration, flat vector picture-book style on warm aged "
    "parchment paper: early Ming dynasty China, 1402. On the right, a determined "
    "Ming prince in a dark-red war robe and black helmet rides a rearing black "
    "horse, raising a sword high; behind him, armored cavalry and tall red war "
    "banners (plain cloth, no writing). On the left, the distant Nanjing imperial "
    "palace behind city walls, stylized orange flames and dark smoke rising into "
    "an amber dusk sky. Palette: vermilion red, imperial yellow, indigo blue, "
    "cream parchment. Clean bold shapes, subtle paper grain, dramatic cinematic "
    "composition with calm empty parchment space in the lower left for a title. "
    "Absolutely no text, no letters, no characters, no seals, no watermark."
)

INK = (45, 42, 38)
PAPER = (243, 238, 228)
RED = (176, 48, 42)
BLUE = (42, 72, 110)


def load_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key:
                    return key
    raise RuntimeError(
        "缺少 OPENAI_API_KEY:请在环境变量或仓库根 .env 中提供"
        "(OPENAI_API_KEY=sk-...),且账号需有图像生成权限")


def _opener() -> urllib.request.OpenerDirector:
    proxy = (os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
             or "http://127.0.0.1:7897")
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}))


def generate_image(model: str = MODEL) -> tuple[Path, dict]:
    """调用图像生成接口,返回缓存文件与 manifest;命中缓存则不请求。"""
    fingerprint = hashlib.sha256(
        f"{model}|{SIZE}|{QUALITY}|{PROMPT}".encode()).hexdigest()[:16]
    raw = CACHE_DIR / f"ming01-{fingerprint}.png"
    manifest = {
        "model": model, "prompt": PROMPT, "size": SIZE, "quality": QUALITY,
        "file": str(raw), "fingerprint": fingerprint,
    }
    if raw.exists() and raw.stat().st_size > 10_000:
        return raw, manifest

    key = load_api_key()
    body = json.dumps({"model": model, "prompt": PROMPT, "size": SIZE,
                       "quality": QUALITY}).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/images/generations", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with _opener().open(request, timeout=600) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[-400:]
        if exc.code == 404 and "model" in detail and model == MODEL:
            print(f"[warn] {model} 不可用,回退 {FALLBACK_MODEL}", file=sys.stderr)
            return generate_image(FALLBACK_MODEL)
        raise RuntimeError(f"图像生成失败 HTTP {exc.code}: {detail}") from exc

    b64 = payload["data"][0].get("b64_json")
    if not b64:
        raise RuntimeError(f"响应缺少 b64_json: {str(payload)[:200]}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(base64.b64decode(b64))
    manifest.update({"created": datetime.now().isoformat(timespec="seconds"),
                     "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()})
    (CACHE_DIR / f"ming01-{fingerprint}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw, manifest


def _font(size: int, bold: bool = False, kai: bool = False) -> ImageFont.ImageFont:
    names = (("simkai.ttf",) if kai else
             ("msyhbd.ttc",) if bold else ("msyh.ttc",))
    for name in names:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose(raw_path: Path, output: Path = OUT_JPG,
            kicker: str = "明朝故事 · 第 01 集", title: str = "靖难之役",
            subtitle: str = "—— 叔叔和侄子的火并") -> Path:
    """原图 → 16:9 裁切 → 1920x1080,左下合成节目标题。"""
    img = Image.open(raw_path).convert("RGB")
    width, height = img.size
    target_h = width * 9 // 16
    if target_h <= height:
        top = (height - target_h) * 45 // 100
        img = img.crop((0, top, width, top + target_h))
    else:
        target_w = height * 16 // 9
        left = (width - target_w) // 2
        img = img.crop((left, 0, left + target_w, height))
    img = img.resize((1920, 1080), Image.LANCZOS)
    d = ImageDraw.Draw(img)

    f_tag = _font(46, bold=True)
    tag_w = d.textlength(kicker, font=f_tag)
    d.rounded_rectangle((84, 78, 84 + tag_w + 60, 78 + 78), radius=14, fill=RED)
    d.text((114, 92), kicker, font=f_tag, fill=PAPER)

    # 标题字数多时缩小字号,保证不出画幅
    f_title = _font(200 if len(title) <= 4 else 150, kai=True)
    d.text((92, 566), title, font=f_title, fill=(20, 18, 16),
           stroke_width=14, stroke_fill=(20, 18, 16))
    d.text((92, 566), title, font=f_title, fill=INK,
           stroke_width=10, stroke_fill=PAPER)

    f_sub = _font(58, bold=True)
    d.text((100, 920), subtitle, font=f_sub, fill=(20, 18, 16),
           stroke_width=8, stroke_fill=(20, 18, 16))
    d.text((100, 920), subtitle, font=f_sub, fill=BLUE,
           stroke_width=5, stroke_fill=PAPER)

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, "JPEG", quality=92)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", action="store_true", help="跳过 API,只用原图合成")
    parser.add_argument("--raw", type=Path, help="指定原图(配合 --compose 或调试)")
    parser.add_argument("--out", type=Path, default=OUT_JPG, help="输出封面路径")
    parser.add_argument("--kicker", default="明朝故事 · 第 01 集", help="左上角系列标签")
    parser.add_argument("--title", default="靖难之役", help="主标题(大字)")
    parser.add_argument("--subtitle", default="—— 叔叔和侄子的火并", help="副标题")
    args = parser.parse_args()
    try:
        if args.raw:
            raw, manifest = args.raw, {"source": "manual", "file": str(args.raw)}
        else:
            raw, manifest = generate_image()
        cover = compose(raw, args.out, args.kicker, args.title, args.subtitle)
        manifest["cover"] = str(cover)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
