# -*- coding: utf-8 -*-
"""AI 快讯栏目主题曲:ACE-Step 1.5 turbo 本地生成纯器乐候选(ComfyUI API)。

工作流照搬 ComfyUI 官方 blueprint「Text to Audio (ACE-Step 1.5)」:
UNETLoader → ModelSamplingAuraFlow(3) → KSampler(8 步 cfg1 euler/simple),
DualCLIPLoader(qwen 0.6b + 4b, type=ace) → TextEncodeAceStepAudio1.5,
负向 = ConditioningZeroOut,VAEDecodeAudio → SaveAudio。

用法(ComfyUI 已在 127.0.0.1:8188 起好):
  python work/ace_theme_gen.py <out_dir>
按文件存在性跳过,可断点续跑。
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

COMFY = "http://127.0.0.1:8188"
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

BASE_TAGS = ("instrumental, no vocals, news broadcast theme, daily tech news intro, "
             "orderly, steady, confident, authoritative, clean modern production, "
             "memorable four-note opening motif, ")
CANDIDATES = [
    ("a_piano_pulse", BASE_TAGS + "grand piano motif, soft synth pads, pulsing synth bass, light electronic percussion", 104, "D major", 11),
    ("b_strings_brass", BASE_TAGS + "orchestral strings, warm brass swell, timpani hits, cinematic broadcast news", 96, "C major", 22),
    ("c_synth_arp", BASE_TAGS + "bright synth arpeggio, analog pads, deep sub bass, minimal electronic beat, futuristic", 110, "A minor", 33),
    ("d_bell_ticker", BASE_TAGS + "glockenspiel and mallet ticker rhythm, piano chords, soft pads, morning news", 100, "F major", 44),
    ("e_piano_strings", BASE_TAGS + "piano and string ensemble, gentle pulse, subtle synth, calm but forward moving", 92, "G major", 55),
    ("f_corporate_tech", BASE_TAGS + "corporate technology, plucked synth, electric piano, crisp hi-hats, uplifting", 108, "E minor", 66),
]
SECONDS = 60


def post(path, body):
    req = urllib.request.Request(COMFY + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def get(path):
    return json.loads(urllib.request.urlopen(COMFY + path, timeout=60).read())


def workflow(name, tags, bpm, key, seed):
    return {
        "104": {"class_type": "UNETLoader", "inputs": {"unet_name": "acestep_v1.5_turbo.safetensors", "weight_dtype": "default"}},
        "78": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["104", 0], "shift": 3.0}},
        "105": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "qwen_0.6b_ace15.safetensors",
                                                            "clip_name2": "qwen_1.7b_ace15.safetensors",
                                                            "type": "ace", "device": "default"}},
        "106": {"class_type": "VAELoader", "inputs": {"vae_name": "ace_1.5_vae.safetensors"}},
        "94": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["105", 0], "tags": tags, "lyrics": "[Instrumental]", "seed": seed, "bpm": bpm,
            "duration": float(SECONDS), "timesignature": "4", "language": "en", "keyscale": key,
            "generate_audio_codes": True, "cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9, "top_k": 0, "min_p": 0.0}},
        "47": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["94", 0]}},
        "98": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": float(SECONDS), "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {"model": ["78", 0], "positive": ["94", 0], "negative": ["47", 0],
                                                    "latent_image": ["98", 0], "seed": seed, "steps": 8, "cfg": 1.0,
                                                    "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "18": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["3", 0], "vae": ["106", 0]}},
        "200": {"class_type": "SaveAudio", "inputs": {"audio": ["18", 0], "filename_prefix": f"ai_news_theme/{name}"}},
    }


def main():
    for name, tags, bpm, key, seed in CANDIDATES:
        dst = OUT / f"{name}.flac"
        if dst.exists():
            print("[skip]", dst.name)
            continue
        t0 = time.time()
        pid = post("/prompt", {"prompt": workflow(name, tags, bpm, key, seed)})["prompt_id"]
        while True:
            time.sleep(3)
            h = get(f"/history/{pid}")
            if pid in h:
                st = h[pid].get("status", {})
                if st.get("status_str") == "error":
                    raise SystemExit(f"[error] {name}: {json.dumps(st.get('messages'))[:800]}")
                outs = [a for o in h[pid]["outputs"].values() for a in o.get("audio", [])]
                if outs:
                    a = outs[0]
                    q = urllib.parse.urlencode({"filename": a["filename"], "subfolder": a["subfolder"], "type": a["type"]})
                    dst.write_bytes(urllib.request.urlopen(f"{COMFY}/view?{q}", timeout=120).read())
                    print(f"[ok] {dst.name} {time.time() - t0:.0f}s", flush=True)
                    break
            if time.time() - t0 > 1800:
                raise SystemExit(f"[timeout] {name}")


if __name__ == "__main__":
    main()
