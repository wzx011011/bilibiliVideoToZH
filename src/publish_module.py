"""多平台发布模块 —— B站 / 喜马拉雅 / RSS(小宇宙)。

由 pipeline_admin.py 接线:
    import publish_module
    # do_GET/do_POST 顶部:
    if self.path.startswith(("/api/pub/", "/podcast/")):
        return publish_module.dispatch(self)

平台策略:
- B站: 扫码登录(passport web qrcode) + upos 分块上传 + add/v3 投稿
- 喜马拉雅: 粘贴 Cookie 登录;上传接口无官方文档,尽力而为,失败给清晰日志
- 小宇宙: 无上传 API(RSS 客户端)。本模块生成 iTunes feed.xml + 音频文件,
  scp 到 NAS 成品库/播客RSS/,用户在 feed 中提交一次地址后每集自动同步

鉴权: 所有 /api/pub/* 要求请求头 X-Publish-Token 匹配 DATA_DIR/publish/config.json
中保存的口令(首次通过 /api/pub/setup 设置)。/podcast/* 为公开静态预览。
凭据只落服务器本地 DATA_DIR/publish/auth/,任何接口不回显完整值。

发布内容源(v1 哈佛幸福课 23 集):
- 视频 videos/episode-NN.mp4 (B站)
- 音频 episodes/ep-NN/episode-NN-audio.mp3 (喜马拉雅/RSS)
- 封面 videos/cover-epNN.jpg (B站封面/RSS art)
"""
from __future__ import annotations

import base64
import hashlib
import html as _html
import json
import os
import queue
import re
import shutil
import struct
import subprocess
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = Path(__file__).resolve().parent

try:  # pipeline_admin 定义了这些名字;独立测试时给出兜底
    from pipeline_admin import DATA_DIR, MEDIA_ROOT, MODE  # type: ignore
except Exception:  # pragma: no cover - 直接运行本文件做语法检查时
    DATA_DIR = ROOT / "work" / "studio"
    MEDIA_ROOT = None
    MODE = "local"

# 哈佛幸福课在 NAS 成品库的相对位置(server 模式数据源)
NAS_SERIES_DIR = "成品库/积极心理学"
NAS_VIDEO_SUB = "04-中文视频"
NAS_AUDIO_SUB = "03-中文音频"

PUB_DIR = DATA_DIR / "publish"
AUTH_DIR = PUB_DIR / "auth"
JOBS_DIR = PUB_DIR / "jobs"
CONFIG_PATH = PUB_DIR / "config.json"
TOTAL_EPISODES = 23

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SERIES_TITLE = "哈佛幸福课 · 中文配音"
SERIES_DESC = (
    "哈佛大学 Tal Ben-Shahar《积极心理学》(幸福课) 中文配音版。"
    "加标点断句、温暖娓娓道来的朗读,适合通勤/睡前听。"
)
DEFAULT_TAGS = "心理学,哈佛,幸福课,积极心理学,自我提升,中文配音"
DEFAULT_TID = 231  # 知识区-社科·法律·心理(可在发布时改)

# 之前拟定的 23 集主题(标题自动填充用)
DEFAULT_TOPICS = {
    1: "什么是积极心理学", 2: "幸福的生物学基础", 3: "幸福的五个前提",
    4: "环境的力量", 5: "成为你想成为的人", 6: "乐观主义与信念的力量",
    7: "关注的力量", 8: "感恩的奇迹", 9: "改变，从现在开始",
    10: "如何真正改变", 11: "养成良好习惯", 12: "工作的意义与使命感",
    13: "设定目标的力量", 14: "压力与应对", 15: "完美主义与最优主义",
    16: "享受过程", 17: "运动与冥想", 18: "睡眠、触摸与亲密关系",
    19: "爱情与关系", 20: "幽默是幸福的关键", 21: "自尊的三个层次",
    22: "自尊与自我实现", 23: "总结：让幸福成为习惯",
}


# =====================================================================
# 配置 / 口令
# =====================================================================

def _ensure_dirs() -> None:
    for d in (PUB_DIR, AUTH_DIR, JOBS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _lock_permissions(path: Path) -> None:
    """凭据/口令文件收紧为 0600(POSIX 生效;Windows 忽略)。"""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_config() -> dict:
    return _read_json(CONFIG_PATH)


def save_config(cfg: dict) -> None:
    _ensure_dirs()
    _write_json(CONFIG_PATH, cfg)
    _lock_permissions(CONFIG_PATH)


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _write_json(path: Path, obj, secure: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    if secure:
        _lock_permissions(tmp)
    tmp.replace(path)
    if secure:
        _lock_permissions(path)


def default_title(ep: int) -> str:
    topic = DEFAULT_TOPICS.get(ep, "")
    return f"【哈佛幸福课·中文配音】EP{ep:02d} - {topic}"


def default_desc(ep: int) -> str:
    topic = DEFAULT_TOPICS.get(ep, "")
    lines = [
        f"本集主题:{topic}" if topic else "",
        "",
        SERIES_DESC,
        "",
        "本系列共 23 集,建议按顺序收听。",
        f"#心理学 #自我提升 #{DEFAULT_TAGS.replace(',', ' #')}",
    ]
    return "\n".join(lines).strip()


# =====================================================================
# 集数扫描(server 模式读 NAS 挂载,local 模式读 PC 目录)
# =====================================================================

def _nas_series_root() -> Path | None:
    if MEDIA_ROOT and (MEDIA_ROOT / NAS_SERIES_DIR).is_dir():
        return MEDIA_ROOT / NAS_SERIES_DIR
    return None


def scan_episodes() -> list[dict]:
    nas = _nas_series_root()
    eps = []
    for ep in range(1, TOTAL_EPISODES + 1):
        nn = f"{ep:02d}"
        if nas is not None:
            video = nas / NAS_VIDEO_SUB / f"第{nn}讲-成品.mp4"
            audio = nas / NAS_AUDIO_SUB / f"第{nn}讲-中文音频.mp3"
            cover = None
        else:
            video = ROOT / "videos" / f"episode-{nn}.mp4"
            audio = ROOT / "episodes" / f"ep-{nn}" / f"episode-{nn}-audio.mp3"
            cover = ROOT / "videos" / f"cover-ep{nn}.jpg"
        item = {
            "ep": ep,
            "video": str(video) if video.is_file() else "",
            "audio": str(audio) if audio.is_file() else "",
            "cover": str(cover) if cover and cover.is_file() else "",
            "video_mb": round(video.stat().st_size / 1048576, 1) if video.is_file() else 0,
            "audio_mb": round(audio.stat().st_size / 1048576, 1) if audio.is_file() else 0,
            "title": default_title(ep),
            "desc": default_desc(ep),
            "tid": DEFAULT_TID,
            "tags": DEFAULT_TAGS,
        }
        eps.append(item)
    return eps


# =====================================================================
# B站
# =====================================================================

BILI_QR_GEN = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
BILI_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
BILI_NAV = "https://api.bilibili.com/x/web-interface/nav"


def bili_auth_path() -> Path:
    return AUTH_DIR / "bilibili.json"


def bili_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://member.bilibili.com/"})
    auth = _read_json(bili_auth_path())
    for k, v in (auth.get("cookies") or {}).items():
        s.cookies.set(k, v, domain=".bilibili.com")
    return s


def bili_logged_in(s: requests.Session | None = None) -> tuple[bool, str]:
    s = s or bili_session()
    try:
        r = s.get(BILI_NAV, timeout=10)
        data = r.json().get("data") or {}
        if data.get("isLogin"):
            return True, data.get("uname") or "已登录"
    except Exception:
        pass
    return False, ""


# 二维码生成/轮询共用会话:key -> (session, created_ts)。B站码有效期约 180s。
_QR_SESSION_TTL = 200
_qr_sessions: dict[str, tuple[requests.Session, float]] = {}
_qr_sessions_lock = threading.Lock()


def _qr_session_gc() -> None:
    now = time.time()
    with _qr_sessions_lock:
        for k in [k for k, (_, ts) in _qr_sessions.items()
                  if now - ts > _QR_SESSION_TTL]:
            _qr_sessions.pop(k, None)


def bilibili_qr_create() -> dict:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    r = s.get(BILI_QR_GEN, timeout=10)
    r.raise_for_status()
    j = r.json()["data"]
    out = {"qr_content": j["url"], "key": j["qrcode_key"]}
    try:
        import io

        import segno
        buf = io.BytesIO()
        segno.make(j["url"], error="h").save(buf, kind="svg", scale=6)
        out["qr_svg"] = buf.getvalue().decode()
    except ImportError:
        out["qr_error"] = "服务器缺少 segno 库(pip install segno),无法渲染二维码"
    _qr_session_gc()
    with _qr_sessions_lock:
        _qr_sessions[j["qrcode_key"]] = (s, time.time())
    return out


def bilibili_qr_poll(key: str) -> dict:
    if not key or not re.fullmatch(r"[\w-]{8,128}", key):
        return {"code": 86038, "error": "无效的二维码 key"}
    _qr_session_gc()
    with _qr_sessions_lock:
        entry = _qr_sessions.get(key)
    if entry is None:  # 服务重启或已过期清理
        return {"code": 86038, "error": "二维码状态丢失,请重新生成"}
    s, _created = entry
    r = s.get(BILI_QR_POLL, params={"qrcode_key": key}, timeout=10,
              allow_redirects=False)
    j = r.json()
    raw_code = (j.get("data") or {}).get("code")
    code = int(raw_code) if raw_code is not None else -1
    out = {"code": code}  # 180=未扫 86090=已扫待确认 86038=过期 0=成功
    if code in (86038,):
        with _qr_sessions_lock:
            _qr_sessions.pop(key, None)
        return out
    if code == 0:
        cookies = {c.name: c.value for c in s.cookies}
        for c in r.cookies:  # 响应 Set-Cookie 里的 SESSDATA/bili_jct 等
            cookies[c.name] = c.value
        missing = [k for k in ("SESSDATA", "bili_jct") if not cookies.get(k)]
        if missing:
            out["error"] = f"登录响应缺少 Cookie: {missing}"
            return out
        # 先用本会话验证登录态,再落盘,避免保存半套 Cookie
        check = requests.Session()
        check.headers.update({"User-Agent": UA, "Referer": "https://member.bilibili.com/"})
        for k, v in cookies.items():
            check.cookies.set(k, v, domain=".bilibili.com")
        logged, uname = False, ""
        try:
            nav = check.get(BILI_NAV, timeout=10).json().get("data") or {}
            logged, uname = bool(nav.get("isLogin")), nav.get("uname") or ""
        except Exception:
            pass
        if not logged:
            out["error"] = "扫码成功但登录校验未通过,请重试"
            return out
        _ensure_dirs()
        _write_json(bili_auth_path(), {
            "cookies": cookies,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }, secure=True)
        out["uname"] = uname
        with _qr_sessions_lock:
            _qr_sessions.pop(key, None)
    return out


def bili_logout() -> None:
    bili_auth_path().unlink(missing_ok=True)


def _bili_upload_cover(s: requests.Session, csrf: str, image: bytes) -> str:
    """传封面,返回 https 图片 URL。"""
    b64 = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    r = s.post("https://member.bilibili.com/x/vu/web/cover/up",
               params={"csrf": csrf}, data={"cover": b64}, timeout=30)
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"封面上传失败: {j.get('message')}")
    url = (((j.get("data") or {}).get("image_url"))
           or ((j.get("data") or {}).get("url")) or "")
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        raise RuntimeError(f"封面响应异常: {json.dumps(j)[:200]}")
    return url


def _bili_preupload(s: requests.Session, fname: str, size: int) -> dict:
    # profile=ugcupos/bup(投稿客户端档案):其 upos 鉴权走 preupload 返回的
    # auth 签名串(X-Upos-Auth),而非 SESSDATA;ugcfx/bup 网页档案实测 405/403
    r = s.get(
        "https://member.bilibili.com/preupload?upcdn=bda2&probe_version=20221109",
        params={
            "r": "upos", "profile": "ugcupos/bup", "ssl": 0,
            "version": "2.8.12", "build": 2081200,
            "name": fname, "size": size,
        }, timeout=30)
    j = r.json()
    if not j.get("upos_uri") or not j.get("auth"):
        raise RuntimeError(f"preupload 失败: {json.dumps(j)[:300]}")
    return j


def _bili_upos_upload(s: requests.Session, pre: dict, sessdata: str,
                      filepath: Path, log) -> str:
    """分块 PUT 到 upos,返回 bili_filename。鉴权用 pre['auth'] 签名串。"""
    upos_uri = pre["upos_uri"]
    endpoint = pre["endpoint"]
    if endpoint.startswith("//"):
        endpoint = "https:" + endpoint
    # upos_uri 形如 "upos://ugcever/xxx.mp4";上传路径为
    # {endpoint}/{bucket}/{object},去掉 upos:// 前缀直接拼
    path_part = re.sub(r"^upos://", "", upos_uri)
    base = f"{endpoint}/{path_part}"
    auth_header = {"X-Upos-Auth": pre["auth"]}
    chunk = min(int(pre.get("chunk_size", 4 * 1024 * 1024)),
                16 * 1024 * 1024)
    size = filepath.stat().st_size
    parts_total = max(1, (size + chunk - 1) // chunk)

    r = s.post(f"{base}?uploads&output=json",
               headers=auth_header, timeout=30)
    r.raise_for_status()
    upload_id = r.json()["upload_id"]

    with filepath.open("rb") as f:
        for idx in range(parts_total):
            data = f.read(chunk)
            # upos PUT 参数与 biliup 对齐(驼峰 uploadId + 全量分块上下文)
            pr = s.put(base, params={
                "uploadId": upload_id, "chunks": parts_total,
                "total": size, "chunk": idx, "size": chunk,
                "partNumber": idx + 1,
                "start": idx * chunk,
                "end": min((idx + 1) * chunk, size),
            }, data=data, timeout=600, headers=auth_header)
            if pr.status_code >= 400:
                raise RuntimeError(
                    f"分块{idx+1}/{parts_total} 上传失败 HTTP {pr.status_code}: {pr.text[:200]}")
            log(f"    分块 {idx+1}/{parts_total}")

    parts = [{"partNumber": i + 1, "eTag": "etag"} for i in range(parts_total)]
    fr = s.post(base, params={
        "name": filepath.name, "uploadId": upload_id,
        "biz_id": str(pre.get("biz_id", "")), "output": "json",
        "profile": "ugcupos/bup",
    }, json={"parts": parts}, headers=auth_header, timeout=60)
    if fr.status_code >= 400 or '"OK":1' not in fr.text and '"OK": 1' not in fr.text:
        # upos 合并成功返回 {"OK":1,...};其余视为失败
        try:
            j = fr.json()
            if int(j.get("OK", -1)) != 1:
                raise RuntimeError(f"upos 合并失败: {fr.text[:200]}")
        except ValueError:
            raise RuntimeError(f"upos 合并响应异常: {fr.text[:200]}")
    name = upos_uri.rsplit("/", 1)[-1]
    return re.sub(r"\.\w+$", "", name)


def bilibili_publish(video: Path, cover: Path | None, title: str, desc: str,
                     tid: int, tags: str, log) -> dict:
    s = bili_session()
    ok, uname = bili_logged_in(s)
    if not ok:
        raise RuntimeError("B站未登录或登录已失效,请先扫码")
    auth = _read_json(bili_auth_path())
    csrf = (auth.get("cookies") or {}).get("bili_jct", "")
    log(f"  B站账号: {uname}")

    if cover and cover.is_file():
        log("  上传封面...")
        cover_url = _bili_upload_cover(s, csrf, cover.read_bytes())
    else:
        cover_url = ""

    log(f"  初始化分片上传: {video.name} ({video.stat().st_size//1048576}MB)")
    pre = _bili_preupload(s, video.name, video.stat().st_size)
    sessdata = (auth.get("cookies") or {}).get("SESSDATA", "")
    filename = _bili_upos_upload(s, pre, sessdata, video, log)
    log(f"  分片合并完成: {filename}")

    payload = {
        "copyright": 2,
        # 转载类型(2)必须带来源;默认填 B 站原视频归属说明
        "source": "哈佛大学 Tal Ben-Shahar《积极心理学》公开课中文配音",
        "cover": cover_url, "desc": desc,
        "tid": int(tid), "tag": tags, "title": title[:80],
        "filename": filename,
        "videos": [{"filename": filename, "title": "", "desc": ""}],
        "dtime": 0, "act_reserve_create": 0, "no_reprint": 1,
        "csrf": csrf,
    }
    r = s.post("https://member.bilibili.com/x/vu/web/add/v3",
               params={"csrf": csrf}, json=payload, timeout=60)
    j = r.json()
    aid = ((j.get("data") or {}).get("aid"))
    if j.get("code") != 0:
        raise RuntimeError(f"投稿失败 code={j.get('code')} msg={j.get('message')}")
    log(f"  ✓ 投稿成功 aid={aid}")
    return {"aid": aid}


# =====================================================================
# 喜马拉雅(尽力而为:接口无官方文档)
# =====================================================================

def ximalaya_auth_path() -> Path:
    return AUTH_DIR / "ximalaya.json"


def ximalaya_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://www.ximalaya.com/"})
    auth = _read_json(ximalaya_auth_path())
    raw = auth.get("cookie_string") or ""
    for pair in raw.split(";"):
        if "=" in pair:
            k, _, v = pair.strip().partition("=")
            s.cookies.set(k, v, domain=".ximalaya.com")
    return s


_XIMALAYA_CHECK_ENDPOINTS = [
    "https://www.ximalaya.com/revision/main/main/getKaowangMsisdn",
    "https://www.ximalaya.com/revision/user/main",
]


def ximalaya_check(s: requests.Session) -> tuple[bool, str]:
    """尝试多个已知端点判断登录态;都识别不了则返回 unknown。"""
    for url in _XIMALAYA_CHECK_ENDPOINTS:
        try:
            r = s.get(url, timeout=10)
            j = r.json()
            data = j.get("data") or {}
            uid = data.get("uid") or data.get("userId")
            if uid:
                return True, str(data.get("nickname") or uid)
        except Exception:
            continue
    return False, "unknown"


def ximalaya_save_cookies(cookie_string: str) -> dict:
    cookie_string = cookie_string.strip()
    if "1&_token" not in cookie_string and "_xmLog" not in cookie_string:
        raise ValueError("Cookie 内容不像喜马拉雅网页 Cookie(缺少特征字段)")
    _ensure_dirs()
    _write_json(ximalaya_auth_path(), {
        "cookie_string": cookie_string,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }, secure=True)
    ok, info = ximalaya_check(ximalaya_session())
    return {"verified": ok, "info": info}


def ximalaya_list_albums(s: requests.Session) -> list[dict]:
    """尽力列出我的专辑;端点随官网变动可能失效。"""
    candidates = [
        "https://www.ximalaya.com/revision/myAlbum/myAlbums?isWeb=true&page=1&perPage=30&status=ALL&category=-1",
        "https://www.ximalaya.com/revision/album/list?pageSize=30&page=1",
    ]
    last_err = ""
    for url in candidates:
        try:
            r = s.get(url, timeout=15)
            j = r.json()
            data = j.get("data") or {}
            albums = (data.get("albumsPageV2") or {}).get("albums") \
                or data.get("albums") or []
            if albums:
                return [{"id": a.get("id"), "title": a.get("title")}
                        for a in albums]
            last_err = json.dumps(j, ensure_ascii=False)[:150]
        except Exception as e:
            last_err = repr(e)
    raise RuntimeError(f"列出专辑失败(接口可能已变更): {last_err}")


def ximalaya_publish(audio: Path, album_id: int, title: str, desc: str,
                     log) -> dict:
    """上传声音到指定专辑。网页上传走私有 multipart 接口,社区无稳定文档;
    这里按已知路径尝试,失败抛出带指引的错误。"""
    s = ximalaya_session()
    ok, info = ximalaya_check(s)
    if info == "unknown":
        log("  ⚠ 无法确认喜马拉雅登录态,继续尝试上传...")
    elif not ok:
        raise RuntimeError("喜马拉雅 Cookie 已失效,请重新粘贴")
    albums = ximalaya_list_albums(s)
    if not any(str(a["id"]) == str(album_id) for a in albums):
        known = ", ".join(f"{a['id']}={a['title']}" for a in albums[:5])
        raise RuntimeError(f"专辑 {album_id} 不存在或不可见。可见专辑: {known}")

    log("  上传音频文件...")
    r = s.post(
        "https://www.ximalaya.com/revision/upload/track",
        data={"albumId": album_id, "title": title, "content": desc},
        files={"file": (audio.name, audio.read_bytes(), "audio/mpeg")},
        timeout=600,
    )
    j = r.json()
    if j.get("ret") != 200:
        raise RuntimeError(
            f"喜马拉雅上传失败 ret={j.get('ret')} msg={j.get('msg')}。"
            "该接口无官方文档,可能已变更——请到喜马拉雅创作中心手动上传本集音频:"
            f" {audio}")
    log(f"  ✓ 上传成功 track={((j.get('data') or {}).get('trackId'))}")
    return j.get("data") or {}


# =====================================================================
# RSS 播客托管(小宇宙入口)—— feed 动态生成,音频流式读源,零拷贝
# =====================================================================

def rss_default_base() -> str:
    return "https://studio.5945.top/podcast"


def validate_rss_base(url: str) -> str:
    """校验对外 base_url;返回规范化值,非法抛 ValueError。"""
    u = (url or "").strip().rstrip("/")
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("base_url 必须是 http/https 完整地址")
    if re.search(r"\s", u) or any(ord(c) < 0x20 or c in "'\"<>" for c in u):
        raise ValueError("base_url 含非法字符")
    return u


def _feed_base(config: dict) -> str:
    """feed 用地址:配置非法时回退默认,保证 feed 始终可用。"""
    raw = config.get("rss_base_url") or ""
    try:
        return validate_rss_base(raw)
    except ValueError:
        return rss_default_base()


def build_feed(config: dict) -> tuple[str, int]:
    """实时构建 iTunes 兼容 feed。返回 (xml文本, 收录集数)。"""
    base = _feed_base(config)
    author = config.get("rss_author") or SERIES_TITLE
    items_xml = []
    count = 0
    for ep_item in scan_episodes():
        audio = ep_item["audio"]
        if not audio:
            continue
        src = Path(audio)
        ep = ep_item["ep"]
        mtime = datetime.fromtimestamp(src.stat().st_mtime)
        dur_s = _mp3_duration_seconds(src)
        h, m, sec = dur_s // 3600, dur_s % 3600 // 60, dur_s % 60
        duration = f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
        url = f"{base}/audio/ep-{ep:02d}.mp3"
        items_xml.append(f"""    <item>
      <title>{_esc(ep_item['title'])}</title>
      <description>{_esc(ep_item['desc'])}</description>
      <guid isPermaLink="false">happiness-ep-{ep:02d}-{int(src.stat().st_mtime)}</guid>
      <pubDate>{mtime.strftime('%a, %d %b %Y %H:%M:%S +0800')}</pubDate>
      <enclosure url="{_esc(url)}" length="{src.stat().st_size}" type="audio/mpeg"/>
      <itunes:duration>{duration}</itunes:duration>
    </item>""")
        count += 1

    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{_esc(SERIES_TITLE)}</title>
    <link>{_esc(base)}</link>
    <language>zh-cn</language>
    <description>{_esc(SERIES_DESC)}</description>
    <itunes:author>{_esc(author)}</itunes:author>
    <itunes:summary>{_esc(SERIES_DESC)}</itunes:summary>
    <itunes:owner><itunes:name>{_esc(author)}</itunes:name></itunes:owner>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""
    return feed, count


def find_audio_for_episode(ep: int) -> Path | None:
    for e in scan_episodes():
        if e["ep"] == ep and e["audio"]:
            return Path(e["audio"])
    return None


def _mp3_duration_seconds(path: Path) -> int:
    """优先系统 ffprobe,其次纯 Python 解析 MP3 帧头(含 Xing/VBR),
    最后按首帧码率估算。失败再退化为按大小估算。"""
    for ffprobe in (shutil.which("ffprobe"),
                    str(ROOT / "work" / "video-tools" / "ffprobe.exe")):
        if ffprobe:
            try:
                r = subprocess.run([ffprobe, "-v", "error",
                                    "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(path)],
                                   capture_output=True, text=True, timeout=30)
                if r.returncode == 0 and r.stdout.strip():
                    return int(float(r.stdout.strip()))
            except Exception:
                pass
    try:
        dur = _mp3_duration_python(path)
        if dur:
            return dur
    except Exception:
        pass
    try:
        return max(1, int(path.stat().st_size * 8 / 192000))
    except OSError:
        return 3600


_MP3_BITRATES = {  # kbps: [MPEG1 L3, MPEG2/2.5 L3]
    1: [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    2: [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_MP3_RATES = [44100, 48000, 32000]  # MPEG1;MPEG2 减半,MPEG2.5 四分之一


def _first_frame(path: Path):
    """解析首个完整 MP3 帧头,返回 (version_idx, layer, bitrate_kbps,
    samplerate, padding)。找不到有效帧返回 None。"""
    with path.open("rb") as f:
        data = f.read(65536)
    i = 0
    while i < len(data) - 4:
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            b1, b2 = data[i + 1], data[i + 2]
            ver = (b1 >> 3) & 0x03      # 0=2.5 1=保留 2=V2 3=V1
            layer_bits = (b1 >> 1) & 0x03  # 1=L3
            if ver in (0, 2, 3) and layer_bits == 1:
                br_row = 1 if ver == 3 else 2
                rate_row = ((b2 >> 2) & 0x03)
                pad = (b2 >> 1) & 0x01
                if rate_row == 3:
                    i += 1
                    continue
                br = _MP3_BITRATES[br_row][(b2 >> 4) & 0x0F]
                if not br:
                    i += 1
                    continue
                sr = _MP3_RATES[rate_row] // (1 if ver == 3 else 2 if ver == 2 else 4)
                return ver, 3, br, sr, pad
        i += 1
    return None


def _mp3_duration_python(path: Path) -> int:
    """Xing/Info 头给出精确帧数(VBR);否则 CBR 按文件大小/首帧码率计算。"""
    info = _first_frame(path)
    if not info:
        return 0
    ver, _layer, br, sr, pad = info
    samples = 1152 if ver == 3 else 576  # MPEG1 L3=1152, MPEG2/2.5 L3=576
    size = path.stat().st_size

    def frame_len() -> int:
        return (samples // 8) * br * 1000 // sr + pad

    with path.open("rb") as f:
        head = f.read(min(8192, size))
    # 跳过 ID3v2
    off = 0
    if head[:3] == b"ID3" and len(head) >= 10:
        sz = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
        off = 10 + sz
    idx = head.find(b"Xing", off)
    kind = b"Xing"
    if idx < 0:
        idx = head.find(b"Info", off)
        kind = b"Info"
    if idx > 0:
        flags = struct.unpack(">I", head[idx + 4:idx + 8])[0]
        if flags & 0x01:
            frames = struct.unpack(">I",
                                   head[idx + 8:idx + 12])[0]
            if frames:
                exact = frames * samples / sr
                # Xing 存在但可能缺首帧信息而失真:与 CBR 估计差 >20% 时信 CBAR
                cbr_est = size * 8 / (br * 1000)
                if abs(exact - cbr_est) / max(cbr_est, 1) < 0.2 or kind == b"Xing":
                    return int(exact)
    fl = frame_len()
    if fl <= 4:
        return 0
    return int(size / fl * samples / sr)


def _esc(s: str) -> str:
    return (_html.escape(str(s), quote=False)
            .replace('"', "&quot;").replace("'", "&apos;"))


# =====================================================================
# 发布任务(job) —— 单 worker 串行执行,防止并发投稿
# =====================================================================

_jobs_lock = threading.Lock()
_job_queue: "queue.Queue[dict]" = queue.Queue()
_worker_started = False
_inflight: set[str] = set()  # 本进程已入队/执行中的 job_id,重启恢复时跳过
VALID_PLATFORMS = ("bilibili", "ximalaya", "rss")


def _recover_stale_jobs() -> None:
    """进程重启后,把上一次运行遗留的 queued/running 标记为失败。
    本进程 inflight 的任务跳过(可能正在执行)。"""
    for p in JOBS_DIR.glob("*.json"):
        j = _read_json(p)
        if not j or j.get("status") not in ("queued", "running"):
            continue
        if j.get("job_id") in _inflight:
            continue
        # 正在队列里的任务(本进程)不算遗留:_run_job 会写 running 并执行完
        j["status"] = "failed"
        j["error"] = "服务重启导致任务中断,请重新提交"
        if j.get("started_at") and not j.get("ended_at"):
            j["ended_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(p, j)


def _ensure_worker() -> None:
    global _worker_started
    with _jobs_lock:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_job_worker_loop, daemon=True,
                     name="publish-worker").start()


def _active_keys() -> dict[tuple[int, str], str]:
    """queued/running 任务占用 (ep, platform) -> job_id(仅磁盘状态)。"""
    taken = {}
    for p in JOBS_DIR.glob("*.json"):
        j = _read_json(p)
        if not j or j.get("status") not in ("queued", "running"):
            continue
        for it in j.get("items") or []:
            ep = it.get("ep")
            if isinstance(ep, int):
                for plat in j.get("platforms") or []:
                    taken[(ep, plat)] = j.get("job_id") or ""
    return taken


def enqueue_job(items: list[dict], platforms: list[str]) -> tuple[dict, str]:
    """返回 (job, 冲突说明)。冲突非空表示与进行中任务重复,未入队。"""
    _ensure_dirs()
    _recover_stale_jobs()
    job_id = time.strftime("%Y%m%d-") + uuid.uuid4().hex[:8]
    conflict = ""
    taken = _active_keys()
    dupes = sorted({(it["ep"], plat) for it in items for plat in platforms
                    if (it["ep"], plat) in taken})
    if dupes:
        detail = ", ".join(f"EP{ep:02d}×{plat}(任务{jid})"
                           for ep, plat, jid in
                           [(e, p, taken[(e, p)]) for e, p in dupes])
        conflict = f"以下已在发布中,请等待完成或先取消:{detail}"
        return {}, conflict
    job = {
        "job_id": job_id,
        "platforms": platforms,
        "items": [{**it, "results": {}} for it in items],
        "status": "queued",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": None, "ended_at": None,
        "log_file": str(JOBS_DIR / f"{job_id}.log"),
    }
    _write_json(JOBS_DIR / f"{job_id}.json", job)
    with _jobs_lock:
        _inflight.add(job_id)
    _ensure_worker()
    _job_queue.put(job_id)
    return job, ""


def _load_job_by_id(job_id: str) -> dict | None:
    return _read_json(JOBS_DIR / f"{job_id}.json")


def _job_worker_loop() -> None:
    while True:
        job_id = _job_queue.get()
        try:
            job = _load_job_by_id(job_id)
            if not job or job.get("status") != "queued":
                continue  # 重启恢复可能已把它标失败
            _run_job(job)
        except Exception as e:  # 兜底:worker 不能死
            try:
                j = _load_job_by_id(job_id)
                if j:
                    j["status"] = "failed"
                    j["error"] = f"worker 异常: {e}"
                    _write_json(JOBS_DIR / f"{j['job_id']}.json", j)
            except Exception:
                pass
        finally:
            with _jobs_lock:
                _inflight.discard(job_id)
            _job_queue.task_done()


def _log_append(log_path: Path, line: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")


def _run_job(job: dict) -> None:
    log_path = Path(JOBS_DIR) / f"{job['job_id']}.log"
    job["status"] = "running"
    job["started_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(JOBS_DIR / f"{job['job_id']}.json", job)

    def log(line: str) -> None:
        print(line, flush=True)
        _log_append(log_path, line)

    cfg = load_config()

    def persist() -> None:
        _write_json(JOBS_DIR / f"{job['job_id']}.json", job)

    def record_fail(it: dict, key: str, msg: str) -> None:
        it["results"][key] = {"ok": False, "error": msg}

    try:
        platforms = job["platforms"]
        eps = {e["ep"]: e for e in scan_episodes()}

        # RSS 只需 feed 校验,统一先行(逐集确认音频存在)
        if "rss" in platforms:
            base = _feed_base(cfg)
            _, count = build_feed(cfg)
            for it in job["items"]:
                info = eps.get(it["ep"])
                if not info or not info["audio"]:
                    record_fail(it, "rss", "音频不存在,RSS 无法收录该集")
                else:
                    it["results"]["rss"] = {
                        "ok": True, "info": f"{base}/feed.xml ({count}集)"}
            log(f"[RSS] feed 就绪:{count} 集,地址 {base}/feed.xml")
            platforms = [p for p in platforms if p != "rss"]

        for it in job["items"]:
            ep = it["ep"]
            title = it.get("title") or default_title(ep)
            desc = it.get("desc") or default_desc(ep)
            paths = eps.get(ep)
            if not paths:
                record_fail(it, "error", f"EP{ep:02d} 不存在")
                continue

            if "bilibili" in platforms:
                key = "bilibili"
                if not paths["video"]:
                    record_fail(it, key, "视频不存在,无法发B站")
                else:
                    log(f"[B站] EP{ep:02d} {title}")
                    try:
                        res = bilibili_publish(
                            Path(paths["video"]),
                            Path(paths["cover"]) if paths["cover"] else None,
                            title, desc, it.get("tid") or DEFAULT_TID,
                            it.get("tags") or DEFAULT_TAGS, log)
                        it["results"][key] = {"ok": True, **res}
                        log(f"[B站] EP{ep:02d} ✓")
                    except Exception as e:
                        record_fail(it, key, str(e))
                        log(f"[B站] EP{ep:02d} ✗ {e}")
                    time.sleep(10)  # 投稿间隔,避免风控

            if "ximalaya" in platforms:
                key = "ximalaya"
                if not paths["audio"]:
                    record_fail(it, key, "音频不存在,无法传喜马")
                else:
                    album_id = int(it.get("album_id") or 0)
                    if album_id <= 0:
                        record_fail(it, key, "未配置专辑ID(xmly_album_id)")
                        log(f"[喜马] EP{ep:02d} ✗ 未配置专辑ID")
                    else:
                        log(f"[喜马] EP{ep:02d} {title}")
                        try:
                            res = ximalaya_publish(
                                Path(paths["audio"]), album_id, title, desc, log)
                            it["results"][key] = {"ok": True, **res}
                            log(f"[喜马] EP{ep:02d} ✓")
                        except Exception as e:
                            record_fail(it, key, str(e))
                            log(f"[喜马] EP{ep:02d} ✗ {e}")
            persist()

        failed = sum(
            1 for it in job["items"] for r in (it.get("results") or {}).values()
            if (isinstance(r, dict) and not r.get("ok"))
            or isinstance(r, str))  # 兼容旧格式字符串错误
        # 保证请求过的每个平台都有结果记录(缺资源/未配置也算失败已覆盖)
        total_expected = sum(
            1 for it in job["items"]
            for plat in job["platforms"])
        recorded = sum(len((it.get("results") or {})) for it in job["items"])
        if recorded < total_expected:
            failed += total_expected - recorded
            log(f"!! 有 {total_expected - recorded} 个平台项无结果,按失败计")
        job["status"] = "done" if failed == 0 else "failed"
        if failed:
            job["error"] = f"{failed} 个子任务失败,详见日志"
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        log(f"!! 任务异常: {e}")
    finally:
        job["ended_at"] = datetime.now().isoformat(timespec="seconds")
        persist()


def list_jobs(limit: int = 20) -> list[dict]:
    jobs = []
    for p in JOBS_DIR.glob("*.json"):
        j = _read_json(p)
        if not j:
            continue
        brief = {k: j.get(k) for k in
                 ("job_id", "platforms", "status", "created_at", "error")}
        brief["items_count"] = len(j.get("items") or [])
        ok = bad = 0
        for it in j.get("items") or []:
            for r in (it.get("results") or {}).values():
                if isinstance(r, dict):
                    if r.get("ok"):
                        ok += 1
                    else:
                        bad += 1
        brief["sub_ok"], brief["sub_bad"] = ok, bad
        jobs.append(brief)
    jobs.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return jobs[:limit]


# =====================================================================
# HTTP 分发(pipeline_admin 调用)
# =====================================================================

def _check_token(handler) -> bool:
    cfg = load_config()
    token = cfg.get("token") or ""
    if not token:
        handler._json({"ok": False, "error": "尚未设置发布口令,先调 /api/pub/setup"},
                      HTTPStatus.UNAUTHORIZED)
        return False
    supplied = handler.headers.get("X-Publish-Token", "")
    import secrets as _secrets
    if not _secrets.compare_digest(supplied, token):
        handler._json({"ok": False, "error": "口令错误"}, HTTPStatus.FORBIDDEN)
        return False
    return True


def pub_state() -> dict:
    cfg = load_config()
    bs = bili_session()
    bili_ok, bili_name = bili_logged_in(bs)
    xm_saved = ximalaya_auth_path().is_file()
    xm_info = ""
    if xm_saved:
        ok, info = ximalaya_check(ximalaya_session())
        xm_info = info if ok else "Cookie 已失效"
    return {
        "configured": bool(cfg.get("token")),
        "mode": MODE,
        "accounts": {
            "bilibili": {"logged": bili_ok, "name": bili_name},
            "ximalaya": {"saved": xm_saved, "info": xm_info},
            "rss": {"base_url": _feed_base(cfg),
                    "author": cfg.get("rss_author") or ""},
        },
        "episodes": scan_episodes(),
        "jobs": list_jobs(),
    }


def dispatch_get(handler) -> bool:
    path = handler.path
    if not path.startswith("/api/pub/") and not path.startswith("/podcast/"):
        return False

    # 公开:播客 feed(动态生成)与音频流(读源文件,支持 Range)
    if path == "/podcast/feed.xml":
        feed, count = build_feed(load_config())
        body = feed.encode("utf-8")
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    m = re.fullmatch(r"/podcast/audio/ep-(\d+)\.mp3", path)
    if m:
        src = find_audio_for_episode(int(m.group(1)))
        if not src or not src.is_file():
            return handler._json({"ok": False, "error": "not found"}, 404)
        size = src.stat().st_size
        rng = handler.headers.get("Range", "")
        start, end = 0, size - 1
        rm = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
        if rm and (rm.group(1) or rm.group(2)):
            if rm.group(1):
                start = int(rm.group(1))
                if rm.group(2):
                    end = min(int(rm.group(2)), size - 1)
            else:  # bytes=-N 后缀
                start = max(0, size - int(rm.group(2)))
        if start > end or start >= size:
            handler.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            handler.send_header("Content-Range", f"bytes */{size}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return True
        length = end - start + 1
        handler.send_response(HTTPStatus.PARTIAL_CONTENT if (rm and rng) else HTTPStatus.OK)
        if rm and rng:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.send_header("Content-Type", "audio/mpeg")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", str(length))
        handler.end_headers()
        with src.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk_data = f.read(min(256 * 1024, remaining))
                if not chunk_data:
                    break
                handler.wfile.write(chunk_data)
                remaining -= len(chunk_data)
        return True

    if not _check_token(handler):
        return True

    if path == "/api/pub/state":
        return handler._json({"ok": True, **pub_state()})
    if path.startswith("/api/pub/bilibili/qr/poll"):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(path).query)
        key = (qs.get("key") or [""])[0]
        try:
            return handler._json({"ok": True, **bilibili_qr_poll(key)})
        except Exception as e:
            return handler._json({"ok": False, "error": str(e)}, 502)
    m = re.fullmatch(r"/api/pub/jobs/([A-Za-z0-9-]+)", path)
    if m:
        j = _read_json(JOBS_DIR / f"{m.group(1)}.json")
        if not j:
            return handler._json({"ok": False, "error": "not found"}, 404)
        # 日志路径按 job_id 在 JOBS_DIR 内重建,不信任状态文件里的任意路径
        tail = ""
        lp = JOBS_DIR / f"{m.group(1)}.log"
        if lp.is_file():
            tail = lp.read_text(encoding="utf-8", errors="replace")[-4000:]
        j["log_tail"] = tail
        return handler._json({"ok": True, "job": j})
    return handler._json({"ok": False, "error": "not found"}, 404)


def dispatch_post(handler) -> bool:
    if not handler.path.startswith("/api/pub/"):
        return False

    if handler.path == "/api/pub/setup":
        cfg = load_config()
        if cfg.get("token"):
            return handler._json({"ok": False, "error": "口令已设置"},
                                 HTTPStatus.CONFLICT)
        body = handler._body()
        token = (body.get("token") or "").strip()
        if len(token) < 6:
            return handler._json({"ok": False,
                                  "error": "口令至少 6 位"}, 400)
        save_config({**cfg, "token": token})
        return handler._json({"ok": True})

    if not _check_token(handler):
        return True

    if handler.path == "/api/pub/bilibili/qr":
        try:
            return handler._json({"ok": True, **bilibili_qr_create()})
        except Exception as e:
            return handler._json({"ok": False, "error": str(e)}, 502)
    if handler.path == "/api/pub/bilibili/logout":
        bili_logout()
        return handler._json({"ok": True})
    if handler.path == "/api/pub/ximalaya/cookies":
        try:
            body = handler._body()
            res = ximalaya_save_cookies(body.get("cookie_string") or "")
            return handler._json({"ok": True, **res})
        except Exception as e:
            return handler._json({"ok": False, "error": str(e)}, 400)
    if handler.path == "/api/pub/rss/config":
        body = handler._body()
        cfg = load_config()
        try:
            if "rss_base_url" in body and (body.get("rss_base_url") or "").strip():
                cfg["rss_base_url"] = validate_rss_base(body["rss_base_url"])
            elif "rss_base_url" in body:
                cfg.pop("rss_base_url", None)  # 显式清空 → 回默认
        except ValueError as e:
            return handler._json({"ok": False, "error": str(e)}, 400)
        if "rss_author" in body:
            cfg["rss_author"] = str(body.get("rss_author") or "").strip()[:80]
        if "xmly_album_id" in body:
            try:
                album = int(body.get("xmly_album_id") or 0)
                assert album >= 0
            except Exception:
                return handler._json({"ok": False,
                                      "error": "专辑ID须为非负整数"}, 400)
            cfg["xmly_album_id"] = album
        save_config(cfg)
        return handler._json({"ok": True})
    if handler.path == "/api/pub/jobs":
        body = handler._body()
        items = body.get("items") or []
        raw_platforms = body.get("platforms") or []
        platforms = [str(p).strip().lower() for p in raw_platforms]
        unknown = sorted({p for p in platforms
                          if p not in VALID_PLATFORMS})
        if unknown:
            return handler._json(
                {"ok": False,
                 "error": f"未知平台: {', '.join(unknown)}(支持 "
                          f"{'/'.join(VALID_PLATFORMS)})"}, 400)
        seen: set[str] = set()
        platforms = [p for p in platforms
                     if not (p in seen or seen.add(p))]
        if not items or not platforms:
            return handler._json({"ok": False,
                                  "error": "items/platforms 不能为空"}, 400)
        try:
            req_album = int(body.get("xmly_album_id") or 0)
        except Exception:
            return handler._json({"ok": False,
                                  "error": "专辑ID须为非负整数"}, 400)
        clean_items = []
        ep_seen: set[int] = set()
        for it in items:
            try:
                ep = int(it.get("ep"))
            except Exception:
                continue
            if not 1 <= ep <= TOTAL_EPISODES or ep in ep_seen:
                continue
            ep_seen.add(ep)
            clean_items.append({
                "ep": ep,
                "title": (it.get("title") or "").strip() or default_title(ep),
                "desc": (it.get("desc") or "").strip() or default_desc(ep),
                "tid": it.get("tid") or DEFAULT_TID,
                "tags": it.get("tags") or DEFAULT_TAGS,
                "album_id": int(it.get("album_id") or 0) or req_album,
            })
        if not clean_items:
            return handler._json({"ok": False, "error": "没有有效集数"}, 400)
        job, conflict = enqueue_job(clean_items, platforms)
        if conflict:
            return handler._json({"ok": False, "error": conflict},
                                 HTTPStatus.CONFLICT)
        return handler._json({"ok": True, "job_id": job["job_id"]},
                             HTTPStatus.ACCEPTED)
    return handler._json({"ok": False, "error": "not found"}, 404)


def dispatch(handler) -> bool:
    """pipeline_admin 的 do_GET/do_POST 顶部调用。处理了返回 True。"""
    if handler.command == "GET":
        return dispatch_get(handler)
    if handler.command == "POST":
        return dispatch_post(handler)
    return False
