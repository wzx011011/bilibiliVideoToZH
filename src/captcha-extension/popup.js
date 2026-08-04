const FIELDS = [
  ["DOUBAO_COOKIE", "Cookie（登录态）", true],
  ["DOUBAO_API_APP_KEY", "api_app_key", true],
  ["DOUBAO_DEVICE_ID", "device_id", true],
  ["DOUBAO_UID", "uid", true],
  ["DOUBAO_WEB_TAB_ID", "web_tab_id", true],
  ["DOUBAO_WEB_ID", "web_id", false],
  ["DOUBAO_TEA_UUID", "tea_uuid", false],
];

async function loadCreds() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "getCreds" }, (creds) => {
      creds = creds || {};
      creds.DOUBAO_WEB_ID = creds.DOUBAO_WEB_ID || creds.DOUBAO_DEVICE_ID || "";
      creds.DOUBAO_TEA_UUID = creds.DOUBAO_TEA_UUID || creds.DOUBAO_WEB_ID || "";
      resolve(creds);
    });
  });
}

function mask(val) {
  if (!val) return "";
  if (val.length > 60) return val.slice(0, 30) + "…（" + val.length + " 字符）";
  return val;
}

function render(creds) {
  const tbody = document.getElementById("fields");
  tbody.innerHTML = "";
  for (const [key, label, required] of FIELDS) {
    const val = creds[key] || "";
    const status = val ? '<span class="ok">✓</span>' : '<span class="miss">✗</span>';
    tbody.innerHTML += `<tr><td class="status">${status}</td><td class="field">${label}${required ? '*' : ''}</td><td class="value ${val ? '' : 'missing'}">${val ? mask(val) : '未抓到'}</td></tr>`;
  }
}

function buildEnv(creds) {
  return "# 豆包朗读凭据\n\n" + FIELDS.map(([k]) => `${k}="${creds[k] || ""}"`).join("\n");
}

async function refresh() { render(await loadCreds()); }
document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("copy").addEventListener("click", async () => {
  await navigator.clipboard.writeText(buildEnv(await loadCreds()));
  const t = document.getElementById("toast"); t.style.display = "block";
  setTimeout(() => t.style.display = "none", 1500);
});
refresh();
