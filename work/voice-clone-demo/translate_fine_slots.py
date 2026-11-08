"""按英文字幕时间槽翻译，要求中文朗读长度贴近槽位。支持断点续跑。"""

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FINE = ROOT / "interview-pilot" / "fine"
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:7b"

SYSTEM = (
    "你是专业的英文访谈中文配音翻译。把英文翻译成自然、口语化、适合朗读的中文。"
    "必须忠实保留事实和逻辑，不要解释，不要添加原文没有的信息。"
    "只输出译文，不要引号、序号或说明。人名用常见中文译名。"
)


def call(text: str, duration: float, before: str, after: str) -> str:
    # CosyVoice 中文约 5~6 字/秒，给模型一个接近槽位的字数目标
    target = max(8, round(duration * 5.3))
    user = (
        f"上文（仅供理解，不要翻译输出）：{before}\n"
        f"当前槽英文（只翻译这一段）：{text}\n"
        f"下文（仅供理解，不要翻译输出）：{after}\n"
        f"当前槽时长为 {duration:.1f} 秒。译文控制在约 {target} 个汉字，"
        "可以承接上文，但只输出当前槽对应的中文；宁可凝练，不要超长。"
    )
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "stream": False,
        "options": {"temperature": 0.15, "num_predict": 256, "seed": 11},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["message"]["content"].strip()


def main() -> None:
    slots = json.loads((FINE / "slots.json").read_text(encoding="utf-8"))
    out_path = FINE / "slots_zh.json"
    out = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    todo = [s for s in slots if str(s["id"]) not in out]
    print(f"slots={len(slots)} todo={len(todo)}", flush=True)
    t0 = time.time()
    for n, s in enumerate(todo, 1):
        try:
            i = s["id"]
            before = slots[i - 1]["text"] if i > 0 else ""
            after = slots[i + 1]["text"] if i + 1 < len(slots) else ""
            z = call(s["text"], s["duration"], before, after)
        except Exception as e:
            print(f"slot {s['id']:03d} FAIL {e}", flush=True)
            continue
        out[str(s["id"])] = z
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        target = round(s["duration"] * 5.3)
        flag = "" if len(z) <= target * 1.3 else " ⚠long"
        print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(todo)} s{s['id']:03d} "
              f"{s['speaker']} {s['duration']:.1f}s {len(z)}/{target}c{flag} {z[:28]}",
              flush=True)
    print(f"done {(time.time()-t0)/60:.1f}min -> {out_path}")


if __name__ == "__main__":
    main()
