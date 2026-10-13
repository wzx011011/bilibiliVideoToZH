# -*- coding: utf-8 -*-
"""发布《大明演义》系列到 B 站(知识区-人文历史,自制)。

复用 publish_module 的登录/上传助手函数;payload 与 apple_event/publish_bilibili
同款"自制"类型。逐集投稿,单集失败不影响后续,结束时汇总 aid/bvid。

用法:
  python src/mzx_story/publish_bilibili.py            # 自动:队列取 ≤2 部未发集投稿
  python src/mzx_story/publish_bilibili.py 1 3        # 强制发第 1、3 集(不看台账)

自动模式(2026-09-13 定时任务用):从 work/publish_queue.json(已过 QC 的待发集号)
按顺序取未发的前 2 部;本地缺视频自动从 NAS 拉取;成功记入 work/publish_ledger.json
防重发。产能约每天 1 集,队列空属正常,直接退出。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "work" / "publish_ledger.json"
QUEUE = ROOT / "work" / "publish_queue.json"
PUBDIR = "D:/mzx-publish"
NAS_DIR = "/volume1/share/视频汉化项目/临时-试听/明朝故事"
AUTO_BATCH = 2


def _find_scp() -> str:
    """定时任务环境 PATH 首位是 System32 OpenSSH 的 scp,中文参数按 ANSI(GBK)
    转码后 NAS 收到乱码路径报 No such file;优先 Git 自带 scp(UTF-8 干净)。"""
    for cand in (Path(r"F:\Program Files\Git\usr\bin\scp.exe"),
                 Path(r"C:\Program Files\Git\usr\bin\scp.exe")):
        if cand.exists():
            return str(cand)
    return "scp"


SCP = _find_scp()

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
    {
        "ep": 9,
        "video": f"{PUBDIR}/大明演义09-正德-CV3版.mp4",
        "nas_video": f"{NAS_DIR}/大明演义09-正德-CV3版.mp4",
        "cover": "videos/cover-ming09.jpg",
        "title": "大明演义09·正德:不想当皇帝的皇帝",
        "desc": "边画边讲的大明历史系列第 9 集。\n"
                "十五岁登基的朱厚照把皇宫过成了游乐场:建豹房养豹收义子,"
                "自封\"威武大将军朱寿\"给自己升官;应州大捷亲自挥刀上阵,"
                "双方十几万大军打了几天,他斩敌一名,差点把自己也搭进去。"
                "宁王造反,御驾亲征走到半路王阳明已经平了叛——他不甘心,要把宁王"
                "放出来\"再抓一遍\"。清江浦落水受寒,三十一岁暴崩无嗣,"
                "堂弟朱厚熜从湖北进京,大明皇位从此换了支系。",
        "tags": "大明演义,明朝,正德,朱厚照,应州大捷,王阳明,宁王之乱,历史,人文历史",
    },
    {
        "ep": 10,
        "video": f"{PUBDIR}/大明演义10-嘉靖-CV3版.mp4",
        "nas_video": f"{NAS_DIR}/大明演义10-嘉靖-CV3版.mp4",
        "cover": "videos/cover-ming10.jpg",
        "title": "大明演义10·嘉靖(上):外藩少年掀翻满朝文武",
        "desc": "边画边讲的大明历史系列第 10 集。\n"
                "十四岁的兴藩世子朱厚熜进京即位,第一仗就为\"我爸是谁\":大礼议"
                "拉锯三年,张璁送上理论武器,少年天子在左顺门廷杖一百八十余名大臣,"
                "硬是把亲爹抬进了太庙。首辅杨廷和致仕,张璁桂萼新贵上位;"
                "皇帝移居西苑修玄炼丹,壬寅宫变里差点被几个宫女勒死——"
                "幕后操盘的手,正慢慢收紧。",
        "tags": "大明演义,明朝,嘉靖,大礼议,朱厚熜,杨廷和,壬寅宫变,历史,人文历史",
    },
    {
        "ep": 11,
        "video": f"{PUBDIR}/大明演义11-嘉靖-CV3版.mp4",
        "nas_video": f"{NAS_DIR}/大明演义11-嘉靖-CV3版.mp4",
        "cover": "videos/cover-ming11.jpg",
        "title": "大明演义11·嘉靖(下):严嵩、倭寇与庚戌之变",
        "desc": "边画边讲的大明历史系列第 11 集。\n"
                "严嵩靠一手青词独相二十年,儿子严世蕃当\"小丞相\";杨继盛"
                "\"铁肩担道义,辣手著文章\",抬棺上疏弹劾严嵩十大罪,死于诏狱。"
                "庚戌之变俺答铁骑兵临北京城下;东南倭乱大爆发,戚继光义乌招兵"
                "练成戚家军,台州九战九捷,与俞大猷联手荡平倭寇。海瑞买棺材骂皇帝,"
                "嘉靖读了叹气连连——但帝国的病,已经不轻了。",
        "tags": "大明演义,明朝,嘉靖,严嵩,戚继光,倭寇,海瑞,庚戌之变,历史,人文历史",
    },
    {
        "ep": 12,
        "video": f"{PUBDIR}/大明演义12-隆庆-CV3版.mp4",
        "nas_video": f"{NAS_DIR}/大明演义12-隆庆-CV3版.mp4",
        "cover": "videos/cover-ming12.jpg",
        "title": "大明演义12·隆庆:闷皇帝干对的两件事",
        "desc": "边画边讲的大明历史系列第 12 集。\n"
                "当了三十年闲散藩王的朱载坖即位,木讷寡言、不爱管事,"
                "却拍板了两件改变帝国的大事:隆庆开关解除海禁,月港开埠白银滚滚"
                "流入;俺答封贡封王互市,北疆罢兵近二十年。朝堂上徐阶、高拱、"
                "张居正内阁暗战,高拱再起主政,张居正在旁蓄势;隆庆六年皇帝骤崩,"
                "十岁幼主临朝——山雨欲来。",
        "tags": "大明演义,明朝,隆庆,隆庆开关,俺答封贡,高拱,张居正,历史,人文历史",
    },
    {
        "ep": 13,
        "video": f"{PUBDIR}/大明演义13-张居正-CV3版.mp4",
        "nas_video": f"{NAS_DIR}/大明演义13-张居正-CV3版.mp4",
        "cover": "videos/cover-ming13.jpg",
        "title": "大明演义13·张居正:帝国最后的裱糊匠",
        "desc": "边画边讲的大明历史系列第 13 集。\n"
                "隆庆驾崩第六天,张居正联手冯保一天扳倒高拱,走上台前摄政十年:"
                "考成法整肃官僚,一条鞭法把赋税折成白银,国库从亏空到积银六百万两;"
                "用戚继光守北边、李成梁镇辽东。夺情风波让师生父子情面撕破,"
                "万历对他的敬畏渐渐变成怨恨;张居正一死即遭抄家清算,长子自尽,"
                "人亡政息——大明最后的机会窗口,关上了。",
        "tags": "大明演义,明朝,张居正,考成法,一条鞭法,万历,冯保,历史,人文历史",
    },
    {
        "ep": 14,
        "video": f"{PUBDIR}/大明演义14-万历-CV3版.mp4",
        "nas_video": f"{NAS_DIR}/大明演义14-万历-CV3版.mp4",
        "cover": "videos/cover-ming14.jpg",
        "title": "大明演义14·万历亲政:皇帝跟大臣冷战十五年",
        "desc": "边画边讲的大明历史系列第 14 集。\n"
                "亲政头几年万历勤政俭省,清算张居正后大权独揽;可立储难题来了:"
                "想立郑贵妃的儿子朱常洵,大臣们搬出祖制死磕\"争国本\",一争十五年,"
                "逼得他立长子朱常洛了事。皇帝一怒几十年不上朝,奏章堆积,"
                "六部堂官缺员过半,帝国空转;三大征惨胜掏空家底——"
                "海对岸的渔翁,正在辽东悄悄长大。",
        "tags": "大明演义,明朝,万历,争国本,朱常洵,朱常洛,东林党,历史,人文历史",
    },
    {
        "ep": 15,
        "video": f"{PUBDIR}/大明演义15-万历三大征上-CV3版.mp4",
        "nas_video": f"{NAS_DIR}/大明演义15-万历三大征上-CV3版.mp4",
        "cover": "videos/cover-ming15.jpg",
        "title": "大明演义15·万历三大征(上):跨过鸭绿江",
        "desc": "边画边讲的大明历史系列第 15 集。\n"
                "哱拜据宁夏反了,李如松引黄河水灌城破敌;丰臣秀吉统一日本,"
                "十几万大军跨海扑向朝鲜,两个月汉城陷落,国王跑到鸭绿江边。"
                "李如松率四万明军跨过鸭绿江,火炮轰开平壤城,碧蹄馆血战遇伏;"
                "和谈骗局折腾五年,战火重燃,丰臣秀吉病亡,露梁海战邓子龙"
                "与李舜臣双双殉国。惨胜的账单摆上案头——辽东的渔翁,该收网了。",
        "tags": "大明演义,明朝,万历三大征,朝鲜之役,李如松,露梁海战,丰臣秀吉,历史,人文历史",
    },
    {
        "ep": 16,
        "video": f"{PUBDIR}/大明演义16-万历三大征下.mp4",
        "nas_video": f"{NAS_DIR}/大明演义16-万历三大征下-CV3版.mp4",
        "cover": "videos/cover-ming16.jpg",
        "title": "大明演义16·万历三大征(下):打赢了所有仗,也打空了家底",
        "desc": "边画边讲的大明历史系列第 16 集。\n"
                "播州七百年杨氏土司的最后一战:杨应龙据海龙囤反了,万历倾国一战,"
                "李化龙坐镇重庆调二十多万大军八路进兵,猛将刘綎提刀先登。仗全赢了——"
                "可两千万两军费掏空内库国库,矿监税使逼反市民,辽东李成梁晚年弃地养虎,"
                "努尔哈赤含恨起兵十三副遗甲。三大征赢了每一场,却输掉了帝国的家底。",
        "tags": "大明演义,明朝,万历三大征,播州之役,杨应龙,海龙囤,努尔哈赤,历史,人文历史",
    },
    {
        "ep": 17,
        "video": f"{PUBDIR}/大明演义17-晚明三大案.mp4",
        "nas_video": f"{NAS_DIR}/大明演义17-晚明三大案-CV3版.mp4",
        "cover": "videos/cover-ming17.jpg",
        "title": "大明演义17·晚明三大案:一个月皇帝与三场罗生门",
        "desc": "边画边讲的大明历史系列第 17 集。\n"
                "苦熬三十九年的太子朱常洛终于登基,在位一个月暴毙——梃击案进宫打人的"
                "汉子是谁指使的?红丸要了皇帝的命是谁下的毒?李选侍赖在乾清宫不走,"
                "大臣们把十六岁的新君连拖带抱\"抢\"出宫。三个月换了三朝,东林党争撕开,"
                "木匠皇帝天启登基,批红悄悄落进了他身边大伴魏忠贤的手里。",
        "tags": "大明演义,明朝,晚明三大案,朱常洛,天启帝,东林党,魏忠贤,历史,人文历史",
    },
    {
        "ep": 18,
        "video": f"{PUBDIR}/大明演义18-魏忠贤.mp4",
        "nas_video": f"{NAS_DIR}/大明演义18-魏忠贤-CV3版.mp4",
        "cover": "videos/cover-ming18.jpg",
        "title": "大明演义18·魏忠贤:九千岁的天下",
        "desc": "边画边讲的大明历史系列第 18 集。\n"
                "河间泼皮魏四赌输了家当,自宫进宫,搭上奶妈客氏一路爬到司礼监。"
                "皇帝做木匠,他管批红:五虎十狗四十孙组成阉党,东林六君子死于诏狱,"
                "生祠修遍天下,喊他九千九百岁。天启驾崩那夜,信王朱由检入宫即位,"
                "带着干粮警惕了一整夜——然后只用一张奏疏和三个月,就让九千岁自缢在阜城旅店。",
        "tags": "大明演义,明朝,魏忠贤,天启帝,阉党,东林党,崇祯,历史,人文历史",
    },
    {
        "ep": 19,
        "video": f"{PUBDIR}/大明演义19-袁崇焕与宁远.mp4",
        "nas_video": f"{NAS_DIR}/大明演义19-袁崇焕与宁远-CV3版.mp4",
        "cover": "videos/cover-ming19.jpg",
        "title": "大明演义19·袁崇焕与宁远:帝国最后的高光",
        "desc": "边画边讲的大明历史系列第 19 集。\n"
                "兵部小官袁崇焕单骑出关请缨,在宁远城头用红衣大炮轰伤努尔哈赤,"
                "打出明朝对后金的第一场胜仗——功劳却记到了魏忠贤名下。崇祯平台召对,"
                "他许下\"五年平辽\"的军令状,持尚方宝剑先斩岛上毛文龙;皇太极的暗流,"
                "正在宁锦防线之外悄悄绕向蒙古。",
        "tags": "大明演义,明朝,袁崇焕,宁远大捷,努尔哈赤,崇祯,毛文龙,历史,人文历史",
    },
    {
        "ep": 20,
        "video": f"{PUBDIR}/大明演义20-己巳之变.mp4",
        "nas_video": f"{NAS_DIR}/大明演义20-己巳之变-CV3版.mp4",
        "cover": "videos/cover-ming20.jpg",
        "title": "大明演义20·己巳之变:皇太极兵临北京",
        "desc": "边画边讲的大明历史系列第 20 集。\n"
                "皇太极绕开宁锦防线,从蒙古破边墙直插遵化——长城被掏了个洞,京师戒严。"
                "袁崇焕率关宁军两昼夜疾驰三百里,广渠门外血战击退后金;可一封反间记,"
                "让多疑的崇祯在平台把他下狱,次年凌迟,百姓争食其肉。孙承宗临危老帅救火,"
                "长城还在,守长城的人没了。",
        "tags": "大明演义,明朝,己巳之变,皇太极,袁崇焕,崇祯,孙承宗,历史,人文历史",
    },
    {
        "ep": 21,
        "video": f"{PUBDIR}/大明演义21-流寇席卷.mp4",
        "nas_video": f"{NAS_DIR}/大明演义21-流寇席卷-CV3版.mp4",
        "cover": "videos/cover-ming21.jpg",
        "title": "大明演义21·流寇席卷:闯王来了不纳粮",
        "desc": "边画边讲的大明历史系列第 21 集。\n"
                "陕西连年大旱,朝廷为省几十万两裁撤驿站,把驿卒李自成裁成了流寇。"
                "车箱峡一场大雨让绝境中的农民军反败为胜,剿来剿去越剿越多;凤阳焚了皇陵,"
                "闯王高迎祥战死,李自成继称闯王。洪承畴孙传庭刚在东线扑灭大火,"
                "清军又破边墙抽血——李自成把福王炖成\"福禄酒\"那天,大明的账也快到总清算。",
        "tags": "大明演义,明朝,李自成,流寇,高迎祥,张献忠,崇祯,历史,人文历史",
    },
    {
        "ep": 22,
        "video": f"{PUBDIR}/大明演义22-崇祯的孤注.mp4",
        "nas_video": f"{NAS_DIR}/大明演义22-崇祯的孤注-CV3版.mp4",
        "cover": "videos/cover-ming22.jpg",
        "title": "大明演义22·崇祯的孤注:双线作战的十年",
        "desc": "边画边讲的大明历史系列第 22 集。\n"
                "关外清军步步紧逼,关内流寇燎原,崇祯把最后家底押上两条战线。"
                "松锦大战十三万明军崩溃,洪承畴被俘绝食求死却降了清,朝廷还在给他设坛痛祭;"
                "张献忠武昌称王,李自成襄京建政,华北又赶上特大瘟疫。孙传庭被逼出潼关,"
                "一败涂地——《明史》说\"传庭死,明亡矣\",这是给十年双线作战的判词。",
        "tags": "大明演义,明朝,松锦大战,洪承畴,孙传庭,李自成,崇祯,历史,人文历史",
    },
    {
        "ep": 23,
        "video": f"{PUBDIR}/大明演义23-1644煤山.mp4",
        "nas_video": f"{NAS_DIR}/大明演义23-1644煤山-CV3版.mp4",
        "cover": "videos/cover-ming23.jpg",
        "title": "大明演义23·1644:煤山的最后一天",
        "desc": "边画边讲的大明历史系列第 23 集。\n"
                "李自成西安称王,五十万大军渡河东征:宁武关周遇吉全家殉国,"
                "大同宣府开门投降,南迁之议吵了一个月没人敢拍板。三月十八夜,"
                "崇祯鸣钟无人上朝,携太监王承恩登煤山自缢,遗书\"任贼分裂朕尸,勿伤百姓一人\"。"
                "城破之后吴三桂引清军入关,一片石大战改写东亚——大明二百七十六年,落幕了。",
        "tags": "大明演义,明朝,崇祯,煤山自缢,李自成,吴三桂,一片石之战,历史,人文历史",
    },
    {
        "ep": 24,
        "video": f"{PUBDIR}/大明演义24-南明终章.mp4",
        "nas_video": f"{NAS_DIR}/大明演义24-南明终章-CV3版.mp4",
        "cover": "videos/cover-ming24.jpg",
        "title": "大明演义24·南明终章:最后的抗争与大明落幕",
        "desc": "边画边讲的大明历史系列第 24 集。\n"
                "崇祯自缢后,南京弘光朝廷一年而亡,史可法殉城,扬州十日;隆武帝志在恢复,"
                "却被郑芝龙出卖。李定国两蹶名王,逼死孔有德、阵斩尼堪,是南明最后的军神;"
                "郑成功北伐南京功败垂成,退守台湾。永历帝逃入缅甸被吴三桂勒死——"
                "大明落幕,但孤岛上的余晖还要再飘二十年。",
        "tags": "大明演义,明朝,南明,史可法,李定国,郑成功,扬州十日,历史,人文历史",
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


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def ensure_local_video(item: dict, log) -> Path:
    """本地没有(或过小)的成品视频自动从 NAS 拉取。"""
    video = Path(item["video"])
    if video.exists() and video.stat().st_size > 10 * 1048576:
        return video
    nas = item.get("nas_video")
    if not nas:
        raise FileNotFoundError(f"本地缺视频且未配置 NAS 路径: {video}")
    log(f"[ep{item['ep']:02d}] 本地缺视频,从 NAS 拉取 {Path(nas).name}")
    video.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [SCP, "-o", "ConnectTimeout=15", f"nas:{nas}", str(video)],
        capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not video.exists() or video.stat().st_size < 10 * 1048576:
        raise RuntimeError(f"NAS 拉取失败: {(r.stderr or '').strip()[-300:]}")
    return video


def main() -> int:
    forced = {int(a) for a in sys.argv[1:]}
    if forced:
        items = [e for e in EPISODES if e["ep"] in forced]
        missing = forced - {e["ep"] for e in items}
        if missing:
            print(f"未知集号: {sorted(missing)}", flush=True)
            return 1
    else:
        published = {rec["ep"] for rec in _read_json(LEDGER, [])}
        pending = sorted(ep for ep in _read_json(QUEUE, []) if ep not in published)
        pending = pending[:AUTO_BATCH]
        if not pending:
            print("队列为空或已全部发布,退出(产能约每天 1 集,属正常)", flush=True)
            return 0
        by_ep = {e["ep"]: e for e in EPISODES}
        items = []
        for ep in pending:
            if ep in by_ep:
                items.append(by_ep[ep])
            else:
                print(f"[ep{ep:02d}] 不在 EPISODES 表中,跳过", flush=True)
        if not items:
            return 0
        print(f"本次待发: {[it['ep'] for it in items]}", flush=True)

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
            ensure_local_video(item, print)
            item = {**item, "cover": str(ROOT / item["cover"])}
            results.append(publish_one(s, auth, item, print))
            ledger = _read_json(LEDGER, [])
            ledger.append({"ep": item["ep"], "aid": results[-1]["aid"],
                           "bvid": results[-1]["bvid"], "title": item["title"]})
            _write_json(LEDGER, ledger)
        except Exception as exc:  # noqa: BLE001 - 单集失败继续下一集
            print(f"[ep{item['ep']:02d}] ✗ {type(exc).__name__}: {exc}", flush=True)
            fails.append({"ep": item["ep"], "error": str(exc)})

    print(json.dumps({"published": results, "failed": fails},
                     ensure_ascii=False, indent=1), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
