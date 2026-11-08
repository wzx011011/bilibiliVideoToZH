# -*- coding: utf-8 -*-
"""把 BV1Jae16mEiN 的视频本体替换为合并加强版(链路取证+桌面端深挖)。

流程:preupload+upos 上传新文件 → x/vu/web/edit 将 videos[].filename 换成新文件。
payload 形状与 edit_zcode_cover.py 的成功版一致(封面沿用线上现 URL 不动)。
"""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))
import publish_module as pm  # noqa: E402
import publish_zcode_audit as _p  # noqa: E402  # DESC/FOOTER/TAGS 单一来源

BVID = "BV1Jae16mEiN"
AID = 117290926347812
VIDEO = ROOT / "kinetic_demo/zcode-audit_video.mp4"
LIVE_COVER = "https://archive.biliimg.com/bfs/archive/aceb15cf20531b42315ae6188698dabefbac0026.jpg"
TITLE = "AI 编程工具会偷偷上传你的代码吗？我们做了一次完整取证"
TID = 231
MERGE_NOTE = (
    "\n\n本片为合并加强版：在原链路取证的基础上，补充桌面端深挖——"
    "明文快照清单、.git 历史占比 98%、每次提问前抓取、开关关不掉、"
    "信封加密链路与防御建议；关键数据均已在本机独立复核。"
    "桌面端部分参考了社区同主题独立分析（blog.ferstar.org），一并致谢。")


def log(m):
    print(m, flush=True)


def main() -> int:
    s = pm.bili_session()
    ok, uname = pm.bili_logged_in(s)
    if not ok:
        log("B站登录失效")
        return 1
    auth = pm._read_json(pm.bili_auth_path())
    csrf = (auth.get("cookies") or {}).get("bili_jct", "")
    sessdata = (auth.get("cookies") or {}).get("SESSDATA", "")

    log(f"上传新视频 {VIDEO.name} ({VIDEO.stat().st_size // 1048576}MB)")
    pre = pm._bili_preupload(s, VIDEO.name, VIDEO.stat().st_size)
    new_fname = pm._bili_upos_upload(s, pre, sessdata, VIDEO, log)
    log(f"新 filename: {new_fname}")

    payload = {
        "aid": AID,
        "cover": LIVE_COVER,
        "title": TITLE[:80],
        "desc": _p.DESC + _p.FOOTER + MERGE_NOTE,
        "tid": TID,
        "tag": _p.TAGS,
        "copyright": 1,
        "videos": [{"filename": new_fname, "title": "", "desc": ""}],
        "desc_format_id": 9999,
        "dynamic": "",
        "interactive": 0,
        "act_reserve_create": 0,
        "no_disturbance": 0,
        "no_reprint": 1,
        "recreate": -1,
        "subtitle": {"open": 0, "lan": ""},
        "dolby": 0,
        "lossless_music": 0,
        "web_os": 1,
        "csrf": csrf,
    }
    headers = {"Referer": "https://member.bilibili.com",
               "Content-Type": "application/json;charset=UTF-8"}
    for wait in (0, 60, 120):
        if wait:
            log(f"等 {wait}s 重试…")
            time.sleep(wait)
        r = s.post("https://member.bilibili.com/x/vu/web/edit",
                   params={"csrf": csrf, "t": int(time.time())},
                   json=payload, headers=headers, timeout=60)
        j = r.json()
        log(f"edit code={j.get('code')} msg={j.get('message')}")
        if j.get("code") == 0:
            log(f"✓ 视频已替换 bvid={BVID}")
            return 0
        if j.get("code") != 21540:
            break
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
