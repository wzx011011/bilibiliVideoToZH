// content script（ISOLATED world）：动态注入 inject.js 到 MAIN world + 桥接消息
(function () {
  // 动态注入 inject.js
  const s = document.createElement("script");
  s.src = chrome.runtime.getURL("inject.js");
  s.onload = () => s.remove();
  (document.head || document.documentElement).appendChild(s);

  // 接收 inject.js(MAIN) 的 postMessage → 转发 background
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.source !== "doubao-inject") return;
    if (data.payload?.kind) {
      try { chrome.runtime.sendMessage({ type: "capturedUrl", payload: data.payload }); } catch (e) {}
    }
  });
})();
