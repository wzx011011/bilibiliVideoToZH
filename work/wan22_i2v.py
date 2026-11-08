# -*- coding: utf-8 -*-
"""Wan2.2 TI2V-5B 图生视频试稿:一张 broll 静图 -> 一段真实连续动作(走本机 ComfyUI)。

用法:
  python work/wan22_i2v.py --image work/broll/ming-16-sanzheng2/s1_0.png \
      --prompt "..." [--length 41] [--steps 30] [--out out.mp4] [--timeout 3600]
官方基线:1280x704 @24fps,steps 30 cfg 5 uni_pc/simple,length 121=5s(试稿默认 41≈1.7s)。
"""
import argparse
import json
import sys
import time
import urllib.request
import uuid

ap = argparse.ArgumentParser()
ap.add_argument("--image", required=True)
ap.add_argument("--prompt", required=True)
ap.add_argument("--length", type=int, default=41)
ap.add_argument("--steps", type=int, default=30)
ap.add_argument("--width", type=int, default=1280)
ap.add_argument("--height", type=int, default=704)
ap.add_argument("--seed", type=int, default=20260912)
ap.add_argument("--out", default="")
ap.add_argument("--timeout", type=int, default=3600)
ap.add_argument("--neg", default="", help="覆盖负面提示词(默认官方负面含'静态'会压制动作)")
ap.add_argument("--weight-dtype", default="fp8_e4m3fn",
                help="UNETLoader 权重精度:fp8_e4m3fn(快)或 default(=fp16 全精度,更稳)")
ap.add_argument("--cfg", type=float, default=5.0)
ap.add_argument("--vae-tile", default="256,64,8,8",
                help="VAEDecodeTiled tile,overlap,temporal_size,temporal_overlap")
args = ap.parse_args()

HOST = "http://127.0.0.1:8188"
CID = str(uuid.uuid4())
# 本机 ComfyUI 必须直连:urllib 默认吃 http_proxy 环境变量,请求会被系统代理
# (Clash)劫持,高峰期连接挂住数十分钟(2026-09-13 实测),ProxyHandler({}) 强制直连。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
NEG = ("色调艳丽，过曝，细节模糊不清，字幕，风格，作品，画作，画面，整体发灰，"
       "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
       "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
       "杂乱的背景，三条腿，背景人很多，倒着走，"
       "镜头推进，镜头拉远，镜头旋转，画面缩放，镜头晃动，"
       "人物融合，人物变形，肢体扭曲，面部变形，多余肢体，动作幅度过大")


def post(path, data=None, files=None, raw=None):
    url = HOST + path
    if files:
        boundary = "----zk" + CID
        body = b""
        for k, v in (data or {}).items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        fn, fb = files
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                 f'filename="{fn}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + fb + \
                f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(raw or data).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=120) as r:
        return json.loads(r.read())


def get(path):
    last = None
    for _ in range(30):  # 采样高峰期 HTTP 可能暂时无响应,重试 30 次
        try:
            with _OPENER.open(HOST + path, timeout=45) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(15)
    raise last


# 1. 上传起始帧
img_bytes = open(args.image, "rb").read()
up = post("/upload/image", data={"overwrite": "true"},
          files=(args.image.replace("\\", "/").split("/")[-1], img_bytes))
print("[1/3] 起始帧已上传:", up["name"], flush=True)

# 2. 组工作流并提交
graph = {
    "37": {"class_type": "UNETLoader", "inputs": {
        "unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": args.weight_dtype}},
    "38": {"class_type": "CLIPLoader", "inputs": {
        "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
    "39": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": args.prompt}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": args.neg or NEG}},
    "57": {"class_type": "LoadImage", "inputs": {"image": up["name"]}},
    "22": {"class_type": "Wan22ImageToVideoLatent", "inputs": {
        "width": args.width, "height": args.height, "length": args.length, "batch_size": 1,
        "vae": ["39", 0], "start_image": ["57", 0]}},
    "3": {"class_type": "KSampler", "inputs": {
        "seed": args.seed, "steps": args.steps, "cfg": args.cfg, "sampler_name": "uni_pc",
        "scheduler": "simple", "denoise": 1.0, "model": ["37", 0],
        "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["22", 0]}},
    "8": {"class_type": "VAEDecodeTiled", "inputs": {
        "samples": ["3", 0], "vae": ["39", 0],
        **dict(zip(("tile_size", "overlap", "temporal_size", "temporal_overlap"),
                   (int(x) for x in args.vae_tile.split(","))))}},
    "cv": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": 24}},
    "save": {"class_type": "SaveVideo", "inputs": {
        "video": ["cv", 0], "filename_prefix": "wan22_i2v", "format": "auto"}},
}
r = post("/prompt", raw={"prompt": graph, "client_id": CID})
pid = r["prompt_id"]
print("[2/3] 已提交 prompt_id:", pid, flush=True)

# 3. 轮询
t0 = time.time()
while True:
    time.sleep(10)
    h = json.loads(get(f"/history/{pid}"))
    if pid in h:
        st = h[pid].get("status", {})
        if st.get("status_str") == "error":
            print("FAILED:", json.dumps(st.get("messages", []))[:2000], flush=True)
            sys.exit(1)
        outs = h[pid].get("outputs", {})
        if outs:
            for node_out in outs.values():
                for key in ("images", "videos", "gifs"):
                    for f in node_out.get(key, []) or []:
                        q = f"&subfolder={f.get('subfolder', '')}" if f.get("subfolder") else ""
                        data = get(f"/view?filename={f['filename']}&type={f.get('type', 'output')}{q}")
                        out = args.out or f"D:/{f['filename']}"
                        open(out, "wb").write(data)
                        dt = time.time() - t0
                        print(f"[3/3] 完成 {args.length}帧/{args.steps}步 用时{dt:.0f}s -> {out}", flush=True)
                        sys.exit(0)
    if time.time() - t0 > args.timeout:
        print("TIMEOUT", flush=True)
        sys.exit(2)
    print(f"  ...{time.time() - t0:.0f}s", flush=True)
