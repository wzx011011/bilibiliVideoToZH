# ep16(三征播州)全节拍 Wan2.2 I2V 批量动态化驱动
# 每拍 5s/121帧/30步,动作提示词按画面内容逐拍手写(贴内容、中等幅度、镜头锁定)
# 断点续跑:已存在的输出直接跳过;单拍失败不阻断后续,结尾汇总
import json
import subprocess
import sys
import hashlib
from pathlib import Path

MANIFEST = Path("work/broll/ming-16-sanzheng2/manifest.json")
IMAGEDIR = Path("work/broll/ming-16-sanzheng2")
OUTDIR = Path("D:/mzx-ming16-i2v")

STYLE = ",保持原有绘画风格不变"

MOTION = {
    "s1_0": "土司首领微微抬头环视四周,衣袍与佩饰轻轻摆动,殿内烛火摇曳",
    "s1_1": "山间云雾缓缓流动,城头旗帜随风飘动,几只飞鸟掠过山谷",
    "s1_2": "叛军挥刀向前推进,浓烟滚滚升腾,火光跳动,逃难人群奔走",
    "s2_0": "将领抬手指向地图上的箭头,衣袖摆动,众人俯身议论,烛火摇曳",
    "s2_1": "战马昂首迈步向前,骑士高举铁刀,披风与大旗猎猎飘动",
    "s2_2": "各路军旗招展,大队人马沿山道鱼贯而行,尘土微微飞扬",
    "s3_0": "山顶云雾缭绕流动,石阶上人影点点上行,城头旗帜飘动",
    "s3_1": "士兵奋力向上攀爬,箭矢纷纷飞过城头,云梯轻晃,旗帜飘动",
    "s3_2": "明朝大将昂首挺胸目光如炬,盔甲缨穗与披风随风轻摆",
    "s4_0": "烛火轻轻摇曳,帐帘微动,案上卷轴一角被风掀动",
    "s4_1": "账房先生伏案疾书翻动账册,白银从箱中哗啦倾泻滑落",
    "s4_2": "灰尘在光柱中缓缓浮动,破旧门帘轻轻晃动",
    "s5_0": "官差在街市中穿行,商贩慌忙收拾货物,人群骚动避让",
    "s5_1": "人群挥臂呐喊涌动,摊位翻倒,杂物与纸片飞散",
    "s5_2": "珠宝银两从满箱倾泻流动,空箱中尘埃轻轻扬起",
    "s6_0": "辽东老将缓缓眯起双眼冷笑,披风轻摆,细雪飘落",
    "s6_1": "撤离的百姓牵牛拉车缓缓走出,炊烟将散,木门在风中轻晃",
    "s6_2": "山脊上雄鹰振翅欲飞,雪雾随风掠过,下方猛虎尾巴轻摆",
    "s7_0": "雪花纷纷飘落,人物双肩颤抖伏在墓前,白幡与衣袍随风飘动",
    "s7_1": "青年缓缓抬头目光坚毅,披风上雪粒滑落,身后雪片飘飞",
    "s7_2": "大军从山上俯冲而下冲锋喊杀,九部营中人仰马翻,雪雾飞扬",
    "s8_0": "秤杆缓缓倾斜下沉,钱币滚动滑落,尘埃微微扬起",
    "s8_1": "疲惫的官员们低头缓行,长袖拖曳,缓缓走过空荡的国库长廊",
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
