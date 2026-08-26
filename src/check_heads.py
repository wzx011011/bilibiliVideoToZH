# -*- coding: utf-8 -*-
"""批量检测各片开头是否需要丢弃(teaser/片头曲/广告口播)。

判定依据:
  1. 首个槽的文本形态:非正片特征 = 开场前插话(如引子/重复句/无上下文碎片)
  2. 首个槽的说话人:主持人未做开场介绍、嘉宾先说话 = 异常
  3. 片头静音/音乐段与首槽的时间间隔

对每部片输出建议 _skip_head 值(只丢 teaser,不伤正片)。

用法(.venv-ocr):
  python check_heads.py --tasks-dir work/studio/tasks --out heads-report.json
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

# 正片开场词特征:介绍节目/嘉宾/自我介绍
HOST_OPEN = re.compile(
    r"(interview|welcome|today|episode|podcast|my guest|joining me|"
    r"our guest|this is|I'm .{1,30}(and|host))", re.I)
# 明显的非正片碎片:无意义感叹/重复/超短
FRAGILE = re.compile(r"^(wow|yeah|um+|uh+|so[, ]|okay)\b.{0,40}$", re.I)


def first_slot_anomaly(slot: dict) -> tuple[bool, str]:
    t = slot.get("text", "")
    if len(t) < 25:
        return True, f"首槽过短({len(t)}字): {t[:40]!r}"
    if FRAGILE.match(t):
        return True, f"首槽是碎片: {t[:40]!r}"
    # 嘉宾(B)在节目正式介绍前说话 = teaser 特征
    if slot.get("speaker") == "B" and not HOST_OPEN.search(t):
        return True, f"嘉宾先说话且非开场介绍: {t[:40]!r}"
    return False, "正常"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--studio", default="work/studio")
    ap.add_argument("--out", default="work/probe-anchors/heads-report.json")
    args = ap.parse_args()

    report = {}
    for f in sorted(glob.glob(args.studio + "/tasks/2026*.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        slug = d.get("params", {}).get("slug", "")
        if not slug:
            continue
        slots_p = Path(args.studio) / slug / "work" / "slots.json"
        if not slots_p.exists():
            report[slug] = {"status": "no-slots"}
            continue
        slots = json.loads(slots_p.read_text(encoding="utf-8"))
        first = slots[0]
        bad, why = first_slot_anomaly(first)
        # 已丢弃过片头的(局部重跑后)不再建议
        already = first.get("start", 0) > 15
        rec = 0.0 if (not bad or already) else float(first.get("end", 10.0))
        report[slug] = {
            "status": "ok",
            "first_start": round(first.get("start", 0), 1),
            "first_speaker": first.get("speaker"),
            "anomaly": bad, "reason": why,
            "suggest_skip_head": rec,
            "preview": first.get("text", "")[:60],
        }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    for slug, r in report.items():
        if r.get("status") != "ok":
            print(f"{slug:24s} {r['status']}")
            continue
        flag = "⚠丢弃" if r["anomaly"] else "✓保留"
        print(f"{slug:24s} {flag} skip={r['suggest_skip_head']:.0f}s "
              f"[{r['first_speaker']}] {r['reason'][:60]}")


if __name__ == "__main__":
    main()
