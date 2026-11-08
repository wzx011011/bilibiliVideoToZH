# -*- coding: utf-8 -*-
"""明朝 cast 纪律的本地出图版:人名签画进图 + RapidOCR 回读校验 + 不合规换种子重生成。

用法:
  work/.venv-ocr/Scripts/python.exe work/qwen_cast_gen.py --job work/qh_ep01_images_r3.json
job 条目: {out, seed, prompt, cast?: "廉颇"}  cast 缺省单次生成;有 cast 时至多 3 次尝试,
OCR 未命中人名则 seed+7 重试;始终生成(无跳过),杜绝新旧风格混切。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
from pathlib import Path

# OpenBLAS 按全核开线程会内存分配失败(2026-10-14 实证),锁单线程
for _k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "1")


def load_qwen():
    spec = importlib.util.spec_from_file_location("qgen", str(Path(__file__).with_name("qwen_gen.py")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    ap.add_argument("--size", default="1280x720")
    args = ap.parse_args()

    jobs = json.loads(Path(args.job).read_text(encoding="utf-8"))
    q = load_qwen()
    q.ensure_comfy()

    ocr = None
    def get_ocr():
        nonlocal ocr
        if ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            ocr = RapidOCR()
        return ocr

    ok_n = 0
    for i, job in enumerate(jobs):
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        cast = job.get("cast")
        tries = 3 if cast else 2  # 非 cast 也留 1 次基础设施重试(WSL 空闲回收杀服务)
        done = False
        for att in range(tries):
            q.ensure_comfy()      # 每次尝试前确认服务活着(空闲回收自愈)
            seed = job["seed"] + att * 7
            print(f"[cast] ({i + 1}/{len(jobs)}) {out.name} seed={seed}"
                  + (f" cast={cast}" if cast else ""), flush=True)
            try:
                data = q.generate(job["prompt"], job.get("size", args.size), seed,
                                  preset=job.get("preset", "qwen21-turbo"))
            except Exception as exc:
                print(f"[cast] 生成失败: {exc}", flush=True)
                continue
            tmp = out.with_suffix(".try.png")
            tmp.write_bytes(data)
            if cast:
                res, _ = get_ocr()(str(tmp))
                text = "".join(x[1] for x in (res or []))
                hit = job["cast"] in text
                print(f"[cast] OCR {'命中' if hit else '未命中'}({text[:36]})", flush=True)
                if not hit and att < tries - 1:
                    continue
            tmp.replace(out)
            done = True
            break
        ok_n += done
        if not done:
            print(f"[cast] 放弃: {out.name}", flush=True)
    print(f"[cast] 全部结束 {ok_n}/{len(jobs)}", flush=True)
    return 0 if ok_n == len(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
