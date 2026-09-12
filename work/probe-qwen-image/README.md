# Qwen-Image 本地试稿引擎(2026-09-11 部署)

**决定(用户定):生产生图只用 ICU gpt-image-2。** Qwen-Image 本地部署仅作零成本试稿、
构图探索和中文文字封面辅助,**不接入 `src/broll/generate.py` 后端路由**。

## 部署构成(WSL Ubuntu-24.04,ComfyUI 0.35.0)

| 组件 | 位置 |
|------|------|
| ComfyUI-GGUF 节点(gguf 0.19.0,纯 Python,torch 未动) | `~/ComfyUI/custom_nodes/ComfyUI-GGUF` |
| DiT:Qwen-Image-2512 GGUF Q4_K_S(11.4GB,16GB 显存完整驻留) | `~/ComfyUI/models/diffusion_models/` |
| 文本编码器:qwen_2.5_vl_7b_fp8_scaled(8.7GB,device=cpu) | `~/ComfyUI/models/text_encoders/` |
| VAE:qwen_image_vae(254MB) | `~/ComfyUI/models/vae/` |
| 试跑脚本(API 提交→轮询→取图) | `work/probe-qwen-image.py` |
| 样张 | `work/probe-qwen-image/` |

```bash
# 用法示例
work/.venv-ocr/Scripts/python.exe work/probe-qwen-image.py \
  --steps 20 --seed 33 --size 1280x720 --prompt "..." --negative "..."
```

工作流要点:`UnetLoaderGGUF`(.gguf 不在核心 UNETLoader 列表)+ `CLIPLoader(type=qwen_image,
device=cpu)` + `ModelSamplingAuraFlow(shift=3.1)` + euler/simple 20 步 cfg 2.5 +
**`VAEDecodeTiled`(tile 512)**。

## 实测数据(RX 7800 XT 16GB)

- 冷启动整图 9~12 分钟(模型装载+CPU 文本编码);热态 **1280×720 约 2.5 分钟/张**
  (20 步,6.6s/it,文本编码几分钟在 CPU)
- 中文文字渲染:两轮 8/8 全对(金书法横排+竖排毛笔字),可画封面标题
- 羊皮纸平涂配方 5 连出 5/5 可用,叙事/人马结构远超本机 SDXL(对比 `work/broll/compare/`)

## 羊皮纸平涂风格配方(对齐 gpt-image-2 出图的"皮")

风格硬约束**全部前置**,叙事放后段:

```
Flat vector picture-book illustration printed on warm aged parchment paper.
Strictly limited palette of four colors only: vermilion red, imperial yellow,
indigo blue, cream parchment. Solid flat color fills, clean bold shapes, thick
outlines, no gradients, minimal shading, subtle paper grain across the whole
image, gouache poster style. Ming dynasty China. Scene: <叙事节拍写这里>.
No text, no letters, no watermark.
```

负向:`photorealistic, painterly brushwork, oil painting, 3D render, gradient
shading, glossy highlights, text, letters, watermark`

- **忌用** `cinematic lighting` / `Dramatic` 开头——会把 Qwen 带进厚涂写实,风格词被稀释
- 旗帜上会自发伪汉字,近景穿帮拍加 "plain banners without characters" 规避
- 多势力博弈节拍可用 "riders on red / yellow / blue horses" 做势力配色编码(实测有效)

## 坑

1. **VAE 解码必 OOM**:DiT 驻留 11.8GB 后普通 `VAEDecode` 爆显存,必须 `VAEDecodeTiled`
2. **启动必须带 `HSA_ENABLE_DXG_DETECTION=1`**,否则 torch 报 No HIP GPUs
3. **WSL 空闲整机会被回收**:/tmp(tmpfs)清空、nohup/setsid 的服务全死;长驻要挂
   前台会话(generate.py 的自动拉起带 HSA env,但只管它自己的 8188)
4. 冷启动慢,试稿时连续出图别让 ComfyUI 闲置回收
5. 下载走代理直连 huggingface.co(aria2 -x6 约 30MB/s);hf-mirror 直连被限速 1MB/s 以下
