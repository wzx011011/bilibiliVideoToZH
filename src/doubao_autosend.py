"""豆包自动发送(路径 A:Playwright 驱动真实页面)。

把 captcha-extension/relay.js 里实战验证过的 DOM 操作移植到 Playwright:
找输入框 → 原生路径填入 → 点发送按钮。签名(a_bogus/msToken)由豆包页面
自己的前端 JS 在真实提交时生成,零逆向。

关键设计:
- 用系统真 Chrome(channel="chrome"),指纹接近正常用户,降低自动化检测风险;
- 持久化用户数据目录(work/playwright-profile),登录态跨次保留;
- Cookie 从项目 .env 的 DOUBAO_COOKIE 注入(与扩展/reader 同源);
- 发送按钮定位与 relay.js 相同:先语义匹配(发送/send/submit),再退回
  输入框右侧小方按钮(最右优先);
- 回复等待:等"朗读"按钮数量增加且稳定(页面出现新回复)。

用法(PoC):
  work/.venv-ocr/Scripts/python.exe src/doubao_autosend.py "你好"
集成用法(供 pipeline_admin 调用):
  from doubao_autosend import DoubaoAutoSender
  sender = DoubaoAutoSender(); sender.send_chunks(files)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "work" / "playwright-profile"
DOUBAO_HOME = "https://www.doubao.com/chat/"

# 与 relay.js EDITOR_SELECTORS 一致
EDITOR_SELECTORS = [
    'textarea[placeholder="发消息或按住空格说话..."]',
    'textarea[placeholder*="发消息"]',
    "textarea.semi-input-textarea",
    "textarea:not([disabled])",
]

RESPONSE_TIMEOUT_S = 300   # 单条回复最长等待
RESPONSE_STABLE_S = 3      # 回复内容静默判定

# 找发送按钮并点击 —— 移植 relay.js 的 findSubmitAction,整段在页面 JS 里
# 原子执行。不能拆成 Python 多轮遍历:fill 会触发 React 重渲染,Python↔浏览器
# 往返期间元素句柄失效(stale),索引漂移导致按钮丢失(实测踩坑)。
JS_FIND_AND_CLICK = """
() => {
  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden";
  };
  const sels = ['textarea[placeholder="发消息或按住空格说话..."]',
                'textarea[placeholder*="发消息"]',
                'textarea.semi-input-textarea', 'textarea:not([disabled])'];
  let editor = null;
  for (const sel of sels) {
    const cs = [...document.querySelectorAll(sel)].filter(isVisible);
    if (cs.length === 1) { editor = cs[0]; break; }
    if (cs.length > 1) {
      const e = cs.filter((c) => c.getAttribute("placeholder") === "发消息或按住空格说话...");
      if (e.length === 1) { editor = e[0]; break; }
    }
  }
  if (!editor) return { ok: false, error: "editor not found" };
  const er = editor.getBoundingClientRect();
  const all = [...document.querySelectorAll('button,[role="button"],[class*="cursor-pointer"]')]
    .filter(isVisible);
  const semantic = all.filter((item) => {
    const label = [item.getAttribute("aria-label"), item.getAttribute("title"),
                   item.getAttribute("data-testid"), item.textContent]
      .filter(Boolean).join(" ");
    return /发送|send|submit/i.test(label) && !/停止|stop|pause/i.test(label) &&
      item.getAttribute("aria-disabled") !== "true" && !item.disabled;
  });
  // 生成中:发送按钮切换为"停止"(同一位置)。此时点击=停止生成,必须等待。
  // label 是 aria-label/title/textContent 拼接串,按词拆开判断,避免
  // "停止 停止"这类拼接后 ^$ 锚点失效。
  const generating = all.some((item) => {
    const label = [item.getAttribute("aria-label"), item.getAttribute("title"),
                   item.textContent].filter(Boolean).join(" ").trim();
    if (/停止生成|停止回答/.test(label)) return true;
    return label.split(/\\s+/).some(
      (w) => /^(停止|stop|pause)$/i.test(w));
  });
  if (generating && !semantic.length) {
    return { ok: false, error: "generating" };
  }
  let btn = null;
  if (semantic.length) {
    btn = semantic[0];
  } else {
    const geo = all.filter((item) => {
      const r = item.getBoundingClientRect();
      return r.width >= 24 && r.width <= 72 && r.height >= 24 && r.height <= 72 &&
        r.x >= er.right - 120 && r.y >= er.top &&
        item.getAttribute("aria-haspopup") == null &&
        item.getAttribute("aria-disabled") !== "true" && !item.disabled &&
        String(item.textContent || "").trim().length <= 4;
    });
    if (geo.length) {
      geo.sort((a, b) =>
        b.getBoundingClientRect().right - a.getBoundingClientRect().right);
      btn = geo[0];
    }
  }
  if (!btn) return { ok: false, error: "submit button not found" };
  btn.click();
  return { ok: true };
}
"""


def load_env() -> dict[str, str]:
    """读项目 .env(不覆盖已有环境变量)。"""
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def cookie_string_to_playwright(cookie_str: str) -> list[dict]:
    """'a=1; b=2' → playwright add_cookies 格式(豆包域)。"""
    out = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        out.append({"name": name.strip(), "value": value.strip(),
                    "domain": ".doubao.com", "path": "/"})
    return out


class DoubaoAutoSender:
    """Playwright 驱动豆包页面自动发送。上下文管理器保持浏览器复用。"""

    def __init__(self, headless: bool = False, cookie: str | None = None):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        env = load_env()
        self.context = self._pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",           # 系统 Chrome,指纹最真
            headless=headless,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        cookies = cookie_string_to_playwright(
            cookie or env.get("DOUBAO_COOKIE", ""))
        if cookies:
            self.context.add_cookies(cookies)
        # 关键:让页面使用与 .env 朗读凭据一致的 web_id。
        # 豆包消息归属创建它的页面 web_id;若 Playwright profile 自动生成
        # 了新 web_id,朗读 WS(用 .env 的 WEB_ID)会因身份不匹配拿不到音频
        # (实测:消息能发能拉,但 TTS 静默无返回)。
        web_id = env.get("DOUBAO_WEB_ID", "").strip('"')
        if web_id:
            self.context.add_init_script(
                "try{var W='%s';var c=localStorage.getItem("
                "'samantha_web_web_id');var w=c?JSON.parse(c).tt_wid||'':'';"
                "if(!c||(JSON.parse(c).web_id||'')!==W){"
                "localStorage.setItem('samantha_web_web_id',"
                "JSON.stringify({web_id:W,tt_wid:w}));}}catch(e){}" % web_id)
        # 注入环境变量供后续 fetch_messages 复用(读者进程同 .env)
        for k in ("DOUBAO_COOKIE", "DOUBAO_DEVICE_ID", "DOUBAO_WEB_ID",
                  "DOUBAO_TEA_UUID", "DOUBAO_WEB_TAB_ID",
                  "DOUBAO_API_APP_KEY", "DOUBAO_UID"):
            if k in env:
                os.environ.setdefault(k, env[k])
        self.page = self.context.pages[0] if self.context.pages \
            else self.context.new_page()

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            self._pw.stop()

    def __enter__(self) -> "DoubaoAutoSender":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------- 页面操作(relay.js 移植) ----------

    def open_chat(self) -> None:
        self.page.goto(DOUBAO_HOME, wait_until="domcontentloaded")
        self._wait_editor(timeout_s=30)

    def _wait_editor(self, timeout_s: float = 15):
        deadline = time.time() + timeout_s
        last_err = "未找到输入框"
        while time.time() < deadline:
            self._check_challenge()
            for sel in EDITOR_SELECTORS:
                loc = self.page.locator(sel)
                if loc.count() == 1 and loc.first.is_visible():
                    return loc.first
                if loc.count() > 1:
                    # 多个候选:精确 placeholder 优先(relay.js 同策略)
                    exact = self.page.locator(EDITOR_SELECTORS[0])
                    if exact.count() == 1 and exact.first.is_visible():
                        return exact.first
            last_err = f"输入框候选异常 ({sel})"
            self.page.wait_for_timeout(500)
        raise RuntimeError(f"未找到豆包输入框: {last_err}(可能未登录或页面改版)")

    def _check_challenge(self) -> None:
        body = self.page.locator("body").inner_text(timeout=5000)
        if any(k in body for k in ("请完成验证", "安全验证", "滑块验证", "验证码")):
            raise RuntimeError("检测到豆包安全验证,需要人工在浏览器里完成验证后重试")

    def _reply_count(self) -> int:
        """页面上"朗读"按钮数量 ≈ 回复条数(仅在鼠标悬停回复时渲染,只作辅助)。"""
        return self.page.locator('button[aria-label="朗读"]').count()

    def _click_send_when_ready(self, timeout_s: float) -> None:
        """点击发送;豆包生成中(按钮=停止态)时先等生成结束;按钮未就绪时轮询。

        实测踩坑:
        - 生成期间发送按钮切换为"停止",点击=终止生成而非发消息;
        - 干净 profile 首次初始化时 React 组件慢,fill 后按钮仍是麦克风态,
          需要轮询等输入真正进入 React state、按钮切换为发送。
        """
        deadline = time.time() + timeout_s
        last_err = "未知"
        while True:
            result = self.page.evaluate(JS_FIND_AND_CLICK)
            if result and result.get("ok"):
                return  # 已点击
            last_err = result.get("error", "未知") if result else "无返回"
            transient = last_err in ("generating", "submit button not found",
                                     "editor not found")
            if not transient or time.time() > deadline:
                raise RuntimeError(f"发送失败: {last_err}")
            self.page.wait_for_timeout(2000)

    def send_one(self, text: str, timeout_s: float = RESPONSE_TIMEOUT_S) -> None:
        """发送一条消息并等回复完成(流式 body 真正结束)。

        回复判定:completion 响应 finished()(不只响应头——expect_response
        事件在 headers 到达即触发,body 要显式等;实测 4k 字块流式约需
        数十秒)。不依赖 DOM 悬停元素(朗读按钮只在鼠标悬停时渲染)。
        """
        self._check_challenge()
        editor = self._wait_editor()
        for attempt in range(5):
            editor.fill(text)  # Playwright fill 走原生 value setter,React 兼容
            self.page.wait_for_timeout(600)
            try:
                if (editor.input_value() or "").strip() == text.strip():
                    break
            except Exception:
                editor = self._wait_editor()
            if attempt == 4:
                raise RuntimeError("输入内容未能进入豆包输入框(React state 未接收)")

        with self.page.expect_response(
                lambda r: "completion" in r.url and r.status == 200,
                timeout=timeout_s * 1000) as resp_info:
            self._click_send_when_ready(timeout_s)
        resp_info.value.finished()  # 等 SSE body 流结束
        # 回复流结束后静默,确保前端渲染完、按钮恢复发送态
        self.page.wait_for_timeout(RESPONSE_STABLE_S * 1000)
        # 旁证:输入框被清空(消息确实发出)
        try:
            cleared = not (editor.input_value() or "").strip()
        except Exception:
            cleared = True  # 元素重建也说明界面翻转了
        if not cleared:
            raise RuntimeError("点击发送后输入框未清空,消息可能未发出")

    def send_chunks(self, chunk_files: list[Path], pause_s: float = 2.0) -> int:
        """依次发送一组分块文件,返回成功数。"""
        self.open_chat()
        ok = 0
        for i, f in enumerate(chunk_files, 1):
            text = f.read_text(encoding="utf-8")
            print(f"[{i}/{len(chunk_files)}] 发送 {f.name} ({len(text)}字)...")
            try:
                self.send_one(text)
                ok += 1
                print(f"    ✓ 回复完成")
            except Exception as e:  # noqa: BLE001
                print(f"    ✗ 失败: {e}")
                raise
            self.page.wait_for_timeout(int(pause_s * 1000))
        return ok


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python doubao_autosend.py <文本或@文件路径>")
        sys.exit(1)
    arg = sys.argv[1]
    if arg.startswith("@"):
        text = Path(arg[1:]).read_text(encoding="utf-8")
    else:
        text = arg
    with DoubaoAutoSender(headless=False) as sender:
        sender.open_chat()
        print("页面就绪,发送:", text[:50], "...")
        sender.send_one(text)
        print("✓ 发送并收到回复")
        # 截图留证
        shot = ROOT / "work" / "autosend-proof.png"
        sender.page.screenshot(path=str(shot))
        print("截图:", shot)


if __name__ == "__main__":
    main()
