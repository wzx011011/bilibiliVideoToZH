// 豆包凭据抓取 — 后台 service worker
// 抓 cookie（含 HttpOnly）+ URL 参数 + api_app_key（WebSocket hook）

const DOUBAO_COOKIE_DOMAIN = "https://www.doubao.com/";
const URL_FIELDS = {
  device_id: "DOUBAO_DEVICE_ID",
  web_id: "DOUBAO_WEB_ID",
  tea_uuid: "DOUBAO_TEA_UUID",
  web_tab_id: "DOUBAO_WEB_TAB_ID",
  uid: "DOUBAO_UID",
};

function parseQuery(url) {
  try {
    const params = {};
    for (const [k, v] of new URL(url).searchParams.entries()) {
      if (!params[k]) params[k] = v;
    }
    return params;
  } catch { return {}; }
}

async function refreshCookie() {
  try {
    const cookies = await chrome.cookies.getAll({ url: DOUBAO_COOKIE_DOMAIN });
    const cookieStr = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    if (cookieStr) {
      const data = await chrome.storage.local.get("creds");
      const creds = data.creds || {};
      creds.DOUBAO_COOKIE = cookieStr;
      await chrome.storage.local.set({ creds });
    }
  } catch (e) { console.error("cookie 抓取失败", e); }
}

chrome.webRequest.onBeforeRequest.addListener(
  (details) => { processUrl(details.url); },
  { urls: ["*://*.doubao.com/*", "wss://*.doubao.com/*"] }
);

function processUrl(url) {
  const params = parseQuery(url);
  if (url.includes("frontier-audio-web-ws") || url.startsWith("wss://")) {
    if (params.api_app_key) {
      chrome.storage.local.get("creds").then((data) => {
        const creds = data.creds || {};
        creds.DOUBAO_API_APP_KEY = params.api_app_key;
        chrome.storage.local.set({ creds });
      });
    }
  }
  const updates = {};
  let hasAny = false;
  for (const [param, envKey] of Object.entries(URL_FIELDS)) {
    if (params[param]) { updates[envKey] = params[param]; hasAny = true; }
  }
  if (hasAny) {
    chrome.storage.local.get("creds").then((data) => {
      Object.assign(data.creds || {}, updates);
      chrome.storage.local.set({ creds });
    });
  }
}

chrome.cookies.onChanged.addListener((changeInfo) => {
  if (changeInfo.cookie.domain.includes("doubao.com") && !changeInfo.removed) refreshCookie();
});
chrome.runtime.onInstalled.addListener(refreshCookie);
chrome.runtime.onStartup.addListener(refreshCookie);

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "capturedUrl" && msg.payload?.url) processUrl(msg.payload.url);
  if (msg.type === "getCreds") {
    refreshCookie().then(async () => {
      sendResponse((await chrome.storage.local.get("creds")).creds || {});
    });
    return true;
  }
});

refreshCookie();
