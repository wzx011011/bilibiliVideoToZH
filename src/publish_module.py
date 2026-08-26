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
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from pathlib import Path

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


def load_config() -> dict:
    return _read_json(CONFIG_PATH)


def save_config(cfg: dict) -> None:
    _ensure_dirs()
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


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


def bilibili_qr_create() -> dict:
    r = requests.get(BILI_QR_GEN, headers={"User-Agent": UA}, timeout=10)
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
    return out


def bilibili_qr_poll(key: str) -> dict:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    r = s.get(BILI_QR_POLL, params={"qrcode_key": key}, timeout=10,
              allow_redirects=False)
    j = r.json()
    code = int(((j.get("data") or {}).get("code")) or -1)
    out = {"code": code}  # 180=未扫 86090=已扫待确认 86038=过期 0=成功
    if code == 0:
        cookies = {c.name: c.value for c in s.cookies}
        for c in r.cookies:  # 响应 Set-Cookie 里的 SESSDATA/bili_jct 等
            cookies[c.name] = c.value
        missing = [k for k in ("SESSDATA", "bili_jct") if not cookies.get(k)]
        if missing:
            out["error"] = f"登录响应缺少 Cookie: {missing}"
            return out
        _ensure_dirs()
        _write_json(bili_auth_path(), {
            "cookies": cookies,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        })
        ok, uname = bili_logged_in()
        out["uname"] = uname
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
    url = ((j.get("data") or {}).get("image_url")) or ""
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        raise RuntimeError(f"封面响应异常: {json.dumps(j)[:200]}")
    return url


def _bili_preupload(s: requests.Session, fname: str, size: int) -> dict:
    r = s.get("https://member.bilibili.com/preupload", params={
        "name": fname, "size": size, "r": "upos",
        "profile": "ugcfx/bup", "upcdn": "bda2",
        "probe_version": "20221109",
    }, timeout=30)
    j = r.json()
    if not j.get("upos_uri"):
        raise RuntimeError(f"preupload 失败: {json.dumps(j)[:300]}")
    return j


def _bili_upos_upload(s: requests.Session, pre: dict, sessdata: str,
                      filepath: Path, log) -> str:
    """分块 PUT 到 upos,返回 bili_filename。所有请求需带 X-Upos-Auth(SESSDATA)。"""
    upos_uri = pre["upos_uri"]
    endpoint = pre["endpoint"]
    if endpoint.startswith("//"):
        endpoint = "https:" + endpoint
    base = f"{endpoint}/{upos_uri}"
    auth_header = {"X-Upos-Auth": sessdata}
    chunk = 4 * 1024 * 1024
    size = filepath.stat().st_size
    parts_total = max(1, (size + chunk - 1) // chunk)

    r = s.post(f"{base}", params={
        "uploads": "", "output": "json", "profile": "ugcfx/bup"},
        headers=auth_header, timeout=30)
    r.raise_for_status()
    upload_id = r.json()["upload_id"]

    with filepath.open("rb") as f:
        for idx in range(parts_total):
            data = f.read(chunk)
            pr = s.put(base, params={
                "partNumber": idx + 1, "upload_id": upload_id,
                "output": "json", "profile": "ugcfx/bup",
            }, data=data, timeout=600, headers=auth_header)
            if pr.status_code >= 400:
                raise RuntimeError(
                    f"分块{idx+1}/{parts_total} 上传失败 HTTP {pr.status_code}: {pr.text[:200]}")
            log(f"    分块 {idx+1}/{parts_total}")

    parts = [{"part": i + 1, "oname": f"part{i+1}"} for i in range(parts_total)]
    fr = s.post(base, params={
        "output": "json", "name": filepath.name, "profile": "ugcfx/bup",
        "submit": "false", "filesize": str(size), "biz_id": str(pre.get("biz_id", "")),
    }, json={"parts": parts}, headers=auth_header, timeout=60)
    if fr.status_code >= 400 or '"ok":0' not in fr.text and '"ok": 0' not in fr.text \
            and '"ok":4' not in fr.text and '"ok": 4' not in fr.text:
        # upos 合并成功时 ok 可能为 0(幂等已存在)或 4;其余视为失败
        try:
            j = fr.json()
            if int(j.get("ok", -1)) not in (0, 4):
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
        "copyright": 2, "source": "", "cover": cover_url, "desc": desc,
        "tid": int(tid), "tag": tags, "title": title[:80],
        "filename": filename,
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
    })
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


def build_feed(config: dict) -> tuple[str, int]:
    """实时构建 iTunes 兼容 feed。返回 (xml文本, 收录集数)。"""
    base = (config.get("rss_base_url") or rss_default_base()).rstrip("/")
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
    ffprobe = ROOT / "work" / "video-tools" / "ffprobe.exe"
    try:
        r = subprocess.run([str(ffprobe), "-v", "error",
                            "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30)
        return int(float(r.stdout.strip()))
    except Exception:
        # 容器无 ffprobe:按 192kbps CBR 估算(本系列音频均为该码率)
        try:
            return max(1, int(path.stat().st_size * 8 / 192000))
        except OSError:
            return 3600


def _esc(s: str) -> str:
    return (_html.escape(str(s), quote=False)
            .replace('"', "&quot;").replace("'", "&apos;"))


# =====================================================================
# 发布任务(job)
# =====================================================================

_jobs_lock = threading.Lock()


def enqueue_job(items: list[dict], platforms: list[str]) -> dict:
    job_id = time.strftime("%Y%m%d-") + uuid.uuid4().hex[:8]
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
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return job


def _log_append(log_path: Path, line: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")


def _run_job(job: dict) -> None:
    _ensure_dirs()
    log_path = Path(job["log_file"])
    job["status"] = "running"
    job["started_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(JOBS_DIR / f"{job['job_id']}.json", job)

    def log(line: str) -> None:
        print(line, flush=True)
        _log_append(log_path, line)

    cfg = load_config()

    def persist() -> None:
        _write_json(JOBS_DIR / f"{job['job_id']}.json", job)

    try:
        platforms = job["platforms"]
        if "rss" in platforms:
            # feed 是动态的:这里只做校验并回填 feed 地址
            base = (cfg.get("rss_base_url") or rss_default_base()).rstrip("/")
            _, count = build_feed(cfg)
            for it in job["items"]:
                it["results"]["rss"] = {"ok": True,
                                        "info": f"{base}/feed.xml ({count}集)"}
            log(f"[RSS] feed 就绪:{count} 集,地址 {base}/feed.xml")
            platforms = [p for p in platforms if p != "rss"]

        for it in job["items"]:
            ep = it["ep"]
            title = it.get("title") or default_title(ep)
            desc = it.get("desc") or default_desc(ep)
            paths = next((e for e in scan_episodes() if e["ep"] == ep), None)
            if not paths:
                it["results"]["error"] = f"EP{ep:02d} 不存在"
                continue

            if "bilibili" in platforms:
                key = "bilibili"
                if not paths["video"]:
                    it["results"][key] = {"ok": False, "error": "视频不存在"}
                    continue
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
                    it["results"][key] = {"ok": False, "error": str(e)}
                    log(f"[B站] EP{ep:02d} ✗ {e}")
                time.sleep(10)  # 投稿间隔,避免风控

            if "ximalaya" in platforms:
                key = "ximalaya"
                if not paths["audio"]:
                    it["results"][key] = {"ok": False, "error": "音频不存在"}
                    continue
                log(f"[喜马] EP{ep:02d} {title}")
                try:
                    res = ximalaya_publish(
                        Path(paths["audio"]), int(cfg.get("xmly_album_id") or 0),
                        title, desc, log)
                    it["results"][key] = {"ok": True, **res}
                    log(f"[喜马] EP{ep:02d} ✓")
                except Exception as e:
                    it["results"][key] = {"ok": False, "error": str(e)}
                    log(f"[喜马] EP{ep:02d} ✗ {e}")
                persist()

        failed = sum(1 for it in job["items"]
                     for r in (it["results"] or {}).values()
                     if isinstance(r, dict) and not r.get("ok"))
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
            "rss": {"base_url": (cfg.get("rss_base_url")
                                 or rss_default_base()).rstrip("/"),
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
        tail = ""
        lp = Path(j.get("log_file") or "")
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
            return handler._json({"ok": False, "error": "口令已设置,如需重置请删 "
                                  f"{CONFIG_PATH}"}, HTTPStatus.CONFLICT)
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
        for k in ("rss_base_url", "rss_author", "xmly_album_id"):
            if k in body:
                cfg[k] = body[k]
        save_config(cfg)
        return handler._json({"ok": True})
    if handler.path == "/api/pub/jobs":
        body = handler._body()
        items = body.get("items") or []
        platforms = body.get("platforms") or []
        if not items or not platforms:
            return handler._json({"ok": False,
                                  "error": "items/platforms 不能为空"}, 400)
        clean_items = []
        for it in items:
            try:
                ep = int(it.get("ep"))
            except Exception:
                continue
            if not 1 <= ep <= TOTAL_EPISODES:
                continue
            clean_items.append({
                "ep": ep,
                "title": (it.get("title") or "").strip() or default_title(ep),
                "desc": (it.get("desc") or "").strip() or default_desc(ep),
                "tid": it.get("tid") or DEFAULT_TID,
                "tags": it.get("tags") or DEFAULT_TAGS,
            })
        if not clean_items:
            return handler._json({"ok": False, "error": "没有有效集数"}, 400)
        job = enqueue_job(clean_items, [str(p) for p in platforms])
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
