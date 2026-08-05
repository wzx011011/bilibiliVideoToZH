const FIELDS = [
  ["DOUBAO_COOKIE", "Cookie（登录态）", true],
  ["DOUBAO_API_APP_KEY", "api_app_key", true],
  ["DOUBAO_DEVICE_ID", "device_id", true],
  ["DOUBAO_UID", "uid", true],
  ["DOUBAO_WEB_TAB_ID", "web_tab_id", true],
  ["DOUBAO_WEB_ID", "web_id", false],
  ["DOUBAO_TEA_UUID", "tea_uuid", false],
];

const STATUS_LABELS = {
  idle: "空闲",
  starting: "正在启动",
  running: "运行中",
  pausing: "等待当前回复后暂停",
  paused: "已暂停",
  failed: "需要处理",
  stopped: "已停止",
  completed: "已完成",
};

const BUILD_STATUS_LABELS = {
  disabled: "未启用",
  waiting: "等待发送完成",
  submitting: "正在提交",
  queued: "已排队",
  running: "正在生成",
  completed: "生成完成",
  failed: "生成失败",
};

let selectedQueueItems = [];
let selectedEpisode = null;
let selectedHasManifest = false;
let senderState = null;

function runtimeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (!response?.ok) reject(new Error(response?.error || "扩展后台处理失败"));
      else resolve(response);
    });
  });
}

function mask(value) {
  const text = String(value || "");
  if (text.length > 60) return `${text.slice(0, 30)}...（${text.length} 字符）`;
  return text;
}

function renderCreds(creds) {
  const tbody = document.getElementById("fields");
  tbody.replaceChildren();
  for (const [key, label, required] of FIELDS) {
    const value = String(creds[key] || "");
    const row = document.createElement("tr");
    const stateCell = document.createElement("td");
    stateCell.className = `state ${value ? "ok" : "miss"}`;
    stateCell.textContent = value ? "OK" : "--";
    const fieldCell = document.createElement("td");
    fieldCell.className = "field";
    fieldCell.textContent = `${label}${required ? "*" : ""}`;
    const valueCell = document.createElement("td");
    valueCell.className = `value${value ? "" : " missing"}`;
    valueCell.textContent = value ? mask(value) : "未抓到";
    row.append(stateCell, fieldCell, valueCell);
    tbody.append(row);
  }
}

function buildEnv(creds) {
  const safe = (value) => String(value || "").replace(/[\r\n]/g, "");
  return `# 豆包朗读凭据\n\n${FIELDS.map(([key]) => `${key}="${safe(creds[key])}"`).join("\n")}\n`;
}

async function refreshCreds() {
  const response = await runtimeMessage({ type: "getCreds" });
  const creds = response.creds || {};
  creds.DOUBAO_WEB_ID ||= creds.DOUBAO_DEVICE_ID || "";
  creds.DOUBAO_TEA_UUID ||= creds.DOUBAO_WEB_ID || "";
  renderCreds(creds);
  return creds;
}

async function queueItemsFromFiles(fileList) {
  const files = [...fileList];
  const manifestFiles = files.filter((file) => file.name.toLowerCase() === "manifest.json");
  if (manifestFiles.length > 1) throw new Error("只能选择一个 manifest.json");
  const textFiles = files.filter((file) => file.name.toLowerCase().endsWith(".txt"));
  if (!textFiles.length) throw new Error("没有选择 TXT 分块");
  const byName = new Map(textFiles.map((file) => [file.name, file]));
  if (byName.size !== textFiles.length) throw new Error("选择的 TXT 中存在同名文件");

  let ordered;
  let episode = null;
  if (manifestFiles.length === 1) {
    const manifest = JSON.parse(await manifestFiles[0].text());
    if (!Array.isArray(manifest.chunks) || !manifest.chunks.length) {
      throw new Error("manifest.json 不包含有效 chunks");
    }
    const expected = manifest.chunks.map((chunk) => String(chunk.txt_file || ""));
    const missing = expected.filter((name) => !byName.has(name));
    const extras = textFiles.map((file) => file.name).filter((name) => !expected.includes(name));
    if (missing.length) throw new Error(`缺少分块：${missing.join(", ")}`);
    if (extras.length) throw new Error(`存在 manifest 之外的 TXT：${extras.join(", ")}`);
    const sourceMatch = String(manifest.srt_source || "").match(/episode-(\d+)/i);
    episode = Number(manifest.episode || sourceMatch?.[1]);
    if (!Number.isInteger(episode) || episode < 1 || episode > 999) {
      throw new Error("manifest.json 的集数无效");
    }
    ordered = await Promise.all(manifest.chunks.map(async (chunk, index) => ({
      name: String(chunk.txt_file),
      chunkIndex: Number.isInteger(chunk.chunk_index) ? chunk.chunk_index : index + 1,
      text: await byName.get(String(chunk.txt_file)).text(),
    })));
  } else {
    ordered = await Promise.all(textFiles
      .sort((left, right) => DoubaoSenderCore.naturalCompare(left.name, right.name))
      .map(async (file, index) => ({ name: file.name, chunkIndex: index + 1, text: await file.text() })));
  }
  return {
    items: DoubaoSenderCore.validateItems(ordered),
    episode,
    hasManifest: manifestFiles.length === 1,
  };
}

function renderSelected(items, hasManifest, episode = null) {
  const target = document.getElementById("selected-files");
  if (!items.length) {
    target.textContent = "尚未选择文件";
    const autoBuild = document.getElementById("auto-build");
    autoBuild.disabled = true;
    autoBuild.checked = false;
    document.getElementById("build-status").textContent = "等待选择 manifest";
    return;
  }
  const mode = hasManifest ? `第 ${episode} 集，manifest 校验通过` : "按文件名自然排序（未使用 manifest）";
  target.textContent = `${items.length} 个分块，${mode}\n${items.map((item) =>
    `${String(item.chunkIndex).padStart(2, "0")}  ${item.name}  ${item.fingerprint}`).join("\n")}`;
  const autoBuild = document.getElementById("auto-build");
  autoBuild.disabled = !hasManifest;
  autoBuild.checked = hasManifest;
  document.getElementById("build-status").textContent = hasManifest
    ? `第 ${episode} 集，等待开始`
    : "需要 manifest";
}

function renderSender(state) {
  senderState = state;
  const total = Number(state?.total || 0);
  const index = Math.min(Number(state?.index || 0), total);
  const label = STATUS_LABELS[state?.status] || state?.status || "空闲";
  document.getElementById("sender-status").textContent = label;
  document.getElementById("sender-progress").textContent = `${index} / ${total}`;
  const bar = document.getElementById("sender-bar");
  bar.max = Math.max(total, 1);
  bar.value = index;
  document.getElementById("sender-error").textContent = state?.error || "";

  const build = state?.build;
  const buildLabel = BUILD_STATUS_LABELS[build?.status] || build?.status || "未启用";
  document.getElementById("build-status").textContent = build?.enabled
    ? `第 ${build.episode} 集 · ${buildLabel}`
    : buildLabel;
  document.getElementById("build-output").textContent = build?.error
    ? `${build.error}${build.logFile ? `\n日志：${build.logFile}` : ""}`
    : build?.status === "completed" ? build.output || "" : "";

  const active = ["starting", "running", "pausing"].includes(state?.status);
  const resumable = ["paused", "failed", "stopped"].includes(state?.status) && index < total;
  document.getElementById("start").disabled = active;
  document.getElementById("pause").disabled = !["starting", "running"].includes(state?.status);
  document.getElementById("resume").disabled = !resumable;
  document.getElementById("skip").disabled = !["paused", "failed"].includes(state?.status) || index >= total;
  document.getElementById("stop").disabled = !active;
  const allItemsDone = Array.isArray(state?.items) && state.items.length > 0 &&
    state.items.every((item) => item.status === "done");
  document.getElementById("build-retry").disabled = !(
    state?.status === "completed" && build?.enabled && build?.status === "failed" && allItemsDone
  );
  document.getElementById("export").disabled = !state?.runId;

  const logs = Array.isArray(state?.logs) ? state.logs : [];
  document.getElementById("sender-log").textContent = logs.length
    ? logs.slice(-12).map((item) => `${item.at.slice(11, 19)}  ${item.message}`).join("\n")
    : "暂无发送日志";
}

async function refreshSender() {
  const response = await runtimeMessage({ type: "senderGetState" });
  renderSender(response.state);
}

async function runAction(action) {
  try {
    const response = await runtimeMessage({ type: action });
    if (response.state) renderSender(response.state);
  } catch (error) {
    document.getElementById("sender-error").textContent = error.message;
  }
}

document.getElementById("queue-files").addEventListener("change", async (event) => {
  try {
    const selected = await queueItemsFromFiles(event.target.files);
    selectedQueueItems = selected.items;
    selectedEpisode = selected.episode;
    selectedHasManifest = selected.hasManifest;
    renderSelected(selectedQueueItems, selectedHasManifest, selectedEpisode);
    document.getElementById("sender-error").textContent = "";
  } catch (error) {
    selectedQueueItems = [];
    selectedEpisode = null;
    selectedHasManifest = false;
    renderSelected([], false);
    document.getElementById("sender-error").textContent = error.message;
  }
});

document.getElementById("probe").addEventListener("click", async () => {
  const target = document.getElementById("probe-result");
  try {
    const response = await runtimeMessage({ type: "senderProbe" });
    const probe = response.probe;
    target.textContent = probe?.ready
      ? `页面可用：${probe.editor}；回复标记 ${probe.responseControls} 个`
      : `页面不可用：${probe?.error || "未知原因"}`;
  } catch (error) {
    target.textContent = `检测失败：${error.message}`;
  }
});

document.getElementById("bridge-probe").addEventListener("click", async () => {
  const target = document.getElementById("build-output");
  try {
    const response = await runtimeMessage({ type: "bridgeProbe" });
    if (response.bridge?.service !== "doubao-build-bridge") {
      target.textContent = "本地构建服务响应异常";
    } else if (response.bridge.credentials_ready) {
      target.textContent = "本地构建服务可用，凭据已就绪";
    } else {
      target.textContent = `服务可用，但缺少：${(response.bridge.missing_credentials || []).join(", ")}`;
    }
  } catch (error) {
    target.textContent = error.message;
  }
});

document.getElementById("start").addEventListener("click", async () => {
  try {
    if (!selectedQueueItems.length) throw new Error("请先选择分块文件");
    const autoBuild = document.getElementById("auto-build").checked;
    if (autoBuild && (!selectedHasManifest || !selectedEpisode)) {
      throw new Error("自动构建必须同时选择 manifest.json");
    }
    if (!confirm(`将向当前豆包对话依次发送 ${selectedQueueItems.length} 个分块，确认开始？`)) return;
    const delayMs = Number(document.getElementById("send-delay").value) * 1000;
    const response = await runtimeMessage({
      type: "senderStart",
      items: selectedQueueItems,
      delayMs,
      build: { enabled: autoBuild, episode: selectedEpisode },
    });
    renderSender(response.state);
  } catch (error) {
    document.getElementById("sender-error").textContent = error.message;
  }
});

document.getElementById("pause").addEventListener("click", () => runAction("senderPause"));
document.getElementById("resume").addEventListener("click", () => runAction("senderResume"));
document.getElementById("skip").addEventListener("click", () => runAction("senderSkip"));
document.getElementById("stop").addEventListener("click", () => runAction("senderStop"));
document.getElementById("build-retry").addEventListener("click", () => runAction("buildRetry"));

document.getElementById("export").addEventListener("click", () => {
  if (!senderState?.runId) return;
  const value = DoubaoSenderCore.exportableState(senderState);
  const blob = new Blob([`${JSON.stringify(value, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `doubao-send-${senderState.runId}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

document.getElementById("refresh").addEventListener("click", () => {
  refreshCreds().catch((error) => {
    document.getElementById("sender-error").textContent = error.message;
  });
});

document.getElementById("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(buildEnv(await refreshCreds()));
    const toast = document.getElementById("toast");
    toast.style.display = "block";
    setTimeout(() => { toast.style.display = "none"; }, 1500);
  } catch (error) {
    document.getElementById("sender-error").textContent = error.message;
  }
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.senderState?.newValue) renderSender(changes.senderState.newValue);
});

Promise.all([refreshCreds(), refreshSender()]).catch((error) => {
  document.getElementById("sender-error").textContent = error.message;
});

setInterval(() => {
  if (["submitting", "queued", "running"].includes(senderState?.build?.status)) {
    refreshSender().catch(() => undefined);
  }
}, 3000);
