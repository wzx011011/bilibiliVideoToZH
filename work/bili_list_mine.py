# -*- coding: utf-8 -*-
"""列出 B 站账号自己的投稿(wbi 签名走空间存档接口),用于核对哪些集已发布。

用法: work/.venv-ocr/Scripts/python.exe work/bili_list_mine.py [关键词]
"""
import hashlib
import json
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import publish_module as pm  # noqa: E402

MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def mixin_key1(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_TAB)[:32]


def wbi_sign(params: dict, img_key: str, sub_key: str) -> dict:
    mixin = mixin_key1(img_key + sub_key)
    params = {**params, "wts": int(time.time())}
    qs = urllib.parse.urlencode(
        {k: "".join(ch for ch in str(v) if ch not in "!'()*")
         for k, v in sorted(params.items())})
    params["w_rid"] = hashlib.md5((qs + mixin).encode()).hexdigest()
    return params


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else None
    s = pm.bili_session()
    ok, uname = pm.bili_logged_in(s)
    if not ok:
        print("B站登录失效", flush=True)
        return 1
    mid = s.cookies.get("DedeUserID")
    nav = s.get("https://api.bilibili.com/x/web-interface/nav",
                headers={"Referer": "https://www.bilibili.com"},
                timeout=30).json()
    w = nav["data"]["wbi_img"]
    img_key = w["img_url"].rsplit("/", 1)[1].split(".")[0]
    sub_key = w["sub_url"].rsplit("/", 1)[1].split(".")[0]
    items = []
    for pn in (1, 2, 3):
        params = wbi_sign({"mid": mid, "pn": pn, "ps": 30, "order": "pubdate"},
                          img_key, sub_key)
        j = s.get("https://api.bilibili.com/x/space/wbi/arc/search",
                  params=params,
                  headers={"Referer": f"https://space.bilibili.com/{mid}"},
                  timeout=30).json()
        if j.get("code") != 0:
            print(f"[code {j.get('code')}] {j.get('message')}", flush=True)
            return 1
        vlist = (j.get("data") or {}).get("list", {}).get("vlist") or []
        items.extend(vlist)
        if len(items) >= (j.get("data", {}).get("total") or 0):
            break
    print(f"账号 {uname} 共拉到 {len(items)} 个投稿:", flush=True)
    for v in items:
        title = v.get("title", "")
        if keyword and keyword not in title:
            continue
        print(f"  {v.get('created')}  {v.get('bvid')}  {title[:50]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
