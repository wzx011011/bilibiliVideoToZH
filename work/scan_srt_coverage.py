import re, glob, os, subprocess

ff = "work/video-tools/ffprobe.exe"

def sec(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))

for srt in sorted(glob.glob("work/ep-*/episode-*-asr.srt")):
    mp3 = srt.replace("-asr.srt", "-audio.mp3")
    if not os.path.exists(mp3):
        print(srt, "无音频")
        continue
    dur = float(subprocess.check_output(
        [ff, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp3],
        stderr=subprocess.DEVNULL).strip())
    txt = open(srt, encoding="utf-8").read()
    ends = [sec(m.group(1)) for m in re.finditer(r"--> (\d{2}:\d{2}:\d{2},\d{3})", txt)]
    span = max(ends) if ends else 0
    flag = "OK" if span > dur * 0.85 else "!!! 字幕只覆盖 {:.0f}%".format(span / dur * 100)
    print(f"{os.path.basename(srt)}: 音频{dur/60:.1f}min 字幕max到{span/60:.1f}min {flag}")
