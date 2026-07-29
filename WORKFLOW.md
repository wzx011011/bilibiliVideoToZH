# 标准工作流

本项目为哈佛积极心理学 23 集课程制作普通话配音版。唯一的质量基准是：

`outputs/harvard-positive-psychology/episode-01-delivery-revised`

不要覆盖该目录。后续每一集都必须复制它的交付结构和质量门槛。

## 固定方法

1. 中文字幕只从画面中的硬字幕读取：`qwen3-vl:4b` 视觉 OCR。
   不使用 NLLB 机器翻译、RapidOCR 或未经复核的文本做最终字幕。
2. OCR 结果必须先经过 `clean_ocr_cues()` 去重，再应用该集的人工复核文件。
   最终 OCR 合成没有 `--review-file` 会直接失败。
3. 配音固定使用 GPT-SoVITS 和
   `work/headless-dub/voice-refs/cn-pro-ref.wav`。默认参考文本已写入脚本。
4. 固定 `--speech-tempo 0.98 --max-tempo 1.05`。短句允许自然停顿，绝不为了
   填满字幕窗而拉伸，也不得快于 1.05 倍。
5. 最终 MP4 必须包含默认普通话音轨、原英文第二音轨、默认中文字幕和英文字幕。

正式 Python 环境固定为：

```powershell
work\headless-dub\.venv-ocr\Scripts\python.exe
```

首次在新机器上执行：

```powershell
& 'work\headless-dub\.venv-ocr\Scripts\python.exe' -m pip install -r 'work\headless-dub\requirements.txt'
```

运行前确认本机 Ollama 已启动且已安装 `qwen3-vl:4b`，GPT-SoVITS 服务可用，
并且 `work/video-tools/ffmpeg.exe` 和 `ffprobe.exe` 存在。

## 每集流程

下面以第 2 集为例。先定义源文件和本集目录：

```powershell
$env:HF_HUB_OFFLINE = '1'
$source = 'outputs\harvard-positive-psychology\02 - 【哈佛大学】积极心理学 Talben Shahar（全23讲） p02 第2讲 为什么要学习积极心理学.mp4'
$work = 'outputs\harvard-positive-psychology\episode-02-work'
$delivery = 'outputs\harvard-positive-psychology\episode-02-delivery'
$python = 'work\headless-dub\.venv-ocr\Scripts\python.exe'
```

### 1. 先做短段 OCR 预检

每集分辨率和字幕带位置可能不同。先用前 90 秒验证字幕带、事件数量和文字质量；
确认无误后才跑全集。

```powershell
& $python 'work\headless-dub\dub_pipeline.py' `
  --input $source --duration 90 `
  --output $work `
  --artifact-stem episode-02-preflight `
  --stage subtitles `
  --subtitle-source ocr --ocr-model qwen3-vl:4b `
  --transcription-model 'work\headless-dub\model-cache\manual-large-v3-turbo'
```

检查 `episode-02-preflight.zh-CN.srt`：中文不能成片缺失、重复或错位；字幕事件
数不能明显异常。预检不合格时，先停止并调整 OCR 参数或人工检查画面，不要直接跑全集。

### 2. 生成全集待复核字幕

使用独立且稳定的本集工作目录。后续合成必须复用这个目录，不能换新目录。

```powershell
& $python 'work\headless-dub\dub_pipeline.py' `
  --input $source --full `
  --output $work `
  --artifact-stem episode-02 `
  --stage subtitles `
  --subtitle-source ocr --ocr-model qwen3-vl:4b `
  --transcription-model 'work\headless-dub\model-cache\manual-large-v3-turbo'
```

复核 `$work\episode-02.zh-CN.srt`。重点检查滚动字幕的重复、速度过快导致的
断句、漏行和明显识别错误。

### 3. 保存人工复核叠加文件

仅记录修改，不要直接改工作目录中的生成文件。创建：

`work/headless-dub/review-overrides/episode-02.json`

```json
{
  "schema_version": 1,
  "overrides": [{"start": 12.34, "text": "已复核文本"}],
  "previous_ends": [{"start": 12.34, "end": 13.20}],
  "restored_cues": [{"start": 13.20, "end": 14.10, "text": "补回字幕"}]
}
```

`start` 必须匹配去重后 OCR cue 的起始时间。脚本会拒绝过期的起始时间或重叠的
时间轴修改，避免把旧复核结果错用到新字幕上。没有修改时，也保留一个包含
`schema_version` 和三个空数组的复核文件，作为已审核记录。

### 4. 合成并发布

这一步会在工作目录中生成最终 MP4，然后以原子方式生成交付目录。若交付目录
已经存在，脚本会停止，防止覆盖已验证的成品。

```powershell
& $python 'work\headless-dub\dub_pipeline.py' `
  --input $source --full `
  --output $work `
  --artifact-stem episode-02 `
  --stage all `
  --subtitle-source ocr --ocr-model qwen3-vl:4b `
  --review-file 'work\headless-dub\review-overrides\episode-02.json' `
  --tts-engine gpt-sovits `
  --ref-audio 'work\headless-dub\voice-refs\cn-pro-ref.wav' `
  --speech-tempo 0.98 --max-tempo 1.05 `
  --transcription-model 'work\headless-dub\model-cache\manual-large-v3-turbo' `
  --delivery-dir $delivery
```

`--delivery-dir` 自动写入以下内容：

```text
episode-02-delivery/
  video/episode-02.dual-audio.bilingual-subtitles.mp4
  audio/episode-02.zh-CN.dub.m4a
  audio/episode-02.en.original.m4a
  subtitles/episode-02.zh-CN.srt
  subtitles/episode-02.en.srt
  metadata/manifest.json
  metadata/ffprobe.json
  metadata/workflow.json
  metadata/episode-02.reviewed-cues.json
  metadata/episode-02.review-overrides.json
  metadata/SHA256SUMS.txt
```

### 5. 发布前验证

```powershell
& 'work\video-tools\ffprobe.exe' -v error -show_streams -show_format -of json `
  "$delivery\video\episode-02.dual-audio.bilingual-subtitles.mp4"
```

确认：视频时长正确；普通话音轨为默认；英文音轨存在；中文字幕为默认；英文字幕
存在；中文 SRT 没有相邻重复文本或时间重叠；`metadata/SHA256SUMS.txt` 中的每项
哈希均匹配。确认后才能分发交付目录。

工作目录只可在交付目录验证完成、复核叠加文件已归档后删除。绝不删除原始 MP4 或
已验证的交付目录。
