# bilibiliVideoToZH

本地化视频生产工作区:英文/中文视频汉化(中文配音+中文字幕),以及中国史、AI 快讯等原创系列的
全自动出片。配音、翻译、出图、质检全部本地模型,成品归档 NAS。

**完整工作指南、约定与踩坑记录见 [`AGENTS.md`](AGENTS.md)**(以它为准);中国史全库排产见
[`HISTORY_PLAN.md`](HISTORY_PLAN.md)。

## 产线

| 产线 | 入口 | 说明 |
|---|---|---|
| 视频汉化平台(v2) | `src/pipeline_admin.py` + `src/studio_agent.py` | 网页建任务,按「字幕情况×说话人×成片模式」自动路由阶段:whisper 成槽 → 声纹分离 → qwen3 翻译+审查 → CosyVoice 配音 → 时间轴版/旁白版/播客版成片 |
| 中国史系列 | `src/mzx_story/`(剧本 JSON + painters + `vector_render.py`) | Qwen-Image 插画 + CV3 配音 + Pillow 逐帧渲染,9 章制;大明/溯源/东周等线 |
| 推演系列 | `src/mzx_series/` | 战略批注风图解 |
| AI 快讯 / 科普 | `kinetic_demo/make_model_video.py` | content JSON → 配音 → Playwright 逐帧舞台 → ffmpeg;每日自动制作发布 |
| Transformer 讲解 | `work/transformer-video-series/` | Remotion,见该目录 [README](work/transformer-video-series/README.md) |

发布前统一过 `src/av_qc.py` 门禁(ASR 回环,hard CER 整体 ≤6%、单章 ≤12%)。

## 常用命令

```bash
PY=work/.venv-ocr/Scripts/python.exe
$PY src/pipeline_admin.py        # 平台控制面 http://127.0.0.1:8766
$PY -m pytest tests/ -q          # 测试
bash deploy-nas-studio.sh        # 更新 NAS 控制面容器
```

依赖外部服务:Ollama(qwen3:14b)、WSL2 GPU 上的 CosyVoice、ComfyUI(Qwen-Image)、
`work/video-tools/` 下的 ffmpeg/ffprobe。环境细节见 AGENTS.md「架构边界」。

## 历史文档

[`WORKFLOW.md`](WORKFLOW.md) 是哈佛积极心理学 23 集(v1,GPT-SoVITS/headless-dub)的交付流程,
该系列已完结,仅作存档;豆包链 v1 已于 2026-10-13 删除,可从 git 历史找回。
