"""连续槽批量英译中:保留上下文，强制 JSON 一一对应，并自动修复异常项。

已参数化(默认模型升级为 qwen3:14b,需 ollama pull):
  python translate_fine_batches.py --slots fine/slots.json       --out fine/slots_zh_v3.json --model qwen3:14b
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FINE = ROOT / "interview-pilot" / "fine"
URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:14b"
BATCH = 6

SYSTEM = (
    "你是专业访谈配音翻译。输入是一组按顺序排列的英文时间槽(自动字幕转写,"
    "常含填充词和半截碎句)。规则(重要):"
    "1) 逐槽一一对应:每个槽的译文只能包含本槽英文的信息,严禁把一句的意思"
    "挪进别的槽、严禁跨槽合并、严禁补写原文没有的内容——下游按槽位配音,挪动"
    "即串位。2) 结合整组上下文理解指代,把 it/this/they 按语境译成人名或具体"
    "名词。3) 去掉 um/uh/you know/I mean/like 等填充词和机械重复;半截碎句"
    "允许译得不完整,不要替说话人把话说完。"
    "每项中文必须接近给定目标字数,宁可凝练。"
    "专有名词可保留 AI、GPT、AlphaFold、Google、DeepMind、LLM,其余英文须译成中文。"
    "严格输出 JSON 对象,格式为 {\"items\":[{\"id\":数字,\"zh\":\"译文\"}]}。"
)

ALLOWED = {"ai", "gpt", "alphafold", "google", "deepmind", "llm", "rna", "dna", "gemini", "chatgpt", "transformer"}


def validate_batch(got, want_ids) -> str:
    """响应必须精确覆盖本批 ID:缺、多、非字符串/空译文都判不合格。

    宽松校验(只查 `id in got`)会把残缺/错位的批次写进正式译文,
    下游逐槽配音时整段串位(elon/yann 等任务 MISMATCH 数百的根源之一)。
    """
    if not isinstance(got, dict):
        return f"响应不是对象: {type(got).__name__}"
    keys = set(got)
    want = set(want_ids)
    if keys != want:
        missing = sorted(want - keys)[:5]
        extra = sorted(keys - want)[:5]
        return f"ID 不匹配(缺 {missing} 多 {extra})"
    bad = [k for k, v in got.items()
           if not isinstance(v, str) or not v.strip()]
    if bad:
        return f"空译文 id={sorted(bad)[:5]}"
    return ""


def request(items, repair=False, context=""):
    prompt = json.dumps({"slots": items}, ensure_ascii=False)
    if context:
        prompt = "【全片语境】" + context + "\n\n" + prompt
    if repair:
        prompt += "\n上次结果不合格，请严格压缩到目标字数并清除不允许的英文。"
    # /no_think 必须带:qwen3 思考 token 会吃掉 num_predict 预算,
    # 批次尾部槽位被截断(缺尾部 ID 的响应实测就是这么来的)
    prompt += "\n/no_think"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "format": "json", "stream": False,
        # num_ctx 必须 >= 提示词+num_predict:默认 8192 时输出仍被窗口边缘
        # 截断(批次尾部槽位缺失实测),16k 才装得下 6000 输出预算
        "options": {"temperature": 0.05, "num_predict": 6000,
                    "num_ctx": 16384, "seed": 19},
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        raw = json.loads(r.read())["message"]["content"]
    data = json.loads(raw)
    return {int(x["id"]): x["zh"].strip() for x in data["items"]}


def build_context(slots) -> str:
    """全片语境卡:输入长输出短(14B 可靠),注入每批让局部翻译具备全局视野。"""
    full = " ".join(s["text"] for s in slots)[:24000]
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": (
                "你是翻译策划。读英文访谈转写,输出一份给译者看的中文语境卡,"
                "200字以内:1)对话主题与脉络;2)关键人名及统一中文译名"
                "(如 Sam Altman=山姆·奥尔特曼);"
                "3)术语表(中文译法统一);4)语言风格建议。"
                '严格输出 JSON: {"context":"..."}')},
            {"role": "user", "content": full + "\n/no_think"},
        ],
        "format": "json", "stream": False,
        "options": {"temperature": 0.1, "num_predict": 800},
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            raw = json.loads(r.read())["message"]["content"]
        return json.loads(re.search(r"\{.*\}", raw, re.S).group(0))["context"]
    except Exception as e:  # 语境卡失败不阻塞翻译
        print(f"[context] 生成失败({e}),退化为无全局语境", flush=True)
        return ""


def bad_reason(z, target):
    if not z or any(x in z for x in ("```", '"items"', ":\"", "英文原文")):
        return "format"
    if len(z) > target * 1.35:
        return "long"
    words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", z)]
    if any(w not in ALLOWED for w in words):
        return "english"
    return ""


def main():
    global URL, MODEL, BATCH
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # Windows GBK 控制台兜底(✗/中文进度打印不该毁掉整批翻译)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slots", default=str(FINE / "slots.json"))
    ap.add_argument("--out", default=str(FINE / "slots_zh_v2.json"))
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--url", default=URL)
    args = ap.parse_args()
    URL, MODEL, BATCH = args.url, args.model, args.batch
    slots_path = Path(args.slots) if Path(args.slots).is_absolute() else ROOT / args.slots
    out_path = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out

    slots = json.loads(slots_path.read_text(encoding="utf-8"))
    out = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    ctx = build_context(slots)
    if ctx:
        print(f"[context] {ctx[:120]}", flush=True)
    batches = [slots[i:i+BATCH] for i in range(0, len(slots), BATCH)]
    t0 = time.time()
    for bi, batch in enumerate(batches, 1):
        missing = [s for s in batch if str(s["id"]) not in out]
        if not missing:
            continue
        items = [{"id": s["id"], "speaker": s["speaker"], "duration": s["duration"],
                  "target_chars": max(8, round(s["duration"] * 5.1)), "english": s["text"]}
                 for s in batch]
        want_ids = [s["id"] for s in batch]
        got = None
        last_err = ""
        for attempt in range(4):
            try:
                cand = request(items, repair=attempt > 0, context=ctx)
                err = validate_batch(cand, want_ids)
                if not err:
                    got = cand
                    break
                last_err = err
                print(f"batch {bi} try{attempt+1} 拒收: {err}", flush=True)
            except Exception as e:
                last_err = str(e)
                print(f"batch {bi} try{attempt+1} {e}", flush=True)
            time.sleep(3)
        if got is None:
            # 整批反复失败(常见:固定 seed 下模型稳定漏掉末尾残句槽),
            # 拆成单槽请求兜底;单槽也无法完成的才整体失败
            got = {}
            for s1 in batch:
                item = {"id": s1["id"], "speaker": s1["speaker"],
                        "duration": s1["duration"],
                        "target_chars": max(8, round(s1["duration"] * 5.1)),
                        "english": s1["text"]}
                for att in range(3):
                    try:
                        one = request([item], repair=True, context=ctx)
                        if not validate_batch(one, [s1["id"]]):
                            got.update(one)
                            break
                    except Exception as e:
                        print(f"batch {bi} slot {s1['id']} try{att+1} {e}", flush=True)
                    time.sleep(2)
            if validate_batch(got, want_ids):
                raise SystemExit(f"batch {bi} (ids {batch[0]['id']}-"
                                 f"{batch[-1]['id']}) 整批与单槽均未完整返回;"
                                 f"已完成批次保留,重跑可续译")
            print(f"batch {bi} 单槽兜底完成(ids {batch[0]['id']}-{batch[-1]['id']})",
                  flush=True)
        for s in batch:
            out[str(s["id"])] = got[s["id"]]
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        bad = sum(bool(bad_reason(out.get(str(s["id"]), ""), round(s["duration"]*5.1))) for s in batch)
        print(f"[{time.strftime('%H:%M:%S')}] batch {bi}/{len(batches)} ids {batch[0]['id']}-{batch[-1]['id']} bad={bad}", flush=True)

    # 单项二次修复
    bads = []
    for s in slots:
        target = max(8, round(s["duration"] * 5.1))
        z = out.get(str(s["id"]), "")
        reason = bad_reason(z, target)
        if reason:
            bads.append((s, reason, z))
    print(f"initial bad={len(bads)}", flush=True)
    for n, (s, reason, old) in enumerate(bads, 1):
        item = {"id": s["id"], "speaker": s["speaker"], "duration": s["duration"],
                "target_chars": max(8, round(s["duration"]*5.1)), "english": s["text"],
                "bad_previous": old, "problem": reason}
        try:
            got1 = request([item], repair=True, context=ctx)
            if validate_batch(got1, [s["id"]]):
                print(f"repair {s['id']} 拒收(保留原值)", flush=True)
            else:
                out[str(s["id"])] = got1[s["id"]]
                out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print(f"repair {s['id']} fail {e}", flush=True)
        print(f"repair {n}/{len(bads)} s{s['id']:03d} {reason}", flush=True)
    print(f"done {len(out)}/{len(slots)} in {(time.time()-t0)/60:.1f}min -> {out_path}")


if __name__ == "__main__":
    main()
