# AGENTS.md — bilibiliVideoToZH 工作指南

统一视频汉化平台:英文/中文视频 → 中文配音 + 中文字幕成品。
**v2 架构(当前)**:类型路由工作流 + 五件套产物 + NAS 归档,全 CosyVoice 配音(已脱离豆包)。

## 平台(v2,当前主力)

- 入口:`work/.venv-ocr/Scripts/python.exe src/pipeline_admin.py` → `http://127.0.0.1:8766`(0.0.0.0 局域网;防火墙放行 `allow-lan-8766.cmd`)
- **公网**:`https://studio.5945.top`(NAS nginx 子域名反代 → 容器 8766)
- **视频类型 = 字幕情况(en_vtt/none/zh_hard)× 说话人(1/2)× 成片模式(时间轴/旁白)** → 自动路由阶段序列
- **NAS资源根**:`/volume1/share/视频汉化项目/`
  - 原片:`原片库/<系列>/`
  - 生成资源:`成品库/<系列>/{01-英文字幕,02-中文字幕,03-中文音频,04-中文视频}/`
- **五件套**(每任务充分必要产物):视频源在原片库,英文字幕/中文字幕/中文音频/成品在成品库,每阶段产物自动 scp 到 NAS 对应系列目录
- 配音:CosyVoice2 零样本克隆(WSL2 GPU,断点续跑;音色库 `work/studio/voices/`);翻译:Ollama qwen3:14b
- 工作目录:`work/studio/<slug>/`;任务状态:`work/studio/tasks/*.json`(schema 2)
- 冒烟参数:API 建任务时传 `_smoke_blocks`/`_smoke_chars` 快速验证
- 豆包链(v1)已退役:`doubao_*.py`/`autosend`/`captcha-extension` 保留在仓库作历史资产,平台不再引用

## 成片模式

| 模式 | 适用类型 | 音轨 | 画面 | 状态 |
|------|----------|------|------|------|
| 时间轴版(默认) | en_vtt×任意 | 中文逐槽对齐原时间轴 | 原片/封面 | ✅ 已验证(ep-22/23, Hinton) |
| **旁白版** | en_vtt_2_narration | 中文语义段自然语速 + 英文原声 -22dB 低混 | 原片保留 | ✅ 已验证(Hinton) |
| **播客版(Remotion)** | none_2_podcast | 语义段精修(polish)+ 停顿顺序排布 | 双真人头像+波形+滚动字幕 | ✅ 平台化(Hinton 手动链固化) |
| 章节图播客 | render_mode=podcast | 同上 | PIL 章节图(旧版) | 保留 |

旁白版核心:细槽按语义合并为 30~75s 段(`narration.py build_runs`),自然语速生成不拉伸,
按原片起点放置、碰撞自动后移,`assemble_narration.py` 合成旁白+原声低混音轨。
双语字幕可选(`compose_bilingual.py`,中上英下,英文去填充词)——默认纯中文。

播客版(none_2_podcast,平台标准链):whisper 成槽 → diarize → 翻译审查 → 语义段 →
配音 → `polish_audio` 精修(输出 `podcast-studio/public/audio-<slug>/`)→
`podcast_props`(锚点截头像 `extract_avatars.py` + props `build_podcast_props.py` +
完整音轨拼接)→ `zh_subtitle`(`podcast_srt.py`,与画面字幕严格一致)→
Remotion 分块渲染。props/音频/头像按 slug 隔离在 podcast-studio 下,互不覆盖;
渲染块断点续跑(已存在 chunk 跳过)。

## 质检阶段(2026-08 新增,已入平台流水线)

- `align_speakers`(词级对齐校声):Qwen3-ForcedAligner 把 VTT 文本对齐到音频(词级 ~33ms),
  按真实停顿切 utterance 后 campplus 重标说话人——根治固定窗口的边界归属错误
  (Hinton 案例:5 槽错标导致"主持人念 Hinton 台词")。工具:`src/align_worker.py`(WSL
  `~/qwen-aligner-venv`,HF_HUB_OFFLINE=1)+ `src/label_speakers.py`。未装对齐器自动跳过。
- `audit_translation`(译文审查):qwen3 逐槽对照英文源判 MATCH/PARTIAL/MISMATCH,
  MISMATCH ≥5 置失败提示人工复核——根治豆包批量翻译的切块串位。工具:`src/audit_translation.py`。
- 阶段路由:en_vtt_2/en_vtt_2_narration 在 en_slots 后插 align_speakers;
  所有含翻译的类型在 translate 后插 audit_translation。

## 音色库(2026-08 扩充:50 豆包音色)

- `work/studio/voices/` 共 52 音色:`doubao-<中文名>`×47(豆包全量克隆)+`doubao-taotao`
  (v1 遗产)+`doubao-yuanboxiaoshu`/`doubao-shenyeboker`(访谈声线:渊博小叔=主持人,
  深夜播客=Hinton)+`orig-hinton-host/guest`(原声克隆)。
- 每个音色 = ref.wav(~14s 参考音频)+ ref.txt(逐字转写)+ meta.json(含豆包 speaker ID)。
- 收割工具:`src/doubao_harvest_all.py`(发一条复述消息→49 音色逐个 WS 朗读抓取,断点续跑);
  音色名单 `src/doubao-voices.json`;单音色参考合成 `src/doubao_gen_refs.py`。
- **坑**:voicegenie WS 的 speaker 参数只认音色 ID,不认中文名(中文名会静默回退默认音色,
  声纹抽检两两相似度 0.976 才暴露);同步 Playwright 与 asyncio.run 冲突,浏览器阶段必须
  先关闭再跑 asyncio 收割。
- 选型参考:Hinton 访谈最终用渊博小叔(主持人)+深夜播客(Hinton);原声克隆(英文参考)
  中文会有"老外腔",豆包声线克隆口音纯正。GPT-SoVITS 备用引擎装在 `work/gpt-sovits/`
  (v2 预训练模型齐,参考音频限 3~10s,本次未采用)。

## 播客版(Remotion)链路

- 组件 `work/podcast-studio/src/Podcast.tsx`:双真人头像+波形+字幕+底部进度条。
- **渲染必须分块**:全片一次渲染会 OOM,按 ~12 章一块 `--frames=起-止` 渲染再 ffmpeg concat;
  Composition 时长用 calculateMetadata 随 props 动态计算。
- **字幕**:按句切条(≤32 字单行),条内时长按字数占比随播放推进(ScrolingText 组件);
  禁止整章文本一次性渲染。
- **禁用 CSS transition**:Remotion 逐帧截图下 transition 完成度不可控 → 进度条/头像/名字
  会闪;一切动画用 interpolate/spring 帧驱动(进度条宽度=frame/总帧)。
- 音频精修:`src/polish_parts.py`(70Hz 高通+首尾静音切除+loudnorm 响度统一+12ms/90ms
  淡入淡出去爆音;--speed 可选降速,中文母语音色保持 1.0)。
- props 构建:`src/build_podcast_props.py`(章节时间轴=顺序排布,换人停顿 0.7s/同人 0.45s)。
- 旁白版字幕:`src/narration_srt.py`(时间轴与 assemble_narration 放置逻辑严格一致)。

## 目录

- `src/pipeline_admin.py + admin.html` 平台服务与前端;`voice_lib.py` 音色库;`render_original.py` 原片保留渲染;`render_podcast.py` 播客渲染;`whisper_slots.py` 无字幕 ASR 成槽;`narration.py` 语义段落合并;`assemble_narration.py` 旁白+低混音轨;`narration_srt.py` 旁白字幕;`polish_parts.py` 配音精修;`build_podcast_props.py` 播客 props;`podcast_srt.py` 播客字幕;`extract_avatars.py` 播客头像;`doubao_harvest_all.py`+`doubao_gen_refs.py` 豆包音色收割;`compose_bilingual.py` 双语字幕;`make_cover_video.py` 封面渲染;`align_srt_asr.py` ASR 字幕(独立轻量);`align_worker.py`+`label_speakers.py`+`audit_translation.py` 质检三件套;`make_episode.py`/`subtitle_ocr.py` 课程单集主控与 OCR(v2 仍复用)
- `work/studio/` 平台任务目录;`work/voice-clone-demo/` CosyVoice 引擎(gitignore,含 5.3GB 模型勿删;脚本已参数化);`work/video-tools/` ffmpeg
- `youtube/` 下载库(按人物);`downloads/` B站原片;`subtitles/` 历史 OCR;`videos/`+`episodes/` 历史成品归档
- NAS 部署:`deploy-nas-studio.sh`(控制面容器)+ `start-studio-agent.cmd`(PC 代理开机自启)
- `.env` 豆包凭据(历史);NAS:ssh 别名 `nas` → 192.168.100.78

## 常用命令

```bash
PY=work/.venv-ocr/Scripts/python.exe
$PY src/pipeline_admin.py            # 平台(页面建任务即全自动)
$PY -m pytest tests/ -q              # 测试(75 个)
# ollama pull qwen3:14b 需清代理: env -u http_proxy -u https_proxy ollama pull qwen3:14b
# NAS 控制面更新: bash deploy-nas-studio.sh
# PC 代理启动: start-studio-agent.cmd(或 shell:startup 放快捷方式)
```

## 架构边界

- **CosyVoice 只在 WSL2 GPU 跑**(`Ubuntu-24.04`,`/home/comfy/cosy-gpu-venv`;env `HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`;fp16 会出乱码)。Windows CPU 可保底(约 1/3 速度)。环境重建见 skill `doubao-voice-clone`
- 访谈声纹分离用 campplus 锚点(同人相似度 ≥0.87);锚点时间需人工从原片选
- zh_hard 型默认封面渲染(中文音频短于原片,时间轴不对齐);访谈型原片保留(旁白版与原片等长)
- 字幕切分 `MAX_SUBTITLE_CHARS=54`(两行容量);libass force_style 不支持 max_lines,文本端控制
- ASR 缓存 `.asr.json` 存在则字幕秒级;whisper large-v3-turbo cpu/int8
- 旁白模式:段碰撞自动后移(不硬对齐原时间轴),原声 -22dB 低混,双语字幕可选但默认纯中文

## Windows 坑

1. **Defender 锁文件**:大文件 rename 偶发 WinError 5,等几秒手动 `mv` 即可救回;yt-dlp 加 `--no-part`
2. **venv launcher**:CPU 密集脚本用 base python + PYTHONPATH(平台已内置处理)
3. **文件名**:全角冒号非法,yt-dlp 用 `--restrict-filenames`
4. **代理**:`all_proxy=socks5` 干扰 Ollama CLI(pull 需 env -u 清除);yt-dlp 用 http_proxy
5. **Playwright DOM 操作**:fill 对 ProseMirror contenteditable 长文本会错位,用 click+Ctrl+A+insert_text;locator.hover 会卡在 React 重渲染,用坐标 mouse.move
6. **WSL 镜像网络**:`.wslconfig` 已设 `networkingMode=mirrored`,WSL 内直接用 `127.0.0.1:7897` 走 Clash(pip/HF 下载不再需要 Windows 侧倒腾);WSL 直连外网仍不通,记得带代理 env
7. **PC 代理进程成对**:venv python.exe 是 launcher,会拉起 Python311 子进程——wmic 看到两个 studio_agent 属正常,别当重复进程误杀
8. **Remotion 渲染**:全片一次渲染 OOM,必须分块;CSS transition 在逐帧截图下不可确定,动画一律 interpolate/spring

## 其他

- `download-youtube.sh` YouTube 批量下载;`rerender-subtitles.sh` 历史批量重渲染
- TTS 风控史:豆包朗读 WS 曾 3003 限流>24h——v2 已脱豆包,不再受影响
- 访谈旁白模式已验证:Hinton 医学访谈 36 分钟,48 语义段,双音色,原片等长
