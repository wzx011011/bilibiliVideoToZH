# 豆包朗读凭据抓取扩展

Chrome/Edge 扩展（MV3），自动抓取豆包网页版朗读所需的全部凭据，一键生成 `.env`。

## 功能

抓取 7 个凭据：
- **cookie**（含 HttpOnly 的 sessionid，用 `chrome.cookies` API）
- **api_app_key**（WebSocket hook 拦截朗读 wss 连接 URL）
- **device_id / uid / web_tab_id / web_id / tea_uuid**（webRequest 抓 URL 参数）

## 安装

1. `edge://extensions` → 开启开发者模式 → 加载已解压扩展 → 选本目录
2. 登录 doubao.com，随便浏览
3. 点扩展图标查看抓取状态
4. 缺 api_app_key 时点豆包朗读按钮 🔊
5. 全绿后点"复制 .env 内容"→ 粘贴到项目根 `.env`

## 文件

```
captcha-extension/
├── manifest.json   MV3 清单
├── background.js   抓 cookie + 处理 URL 参数
├── relay.js        content script（ISOLATED），动态注入 inject.js
├── inject.js       MAIN world：hook WebSocket/fetch/XHR
├── popup.html/js   展示状态 + 生成 .env
└── icons/
```
