# -*- coding: utf-8 -*-
"""给已发布的 zcode-audit 稿件更换封面。

关键:稿件详情用 x/vupre/web/archive/view?bvid=(x2/creative 系已 404)，
从返回的 videos[].filename 重建 edit payload(x/vu/web/edit)。
"""
from pathlib import Path
import io
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))
import publish_module as pm  # noqa: E402
import publish_zcode_audit as _p  # noqa: E402  # DESC/FOOTER/TAGS 单一来源

BVID = "BV1Jae16mEiN"
AID = 117290926347812
COVER_PNG = ROOT / "work/zcode-audit-cover-final.png"
TITLE = "AI 编程工具会偷偷上传你的代码吗？我们做了一次完整取证"
TID = 231


def log(m):
    print(m, flush=True)


def main() -> int:
    from PIL import Image
    im = Image.open(COVER_PNG).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)

    s = pm.bili_session()
    ok, uname = pm.bili_logged_in(s)
    if not ok:
        log("B站登录失效")
        return 1
    auth = pm._read_json(pm.bili_auth_path())
    csrf = (auth.get("cookies") or {}).get("bili_jct", "")

    log("拉取稿件原始配置…")
    r = s.get("https://member.bilibili.com/x/vupre/web/archive/view",
              params={"topic_grey": 1, "bvid": BVID}, timeout=30)
    j = r.json()
    if j.get("code") != 0:
        log(f"详情失败 code={j.get('code')} msg={j.get('message')}")
        return 1
    d = j["data"]
    arc = d.get("archive") or {}
    vids = d.get("videos") or []
    log(f"archive: tid={arc.get('tid')} title={arc.get('title')!r}")
    log(f"videos: {[(v.get('filename'), v.get('title')) for v in vids]}")

    videos = [{"filename": v.get("filename", ""),
               "title": v.get("title", "") or "",
               "desc": v.get("desc", "") or "",
               "cid": v.get("cid")}
              for v in vids]
    if not videos or not any(v["filename"] for v in videos):
        log("仍未取得 filename,放弃编辑(不动稿件)")
        return 1

    log("上传新封面…")
    cover_url = pm._bili_upload_cover(s, csrf, buf.getvalue())
    log(f"新封面 URL: {cover_url[:90]}")

    payload = {
        "aid": AID,
        "cover": cover_url,
        "title": (arc.get("title") or TITLE)[:80],
        "desc": arc.get("desc") or (_p.DESC + _p.FOOTER),
        "tid": arc.get("tid") or TID,
        "tag": arc.get("tag") or _p.TAGS,
        "copyright": arc.get("copyright") or 1,
        "videos": videos,
        "desc_format_id": 9999,
        "dynamic": arc.get("dynamic") or "",
        "interactive": arc.get("interactive", 0) or 0,
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
            log(f"✓ 封面已更换 bvid={BVID} 新封面: {cover_url[:80]}")
            return 0
        if j.get("code") != 21540:  # 非限频错误不重试
            break
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
