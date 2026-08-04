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

let selectedQueueItems = [];
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
  return DoubaoSenderCore.validateItems(ordered);
}

function renderSelected(items, hasManifest) {
  const target = document.getElementById("selected-files");
  if (!items.length) {
    target.textContent = "尚未选择文件";
    return;
  }
  const mode = hasManifest ? "manifest 校验通过" : "按文件名自然排序（未使用 manifest）";
  target.textContent = `${items.length} 个分块，${mode}\n${items.map((item) =>
    `${String(item.chunkIndex).padStart(2, "0")}  ${item.name}  ${item.fingerprint}`).join("\n")}`;
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

  const active = ["starting", "running", "pausing"].includes(state?.status);
  const resumable = ["paused", "failed", "stopped"].includes(state?.status) && index < total;
  document.getElementById("start").disabled = active;
  document.getElementById("pause").disabled = !["starting", "running"].includes(state?.status);
  document.getElementById("resume").disabled = !resumable;
  document.getElementById("skip").disabled = !["paused", "failed"].includes(state?.status) || index >= total;
  document.getElementById("stop").disabled = !active;
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
    selectedQueueItems = await queueItemsFromFiles(event.target.files);
    renderSelected(selectedQueueItems, [...event.target.files]
      .some((file) => file.name.toLowerCase() === "manifest.json"));
    document.getElementById("sender-error").textContent = "";
  } catch (error) {
    selectedQueueItems = [];
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

document.getElementById("start").addEventListener("click", async () => {
  try {
    if (!selectedQueueItems.length) throw new Error("请先选择分块文件");
    if (!confirm(`将向当前豆包对话依次发送 ${selectedQueueItems.length} 个分块，确认开始？`)) return;
    const delayMs = Number(document.getElementById("send-delay").value) * 1000;
    const response = await runtimeMessage({ type: "senderStart", items: selectedQueueItems, delayMs });
    renderSender(response.state);
  } catch (error) {
    document.getElementById("sender-error").textContent = error.message;
  }
});

document.getElementById("pause").addEventListener("click", () => runAction("senderPause"));
document.getElementById("resume").addEventListener("click", () => runAction("senderResume"));
document.getElementById("skip").addEventListener("click", () => runAction("senderSkip"));
document.getElementById("stop").addEventListener("click", () => runAction("senderStop"));

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
