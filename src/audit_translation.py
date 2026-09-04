"""译文审查:逐槽对照英文源,检测翻译串位/越界(豆包批量切块错位类 bug)。

qwen3 对每个槽判定 MATCH/PARTIAL/MISMATCH;结果落盘 audit json。
MISMATCH 数 >= fail-over 时退出码 2(平台阶段置失败,提示人工复核)。

v2 修复(6 小时超时/样本报告冒充全量问题):
  - 每槽完成即增量落盘(as_completed),单个慢请求不再堵塞检查点;
  - 报告带 _summary{complete,mode,counts,指纹}:全量审查必须覆盖全部槽位,
    抽样通过标记 mode=sample;超时/中断留下的部分报告 complete=False,
    平台据此要求续跑,不会把样本报告当全量结论;
  - ask() 自带重试;Ollama 连续不可用立即失败,不再产出整篇 ERROR。

用法(.venv-ocr):
  python src/audit_translation.py --slots work/<slug>/work/slots.json \
      --zh work/<slug>/work/slots_zh.json --out work/<slug>/work/audit_translation.json \
      [--model qwen3:14b] [--fail-over 5]
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

URL = "http://127.0.0.1:11434/api/chat"
SUMMARY_KEY = "_summary"
REQ_TIMEOUT = 180   # 单槽审查是短输出;600s 的老超时让一个挂起请求拖死全批
ASK_RETRIES = 2
VERDICTS = {"MATCH", "PARTIAL", "MISMATCH", "ERROR", "SKIP"}

SYSTEM = (
    "你是翻译质检员。给你同一段英文原文(口语/自动字幕碎片,可能只是半句话)"
    "和对应中文译文,判断译文的核心信息是否忠实于这段英文。"
    "以下都算 MATCH:意译、压缩、省略 um/uh 等填充词、补全主语、加少量衔接词、"
    "把破碎口语整理成通顺中文、译文比原文完整但信息点都来自这段英文。"
    "判 MISMATCH 仅限:译文核心话题与这段英文明显无关(内容像是访谈中另一处的,"
    "即真正的串位),或译文意思与原文相反。"
    "译文覆盖了本段英文但明显混入大段相邻槽的内容判 PARTIAL,并在 reason 里指出。"
    '严格输出 JSON: {"verdict":"MATCH|PARTIAL|MISMATCH","reason":"一句话"}'
)


def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


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
    last = None
    for i in range(ASK_RETRIES + 1):
        try:
            req = urllib.request.Request(URL, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as r:
                raw = json.loads(r.read())["message"]["content"]
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
            m = re.search(r"\{.*\}", raw, flags=re.S)
            if not m:
                return {"verdict": "ERROR", "reason": (raw or "empty")[:120]}
            v = json.loads(m.group(0))
            if v.get("verdict") not in VERDICTS:
                v["verdict"] = "ERROR"
                v["reason"] = f"非法 verdict: {str(v.get('verdict'))[:80]}"
            return v
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"Ollama 连续 {ASK_RETRIES + 1} 次失败: {str(last)[:120]}")


def compute_summary(result: dict, expected: list[str],
                    covered: list[str], mode: str) -> dict:
    """纯函数:从报告算 complete/counts(排除 _summary 自身),供平台判定。"""
    verdicts = [v.get("verdict") for k, v in result.items()
                if k != SUMMARY_KEY and isinstance(v, dict)]
    counts = dict(Counter(verdicts))
    complete = all(k in result for k in covered)
    return {"mode": mode, "complete": complete,
            "covered": sum(1 for k in covered if k in result),
            "needed": len(covered), "total_slots": len(expected),
            "counts": counts, "mismatch": counts.get("MISMATCH", 0)}


def save_report(out: Path, result: dict, summary: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in result.items() if k != SUMMARY_KEY}
    data[SUMMARY_KEY] = summary
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, out)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slots", required=True, type=Path)
    ap.add_argument("--zh", required=True, type=Path, help="槽译文 JSON({id: text})")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model", default="qwen3:14b")
    ap.add_argument("--fail-over", type=int, default=5,
                    help="MISMATCH 数达到该值则退出码 2(默认 5)")
    ap.add_argument("--jobs", type=int, default=3,
                    help="并发审查请求数(默认 3)")
    ap.add_argument("--sample", type=int, default=0,
                    help="抽样审查:每隔 N 槽审 1 个;发现 MISMATCH 自动全量(默认 0=全量)")
    args = ap.parse_args()

    slots = json.loads(args.slots.read_text(encoding="utf-8"))
    zh_map = json.loads(args.zh.read_text(encoding="utf-8"))
    expected = [str(i) for i in range(len(slots))]

    # 断点续跑:已有报告必须键位合法(槽序号),否则视为异物丢弃
    result: dict = {}
    if args.out.exists():
        prev = json.loads(args.out.read_text(encoding="utf-8"))
        if isinstance(prev, dict) and all(
                k in expected or k == SUMMARY_KEY for k in prev):
            result = {k: v for k, v in prev.items() if k != SUMMARY_KEY}

    sampled = expected[::args.sample] if args.sample > 1 else expected

    def audit_keys(keys: list[str], ckpt_covered: list[str]) -> None:
        """并发审查一组缺失槽;每完成 5 槽落一次盘,一个慢请求不堵其他结果。

        ckpt_covered = 当前这轮的目标覆盖(抽样轮=抽样集,全量轮=全部槽):
        检查点的 complete 必须按本轮目标算,否则全量升级中途的检查点会
        冒充"已完成"(只有抽样覆盖却标 complete)。
        """
        todo = []
        for key in keys:
            if key in result:
                continue
            i = int(key)
            zh = zh_map.get(key) or zh_map.get(str(slots[i].get("id", i))) or ""
            if not zh:
                result[key] = {"verdict": "SKIP", "reason": "无译文"}
                continue
            todo.append((i, key, zh))
        if not todo:
            return
        done_since_save = 0
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futs = {ex.submit(ask, args.model, slots[i]["text"], zh): (i, key)
                    for i, key, zh in todo}
            for f in as_completed(futs):
                i, key = futs[f]
                try:
                    v = f.result()
                except RuntimeError as e:
                    # Ollama 不可用:撤掉未开工的请求,保检查点、整体失败
                    # (平台重试可续跑;不撤会等 executor 收尾拖几分钟)
                    for pf in futs:
                        pf.cancel()
                    save_report(args.out, result,
                                compute_summary(result, expected,
                                                ckpt_covered, "partial"))
                    raise SystemExit(f"[abort] {e};已完成 {len(result)} 槽已保存,重跑续审")
                except Exception as e:  # noqa: BLE001
                    v = {"verdict": "ERROR", "reason": str(e)[:120]}
                result[key] = {
                    "verdict": v.get("verdict") if v.get("verdict") in VERDICTS else "ERROR",
                    "reason": str(v.get("reason", ""))[:200],
                    "speaker": slots[i].get("speaker", "")}
                done_since_save += 1
                if done_since_save >= 5:
                    save_report(args.out, result,
                                compute_summary(result, expected,
                                                ckpt_covered, "partial"))
                    done_since_save = 0
                print(f"[{time.strftime('%H:%M:%S')}] {i:3d} {result[key]['verdict']:8s} "
                      f"{result[key]['reason'][:60]}", flush=True)
        save_report(args.out, result,
                    compute_summary(result, expected, ckpt_covered, "partial"))

    mode = "full"
    audit_keys(sampled, sampled)
    if args.sample > 1:
        mm = sum(1 for k in sampled
                 if result.get(k, {}).get("verdict") == "MISMATCH")
        if mm:
            print(f"抽样发现 {mm} 个 MISMATCH,自动转入全量审查", flush=True)
            mode = "full"
            audit_keys(expected, expected)
        else:
            mode = "sample"

    summary = compute_summary(result, expected, sampled if mode == "sample"
                              else expected, mode)
    summary.update({"slots_sha": file_sha(args.slots),
                    "zh_sha": file_sha(args.zh),
                    "model": args.model, "ts": time.strftime("%F %T")})
    save_report(args.out, result, summary)
    print(f"[OK] 审查 mode={mode} {summary['covered']}/{summary['needed']} 槽: "
          f"{summary['counts']}")
    if not summary["complete"]:
        raise SystemExit(3)
    if summary["mismatch"] >= args.fail_over:
        print(f"    [X] MISMATCH {summary['mismatch']} >= 阈值 {args.fail_over}:"
              f"疑似批量串位,需人工复核 -> {args.out}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
