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

  function isEditorValueEmpty(value) {
    // Some rich editors preserve invisible format characters after clearing.
    return String(value ?? "").replace(/[\u200B-\u200D\u2060\uFEFF]/g, "").trim() === "";
  }

  function parseDoubaoChatUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (url.protocol !== "https:" || url.hostname !== "www.doubao.com") return null;
      const pathname = url.pathname.replace(/\/+$/, "") || "/";
      if (pathname === "/chat") {
        return { conversationUrl: null, initial: true };
      }
      if (!/^\/chat\/[^/]+$/.test(pathname)) return null;
      return { conversationUrl: `${url.origin}${pathname}`, initial: false };
    } catch {
      return null;
    }
  }

  function isDoubaoChatUrl(value) {
    return parseDoubaoChatUrl(value) !== null;
  }

  function isInitialChatUrl(value) {
    return parseDoubaoChatUrl(value)?.initial === true;
  }

  function conversationKey(value) {
    return parseDoubaoChatUrl(value)?.conversationUrl || null;
  }

  function newResponseRevision(before, current) {
    const baseline = Array.isArray(before) ? before.map(String) : [...(before || [])].map(String);
    const latest = Array.isArray(current) ? current.map(String) : [...(current || [])].map(String);
    const remaining = new Map();
    for (const signature of baseline) {
      remaining.set(signature, (remaining.get(signature) || 0) + 1);
    }
    const unseen = [];
    for (const signature of latest) {
      const count = remaining.get(signature) || 0;
      if (count > 0) remaining.set(signature, count - 1);
      else unseen.push(signature);
    }
    return unseen.length ? `count:${latest.length}|new:${unseen.join("|")}` : null;
  }

  function doubaoUidFromCookies(cookies) {
    const candidates = Array.isArray(cookies)
      ? cookies.filter((cookie) => cookie?.name === "multi_sids")
      : [];
    for (const cookie of candidates) {
      let value = String(cookie.value || "");
      try {
        value = decodeURIComponent(value);
      } catch {
        // Keep the raw value when a malformed escape sequence is present.
      }
      for (const entry of value.split(/[|,]/)) {
        const match = entry.trim().match(/^(\d{6,30}):/);
        if (match) return match[1];
      }
    }
    return null;
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
      const text = String(item?.text || "")
        .replace(/^\uFEFF/, "")
        .replace(/\r\n?/g, "\n")
        .trim();
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

  function normalizeBuildOptions(value) {
    const enabled = Boolean(value?.enabled);
    const episode = Number(value?.episode);
    if (enabled && (!Number.isInteger(episode) || episode < 1 || episode > 999)) {
      throw new Error("自动构建需要 manifest 中的有效集数");
    }
    return {
      enabled,
      episode: enabled ? episode : null,
      status: enabled ? "waiting" : "disabled",
      jobId: null,
      error: null,
      output: null,
      logFile: null,
      updatedAt: null,
    };
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
      build: state?.build ? {
        enabled: Boolean(state.build.enabled),
        episode: Number.isInteger(state.build.episode) ? state.build.episode : null,
        status: state.build.status || "disabled",
        job_id: state.build.jobId || null,
        error: state.build.error || null,
        output: state.build.output || null,
        log_file: state.build.logFile || null,
      } : null,
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

  return {
    fingerprint,
    naturalCompare,
    isEditorValueEmpty,
    isDoubaoChatUrl,
    isInitialChatUrl,
    conversationKey,
    newResponseRevision,
    doubaoUidFromCookies,
    validateItems,
    normalizeBuildOptions,
    exportableState,
  };
});
