"""访谈试点:解析 VTT 字幕 → 停顿交替切分说话人 → 挑参考音频和试点轮次。"""

import json
import re
import subprocess
from pathlib import Path

PILOT = Path(__file__).resolve().parent / "interview-pilot"
VTT = next((Path(__file__).resolve().parent.parent.parent / "youtube" / "geoffrey-hinton").glob("*.en-orig.vtt"))
AUDIO = PILOT / "hinton-full.wav"
FFMPEG = Path(__file__).resolve().parent.parent / "video-tools" / "ffmpeg.exe"

GAP_SWITCH = 0.9   # 音频静音超过此秒数视为换人
MAX_TURN = 25.0    # 参考片段上限


def parse_vtt(path: Path) -> list[tuple[float, float, str]]:
    tc = re.compile(r"(\d+):(\d+):(\d+)[.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[.](\d+)")
    segs: list[tuple[float, float, str]] = []
    start = end = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = tc.search(line)
        if m:
            g = [int(x) for x in m.groups()]
            start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            continue
        if start is None or not line.strip() or "<" in line or line.strip().upper() == "WEBVTT":
            continue
        text = line.strip()
        if not segs or segs[-1][2] != text:  # 跳过滚动重复行
            segs.append((start, end, text))
            start = None
    # 合并相邻同文本片段
    return segs


def detect_silences() -> list[tuple[float, float]]:
    """音频静音区间(说话人切换的物理依据)。"""
    out = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-i", str(AUDIO),
         "-af", "silencedetect=noise=-35dB:d=0.6", "-f", "null", "NUL"],
        capture_output=True, text=True).stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", out)]
    return list(zip(starts, ends[: len(starts)]))


def build_turns(segs, silences) -> list[dict]:
    """静音 >= GAP_SWITCH 处切换说话人(交替启发式)。"""
    switch_times = sorted(s for s, e in silences if e - s >= GAP_SWITCH)
    turns: list[dict] = []
    cur_spk = "A"
    prev_end = 0.0
    si = 0
    for s, e, t in segs:
        while si < len(switch_times) and switch_times[si] < s:
            si += 1
        # prev_end..s 之间经历的切换次数(偶数次则仍是同一人)
        n = sum(1 for sw in switch_times if prev_end <= sw < s)
        if n % 2 == 1:
            cur_spk = "B" if cur_spk == "A" else "A"
        prev_end = max(prev_end, e)
        if turns and turns[-1]["speaker"] == cur_spk:
            turns[-1]["end"] = max(turns[-1]["end"], e)
            turns[-1]["text"] += " " + t
        else:
            turns.append({"speaker": cur_spk, "start": s, "end": e, "text": t})
    return turns


def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).replace(" uh ", " ").replace(" um ", " ").strip()


def main() -> None:
    segs = parse_vtt(VTT)
    silences = detect_silences()
    turns = [t for t in build_turns(segs, silences) if (d := t["end"] - t["start"]) > 3.0]
    print(f"segments={len(segs)} turns={len(turns)} "
          f"A={sum(1 for t in turns if t['speaker']=='A')} B={sum(1 for t in turns if t['speaker']=='B')}")

    result = {"speakers": {}}
    for spk in ("A", "B"):
        cands = [t for t in turns if t["speaker"] == spk
                 and 8.0 <= t["end"] - t["start"] <= MAX_TURN]
        cands.sort(key=lambda t: t["end"] - t["start"], reverse=True)
        ref = cands[0]
        text = clean_text(ref["text"])
        result["speakers"][spk] = {
            "ref_start": round(ref["start"], 2), "ref_end": round(ref["end"], 2),
            "ref_dur": round(ref["end"] - ref["start"], 2),
            "ref_text": text, "zh_text": "",
        }
        print(f"spk {spk}: ref {ref['start']:.1f}-{ref['end']:.1f} "
              f"({ref['end']-ref['start']:.1f}s) {text[:90]}")

    # 试点朗读轮次:每位说话人前中段各取 2 条 5-15 秒的轮次
    pilots = []
    for spk in ("A", "B"):
        c = [t for t in turns if t["speaker"] == spk
             and 5.0 <= t["end"] - t["start"] <= 15.0 and 120 < t["start"] < 1500]
        c.sort(key=lambda t: t["end"] - t["start"], reverse=True)
        for t in c[:2]:
            pilots.append({"speaker": spk, "start": round(t["start"], 2),
                           "end": round(t["end"], 2),
                           "en_text": clean_text(t["text"]), "zh_text": ""})
    result["pilot_chunks"] = pilots
    for p in pilots:
        print(f"pilot {p['speaker']} {p['start']:.0f}-{p['end']:.0f}: {p['en_text'][:80]}")

    (PILOT / "pilot.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", PILOT / "pilot.json")


if __name__ == "__main__":
    main()
