# 豆包课程配音助手

适用于 Chrome / Edge 的 Manifest V3 扩展。它包含两组能力：

- 抓取豆包网页朗读所需的 Cookie、设备参数和 `api_app_key`，生成项目根目录 `.env`。
- 在当前豆包对话中读取课程分块 TXT，按顺序自动发送并等待每条回复完成。

自动发送使用豆包页面自己的输入框和发送动作，不直接调用私有发消息接口，也不构造
`a_bogus`。登录、CAPTCHA 和安全验证仍由用户在浏览器中完成。

## 安装或更新

1. Edge 打开 `edge://extensions`，Chrome 打开 `chrome://extensions`。
2. 开启“开发者模式”。
3. 首次安装选择“加载已解压的扩展”，目录为 `src/captcha-extension/`。
4. 更新源码后，在扩展卡片上点击“重新加载”，随后刷新豆包对话页。

浏览器扩展安装属于高权限操作，应只加载本仓库中的目录。

## 自动发送分块

1. 运行 `make_episode.py --episode N --step prep` 生成：

   ```text
   work/ep-NN/chunks/
   ├── manifest.json
   ├── 01.txt
   ├── 02.txt
   └── ...
   ```

2. 打开目标豆包对话并保持登录。
3. 打开扩展，在“分块发送”中同时选择 `manifest.json` 和全部 TXT。
4. 点击“检测页面”，确认找到消息输入框。
5. 点击“开始发送”并确认队列。

Popup 可以关闭。Service Worker 只管理持久状态，真正的等待与页面操作由对话页中的
content script 执行。每个分块依次经过：

```text
填入并全文校验
→ 点击页面发送动作
→ 确认输入框清空
→ 确认新的用户消息出现
→ 等待该回复新增“朗读”按钮
→ 进入下一块
```

队列支持暂停、继续、停止和跳过当前项。暂停发生在当前回复完成之后；停止不会撤回
已经发送的内容。

## 异常恢复

- 输入框已有草稿：队列停止，避免覆盖。
- 页面出现 CAPTCHA / 安全验证：队列停止，完成验证后重试当前项。
- 页面刷新发生在发送或等待回复期间：状态标记为 `uncertain_delivery`。先在页面确认
  当前分块是否已经送达；未送达时选择“重试/继续”，已送达时选择“跳过当前”。
- 当前对话与队列启动时的 URL 不同：扩展拒绝继续。
- 豆包五分钟内没有出现新回复的“朗读”按钮：队列停止并保留当前索引。

“导出记录”会下载不含正文的 JSON sidecar，内容包括会话 URL、分块文件名、文本指纹、
发送/回复时间和最终状态，可用于排查错配。扩展不能直接改写工作区中的 manifest。

## 朗读凭据

扩展会抓取：

- `DOUBAO_COOKIE`，包括 HttpOnly 登录 Cookie。
- `DOUBAO_API_APP_KEY`，来自朗读 WebSocket URL。
- `DOUBAO_DEVICE_ID`、`DOUBAO_UID`、`DOUBAO_WEB_TAB_ID`、`DOUBAO_WEB_ID`、
  `DOUBAO_TEA_UUID`。

缺少 `api_app_key` 时，在豆包页面点击任意回复的“朗读”按钮，再刷新扩展状态。复制的
`.env` 含登录凭据，只能保存在项目根目录，不能提交或分享。

## 调试

- Popup：在扩展图标上右键并检查弹出式窗口。
- Service Worker：在扩展管理页点击“Service Worker”。
- Content Script：打开豆包页面开发者工具，在 Console 查看
  `[豆包课程配音助手]` 日志。
- 页面检测失败时，先重新加载扩展并刷新豆包标签页。

静态检查：

```powershell
node --check src/captcha-extension/background.js
node --check src/captcha-extension/relay.js
node --check src/captcha-extension/inject.js
node --check src/captcha-extension/popup.js
node --test src/captcha-extension/sender-core.test.cjs
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
