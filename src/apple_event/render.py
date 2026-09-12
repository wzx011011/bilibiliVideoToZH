# -*- coding: utf-8 -*-
"""苹果发布会速览渲染:复用 gpt_explainer 管线,换 Apple 发布会夜皮肤。

皮肤:近黑底 + 银灰 + Apple 蓝;底部来源标注改为 Apple Newsroom 官方。
时间轴/字幕/音频拼装/ffprobe 校验全部沿用已验证实现。

用法:
  python src/apple_event/render.py --preview            # 出代表帧+拼图(无需配音)
  python src/apple_event/render.py --render             # 配音就绪后出全片
  python src/apple_event/render.py --render --content X.json --out D:/some/dir
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[0]
sys.path.insert(0, str(SRC))

import gpt_explainer.render as base  # noqa: E402

# Apple 发布会夜皮肤(渲染函数运行时读取模块常量,覆盖即可)
base.BG = (2, 2, 3)
base.PANEL = (24, 24, 27)
base.PANEL_2 = (36, 36, 41)
base.TEAL = (152, 152, 162)      # 银灰
base.CORAL = (10, 132, 255)      # Apple 蓝
base.GOLD = (243, 182, 92)       # 价格强调
base.SOURCE_LABEL = "Apple Newsroom 官方通稿"
base.DISCLAIMER = "规格与价格以 Apple 官方为准"

DEFAULT_CONTENT = HERE / "content-apple-2026-09.json"
DEFAULT_OUT = Path("D:/apple-event-202609")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, default=DEFAULT_CONTENT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    try:
        result = base.run(content_path=args.content, out=args.out,
                          smoke=args.preview or not args.render,
                          render=args.render)
        if args.render:
            raw_video = args.out / "gpt-astra-explainer.mp4"
            if raw_video.exists():
                final_video = args.out / "苹果2026秋季发布会-速览.mp4"
                raw_video.replace(final_video)
                result["video"] = str(final_video)
                if "report" in result:
                    result["report"]["output"] = str(final_video)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
