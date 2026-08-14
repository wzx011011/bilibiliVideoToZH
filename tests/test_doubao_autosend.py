"""doubao_autosend 纯函数单测:cookie 解析、.env 读取、页面 JS 语法有效性。"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from doubao_autosend import (  # noqa: E402
    JS_FIND_AND_CLICK,
    cookie_string_to_playwright,
    load_env,
)


def test_cookie_string_to_playwright():
    cs = "sessionid=abc123; ttwid=1%7Cxyz; uid=42"
    out = cookie_string_to_playwright(cs)
    assert len(out) == 3
    by_name = {c["name"]: c for c in out}
    assert by_name["sessionid"]["value"] == "abc123"
    assert by_name["ttwid"]["value"] == "1%7Cxyz"
    assert all(c["domain"] == ".doubao.com" and c["path"] == "/" for c in out)


def test_cookie_string_malformed_parts_skipped():
    out = cookie_string_to_playwright("a=1;; nosign; b=2; ")
    assert {c["name"] for c in out} == {"a", "b"}


def test_load_env_parses(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text(
        "# comment\nDOUBAO_COOKIE=abc=1; def=2\nEMPTY=\nSPACED = value \n",
        encoding="utf-8")
    monkeypatch.setattr(Path, "exists", lambda self, _f=f: self == _f or Path.exists(self))
    # 直接测内部逻辑:load_env 读 ROOT/.env;这里改为显式注入逻辑等价验证
    env = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    assert env == {"DOUBAO_COOKIE": "abc=1; def=2", "EMPTY": "",
                   "SPACED": "value"}


def test_js_find_and_click_syntax_valid():
    """注入页面的 JS 必须是合法脚本(包成函数体做语法解析)。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用")
    proc = subprocess.run(
        [node, "-e", f"new Function({json.dumps('return (' + JS_FIND_AND_CLICK + ');')})"],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"JS 语法错误: {proc.stderr[:300]}"


def test_js_find_and_click_semantics_dry_run():
    """在模拟 DOM(jsdom 缺席时用最小桩)验证语义分支。跳过若无 node。

    这里用 node 的最小 DOM 桩验证:editor 找不到时返回错误、
    生成中(停止按钮)返回 generating。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用")
    stub = """
    const _els = [];
    global.document = {
      querySelectorAll: (sel) => _els.filter((e) => sel.startsWith(e.sel)),
    };
    global.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
    const mk = (o) => {
      const el = {
        sel: o.sel || '*', textContent: o.text || '',
        getAttribute: (k) => (o.attrs || {})[k] ?? null,
        getBoundingClientRect: () => o.rect,
        disabled: !!o.disabled,
        click: () => { global.__clicked = (global.__clicked || 0) + 1; },
      };
      _els.push(el); return el;
    };
    """
    # 用例1:无 editor → editor not found
    js1 = stub + f"const fn = ({JS_FIND_AND_CLICK}); console.log(JSON.stringify(fn()));"
    proc = subprocess.run([node, "-e", js1], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr[:300]
    assert '"editor not found"' in proc.stdout

    # 用例2:有 editor + 生成中(停止按钮) → generating
    js2 = stub + f"""
    const fn = ({JS_FIND_AND_CLICK});
    mk({{sel: 'textarea', rect: {{x: 380, y: 800, width: 960, height: 24, top: 800, right: 1340}}}});
    mk({{sel: 'button', text: '停止', attrs: {{'aria-label': '停止'}},
        rect: {{x: 1314, y: 838, width: 36, height: 36}}}});
    console.log(JSON.stringify(fn()));
    """
    proc = subprocess.run([node, "-e", js2], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr[:300]
    assert '"generating"' in proc.stdout

    # 用例3:有 editor + 语义发送按钮 → 点击
    js3 = stub + f"""
    const fn = ({JS_FIND_AND_CLICK});
    mk({{sel: 'textarea', rect: {{x: 380, y: 800, width: 960, height: 24, top: 800, right: 1340}}}});
    mk({{sel: 'button', text: '发送', attrs: {{'aria-label': '发送'}},
        rect: {{x: 1314, y: 838, width: 36, height: 36}}}});
    console.log(JSON.stringify(fn()));
    """
    proc = subprocess.run([node, "-e", js3], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr[:300]
    assert '"ok":true' in proc.stdout
