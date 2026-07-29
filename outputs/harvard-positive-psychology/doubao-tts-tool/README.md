# 豆包朗读音频提取工具

把网页版豆包(www.doubao.com)的"朗读"功能,**自动化**地调出来,把任意一条豆包回复转成音频文件(.ogg)保存。

> 通过逆向豆包网页版的 WebSocket 朗读协议实现。无需官方 API,无需破解签名。

---

## 一、它能做什么

| 功能 | 命令 | 说明 |
|---|---|---|
| 列出最近回复 | `python doubao_reader.py list` | 拉取账号下最近的豆包对话回复(带文本预览、时间) |
| 朗读单条 | `python doubao_reader.py read 5` | 把第 5 条回复朗读成 `.ogg` 音频 |
| 批量朗读 | `python doubao_reader.py read-all 10` | 批量朗读最近 10 条(已读过的自动跳过) |
| 交互菜单 | `python doubao_reader.py` | 图形化菜单,一步步操作 |

**适用场景**:你想把豆包已经生成的某条回复(比如它帮你整理的字幕、文稿)**转成语音音频**保存下来。

---

## 二、快速开始(3 步)

### 第 1 步:安装依赖
```bash
pip install websockets requests
```

### 第 2 步:填写账号信息
打开 `doubao_reader.py`,修改顶部配置区的 **`COOKIE`**(必填,其它设备参数一般不用改):
```python
COOKIE = "你的 cookie 串"   # 见下方"如何获取 cookie"
```

### 第 3 步:运行
```bash
# 方式 A:交互菜单(推荐新手)
python doubao_reader.py
# 然后输入 list → 看列表 → 输入 read 序号

# 方式 B:直接命令
python doubao_reader.py list       # 先列出
python doubao_reader.py read 3     # 朗读第 3 条
```

音频会保存到 `audio_out/` 目录,文件名格式:`doubao_时间_消息ID.ogg`。

---

## 三、如何获取 cookie(关键)

朗读协议需要登录态,通过 cookie 鉴权。获取方法:

1. 用 Chrome / Edge 打开 https://www.doubao.com 并**登录**
2. 按 `F12` 打开开发者工具 → **Network**(网络)标签
3. 在豆包页面随便点一下(或刷新),让请求产生
4. 在请求列表里找任意一个发往 `www.doubao.com` 的请求,点开它
5. 右侧 **Headers** → 找到 **Request Headers** 里的 `Cookie:` 字段
6. **整段复制** cookie 值,粘贴到脚本的 `COOKIE = "..."` 里

**最少需要这几个字段**(脚本会用到):
- `sessionid`(或 `sid_tt`)—— 登录态核心
- `ttwid` —— 设备指纹
- `passport_csrf_token` —— CSRF 防护

> 建议直接粘贴完整 cookie 串,最稳。

---

## 四、工作原理(协议逆向说明)

### 4.1 整体流程

```
你的账号(cookie)
       │
       ▼
┌─────────────────────────────────────────┐
│ ① 列出消息接口(HTTP POST)              │
│    www.doubao.com/im/chain/recent_conv  │
│    → 拿到 message_id / reply_unique_key │
└─────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ ② 朗读接口(WebSocket)                  │
│    wss://frontier-audio-web-ws.doubao   │
│    .com/api/v2/sami/voicegenie          │
│    → 流式返回 ogg 音频帧                │
└─────────────────────────────────────────┘
       │
       ▼
    .ogg 音频文件
```

### 4.2 消息列表接口(HTTP)

**用途**:拉取账号下的豆包对话历史,从中提取朗读所需的标识符。

```
POST https://www.doubao.com/im/chain/recent_conv?aid=497858&...
Content-Type: application/json
Cookie: <你的cookie>

{
  "cmd": 3200,
  "uplink_body": {
    "pull_recent_conv_chain_uplink_body": {
      "limit": 20, "message_count_per_conv": 10, ...
    }
  }
}
```

**返回**:`downlink_body.pull_recent_conv_chain_downlink_body.cells[]`,每个 cell 含一个会话,会话里的 `messages[]` 每条消息带这些关键字段:

| 字段 | 路径 | 用途 |
|---|---|---|
| `message_id` | message.message_id | 朗读目标 |
| `bot_reply_message_id` | message.bot_reply_message_id | 对应的提问 ID(=question_id) |
| `conversation_id` | message.conversation_id | 会话 ID |
| `section_id` | message.section_id | 段落 ID |
| `reply_unique_key` | message.**ext**.reply_unique_key | ⭐ 朗读校验关键,每次回复都不同 |
| `tts_content` | message.tts_content | 该回复的朗读原文 |
| `user_type` | message.user_type | `2`=豆包回复,`1`=你的提问 |

> ⚠️ `reply_unique_key` 藏在 `ext` 字段里(JSON 字符串),需要二次解析。这是朗读校验的关键,无法凭空构造,必须从实际回复里抓。

### 4.3 朗读接口(WebSocket,核心)

**连接地址**:
```
wss://frontier-audio-web-ws.doubao.com/api/v2/sami/voicegenie
    ?api_app_key=<你的 API_APP_KEY,见 .env>
    &namespace=VoiceGenie
    &aid=497858
    &device_id=<你的设备ID>
    &...(其它设备参数)
```

**鉴权**:仅靠 URL 上的 `api_app_key` + 设备参数 + WebSocket 握手头(Origin/Cookie)。**没有动态签名**(这是能复刻的关键)。

**通信协议**:Protobuf 二进制(不是 JSON)。连接后**依次发送三条消息**:

| 序号 | 命令 | 字段 | payload |
|---|---|---|---|
| 1 | `StartTask` | field2=appkey, field3="VoiceGenie", field5="StartTask" | `{}` |
| 2 | `StartSession` | + field6=会话参数JSON, field8=task_id | 含 message_id、音色等 |
| 3 | `StartTTS` | 同上 | 真正发起合成 |

**Protobuf 字段映射**(手动编码,无需 .proto 文件):
```
field 2 (wire type 2): api_app_key     <你的 API_APP_KEY>
field 3 (wire type 2): namespace       "VoiceGenie"
field 5 (wire type 2): command         "StartTask" / "StartSession" / "StartTTS"
field 6 (wire type 2): payload         JSON 字符串
field 8 (wire type 2): task_id         UUID
```

**服务端返回**(二进制帧):
```
field 4: 状态    "TaskStarted" → ... → "TTSEnded"(结束信号)
field 6: 状态描述 "OK"
field 8: 音频数据 ogg 流(每帧拼接即得完整 ogg)
```

### 4.4 关键技术点

1. **`chat_tts` 模式**:客户端**只发 message_id,不发朗读文本**。服务端自己去数据库取该条回复的文本再合成。所以本工具只能朗读"豆包已生成的回复",不能朗读任意自定义文本。

2. **音频格式**:服务端流式返回 **ogg_opus**(48kHz),每帧约 1KB,直接拼接所有 field8 即得合法 ogg 文件。文件头为 `OggS`。

3. **去重**:同一条回复短时间内重复朗读会被服务端拒绝(返回 0 帧)。脚本已处理:批量模式跳过已存在文件;单条失败时等 1~2 分钟再试。

4. **音色**:通过 payload 里的 `tts.speaker` 字段控制。默认桃桃女声 `zh_female_taozi_conversation_v4_wvae_bigtts`,可换成豆包里的其它音色 ID。

---

## 五、配置项详解(从环境变量 / `.env` 读取)

所有账号/设备参数从环境变量或同目录 `.env` 文件读取(复制 `doubao.env.example` 为 `.env` 后填值)。切勿把真实凭据写进源码或提交到 git。

| 环境变量 | 说明 | 是否必填 |
|---|---|---|
| `DOUBAO_COOKIE` | 登录 cookie(完整串) | ⭐ 必填,失效后需重抓 |
| `DOUBAO_DEVICE_ID` / `DOUBAO_WEB_ID` / `DOUBAO_TEA_UUID` | 设备标识 | 必填(来自抓包) |
| `DOUBAO_WEB_TAB_ID` | 浏览器标签页 ID | 必填 |
| `DOUBAO_API_APP_KEY` | 朗读服务 appkey | 必填 |
| `DOUBAO_UID` | 用户 ID | 必填(从 cookie 里来的) |
| `DOUBAO_MESSAGE_ID` / `DOUBAO_CONVERSATION_ID` / `DOUBAO_QUESTION_ID` / `DOUBAO_SECTION_ID` / `DOUBAO_REPLY_UNIQUE_KEY` | 朗读目标标识(`doubao_tts.py` 用) | 必填 |
| `SPEAKER` | 音色 ID(脚本常量) | 可改,换成其它豆包音色 |
| `OUTPUT_DIR` | 输出目录(脚本常量) | 默认 `audio_out` |

---

## 六、常见问题

### Q1:运行报错"没拉到任何回复"
→ Cookie 失效了。重新登录豆包网页,按【三、如何获取 cookie】重抓。

### Q2:朗读时"未收到音频帧"
→ 三种可能:
1. 这条回复刚被朗读过,被服务端去重 → 等 1~2 分钟再试
2. `reply_unique_key` 不对 → 重新 `list` 拉最新数据
3. 该 message_id 不属于当前账号 → 换一条

### Q3:音频文件播不了
→ 文件头应是 `OggS`。Windows 自带"电影和电视"、VLC、PotPlayer 都能放 `.ogg`。转 mp3 用:`ffmpeg -i xxx.ogg xxx.mp3`

### Q4:能朗读任意文本吗?
→ **不能**。这是 `chat_tts`(复读)模式,只能朗读豆包已生成的回复。要朗读任意文本,需用火山引擎官方 TTS API。

### Q5:cookie 多久失效?
→ `sessionid` 约 30 天。建议失效就重抓。

---

## 七、文件清单

```
doubao-tts-tool/
├── README.md              ← 本文档
├── doubao_reader.py       ← 主工具(消息列表 + 朗读,推荐用这个)
├── doubao_tts.py          ← 单条朗读脚本(早期版本,需手动填参数)
└── audio_out/             ← 音频输出目录(运行后自动生成)
```

---

## 八、合规与安全提示

1. ⚠️ **Cookie 是登录凭据,等同账号密码**。不要分享、不要提交到 git、不要发到群里。
2. ⚠️ 本工具通过逆向网页协议实现,属于非官方通道,**可能违反豆包服务条款**,且协议可能随版本变化失效。
3. ⚠️ 请勿用于批量爬取、商业化或任何可能对服务造成压力的场景。
4. ✅ 长期稳定、合规的使用,请走**火山引擎官方语音合成 API**。
