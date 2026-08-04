# B站视频 → 中文配音视频

把 B站视频（如哈佛积极心理学课程）自动转换成"封面图 + 豆包中文配音 + 中文字幕"的视频。

## 流水线

```
下载（yt-dlp）→ 字幕提取（RapidOCR）→ 豆包配音（豆包朗读）→ 视频生成（封面图+字幕）
```

## 目录结构

```
bilibiliVideoToZH/
├── src/                         代码
│   ├── download.py              B站下载（yt-dlp）
│   ├── subtitle_ocr.py          硬字幕 OCR 提取
│   ├── doubao_reader.py         豆包朗读基础能力
│   ├── doubao_pipeline.py       分块/切割/字幕生成
│   ├── make_episode.py          单集制作主控
│   ├── make_cover_video.py      封面图+字幕+水印→MP4
│   └── captcha-extension/       豆包凭据抓取 + 分块自动发送扩展
├── subtitles/                   各集中文字幕（SRT）
├── videos/                      成品视频
├── downloads/                   下载的原视频
├── work/                        工作目录（中间产物）
│   ├── .venv-ocr/               Python 虚拟环境
│   └── video-tools/             ffmpeg/ffprobe
├── tests/                       测试
├── requirements.txt             依赖
└── .env                         豆包凭据（gitignore，用扩展生成）
```

## 环境搭建

```bash
# 1. Python 虚拟环境
python -m venv work/.venv-ocr
work/.venv-ocr/Scripts/python -m pip install -r requirements.txt

# 2. ffmpeg（放入 work/video-tools/）
# 下载 ffmpeg.exe 和 ffprobe.exe 到 work/video-tools/

# 3. 豆包凭据（用扩展抓取，见 src/captcha-extension/README.md）
# 复制结果到 .env

# 4. 运行前去掉 SOCKS 代理（豆包 WS 不支持）
unset all_proxy ALL_PROXY
```

## 制作一集

```bash
# 1. 下载视频（如需要）
work/.venv-ocr/Scripts/python src/download.py "B站URL" --episode 2

# 2. 提取字幕（如需要，视频需有硬字幕）
#    使用 subtitle_ocr.py 从画面 OCR 中文字幕

# 3. 豆包配音
work/.venv-ocr/Scripts/python src/make_episode.py --episode 2 --step prep
# → 用 src/captcha-extension 选择 manifest.json + 全部 txt，自动依次发送
work/.venv-ocr/Scripts/python src/make_episode.py --episode 2 --step build
# → videos/episode-02.mp4
```

## 已完成

- 第 1-11 集中文字幕（subtitles/，原片 OCR + 人工复核）
- 第 1-2 集豆包配音视频（videos/）

## 技术要点

- **豆包配音**：豆包朗读是 chat_tts 模式（朗读已生成回复），通过提示词让豆包给无标点字幕加标点+润色语气后朗读
- **签名风控**：扩展操作豆包网页原生输入框和发送动作，由浏览器页面完成正常签名
- **字幕延后**：豆包朗读节奏与字符比例切割有时间差，字幕整体延后 0.5 秒
