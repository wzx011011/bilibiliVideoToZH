importScripts("sender-core.js");

const DOUBAO_COOKIE_DOMAIN = "https://www.doubao.com/";
const SENDER_KEY = "senderState";
const MAX_LOGS = 100;
const URL_FIELDS = {
  device_id: "DOUBAO_DEVICE_ID",
  web_id: "DOUBAO_WEB_ID",
  tea_uuid: "DOUBAO_TEA_UUID",
  web_tab_id: "DOUBAO_WEB_TAB_ID",
  uid: "DOUBAO_UID",
};

let credsUpdateChain = Promise.resolve();
let senderUpdateChain = Promise.resolve();

function nowIso() {
  return new Date().toISOString();
}

function isDoubaoUrl(value, requireChat = false) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" && url.hostname === "www.doubao.com" &&
      (!requireChat || url.pathname.startsWith("/chat/"));
  } catch {
    return false;
  }
}

function conversationKey(value) {
  try {
    const url = new URL(String(value || ""));
    return url.hostname === "www.doubao.com" && url.pathname.startsWith("/chat/")
      ? `${url.origin}${url.pathname}`
      : null;
  } catch {
    return null;
  }
}

function parseQuery(value) {
  try {
    const url = new URL(String(value));
    if (!url.hostname.endsWith("doubao.com")) return {};
    return Object.fromEntries(url.searchParams.entries());
  } catch {
    return {};
  }
}

function updateCreds(updates) {
  credsUpdateChain = credsUpdateChain.catch(() => undefined).then(async () => {
    const data = await chrome.storage.local.get("creds");
    const creds = { ...(data.creds || {}), ...updates };
    await chrome.storage.local.set({ creds });
    return creds;
  });
  return credsUpdateChain;
}

async function refreshCookie() {
  const cookies = await chrome.cookies.getAll({ url: DOUBAO_COOKIE_DOMAIN });
  const cookie = cookies.map((item) => `${item.name}=${item.value}`).join("; ");
  return updateCreds({ DOUBAO_COOKIE: cookie });
}

async function processUrl(value) {
  const params = parseQuery(value);
  const updates = {};
  if (params.api_app_key) updates.DOUBAO_API_APP_KEY = params.api_app_key;
  for (const [param, envKey] of Object.entries(URL_FIELDS)) {
    if (params[param]) updates[envKey] = params[param];
  }
  if (Object.keys(updates).length) await updateCreds(updates);
}

function defaultSenderState() {
  return {
    runId: null,
    status: "idle",
    phase: "idle",
    items: [],
    index: 0,
    total: 0,
    tabId: null,
    conversationUrl: null,
    delayMs: 5000,
    startedAt: null,
    completedAt: null,
    updatedAt: nowIso(),
    error: null,
    logs: [],
  };
}

async function getSenderState() {
  const data = await chrome.storage.local.get(SENDER_KEY);
  return data[SENDER_KEY] || defaultSenderState();
}

function updateSenderState(patch, logMessage = null, itemUpdate = null) {
  senderUpdateChain = senderUpdateChain.catch(() => undefined).then(async () => {
    const current = await getSenderState();
    const next = { ...current, ...patch, updatedAt: nowIso() };
    if (itemUpdate && Number.isInteger(itemUpdate.index) && next.items[itemUpdate.index]) {
      next.items = next.items.map((item, index) => index === itemUpdate.index
        ? { ...item, ...itemUpdate.patch }
        : item);
    }
    if (logMessage) {
      const currentLogs = Array.isArray(current.logs) ? current.logs : [];
      next.logs = [...currentLogs, { at: nowIso(), message: String(logMessage) }]
        .slice(-MAX_LOGS);
    }
    await chrome.storage.local.set({ [SENDER_KEY]: next });
    return next;
  });
  return senderUpdateChain;
}

async function activeDoubaoTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab?.id || !isDoubaoUrl(tab.url, true)) {
    throw new Error("请先切换到已登录的豆包对话页，再打开扩展");
  }
  return tab;
}

function sendTabMessage(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error("页面脚本未就绪，请刷新豆包页面后重试"));
      } else {
        resolve(response || {});
      }
    });
  });
}

function senderOwnsMessage(sender, state) {
  return sender?.tab?.id === state.tabId &&
    conversationKey(sender.url || sender.tab.url) === conversationKey(state.conversationUrl);
}

async function startSender(items, delayMs) {
  const tab = await activeDoubaoTab();
  const normalized = DoubaoSenderCore.validateItems(items);
  const state = {
    ...defaultSenderState(),
    runId: crypto.randomUUID(),
    status: "starting",
    phase: "probe",
    items: normalized,
    total: normalized.length,
    tabId: tab.id,
    conversationUrl: tab.url,
    delayMs: Math.min(60000, Math.max(1000, Number(delayMs) || 5000)),
    startedAt: nowIso(),
    logs: [{ at: nowIso(), message: `已载入 ${normalized.length} 个分块` }],
  };
  await chrome.storage.local.set({ [SENDER_KEY]: state });
  const response = await sendTabMessage(tab.id, { type: "doubaoSenderStart", state });
  if (!response.ok) throw new Error(response.error || "页面拒绝启动发送队列");
  return state;
}

async function pauseSender() {
  const state = await getSenderState();
  if (!state.runId) throw new Error("没有可暂停的队列");
  const next = await updateSenderState(
    { status: "pausing", error: null },
    "已请求暂停；当前回复完成后暂停",
  );
  if (state.tabId) await sendTabMessage(state.tabId, { type: "doubaoSenderPause", runId: state.runId });
  return next;
}

async function resumeSender() {
  const state = await getSenderState();
  if (!state.runId || state.index >= state.total) throw new Error("没有可继续的分块");
  const tab = await activeDoubaoTab();
  if (conversationKey(tab.url) !== conversationKey(state.conversationUrl)) {
    throw new Error("当前豆包对话与队列绑定的对话不同，已拒绝继续");
  }
  const next = await updateSenderState(
    { status: "running", phase: "resuming", tabId: tab.id, error: null },
    `从 ${state.items[state.index].name} 继续`,
  );
  const response = await sendTabMessage(tab.id, { type: "doubaoSenderStart", state: next });
  if (!response.ok) throw new Error(response.error || "页面拒绝继续队列");
  return next;
}

async function stopSender() {
  const state = await getSenderState();
  const next = await updateSenderState(
    { status: "stopped", phase: "stopped", error: null },
    "队列已停止",
  );
  if (state.tabId) {
    try {
      await sendTabMessage(state.tabId, { type: "doubaoSenderStop", runId: state.runId });
    } catch {
      // The persisted stopped state is authoritative even if the page is gone.
    }
  }
  return next;
}

async function skipCurrent() {
  const state = await getSenderState();
  if (!state.runId || !["paused", "failed"].includes(state.status)) {
    throw new Error("只有暂停或失败状态可以跳过当前分块");
  }
  const index = state.index + 1;
  const completed = index >= state.total;
  return updateSenderState(
    {
      index,
      status: completed ? "completed" : "paused",
      phase: completed ? "completed" : "paused",
      completedAt: completed ? nowIso() : null,
      error: null,
    },
    `已跳过 ${state.items[state.index].name}`,
    { index: state.index, patch: { status: "skipped", error: "用户跳过" } },
  );
}

chrome.webRequest.onBeforeRequest.addListener(
  (details) => { processUrl(details.url).catch(console.error); },
  { urls: ["*://*.doubao.com/*"] },
);

chrome.cookies.onChanged.addListener((changeInfo) => {
  if (changeInfo.cookie.domain.includes("doubao.com")) refreshCookie().catch(console.error);
});
chrome.runtime.onInstalled.addListener(() => refreshCookie().catch(console.error));
chrome.runtime.onStartup.addListener(() => refreshCookie().catch(console.error));

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    switch (message?.type) {
      case "capturedUrl":
        if (!isDoubaoUrl(sender.url || sender.tab?.url) ||
            !["websocket", "fetch", "xhr"].includes(message.payload?.kind)) {
          throw new Error("拒绝非豆包页面的捕获消息");
        }
        await processUrl(message.payload.url);
        return { ok: true };
      case "getCreds":
        return { ok: true, creds: await refreshCookie() };
      case "senderGetState":
        return { ok: true, state: await getSenderState() };
      case "senderProbe": {
        const tab = await activeDoubaoTab();
        return await sendTabMessage(tab.id, { type: "doubaoSenderProbe" });
      }
      case "senderStart":
        return { ok: true, state: await startSender(message.items, message.delayMs) };
      case "senderPause":
        return { ok: true, state: await pauseSender() };
      case "senderResume":
        return { ok: true, state: await resumeSender() };
      case "senderSkip":
        return { ok: true, state: await skipCurrent() };
      case "senderStop":
        return { ok: true, state: await stopSender() };
      case "senderUpdate": {
        const state = await getSenderState();
        if (message.runId !== state.runId || !senderOwnsMessage(sender, state)) {
          throw new Error("发送状态来源无效");
        }
        const allowed = {};
        for (const key of ["status", "phase", "index", "completedAt", "error"]) {
          if (Object.prototype.hasOwnProperty.call(message.patch || {}, key)) {
            allowed[key] = message.patch[key];
          }
        }
        const itemUpdate = Number.isInteger(message.itemIndex) && message.itemPatch
          ? { index: message.itemIndex, patch: message.itemPatch }
          : null;
        return {
          ok: true,
          state: await updateSenderState(allowed, message.log || null, itemUpdate),
        };
      }
      case "senderReady": {
        const state = await getSenderState();
        if (!senderOwnsMessage(sender, state) || !["starting", "running", "pausing"].includes(state.status)) {
          return { ok: true, resume: null };
        }
        if (["sending", "confirming_send", "waiting_reply"].includes(state.phase)) {
          await updateSenderState(
            {
              status: "failed",
              phase: "uncertain_delivery",
              error: "页面在发送过程中刷新；请检查当前分块是否已送达，再选择重试或跳过",
            },
            "页面刷新导致发送状态不确定",
          );
          return { ok: true, resume: null };
        }
        return { ok: true, resume: state };
      }
      default:
        throw new Error("未知扩展消息");
    }
  })().then(sendResponse).catch((error) => {
    console.error(error);
    sendResponse({ ok: false, error: error.message || String(error) });
  });
  return true;
});

refreshCookie().catch(console.error);
