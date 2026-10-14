# -*- coding: utf-8 -*-
"""节拍-句子对齐工具:把 content JSON 的 broll 拍窗口对齐到字幕逐句 cue。

规则(2026-10-13 定,修"章尾露底闪矢量"):
- 多拍章:按时长把本章 cue 连续分组,切换落句界;**首拍 at=0(顶章头),
  末拍 hold 到章节结束(顶章尾)**——杜绝章首/章尾闪出矢量场景。
- 单拍章(彩蛋):盖中段句(第 2 句起至末句),头尾留给矢量场景(设计如此)。
- 拍间 0.015 微叠做交叉。

用法:
  python src/mzx_story/align_beats.py --content src/mzx_story/sy-01-liangzhu.json \
      --timeline C:/render-tmp/sy-01/timeline.json --srt C:/render-tmp/sy-01/subtitles.srt
"""
from __future__ import annotations

import argparse
import json
import re


def parse_srt(path: str):
    blocks = open(path, encoding='utf-8').read().strip().split('\n\n')
    cues = []
    for b in blocks:
        lines = b.split('\n')
        for ln in lines[1:]:
            m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)', ln)
            if m:
                g = list(map(int, m.groups()))
                cues.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                             g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000))
    return cues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--content', required=True)
    ap.add_argument('--timeline', required=True)
    ap.add_argument('--srt', required=True)
    a = ap.parse_args()

    content = json.load(open(a.content, encoding='utf-8'))
    tl = json.load(open(a.timeline, encoding='utf-8'))
    cues = parse_srt(a.srt)

    for i, ch in enumerate(content['chapters']):
        k = len(ch.get('broll') or [])
        if not k:
            continue
        ent = tl['chapters'][i]
        t0, dur = ent['start'], ent['duration']
        cc = [x for x in cues if t0 - 0.35 <= x[0] < t0 + dur - 0.2]
        if not cc:
            continue
        if k == 1:
            s = cc[1][0] if len(cc) > 2 else cc[0][0]
            e = cc[-1][1]
            ch['broll'][0]['at'] = round(max(0.0, (s - t0) / dur), 3)
            ch['broll'][0]['hold'] = round((e - s) / dur + 0.015, 3)
            continue
        total = cc[-1][1] - cc[0][0]
        bounds = [cc[0][0]]
        cum = 0.0
        for x in cc[:-1]:
            cum += x[1] - x[0]
            if cum >= total * len(bounds) / k:
                bounds.append(x[1])
        bounds.append(cc[-1][1])
        if len(bounds) != k + 1:
            step = dur / k
            bounds = [t0 + j * step for j in range(k + 1)]
        bounds[0] = t0                      # 首拍顶章头
        bounds[-1] = t0 + dur               # 末拍顶章尾
        for bi, beat in enumerate(ch['broll']):
            beat['at'] = round(max(0.0, (bounds[bi] - t0) / dur), 3)
            beat['hold'] = round((bounds[bi + 1] - bounds[bi]) / dur + 0.015, 3)

    json.dump(content, open(a.content, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('对齐完成(首尾顶格):', a.content)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
