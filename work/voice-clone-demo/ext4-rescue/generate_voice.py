"""通用逐段中文配音(CosyVoice2 零样本),断点续跑,可选拼接成整轨。

统一支撑两种任务形态:
- 时间槽型(访谈):--items-json 来自 slots+翻译,parts 交给 assemble_fine_runs
- 顺序文本型(中文硬字幕课程):--items-json 来自 OCR 文本切块,
  --concat-out 直接拼成成品音轨(段间静音)

items JSON: [{"id": 0, "text": "中文…", "speaker": "A"}, ...]
refs JSON:  {"A": {"ref_wav": "绝对或相对本文件路径", "ref_text_en": "参考文本"}}

GPU(Windows 调用示例见 clone_episode.sh;核心 env:
 HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1)
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "CosyVoice"))
sys.path.insert(0, str(ROOT / "CosyVoice" / "third_party" / "Matcha-TTS"))


def _rel(p: str, base: Path) -> Path:
    q = Path(p)
    return q if q.is_absolute() else base / q


def _norm_path(p: str) -> Path:
    """跨系统路径:Windows 绝对路径在 WSL/Linux 侧转 /mnt/<drive>/...。
    必须用字符串正则检测盘符——Linux 的 Path('E:\...').drive 是空,
    会被当相对路径拼到 ROOT 下(实测踩坑)。"""
    import os as _os
    import re as _re
    s = str(p)
    m = _re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        if _os.name != "nt":
            return Path("/mnt/" + m.group(1).lower() + "/"
                        + m.group(2).replace("\\", "/"))
        return Path(s)
    q = Path(s)
    return q if q.is_absolute() else ROOT / q


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--items-json", required=True,
                    help="[{id,text,speaker}] 文本可为 slots_zh 映射后的列表")
    ap.add_argument("--refs-json", required=True)
    ap.add_argument("--out-dir", required=True, help="逐段 wav 输出目录")
    ap.add_argument("--concat-out", default=None,
                    help="可选:顺序拼接(0.25s 间隔)成整轨 wav")
    ap.add_argument("--model-dir",
                    default=str(ROOT / "models" / "CosyVoice2-0.5B"))
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--gap-ms", type=int, default=250)
    args = ap.parse_args()

    items_path = _norm_path(args.items_json)
    refs_path = _norm_path(args.refs_json)
    out_dir = _norm_path(args.out_dir)
    model_dir = _norm_path(args.model_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    items = json.loads(items_path.read_text(encoding="utf-8"))
    refs = json.loads(refs_path.read_text(encoding="utf-8"))
    for spk, ref in refs.items():
        ref["ref_wav_abs"] = str(_norm_path(ref["ref_wav"]))

    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    from cosyvoice.cli.cosyvoice import AutoModel
    model = AutoModel(model_dir=str(model_dir), load_jit=False,
                      load_trt=False, load_vllm=False, fp16=False)

    t0 = time.time()
    made = 0
    for n, it in enumerate(items, 1):
        out = out_dir / f"item_{int(it['id']):04d}.wav"
        if out.exists() and out.stat().st_size > 1000:
            continue
        spk = refs[it["speaker"]]
        pieces = [r["tts_speech"] for r in model.inference_zero_shot(
            it["text"], spk["ref_text_en"], spk["ref_wav_abs"], stream=False)]
        speech = torch.cat(pieces, dim=1)
        torchaudio.save(str(out), speech, model.sample_rate)
        made += 1
        dur = speech.shape[1] / model.sample_rate
        print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(items)} "
              f"id={it['id']} {it['speaker']} gen={dur:.1f}s", flush=True)

    print(f"parts done made={made} total={len(items)} "
          f"elapsed={(time.time() - t0) / 60:.1f}min", flush=True)

    if args.concat_out:
        concat = _norm_path(args.concat_out)
        gap = torch.zeros(1, int(model.sample_rate * args.gap_ms / 1000))
        clips = []
        for it in items:
            w, _ = torchaudio.load(
                str(out_dir / f"item_{int(it['id']):04d}.wav"))
            clips.append(w)
        combined = clips[0]
        for w in clips[1:]:
            combined = torch.cat([combined, gap, w], dim=1)
        torchaudio.save(str(concat), combined, model.sample_rate)
        total = combined.shape[1] / model.sample_rate
        print(f"concat {len(clips)} 段 -> {concat} ({total / 60:.1f}min)",
              flush=True)


if __name__ == "__main__":
    main()
