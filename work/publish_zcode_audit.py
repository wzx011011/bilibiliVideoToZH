# -*- coding: utf-8 -*-
"""投稿 zcode-audit 单集到 B 站(知识区-计算机技术,自制)。复用 publish_module。"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import publish_module as pm  # noqa: E402

VIDEO = ROOT / "kinetic_demo/zcode-audit_video.mp4"
COVER = ROOT / "videos/cover-zcode-audit.jpg"
TITLE = "AI 编程工具会偷偷上传你的代码吗？我们做了一次完整取证"
DESC = (
    "AI 编程工具会不会偷偷把你的代码传上云端？本期对 ZCode 的仓库快照机制"
    "做了一次完整的本地取证：\n"
    "① 字符串探针：上传、加密、凭据等关键实现在无头运行时里零命中，"
    "上传管线只存在于桌面壳；\n"
    "② 启动链路：伴生进程以纯 Node 自托管方式拉起无头 app-server，"
    "进程内没有接线任何捕获逻辑；\n"
    "③ 行为实验：按完全相同的方式拉起无头进程，在一次性临时工作区跑一个真实回合"
    "——快照目录零新增，全盘路径搜索零命中。\n"
    "结论：手机→中继→伴生→无头这条远程链路是干净的；真正会打包上传的是桌面端 App"
    "（为打开过的工作区建档，本机一个 207MB 加密包曾重试 451 次）。\n"
    "两条建议：工具行为要用实验验证；每次升级后要重新审计。")
FOOTER = ("\n\n本视频为独立安全分析与技术科普，基于本地代码审计与行为实验，"
          "仅代表个人研究结论；工具行为可能随版本更新变化。"
          "制作：矢量舞台动画+AI语音合成。")
TAGS = "AI编程,代码安全,程序员,隐私保护,技术揭秘,ZCode,安全审计,科普"
TIDS = [231, 208, 201]  # 计算机技术 → 野生技术协会 → 科学科普
LEDGER = ROOT / "work" / "publish_ledger_kinetic.json"


def log(msg):
    print(msg, flush=True)


def main() -> int:
    s = pm.bili_session()
    ok, uname = pm.bili_logged_in(s)
    if not ok:
        log("B站登录失效,请先在平台扫码登录")
        return 1
    log(f"B站账号: {uname}")
    auth = pm._read_json(pm.bili_auth_path())
    csrf = (auth.get("cookies") or {}).get("bili_jct", "")
    sessdata = (auth.get("cookies") or {}).get("SESSDATA", "")

    log(f"封面 {COVER.name}")
    cover_url = pm._bili_upload_cover(s, csrf, COVER.read_bytes())
    log(f"上传 {VIDEO.name} ({VIDEO.stat().st_size // 1048576}MB)")
    pre = pm._bili_preupload(s, VIDEO.name, VIDEO.stat().st_size)
    filename = pm._bili_upos_upload(s, pre, sessdata, VIDEO, log)

    payload = {
        "copyright": 1,  # 自制
        "cover": cover_url,
        "desc": DESC + FOOTER,
        "tid": TIDS[0],
        "tag": TAGS,
        "title": TITLE[:80],
        "filename": filename,
        "videos": [{"filename": filename, "title": "", "desc": ""}],
        "dtime": 0,
        "act_reserve_create": 0,
        "no_reprint": 1,
        "csrf": csrf,
    }
    j = {}
    for tid in TIDS:
        payload["tid"] = tid
        r = s.post("https://member.bilibili.com/x/vu/web/add/v3",
                   params={"csrf": csrf}, json=payload, timeout=60)
        j = r.json()
        if j.get("code") == 0:
            break
        log(f"tid={tid} 失败 code={j.get('code')} msg={j.get('message')},试下一个")
    if j.get("code") != 0:
        raise RuntimeError(f"投稿失败 code={j.get('code')} msg={j.get('message')}")
    data = j.get("data") or {}
    log(f"✓ 投稿成功 bvid={data.get('bvid')} aid={data.get('aid')}")
    LEDGER.write_text(json.dumps(
        [{"slug": "zcode-audit", "aid": data.get("aid"),
          "bvid": data.get("bvid"), "title": TITLE, "tid": payload["tid"]}],
        ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
