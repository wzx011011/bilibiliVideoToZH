# AGENTS.md — bilibiliVideoToZH 工作指南

B站视频(哈佛积极心理学课)→ 豆包中文配音 + 中文字幕视频。
流水线:`下载(yt-dlp) → OCR字幕(RapidOCR) → 分块 → 豆包配音(半自动) → ASR字幕对齐(faster-whisper) → ffmpeg渲染`

## 目录

- `src/` 全部代码。`make_episode.py` 是单集制作主控;`align_srt_asr.py` ASR字幕(独立轻量,不依赖 doubao_pipeline);`make_cover_video.py` 渲染(libass 烧硬字幕);`captcha-extension/` 浏览器扩展(豆包凭据抓取+分块发送);`dashboard.html` 流水线监控面板(doubao_bridge 在 http://127.0.0.1:8765/dashboard 提供)
- `work/` 实际工作目录(每集 ep-XX,gitignore);`episodes/` 是成品归档副本
- `subtitles/` OCR 中文字幕;`videos/` 成品 mp4;`downloads/` B站原片;`youtube/` YouTube 下载(按人物分目录,gitignore)
- `.env` 豆包凭据(gitignore,由扩展生成)

## 常用命令

```bash
PY=work/.venv-ocr/Scripts/python.exe

# 单集制作(make_episode 内部自动处理 PYTHONPATH)
$PY src/make_episode.py --episode 2 --step prep      # 分块(需浏览器扩展发送)
$PY src/make_episode.py --episode 2 --step subtitle  # ASR字幕(有 .asr.json 缓存,秒级)
$PY src/make_episode.py --episode 2 --step video     # 渲染(约4-7分钟/集)

# ASR 字幕单独重生成(绕过 gen-srt 依赖)
$PY src/align_srt_asr.py work/ep-02/episode-02-audio.mp3 -o work/ep-02/episode-02-asr.srt --asr-only

# 测试
$PY -m pytest tests/ -q
node src/captcha-extension/sender-core.test.cjs

# 桥接服务(仅 127.0.0.1:8765)
$PY src/doubao_bridge.py start
```

## 架构边界

- **配音是半自动的**:prep 生成 chunks/*.txt → 用户在浏览器扩展里手动发送(绕豆包签名风控)→ 扩展回调桥接自动 build。agent 无法自动完成发送环节。
- `--step subtitle/video` 会先跑 gen-srt,它依赖 manifest 的 `harvested_chunks`(朗读记录)。个别集(如 ep-02)缺该记录会失败——绕过:直接调 `align_srt_asr.py --asr-only` + `make_cover_video.py`。
- `align_srt_asr.py` 保持无 doubao 依赖(轻量、可独立跑);不要让它 import doubao_pipeline。
- 字幕切分:`MAX_SUBTITLE_CHARS = 54`(两行容量,1920/FontSize22 一行约27字)。语义优先:整句 ≤54 不切,超长才在逗号处断。libass force_style 不支持 max_lines,只能文本端控制。

## Windows 坑(本项目高频踩)

1. **Defender 锁文件**:大文件 rename(如 `.part.mp4` → 正式名)偶发 `PermissionError [WinError 5]`。yt-dlp 加 `--no-part`;make_episode 的 `os.replace` 失败时,等几秒手动 `mv` `.part.mp4` 即可救回(文件是完整的)。
2. **venv launcher**:Windows venv python 是 shim,CPU 密集脚本(subtitle_ocr/align_srt_asr)应直接用 base python + PYTHONPATH 指向 venv site-packages。`make_episode.py` 已内置此逻辑,优先走它。
3. **文件名**:标题含全角冒号等在 Windows 非法。yt-dlp 用 `--restrict-filenames`。
4. **代理**:环境有 `all_proxy=socks5://`,豆包 WS 不支持——跑豆包相关前 `unset all_proxy ALL_PROXY`。yt-dlp 用 `http_proxy`(127.0.0.1:7897)。

## 其他

- ffmpeg/ffprobe 在 `work/video-tools/`(gitignore),不在 PATH。
- ASR 缓存:`work/ep-XX/episode-XX-audio.mp3.asr.json` 存在则字幕重生成秒级;删除即重跑 whisper(large-v3-turbo, cpu/int8)。
- ep-04/20/21 的 ASR segment 本就 ≤28 字,从未需要重渲染;ep-22 有分块失败问题(整集塞一个 52KB chunk,豆包无音频产出,build job 卡 queued)。
- `rerender-subtitles.sh` 批量重渲染(带 `work/ep-XX/.rerendered` 完成标记,可断点续跑)。
- `download-youtube.sh` YouTube 批量下载(1080p;`--no-part` + `--restrict-filenames` 防 Windows 坑;重跑自动跳过已下视频)。
