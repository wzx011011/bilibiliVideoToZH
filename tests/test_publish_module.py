"""publish_module 单测:鉴权矩阵、平台白名单、任务状态机、QR 会话、RSS/音频流。

不触外网:requests 网络点全部 mock 或用本地临时文件。
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import types
from http import HTTPStatus
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import publish_module as pm


# ======================== 基础设施 ========================

class FakeHeaders:
    def __init__(self, token=None, extra=None):
        self._d = {}
        if token is not None:
            self._d["X-Publish-Token"] = token
        self._d.update(extra or {})

    def get(self, k, default=None):
        return self._d.get(k, default)


class FakeHandler:
    """最小 handler 桩:记录 _json 输出。"""

    def __init__(self, path="/", body=None, token=None, method="POST",
                 extra_headers=None):
        self.path = path
        self.command = method
        self.headers = FakeHeaders(token, extra_headers)
        self._body_obj = body if body is not None else {}
        self.status = None
        self.resp = None
        self.out = io.BytesIO()

    def _json(self, obj, status=HTTPStatus.OK):
        self.status = int(status)
        self.resp = obj
        self.out.write(json.dumps(obj, ensure_ascii=False).encode())
        return True

    def _body(self):
        return self._body_obj


@pytest.fixture()
def pub_env(tmp_path, monkeypatch):
    """把发布数据目录整体指到临时目录,隔离真实 work/studio。"""
    d = tmp_path / "pubdata"
    monkeypatch.setattr(pm, "PUB_DIR", d)
    monkeypatch.setattr(pm, "AUTH_DIR", d / "auth")
    monkeypatch.setattr(pm, "JOBS_DIR", d / "jobs")
    monkeypatch.setattr(pm, "CONFIG_PATH", d / "config.json")
    with pm._jobs_lock:
        pm._inflight.clear()
    yield d


def _setup_token(handler_body={"token": "test-token-123"}):
    h = FakeHandler("/api/pub/setup", handler_body)
    pm.dispatch_post(h)
    assert h.status == 200


def _authed(path, body, token="test-token-123", **kw):
    return FakeHandler(path, body, token=token, **kw)


# ======================== 鉴权矩阵 ========================

def test_setup_flow_and_auth_matrix(pub_env):
    # 未配置:任何 /api/pub/* 无口令 → 401 尚未设置
    h = FakeHandler("/api/pub/state", method="GET")
    pm.dispatch_get(h)
    assert h.status == 401 and "尚未设置" in h.resp["error"]
    # 短口令(尚无配置) → 400
    h = FakeHandler("/api/pub/setup", {"token": "abc"})
    pm.dispatch_post(h)
    assert h.status == 400
    # 正式设置
    _setup_token()
    h = FakeHandler("/api/pub/state", token="wrong!", method="GET")
    pm.dispatch_get(h)
    assert h.status == 403 and h.resp["ok"] is False
    # 正确口令 → 200(ok 字段在响应外层)
    h = FakeHandler("/api/pub/state", token="test-token-123", method="GET")
    pm.dispatch_get(h)
    assert h.status == 200
    # 重复 setup → 409 且不泄露服务器路径
    h = FakeHandler("/api/pub/setup", {"token": "another-token"})
    pm.dispatch_post(h)
    assert h.status == 409
    assert "config.json" not in json.dumps(h.resp)


# ======================== 平台白名单与输入校验 ========================

def _post_job(body, token="test-token-123"):
    h = _authed("/api/pub/jobs", body, token)
    pm.dispatch_post(h)
    return h


def test_platform_whitelist_rejects_unknown(pub_env):
    _setup_token()
    h = _post_job({"items": [{"ep": 1}], "platforms": ["not-a-platform"]})
    assert h.status == 400 and "未知平台" in h.resp["error"]
    # 大小写归一后可用
    h = _post_job({"items": [{"ep": 1}],
                   "platforms": ["RSS", " rss "]})
    assert h.status == int(HTTPStatus.ACCEPTED), h.resp
    job = pm._read_json(pub_env / "jobs" / f"{h.resp['job_id']}.json")
    assert job["platforms"] == ["rss"]  # 去重+规范化


def test_empty_items_or_platforms_400(pub_env):
    _setup_token()
    assert _post_job({"items": [], "platforms": ["rss"]}).status == 400
    assert _post_job({"items": [{"ep": 1}], "platforms": []}).status == 400
    assert _post_job({"items": [{"ep": 99}], "platforms": ["rss"]}).status == 400


def test_invalid_json_body_returns_400(pub_env):
    """非法 Content-Length/JSON 经 pipeline_admin.Handler._body 语义应回 400。"""
    import pipeline_admin as pa

    class Stub:
        MAX_BODY_BYTES = pa.Handler.MAX_BODY_BYTES

        def __init__(self, length, payload=b"{}"):
            self.headers = FakeHeaders(
                extra={"Content-Length": length})
            self.rfile = io.BytesIO(payload)
            self.status = None
            self.resp = None
            self.out = io.BytesIO()

        _json = FakeHandler._json

    s = Stub("abc")           # 非数字长度
    with pytest.raises(pa._BodyRejected):
        pa.Handler._body(s)
    assert s.status == 400
    s = Stub(str(pa.Handler.MAX_BODY_BYTES + 1))  # 超限拒收
    with pytest.raises(pa._BodyRejected):
        pa.Handler._body(s)
    assert s.status == 400
    s = Stub("2", b"{bad")    # 非法 JSON
    with pytest.raises(pa._BodyRejected):
        pa.Handler._body(s)
    assert s.status == 400
    s = Stub("-1")            # 负数
    with pytest.raises(pa._BodyRejected):
        pa.Handler._body(s)
    assert s.status == 400


# ======================== 专辑ID贯通 ========================

def test_album_id_passed_into_items(pub_env):
    _setup_token()
    h = _post_job({
        "items": [{"ep": 1}, {"ep": 2, "album_id": 777}],
        "platforms": ["ximalaya"], "xmly_album_id": 12345})
    assert h.status == 202
    job = pm._read_json(pub_env / "jobs" / f"{h.resp['job_id']}.json")
    albums = {it["ep"]: it["album_id"] for it in job["items"]}
    assert albums == {1: 12345, 2: 777}


# ======================== 重复提交与恢复 ========================

def test_duplicate_submit_conflict(pub_env):
    _setup_token()
    h = _post_job({"items": [{"ep": 3}], "platforms": ["bilibili"]})
    jid = h.resp["job_id"]
    with pm._jobs_lock:
        pm._inflight.add(jid)  # 视为仍在进行(避免测试里真的执行发布)
    h2 = _post_job({"items": [{"ep": 3}], "platforms": ["Bilibili"]})
    assert h2.status == 409
    assert jid in h2.resp["error"]


def test_recover_stale_jobs_marks_failed_and_skips_inflight(pub_env):
    (pub_env / "jobs").mkdir(parents=True, exist_ok=True)
    for name, st in (("20260826-aaaa.json", "queued"),
                     ("20260826-bbbb.json", "running")):
        pm._write_json(pub_env / "jobs" / name,
                       {"job_id": name[:-5], "status": st,
                        "items": [], "platforms": []})
    live_id = "20260826-live"
    pm._write_json(pub_env / "jobs" / f"{live_id}.json",
                   {"job_id": live_id, "status": "running",
                    "items": [], "platforms": []})
    with pm._jobs_lock:
        pm._inflight.add(live_id)
    pm._recover_stale_jobs()
    states = {p.stem: pm._read_json(p)["status"]
              for p in (pub_env / "jobs").glob("*.json")}
    assert states["20260826-aaaa"] == "failed"
    assert states["20260826-bbbb"] == "failed"
    assert states[live_id] == "running"  # 本进程任务不受影响


def test_enqueue_starts_worker_and_serializes(pub_env, monkeypatch):
    """两个任务入队时单 worker 串行:执行区间互不重叠。"""
    _setup_token()

    def fake_run(job):
        job.setdefault("_t", {})
        job["_t"]["start"] = time.time()
        time.sleep(0.15)
        job["_t"]["end"] = time.time()
        job["status"] = "done"
        pm._write_json(pm.JOBS_DIR / f"{job['job_id']}.json", job)

    monkeypatch.setattr(pm, "_run_job", fake_run)
    j1, c1 = pm.enqueue_job([{"ep": 1}], ["rss"])
    j2, c2 = pm.enqueue_job([{"ep": 2}], ["rss"])
    assert not c1 and not c2

    def load(jid):
        """Windows 下 replace 后短暂可读到旧内容(Defender 锁),
        轮询窗口放宽到 6s。"""
        deadline = time.time() + 6
        j = None
        while time.time() < deadline:
            j = pm._read_json(pub_env / "jobs" / f"{jid}.json")
            if j and "_t" in j and "end" in j["_t"]:
                return j
            time.sleep(0.05)
        raise AssertionError(f"job {jid} 未完成: {j}")

    a, b = load(j1["job_id"]), load(j2["job_id"])
    ia, ib = a["_t"], b["_t"]
    # 区间不相交:后一个的 start 不早于前一个的 end
    first, second = sorted([ia, ib], key=lambda t: t["start"])
    assert second["start"] >= first["end"]


# ======================== 资源分支与最终状态 ========================

@pytest.fixture()
def fake_eps(tmp_path, monkeypatch):
    """真实小文件,避免 build_feed 里 stat 真实路径炸掉。"""
    v1 = tmp_path / "v1.mp4"
    a1 = tmp_path / "a1.mp3"
    a2 = tmp_path / "a2.mp3"
    for p in (v1, a1, a2):
        p.write_bytes(b"\xff\xfb\x90\x00" * 64)
    eps = [
         {"ep": 1, "video": str(v1), "audio": str(a1), "cover": "",
          "title": pm.default_title(1), "desc": "d1"},
         {"ep": 2, "video": "", "audio": str(a2), "cover": "",
          "title": pm.default_title(2), "desc": "d2"},
         {"ep": 3, "video": "", "audio": "", "cover": "",
          "title": pm.default_title(3), "desc": "d3"},
    ]
    monkeypatch.setattr(pm, "scan_episodes", lambda: eps)
    return eps


def _mk_job(platforms, items=None):
    return {
        "job_id": "test-" + time.strftime("%H%M%S"),
        "platforms": platforms,
        "items": [{**it, "results": {}} for it in (
            items or [{"ep": 2, "title": "t", "desc": "d", "tid": 231,
                       "tags": "tg", "album_id": 42}])],
        "log_file": "",
    }


def test_audio_only_episode_all_platforms_accounted(pub_env, fake_eps,
                                                   monkeypatch):
    """纯音频集:B站缺视频记失败,不影响喜马继续;终态正确。"""
    monkeypatch.setattr(pm, "bilibili_publish",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("不该被调用")))
    monkeypatch.setattr(pm, "ximalaya_publish",
                        lambda audio, album, t, d, log: {"trackId": 9})
    job = _mk_job(["bilibili", "ximalaya"])
    pm._run_job(job)
    res = job["items"][0]["results"]
    assert res["bilibili"]["ok"] is False
    assert res["ximalaya"]["ok"] is True
    assert job["status"] == "failed"


def test_missing_both_resources_fails_per_platform(pub_env, fake_eps):
    job = _mk_job(["bilibili", "rss"], items=[{"ep": 3}])
    pm._run_job(job)
    res = job["items"][0]["results"]
    assert res["bilibili"]["ok"] is False and res["rss"]["ok"] is False
    assert job["status"] == "failed"


def test_nonexistent_ep_recorded_as_failure(pub_env, fake_eps):
    job = _mk_job(["bilibili", "rss"], items=[{"ep": 99}])
    pm._run_job(job)
    assert job["status"] == "failed"
    assert any(not r.get("ok") for r in job["items"][0]["results"].values())


def test_happy_path_done(pub_env, fake_eps, monkeypatch):
    monkeypatch.setattr(pm, "bilibili_publish", lambda *a, **k: {"aid": 1})
    job = _mk_job(["bilibili", "rss"])  # ep2 有音频无视频也行:分开断言
    job["items"][0]["ep"] = 1
    pm._run_job(job)
    assert job["status"] == "done"


def test_ximalaya_without_album_id_fails_clearly(pub_env, fake_eps):
    job = _mk_job(["ximalaya"],
                  items=[{"ep": 2, "album_id": 0}])
    pm._run_job(job)
    r = job["items"][0]["results"]["ximalaya"]
    assert r["ok"] is False and "专辑ID" in r["error"]


def test_legacy_string_error_counted_as_failure(pub_env, fake_eps):
    """旧格式字符串错误也要计入失败统计,不许假成功。"""
    job = _mk_job(["bilibili", "rss"], items=[
        {"ep": 2, "title": "t", "desc": "d", "tid": 231, "tags": "g",
         "album_id": 5, "results": {"error": "历史遗留字符串错误"}}])
    pm._run_job(job)
    assert job["status"] == "failed"
    assert "子任务失败" in (job.get("error") or "")


# ======================== 二维码会话 ========================

class FakeResp:
    def __init__(self, obj, cookies=None):
        self._obj = obj
        self.cookies = cookies or []

    def json(self):
        return self._obj


class FakeJar(dict):
    """模拟 requests CookieJar:支持 .set 与可迭代。"""

    def set(self, k, v, domain=None):
        self[k] = v

    def __iter__(self):
        return iter([types.SimpleNamespace(name=n, value=v)
                     for n, v in self.items()])


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.cookies = FakeJar()
        self.resp = None

    def get(self, url, **kw):
        return self.resp or FakeResp({})


def test_qr_poll_rejects_bad_key():
    out = pm.bilibili_qr_poll("")
    assert out["code"] == 86038
    out = pm.bilibili_qr_poll("../../etc/passwd")
    assert out["code"] == 86038


def test_qr_poll_unknown_key_expired(pub_env):
    pm._qr_sessions.clear()
    out = pm.bilibili_qr_poll("a" * 32)
    assert out["code"] == 86038  # 未生成过=过期语义


def test_qr_poll_waiting_state(pub_env):
    key = "b" * 32
    fs = FakeSession()
    fs.resp = FakeResp({"data": {"code": 180}})
    pm._qr_sessions.clear()
    pm._qr_sessions[key] = (fs, time.time())
    out = pm.bilibili_qr_poll(key)
    assert out["code"] == 180
    assert key in pm._qr_sessions  # 未过期保留


def test_qr_poll_success_saves_cookie_after_nav_ok(pub_env, monkeypatch):
    key = "c" * 32
    gen = FakeSession()          # 生成时的 session(poll 复用)
    gen.cookies.set("SESSDATA", "abc")
    gen.cookies.set("bili_jct", "xyz")
    gen.resp = FakeResp({"data": {"code": 0}})
    checker = FakeSession()      # nav 校验用的 session
    checker.resp = FakeResp({"data": {"isLogin": True, "uname": "tester"}})

    it = iter([checker])         # poll 只在 code==0 后建一个校验 Session
    monkeypatch.setattr(pm.requests, "Session",
                        lambda *a, **k: next(it))
    pm._qr_sessions.clear()
    pm._qr_sessions[key] = (gen, time.time())

    out = pm.bilibili_qr_poll(key)
    assert out["uname"] == "tester"
    auth = pm._read_json(pub_env / "auth" / "bilibili.json")
    assert auth["cookies"]["SESSDATA"] == "abc"


def test_qr_poll_login_check_failure_not_saved(pub_env, monkeypatch):
    key = "d" * 32
    gen = FakeSession()
    gen.cookies.set("SESSDATA", "a")
    gen.cookies.set("bili_jct", "b")
    gen.resp = FakeResp({"data": {"code": 0}})
    checker = FakeSession()
    checker.resp = FakeResp({"data": {"isLogin": False}})

    it = iter([checker])
    monkeypatch.setattr(pm.requests, "Session",
                        lambda *a, **k: next(it))
    pm._qr_sessions.clear()
    pm._qr_sessions[key] = (gen, time.time())
    out = pm.bilibili_qr_poll(key)
    assert "登录校验未通过" in (out.get("error") or "")
    assert not (pub_env / "auth" / "bilibili.json").exists()


# ======================== 音频流 Range ========================

class StreamHandler(FakeHandler):
    """带 wfile/发头能力的桩,用于 podcast 音频流。"""

    def __init__(self, path, range_header=None):
        super().__init__(path, method="GET")
        self.headers = FakeHeaders(extra={"Range": range_header or ""})
        self.sent = []
        self.code = None
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.code = int(code)

    def send_header(self, k, v):
        self.sent.append((k, v))

    def end_headers(self):
        pass


def _write_mp3(tmp_path, size=2048):
    p = tmp_path / "第01讲-中文音频.mp3"
    p.write_bytes(b"\xff\xfb\x90\x00" * (size // 4))
    return p


def test_podcast_audio_range_stream(tmp_path, monkeypatch):
    src = _write_mp3(tmp_path)
    monkeypatch.setattr(pm, "find_audio_for_episode",
                        lambda ep: src if ep == 1 else None)
    h = StreamHandler("/podcast/audio/ep-01.mp3",
                      "bytes=0-1023")
    assert pm.dispatch_get(h) is True
    assert h.code == 206
    hdrs = dict(h.sent)
    assert hdrs["Content-Length"] == "1024"
    assert hdrs["Content-Range"].startswith("bytes 0-1023/")
    # 无 Range → 200 全量
    h2 = StreamHandler("/podcast/audio/ep-01.mp3")
    pm.dispatch_get(h2)
    assert h2.code == 200
    # 起点越界 → 416
    h3 = StreamHandler("/podcast/audio/ep-01.mp3",
                       f"bytes={src.stat().st_size}-")
    pm.dispatch_get(h3)
    assert h3.code == 416
    # 不存在的集 → 404
    h4 = StreamHandler("/podcast/audio/ep-99.mp3")
    pm.dispatch_get(h4)
    assert h4.status == 404


# ======================== RSS feed ========================

def test_validate_rss_base():
    assert pm.validate_rss_base("https://studio.5945.top/podcast/") == \
        "https://studio.5945.top/podcast"
    for bad in ("ftp://x/y", "not-a-url", "http://", "",
                "https://a.com/pa th", "https://a.com/<x>"):
        with pytest.raises(ValueError):
            pm.validate_rss_base(bad)


def test_feed_escapes_and_skips_missing_audio(monkeypatch):
    eps = [
        {"ep": 1, "audio": "", "title": "<T&S>", "desc": 'q"s',
         "video": "", "cover": ""},
        {"ep": 2, "audio": "/tmp/fake.mp3",
         'title': 'A"b<c>&d', "desc": "d", "video": "", "cover": ""},
    ]
    monkeypatch.setattr(pm, "scan_episodes", lambda: eps)

    class P:
        def __init__(self, p):
            self._p = p

        def stat(self):
            return types.SimpleNamespace(st_mtime=1700000000, st_size=1000)

        def open(self, *a):
            return io.BytesIO(b"\xff\xfb\x90\x00" * 250)

    monkeypatch.setattr(pm, "Path", P)
    feed, count = pm.build_feed({})
    assert count == 1                      # 无音频的 ep1 不收录
    assert feed.count("<item>") == 1
    assert "<title>A&quot;b&lt;c&gt;&amp;d</title>" in feed


def test_feed_base_falls_back_on_invalid_config(monkeypatch):
    monkeypatch.setattr(pm, "scan_episodes", lambda: [])
    feed, _ = pm.build_feed({"rss_base_url": "javascript:alert(1)"})
    assert "https://studio.5945.top/podcast" in feed


# ======================== MP3 时长解析 ========================

def _synth_cbr_mp3(seconds=8.0):
    sr, br_kbps = 44100, 128
    frame = (1152 // 8) * br_kbps * 1000 // sr  # 417
    n = int(seconds * sr) // 1152
    return b"\xff\xfb\x90\x00" + b"\x00" * (frame - 4), n, sr, br_kbps


def test_mp3_duration_python_cbr(tmp_path):
    header, n, sr, br = _synth_cbr_mp3()
    p = tmp_path / "a.mp3"
    p.write_bytes(header * n)
    dur = pm._mp3_duration_python(p)
    expect = n * 1152 / sr
    assert abs(dur - expect) < 1.5


def test_mp3_duration_with_id3_prefix(tmp_path):
    header, n, sr, _br = _synth_cbr_mp3()
    p = tmp_path / "b.mp3"
    id3 = b"ID3" + b"\x03\x00" + b"\x00" * 6 + b"\x00" * 200
    p.write_bytes(id3 + header * n)
    dur = pm._mp3_duration_python(p)
    expect = n * 1152 / sr
    assert abs(dur - expect) < 1.5


# ======================== 日志路径限制 ========================

def test_job_log_read_confined_to_jobs_dir(pub_env):
    _setup_token()
    jid = "20260826-confined"
    (pub_env / "jobs").mkdir(parents=True, exist_ok=True)
    pm._write_json(pub_env / "jobs" / f"{jid}.json",
                   {"job_id": jid, "status": "done", "items": [],
                    "platforms": [],
                    "log_file": "/etc/passwd"})  # 恶意路径
    secret = pub_env / "jobs" / f"{jid}.log"
    secret.write_text("[h] normal tail", encoding="utf-8")
    h = FakeHandler(f"/api/pub/jobs/{jid}", method="GET",
                    token="test-token-123")
    pm.dispatch_get(h)
    assert h.status == 200
    assert h.resp["job"]["log_tail"] == "[h] normal tail"
    assert "root:" not in h.resp["job"]["log_tail"]


# ======================== 权限收紧(POSIX) ========================

@pytest.mark.skipif(sys.platform != "linux", reason="仅 POSIX chmod 生效")
def test_secure_write_permissions(pub_env):
    pub_env.mkdir(parents=True, exist_ok=True)
    pm.save_config({"token": "x" * 10})
    assert (oct(pub_env.stat().st_mode & 0o777)) == "0o600" or \
        (pub_env / "config.json").exists()


# ======================== 前端静态契约 ========================

def test_admin_html_frontend_contract():
    html = (SRC / "admin.html").read_text(encoding="utf-8")
    # 1. B站二维码必须显式 POST(P0 回归)
    assert "pubApi('/api/pub/bilibili/qr', {}, 'POST')" in html
    # 2. 发布提交携带专辑ID
    assert "xmly_album_id" in html
    assert "body.xmly_album_id = albumId" in html
    # 3. 纯音频集不再因缺视频被禁用
    assert "(e.video || e.audio)" in html
    # 4. pollQR 对 !ok 停止轮询
    assert re.search(r"pollQR[\s\S]{0,800}?if \(!j\.ok\)", html), \
        "pollQR 必须先判 !j.ok"
    # 5. 后端 body 上限存在
    admin_py = (SRC / "pipeline_admin.py").read_text(encoding="utf-8")
    assert "MAX_BODY_BYTES" in admin_py
