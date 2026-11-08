"""用 Ollama qwen2.5:7b 把访谈轮次英译中(适合配音朗读的口语体),支持断点续跑。"""

import json
import time
import urllib.request
from pathlib import Path

PILOT = Path(__file__).resolve().parent / "interview-pilot"
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:7b"

SYSTEM = (
    "你是专业的英中访谈翻译,为中文配音撰写文稿。把用户的英文翻译成口语化、"
    "自然、适合朗读的中文。要求:忠实原意;句子完整流畅,标点规范;"
    "数字保留阿拉伯数字;人名采用通用中文译名(如 Geoffrey Hinton=杰弗里·辛顿);"
    "不要添加任何解释、注释或原文。只输出译文。"
)


def translate(text: str) -> str:
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 1024, "seed": 7},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["message"]["content"].strip()


def main() -> None:
    turns = json.loads((PILOT / "turns.json").read_text(encoding="utf-8"))
    out_path = PILOT / "turns_zh.json"
    zh = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}

    todo = [i for i, t in enumerate(turns) if str(i) not in zh and t["text"].strip()]
    print(f"turns={len(turns)} todo={len(todo)}", flush=True)
    t0 = time.time()
    for n, i in enumerate(todo, 1):
        t = turns[i]
        try:
            z = translate(t["text"])
        except Exception as e:
            print(f"turn {i} FAILED: {e}", flush=True)
            continue
        # 译文长度健全性:中文字符数应在英文词数的 1.2~3.2 倍
        en_words = len(t["text"].split())
        zh_chars = len(z)
        flag = "" if 1.2 <= zh_chars / max(en_words, 1) <= 3.2 else " ⚠ratio"
        zh[str(i)] = z
        out_path.write_text(json.dumps(zh, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(todo)} turn{i:02d} "
              f"({t['speaker']}, {en_words}w->{zh_chars}c{flag}) {z[:36]}",
              flush=True)
    print(f"done in {(time.time()-t0)/60:.1f} min -> {out_path}")


if __name__ == "__main__":
    main()
