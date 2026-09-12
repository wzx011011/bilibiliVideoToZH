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
- **哈佛积极心理学系列(ep1~23)成品以 v1 豆包链路 `videos/episode-N.mp4` 为准**(2026-09-11
  用户定,要保持系列统一):豆包网页版音色+干净字幕+49 分钟量级;平台 zh_hard 重排版
  (CosyVoice 克隆音色/ASR 字幕乱码复读/仅 21 分钟)已弃用,ep-23 的 NAS 成品已换回 v1 版
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

⚠️ **正脸访谈慎用时间轴版**(2026-08 Tibo 试验版实证):中文整段贴轨后句内节奏必然
偏离口型,观众感知"音画不同步",属范式极限而非 bug。此类素材一律走**旁白版或播客版**。
自动声纹锚点无需人工听选:YouTube 字幕 `>>` 换人标记切边界 + 3s 窗口 campplus 聚类
即可产出 A/B 锚点(实现见 `work/voice-clone-demo/tibo_pipeline.py` 的 stage_prep)。

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

- `src/pipeline_admin.py + admin.html` 平台服务与前端;`voice_lib.py` 音色库;`render_original.py` 原片保留渲染;`render_podcast.py` 播客渲染;`whisper_slots.py` 无字幕 ASR 成槽;`narration.py` 语义段落合并;`assemble_narration.py` 旁白+低混音轨;`narration_srt.py` 旁白字幕;`polish_parts.py` 配音精修;`build_podcast_props.py` 播客 props;`podcast_srt.py` 播客字幕;`extract_avatars.py` 播客头像;`doubao_harvest_all.py`+`doubao_gen_refs.py` 豆包音色收割;`compose_bilingual.py` 双语字幕;`make_cover_video.py` 封面渲染;`align_srt_asr.py` ASR 字幕(独立轻量);`align_worker.py`+`label_speakers.py`+`audit_translation.py` 质检三件套;`make_episode.py`/`subtitle_ocr.py` 课程单集主控与 OCR(v2 仍复用);`apple_event/` 发布会监控+速览成片(monitor.py 三源轮询→facts/raw 快照,prepare/render 复用 gpt_explainer 管线换苹果夜皮肤,音色东方浩然);gpt_explainer 渲染器支持 `kind:"image"` 章节(官方产品图左+要点右,带进度推近,图片按 chapter.image 字段引用),产品速览类视频必须配官方产品图(2026-09 用户定)
- `work/studio/` 平台任务目录;`work/voice-clone-demo/` CosyVoice 引擎(gitignore,含 5.3GB 模型勿删;脚本已参数化);`work/video-tools/` ffmpeg
- `youtube/` 下载库(按人物);`downloads/` B站原片;`subtitles/` 历史 OCR;`videos/`+`episodes/` 历史成品归档
- NAS 部署:`deploy-nas-studio.sh`(控制面容器)+ `start-studio-agent.cmd`(PC 代理开机自启)
- `.env` 豆包凭据(历史);NAS:ssh 别名 `nas` → 192.168.100.78

## 常用命令

```bash
PY=work/.venv-ocr/Scripts/python.exe
$PY src/pipeline_admin.py            # 平台(页面建任务即全自动)
$PY -m pytest tests/ -q              # 测试(140 个)
# ollama pull qwen3:14b 需清代理: env -u http_proxy -u https_proxy ollama pull qwen3:14b
# NAS 控制面更新: bash deploy-nas-studio.sh
# PC 代理启动: agent-forever.cmd(看门狗,console 输出落 work/studio/agent-console.log)
```

## 任务生命周期与可靠性(2026-08-31 大修,tests/test_recovery.py)

- **租约协议**:代理 claim 时服务端发 lease token(存 `active.json`),之后每次
  stage/artifact/log/progress/done 上报必须携带;token 不符回 409,代理收到
  409 抛 `LeaseLost` 立即放弃本地执行。claim/heartbeat/release 全程持
  `ACTIVE_LOCK` 串行化 + 原子写,双代理并发领取不可能。
- **心跳失联自动续跑**:60 分钟无心跳 → 服务端回收租约,被中断阶段复位
  pending,任务保持 running 由下个代理无缝接手(不再打成 failed 等人重试)。
- **代理生命周期**:run_one 全程 try/except/finally,任何退出路径必停心跳 +
  终态上报(done 带 5 次退避重试);poll 的 lease 在 `r["lease"]`,必须显式
  传给 run_one(漏传=全部上报 409 静默空转,2026-09-01 实测坑)。
- **阶段内取消**:cancel 动作 → 代理 `pa.CANCEL_PROBE`(10s 粒度)→ `_run`
  杀子进程 → `StageCanceled` → 阶段复位 pending + 状态 canceled,产物检查点
  (翻译断点/审查报告)全部保留,恢复即续跑。
- **恢复语义**:`_normalize_for_run` 统一处理残留 running/failed;本地 runner
  注册表防同任务并行;API 动作:`retry`(重试失败阶段)/`resume`(取消续跑)/
  `reclaim`(强收卡死 running,租约新鲜时拒绝)/`retranslate`(审查串位后作废
  译文从翻译重跑)。
- **翻译可靠性**:批次响应必须精确覆盖本批 ID(缺/多/空译文整批重试 4 次,
  否则断点退出),杜绝部分批次静默写盘;`slots_zh.meta.json` 存 slots 指纹+
  模型,指纹变化自动作废旧译文;平台侧逐槽校验覆盖(缺槽/残留/空译文)。
- **审查可靠性**:逐槽完成即原子落盘(as_completed,单慢请求不堵检查点);
  报告带 `_summary{complete,mode,指纹}`:部分报告 complete=False 不能当结论;
  全量审查必须覆盖全部槽;zh 指纹不符自动作废重审;Ollama 连挂立即失败保
  检查点(不再产出整篇 ERROR 或 6h 无输出超时)。
- **en_slots 续跑**:`slots.json` 已存在则跳过 whisper 重转写,只重跑声纹。
- **诊断**:任务 JSON 的 stage.error 现在带 stderr 尾部(不再只有
  `python.exe exit 1`);子进程统一 `PYTHONIOENCODING=utf-8`(GBK 管道打 ✓
  曾毁掉整个 en_slots);PC 代理 console 落 `work/studio/agent-console.log`。
- **控制面容器被杀恢复**:`--restart unless-stopped` 兜底;若被外部强杀
  (exit 137 非 OOM,DSM 侧动过),`ssh nas "docker start studio-console"`
  一条命令拉起。NAS 无免密 sudo,root crontab 看门狗未装。
- **PC 访问控制面走 Clash**:沙盒/本机对 `192.168.100.78:8766` 直连被拒,
  一切查询走系统代理;容器重启窗口代理回 502,脚本必须无限重试兜底
  (work/watch_*.py 两例)。

## 架构边界

- **CosyVoice 只在 WSL2 GPU 跑**(`Ubuntu-24.04`,`/home/comfy/cosy-gpu-venv`;env `HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`;fp16 会出乱码)。Windows CPU 可保底(约 1/3 速度)。环境重建见 skill `doubao-voice-clone`。**CV3 已入产线**(2026-09-12):`work/voice-clone-demo/models/Fun-CosyVoice3-0.5B-2512`(8.3GB,ModelScope);CV3 加载不能走 `generate_voice.py`(AutoModel 转发 load_jit 会 TypeError),用 `cv3_generate_voice.py`;refs 的 ref_text 必须带 `You are a helpful assistant.<|endofprompt|>` 前缀;CV3 还支持拼音 hotfix 内标注(`[j][ǐ]` 直接锁音)
- 访谈声纹分离用 campplus 锚点(同人相似度 ≥0.87);锚点时间需人工从原片选
- zh_hard 型默认封面渲染(中文音频短于原片,时间轴不对齐);访谈型原片保留(旁白版与原片等长)
- 字幕切分 `MAX_SUBTITLE_CHARS=54`(两行容量);libass force_style 不支持 max_lines,文本端控制
- ASR 缓存 `.asr.json` 按 mtime 校验(2026-09-11 修复:ep23 音频重收割后旧短音频缓存未失效,字幕只烧了前 16 分钟/音频 49 分钟,全系列覆盖度扫描脚本 `work/scan_srt_coverage.py`);whisper large-v3-turbo cpu/int8
- 旁白模式:段碰撞自动后移(不硬对齐原时间轴),原声 -22dB 低混,双语字幕可选但默认纯中文

### 科普视频管线(kinetic_demo)

- 管线:`kinetic_demo/make_model_video.py`——content/<slug>.json(文案+场景数据)→
  CosyVoice 配音(东方浩然说书音色)→ build 时间轴/字幕 → Playwright 逐帧 → ffmpeg 成片
- 舞台选择:content 的 `stage` 字段 > `<slug>_stage.html` > `model_stage.html`(通用模板);
  每个系列应有专属视觉(月夜/黎明/水墨/新闻站…),禁止跨系列复用同一舞台(同质化教训)
- 已有舞台:glm_stage(GLM 原版)/ kimi-k3_stage(月夜星野+月相)/ qwen3.8_stage(黎明绸缎)/
  news_stage(AI 快讯栏目)/ k3_desktop_stage(拟真桌面)
- 人物音色档案:`src/voice_casting.py` + work/studio/voice-castings.json,同一人物跨片复用
- **不做幕后彩蛋环节**(2026-09 用户定):解说词来源/制作方式自曝段永久移除
- 坑:改文案后必须清 <slug>_video/parts* 再跑(配音断点续跑会跳过旧缓存);stage 文件名必须等于 slug

### 手绘/推演系列(src/mzx_story、src/mzx_series,2026-09 新增)

- 复用 gpt_explainer.render 的配音拼装/时间轴/字幕/探测管线;Pillow 逐帧流式喂 ffmpeg
  (15fps 绘制复制成 30fps),不落帧盘,成片在 D 盘临时目录
- **B-roll 编排原则**(2026-09-12 讨论定):**插画讲"人",图解讲"势"**——插画保持连续铺满
  作画面主体;解说讲到地理移动/多方对峙/数字对比的段落,该段时间划给矢量图解
  (ep01 模式:diagram 段与插画段段级互斥、首尾相接、0.12×段长交叉淡化、同一羊皮纸色系,
  机制现成免改渲染)。图解段长驻 ≥20s,每集 0~4 个按内容定不硬凑;ep09~24(北京保卫战、
  庚戌之变、倭乱海防、三大征)天然多"势"段。多人插画分不清谁是谁 → **cast 人名标注**
  (用户定:AI 直接画进图里):broll 节拍加 `"cast": ["左·于谦", "右·朱祁钰"]`
  (位置前缀 左/中/右,单人可省),generate.py 对 cast 节拍去掉 broll_style 的 no text
  约束、追加羊皮纸签+楷书墨字指令,**强制 ICU 后端**(SDXL 画不了中文),生成后 RapidOCR
  回读校验姓名全部命中(`rapidocr_onnxruntime`,.venv-ocr 自带),未命中自动重生成,连续
  3 次失败不落正式文件名(渲染端缺图报错门禁拦截),末张留 `<name>.reject.png` 人工检查;
  manifest 记 `cast_check`。prompt 纪律:多人节拍必须写服色+左右锚点(绯红官服居左/明黄
  龙袍居右),保证标注位置词与画面一致。**节拍 at/hold 顺序必须跟解说提及顺序对齐**
  (ep-09 s6 曾反排:字幕讲"王阳明重写战报"画面却是"再抓一遍",用户指出;av_qc 的
  frame_manifest 就是逐 4s 画面-字幕配对清单,排产后必须过一遍)。试稿实证(2026-09-12,
  `work/probe-cast-labels.py`):
  gpt-image-2 中文姓名签 6/6 OCR 全命中、位置全对、羊皮纸签+红印章完全融入系列画风
  (含朱祁镇/朱祁钰兄弟同袍最难例);OCR 门禁对繁体/错字不放过(歷→历 类错字必须重生成)。
- **B-roll 分镜层**(2026-09-10 用户定):故事章节由 AI 分镜**连续铺满整章**(`broll:[{prompt,at,hold}]` 按解说句子节拍切分,段间 AI↔AI 交叉淡化,矢量层不再闪现);**图解节拍** `{"type":"diagram","at","hold"}` 让矢量图解(地图/价格/战线)长驻整段解说时长、可读性优先;章节氛围背景板 `bg` 垫底 + 系列级 `broll_style` 前缀;`src/broll/generate.py` 批量生成(fingerprint 缓存,缺图渲染报错)。**生图双后端**:本机 ComfyUI(WSL ROCm, SDXL, 127.0.0.1:8188, 零成本, 服务丢了自动拉起)优先, ICU gpt-image-2 计费回退(`--backend`);权重 `~/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors`。 **大明演义系列定档纯 ICU 出图**(内容 JSON `broll_backend:"icu"`,用户定:ICU 额度不足即停止,不用本地模型降级——除非本地调教到 gpt-image-2 同等质量)坑:给 cosy-gpu-venv 装 ComfyUI 依赖必须 `grep -v -i '^torch'` 过滤并关键包 `--no-deps`,否则 pip 会把 CUDA 版 torch 顶掉 ROCm 版(踩过,修复脚本 `src/broll/restore_torch.sh`)。**不加"AI 插画"角标**(用户定,视作水印);**字幕单行**(cue ≤16 字、优先在 ，。：、 断句整句显示不折行不截断,字幕带压缩到 168px,舞台加高到 912)。适用:历史故事线;新闻类(苹果速览)只用官方实拍图,引文/数据页不用 AI 图
- **Qwen-Image 本地试稿引擎**(2026-09-11 部署;**用户定:生产生图仍只用 ICU gpt-image-2**,
  Qwen 不接入 generate.py 后端路由,仅作零成本试稿/中文文字封面辅助):ComfyUI-GGUF +
  Qwen-Image-2512 GGUF Q4_K_S + fp8 文本编码器(device=cpu)+ VAEDecodeTiled;7800XT
  16GB 完整驻留,热态 2.5 分钟/张,中文标题字 8/8 全对;羊皮纸平涂配方与坑全记录
  在 `work/probe-qwen-image/README.md`(要点:风格硬约束前置,忌 cinematic lighting,
  VAE 必须 Tiled 解码,启动带 HSA_ENABLE_DXG_DETECTION=1,WSL 空闲整机会回收)
- **明朝故事线**(`src/mzx_story/vector_render.py`):准确、生动的矢量动画图解——真实地理投影、角色服化道、镜头随叙事推进；统一 1920×1080 三段式版面(顶部信息区/中部内容舞台/底部字幕安全带)，字幕和场景不得互相侵入。所有场景坐标使用最终像素，超采样只在渲染器内部执行；每章 8 个时间点抽样并输出 `layout_report.json`，通过布局门禁后才渲染成片。镜头语义=舞台窗口(中心 cx,cy + 缩放 zoom,窗口高 700/zoom)，**每场镜头窗口必须覆盖本场全部内容**(曾因按 1080 取景把燕王标记整体裁掉)。人物头底必须搭在袍肩上(hy=y-0.675h)。多音字纠音字段 `tts_narration` 保留作兜底(如"静难之役"锁 jìng nàn)，字幕仍显示正确写法。**配音引擎已切 CV3**(2026-09-12 用户验收)：ep-08 CV3 版 QC PASS(纯 narration 原文零纠音,朱祐樘/斋醮 直读正确,整体 hard CER 3.01%)，`prepare.py` 固定走 `cv3_generate_voice.py`+endofprompt 前缀，指纹含引擎标记(换引擎自动作废旧 parts)；其余集仍是 CV2 旧成品，重渲即转新链路；已知小瑕疵:ep-08 边防章一处"弘治"读偏(近似"红日")，av_qc 转写可复查。封面用 `src/mzx_story/make_cover.py`(gpt-image-2 出图+本地合成标题，key 只读 OPENAI_API_KEY，原图按指纹缓存+manifest)。音色固定 **doubao-京腔侃爷**(2026-09 用户定,写进内容 JSON `voice` 字段)。旧白板实现 `doodle_render.py` 仅保留作历史资产，不作为当前默认链路。
- **毛选推演线**(`src/mzx_series/render.py`):战略批注风(米黄文件纸+红蓝推演色+印章),
  音色东方浩然;来源标注+原文引用角标的可信度体系每集必备
- 换音色/换文案=指纹变化:清 <OUT>/tts_fingerprint.txt 和 parts 后重跑 prepare
- 样片与音色小样归档 NAS `临时-试听/`;通过验收才进成品库
- **发布前 QC 门禁**(`src/av_qc.py`,work/.venv-ocr 环境):ASR 回环校验——成品音频用本地
  faster-whisper(large-v3-turbo,模型在 `work/models/faster-whisper-large-v3-turbo`)转回
  文字与 TTS 期望文本逐字比对;**hard CER**(剔除同音转写,只计异音替换+缺字)整体 ≤6%、
  单章 ≤12% 为 PASS,可疑错读带时间戳全量列出供复核;并输出逐帧"画面-字幕-节拍"配对
  清单(frame_manifest)供审片。**必须逐章音频单独转写**(整段转写的 whisper 长段会跨章
  串扰,CER 虚增到 30%+);同音字替换(静→靖)是 ASR 正常选字,不计错;
  **whisper 静音尾段幻觉过滤**(`is_hallucination`,"请不吝点赞…明镜与点点"/"优优独播剧场
  YoYo"等频道水印串)在拼 CER 前丢弃——ep-09 尾部 ~0.7s 静音曾幻觉出 19 字推广串,
  把该章 hard CER 顶到 16.9% 假 FAIL(ep-08 修复脚本 BLACKLIST 同源问题的前身);
  **成片逐章尾句转写核对必做**(2026-09-12 教训):av_qc 逐章转写的是原始 parts,
  测不到 assemble+polish 环节的损伤——ep08 s7"好生教导"被 polish 的停顿压缩从段尾
  一刀切剁成"要好生"(用户听出),波形互相关+成片局部转写才定位。根因:
  `_polish_frames` 停顿压缩对每个超长停顿 `audio[:len-超出]` 砍尾部,停顿越多的章被砍
  越多;已改为在停顿位置拼接收窄(回归测试 tests/test_gpt_explainer_render.py),
  ep08-cv3 重渲修复。诊断手法:ffmpeg 抽成片末段转写 + 原始件/成片互相关对齐切点

# Windows 坑

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
