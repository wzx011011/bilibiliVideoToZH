(function () {
  "use strict";

  const RESPONSE_TIMEOUT_MS = 300000;
  const EDITOR_SELECTORS = [
    'textarea[placeholder="发消息或按住空格说话..."]',
    'textarea[placeholder*="发消息"]',
    'textarea.semi-input-textarea',
    'textarea:not([disabled])',
  ];

  let activeRun = null;

  function conversationKey(value) {
    try {
      const url = new URL(String(value || ""), location.href);
      return url.hostname === "www.doubao.com" && url.pathname.startsWith("/chat/")
        ? `${url.origin}${url.pathname}`
        : null;
    } catch {
      return null;
    }
  }

  function assertConversation(run) {
    if (conversationKey(location.href) !== conversationKey(run.conversationUrl)) {
      throw new Error("豆包对话已切换，队列已暂停以避免发错会话");
    }
  }

  function injectCaptureHook() {
    const script = document.createElement("script");
    script.src = chrome.runtime.getURL("inject.js");
    script.onload = () => script.remove();
    (document.head || document.documentElement).appendChild(script);
  }

  function isVisible(element) {
    if (!(element instanceof Element)) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" &&
      style.visibility !== "hidden";
  }

  function findEditor() {
    for (const selector of EDITOR_SELECTORS) {
      const candidates = [...document.querySelectorAll(selector)].filter(isVisible);
      if (candidates.length === 1) return candidates[0];
      if (candidates.length > 1) {
        const exact = candidates.filter((item) =>
          item.getAttribute("placeholder") === "发消息或按住空格说话...");
        if (exact.length === 1) return exact[0];
        throw new Error(`找到 ${candidates.length} 个输入框，无法安全选择`);
      }
    }
    throw new Error("未找到豆包消息输入框，请确认已打开对话页并刷新页面");
  }

  function findComposerRoot(editor) {
    const editorRect = editor.getBoundingClientRect();
    let node = editor.parentElement;
    for (let depth = 0; node && depth < 10; depth += 1, node = node.parentElement) {
      const rect = node.getBoundingClientRect();
      const actions = [...node.querySelectorAll('button,[role="button"],[class*="cursor-pointer"]')]
        .filter((item) => {
          if (!isVisible(item)) return false;
          const itemRect = item.getBoundingClientRect();
          return itemRect.width >= 24 && itemRect.width <= 72 &&
            itemRect.height >= 24 && itemRect.height <= 72 &&
            itemRect.x >= editorRect.right - 120 && itemRect.y >= editorRect.top;
        });
      if (rect.width >= editorRect.width && actions.length) return node;
    }
    throw new Error("未找到输入框操作区，豆包页面结构可能已更新");
  }

  function findSubmitAction(editor) {
    const root = findComposerRoot(editor);
    const editorRect = editor.getBoundingClientRect();
    const all = [...root.querySelectorAll('button,[role="button"],[class*="cursor-pointer"]')]
      .filter(isVisible);

    const semantic = all.filter((item) => {
      const label = [item.getAttribute("aria-label"), item.getAttribute("title"),
        item.getAttribute("data-testid"), item.textContent].filter(Boolean).join(" ");
      return /发送|send|submit/i.test(label) && item.getAttribute("aria-disabled") !== "true" &&
        !item.disabled;
    });
    if (semantic.length === 1) return semantic[0];

    const rightActions = all.filter((item) => {
      const rect = item.getBoundingClientRect();
      const label = String(item.textContent || "").trim();
      return rect.width >= 24 && rect.width <= 64 && rect.height >= 24 && rect.height <= 64 &&
        rect.x >= editorRect.right - 120 && rect.y >= editorRect.top &&
        item.getAttribute("aria-haspopup") == null && item.getAttribute("aria-disabled") !== "true" &&
        !item.disabled && label.length <= 4;
    }).filter((item) => !rightActionsParentIncluded(item, all));

    rightActions.sort((left, right) => {
      const a = left.getBoundingClientRect();
      const b = right.getBoundingClientRect();
      return b.right - a.right || (a.width * a.height) - (b.width * b.height);
    });
    if (rightActions.length) return rightActions[0];
    throw new Error("输入内容后仍未找到发送按钮");
  }

  function rightActionsParentIncluded(candidate, all) {
    return all.some((other) => other !== candidate && candidate.contains(other) && isVisible(other));
  }

  function setEditorText(editor, text) {
    editor.focus();
    const prototype = editor instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (!setter) throw new Error("浏览器不支持设置豆包输入框");
    setter.call(editor, text);
    editor.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      inputType: "insertText",
      data: text,
    }));
    editor.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function responseSignatures() {
    const signatures = new Set();
    for (const button of document.querySelectorAll('button[aria-label="朗读"]')) {
      let node = button.parentElement;
      for (let depth = 0; node && depth < 9; depth += 1, node = node.parentElement) {
        const text = String(node.innerText || "").replace(/\s+/g, " ").trim();
        if (text.length >= 20) {
          signatures.add(DoubaoSenderCore.fingerprint(text));
          break;
        }
      }
    }
    return signatures;
  }

  function hasNewResponse(before) {
    return [...responseSignatures()].some((signature) => !before.has(signature));
  }

  function occurrenceCount(text, marker) {
    if (!marker) return 0;
    let count = 0;
    let start = 0;
    while ((start = text.indexOf(marker, start)) !== -1) {
      count += 1;
      start += marker.length;
    }
    return count;
  }

  function deliveryMarker(text) {
    const compact = String(text).replace(/\s+/g, " ").trim();
    return compact.slice(-100);
  }

  function pageHasChallenge() {
    const text = String(document.body?.innerText || "");
    return /请完成验证|安全验证|滑块验证|验证码/.test(text);
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitUntil(predicate, timeoutMs, description, run) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (run.stopped) throw new Error("队列已停止");
      assertConversation(run);
      if (pageHasChallenge()) throw new Error("检测到豆包安全验证，请完成验证后重试当前分块");
      if (predicate()) return;
      await sleep(350);
    }
    throw new Error(`${description}超时`);
  }

  async function waitForDomQuiet(quietMs, timeoutMs, run) {
    let lastMutation = Date.now();
    const observer = new MutationObserver(() => { lastMutation = Date.now(); });
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });
    try {
      await waitUntil(() => Date.now() - lastMutation >= quietMs, timeoutMs,
        "等待回复页面稳定", run);
    } finally {
      observer.disconnect();
    }
  }

  function sendRuntime(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else if (!response?.ok) reject(new Error(response?.error || "扩展后台处理失败"));
        else resolve(response);
      });
    });
  }

  async function report(run, patch, log = null, itemIndex = null, itemPatch = null) {
    if (Object.prototype.hasOwnProperty.call(patch || {}, "phase")) run.phase = patch.phase;
    if (Object.prototype.hasOwnProperty.call(patch || {}, "index")) run.index = patch.index;
    return sendRuntime({
      type: "senderUpdate",
      runId: run.runId,
      patch,
      log,
      itemIndex,
      itemPatch,
    });
  }

  async function waitWhilePaused(run, itemName) {
    if (!run.paused) return;
    await report(run, { status: "paused", phase: "paused" }, `已在 ${itemName} 前暂停`);
    while (run.paused && !run.stopped) await sleep(300);
    if (run.stopped) throw new Error("队列已停止");
  }

  async function sendItem(run, item, index) {
    await waitWhilePaused(run, item.name);
    assertConversation(run);
    await report(
      run,
      { status: "running", phase: "filling", index, error: null },
      `正在填入 ${item.name}`,
      index,
      { status: "filling", error: null },
    );

    const editor = findEditor();
    if (String(editor.value || "").trim()) {
      throw new Error("豆包输入框已有未发送内容，已暂停以避免覆盖草稿");
    }
    const marker = deliveryMarker(item.text);
    const pageTextBefore = String(document.body?.innerText || "").replace(/\s+/g, " ");
    const markerCountBefore = occurrenceCount(pageTextBefore, marker);
    const responsesBefore = responseSignatures();

    setEditorText(editor, item.text);
    await sleep(250);
    if (editor.value !== item.text) {
      throw new Error(`输入框内容校验失败：${item.name}`);
    }

    const action = findSubmitAction(editor);
    await report(run, { phase: "sending" }, `正在发送 ${item.name}`, index, { status: "sending" });
    action.click();

    await report(run, { phase: "confirming_send" });
    await waitUntil(() => String(editor.value || "").trim() === "", 15000, "等待输入框清空", run);
    await waitUntil(() => {
      const pageText = String(document.body?.innerText || "").replace(/\s+/g, " ");
      return occurrenceCount(pageText, marker) > markerCountBefore;
    }, 20000, "确认用户消息送达", run);

    const sentAt = new Date().toISOString();
    await report(
      run,
      { phase: "waiting_reply" },
      `${item.name} 已送达，等待豆包回复完成`,
      index,
      { status: "waiting_reply", sentAt },
    );
    await waitUntil(() => hasNewResponse(responsesBefore), RESPONSE_TIMEOUT_MS,
      "等待豆包回复完成", run);
    await waitForDomQuiet(2500, 30000, run);

    const replyAt = new Date().toISOString();
    await report(
      run,
      { index: index + 1, phase: "item_done" },
      `${item.name} 回复完成`,
      index,
      { status: "done", replyAt },
    );
    await sleep(run.delayMs);
  }

  async function executeQueue(run) {
    if (run.executing) return;
    run.executing = true;
    try {
      assertConversation(run);
      const probe = probePage();
      if (!probe.ready) throw new Error(probe.error);
      await report(run, { status: "running", phase: "ready", error: null },
        `页面检测通过，准备发送 ${run.items.length - run.index} 个分块`);

      for (let index = run.index; index < run.items.length; index += 1) {
        if (run.stopped) break;
        run.index = index;
        await sendItem(run, run.items[index], index);
      }
      if (!run.stopped) {
        await report(run, {
          status: "completed",
          phase: "completed",
          index: run.items.length,
          completedAt: new Date().toISOString(),
          error: null,
        }, "全部分块发送完成");
      }
    } catch (error) {
      if (!run.stopped) {
        const uncertain = ["sending", "confirming_send", "waiting_reply"].includes(run.phase);
        const phase = uncertain ? "uncertain_delivery" : "failed";
        const message = uncertain
          ? `${error.message}；当前分块可能已送达，请检查页面后选择重试或跳过`
          : error.message;
        await report(
          run,
          { status: "failed", phase, index: run.index, error: message },
          `队列暂停：${message}`,
          run.index,
          { status: uncertain ? "uncertain_delivery" : "failed", error: message },
        ).catch(console.error);
      }
    } finally {
      run.executing = false;
    }
  }

  function probePage() {
    try {
      if (location.hostname !== "www.doubao.com" || !location.pathname.startsWith("/chat/")) {
        throw new Error("当前页面不是豆包对话页");
      }
      const editor = findEditor();
      const root = findComposerRoot(editor);
      return {
        ready: true,
        url: location.href,
        editor: editor.getAttribute("placeholder") || editor.tagName.toLowerCase(),
        actionCandidates: root.querySelectorAll('button,[role="button"],[class*="cursor-pointer"]').length,
        responseControls: document.querySelectorAll('button[aria-label="朗读"]').length,
      };
    } catch (error) {
      return { ready: false, error: error.message };
    }
  }

  function startRun(state) {
    if (!state?.runId || !Array.isArray(state.items)) throw new Error("队列状态无效");
    if (activeRun?.runId === state.runId) {
      if (activeRun.executing && activeRun.index !== state.index) {
        activeRun.stopped = true;
        const replacement = {
          runId: state.runId,
          items: state.items,
          index: state.index || 0,
          delayMs: state.delayMs || 5000,
          conversationUrl: state.conversationUrl,
          phase: state.phase || "resuming",
          paused: false,
          stopped: false,
          executing: false,
        };
        activeRun = replacement;
        setTimeout(() => executeQueue(replacement), 50);
        return;
      }
      activeRun.paused = false;
      activeRun.stopped = false;
      activeRun.index = state.index;
      if (!activeRun.executing) executeQueue(activeRun);
      return;
    }
    if (activeRun) activeRun.stopped = true;
    activeRun = {
      runId: state.runId,
      items: state.items,
      index: state.index || 0,
      delayMs: state.delayMs || 5000,
      conversationUrl: state.conversationUrl,
      phase: state.phase || "starting",
      paused: state.status === "paused" || state.status === "pausing",
      stopped: false,
      executing: false,
    };
    executeQueue(activeRun);
  }

  window.addEventListener("message", (event) => {
    const data = event.data;
    if (event.source !== window || location.hostname !== "www.doubao.com" ||
        !data || data.source !== "doubao-inject" ||
        !["websocket", "fetch", "xhr"].includes(data.payload?.kind)) return;
    try {
      const url = new URL(String(data.payload.url));
      if (!url.hostname.endsWith("doubao.com")) return;
      chrome.runtime.sendMessage({ type: "capturedUrl", payload: data.payload });
    } catch {
      // Ignore malformed page messages.
    }
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    try {
      switch (message?.type) {
        case "doubaoSenderProbe":
          sendResponse({ ok: true, probe: probePage() });
          break;
        case "doubaoSenderStart":
          startRun(message.state);
          sendResponse({ ok: true });
          break;
        case "doubaoSenderPause":
          if (activeRun?.runId === message.runId) activeRun.paused = true;
          sendResponse({ ok: true });
          break;
        case "doubaoSenderStop":
          if (activeRun?.runId === message.runId) activeRun.stopped = true;
          sendResponse({ ok: true });
          break;
        default:
          sendResponse({ ok: false, error: "未知页面命令" });
      }
    } catch (error) {
      sendResponse({ ok: false, error: error.message });
    }
    return true;
  });

  injectCaptureHook();
  sendRuntime({ type: "senderReady" }).then((response) => {
    if (response.resume) startRun(response.resume);
  }).catch(() => {
    // The background may still be starting after an extension reload.
  });
})();
