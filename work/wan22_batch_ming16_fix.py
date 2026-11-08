# ep16 质量返修批量:只重生成"人物动作导致崩坏"的节拍(2026-09-14 用户反馈
# "大部分很奇怪,质量不稳定"后的配方修正)。
# 配方纪律(对 ep17~24 一并生效):
#   动作提示词只允许无生命运动(风/雪/云/雾/火/烟/水/光影/物体/旗帜/衣袍被动飘动),
#   画面人物一律"保持静止",负面词追加反融合反变形;人群大动作场景宁退回静态图缓推。
# 技术参数由命令行透传(A/B 定案后填,如 --weight-dtype default --cfg 3.5 --vae-tile 512,128,16,16)
import hashlib
import subprocess
import sys
from pathlib import Path

MANIFEST = Path("work/broll/ming-16-sanzheng2/manifest.json")
IMAGEDIR = Path("work/broll/ming-16-sanzheng2")
OUTDIR = Path("D:/mzx-ming16-i2v")

NEG = ("色调艳丽，过曝，细节模糊不清，字幕，风格，作品，画作，画面，整体发灰，"
       "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
       "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
       "杂乱的背景，三条腿，背景人很多，倒着走，"
       "镜头推进，镜头拉远，镜头旋转，画面缩放，镜头晃动，"
       "人物融合，人物变形，肢体扭曲，面部变形，多余肢体，人群走动，人群奔跑，动作幅度过大")

STYLE = ",画面人物保持静止不动,保持原有绘画风格不变"

# 只重做这 15 拍(其余 9 拍已是环境动效,质量稳定,保留)
MOTION = {
    "s1_0": "殿内烛火轻轻摇曳,光影在墙上缓缓晃动,土司首领的衣袍与佩饰随风轻摆",
    "s1_2": "浓烟缓缓翻涌升腾,火光明灭跳动,战旗猎猎飘动,尘埃缓缓飞扬",
    "s2_0": "烛火轻轻摇曳,地图上的旗标随气流微颤,将领衣袍轻摆,众人衣袖随风微动",
    "s2_1": "披风与大旗猎猎飘动,马鬃和缨穗随风轻扬,尘埃微微飞扬",
    "s2_2": "山间云雾缓缓流动,军旗随风翻卷飘动,山道尘土轻轻扬起",
    "s3_1": "箭矢纷纷掠过城头,烟雾缓缓流动,云梯轻微晃动,旗帜猎猎飘动",
    "s3_2": "细雪纷纷飘落,大红披风随风轻摆,盔甲缨穗轻扬,呼出的白气缓缓飘散",
    "s4_1": "白银从箱中哗啦倾泻滑落,银光流动,烛火轻轻摇曳,账册纸页微微掀动",
    "s5_0": "纸片与杂物在风中缓缓飘散,尘土轻轻扬起,摊位布幔与旗帜轻轻摆动",
    "s5_1": "纸片与杂物在风中缓缓飘散,尘土轻轻扬起,摊位布幔翻动,尘埃飞扬",
    "s6_0": "细雪纷纷飘落,老将披风边缘随风轻摆,眉间须髯微微颤动,雪雾缓缓掠过",
    "s6_2": "雪雾随风掠过山脊,雄鹰羽毛微微颤动,下方草甸随风起伏",
    "s7_1": "披风上雪粒缓缓滑落,身后雪片纷纷飘飞,白幡随风轻摆",
    "s7_2": "雪雾漫天飞扬,九部营帐布幔剧烈翻卷,战旗猎猎作响,尘埃与雪粒横飞",
    "s8_1": "尘埃在斜射的光柱中缓缓浮动,官员们的长袖与衣袍下摆轻轻飘动",
}


def main():
    extra = sys.argv[1:]
    OUTDIR.mkdir(exist_ok=True)
    for beat, motion in sorted(MOTION.items()):
        out = OUTDIR / f"{beat}.mp4"
        bak = OUTDIR / f"{beat}_v1.mp4"
        if bak.exists() and out.exists() is False:
            pass
        if out.exists() and out.stat().st_size > 100_000:
            # 已有旧版:移成 _v1 留档,重生成新版(除非显式传 --keep)
            if "--keep" in extra:
                print(f"[keep] {beat}", flush=True)
                continue
            if not bak.exists():
                out.rename(bak)
                print(f"[bak] {beat} -> {bak.name}", flush=True)
        img = IMAGEDIR / f"{beat}.png"
        seed = int(hashlib.sha256(beat.encode()).hexdigest()[:8], 16)
        cmd = [sys.executable, "work/wan22_i2v.py",
               "--image", str(img), "--prompt", motion + STYLE, "--neg", NEG,
               "--length", "121", "--steps", "30", "--seed", str(seed),
               "--out", str(out), "--timeout", "7200"] + extra
        print(f"[run] {beat}: {motion[:30]}...", flush=True)
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print(f"[FAIL] {beat} rc={r.returncode}", flush=True)
    print("FIX-DONE", flush=True)


if __name__ == "__main__":
    main()
