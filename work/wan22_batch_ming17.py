# ep17(晚明三大案)全节拍 Wan2.2 I2V 批量动态化驱动
# 每拍 5s/121帧/30步,动作提示词按画面内容逐拍手写(贴内容、中等幅度、镜头锁定)
# 断点续跑:已存在的输出直接跳过;单拍失败不阻断后续,结尾汇总
import json
import subprocess
import sys
import hashlib
from pathlib import Path

MANIFEST = Path("work/broll/ming-17-sanan/manifest.json")
IMAGEDIR = Path("work/broll/ming-17-sanan")
OUTDIR = Path("D:/mzx-ming17-i2v")

STYLE = ",画面人物保持静止不动,保持原有绘画风格不变"

# 配方纪律(2026-09-14 定):动作提示词只写无生命运动(风/雪/云/雾/火/烟/水/光影/
# 物体/旗帜/衣袍被动飘动),人物动作一律不写,避免 5B 模型人多动作时的融合崩坏
MOTION = {
    "s1_0": "烛火微摇,窗外落叶缓缓飘下,皇子长袖与衣袍轻轻摆动,光影缓缓流转",
    "s1_1": "殿门在夜风里吱呀晃动,尘土飞扬,灯笼火光摇曳,守卫衣袍被动翻飞",
    "s1_2": "灯笼火光摇曳,烟雾缓缓流动,官员们衣袖随风轻摆,光影明灭",
    "s2_0": "晨光渐亮,明黄龙袍衣袂轻扬,朝臣朝服随风微摆,旌旗轻轻飘动",
    "s2_1": "告示在风中哗哗颤动,纸页轻掀,人群衣袍轻摆,尘光缓缓浮动",
    "s2_2": "银锭银光流转,车幔轻扬,旗帜轻摆,尘埃微微飞扬",
    "s3_0": "烛火摇曳,帷帐轻轻晃动,太医们衣袍轻摆,熏香青烟缓缓流动",
    "s3_1": "红丸在盒中微微颤动,烛光闪烁,瓷器表面流光微动",
    "s3_2": "香炉青烟笔直升起后缓缓散开,黑幔轻垂微晃,空荡龙座前烛火忽明忽暗",
    "s4_0": "晨风吹动门幡与衣袍翻飞,尘埃在门洞光柱里飞扬,光影流转",
    "s4_1": "帷幔轻轻晃动,选侍衣袍披帛随风轻扬,殿内光线微微明灭",
    "s4_2": "晨光渐亮,龙袍衣袂轻扬,朝臣朝服随风微摆,丹陛旗幡轻飘",
    "s5_0": "卷轴纸页微微掀动,窗外河水缓缓流动,书生们衣袖随风轻摆",
    "s5_1": "殿内尘埃在光柱中缓缓浮动,两班朝服衣摆轻轻飘动,光影微移",
    "s5_2": "告示纸页被风吹得哗哗颤动,人群衣袍轻摆,尘光浮动",
    "s6_0": "木花卷落纷飞,木屑缓缓散落,烛火轻摇,案上小宫殿模型静止",
    "s6_1": "两人衣袂披帛随风轻摆,殿内光线渐暗,烛影摇曳",
    "s6_2": "奏章在案边越堆越高,木屑散落满案,尘光缓缓浮动",
    "s7_0": "刨花轻轻落下,奏章纸页微颤,烛火摇曳,光影缓缓流转",
    "s7_1": "帘幕轻轻晃动,朱笔在光柱里微微转动,尘埃缓缓浮动",
    "s7_2": "尘土飞扬,纸片在风中翻飞飘散,甲片轻颤,衣袍被动翻飞",
    "s8_0": "三座空荡龙座在雾气中若隐若现,雾气缓缓流淌,尘埃飘散",
    "s8_1": "烛火摇曳,少年衣袍随夜风轻摆,手中宫殿木模型静止,光影缓移",
    "s8_2": "乌云在宫城上空翻滚涌动,暮色中风声骤起,檐角铃铎轻晃",
}

FALLBACK = "画面中人物自然轻微活动,衣袍与旗帜随风轻摆,云雾缓缓流动"


def main():
    OUTDIR.mkdir(exist_ok=True)
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    beats = sorted(k for k, v in man.items() if isinstance(v, dict) and not k.endswith("_bg"))
    results = {}
    for b in beats:
        out = OUTDIR / f"{b}.mp4"
        if out.exists() and out.stat().st_size > 100_000:
            print(f"[skip] {b}", flush=True)
            results[b] = "skip"
            continue
        img = IMAGEDIR / f"{b}.png"
        if not img.exists():
            print(f"[MISSING-IMG] {b}", flush=True)
            results[b] = "noimg"
            continue
        prompt = MOTION.get(b, FALLBACK) + STYLE
        seed = int(hashlib.sha256(b.encode()).hexdigest()[:8], 16)
        cmd = [
            sys.executable, "work/wan22_i2v.py",
            "--image", str(img),
            "--prompt", prompt,
            "--length", "121", "--steps", "30",
            "--seed", str(seed),
            "--out", str(out),
            "--timeout", "7200",
        ]
        print(f"[run] {b}: {prompt[:36]}...", flush=True)
        r = subprocess.run(cmd)
        results[b] = "ok" if r.returncode == 0 else f"fail({r.returncode})"
    print("=== SUMMARY ===", flush=True)
    bad = [k for k, v in results.items() if v not in ("ok", "skip")]
    for k, v in results.items():
        print(f"  {k}: {v}")
    print(f"total={len(results)} bad={len(bad)} {bad}", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
