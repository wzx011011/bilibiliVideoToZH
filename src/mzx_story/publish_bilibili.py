# -*- coding: utf-8 -*-
"""发布《大明演义》系列到 B 站(知识区-人文历史,自制)。

复用 publish_module 的登录/上传助手函数;payload 与 apple_event/publish_bilibili
同款"自制"类型。逐集投稿,单集失败不影响后续,结束时汇总 aid/bvid。

用法:
  python src/mzx_story/publish_bilibili.py            # 发布全部待发集
  python src/mzx_story/publish_bilibili.py 1 3        # 只发第 1、3 集
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_module as pm  # noqa: E402

TID = 228  # 知识区-人文历史
FOOTER = ("\n\n本系列为原创历史科普动画：矢量图解+AI插画+语音合成，"
          "史实以《明史》等正史记载为据，观点仅供参考。更新不易，欢迎三连关注～")

EPISODES = [
    {
        "ep": 1,
        "video": "D:/mzx-ming01-professional/大明演义01-靖难之役.mp4",
        "cover": "videos/cover-ming01.jpg",
        "title": "大明演义01·靖难之役：叔叔为啥抢了侄子的皇位",
        "desc": "边画边讲的大明历史系列第 1 集。\n"
                "明朝开国三十一年，七十一岁的朱元璋驾崩，接班的不是儿子而是孙子。"
                "建文帝一年之内连削五王，燕王朱棣装疯自保，最终以“清君侧”之名起兵"
                "——三年拉锯后轻骑直捣南京，皇宫起火，建文帝下落成谜。",
        "tags": "大明演义,明朝,靖难之役,朱棣,建文帝,历史,人文历史,历史故事",
    },
    {
        "ep": 2,
        "video": "D:/mzx-ming02/大明演义02-朱元璋前传.mp4",
        "cover": "videos/cover-ming02.jpg",
        "title": "大明演义02·朱元璋：从讨饭和尚到开国皇帝",
        "desc": "边画边讲的大明历史系列第 2 集。\n"
                "1328 年生在赤贫农家，名字只能叫朱重八；1344 年半个月内痛失双亲，"
                "讨饭三年走遍淮西；25 岁投红巾军，鄱阳湖二十万对六十万一战定乾坤，"
                "40 岁开国称帝。废丞相、铁腕反腐，也留下胡蓝之狱的腥风——功过两面的洪武皇帝。",
        "tags": "大明演义,明朝,朱元璋,历史,人文历史,历史故事",
    },
    {
        "ep": 3,
        "video": "D:/mzx-ming03/大明演义03-朱棣永乐.mp4",
        "cover": "videos/cover-ming03.jpg",
        "title": "大明演义03·永乐大帝：迁都北京、下西洋、修大典",
        "desc": "边画边讲的大明历史系列第 3 集。\n"
                "从侄子手里抢来的皇位，怎么坐稳？朱棣先用刀子正名，再立碑收心："
                "修《永乐大典》两万两千卷、郑和宝船六下西洋最远抵达非洲、"
                "营建紫禁城迁都北京天子守国门、五次亲征漠北——功业远迈汉唐，"
                "骂名也永远钉在身上。",
        "tags": "大明演义,明朝,朱棣,永乐,郑和下西洋,紫禁城,永乐大典,历史,人文历史",
    },
    {
        "ep": 4,
        "video": "D:/mzx-ming04/大明演义04-仁宣之治.mp4",
        "cover": "videos/cover-ming04.jpg",
        "title": "大明演义04·仁宣之治：胖皇帝和蛐蛐皇帝的黄金十年",
        "desc": "边画边讲的大明历史系列第 4 集。\n"
                "体胖腿疾、被两个弟弟挤兑了二十年的朱高炽，一上任就平反冤狱、"
                "叫停下西洋、减免赋税，让国家喘了口气；儿子朱瞻基重用“三杨”、"
                "御驾亲征擒二叔，斗蛐蛐也玩出了名堂。父子在位十年，史称仁宣之治"
                "——明朝国力顶峰，却也埋下了宦官干政的雷。",
        "tags": "大明演义,明朝,仁宣之治,朱高炽,朱瞻基,历史,人文历史,历史故事",
    },
    {
        "ep": 5,
        "video": "D:/mzx-ming05-icu/大明演义05-土木堡之变-ICU版.mp4",
        "cover": "videos/cover-ming05.jpg",
        "title": "大明演义05·土木堡之变：皇帝被蒙古人抓走了",
        "desc": "边画边讲的大明历史系列第 5 集。\n"
                "宦官王振专权，怂恿二十三岁的英宗仓促亲征；几十万大军出居庸关，"
                "一路折腾断水断粮，八月十五在土木堡被瓦剌铁骑合围——随行文武大臣"
                "全部战死，皇帝本人被俘。也先挟着“叫门天子”到大同、宣府叩关，"
                "败报传回北京，朝堂哭成一片：有人翻出星象喊南迁，有个人站了出来。",
        "tags": "大明演义,明朝,土木堡之变,朱祁镇,王振,也先,历史,人文历史,历史故事",
    },
    {
        "ep": 6,
        "video": "D:/mzx-ming06/大明演义06-北京保卫战.mp4",
        "cover": "videos/cover-ming06.jpg",
        "title": "大明演义06·北京保卫战：于谦的孤注一掷",
        "desc": "边画边讲的大明历史系列第 6 集。\n"
                "“言南迁者，可斩！”于谦站了出来：调两京备操军、粮船自通州排队进京，"
                "拥郕王即位让也先手里的皇帝变成废牌，列阵九门之外背城而战。"
                "德胜门设伏空屋，神机营火器骤发——北京保住了。可八年后夺门之变，"
                "复辟的第一件事就是杀于谦；抄家时家无余财，只有正屋锁着的蟒袍和剑器。",
        "tags": "大明演义,明朝,北京保卫战,于谦,景泰帝,夺门之变,历史,人文历史,历史故事",
    },
    {
        "ep": 7,
        "video": "D:/mzx-ming07/大明演义07-成化朝.mp4",
        "cover": "videos/cover-ming07.jpg",
        "title": "大明演义07·成化朝：大十七岁的万贵妃与西厂特务",
        "desc": "边画边讲的大明历史系列第 7 集。\n"
                "成化帝一生最离不开的，是大自己十七岁的宫女万贞儿；他绕开东厂设西厂，"
                "交给宦官汪直，几个月掀翻一批大臣。可他也有另一面：为于谦平反、"
                "恢复景泰帝号、“成化犁庭”直捣建州女真老巢、安置荆襄百万流民。"
                "深居西苑不见大臣，“纸糊的三阁老、泥塑的六尚书”——懒与狠、情与政，拧成了一个人。",
        "tags": "大明演义,明朝,成化,万贵妃,西厂,成化犁庭,历史,人文历史,历史故事",
    },
    {
        "ep": 8,
        "video": "D:/mzx-ming08/大明演义08-弘治中兴.mp4",
        "cover": "videos/cover-ming08.jpg",
        "title": "大明演义08·弘治中兴：一生只娶一个人的皇帝",
        "desc": "边画边讲的大明历史系列第 8 集。\n"
                "生在冷宫、被万贵妃迫害着长大的朱祐樘，十八岁即位。他重开午朝、"
                "批奏章到深夜，待大臣宽厚从不廷杖羞辱；王恕、马文升、刘大夏满朝君子，"
                "治黄河、收复哈密，国库充实——史称弘治中兴。他还有帝王史上独一份的纪录："
                "一生只娶张皇后一人，不选妃不纳嫔。1505 年他把家底交给了儿子朱厚照——明朝最会玩的皇帝要来了。",
        "tags": "大明演义,明朝,弘治中兴,朱祐樘,历史,人文历史,历史故事",
    },
]


def publish_one(s, auth: dict, item: dict, log) -> dict:
    csrf = (auth.get("cookies") or {}).get("bili_jct", "")
    sessdata = (auth.get("cookies") or {}).get("SESSDATA", "")
    video = Path(item["video"])
    cover = Path(item["cover"])

    log(f"[ep{item['ep']:02d}] 封面 {cover.name}")
    cover_url = pm._bili_upload_cover(s, csrf, cover.read_bytes())

    log(f"[ep{item['ep']:02d}] 上传 {video.name} ({video.stat().st_size // 1048576}MB)")
    pre = pm._bili_preupload(s, video.name, video.stat().st_size)
    filename = pm._bili_upos_upload(s, pre, sessdata, video, log)

    payload = {
        "copyright": 1,  # 自制
        "cover": cover_url,
        "desc": item["desc"] + FOOTER,
        "tid": TID,
        "tag": item["tags"],
        "title": item["title"][:80],
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
        raise RuntimeError(f"投稿失败 code={j.get('code')} msg={j.get('message')}")
    data = j.get("data") or {}
    log(f"[ep{item['ep']:02d}] ✓ 投稿成功 bvid={data.get('bvid')}")
    return {"ep": item["ep"], "aid": data.get("aid"), "bvid": data.get("bvid"),
            "title": item["title"]}


def main() -> int:
    only = {int(a) for a in sys.argv[1:]}
    items = [e for e in EPISODES if not only or e["ep"] in only]

    s = pm.bili_session()
    ok, uname = pm.bili_logged_in(s)
    if not ok:
        print("B站登录失效,请重新扫码", flush=True)
        return 1
    print(f"B站账号: {uname}", flush=True)
    auth = pm._read_json(pm.bili_auth_path())

    results, fails = [], []
    for item in items:
        try:
            results.append(publish_one(s, auth, item, print))
        except Exception as exc:  # noqa: BLE001 - 单集失败继续下一集
            print(f"[ep{item['ep']:02d}] ✗ {type(exc).__name__}: {exc}", flush=True)
            fails.append({"ep": item["ep"], "error": str(exc)})

    print(json.dumps({"published": results, "failed": fails},
                     ensure_ascii=False, indent=1), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
