// MAIN world 注入：hook WebSocket/fetch 抓 api_app_key + 设备参数
(function () {
  if (window.__doubaoHooked) return;
  window.__doubaoHooked = true;

  function send(payload) {
    window.postMessage({ source: "doubao-inject", payload }, "*");
  }

  // Hook WebSocket
  const OriginalWS = window.WebSocket;
  function HookedWS(url, protocols) {
    try {
      if (typeof url === "string" && url.includes("doubao")) {
        send({ kind: "websocket", url: url });
      }
    } catch (e) {}
    return protocols !== undefined ? new OriginalWS(url, protocols) : new OriginalWS(url);
  }
  HookedWS.prototype = OriginalWS.prototype;
  HookedWS.CONNECTING = OriginalWS.CONNECTING;
  HookedWS.OPEN = OriginalWS.OPEN;
  HookedWS.CLOSING = OriginalWS.CLOSING;
  HookedWS.CLOSED = OriginalWS.CLOSED;
  window.WebSocket = HookedWS;

  // Hook fetch
  const originalFetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      const url = typeof input === "string" ? input : input?.url;
      if (url && url.includes("doubao.com")) {
        send({ kind: "fetch", url: url });
      }
    } catch (e) {}
    return originalFetch.apply(this, arguments);
  };

  // Hook XHR
  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    try {
      if (url && url.includes("doubao.com")) send({ kind: "xhr", url: url });
    } catch (e) {}
    return originalOpen.apply(this, arguments);
  };

  console.log("[豆包抓取] hook 已注入");
})();
