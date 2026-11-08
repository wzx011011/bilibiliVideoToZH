# 把 Wan2.2 I2V 片段(24fps/121帧)抽成渲染器可用的 15fps 帧文件夹。
# 帧预裁到舞台尺寸 1920x762(cover 居中),渲染端 Image.open 直接贴,无状态可断点。
# 用法: python work/ming16_extract_frames.py [--slug ming-16-sanzheng2] [--force]
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
# (片段源目录, 内容 slug)——slug 必须与 src/mzx_story/ming-*.json 文件名一致
SRC_DIRS = [(Path("D:/mzx-ming16-i2v"), "ming-16-sanzheng2")]
OUT_ROOT = ROOT / "work" / "mzx_story_i2v_frames"
DRAW_FPS = 15          # 渲染器 30fps 中每 2 帧绘制 1 帧
STAGE_W, STAGE_H = 1920, 762

# 帧保留完整画面(1280x704),cover/contain 两种舞台铺法由渲染端处理
VF = f"fps={DRAW_FPS}"


def extract_one(mp4: Path, outdir: Path) -> bool:
    tmp = outdir.parent / (outdir.name + ".tmp")
    if tmp.exists():
        subprocess.run(["rm", "-rf", str(tmp)], check=True)
    tmp.mkdir(parents=True)
    r = subprocess.run([
        str(FFMPEG), "-y", "-loglevel", "error", "-i", str(mp4),
        "-vf", VF, "-start_number", "0", str(tmp / "f%04d.png"),
    ])
    if r.returncode != 0 or not any(tmp.glob("f*.png")):
        subprocess.run(["rm", "-rf", str(tmp)])
        return False
    if outdir.exists():
        subprocess.run(["rm", "-rf", str(outdir)], check=True)
    tmp.rename(outdir)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=None, help="只处理该 slug(默认全部源目录)")
    ap.add_argument("--force", action="store_true", help="已存在的帧文件夹也重抽")
    args = ap.parse_args()

    ok = bad = skip = 0
    for src_dir, slug in SRC_DIRS:
        if args.slug and slug != args.slug:
            continue
        for mp4 in sorted(src_dir.glob("s*.mp4")):
            outdir = OUT_ROOT / slug / mp4.stem
            if outdir.exists() and any(outdir.glob("f*.png")) and not args.force:
                skip += 1
                continue
            if extract_one(mp4, outdir):
                n = len(list(outdir.glob("f*.png")))
                print(f"[ok] {slug}/{mp4.stem}: {n} 帧", flush=True)
                ok += 1
            else:
                print(f"[FAIL] {mp4}", flush=True)
                bad += 1
    print(f"完成: 新抽 {ok}, 跳过 {skip}, 失败 {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
