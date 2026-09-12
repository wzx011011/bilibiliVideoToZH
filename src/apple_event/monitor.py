# -*- coding: utf-8 -*-
"""苹果发布会实时监控:多源轮询 → 去重事实流 + 全页快照,供成片脚本引用。

源优先级(权威性):
1. Apple Newsroom 官方通稿(发布会进行中逐条发布,规格/价格零误差)
2. MacRumors Live 文字实录(稳定 URL,滚动快)
3. CNET Live(备用)

输出(work/apple-event-202609/):
  facts.json    时间线事实(标题级,原子写,含来源与捕获时间)
  raw/*.txt     每轮各源全文快照(成片时通读提炼)
  seen.json     已见标题指纹(断点续跑不重复)
  monitor.log   运行日志

用法:
  python src/apple_event/monitor.py --once            # 单轮(预检/补拍)
  python src/apple_event/monitor.py --until 02:55     # 持续轮询到本地 HH:MM
网络走 Clash 代理(可用 https_proxy 环境变量覆盖)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work" / "apple-event-202609"
RAW = WORK / "raw"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

SOURCES = {
    "newsroom": "https://www.apple.com/newsroom/archive/2026/",
    "verge": "https://www.theverge.com/apple-event",
    "cnet": "https://www.cnet.com/news-live/apple-event-2026-live-updates/",
}


def _opener():
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") \
        or "http://127.0.0.1:7897"
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}))


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity", "Accept-Language": "en-US,en;q=0.9"})
    with _opener().open(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def html_text(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean(snippet: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", snippet))).strip()


def headlines_newsroom(html: str) -> list[tuple[str, str]]:
    """官方通稿:(相对路径, 标题),按页面顺序。"""
    items = []
    for href, snippet in re.findall(
            r'<a[^>]+href="(/newsroom/2026/0[89]/[^"]+)"[^>]*>(.*?)</a>',
            html, flags=re.S):
        title = _clean(snippet)
        if title and len(title) >= 8:
            items.append((href, title))
    seen, out = set(), []
    for href, title in items:
        if href not in seen:
            seen.add(href)
            out.append((f"https://www.apple.com{href}", title))
    return out


def headlines_generic(html: str, base: str) -> list[tuple[str, str]]:
    """直播页兜底提取:标题级标签文本,滤导航噪声。"""
    out = []
    for tag in ("h1", "h2", "h3"):
        for snippet in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", html,
                                  flags=re.S | re.I):
            title = _clean(snippet)
            if 16 <= len(title) <= 220 and not re.match(
                    r"^(share|newsletter|sign in|topics|latest)", title, re.I):
                out.append((base, title))
    return out


def fingerprint(title: str) -> str:
    norm = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title.lower())
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def atomic_write(path: Path, payload: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def log(message: str) -> None:
    line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    with (WORK / "monitor.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def poll_once() -> int:
    """抓一轮全部源;返回新增事实数。"""
    WORK.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(exist_ok=True)
    seen_path = WORK / "seen.json"
    seen = set(json.loads(seen_path.read_text(encoding="utf-8"))
               if seen_path.exists() else [])
    facts_path = WORK / "facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8")) \
        if facts_path.exists() else []
    stamp = dt.datetime.now().strftime("%H%M%S")
    added = 0
    for name, url in SOURCES.items():
        try:
            html = fetch(url)
        except Exception as exc:  # 单源失败不阻塞其它源
            log(f"[warn] {name} fetch失败: {type(exc).__name__}: {exc}")
            continue
        (RAW / f"{stamp}-{name}.html").write_text(html, encoding="utf-8")
        (RAW / f"{stamp}-{name}.txt").write_text(html_text(html), encoding="utf-8")
        if name == "newsroom":
            heads = headlines_newsroom(html)
        else:
            heads = headlines_generic(html, url)
        for link, title in heads:
            fp = fingerprint(title)
            if fp in seen:
                continue
            seen.add(fp)
            facts.append({"captured": dt.datetime.now().isoformat(timespec="seconds"),
                          "source": name, "title": title, "url": link})
            added += 1
    atomic_write(seen_path, json.dumps(sorted(seen), ensure_ascii=False))
    atomic_write(facts_path, json.dumps(facts, ensure_ascii=False, indent=2))
    log(f"poll ok: 新增 {added} 条,累计 {len(facts)} 条")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="只抓一轮")
    parser.add_argument("--interval", type=int, default=45)
    parser.add_argument("--until", default="02:55", help="本地 HH:MM 停止")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    if args.once:
        poll_once()
        return 0
    log(f"monitor start, interval={args.interval}s, until={args.until}")
    while True:
        now = dt.datetime.now().strftime("%H:%M")
        if now >= args.until:
            log("到达停止时间,退出")
            return 0
        try:
            poll_once()
        except Exception as exc:
            log(f"[error] 轮询异常(继续): {type(exc).__name__}: {exc}")
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
