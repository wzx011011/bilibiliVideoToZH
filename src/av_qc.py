# -*- coding: utf-8 -*-
"""音视频内容一致性 QC(发布前门禁):ASR 回环 + 字幕对齐 + 画面配对清单。

三件校验(对应 TTS/字幕行业成熟做法):
1. 发音校验 = ASR 回环:成品音频用 faster-whisper 转回文字,与 TTS 期望文本
   逐字比对 → CER(字错误率,TTS 行业标准的可懂度指标),并列出全部"可疑错读"
   (替换/缺失字符及出现时间),人工或 VLM 复核。
2. 字幕对齐 = 字幕 cue 时间与 ASR 分段时间的漂移检查。
3. 画面配对清单 = 每个抽样帧记录(当期字幕, 当期分镜节拍, 图层类型),
   输出给人工或视觉模型审查"画面是否表达了当期旁白"。

用法(work/.venv-ocr 环境,含 faster-whisper):
  work/.venv-ocr/Scripts/python.exe src/av_qc.py \
    --content src/mzx_story/ming-05-tumu-icu.json \
    --audio D:/mzx-ming05-icu/audio.wav \
    --timeline D:/mzx-ming05-icu/timeline.json \
    --srt D:/mzx-ming05-icu/subtitles.srt \
    --out D:/mzx-ming05-icu/qc_report.json
退出码: 0=PASS  1=FAIL(超阈值)  2=参数/环境错误
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from align_srt_asr import parse_srt, transcribe  # noqa: E402
from pypinyin import lazy_pinyin  # noqa: E402

_DIGITS = str.maketrans("0123456789", "零一二三四五六七八九")
_HANZI = re.compile(r"[\u4e00-\u9fff]")

# whisper 在静音/收尾段的经典幻觉串(训练语料里的频道水印),不是音频真实内容;
# 按原始文本匹配(含拉丁字母,须在 normalize_spoken 去拉丁之前过滤)
_HALLUCINATION_MARKS = (
    "明镜与点点", "请不吝点赞", "转发打赏", "独播剧场",
    "yoyo television", "字幕由", "字幕 provided",
)


def is_hallucination(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in _HALLUCINATION_MARKS)


def drop_hallucination(segs: list) -> list:
    kept = [s for s in segs if not is_hallucination(s[2])]
    for s in segs:
        if is_hallucination(s[2]):
            print(f"[qc] 丢弃 ASR 幻觉段 {s[0]:.1f}-{s[1]:.1f}s: {s[2]!r}")
    return kept


def normalize_spoken(text: str) -> str:
    """归一化为"口播字序":数字转汉字读法,去标点/空格/拉丁,仅保留汉字。"""
    text = text.translate(_DIGITS)
    return "".join(_HANZI.findall(text))


def _pinyin(text: str) -> str:
    return "".join(lazy_pinyin(text))


def _is_homophone(a: str, b: str) -> bool:
    """替换两侧拼音一致 → 同音字转写(无害);否则异音(真错读嫌疑)。"""
    try:
        return _pinyin(a) == _pinyin(b)
    except Exception:
        return False


def chapter_diff(expected: str, got: str) -> dict:
    """逐字比对 → CER 与可疑清单;拼音层把替换分为同音(轻)与异音(重)。"""
    sm = SequenceMatcher(None, expected, got, autojunk=False)
    subs, missing, extra = [], [], []
    cer = 0
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            continue
        cer += max(a1 - a0, b1 - b0)
        ctx_a = expected[max(0, a0 - 4):a0] + "【" + expected[a0:a1] + "】" + expected[a1:a1 + 4]
        if op == "replace":
            frag_a, frag_b = expected[a0:a1], got[b0:b1]
            subs.append({"at": a0, "expected": frag_a, "got": frag_b,
                         "context": ctx_a,
                         "homophone": _is_homophone(frag_a, frag_b)})
        elif op == "delete":
            missing.append({"at": a0, "expected": expected[a0:a1], "context": ctx_a})
        elif op == "insert":
            extra.append({"at": a0, "got": got[b0:b1]})
    return {"expected_chars": len(expected), "errors": cer,
            "cer": round(cer / max(1, len(expected)), 4),
            "substitutions": subs, "missing": missing, "insertions": extra}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--timeline", default=None, help="渲染器 timeline.json(章节起止)")
    parser.add_argument("--srt", default=None, help="字幕 SRT(对齐漂移检查)")
    parser.add_argument("--parts-dir", default=None,
                        help="逐章音频目录(item_*.wav),优先:逐章转写消除边界串扰")
    parser.add_argument("--out", default=None, help="QC 报告输出路径")
    parser.add_argument("--asr-cache", default=None)
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--cer-max", type=float, default=0.06, help="整体 CER 阈值")
    parser.add_argument("--chapter-cer-max", type=float, default=0.12)
    args = parser.parse_args()

    content = json.loads(Path(args.content).read_text(encoding="utf-8"))
    audio = Path(args.audio)
    if not audio.exists():
        print(f"[error] 音频不存在: {audio}", file=sys.stderr)
        return 2

    # 1) ASR 回环
    cache = Path(args.asr_cache) if args.asr_cache else \
        audio.parent / (audio.stem + ".asr-qc.json")
    segs = transcribe(audio, model_size=args.model, language="zh", cache_path=cache)
    segs = drop_hallucination(segs)
    asr_all = normalize_spoken("".join(t for _, _, t in segs))

    # 章节时间轴:优先 timeline.json,否则按字数比例估算
    chapters = content["chapters"]
    durations = [max(1, len(normalize_spoken(ch.get("tts_narration", ch["narration"]))))
                 for ch in chapters]
    if args.timeline and Path(args.timeline).exists():
        tl = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
        if tl.get("chapters"):
            spans = [(c["start"], c["end"]) for c in tl["chapters"]]
        else:
            spans = []
    else:
        spans = []
    if not spans:
        # 无 timeline:按各章字数比例估算时间轴(与渲染器的字数比例逻辑一致)
        chars = [len(normalize_spoken(ch.get("tts_narration", ch["narration"])))
                 for ch in chapters]
        total_chars = max(1, sum(chars))
        est_total = max(10.0, total_chars * 0.21 + 0.5 + 0.6 * (len(chapters) - 1) + 2.0)
        t0, spans = 0.5, []
        for d in chars:
            dur = d / total_chars * (est_total - 2.5)
            spans.append((t0, t0 + dur))
            t0 += dur + 0.6

    # 逐章比对:优先用逐章音频(parts/item_*.wav)分别转写,消除跨章边界串扰;
    # 无 parts 时回退整段音频按时间切分(有串扰风险,CER 仅作参考)。
    parts_dir = Path(args.parts_dir) if args.parts_dir else None
    chapter_reports, all_subs = [], []
    if parts_dir and parts_dir.exists():
        parts = sorted(parts_dir.glob("item_*.wav"))
        if len(parts) != len(chapters):
            print(f"[error] parts 数({len(parts)})与章节数({len(chapters)})不一致",
                  file=sys.stderr)
            return 2
        for ch, part in zip(chapters, parts):
            psegs = transcribe(part, model_size=args.model, language="zh",
                               cache_path=part.with_suffix(".asr-qc.json"))
            got = normalize_spoken("".join(t for _, _, t in drop_hallucination(psegs)))
            expected = normalize_spoken(ch.get("tts_narration", ch["narration"]))
            rep = chapter_diff(expected, got)
            rep["kind"], rep["title"] = ch["kind"], ch.get("title", "")
            for sub in rep["substitutions"] + rep["missing"]:
                at_ch = sub["at"]
                sub["time_in_chapter"] = round(
                    at_ch / max(1, len(expected)), 2)
                all_subs.append({"chapter": ch["kind"], **sub})
            chapter_reports.append(rep)
    else:
        for ch, (s0, s1) in zip(chapters, spans):
            seg_txt = normalize_spoken("".join(
                t for s, e, t in segs if e > s0 - 0.5 and s < s1 + 0.5))
            expected = normalize_spoken(ch.get("tts_narration", ch["narration"]))
            rep = chapter_diff(expected, seg_txt)
            rep["kind"], rep["title"], rep["span"] = ch["kind"], ch.get("title", ""), [round(s0, 2), round(s1, 2)]
            for sub in rep["substitutions"] + rep["missing"]:
                at_ch = sub["at"]
                sub["time"] = round(s0 + max(0.0, min(1.0, at_ch / max(1, len(expected)))) *
                                    (s1 - s0), 2)
                all_subs.append({"chapter": ch["kind"], **sub})
            chapter_reports.append(rep)

    overall_cer = round(sum(r["errors"] for r in chapter_reports) /
                        max(1, sum(r["expected_chars"] for r in chapter_reports)), 4)
    # hard CER:剔除同音字转写(发音正确,仅 ASR 选字不同),只统计异音替换+缺字/多字
    for r in chapter_reports:
        hard = (sum(len(s["expected"]) for s in r["substitutions"] if not s.get("homophone"))
                + sum(len(m["expected"]) for m in r["missing"])
                + sum(len(e["got"]) for e in r["insertions"]))
        r["hard_errors"], r["hard_cer"] = hard, round(hard / max(1, r["expected_chars"]), 4)
    overall_hard = round(sum(r["hard_errors"] for r in chapter_reports) /
                         max(1, sum(r["expected_chars"] for r in chapter_reports)), 4)
    bad_chapters = [r["kind"] for r in chapter_reports
                    if r["hard_cer"] > args.chapter_cer_max]
    status = "PASS" if overall_hard <= args.cer_max and not bad_chapters else "FAIL"

    # 2) 字幕对齐漂移(可选)
    cue_report = None
    if args.srt and Path(args.srt).exists():
        cues = parse_srt(Path(args.srt))
        drifts = []
        for cs, ce, ct in cues:
            cn = normalize_spoken(ct)
            if len(cn) < 2:
                continue
            best, bd = None, 1e9
            for s, e, t in segs:
                tn = normalize_spoken(t)
                if not tn:
                    continue
                dist = abs(cs - s)
                if dist < bd and (cn[:4] in tn or tn[:4] in cn or dist < 2.0):
                    best, bd = s, dist
            if best is not None and bd < 90:
                drifts.append(round(bd, 2))
        cue_report = {"cues": len(cues), "matched": len(drifts),
                      "max_drift_sec": max(drifts) if drifts else None}

    # 3) 画面配对清单(每抽样帧:当期字幕 + 当期节拍)
    manifest = []
    cues = parse_srt(Path(args.srt)) if args.srt and Path(args.srt).exists() else []
    for ci, ch in enumerate(chapters):
        s0, s1 = spans[ci]
        for prog in (0, .15, .30, .45, .60, .75, .90, 1.0):
            t = s0 + (s1 - s0) * prog
            cue = next((ct for cs, ce, ct in cues if cs <= t < ce), "")
            beat = next(({"i": i, "type": b.get("type", "ai"),
                          "fit": b.get("fit", "cover"),
                          "prompt": b.get("prompt", "")[:80]}
                         for i, b in enumerate(ch.get("broll") or [])
                         if b.get("at", 0) <= min(prog, 0.999) < b.get("at", 0) + b.get("hold", 1)),
                        None)
            manifest.append({"chapter": ch["kind"], "t": round(t, 2), "progress": prog,
                             "subtitle": cue, "beat": beat})

    report = {"status": status, "overall_cer": overall_cer, "overall_hard_cer": overall_hard,
              "thresholds": {"hard_cer_max": args.cer_max, "chapter_hard_cer_max": args.chapter_cer_max},
              "asr_segments": len(segs), "chapters": chapter_reports,
              "suspect_count": len(all_subs), "suspects": all_subs,
              "cue_alignment": cue_report, "frame_manifest": manifest,
              "note": "suspects=可疑错读/缺读,均含时间戳,供人工或VLM复核;CER 为 TTS 行业标准可懂度指标"}
    out = Path(args.out) if args.out else audio.parent / "qc_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "overall_hard_cer": overall_hard,
                      "suspect_count": len(all_subs), "bad_chapters": bad_chapters,
                      "report": str(out)}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
