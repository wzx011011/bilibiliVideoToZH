# -*- coding: utf-8 -*-
"""人物音色选型档案:同一人物的音色定案持久化,后续视频直接复用。

存储 work/studio/voice-castings.json:
  {"Sam Altman": {"voice": "doubao-磁性俊宇（升级版）", "display_name": "Sam Altman",
                  "role": "guest", "picked_at": "2026-08-26",
                  "source": "人工试听(声纹top2)", "f0_p25": 136}}

接入:pipeline_admin._build_voice_inputs 在 voice_{A,B} 缺省时按
name_{A,B}(人物名)自动查表回填;pick_voice 选型确认后调用 set() 落档。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASTINGS = ROOT / "work" / "studio" / "voice-castings.json"


def _load() -> dict:
    try:
        return json.loads(CASTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get(person: str) -> dict | None:
    """人物名(支持中英文常用写法)→ 选型记录。"""
    if not person:
        return None
    table = _load()
    person = person.strip()
    for key in (person, person.lower()):
        if key in table:
            return table[key]
    # 宽松匹配:忽略大小写与常见别名前后缀
    low = person.lower()
    for key, rec in table.items():
        if key.lower() in low or low in key.lower():
            return rec
    return None


def set(person: str, voice: str, display_name: str = "", role: str = "guest",
        source: str = "", f0_p25: float | None = None,
        notes: str = "") -> dict:
    table = _load()
    rec = {"voice": voice, "display_name": display_name or person,
           "role": role, "picked_at": time.strftime("%Y-%m-%d"),
           "source": source}
    if f0_p25:
        rec["f0_p25"] = f0_p25
    if notes:
        rec["notes"] = notes
    table[person.strip()] = rec
    CASTINGS.parent.mkdir(parents=True, exist_ok=True)
    CASTINGS.write_text(json.dumps(table, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return rec


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list")
    p_set = sub.add_parser("set")
    p_set.add_argument("person")
    p_set.add_argument("voice")
    p_set.add_argument("--display-name", default="")
    p_set.add_argument("--role", default="guest", choices=["guest", "host"])
    p_set.add_argument("--source", default="")
    p_set.add_argument("--f0", type=float)
    p_set.add_argument("--notes", default="")
    args = ap.parse_args()
    if args.cmd == "list":
        for k, v in _load().items():
            print(f"{k:20s} -> {v['voice']}({v.get('role','')},"
                  f"{v.get('picked_at','')})")
    else:
        set(args.person, args.voice, args.display_name, args.role,
           args.source, args.f0, args.notes)
        print(f"[✓] {args.person} -> {args.voice}")
