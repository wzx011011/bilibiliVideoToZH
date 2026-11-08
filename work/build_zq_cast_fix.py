# -*- coding: utf-8 -*-
"""东周线 zq-01~08 人名签补齐:从既有任务单中挑出主角镜头,加签条提示词重生成。"""
import json

CAST = {
 "zq-01-shewangjian": {"s2_0": "郑庄公", "s5_2": "周桓王", "s6_0": "熊通"},
 "zq-02-hengwen": {"s2_0": "管仲", "s5_2": "重耳", "s6_3": "晋文公"},
 "zq-03-mibing-wuyue": {"s4_0": "伍子胥", "s5_2": "伍子胥", "s6_2": "勾践",
                        "s6_3": "勾践", "s7_1": "西施", "s8_0": "范蠡"},
 "zq-04-kongzi": {"s2_0": "孔子", "s3_1": "孔子", "s5_1": "子路", "s7_1": "子路"},
 "zq-05-sanfen": {"s4_1": "程婴", "s6_1": "赵襄子", "s9_0": "豫让", "s9_1": "豫让"},
 "zq-06-weiguo": {"s2_0": "李悝", "s3_1": "西门豹", "s4_1": "吴起",
                  "s5_1": "孙膑", "s6_2": "庞涓", "s7_0": "商鞅"},
 "zq-07-baijia": {"s2_0": "孟子", "s3_0": "庄子", "s4_0": "墨子", "s4_1": "墨子"},
 "zq-08-jixia": {"s2_0": "孟子", "s2_2": "邹衍", "s9_0": "淳于髡"},
}

NOTEXT = "画面中不出现任何文字与水印。"
jobs = []
for slug, beats in CAST.items():
    num = slug.split("-")[1]
    src = json.load(open(f"work/zq_ep{num}_images.json", encoding="utf-8"))
    by_base = {j["out"].rsplit("/", 1)[-1]: j for j in src}
    for beat, name in beats.items():
        j = by_base.get(beat + ".png")
        if j is None:
            print("跳过(任务单无此项):", slug, beat)
            continue
        prompt = j["prompt"]
        if prompt.endswith(NOTEXT):
            prompt = prompt[: -len(NOTEXT)]
        prompt += (f" 画面中唯一允许的文字,是主角身旁写着「{name}」两个大字的竖式签条;"
                   f"除此之外不出现任何文字与水印。")
        jobs.append({"out": j["out"], "seed": 2100 + len(jobs), "size": "1536x864",
                     "preset": j.get("preset", "qwen21-turbo"),
                     "prompt": prompt, "cast": name})

json.dump(jobs, open("work/zq_cast_fix.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("人名签补齐任务:", len(jobs), "张")
