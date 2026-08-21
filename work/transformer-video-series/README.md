# Transformer 视频生产线

这是一个基于 Remotion 的中文 Transformer 教学视频项目。生产流程由 React 画面、TTS 旁白、时间轴 sidecar 和自动化校验组成。最终视频中的字幕、章节切换、语义高亮和术语解释都读取同一份 timing JSON。

## 目录约定

```text
narration/                 旁白原稿，段落对应章节
public/audio/              音频和 neural.timing.json
src/                       Remotion Composition 与视觉组件
scripts/generate-neural-audio.py
                          生成音频和句级时间轴
scripts/validate-timing.py
                          校验时间轴完整性
scripts/render-pipeline.ps1
                          标准化检查与渲染入口
pipeline.config.json       可复用渲染 profile
out/                       本地渲染产物，不提交 Git
```

## 标准流程

### 1. 写稿

每个空行分隔一个章节。首次出现且会影响后文理解的术语，必须用三句话交代：白话含义、为什么需要、当前例子对应什么。新版术语展开稿见 `narration/transformer-beginner-10min-v3.txt`。

### 2. 生成旁白和时间轴

```powershell
& ..\gpt-sovits\.venv\Scripts\python.exe `
  scripts\generate-neural-audio.py `
  --source narration\transformer-beginner-10min-v3.txt `
  --output public\audio\transformer-beginner-10min-v3.neural.mp3 `
  --voice zh-CN-XiaoxiaoNeural `
  --rate=-10% `
  --split-paragraphs
```

生成器会输出：

- 规范化后的 MP3；
- `*.neural.timing.json`；
- 每句的 `from`、`duration` 和文本；
- 每章的 `paragraphDurations`。

### 3. 校验时间轴

```powershell
pnpm timing:validate
```

校验器会拒绝以下问题：章节时长之和不等于音频时长、字幕句子重叠、字幕越过音频尾部、空字幕和非法数字。

### 4. 渲染

推荐使用 profile，不要手工拼接 Composition、音频和输出文件名：

```powershell
pnpm pipeline:terms
pnpm pipeline:semantic
```

也可以直接运行：

```powershell
.\scripts\render-pipeline.ps1 -Profile terms -Concurrency 8
```

profile 在 `pipeline.config.json` 中维护。目前包含：

| Profile | Composition | 用途 |
| --- | --- | --- |
| `semantic` | `Transformer-01-Beginner-10min-V2` | 句子驱动区域高亮和流程动画 |
| `terms` | `Transformer-01-Beginner-Terms-V3` | 关键术语三栏展开讲解 |

### 5. 验收

渲染完成后至少检查：

```powershell
pnpm check
& ..\video-tools\ffprobe.exe -v error `
  -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate,sample_rate,channels `
  -of json out\transformer-beginner-terms-v3.mp4
```

另外从音频中段、章节切换点、术语卡片和最后 1 秒各抽一帧，确认：文字不溢出、字幕与旁白同步、语义高亮落在正确模块、尾帧和音轨完整。

## 对齐策略

当前生成器使用 TTS 返回的 `SentenceBoundary` 作为句级时间轴。字幕、章节和语义动画共享它，因此句子级同步稳定。长句内部的多行字幕目前按字符比例切换；如果需要逐词高亮，可在生成后增加 WhisperX、stable-ts 或 FunASR 的强制对齐步骤，并把词级数组写入同一个 sidecar。

## 本地开发

```powershell
$env:PATH = 'C:\Users\106660\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;C:\Users\106660\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback;' + $env:PATH
pnpm install
pnpm check
pnpm start
```

默认规格为 1920x1080、30fps、H.264 MP4。音频、视频、日志和预览目录已加入 Git 忽略规则；源码、旁白文本、timing JSON、配置和脚本会提交到仓库。
