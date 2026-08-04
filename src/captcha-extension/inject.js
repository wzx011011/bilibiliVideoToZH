(function () {
  "use strict";
  if (window.__doubaoCourseAssistantHooked) return;
  window.__doubaoCourseAssistantHooked = true;

  function normalizedUrl(value) {
    try {
      if (value instanceof Request) return value.url;
      return String(value instanceof URL ? value.href : value || "");
    } catch {
      return "";
    }
  }

  function capture(kind, value) {
    const url = normalizedUrl(value);
    try {
      const parsed = new URL(url, location.href);
      if (!parsed.hostname.endsWith("doubao.com")) return;
      window.postMessage({
        source: "doubao-inject",
        payload: { kind, url: parsed.href },
      }, location.origin);
    } catch {
      // Ignore malformed URLs from page code.
    }
  }

  const OriginalWebSocket = window.WebSocket;
  function HookedWebSocket(url, protocols) {
    capture("websocket", url);
    return protocols === undefined
      ? new OriginalWebSocket(url)
      : new OriginalWebSocket(url, protocols);
  }
  HookedWebSocket.prototype = OriginalWebSocket.prototype;
  Object.setPrototypeOf(HookedWebSocket, OriginalWebSocket);
  window.WebSocket = HookedWebSocket;

  const originalFetch = window.fetch;
  window.fetch = function (input) {
    capture("fetch", input);
    return originalFetch.apply(this, arguments);
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    capture("xhr", url);
    return originalOpen.apply(this, arguments);
  };

  console.info("[豆包课程配音助手] 页面捕获已启用");
})();
