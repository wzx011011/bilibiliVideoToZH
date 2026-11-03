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
- 豆包链(v1)已删除(2026-10-13 用户定"一起清"):doubao_bridge/autosend/pipeline/reader/page_tts/harvest_all/gen_refs、make_episode(课程单集主控)、interview_lib、captcha-extension、dashboard.html、start-doubao-bridge.cmd、2 个 doubao 测试、kinetic_demo 的 doubao 试验产物、.env 豆包凭据——全部可从 git 历史找回;**音色包 work/studio/voices/doubao-* 是活资产**(目录名含 doubao 而已,pipeline_admin 的音色 hint 正常)

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
- 收割工具已随 v1 链删除(2026-10-13);音色包本体在 work/studio/voices/ 完好,跨片复用不受影响。
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

- `mech_demo.html` 机制动画演示(2026-10-13,子会话产出):22s 自动循环演"势"——A 幕《四十六天》(合围收紧+粮道斩断+计日翻牌)+ B 幕《编户齐民》(方块逐户落账+兵粮数字攀升)+ 底部四个图解原语预览(行军箭头/方块落账/疆域填充/计日翻牌);定位=vector_render 图解段动画曲线的方向验证,与现有 Pillow 进度驱动渲染同构,不是新引擎
- `HISTORY_PLAN.md` 中国史全库规划(2026-10-13 定):118 集=溯源4+东周16+秦汉16+大明24(已完成)+魏晋14+隋唐16+两宋12+清16,覆盖良渚~1912;含单集 r4.5 规格、产能公式、待拍板清单——新系列立项/排产以它为准
- `history_map.html` 中国历史结构版图·视频路线图(零依赖自包含网页:朝代主脉/并立时间轴 + 皇权/选官/财税/央地四条制度暗线 + 九大分期卡 + 大明演义 24 集路线(状态来自 OUTLINE.md)+ 5 条候选系列;后续历史系列的选题路线图,状态更新直接改页内数据区);`history_tree.html` 王朝谱系 3D 星图(2026-10-12:零依赖 canvas 自写透视投影,枝条=国祚/金色弧=合流统一/★=大一统/深度轴=南北,拖动旋转+点击王朝开抽屉);`history_geo.html` 舆图沙盘(2026-10-12:宣纸底中国地图+疆域随年代生长消亡的播放沙盘,35+ 疆域多边形为解释性示意(页内已声明非精确疆界,精确见谭其骧图集),年代轴拖动/事件刻度/并立同屏多色/朝代快捷跳转,4 速播放;**海岸线/河流为 Natural Earth 50m 真形**(公有领域,数据抽稀后内嵌 128KB,源数据 work/ne_data/),政权色块 canvas clip 裁进陆地真形;**知识库探索版**(2026-10-12 用户定"历史知识乐园"):**数据共享于 `history_knowledge.js`(38 政权 × 都城/重大事件/人物/著作/经济/制度,改此文件三页即生效,无需注入)**;**三页全量落地**:geo 页(点疆域→六栏卡,事件→跳当年舆图+闪年份;人物→词条页[简介+同代大事+同代人物 chips+返回+维基链];头部按钮→全历史事件总索引 138 条五类筛选,点行=跳年份+开政权卡;著作挂维基检索);tree 页(点王朝枝→同款六栏卡+坐标栏,事件→新标签开 `history_geo.html?y=年份` 跨页联动,人物词条页同款);map 页(点朝代条→原 机制一句/视频机会 保留 + K 六栏合体,事件→时间轴滚动到当年+高亮);geo 页支持 `?y=` 参数直达年代。三页互链共用 ERAS 色板与年代口径,构成"何时/分合/何地"三视图。**性能坑**:clip 用的 Path 必须只用中国域内陆地(NE 数据是全球的,不滤域则 13 块变 300+ 块,每帧 >3s 页面卡死);静态底图(海/网格/陆/河)已做离屏缓存层,每帧只画疆域+标签,现 0.1ms/帧)
- `src/pipeline_admin.py + admin.html` 平台服务与前端;`voice_lib.py` 音色库;`render_original.py` 原片保留渲染;`render_podcast.py` 播客渲染;`whisper_slots.py` 无字幕 ASR 成槽;`narration.py` 语义段落合并;`assemble_narration.py` 旁白+低混音轨;`narration_srt.py` 旁白字幕;`polish_parts.py` 配音精修;`build_podcast_props.py` 播客 props;`podcast_srt.py` 播客字幕;`extract_avatars.py` 播客头像;`compose_bilingual.py` 双语字幕;`make_cover_video.py` 封面渲染;`align_srt_asr.py` ASR 字幕(独立轻量);`align_worker.py`+`label_speakers.py`+`audit_translation.py` 质检三件套;`subtitle_ocr.py` OCR(v2 复用;课程主控 make_episode 已随 v1 链删除);`apple_event/` 发布会监控+速览成片(monitor.py 三源轮询→facts/raw 快照,prepare/render 复用 gpt_explainer 管线换苹果夜皮肤,音色东方浩然);gpt_explainer 渲染器支持 `kind:"image"` 章节(官方产品图左+要点右,带进度推近,图片按 chapter.image 字段引用),产品速览类视频必须配官方产品图(2026-09 用户定)
- `work/studio/` 平台任务目录;`work/voice-clone-demo/` CosyVoice 引擎(gitignore,含 5.3GB 模型勿删;脚本已参数化);`work/video-tools/` ffmpeg
- `youtube/` 下载库(按人物);`downloads/` B站原片;`subtitles/` 历史 OCR;`videos/`+`episodes/` 历史成品归档
- NAS 部署:`deploy-nas-studio.sh`(控制面容器)+ `start-studio-agent.cmd`(PC 代理开机自启)
- 磁盘卫生(2026-10-13):WSL vhdx 已在 C 盘;页面文件迁 C 用 `tools/move_pagefile_to_c.ps1`(管理员+重启);渲染输出走 C:
ender-tmp;D/E/F 为机械盘,索引服务排除见会话记录
- `.env` 豆包凭据已删(v1 链清理);NAS:ssh 别名 `nas` → 192.168.100.78

## 常用命令

```bash
PY=work/.venv-ocr/Scripts/python.exe
$PY src/pipeline_admin.py            # 平台(页面建任务即全自动)
$PY -m pytest tests/ -q              # 测试
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
  news_stage(AI 快讯栏目)/ k3_desktop_stage(拟真桌面);model_stage(通用模板)/stage(默认兜底)。**渲染快照一律落 `kinetic_demo/issues/`**(2026-10-13 清理:删 8 个零引用实验舞台 epic/calm/engine_explode/zcode-audit/ai-news_interactive/xyj_stage/xyj_demo+根目录 rig_demo,快照归档 issues/,make_model_video/render_glm/render_demo 输出路径已同步)
- **AI 快讯 B-roll 规范**(2026-09-24 用户定):模型类要闻必须配真实素材插播——模型官网
  能力展示(官方通稿头图/能力页)+ 第三方评测与社区实测(Artificial Analysis 榜单、
  Simon Willison 鹈鹕骑车同题对比等,用户点名要社区真实案例),禁止 AI 生成图;
  news_stage 支持 story 级 `broll:[{img,cap,src,f1,f2,pos}]`(f 为段内进度窗口,边缘 6%
  渐入渐出,纯帧函数驱动,图片预载并入 `__READY__` 门禁,pos 控制裁切偏移)。素材采集:
  官网页面有 Cloudflare 风控时,用 web_reader 服务端抓通稿拿 og:image/CDN 直链再 curl 下载
  (无头/有头浏览器直截都会被挑战);第三方榜单 Playwright 无头可截,记得 JS 清掉粘性导航
  和翻译弹窗再截。B-roll 图存 `kinetic_demo/broll/<slug>/`,content 里写相对路径;
  网格类近方形素材用 PIL 重组成 1600×640 解读卡(左中文要点+右完整素材,内边距 ≥56px 抗
  1.045 推近裁切),不要裸塞 16:9 窗口
- **模型发布必带第三方评分**(2026-09-24 用户定):新模型发布类要闻必须在 content 里挂
  `scores:{title,rows:[{name,value,rank,ref}]}`(AA 智能指数等真实榜单分,ref:true 为
  参照行半透明);news_stage 渲染成顶部右侧单行评分条(B-roll 插播时隐藏,评分小牌自动
  嵌进素材来源条,两处同一份数据)。评分条别放底部——卡片比预估高会压住它,顶部右侧与
  标题带垂直错位才是安全位。**rows 最多 3 行**(2026-10-07 实证):B-roll 同窗时评分小牌
  嵌进素材来源条,行数多了把左侧素材 cap 挤成竖排窄列;本期主模型一行 + 参照两行,
  broll 的 cap/src 各 ≤16 字,抽帧 QC 专查这一处
- **栏目标签按期取舍**(2026-10-07 用户定):nav 不再固定 8 槽——写稿时先给每条新闻定
  tag,再 `nav=["Intro"]+本期各条去重 tag(按播出顺序)`;高亮靠 tab 文字与 story tag
  全等匹配,tag 不在 nav 里整段无高亮(0928 期「社区风向」教训),同类多条新闻共用一个
  tag 让 nav 更短;tag 取 2~4 字防溢出。惯用 tag 池(从中选,保持栏目辨识度):
  要闻/模型发布/产品动态/安全与隐私/开源生态/行业风向/前瞻传闻
- **AI 快讯每日链**(2026-09-24 用户定,定时任务 automation-d3a45b41):每天早上 8:00 自动
  制作,内容窗口=昨天一整天(T-1),每条新闻必须能确认日期是昨天,更早的旧闻一律不用,
  日期拿不准宁缺毋滥;slug/brand/NAS 文件名都用制作日日期(早报惯例,内容是昨日新闻);
  **质检全过后自动发布 B 站**(2026-09-25 用户定,不再人工门禁):`src/publish_ai_news.py`
  投稿(tid 95,标题「AI快讯·M月D日:主打一,主打二」);归档 NAS
  `临时-试听/AI快讯/`;质检任一项不过则只归档不发布,报告说明原因
- **封面杂志版·安全区**(2026-10-09 用户定,替代 inpaint 复用版):用
  `kinetic_demo/make_cover_magazine.py` 生成——深蓝星空底+左侧大标题+右侧最多 3 张
  当日真实素材缩略卡;**关键内容全部压进中央安全区 x∈[260,1660]**,因为 B 站手机端
  信息流卡片约 4:3,16:9 封面按高撑满后左右各裁 ~12%(2026-10-09 用户实证封面被切);
  改 CONFIG(badge/title_lines/pill/bullets/thumbs)后运行,自动产出
  `cover_feed_preview.jpg`(4:3 中心裁切自检图,发布前必看)
- 人物音色档案:`src/voice_casting.py` + work/studio/voice-castings.json,同一人物跨片复用
- **不做幕后彩蛋环节**(2026-09 用户定):解说词来源/制作方式自曝段永久移除
- **播报稿连字符坑**(2026-09-24 用户反馈):GPT-6/Terminal-Bench/纳维-斯托克斯 这类
  连字符会被 CV3 读出"杠"音;kinetic_demo 的 items 支持可选 `tts` 字段——配音用它、
  字幕用 text 原文,连字符在 tts 里改写为空格或汉字(GPT 6/GPT 五点六/Terminal Bench/
  纳维 斯托克斯);TTS 指纹含 tts 字段,改动自动重录。模型名读音问题优先走这条,
  CV3 拼音 hotfix([j][ǐ] 锁音)留作多音字兜底
- 坑:改文案后必须清 <slug>_video/parts* 再跑(配音断点续跑会跳过旧缓存);stage 文件名必须等于 slug
- **CV3 整段流式合成会崩**(2026-09-26 实证):token2wav 块边界退化报 conv1d
  "Kernel size can't be greater than actual input size",同一文本可稳定复现,
  但按句拆开逐句合成全部可过;make_model_video.run_tts 已内置降级——整段失败
  自动按句(。!?; 切分)重合成并以 0.15s 句间静音拼回,无需人工干预
- B站发布自动链:md5 以最后一次渲染为准,冒烟重渲会改变 H.264 字节(md5 非逐位
  确定),重渲后必须重推 NAS 校准

### 手绘/推演系列(src/mzx_story、src/mzx_series,2026-09 新增)

- **溯源篇 ✅ 全 4 集完成(2026-10-15,NAS 临时-试听/溯源篇)**:S1 良渚 3.36%/S2 二里头 2.6%/S3 甲骨文 5.07%/S4 宅兹中国 2.23% 全 QC PASS。**批量产线定型**:`work/run_batch_detached.py`(断点续批驱动,按 preset 分组 turbo 先 base 后,须用 PowerShell Start-Process 脱离会话跑——ZCode 会话恢复会杀后台任务,cmd start 的中文参数会被 GBK 代码页打穿)+`work/run_chain_sy.py`(链式多集:补图→prod_episode 串联)+`src/mzx_story/generic_painters.py`(矢量退役后的通用兜底,新集 JSON 指它即可免写场景模块)+`src/mzx_story/prod_episode.py`(单集一键:配音→渲染→对齐→终渲→QC→NAS)。**坑**:①prod_episode 链内 NAS 步骤对中文目录名会静默失败(链 EXIT 1 但成片/QC 完好)——归档手动补;②chapter year_val 必须落在 era 区间内,否则纪年角标画矩形反转崩渲染(S4 前1100 西周 era 前1046 曾炸,era 放宽到前1150 解决);③基座 GGUF 偶发 ROCm 采样死锁(冻结在进度条某步永不结束)——整机重置+换种子,cast_gen 超时自愈已内置。
- **溯源篇 S1《满天星斗·良渚》**(2026-10-13,`sy-01-liangzhu.json`+`sy_painters_01.py`,渲染 C:/render-tmp/sy-01,成片 QC hard CER 3.36% PASS,NAS 临时-试听/溯源篇):**全库第 27 集**;考古皮肤(灰米+玉青)首用;史前无具名人物→cast 签机制自然休眠,画面锚=遗迹/器物;9 章制含彩蛋"换考卷"(文明三要素 vs 中国方案);42 张图零失败,vmmem 12.4~12.9GB 实证 13GB 帽子+页面文件迁 C 后批跑全程无卡顿。
- **秦汉前传 ep01《长平之战》**(2026-10-12,`qh-01-changping.json`+`qh_painters_01.py`,成片 165.5s/QC hard CER 4.26% PASS,NAS 临时-试听/秦汉前传):**首集全量 Qwen-Image-2.1-turbo 出图**(8 底板+7 漫画插页,零 ICU);阵营色约定 秦=朱砂/赵=铜绿;坑再现:①av_qc 整轨转写偶发把 166s 并成 11 个超长段→跨章串扰 hard CER 虚高到 56%(假 FAIL),**必须带 --parts-dir 逐章转写真值 4.26%**;②figure mood 只支持 neutral/smirk/sad/worried/angry(无 happy);③wall(x0,x1,y,h) 参数序勿反。**v2 升级(用户反馈"比大明差点意思"后)**:差距诊断=插画密度只有大明 1/3(每章 1 拍)+白底漫画当主画面太素+镜头全静止;修法=**每章 3 拍场景化厚涂插画连续铺满(fit=cover,21 张,配方从"白底漫画分镜"改"full cinematic scenery composition"+gouache 场景画,质量反超 ICU 同题材)+CAMS 全动态(每场推/拉/平移)+插页提示词强制 "Plain red banners without any characters"(2.1 会画真汉字但会挂错军队)**。**东周线人名签补齐(2026-10-23)**:东周线图任务当初漏了 cast 字段,8 集 33 张主角镜头(郑庄公/管仲/伍子胥/孔子/程婴/豫让/李悝/孟子/邹衍等)补「名」签条重生成+重渲归档(md5 8/8 一致)。**补齐流程=build_zq_cast_fix.py 生成签条任务→qwen_cast_gen 直跑(覆盖式重生成不能走缺图驱动的跳过逻辑)→rerender_zq_cast.py 八集渲染/对齐/终渲链(音频未变 QC 沿用)**。规矩:**所有系列图任务单必须含 cast 字段**。
**v3 完全体(用户指出 ①新旧两种风格混切 ②关键人物没名称备注 ③背景露馅)——即"完全用大明工作流+本地模型"**:①根因=qwen_gen 的"跳过已存在"让每章第 1 拍残留第一版白底漫画;②修法=**`work/qwen_cast_gen.py`(大明 cast 纪律移植):人名签提示词(「名」大字签条)+RapidOCR 回读+换种子重生成**,10 个关键人物拍全带签(2.1 写汉字极准,廉颇/白起签全对);坑:**RapidOCR 对 2.1 英文提示词下的艺术体签条误报高(命中 0 但目检全对)——OCR 只当提示,终判目检**(中文提示词下命中率反升);③配方加 "clean coherent background with no stray limbs or distorted figures"+统一色板锚点(warm parchment-toned + vermilion/ochre/celadon)。
**v4(r4 质量完全体,2026-10-13,用户点名"做一下质量提升")**:①**中文提示词**(qwen3vl 编码器中文原生更强,场景/人名签/素旗条款全改中文,OCR 命中率反升)②解剖负向词(extra limbs/bad anatomy/duplicate faces/fused bodies/cropped heads/twisted torso)③出图分辨率 1280x720→**1536x864**④**preset 路由**:每章第 1 拍(定调镜头)走 qwen21 基座(20 步,细节密度最高),其余拍 turbo(速度)⑤**`work/qwen_edit.py` 图生图修复链**(ComfyUI upload/image+VAEEncode+低 denoise 重绘,外科手术式修图——实测只换天色去火光、构图兵阵全保留;治错字旗/露馅,替代整张重roll)⑥插画升**每章 4 拍**(28 张/集,切换点更贴解说语义段;ep02 起写稿时按句子定拍)。**纪年角标上移**(strip yb 140→124,年份 102→86,刻度下探缩短):角标与 contain 卡片模糊底只隔 3px 视觉粘连(用户报"重叠遮挡"),现留 ~20px 纸色呼吸带(像素验证)。r4 配方(28 张中文提示词+13 签+首拍基座)即秦汉线新标准。**图解动画段已试产并否决(2026-10-13)**:ep01 s6 混编(插画+合围/翻牌图解动画)用户观感"质量变低"——图解帧动画与厚涂插画混切显廉价,**秦汉线维持全插画(diagram 节拍留作大明线既有能力,不在秦汉用)**;mech_demo.html 留作原语参考。**节拍-句子对齐机制(工具 `src/mzx_story/align_beats.py`,渲染后必跑)**:按 subtitles.srt 逐句 cue 分组定拍窗,切换落句界;**首拍顶章头、末拍顶章尾(含单拍章全章覆盖)——矢量层彻底不露**(2026-10-14 用户定"放弃帧动画插入":全部章节含收尾/彩蛋一律插画铺满, painters 矢量场景仅作无图兜底,成品中不可见;ep01 s8 矢量收尾已换 4 拍插画,s9 彩蛋统一 2 拍)。**s9 尾声·趣闻(2026-10-13 用户定,每集标配)**:第 9 章讲一个正片外的有趣史料(选题由用户定调:要"内容自洽的冷知识"),叙事收尾后追加约 15s;ep00=商鞅名字的来历(卫鞅→公孙鞅→商鞅,军功爵的活案例),ep01=纸上谈兵是穿越成语(赵括无纸读竹简,成语定型晚到清代);文案句长 ≤44 校验,1 拍插画+矢量小场景,改动需重配 s9 音频(指纹全量变化,prepare 全重跑约 8min/集)。
- **秦汉前传 ep00《商鞅变法》**(2026-10-11 出片,10-13 升 r4 完全体:32 张中文提示词/4 拍·章/首拍基座,成片 QC hard CER 1.96% PASS,NAS 临时-试听/秦汉前传;`qh-00-shangyang.json`+`qh_painters_00.py`,本地渲染目录 D:/qh-ep00):清晰度五件套首次落地——①纪年角标+朝代条(vector_render 新增 `_draw_era_chrome`,内容 JSON 声明 `era`/`year`/`year_val` 即启用,大明各集不带字段行为不变)②出场卡(首出场"名·职务")③数量方块阵(qh_painters 的 `tally()`,编户齐民)④机制收尾卡⑤回调芯片(④⑤已于 2026-10-13 按用户要求**移除**——s8 改叙事收尾与大明一致:ep00 用 4 拍收尾插画(晨光咸阳/秦王按剑/铁骑东出/法典孤灯),ep01 用矢量六国示意+互动提问;`takeaway`/`refs` 字段保留休眠不渲染)。**painters 装载机制**:内容 JSON `"painters": "<py>"` 指向本集场景模块(bind/skin/PAINTERS/CAMS 约定),新系列免改 vector_render 本体;秦汉皮肤=竹纸青灰+朱砂+铜绿(skin 覆盖 vr 全局色,Board 方法定义期绑定的默认色仍需显式传参)。音色 doubao-渊博小叔(试播暂定)。字幕单句 ≤44 字是硬约束(超长句被 cue 截断,ch5 曾中招——写文案时逐句数)。
- **Qwen-Image 漫画风配方已验证**(2026-10-11):扁平漫画+粗描边+夸张表情可出"半小时漫画"效果(s2 徙木/s7 夜逃两张实证),竹简底板配方见 `work/qh_ep00_images.json`;工具 `work/qwen_gen.py`(ComfyUI API:UnetLoaderGGUF+CLIPLoader qwen_image+ModelSamplingAuraFlow shift3.1+euler/simple 20步 cfg2.5+VAEDecodeTiled,本版必填 overlap/temporal_size/temporal_overlap≥4)。坑:CV3 与 ComfyUI 抢 16GB 显存会挂,连跑前 `wsl --shutdown`;ComfyUI 冷启动首张 10 分钟、热态 2.5 分钟,偶发 /history 读超时,重跑脚本按输出文件存在性跳过续跑。
- **Qwen-Image-2.1 本地栈升级完成**(2026-10-11,用户定"一步到位"):官方无"3.0"(搜索以讹传讹),最新代=**Qwen-Image-2.1**(9-14 发布)+2.1-Turbo(10-09)。2.1 是新架构(qwen3vl_8b 文本编码器+新 VAE+QwenImage21Transformer),已升级 ComfyUI 0.35→0.39(git pull,requirements 按 grep -v torch 装清华镜像;workflow-templates 的 media-assets 子包镜像没有,跳过不影响 API)、下载全套模型(diffusion_models/qwen_image_2.1_Q8_0.gguf 7.6G + qwen_image_2.1_turbo_int8_convrot 7.3G、text_encoders/qwen3vl_8b_int8_convrot 9.4G、vae/qwen_image_2.1_vae_bf16、loras/turbo_lora;aria2 走代理,25GB 约 15 分钟)。`work/qwen_gen.py` 已 preset 化:**qwen21-turbo(默认,8 步 CFG1.0,速度 2.5 倍,质量 A/B 实证近基座)**/qwen21(Q8 GGUF,20 步,线条最干净)/qwen2512(一代兜底);CLIPLoader type 仍填 qwen_image,qwen3vl 按权重自动识别。**已知坑**:①turbo 个别 seed 触发 ROCm 采样死锁(seed 202 两次挂满 30 分钟,服务端任务永不结束——症状是客户端超时但 /queue 里一直 running;解法=重启 ComfyUI+换 seed,qwen_gen 超时已自动这么干)②GGUF↔int8 交替跑批时换模型 IO 慢,批量按 preset 分组跑③ComfyUI 重启后 Windows 侧 localhost 转发可能延迟,连不上先 `wsl --shutdown` 再起。
- **本机重度生图会卡死桌面(2026-10-13 实证,根因已修)**:症状=1536×864 批量出图时整机冻结数分钟。根因不是 GPU,是 **`.wslconfig` 曾设 memory=24GB > 物理内存 23GB**——WSL(文本编码器 9.4G 驻 CPU+模型换装双份权重)吃满后 Windows 疯狂换页。已改 **memory=13GB + swap=8GB**;坑:**`autoMemoryReclaim` 键本机 WSL 版本不认,整个 .wslconfig 会被拒载(内存上限一起失效)**,勿加此键;mirrored 模式下 localhostForwarding 告警属正常。内存上限实际效力待下批挂机时以 vmmem 监控验证(动态内存版本 /proc/meminfo 显示不可信)。配套纪律:**重度批任务(基座 20 步/大批量)只在用户确认的挂机窗口跑**;平时统一 turbo;批任务按 preset 分组消除换装churn;长批要挂 WSL 保活会话(`wsl -d Ubuntu-24.04 -- sleep infinity`,空闲整机回收会杀掉 nohup 服务)。另:GPU/WSL 坏态(生成三连超时)普通重启救不回,必须 `wsl --shutdown` 整机重置(qwen_gen 自愈已升级为整机重置)。
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
- **明朝故事线**(`src/mzx_story/vector_render.py`):准确、生动的矢量动画图解——真实地理投影、角色服化道、镜头随叙事推进；统一 1920×1080 三段式版面(顶部信息区/中部内容舞台/底部字幕安全带)，字幕和场景不得互相侵入。所有场景坐标使用最终像素，超采样只在渲染器内部执行；每章 8 个时间点抽样并输出 `layout_report.json`，通过布局门禁后才渲染成片。镜头语义=舞台窗口(中心 cx,cy + 缩放 zoom,窗口高 700/zoom)，**每场镜头窗口必须覆盖本场全部内容**(曾因按 1080 取景把燕王标记整体裁掉)。人物头底必须搭在袍肩上(hy=y-0.675h)。多音字纠音字段 `tts_narration` 保留作兜底(如"静难之役"锁 jìng nàn)，字幕仍显示正确写法。**配音引擎已切 CV3**(2026-09-12 用户验收)：ep-08 CV3 版 QC PASS(纯 narration 原文零纠音,朱祐樘/斋醮 直读正确,整体 hard CER 3.01%)，`prepare.py` 固定走 `cv3_generate_voice.py`+endofprompt 前缀，指纹含引擎标记(换引擎自动作废旧 parts)；其余集仍是 CV2 旧成品，重渲即转新链路；已知小瑕疵:ep-08 边防章一处"弘治"读偏(近似"红日")，av_qc 转写可复查。封面用 `src/mzx_story/make_cover.py`(gpt-image-2 出图+本地合成标题，key 只读 OPENAI_API_KEY，原图按指纹缓存+manifest)。音色固定 **doubao-京腔侃爷**(2026-09 用户定,写进内容 JSON `voice` 字段)。旧白板实现 doodle_render.py 与 ep05 试稿变体(auto/lightning)已于 2026-09-12 清理,需找回看 git 历史(提交 ccedc96)。**Wan2.2 I2V 图生视频已彻底放弃**(2026-09-15 用户定):ep16 全集 24 拍试产实证——纯环境动效段(云/雪/旗/物体)稳定,但人群动作段人物融合崩坏、特写人脸微融,提示词收敛+fp16/cfg/VAE 调参也救不回扁平插画的风格适配性,回到静态插画渲染;`work/wan22_i2v.py`/`wan22_batch_ming1*.py`/`ming16_extract_frames.py` 及 vector_render 的 I2V 分支留作历史资产(按 `work/mzx_story_i2v_frames/<slug>/` 目录存在性触发,目录已删即休眠)。
**产物只留确定性资产**(2026-09-12 用户定;2026-10-13 渲染临时目录迁 C 盘固态 `C:
ender-tmp\<slug>`,验完即删——HDD 只读不写,根治机械盘满载;成片 md5 对照 NAS 后删除),
NAS `临时-试听/明朝故事/` 是唯一成品归档(每集 32 张 broll 图在 `work/broll/<slug>/` 指纹缓存,可复渲)。
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
