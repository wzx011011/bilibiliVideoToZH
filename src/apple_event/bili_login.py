# -*- coding: utf-8 -*-
"""B站扫码登录:生成二维码 → 轮询 → 成功后凭据由 publish_module 落盘。

输出(NOHUP 日志/STDOUT):
  二维码 PNG 路径 + 终端 ASCII 二维码(供直接扫屏)
  结束时打印 JSON: {"status": "success"|"timeout"|"error", "user": "..."}
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_module as pm  # noqa: E402
import segno  # noqa: E402

PNG = Path(__file__).resolve().parents[2] / "work" / "bili-login-qr.png"

def main() -> int:
    qr = pm.bilibili_qr_create()
    segno.make(qr["qr_content"], error="m").save(str(PNG), scale=8, border=2, dark="#111")
    print(f"QR_PNG: {PNG}", flush=True)
    print(f"QR_URL: {qr['qr_content']}", flush=True)

    deadline = time.time() + 170
    while time.time() < deadline:
        res = pm.bilibili_qr_poll(qr["key"])
        code = res.get("code")
        if code == 0:
            ok, uname = pm.bili_logged_in()
            print(json.dumps({"status": "success", "user": uname}, ensure_ascii=False),
                  flush=True)
            return 0
        if code == 86038:
            print(json.dumps({"status": "expired"}, flush=True), flush=True)
            return 1
        # 180=未扫 86090=已扫待确认:继续轮询
        time.sleep(2)
    print(json.dumps({"status": "timeout"}), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
