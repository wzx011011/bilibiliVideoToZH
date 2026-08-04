(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.DoubaoSenderCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MAX_ITEMS = 100;
  const MAX_ITEM_CHARS = 200000;
  const MAX_TOTAL_CHARS = 2000000;

  function fingerprint(text) {
    const value = String(text || "");
    let hash = 2166136261;
    for (let i = 0; i < value.length; i += 1) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return `${(hash >>> 0).toString(16).padStart(8, "0")}:${value.length}`;
  }

  function naturalCompare(left, right) {
    return String(left).localeCompare(String(right), "zh-CN", {
      numeric: true,
      sensitivity: "base",
    });
  }

  function validateItems(items) {
    if (!Array.isArray(items) || items.length === 0) {
      throw new Error("请选择至少一个 TXT 分块");
    }
    if (items.length > MAX_ITEMS) {
      throw new Error(`分块数量不能超过 ${MAX_ITEMS}`);
    }

    const names = new Set();
    let totalChars = 0;
    const normalized = items.map((item, index) => {
      const name = String(item?.name || `${index + 1}.txt`).trim();
      const text = String(item?.text || "").replace(/^\uFEFF/, "").trim();
      if (!name || names.has(name)) throw new Error(`文件名重复或为空：${name}`);
      if (!text) throw new Error(`分块内容为空：${name}`);
      if (text.length > MAX_ITEM_CHARS) throw new Error(`分块过大：${name}`);
      names.add(name);
      totalChars += text.length;
      return {
        name,
        text,
        chunkIndex: Number.isInteger(item?.chunkIndex) ? item.chunkIndex : index + 1,
        fingerprint: fingerprint(text),
        status: "pending",
        sentAt: null,
        replyAt: null,
        error: null,
      };
    });

    if (totalChars > MAX_TOTAL_CHARS) {
      throw new Error("分块总文本超过 200 万字符");
    }
    return normalized;
  }

  function exportableState(state) {
    return {
      schema_version: 1,
      run_id: state?.runId || null,
      status: state?.status || "idle",
      conversation_url: state?.conversationUrl || null,
      started_at: state?.startedAt || null,
      completed_at: state?.completedAt || null,
      current_index: Number.isInteger(state?.index) ? state.index : 0,
      total: Number.isInteger(state?.total) ? state.total : 0,
      error: state?.error || null,
      items: Array.isArray(state?.items)
        ? state.items.map((item) => ({
            name: item.name,
            chunk_index: item.chunkIndex,
            fingerprint: item.fingerprint,
            status: item.status,
            sent_at: item.sentAt,
            reply_at: item.replyAt,
            error: item.error,
          }))
        : [],
      logs: Array.isArray(state?.logs) ? state.logs : [],
    };
  }

  return { fingerprint, naturalCompare, validateItems, exportableState };
});
