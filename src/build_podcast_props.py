# -*- coding: utf-8 -*-
"""构建播客版(Remotion)props:精修音频 + 顺序时间轴 + 分块渲染边界。

参数化版(平台 podcast_props 阶段调用),不再硬编码 Hinton 路径:
  输入:runs.json + items.json(译文) + parts(polished,音频已在
        podcast-studio/public/audio-<slug>/ 下,Remotion staticFile 只能读 public)
  输出:props-<slug>.json(章节含 avatarFile/audioFile 相对 public 路径)

排布:换人停顿 0.7s,同人连续 0.45s;章 start/end 由实际音频时长累加。

用法:
  python build_podcast_props.py \
      --runs work/studio/<slug>/work/narration/runs.json \
      --items work/studio/<slug>/work/narration/items.json \
      --audio-dir work/podcast-studio/public/audio-<slug> --audio-rel audio-<slug> \
      --avatar-rel avatars/<slug> \
      --name-a "主持人" --name-b "嘉宾" --title "标题" \
      -o work/podcast-studio/props-<slug>.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"
FPS = 30


def probe(p: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], check=True,
        capture_output=True, text=True).stdout.strip()
    return float(out)


def build_chapters(runs: list[dict], texts: dict[int, str],
                   audio_dir: Path, audio_rel: str, avatar_rel: str,
                   names: dict[str, str]):
    """顺序排布章节;返回 (chapters, total_seconds)。"""
    chapters, cursor, prev_spk = [], 0.0, None
    for r in runs:
        rid = int(r["id"])
        part = audio_dir / f"{rid:04d}.wav"
        if not part.exists():  # 兼容 item_ 前缀命名
            part = audio_dir / f"item_{rid:04d}.wav"
        dur = probe(part)
        gap = 0.45 if r["speaker"] == prev_spk else 0.7
        cursor += 0.0 if prev_spk is None else gap
        spk = r["speaker"]
        chapters.append({
            "id": rid, "speaker": spk,
            "speakerName": names.get(spk, f"说话人{spk}"),
            "avatarFile": f"{avatar_rel}/speaker-{spk}.jpg",
            "start": round(cursor, 3), "end": round(cursor + dur, 3),
            "text": texts.get(rid, r.get("text", "")),
            "audioFile": f"{audio_rel}/{rid:04d}.wav",
        })
        cursor += dur
        prev_spk = spk
    return chapters, cursor


def chunk_bounds(chapters: list[dict], total: float,
                 max_chapters: int = 12, max_minutes: float = 25.0):
    """分块渲染边界(帧):每块 ≤max_chapters 章且跨度 ≤max_minutes,边界取章起点帧。"""
    edges, i, n = [0], 0, len(chapters)
    while i < n:
        j = i + 1
        while j < n and j - i < max_chapters and \
                chapters[j]["start"] - chapters[i]["start"] < max_minutes * 60:
            j += 1
        if j < n:
            edges.append(round(chapters[j]["start"] * FPS))
        i = j
    edges.append(int(total * FPS) + 90)  # 与 calculateMetadata 的 +90 帧对齐
    return edges


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", required=True, type=Path)
    ap.add_argument("--items", required=True, type=Path)
    ap.add_argument("--audio-dir", required=True, type=Path,
                    help="polished 音频所在目录(需在 podcast-studio/public 下)")
    ap.add_argument("--audio-rel", required=True,
                    help="相对 public 的目录名,如 audio-<slug>")
    ap.add_argument("--avatar-rel", default="avatars",
                    help="相对 public 的头像目录,如 avatars/<slug>")
    ap.add_argument("--name-a", default="主持人")
    ap.add_argument("--name-b", default="嘉宾")
    ap.add_argument("--title", default="")
    ap.add_argument("-o", "--out", required=True, type=Path)
    args = ap.parse_args()

    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    texts = {int(it["id"]): it["text"] for it in
             json.loads(args.items.read_text(encoding="utf-8"))}
    names = {"A": args.name_a, "B": args.name_b}

    chapters, total = build_chapters(
        runs, texts, args.audio_dir, args.audio_rel, args.avatar_rel, names)
    if not chapters:
        raise SystemExit("无章节:runs 为空或译文缺失")

    props = {"title": args.title or "中文播客", "chapters": chapters}
    args.out.write_text(json.dumps(props, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    edges = chunk_bounds(chapters, total)
    print(f"chapters={len(chapters)} total={total / 60:.1f}min -> {args.out}")
    print(f"chunks: {len(edges) - 1} 块, frames "
          f"{[f'{edges[i]}-{edges[i + 1] - 1}' for i in range(len(edges) - 1)][:8]}"
          f"{'...' if len(edges) > 9 else ''}")


if __name__ == "__main__":
    main()
