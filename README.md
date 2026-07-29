# 哈佛积极心理学中文配音项目

当前唯一认可的成品位于：

`outputs/harvard-positive-psychology/episode-01-delivery-revised`

请观看其中的：

`video/episode-01.dual-audio.bilingual-subtitles.mp4`

它是后续第 2 至 23 集的质量标准：默认普通话音轨和中文字幕、原英文第二音轨、
英文字幕、572 条已复核中文字幕，以及 `0.98` 自然语速和 `1.05` 最高加速限制。

保留内容：

- `outputs/harvard-positive-psychology/01-*.mp4` 至 `23-*.mp4`：原始课程视频
- `outputs/harvard-positive-psychology/episode-01-delivery-revised/`：已验证交付
- `work/headless-dub/dub_pipeline.py`：字幕、配音、封装和发布流程
- `work/headless-dub/subtitle_ocr.py`：Qwen 视觉 OCR
- `work/headless-dub/tts_gpt_sovits.py`：GPT-SoVITS 合成封装
- `work/headless-dub/review-overrides/`：每集人工复核记录
- `work/headless-dub/voice-refs/cn-pro-ref.wav`：已批准的中文参考音频

后续制作请严格遵循 [WORKFLOW.md](WORKFLOW.md)。不要把临时 OCR、样片或未复核的
工作目录作为交付。
