# AGENTS.md — bilibiliVideoToZH 工作指南

统一视频汉化平台:英文/中文视频 → 中文配音 + 中文字幕成品。
**v2 架构(当前)**:类型路由工作流 + 五件套产物 + NAS 归档,全 CosyVoice 配音(已脱离豆包)。

## 平台(v2,当前主力)

- 入口:`work/.venv-ocr/Scripts/python.exe src/pipeline_admin.py` → `http://127.0.0.1:8766`(0.0.0.0 局域网;防火墙放行 `allow-lan-8766.cmd`)
- **视频类型 = 字幕情况(en_vtt/none/zh_hard)× 说话人(1/2)** → 自动路由阶段序列
- **五件套**(每任务充分必要产物):`01-视频源 / 02-英文字幕 / 03-中文字幕 / 04-中文音频 / 05-成品`,每阶段产物自动 scp 到 `nas:/volume1/share/视频/<slug>/`
- 配音:CosyVoice2 零样本克隆(WSL2 GPU,断点续跑;音色库 `work/studio/voices/`,预置 doubao-taotao + Hinton 原声);翻译:Ollama qwen3:14b
- 工作目录:`work/studio/<slug>/`;任务状态:`work/studio/tasks/*.json`(schema 2)
- 冒烟参数:API 建任务时传 `_smoke_blocks`/`_smoke_chars` 快速验证
- 豆包链(v1)已退役:`doubao_*.py`/`autosend`/`captcha-extension` 保留在仓库作历史资产,平台不再引用

## 目录

- `src/pipeline_admin.py + admin.html` 平台服务与前端;`voice_lib.py` 音色库;`render_original.py` 原片保留渲染;`whisper_slots.py` 无字幕 ASR 成槽;`make_cover_video.py` 封面渲染;`align_srt_asr.py` ASR 字幕(独立轻量);`make_episode.py`/`subtitle_ocr.py` 课程单集主控与 OCR(v2 仍复用)
- `work/studio/` 平台任务目录;`work/voice-clone-demo/` CosyVoice 引擎(gitignore,含 5.3GB 模型勿删;脚本已参数化:`prepare_fine_slots / translate_fine_batches / generate_voice / assemble_fine_runs`);`work/video-tools/` ffmpeg
- `youtube/` 下载库(按人物);`downloads/` B站原片;`subtitles/` 历史 OCR;`videos/`+`episodes/` 历史成品归档
- `.env` 豆包凭据(历史);NAS:ssh 别名 `nas` → 192.168.100.78

## 常用命令

```bash
PY=work/.venv-ocr/Scripts/python.exe
$PY src/pipeline_admin.py            # 平台(页面建任务即全自动)
$PY -m pytest tests/ -q              # 测试(75 个)
# ollama pull qwen3:14b 需清代理: env -u http_proxy -u https_proxy ollama pull qwen3:14b
```

## 架构边界

- **CosyVoice 只在 WSL2 GPU 跑**(`Ubuntu-24.04`,`/home/comfy/cosy-gpu-venv`;env `HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`;fp16 会出乱码)。Windows CPU 可保底(约 1/3 速度)。环境重建见 skill `doubao-voice-clone`
- 访谈声纹分离用 campplus 锚点(同人相似度 ≥0.87);锚点时间需人工从原片选
- zh_hard 型默认封面渲染(中文音频短于原片,时间轴不对齐);访谈型原片保留(音轨经保音高慢放与原片等长)
- 字幕切分 `MAX_SUBTITLE_CHARS=54`(两行容量);libass force_style 不支持 max_lines,文本端控制
- ASR 缓存 `.asr.json` 存在则字幕秒级;whisper large-v3-turbo cpu/int8

## Windows 坑

1. **Defender 锁文件**:大文件 rename 偶发 WinError 5,等几秒手动 `mv` 即可救回;yt-dlp 加 `--no-part`
2. **venv launcher**:CPU 密集脚本用 base python + PYTHONPATH(平台已内置处理)
3. **文件名**:全角冒号非法,yt-dlp 用 `--restrict-filenames`
4. **代理**:`all_proxy=socks5` 干扰 Ollama CLI(pull 需 env -u 清除);yt-dlp 用 http_proxy

## 其他

- `download-youtube.sh` YouTube 批量下载;`rerender-subtitles.sh` 历史批量重渲染
- TTS 风控史:豆包朗读 WS 曾 3003 限流>24h——v2 已脱豆包,不再受影响
