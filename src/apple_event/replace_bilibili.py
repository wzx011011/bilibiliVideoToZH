# -*- coding: utf-8 -*-
"""把 BV1pgYh6kEYj 的视频源与封面原地替换为新版(保留 BV 号)。

复用 publish_module 的登录/上传助手;编辑端点 /x/vu/web/edit。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_module as pm  # noqa: E402

AID = 117244000476011
BVID = "BV1pgYh6kEYj"
VIDEO = Path("D:/apple-event-202609/苹果2026秋季发布会-速览.mp4")
COVER = Path("D:/apple-event-202609/cover.jpg")

# 与首次投稿一致的字段(编辑请求必须带全,缺失项会被清空)
TITLE = "3分钟速览苹果2026秋季发布会：iPhone 18 Pro、折叠屏Duo、Watch Ultra 4"
DESC = """北京时间9月10日凌晨苹果秋季发布会"Surprise and Shine"全部重点,3分钟看完。

· iPhone 18 Pro / Pro Max:首发2nm A20 Pro、48MP可变光圈主摄、Pro Max史上最大电池提升,$1,199/$1,299,9月18日发售
· iPhone Duo:苹果首款折叠屏,外屏≈iPhone 18 Pro的90%屏幕面积,纳米纹理内屏,$1,999,10月23日发售
· Apple Watch Series 12($399)/ Ultra 4($799):S11芯片+全新健康感知系统
· AirPods 5:开放式主动降噪,比AirPods 4多消除50%噪声,$129起
· iOS 27 / watchOS 27 9月14日推送;新版Siri AI首发不含欧盟

规格与价格均整理自 Apple Newsroom 官方新闻稿,产品图为官方图片;结尾含编辑观点(已标注)。
频道说明:本视频为资讯速览类内容,画面为自制的图文解说。"""
TAGS = "苹果,Apple,iPhone18Pro,iPhoneDuo,折叠屏iPhone,AppleWatch,AirPods,发布会,科技数码速览"
TID = 95


def log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    s = pm.bili_session()
    ok, uname = pm.bili_logged_in(s)
    if not ok:
        log("B站登录失效,请重新扫码")
        return 1
    log(f"B站账号: {uname}")
    auth = pm._read_json(pm.bili_auth_path())
    csrf = (auth.get("cookies") or {}).get("bili_jct", "")

    log("上传新封面...")
    cover_url = pm._bili_upload_cover(s, csrf, COVER.read_bytes())
    log(f"  封面: {cover_url}")

    log(f"上传新视频: {VIDEO.name} ({VIDEO.stat().st_size // 1048576}MB)")
    pre = pm._bili_preupload(s, VIDEO.name, VIDEO.stat().st_size)
    sessdata = (auth.get("cookies") or {}).get("SESSDATA", "")
    filename = pm._bili_upos_upload(s, pre, sessdata, VIDEO, log)
    log(f"  合并完成: {filename}")

    payload = {
        "aid": AID,
        "copyright": 1,
        "cover": cover_url,
        "desc": DESC,
        "tid": TID,
        "tag": TAGS,
        "title": TITLE[:80],
        "filename": filename,
        "videos": [{"filename": filename, "title": "", "desc": ""}],
        "dtime": 0,
        "act_reserve_create": 0,
        "no_reprint": 1,
        "csrf": csrf,
    }
    r = s.post("https://member.bilibili.com/x/vu/web/edit",
               params={"csrf": csrf}, json=payload, timeout=60)
    try:
        j = r.json()
    except ValueError:
        log(f"编辑响应非 JSON: HTTP {r.status_code} {r.text[:200]}")
        return 1
    if j.get("code") != 0:
        log(f"编辑失败 code={j.get('code')} msg={j.get('message')}")
        return 1
    log(f"✓ 替换成功 {BVID} aid={AID},等待重新审核")
    print(json.dumps({"aid": AID, "bvid": BVID, "new_filename": filename},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
