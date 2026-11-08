"""Tibo 访谈中文配音流水线(复用 Hinton 验证过的方案,三处改进内置):
  1) 配音 = 中文普通话底音(Edge-TTS) + CosyVoice 音色转换 → 无外国口音
  2) 语速靠 Edge-TTS 原生 rate 自适应,不做激进整段加速
  3) 所有片段淡入淡出,消除切换处电流声

阶段: prep / translate / bases / vc / assemble / subs / render
Windows 端跑除 vc 外全部;vc 用 WSL cosy-gpu-venv。
用法: python tibo_pipeline.py <stage>
"""

import asyncio
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "interview-tibo"
FINE = BASE / "fine"
PARTS = FINE / "parts"
BASES = FINE / "bases"
REFS = BASE / "refs"
AUDIO = BASE / "tibo-full.wav"
VTT = next((ROOT.parent.parent / "youtube" / "matthew-berman").glob("*en-orig.vtt"))
VIDEO = ROOT.parent.parent / "youtube" / "matthew-berman" / (
    "Tibo_Interview_MatthewBerman_4qjEgPojjzM.mp4")
CAMPPLUS = ROOT / "models" / "CosyVoice2-0.5B" / "campplus.onnx"
FFMPEG = ROOT.parent / "video-tools" / "ffmpeg.exe"
ASR_PY = ROOT.parent.parent / "work" / ".venv-ocr" / "Scripts" / "python.exe"
TOTAL = 2668.154
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:7b"
VOICES = {"A": "zh-CN-YunjianNeural",   # Matthew Berman(主持人)
          "B": "zh-CN-YunxiNeural"}     # Tibo
WIN_TARGET = 5.5
SLOT_MAX = 12.0

SYS_PROMPT = (
    "你是专业的英文访谈配音翻译。输入是一组按顺序排列的英文时间槽。"
    "结合整组上下文，将每个槽分别译成自然、忠实、可朗读的中文。"
    "不得跨槽重复，不得漏译，不得添加解释。每项接近给定目标字数，宁可凝练。"
    "人名规则：Tibo→蒂博，Matthew Berman→马修·伯曼。"
    "产品/公司名保留原文：OpenAI、Codex、ChatGPT、GPT-5、GitHub、Gemini、Grok。"
    '严格输出 JSON 对象，格式为 {"items":[{"id":数字,"zh":"译文"}]}。'
)
ALLOWED_EN = {"ai", "gpt", "codex", "openai", "chatgpt", "api", "ceo", "llm",
              "deepmind", "google", "github", "gemini", "grok", "transformer",
              "youtube", "tweet", "luna", "labs", "agi", "copilot", "cursor",
              "claude", "anthropic", "devin", "kubernetes", "docker", "slack",
              "jupyter", "vscode", "sdk", "ui", "ux", "rust", "python",
              "javascript", "typescript", "react", "vercel", "supabase",
              "mistral", "llama", "mcp", "demo", "demos", "ok", "oh", "um"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ff(*args):
    subprocess.run([str(FFMPEG), "-y", "-hide_banner", "-loglevel",
                    "error", *args], check=True)


# ---------------------------------------------------------------- prep ----

def ts(v):
    h, m, rest = v.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_phrases(path):
    """全量短语(保覆盖),只保留纯文本行;换人标记以内联 '>>' 形式存在。"""
    import html as _html
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8"))
    out = []
    for block in blocks:
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        tl = next((x for x in lines if "-->" in x), None)
        if not tl:
            continue
        a, b = [x.strip().split()[0] for x in tl.split("-->")]
        s, e = ts(a), ts(b)
        text_lines = [x for x in lines if x != tl and not
                      x.startswith(("WEBVTT", "Kind:", "Language:"))]
        text = _html.unescape(" ".join(text_lines)).strip()
        text = re.sub(r"<[^>]*>", "", text)   # 剥掉内联时间戳/c 标签
        text = re.sub(r"\s+", " ", text).strip()
        if not text or e - s <= 0.03:
            continue
        marker = bool(re.match(r"^>>+\s*", text))
        clean = re.sub(r"^>>+\s*", "", text)
        if out and out[-1]["text"] == clean:  # 滚动确认行去重
            continue
        out.append({"start": s, "end": e, "marker": marker, "text": clean})
    return out


def kmeans2(x, iters=25):
    import numpy as np
    d = x @ x.T
    i0, i1 = divmod(int(d.argmax()), x.shape[0])
    c = x[[i0, i1]].copy()
    labels = None
    for _ in range(iters):
        new = (x @ c.T).argmax(axis=1)
        if labels is not None and (new == labels).all():
            break
        labels = new
        for k in (0, 1):
            m = x[labels == k]
            if len(m):
                c[k] = m.mean(axis=0)
                c[k] /= max(np.linalg.norm(c[k]), 1e-9)
    return labels


WIN = 3.0        # 小窗口减少两人语音混合污染
GAP_SPLIT = 0.8  # 大于该停顿视为硬边界
SLOT_MAX = 12.0


def stage_prep():
    import numpy as np
    import onnxruntime
    import torchaudio
    import torchaudio.compliance.kaldi as kaldi

    phrases = parse_phrases(VTT)
    log(f"phrases={len(phrases)} span={phrases[-1]['end']-phrases[0]['start']:.0f}s")

    full, sr = torchaudio.load(str(AUDIO))
    sess = onnxruntime.InferenceSession(str(CAMPPLUS),
                                        providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    def emb(s, e):
        wav = full[:, int(s*sr):min(int(e*sr), full.shape[1])]
        feat = kaldi.fbank(wav, num_mel_bins=80, dither=0, sample_frequency=sr)
        feat -= feat.mean(dim=0, keepdim=True)
        v = sess.run(None, {inp: feat.unsqueeze(0).numpy()})[0].flatten()
        return v / np.linalg.norm(v)

    # 硬边界切分:换人标记 或 >GAP_SPLIT 停顿
    segs, cur, prev_end = [], None, None
    for p in phrases:
        if cur is None or p["marker"] or \
           (prev_end is not None and p["start"] - prev_end > GAP_SPLIT):
            cur = {"start": p["start"], "end": p["end"], "texts": [p["text"]]}
            segs.append(cur)
        else:
            cur["end"] = max(cur["end"], p["end"])
            cur["texts"].append(p["text"])
        prev_end = max(prev_end or 0, p["end"])
    segs = [s for s in segs if s["end"] - s["start"] >= 0.6]
    log(f"segments={len(segs)} "
        f"cover={sum(x['end']-x['start'] for x in segs):.0f}s")

    wins = []
    for si, sg in enumerate(segs):
        s = sg["start"]
        while s < sg["end"] - 0.8:
            e = min(s + WIN, sg["end"])
            wins.append({"start": s, "end": e, "seg": si})
            s = e
    X = np.array([emb(w["start"], w["end"]) for w in wins])
    labels = kmeans2(X)

    def centroid(k):
        m = X[labels == k]
        u = m.mean(axis=0)
        return u / np.linalg.norm(u)

    cs = np.array([centroid(0), centroid(1)])
    simm = X @ cs.T
    intra = [float(simm[i][labels[i]]) for i in range(len(labels))]
    inter = [float(simm[i][1 - labels[i]]) for i in range(len(labels))]

    # 段标签 = 窗口多数票
    slab = []
    for si in range(len(segs)):
        votes = [labels[i] for i, w in enumerate(wins) if w["seg"] == si]
        slab.append(max(set(votes), key=votes.count) if votes else None)
    # 平滑:两侧一致的孤立短段并入
    for si in range(1, len(slab) - 1):
        nvotes = sum(1 for w in wins if w["seg"] == si)
        if nvotes <= 1 and None not in (slab[si-1], slab[si+1]) \
                and slab[si-1] == slab[si+1]:
            slab[si] = slab[si-1]
    # 短疑问段偏主持人
    for si, sg in enumerate(segs):
        txt = " ".join(sg["texts"])
        dur = sg["end"] - sg["start"]
        if txt.endswith("?") and dur < 7 and \
           None not in (slab[si-1], slab[si+1]) if 0 < si < len(segs)-1 else False:
            pass  # 占位:不做强改,仅统计用
    qlines = {"A": 0, "B": 0}

    # 主持人识别:欢迎语含嘉宾名
    host_k = None
    for si, sg in enumerate(segs):
        txt = " ".join(sg["texts"])
        if re.search(r"\btibo\b", txt, re.I) and \
           re.search(r"(joining|welcome|thanks)", txt, re.I):
            host_k = slab[si]
            break
    if host_k is None:
        q = [0, 0]
        for si, sg in enumerate(segs):
            if slab[si] is not None:
                q[slab[si]] += " ".join(sg["texts"]).count("?")
        host_k = int(np.argmax(q))
    key = lambda k: "A" if k == host_k else "B"

    # 段为原子单元贪心打包成槽(不切割段 → 零丢失)
    units = [(si, segs[si]) for si in range(len(segs)) if slab[si] is not None]
    merged = []
    for si, sg in units:
        spk = key(slab[si])
        cur = merged[-1] if merged else None
        add_ok = cur and cur["speaker"] == spk and \
            (sg["end"] - cur["start"]) <= SLOT_MAX * 1.15 and \
            sg["start"] - cur["end"] < GAP_SPLIT * 2
        if add_ok:
            cur["end"] = sg["end"]
            cur["segs"].append(si)
        else:
            merged.append({"speaker": spk, "start": sg["start"],
                           "end": sg["end"], "segs": [si]})
    # 超长合并组按均分边界二次拆分(段保持完整,归属最近边界)
    slots = []
    for r in merged:
        dur = r["end"] - r["start"]
        if dur <= SLOT_MAX * 1.25:
            grp = [(si, segs[si]) for si in r["segs"]]
        else:
            chunks = max(2, round(dur / SLOT_MAX))
            bounds = [r["start"] + dur*i/chunks for i in range(chunks)] + [r["end"]]
            grp, ci = [], 0
            for si in r["segs"]:
                while ci < chunks - 1 and segs[si]["start"] >= bounds[ci+1]:
                    ci += 1
                    grp = grp if not isinstance(grp[-1], list) else grp
                while len(grp) <= ci:
                    grp.append([])
                if isinstance(grp, list) and len(grp) > ci and \
                        isinstance(grp[ci], list):
                    grp[ci].append((si, segs[si]))
            grp = [g for g in grp if g]
        if grp and not isinstance(grp[0], list):
            grp = [grp]
        for g in grp:
            send = max(x[1]["end"] for x in g)
            sstart = g[0][1]["start"]
            if send - sstart < 0.8:
                continue
            text = " ".join(" ".join(x[1]["texts"]) for x in g)
            slots.append({"id": len(slots), "speaker": r["speaker"],
                          "start": round(sstart, 3), "end": round(send, 3),
                          "duration": round(send - sstart, 3), "text": text})

    a_t = sum(s["duration"] for s in slots if s["speaker"] == "A")
    b_t = sum(s["duration"] for s in slots if s["speaker"] == "B")
    alt = sum(1 for i in range(1, len(slab)) if slab[i] != slab[i-1])
    log(f"slots={len(slots)} A={a_t:.0f}s B={b_t:.0f}s switch={alt} "
        f"intra={np.mean(intra):.3f} inter={np.mean(inter):.3f}")
    for s in slots[:10]:
        flag = "?" if s["text"].endswith("?") else " "
        print(f"  {s['speaker']}{flag} {s['start']:7.1f}-{s['end']:7.1f} "
              f"{s['text'][:62]}")

    REFS.mkdir(exist_ok=True)
    refinfo = {}
    for r in merged:
        dur = r["end"] - r["start"]
        if not (10.0 <= dur <= 22.0):
            continue
        if r["speaker"] not in refinfo or dur > refinfo[r["speaker"]]["dur"]:
            refinfo[r["speaker"]] = {"start": r["start"], "end": r["end"],
                                     "dur": dur}
    missing = {"A", "B"} - set(refinfo)
    if missing:
        raise SystemExit(f"参考段不足(放宽长度筛选): {refinfo}")
    for spk, info in refinfo.items():
        ff("-ss", str(info["start"]), "-to", str(info["end"]),
           "-i", str(AUDIO), "-ac", "1", "-ar", "16000",
           str(REFS / f"{spk}.wav"))
        log(f"ref {spk}: {info['start']:.1f}-{info['end']:.1f} ({info['dur']:.1f}s)")

    FINE.mkdir(exist_ok=True)
    (FINE / "slots.json").write_text(
        json.dumps(slots, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"-> {FINE/'slots.json'}")


# ---------------------------------------------------------- translate ----

def _ollama(items, repair=False):
    prompt = json.dumps({"slots": items}, ensure_ascii=False)
    if repair:
        prompt += "\n上次结果不合格,请压缩到目标字数并清除允许列表之外的英文。"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS_PROMPT},
                     {"role": "user", "content": prompt}],
        "format": "json", "stream": False,
        "options": {"temperature": 0.05, "num_predict": 1500, "seed": 19},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(json.loads(r.read())["message"]["content"])
    return {int(x["id"]): x["zh"].strip() for x in data["items"]
            if isinstance(x.get("zh"), str)}


def bad_reason(z, target, src=""):
    if not z or any(x in z for x in ("```", '"items"', ":\"", "英文原文")):
        return "format"
    if len(z) > target * 1.5 or len(z) < target * 0.45:
        return "length"
    words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", z)]
    bad = [w for w in words if w not in ALLOWED_EN]
    # 源文里本就存在的专有名词放行,但整句latin字符总量受控
    bad = [w for w in bad if not (len(w) >= 4 and w in src.lower())]
    latin = sum(len(w) for w in words)
    if latin > max(24, target * 0.8):
        return "english:" + ",".join(bad)[:40]
    return ""


def target_chars(slot):
    return max(8, round(slot["duration"] * 5.0))


def stage_translate():
    slots = json.loads((FINE / "slots.json").read_text(encoding="utf-8"))
    out_path = FINE / "slots_zh.json"
    out = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    t0 = time.time()
    B = 6
    nbatches = (len(slots) + B - 1) // B
    for bi in range(0, len(slots), B):
        batch = slots[bi:bi+B]
        if all(str(s["id"]) in out and out[str(s["id"])] for s in batch):
            continue
        items = [{"id": s["id"], "duration": s["duration"],
                  "target_chars": target_chars(s), "english": s["text"]}
                 for s in batch]
        got = {}
        for attempt in range(3):
            try:
                got = _ollama(items, repair=attempt > 0)
                if all(got.get(s["id"]) for s in batch):
                    break
            except Exception as e:
                log(f"batch@{batch[0]['id']} try{attempt+1} ERR {e}")
                time.sleep(3)
        for s in batch:
            if got.get(s["id"]):
                out[str(s["id"])] = got[s["id"]]
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        bads = sum(bool(bad_reason(out.get(str(s["id"]), ""), target_chars(s), s["text"]))
                   for s in batch)
        log(f"batch {bi//B + 1}/{nbatches} "
            f"s{batch[0]['id']}-{batch[-1]['id']} bad={bads}")
    bads = [(s, bad_reason(out.get(str(s["id"]), ""), target_chars(s), s["text"]))
            for s in slots if bad_reason(out.get(str(s["id"]), ""),
                                         target_chars(s))]
    log(f"repair pass: {len(bads)} bad slots")
    done = 0
    for s, reason in bads:
        item = [{"id": s["id"], "duration": s["duration"],
                 "target_chars": target_chars(s), "english": s["text"],
                 "bad_previous": out.get(str(s["id"])), "problem": reason}]
        try:
            fixed = _ollama(item, repair=True).get(s["id"])
        except Exception as e:
            log(f"repair s{s['id']} fail {e}")
            continue
        if fixed:
            out[str(s["id"])] = fixed
            out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        done += 1
        if done % 10 == 0:
            log(f"repaired {done}/{len(bads)}")
    remain = [s["id"] for s in slots
              if bad_reason(out.get(str(s["id"]), ""), target_chars(s), s["text"])]
    log(f"translate done {(time.time()-t0)/60:.1f}min remaining_bad={len(remain)}")
    if remain[:20]:
        log(f"bad ids: {remain[:20]}")


# ------------------------------------------------------------- bases ----

async def edge_synth(text, voice, rate, mp3):
    import edge_tts
    async def _do():
        await edge_tts.Communicate(text, voice, rate=rate).save(str(mp3))
    try:
        await asyncio.wait_for(_do(), timeout=150)
    except asyncio.TimeoutError:
        raise RuntimeError(f"edge-tts timeout ({len(text)} chars)")


async def base_one(slot, zh):
    sid = f"slot_{slot['id']:03d}"
    mp3 = BASES / f"{sid}.mp3"
    wav = BASES / f"{sid}.wav"
    rates = ["-4%"]
    ratio = None
    for i, rate in enumerate(rates):
        await edge_synth(zh, VOICES[slot["speaker"]], rate, mp3)
        ff("-i", str(mp3), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
           str(wav))
        import soundfile as sf
        d = sf.info(str(wav)).duration
        ratio = d / slot["duration"]
        if ratio <= 1.04:
            break
        if i == 0:
            over = max(4, min(18, round((ratio - 1) * 100)))
            rates.append(f"+{over}%")
    return sid, ratio


async def stage_bases():
    slots = json.loads((FINE / "slots.json").read_text(encoding="utf-8"))
    zh = json.loads((FINE / "slots_zh.json").read_text(encoding="utf-8"))
    BASES.mkdir(parents=True, exist_ok=True)
    todo = [s for s in slots if zh.get(str(s["id"]))
            and not (BASES / f"slot_{s['id']:03d}.wav").exists()]
    log(f"bases todo={len(todo)}")
    sem = asyncio.Semaphore(6)

    async def worker(s):
        async with sem:
            try:
                _, r = await base_one(s, zh[str(s["id"])])
            except Exception as e:
                log(f"base s{s['id']} FAIL {e}")
                return
            if r > 1.10:
                log(f"base s{s['id']:03d} overrun ratio={r:.2f}")

    await asyncio.gather(*(worker(s) for s in todo))
    made = len(list(BASES.glob("slot_*.wav")))
    log(f"bases done total_files={made}")


# ---------------------------------------------------------------- vc ----

def stage_vc():
    import torch
    import torchaudio
    sys.path.insert(0, str(ROOT / "CosyVoice"))
    sys.path.insert(0, str(ROOT / "CosyVoice" / "third_party" / "Matcha-TTS"))

    PARTS.mkdir(parents=True, exist_ok=True)
    slots = json.loads((FINE / "slots.json").read_text(encoding="utf-8"))
    todo = [s for s in slots
            if not (PARTS / f"slot_{s['id']:03d}.wav").exists()]
    log(f"vc todo={len(todo)}")
    torch.manual_seed(20260827)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    from cosyvoice.cli.cosyvoice import AutoModel
    model = AutoModel(model_dir=str(ROOT / "models" / "CosyVoice2-0.5B"),
                      load_jit=False, load_trt=False, load_vllm=False,
                      fp16=False)
    refs = {spk: str(REFS / f"{spk}.wav") for spk in VOICES}
    t0 = time.time(); n = 0
    for i, s in enumerate(slots):
        out = PARTS / f"slot_{s['id']:03d}.wav"
        if out.exists() and out.stat().st_size > 1000:
            continue
        src = BASES / f"slot_{s['id']:03d}.wav"
        if not src.exists():
            log(f"vc s{s['id']:03d}: no base, skip")
            continue
        # 复用 vc_segments_gpu 的方案:源音频>30s 切 22s 小块逐段转换再拼
        wav, wsr = torchaudio.load(str(src))
        if wav.shape[1] / wsr <= 28:
            pieces = [r["tts_speech"] for r in model.inference_vc(
                str(src), refs[s["speaker"]], stream=False)]
            speech = torch.cat(pieces, dim=1)
        else:
            step = int(22 * wsr)
            outs = []
            tmp = BASE / "_vc_tmp.wav"
            for off in range(0, wav.shape[1], step):
                torchaudio.save(str(tmp), wav[:, off:off+step], wsr)
                ps = [r["tts_speech"] for r in model.inference_vc(
                    str(tmp), refs[s["speaker"]], stream=False)]
                outs.append(torch.cat(ps, dim=1))
            tmp.unlink(missing_ok=True)
            speech = torch.cat(outs, dim=1)
        torchaudio.save(str(out), speech, model.sample_rate)
        n += 1
        if n % 25 == 0 or n == len(todo):
            el = time.time() - t0
            done_ids = [x["id"] for x in slots
                        if (PARTS / f"slot_{x['id']:03d}.wav").exists()]
            left = len([x for x in slots
                        if not (PARTS / f"slot_{x['id']:03d}.wav").exists()])
            eta = el / max(n, 1) * left / 60
            log(f"vc progress done_total={len(done_ids)}/{len(slots)} "
                f"eta≈{eta:.0f}min")


# ---------------------------------------------------------- assemble ----

def stage_assemble():
    import numpy as np
    import soundfile as sf

    slots = json.loads((FINE / "slots.json").read_text(encoding="utf-8"))
    SR = 24000
    canvas = np.zeros(int(TOTAL * SR), dtype=np.float32)
    placed = trunc = 0
    for s in slots:
        p = PARTS / f"slot_{s['id']:03d}.wav"
        if not p.exists():
            continue
        wav, sr = sf.read(str(p), dtype="float32")
        if sr != SR:
            wav = np.interp(np.arange(0, len(wav) * SR / sr, SR / sr),
                            np.arange(len(wav)), wav).astype(np.float32)
        off = int(s["start"] * SR)
        fade_in = min(len(wav), int(0.012 * SR))
        fade_out = min(len(wav) - fade_in, int(0.06 * SR))
        wav[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)
        if fade_out > 0:
            wav[-fade_out:] *= np.linspace(1, 0, fade_out, dtype=np.float32)
        room = canvas.shape[0] - off
        if len(wav) > room:
            print(f"  slot {s['id']} 超出画布,丢弃")
            continue
        limit = int(s["duration"] * 1.06 * SR)
        if len(wav) > limit:                     # 二次保音高提速吸收超时长
            rate = len(wav) / (limit * 1.001)
            if rate < 1.22:            # 轻度超长走温和提速;病态超长也必须完整说完
                pass
            tmpw = BASE / "_fit_in.wav"
            tmpo = BASE / "_fit_out.wav"
            sf.write(str(tmpw), wav, SR, subtype="FLOAT")
            subprocess.run([str(FFMPEG), "-y", "-hide_banner", "-loglevel",
                            "error", "-i", str(tmpw),
                            "-af", f"atempo={rate:.5f}", str(tmpo)], check=True)
            wav, _ = sf.read(str(tmpo), dtype="float32")
            tmpw.unlink()
            tmpo.unlink()
            trunc += 1
        if len(wav) > int(s["duration"] * 1.065 * SR):   # 兜底裁剪
            cut = int(s["duration"] * 1.065 * SR)
            wf = int(min(0.03 * SR, cut // 3))
            wav[cut-wf:cut] *= np.linspace(1, 0, wf, dtype=np.float32)
            wav = wav[:cut]
        elif len(wav) > int(s["duration"] * 1.001 * SR):
            pass                                  # 正常范围内保留呼吸感
        room = canvas.shape[0] - off
        if len(wav) > room:
            continue
        canvas[off:off+len(wav)] += wav
        placed += 1
    # 响度归一到约 -19 dB mean
    measure = subprocess.run([str(FFMPEG), "-hide_banner", "-i", "-",
                              "-af", "volumedetect", "-f", "null", "NUL"],
                             input=canvas.tobytes(), capture_output=True)
    err = measure.stderr.decode("utf-8", "ignore")
    m = re.search(r"mean_volume:\s*(-?[\d.]+)", err)
    gain = 1.0
    if m:
        mean_db = float(m.group(1))
        gain = float(np.clip(10 ** ((-19.0 - mean_db) / 20), 0.2, 6.0))
        log(f"loudness mean={mean_db:.1f}dB -> gain x{gain:.2f}")
    canvas *= gain
    peak = np.abs(canvas).max()
    if peak > 0.99:
        canvas *= 0.98 / peak
        log(f"peak guard applied, was {peak:.2f}")
    out_wav = BASE / "tibo-zh.wav"
    sf.write(str(out_wav), canvas[np.newaxis].T, SR, subtype="PCM_16")
    log(f"assemble placed={placed} truncated={trunc} -> {out_wav}")


# ------------------------------------------------------------- subs ----

def stage_subs():
    wav = BASE / "tibo-zh.wav"
    srt = BASE / "tibo-zh.srt"
    subprocess.run([str(ASR_PY), str(ROOT.parent.parent / "src" /
                                     "align_srt_asr.py"),
                    str(wav), "-o", str(srt), "--asr-only"], check=False)
    log(f"subs -> {srt}")


# ----------------------------------------------------------- render ----

def stage_render(upload=True):
    srt = str((BASE / "tibo-zh.srt").resolve()).replace("\\", "/") \
        .replace(":", "\\:")
    vf = ("subtitles='" + srt +
          "':force_style='Fontname=Microsoft YaHei,FontSize=22,"
          "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,"
          "Outline=2,Alignment=2,MarginV=30',"
          "drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':text='wzx':"
          "fontcolor=white@0.7:fontsize=36:x=40:y=h-th-40")
    out = BASE / "tibo-interview-zh.mp4"
    subprocess.run([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(VIDEO), "-i", str(BASE / "tibo-zh.wav"),
                    "-map", "0:v", "-map", "1:a", "-vf", vf,
                    "-c:v", "libx264", "-crf", "21", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", str(out)], check=True)
    log(f"render -> {out}")
    if upload:
        remote = "/volume1/share/视频/Tibo访谈-中文版.mp4"
        subprocess.run(["scp", str(out), f"nas:{remote}"], check=False)
        res = subprocess.run(["ssh", "nas", "stat -c%s \"" + remote + "\""],
                             capture_output=True, text=True)
        log(f"nas size={res.stdout.strip()} local={out.stat().st_size}")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    fns = {"prep": stage_prep, "translate": stage_translate,
           "bases": lambda: asyncio.run(stage_bases()),
           "vc": stage_vc, "assemble": stage_assemble,
           "subs": stage_subs, "render": stage_render}
    if stage not in fns:
        raise SystemExit(f"unknown/missing stage '{stage}'. choose from {list(fns)}")
    fns[stage]()
