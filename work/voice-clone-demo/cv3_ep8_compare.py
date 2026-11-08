# -*- coding: utf-8 -*-
"""CV3 试音客观对比(ep08):三组逐章 ASR 回环 + 同音容错 CER + 试听包。

组:CV2纠音基线(D:/mzx-ming08/parts) / CV3原文(narr) / CV3纠音(tts)。
注意:transcribe 每次调用重载 1.6GB 模型,这里自管共享 WhisperModel;
文本比对复用 src/av_qc.py 的 normalize_spoken/chapter_diff(同音字不计错)。
"""
from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from av_qc import normalize_spoken, chapter_diff  # noqa: E402

CONTENT = ROOT / "src/mzx_story/ming-08-hongzhi.json"
ASR_DIR = ROOT / "work/models/faster-whisper-large-v3-turbo"
BASE = Path("D:/mzx-ming08")
AUD = BASE / "cv3-audition"

GROUPS = [  # (组名, parts 目录, 期望文本 key)
    ("CV2纠音基线", BASE / "parts", "tts"),
    ("CV3原文", AUD / "narr/parts", "narr"),
    ("CV3纠音", AUD / "tts/parts", "tts"),
]
KEY_CHAPTERS = {0: ["朱祐樘", "弘治"], 6: ["斋醮", "朱祐樘"], 7: ["弘治中兴"]}


def asr_parts(model, wav: Path, cache: Path):
    """逐段转写,带缓存(格式同 align_srt_asr)。"""
    if cache.exists() and cache.stat().st_mtime >= wav.stat().st_mtime:
        return [(d["start"], d["end"], d["text"]) for d in
                json.loads(cache.read_text(encoding="utf-8"))]
    segments, _ = model.transcribe(str(wav), language="zh",
                                   beam_size=5, vad_filter=True)
    out = [{"start": round(s.start, 2), "end": round(s.end, 2),
            "text": s.text.strip()} for s in segments if s.text.strip()]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return [(d["start"], d["end"], d["text"]) for d in out]


def main() -> None:
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    chapters = content["chapters"]
    texts = {
        "narr": [c["narration"] for c in chapters],
        "tts": [c.get("tts_narration") or c["narration"] for c in chapters],
    }

    from faster_whisper import WhisperModel
    model = WhisperModel(str(ASR_DIR), device="cpu", compute_type="int8")

    report = {}
    for gname, parts, key in GROUPS:
        rows = []
        for i, ch in enumerate(chapters):
            wav = parts / f"item_{i:04d}.wav"
            if not wav.exists():
                rows.append({"chapter": ch["title"], "missing": True})
                continue
            cache = AUD / ".asr-cache" / gname / f"item_{i:04d}.json"
            got_raw = "".join(t for _, _, t in asr_parts(model, wav, cache))
            diff = chapter_diff(normalize_spoken(texts[key][i]),
                                normalize_spoken(got_raw))
            hard = (sum(len(s["expected"]) for s in diff["substitutions"]
                        if not s["homophone"])
                    + sum(len(m["expected"]) for m in diff["missing"]))
            rows.append({
                "chapter": ch["title"],
                "cer": diff["cer"], "hard_chars": hard,
                "expected": texts[key][i], "got_raw": got_raw,
                "suspects": [s for s in diff["substitutions"]
                             if not s["homophone"]][:6],
            })
            print(f"[{gname}] ch{i + 1} {ch['title']}: "
                  f"cer={diff['cer']:.3f} hard={hard}", flush=True)
        report[gname] = rows

    # markdown 报告
    lines = ["# CV3 试音客观对比(ep08 弘治中兴)", "",
             "CER=同音容错后字错误率;hard=异音错字+漏字数(真读错嫌疑)。", ""]
    for gname, _, _ in GROUPS:
        rows = report[gname]
        cer_all = sum(r["cer"] * len(normalize_spoken(r.get("expected", "")))
                      for r in rows if not r.get("missing")) / max(
            1, sum(len(normalize_spoken(r.get("expected", "")))
                   for r in rows if not r.get("missing")))
        lines += [f"## {gname}(整体 CER {cer_all:.3f})", "",
                  "| 章 | CER | 异音错+漏 |", "|---|---|---|"]
        for r in rows:
            if r.get("missing"):
                lines.append(f"| {r['chapter']} | 缺文件 | - |")
            else:
                lines.append(f"| {r['chapter']} | {r['cer']:.3f} "
                             f"| {r['hard_chars']} |")
        lines.append("")
    lines += ["## 关键词读音核对(whisper 转写原文)", ""]
    for gname, _, key in GROUPS:
        lines.append(f"### {gname}")
        for ci, kws in KEY_CHAPTERS.items():
            r = report[gname][ci]
            if r.get("missing"):
                continue
            lines.append(f"- ch{ci + 1} {r['chapter']}(关注 {'、'.join(kws)}):"
                         f" {r['got_raw']}")
        lines.append("")
    (AUD / "对比报告.md").write_text("\n".join(lines), encoding="utf-8")
    (AUD / "compare.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # 试听包
    pkg = AUD / "试听包"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    for gname, parts, _ in GROUPS:
        for i, ch in enumerate(chapters):
            src = parts / f"item_{i:04d}.wav"
            if src.exists():
                shutil.copy2(src, pkg / f"{i + 1:02d}-{ch['title']}-{gname}.wav")
    fulls = [("CV2纠音基线", BASE / "audio.wav"),
             ("CV3原文", AUD / "narr/audio.wav"),
             ("CV3纠音", AUD / "tts/audio.wav")]
    for gname, src in fulls:
        if src.exists():
            shutil.copy2(src, pkg / f"整轨-{gname}.wav")
    shutil.copy2(AUD / "对比报告.md", pkg / "对比报告.md")
    print(f"试听包: {pkg}", flush=True)


if __name__ == "__main__":
    main()
