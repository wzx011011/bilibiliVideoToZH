"""译文审查:逐槽对照英文源,检测翻译串位/越界(豆包批量切块错位类 bug)。

qwen3 对每个槽判定 MATCH/PARTIAL/MISMATCH;结果落盘 audit json。
MISMATCH 数 >= fail-over 时以非零码退出(平台阶段置失败,提示人工复核)。

用法(.venv-ocr):
  python src/audit_translation.py --slots work/<slug>/work/slots.json \
      --zh work/<slug>/work/slots_zh.json --out work/<slug>/work/audit_translation.json \
      [--model qwen3:14b] [--fail-over 5]
"""
import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:11434/api/chat"

SYSTEM = (
    "你是翻译质检员。给你同一句英文原文和中文配音译文,判断中文是否忠实翻译了这段英文。"
    "注意:译文只应覆盖这段英文的内容。如果译文里出现了英文中完全没有的话题(内容串位),"
    "或者译文明显是另一段话的翻译,判 MISMATCH。译文略有意译、压缩、漏掉填充词都算 MATCH。"
    "译文覆盖了本段英文但也混入了相邻段落的内容判 PARTIAL,并在 reason 里指出混入的部分。"
    '严格输出 JSON: {"verdict":"MATCH|PARTIAL|MISMATCH","reason":"一句话"}'
)


def ask(model: str, en: str, zh: str) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"英文原文:\n{en}\n\n中文译文:\n{zh}\n\n/no_think"},
        ],
        "format": "json", "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2500},
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        raw = json.loads(r.read())["message"]["content"]
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return {"verdict": "ERROR", "reason": (raw or "empty")[:120]}
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slots", required=True, type=Path)
    ap.add_argument("--zh", required=True, type=Path, help="槽译文 JSON({id: text})")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model", default="qwen3:14b")
    ap.add_argument("--fail-over", type=int, default=5,
                    help="MISMATCH 数达到该值则退出码 2(默认 5)")
    args = ap.parse_args()

    slots = json.loads(args.slots.read_text(encoding="utf-8"))
    zh_map = json.loads(args.zh.read_text(encoding="utf-8"))
    result = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}

    for i, s in enumerate(slots):
        key = str(i)
        if key in result:
            continue
        zh = zh_map.get(key) or zh_map.get(str(s.get("id", i))) or ""
        if not zh:
            result[key] = {"verdict": "SKIP", "reason": "无译文"}
            continue
        try:
            v = ask(args.model, s["text"], zh)
        except Exception as e:
            v = {"verdict": "ERROR", "reason": str(e)[:120]}
        result[key] = {"verdict": v.get("verdict"), "reason": str(v.get("reason", ""))[:200],
                       "speaker": s.get("speaker", "")}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{time.strftime('%H:%M:%S')}] {i:3d} {v.get('verdict'):8s} "
              f"{str(v.get('reason',''))[:60]}", flush=True)

    from collections import Counter
    c = Counter(v["verdict"] for v in result.values())
    mismatch = c.get("MISMATCH", 0)
    print(f"[✓] 审查 {len(result)} 槽: {dict(c)}")
    if mismatch >= args.fail_over:
        print(f"    ✗ MISMATCH {mismatch} >= 阈值 {args.fail_over}:疑似批量串位,需人工复核"
              f" -> {args.out}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
