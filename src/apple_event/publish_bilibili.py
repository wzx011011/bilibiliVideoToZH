# -*- coding: utf-8 -*-
"""发布《苹果2026秋季发布会速览》到 B 站。

复用 publish_module 的登录/上传助手函数,但投稿 payload 用"自制"类型
(publish_module.bilibili_publish 硬编码了哈佛幸福课的转载来源,不适用)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_module as pm  # noqa: E402

VIDEO = Path("D:/apple-event-202609/苹果2026秋季发布会-速览.mp4")
COVER = Path("D:/apple-event-202609/cover.jpg")

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
TID = 95  # 科技区-手机平板


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

    log("上传封面...")
    cover_url = pm._bili_upload_cover(s, csrf, COVER.read_bytes())

    log(f"初始化分片上传: {VIDEO.name} ({VIDEO.stat().st_size // 1048576}MB)")
    pre = pm._bili_preupload(s, VIDEO.name, VIDEO.stat().st_size)
    sessdata = (auth.get("cookies") or {}).get("SESSDATA", "")
    filename = pm._bili_upos_upload(s, pre, sessdata, VIDEO, log)
    log(f"分片合并完成: {filename}")

    payload = {
        "copyright": 1,  # 自制
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
