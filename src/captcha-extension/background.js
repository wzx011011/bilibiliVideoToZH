importScripts("sender-core.js");

const DOUBAO_COOKIE_DOMAIN = "https://www.doubao.com/";
const SENDER_KEY = "senderState";
const MAX_LOGS = 100;
const BRIDGE_BASE_URL = "http://127.0.0.1:8765";
const BRIDGE_TIMEOUT_MS = 5000;
const BRIDGE_SERVICE = "doubao-build-bridge";
const BRIDGE_VERSION = 1;
const CAPTURE_HOSTS = new Set([
  "www.doubao.com",
  "frontier-audio-web-ws.doubao.com",
]);
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
      (!requireChat || DoubaoSenderCore.isDoubaoChatUrl(url.href));
  } catch {
    return false;
  }
}

function conversationKey(value) {
  return DoubaoSenderCore.conversationKey(value);
}

function parseQuery(value) {
  try {
    const url = new URL(String(value));
    if (!CAPTURE_HOSTS.has(url.hostname) || !["https:", "wss:"].includes(url.protocol)) return {};
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
  const updates = { DOUBAO_COOKIE: cookie };
  const uid = DoubaoSenderCore.doubaoUidFromCookies(cookies);
  if (uid) updates.DOUBAO_UID = uid;
  return updateCreds(updates);
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
    build: DoubaoSenderCore.normalizeBuildOptions({ enabled: false }),
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

async function bridgeRequest(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BRIDGE_TIMEOUT_MS);
  try {
    const response = await fetch(`${BRIDGE_BASE_URL}${path}`, {
      cache: "no-store",
      ...options,
      signal: controller.signal,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      // The status code still produces a useful error below.
    }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `本地构建服务返回 HTTP ${response.status}`);
    }
    return payload;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("连接本地构建服务超时");
    if (error instanceof TypeError) {
      throw new Error("本地构建服务未启动，请先运行 python src/doubao_bridge.py start");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function bridgeHealth(requireCredentials = false) {
  const response = await bridgeRequest("/api/health");
  if (response.service !== BRIDGE_SERVICE || response.version !== BRIDGE_VERSION) {
    throw new Error("127.0.0.1:8765 不是本项目的豆包构建服务");
  }
  if (requireCredentials && !response.credentials_ready) {
    const missing = Array.isArray(response.missing_credentials)
      ? response.missing_credentials.join(", ")
      : "DOUBAO_COOKIE 等字段";
    throw new Error(`自动构建缺少凭据：${missing}。请先复制扩展凭据到项目 .env`);
  }
  return response;
}

function buildFromJob(previous, job) {
  return {
    ...previous,
    status: job?.status || previous.status,
    jobId: job?.job_id || previous.jobId,
    error: job?.error || null,
    output: job?.output_mp4 || previous.output || null,
    logFile: job?.log_file || previous.logFile || null,
    updatedAt: nowIso(),
  };
}

async function submitBuild(state, force = false) {
  const build = state?.build;
  if (!build?.enabled || state.status !== "completed") return state;
  const recoverInterruptedSubmit = force && build.status === "submitting" && !build.jobId;
  if (["submitting", "queued", "running", "completed"].includes(build.status) &&
      !recoverInterruptedSubmit) return state;
  if (build.status === "failed" && !force) return state;
  const allItemsDone = Array.isArray(state.items) && state.items.length > 0 &&
    state.items.every((item) => item.status === "done");
  if (!allItemsDone) {
    return updateSenderState({
      build: {
        ...build,
        status: "failed",
        error: "队列包含跳过或未完成的分块，不能生成完整成品",
        updatedAt: nowIso(),
      },
    }, "本地构建已阻止：队列不完整");
  }

  let current = await updateSenderState({
    build: { ...build, status: "submitting", error: null, updatedAt: nowIso() },
  }, `正在提交第 ${build.episode} 集本地构建`);
  try {
    const payload = {
      ...DoubaoSenderCore.exportableState(current),
      episode: build.episode,
    };
    const response = await bridgeRequest("/api/build", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    current = await updateSenderState({
      build: buildFromJob(current.build, response.job),
    }, `第 ${build.episode} 集已进入本地构建队列`);
  } catch (error) {
    current = await updateSenderState({
      build: {
        ...current.build,
        status: "failed",
        error: error.message,
        updatedAt: nowIso(),
      },
    }, `本地构建提交失败：${error.message}`);
  }
  return current;
}

async function refreshBuildStatus() {
  const state = await getSenderState();
  const build = state.build;
  if (!build?.enabled || !build.jobId) return state;
  try {
    const response = await bridgeRequest(`/api/jobs/${encodeURIComponent(build.jobId)}`);
    const nextBuild = buildFromJob(build, response.job);
    const changed = nextBuild.status !== build.status || nextBuild.error !== build.error ||
      nextBuild.output !== build.output;
    if (!changed) return state;
    const finished = ["completed", "failed"].includes(nextBuild.status);
    return updateSenderState(
      { build: nextBuild },
      finished
        ? `本地构建${nextBuild.status === "completed" ? "完成" : "失败"}`
        : null,
    );
  } catch (error) {
    if (build.error === error.message) return state;
    return updateSenderState({
      build: { ...build, error: error.message, updatedAt: nowIso() },
    });
  }
}

async function reconcileBuildState() {
  const state = await getSenderState();
  const build = state.build;
  if (state.status === "completed" && build?.enabled) {
    if (build.status === "waiting") return submitBuild(state);
    if (build.status === "submitting" && !build.jobId) return submitBuild(state, true);
  }
  return refreshBuildStatus();
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

async function senderMessageIdentity(sender, state, pageUrl = null) {
  if (sender?.tab?.id !== state.tabId) return { owns: false, currentUrl: null };
  let tabUrl = sender.tab?.url;
  if (!DoubaoSenderCore.isDoubaoChatUrl(pageUrl)) {
    try {
      tabUrl = (await chrome.tabs.get(sender.tab.id))?.url || tabUrl;
    } catch {
      // Fall back to the sender metadata if the tab disappears during validation.
    }
  }
  const currentUrl = DoubaoSenderCore.currentChatUrl(sender.url, tabUrl, pageUrl);
  return {
    owns: DoubaoSenderCore.senderOwnsConversation(
      sender.url,
      tabUrl,
      state.conversationUrl,
      pageUrl,
    ),
    currentUrl,
  };
}

async function startSender(items, delayMs, buildOptions = {}) {
  const tab = await activeDoubaoTab();
  const normalized = DoubaoSenderCore.validateItems(items);
  const build = DoubaoSenderCore.normalizeBuildOptions(buildOptions);
  if (build.enabled) await bridgeHealth(true);
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
    build,
    logs: [{ at: nowIso(), message: `已载入 ${normalized.length} 个分块` }],
  };
  await chrome.storage.local.set({ [SENDER_KEY]: state });
  try {
    const response = await sendTabMessage(tab.id, { type: "doubaoSenderStart", state });
    if (!response.ok) throw new Error(response.error || "页面拒绝启动发送队列");
  } catch (error) {
    await updateSenderState({
      status: "failed",
      phase: "control_error",
      error: error.message,
    }, `队列启动失败：${error.message}`);
    throw error;
  }
  return state;
}

async function pauseSender() {
  const state = await getSenderState();
  if (!state.runId) throw new Error("没有可暂停的队列");
  const next = await updateSenderState(
    { status: "pausing", error: null },
    "已请求暂停；当前回复完成后暂停",
  );
  try {
    if (state.tabId) await sendTabMessage(state.tabId, { type: "doubaoSenderPause", runId: state.runId });
  } catch (error) {
    return updateSenderState({
      status: "failed",
      phase: "control_error",
      error: error.message,
    }, `暂停失败：${error.message}`);
  }
  return next;
}

async function resumeSender() {
  const state = await getSenderState();
  if (!state.runId || state.index >= state.total) throw new Error("没有可继续的分块");
  const tab = await activeDoubaoTab();
  if (conversationKey(tab.url) !== conversationKey(state.conversationUrl)) {
    throw new Error("当前豆包对话与队列绑定的对话不同，已拒绝继续（点'重新绑定'切换到当前对话）");
  }
  const next = await updateSenderState(
    { status: "running", phase: "resuming", tabId: tab.id, error: null },
    `从 ${state.items[state.index].name} 继续`,
  );
  try {
    const response = await sendTabMessage(tab.id, { type: "doubaoSenderStart", state: next });
    if (!response.ok) throw new Error(response.error || "页面拒绝继续队列");
  } catch (error) {
    return updateSenderState({
      status: "failed",
      phase: "control_error",
      error: error.message,
    }, `继续失败：${error.message}`);
  }
  return next;
}

async function rebindSender() {
  const state = await getSenderState();
  if (!state.runId) throw new Error("没有活跃的队列可重新绑定");
  const tab = await activeDoubaoTab();
  const newUrl = conversationKey(tab.url);
  if (!newUrl && !DoubaoSenderCore.isInitialChatUrl(tab.url)) {
    throw new Error("当前标签页不是豆包对话页");
  }
  const next = await updateSenderState(
    { conversationUrl: tab.url, tabId: tab.id, status: "paused", error: null,
      phase: "rebound" },
    `队列已重新绑定到当前对话`,
  );
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
  const next = await updateSenderState(
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
  return next.status === "completed" ? submitBuild(next) : next;
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
      case "senderGetState": {
        const state = await reconcileBuildState();
        return { ok: true, state };
      }
      case "bridgeProbe":
        return { ok: true, bridge: await bridgeHealth() };
      case "senderProbe": {
        const tab = await activeDoubaoTab();
        return await sendTabMessage(tab.id, { type: "doubaoSenderProbe" });
      }
      case "senderStart":
        return {
          ok: true,
          state: await startSender(message.items, message.delayMs, message.build),
        };
      case "senderPause":
        return { ok: true, state: await pauseSender() };
      case "senderResume":
        return { ok: true, state: await resumeSender() };
      case "senderRebind":
        return { ok: true, state: await rebindSender() };
      case "senderSkip":
        return { ok: true, state: await skipCurrent() };
      case "senderStop":
        return { ok: true, state: await stopSender() };
      case "buildRetry": {
        const state = await getSenderState();
        if (state.status !== "completed" || !state.build?.enabled) {
          throw new Error("当前队列不满足自动构建条件");
        }
        if (!Array.isArray(state.items) || !state.items.every((item) => item.status === "done")) {
          throw new Error("队列包含跳过或未完成的分块，不能重试构建");
        }
        const reset = await updateSenderState({
          build: { ...state.build, status: "waiting", error: null, updatedAt: nowIso() },
        });
        return { ok: true, state: await submitBuild(reset, true) };
      }
      case "senderUpdate": {
        const state = await getSenderState();
        if (message.runId !== state.runId) {
          throw new Error("发送状态来源无效");
        }
        const identity = await senderMessageIdentity(sender, state, message.pageUrl);
        if (!identity.owns) {
          if (sender?.tab?.id === state.tabId &&
              ["starting", "running", "pausing"].includes(state.status)) {
            const expected = conversationKey(state.conversationUrl)?.split("/").pop() || "待绑定";
            const current = conversationKey(identity.currentUrl)?.split("/").pop() || "未知";
            const error = `会话不一致：队列 ${expected}，页面 ${current}；队列已暂停`;
            await updateSenderState({
              status: "failed",
              phase: "source_validation_failed",
              error,
            }, `队列暂停：${error}`);
          }
          throw new Error("发送状态来源无效");
        }
        const allowed = {};
        for (const key of ["status", "phase", "index", "completedAt", "error"]) {
          if (Object.prototype.hasOwnProperty.call(message.patch || {}, key)) {
            allowed[key] = message.patch[key];
          }
        }
        if (Object.prototype.hasOwnProperty.call(message.patch || {}, "conversationUrl")) {
          const boundConversation = conversationKey(message.patch.conversationUrl);
          const pageConversation = conversationKey(message.pageUrl);
          if (!boundConversation || conversationKey(state.conversationUrl) ||
              !DoubaoSenderCore.isInitialChatUrl(state.conversationUrl) ||
              pageConversation !== boundConversation) {
            throw new Error("新建豆包会话绑定无效");
          }
          allowed.conversationUrl = boundConversation;
        }
        const itemUpdate = Number.isInteger(message.itemIndex) && message.itemPatch
          ? { index: message.itemIndex, patch: message.itemPatch }
          : null;
        const next = await updateSenderState(allowed, message.log || null, itemUpdate);
        return { ok: true, state: next.status === "completed" ? await submitBuild(next) : next };
      }
      case "senderReady": {
        const state = await getSenderState();
        const identity = await senderMessageIdentity(sender, state, message.pageUrl);
        if (!identity.owns ||
            !["starting", "running", "pausing"].includes(state.status)) {
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
