# 豆包课程配音助手

适用于 Chrome / Edge 的 Manifest V3 扩展。它包含两组能力：

- 抓取豆包网页朗读所需的 Cookie、设备参数和 `api_app_key`，可复制为项目根目录 `.env`。
- 在当前豆包对话中读取课程分块 TXT，按顺序自动发送并等待每条回复完成。
- 全部回复完成后，将本次发送记录交给本机桥接服务，自动生成音频、字幕和视频。

自动发送使用豆包页面自己的输入框和发送动作，不直接调用私有发消息接口，也不构造
`a_bogus`。登录、CAPTCHA 和安全验证仍由用户在浏览器中完成。

## 安装或更新

1. Edge 打开 `edge://extensions`，Chrome 打开 `chrome://extensions`。
2. 开启“开发者模式”。
3. 首次安装选择“加载已解压的扩展”，目录为 `src/captcha-extension/`。
4. 更新源码后，在扩展卡片上点击“重新加载”，随后刷新豆包对话页。

浏览器扩展安装属于高权限操作，应只加载本仓库中的目录。
2.1 版本新增 `http://127.0.0.1/*` 权限，仅用于访问本仓库的本地构建服务。

## 自动发送分块

1. 后台启动本地构建服务。重复执行不会启动多个实例：

   ```powershell
   python src/doubao_bridge.py start
   ```

   Windows 也可以双击项目根目录的 `start-doubao-bridge.cmd`。

   健康检查地址：`http://127.0.0.1:8765/api/health`。

2. 首次使用或凭据更新后，在扩展的“朗读凭据”中点击“复制 .env”，保存到项目根目录
   `.env`。构建服务只检查字段是否就绪，不会通过 HTTP 接收 Cookie。

3. 运行 `make_episode.py --episode N --step prep` 生成：

   ```text
   work/ep-NN/chunks/
   ├── manifest.json
   ├── 01.txt
   ├── 02.txt
   └── ...
   ```

4. 打开目标豆包对话并保持登录。
5. 打开扩展，在“分块发送”中同时选择 `manifest.json` 和全部 TXT。
6. 点击“检测页面”和“检测构建服务”。
7. 保持“完成后生成音频和视频”勾选，点击“开始发送”。

Popup 可以关闭。Service Worker 只管理持久状态，真正的等待与页面操作由对话页中的
content script 执行。每个分块依次经过：

```text
填入并全文校验
→ 点击页面发送动作
→ 确认输入框清空
→ 确认新的用户消息出现
→ 等待该回复新增“朗读”按钮，并确认回复文本稳定
→ 进入下一块
```

队列支持暂停、继续、停止和跳过当前项。暂停发生在当前回复完成之后；停止不会撤回
已经发送的内容。

全部分块必须是 `done` 才会进入本地构建。最后一个分块若被跳过，发送队列虽然结束，
构建服务仍会拒绝生成不完整成品。构建状态会显示为“已排队”“正在生成”“生成完成”
或“生成失败”；失败后可点击“重试构建”。生成结果包括：

```text
work/ep-NN/episode-NN-audio.mp3
work/ep-NN/episode-NN.srt
videos/episode-NN.mp4
episodes/ep-NN/               归档的音频、字幕、manifest 和 TXT
```

## 异常恢复

- 输入框已有草稿：队列停止，避免覆盖。
- 页面出现 CAPTCHA / 安全验证：队列停止，完成验证后重试当前项。
- 页面刷新发生在发送或等待回复期间：状态标记为 `uncertain_delivery`。先在页面确认
  当前分块是否已经送达；未送达时选择“重试/继续”，已送达时选择“跳过当前”。
- 当前对话与队列启动时的 URL 不同：扩展拒绝继续。
- 豆包五分钟内没有出现新回复的“朗读”按钮：队列停止并保留当前索引。

“导出记录”会下载不含正文的 JSON sidecar，内容包括会话 URL、分块文件名、文本指纹、
发送/回复时间、构建状态和最终状态，可用于排查。自动构建时，本地桥接服务会把经过
manifest 和指纹校验的记录保存为 `work/ep-NN/doubao-send.json`。

Python 不再按“最近回复”猜测自动任务。它会使用会话 ID、TXT 指纹、发送时间窗口，
以及机器人回复里的 question ID 关联原始用户消息；任何分块缺失、重复或跨会话都会
中止。每块音频成功后立即原子更新 manifest，重试时可从已有音频继续。

## 朗读凭据

扩展会抓取：

- `DOUBAO_COOKIE`，包括 HttpOnly 登录 Cookie。
- `DOUBAO_API_APP_KEY`，来自朗读 WebSocket URL。
- `DOUBAO_DEVICE_ID`、`DOUBAO_WEB_TAB_ID`、`DOUBAO_WEB_ID`、`DOUBAO_TEA_UUID`，
  来自豆包页面请求；`DOUBAO_UID` 从登录 Cookie 的 `multi_sids` 自动解析。

缺少 `api_app_key` 时，在豆包页面点击任意回复的“朗读”按钮，再刷新扩展状态。复制的
`.env` 含登录凭据，只能保存在项目根目录，不能提交或分享。

自动构建时，凭据不会通过 HTTP 传输；桥接只从项目 `.env` 或本地进程环境读取，
任务 JSON 和发送 sidecar 不保存 Cookie。桥接服务固定仓库根、集数范围和构建命令，
客户端不能传入命令或任意文件路径。

## 调试

- Popup：在扩展图标上右键并检查弹出式窗口。
- Service Worker：在扩展管理页点击“Service Worker”。
- Content Script：打开豆包页面开发者工具，在 Console 查看
  `[豆包课程配音助手]` 日志。
- 页面检测失败时，先重新加载扩展并刷新豆包标签页。
- 构建服务检测失败时，运行 `python src/doubao_bridge.py start`，再点击“检测构建服务”。
- 构建失败日志位于 `work/doubao-bridge/jobs/<run-id>.log`。

静态检查：

```powershell
node --check src/captcha-extension/background.js
node --check src/captcha-extension/relay.js
node --check src/captcha-extension/inject.js
node --check src/captcha-extension/popup.js
node --test src/captcha-extension/sender-core.test.cjs
$env:PYTHONPATH='src'; work/.venv-ocr/Scripts/python -m pytest tests/test_doubao_automation.py -q
```

## 文件

```text
captcha-extension/
├── manifest.json
├── sender-core.js          纯队列逻辑和导出格式
├── background.js           凭据、队列状态与标签页绑定
├── relay.js                页面发送状态机
├── inject.js               MAIN world 网络 URL 捕获
├── popup.html / popup.js   队列与凭据 UI
└── sender-core.test.cjs
```

本地部分：

```text
src/doubao_bridge.py        回环 HTTP 服务、任务校验和异步构建
src/make_episode.py         精确匹配、朗读、音频/字幕/视频生成
```
