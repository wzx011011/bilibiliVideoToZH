# -*- coding: utf-8 -*-
"""cast 姓名签 PIL 盖章兜底(泛化版)。

gpt-image-2 对部分字有顽固形近字先验(实测"涟"9 连写成"连",改图接口也修不动),
OCR 门禁连续失败后走本脚本:无人名签纯场景出图 → PIL 羊皮纸签+楷书按码位直写
(构造正确)→ manifest 登记 cast_check=pil-stamped。OCR 仅参考(该引擎对楷书竖排
小字有已知形近字偏差)。

用法: python work/fix_cast_stamp.py <slug> <beat> "左·杨涟"
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from broll.generate import build_prompt  # noqa: E402

slug, beat, cast_entry = sys.argv[1], sys.argv[2], sys.argv[3]
NAME = cast_entry.split("·")[-1].strip()
BDIR = ROOT / "work" / "broll" / slug
CONTENT = json.loads(
    (ROOT / "src" / "mzx_story" / f"{slug}.json").read_text(encoding="utf-8"))
GEN = "C:/Users/67376/.zcode/skills/icu-image/scripts/generate.py"

beat_def = None
for c in CONTENT["chapters"]:
    for i, b in enumerate(c.get("broll", [])):
        if f"{c['kind']}_{i}" == beat:
            beat_def = dict(b)
            beat_def.pop("cast", None)
if beat_def is None:
    sys.exit(f"[fail] {slug} 里找不到节拍 {beat}")

prompt = build_prompt(CONTENT.get("broll_style", ""), beat_def)
out = BDIR / f"{beat}.png"
if not out.exists():
    print("[gen] 纯场景出图...", flush=True)
    r = subprocess.run([sys.executable, GEN, "--prompt", prompt, "--out", str(out),
                        "--size", "1344x768"], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        print(r.stdout[-300:], r.stderr[-300:])
        sys.exit(f"[fail] {beat} 场景出图失败")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

im = Image.open(out).convert("RGB")
W, H = im.size
SLIP_W, SLIP_H = int(W * 0.062), int(H * 0.50)
X0, Y0 = int(W * 0.014), int(W * 0.014)
slip = Image.new("RGB", (SLIP_W, SLIP_H), (233, 222, 198))
sd = ImageDraw.Draw(slip)
sd.rectangle([0, 0, SLIP_W - 1, SLIP_H - 1], outline=(120, 100, 74), width=2)
sd.ellipse([SLIP_W * 0.5 - 5, 7, SLIP_W * 0.5 + 5, 17], fill=(168, 52, 40))
font = ImageFont.truetype("C:/Windows/Fonts/simkai.ttf", int(SLIP_W * 0.70))
ty = int(SLIP_H * 0.09)
for ch in NAME:
    sd.text((SLIP_W / 2, ty), ch, font=font, fill=(30, 27, 24), anchor="ma")
    ty += int(SLIP_W * 0.78)
im.paste(slip, (X0, Y0))
im.save(out)
print(f"[stamp] {beat} 姓名签已盖: {NAME}", flush=True)

man_path = BDIR / "manifest.json"
man = json.loads(man_path.read_text(encoding="utf-8"))
if beat in man and isinstance(man[beat], dict):
    man[beat]["cast_check"] = f"pil-stamped({NAME})"
    man[beat]["status"] = "ok"
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1),
                        encoding="utf-8")
print("[manifest] updated", flush=True)

from rapidocr_onnxruntime import RapidOCR  # noqa: E402
res, _ = RapidOCR()(str(out))
texts = [t for _, t, _ in (res or [])]
print("[ocr]", texts, "(引擎形近字偏差仅供参考)", flush=True)
if not any(NAME in t for t in texts):
    print("[note] OCR 未命中;签为 PIL 按码位直写,构造正确,接受", flush=True)
print("[ok] 完成", flush=True)
