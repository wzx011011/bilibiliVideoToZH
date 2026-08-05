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
│   ├── doubao_bridge.py         扩展到本地构建的回环服务
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

# 3. 启动本地构建桥接（后台运行；重复执行是安全的）
python src/doubao_bridge.py start
# Windows 也可以双击 start-doubao-bridge.cmd

# 4. 豆包凭据由扩展抓取后复制到项目根目录 .env
#    桥接只从本地 .env/进程环境读取，不通过 HTTP 传输 Cookie

# 5. 运行前去掉 SOCKS 代理（豆包 WS 不支持）
unset all_proxy ALL_PROXY
```

## 制作一集

```bash
# 1. 下载视频（如需要）
work/.venv-ocr/Scripts/python src/download.py "B站URL" --episode 2

# 2. 提取字幕（如需要，视频需有硬字幕）
#    使用 subtitle_ocr.py 从画面 OCR 中文字幕

# 3. 生成待发送分块
work/.venv-ocr/Scripts/python src/make_episode.py --episode 2 --step prep

# 4. 在扩展中选择 work/ep-02/chunks/manifest.json + 全部 TXT
#    保持“完成后生成音频和视频”勾选，然后开始发送
#    发送完成后会自动朗读、拼接音频、生成字幕和 MP4

# 仅在自动任务失败后需要手动恢复：
work/.venv-ocr/Scripts/python src/make_episode.py --episode 2 --step build
# → videos/episode-02.mp4
```

## 已完成

- 第 1-11 集中文字幕（subtitles/，原片 OCR + 人工复核）
- 第 1-2 集豆包配音视频（videos/）

## 技术要点

- **豆包配音**：豆包朗读是 chat_tts 模式（朗读已生成回复），通过提示词让豆包给无标点字幕加标点+润色语气后朗读
- **签名风控**：扩展操作豆包网页原生输入框和发送动作，由浏览器页面完成正常签名
- **精确匹配**：本地构建按会话 ID、原始提问指纹和提问/回复 ID 逐块绑定，缺失或歧义时拒绝生成
- **本地桥接**：服务只监听 `127.0.0.1:8765`，不接受客户端提供命令或工作路径
- **字幕延后**：豆包朗读节奏与字符比例切割有时间差，字幕整体延后 0.5 秒
