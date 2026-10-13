# -*- coding: utf-8 -*-
"""发布《AI 快讯》栏目成片到 B 站(自制,科技区)。

复用 publish_module 登录/上传助手;元数据走参数,供每日定时链与人工投稿共用。

用法:
  python src/publish_ai_news.py --video <mp4> --cover <jpg> --title <标题> \
      --tags <逗号分隔> --desc-file <txt路径> [--tid 95]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_module as pm  # noqa: E402


def log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--cover", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--tags", required=True)
    ap.add_argument("--desc-file", required=True)
    ap.add_argument("--tid", type=int, default=95)  # 科技区-手机平板(苹果速览同款)
    args = ap.parse_args()

    video = Path(args.video)
    cover = Path(args.cover)
    desc = Path(args.desc_file).read_text(encoding="utf-8").strip()
    assert video.exists() and cover.exists(), "视频或封面不存在"

    s = pm.bili_session()
    ok, uname = pm.bili_logged_in(s)
    if not ok:
        log("B站登录失效,请重新扫码")
        return 1
    log(f"B站账号: {uname}")
    auth = pm._read_json(pm.bili_auth_path())
    csrf = (auth.get("cookies") or {}).get("bili_jct", "")

    log("上传封面...")
    cover_url = pm._bili_upload_cover(s, csrf, cover.read_bytes())

    log(f"初始化分片上传: {video.name} ({video.stat().st_size // 1048576}MB)")
    pre = pm._bili_preupload(s, video.name, video.stat().st_size)
    sessdata = (auth.get("cookies") or {}).get("SESSDATA", "")
    filename = pm._bili_upos_upload(s, pre, sessdata, video, log)
    log(f"分片合并完成: {filename}")

    payload = {
        "copyright": 1,  # 自制
        "cover": cover_url,
        "desc": desc,
        "tid": args.tid,
        "tag": args.tags,
        "title": args.title[:80],
        "filename": filename,
        "videos": [{"filename": filename, "title": "", "desc": ""}],
        "dtime": 0,
        "act_reserve_create": 0,
        "no_reprint": 1,
        "csrf": csrf,
    }
    r = s.post("https://member.bilibili.com/x/vu/web/add/v3",
               params={"csrf": csrf}, json=payload, timeout=60)
    j = r.json()
    if j.get("code") != 0:
        log(f"投稿失败 code={j.get('code')} msg={j.get('message')}")
        return 1
    aid = (j.get("data") or {}).get("aid")
    bvid = (j.get("data") or {}).get("bvid")
    log(f"✓ 投稿成功 aid={aid} bvid={bvid}")
    print(json.dumps({"aid": aid, "bvid": bvid}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
