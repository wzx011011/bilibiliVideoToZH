# -*- coding: utf-8 -*-
"""
豆包朗读工具(路径 A:网页发消息 + 脚本自动朗读)

完整流程:
  你(网页):发字幕+提示词给豆包,拿到回复
  脚本(本工具):
    1) list   —— 列出最近的豆包回复(带文本预览)
    2) read N —— 自动朗读第 N 条,保存为 .ogg 音频

用法:
  python doubao_reader.py            # 交互菜单
  python doubao_reader.py list       # 只列消息
  python doubao_reader.py read 3     # 直接朗读第 3 条
  python doubao_reader.py read-all   # 批量朗读最近的 5 条

依赖: pip install websockets requests

账号/设备参数从环境变量或同目录 .env 文件读取(见 doubao.env.example)。
不要把真实 cookie / 设备号写进源码或提交到仓库。
"""
import asyncio
import json
import os
import re
import sys
import time
import uuid

# ======================== 加载本地 .env ========================
try:
    from pathlib import Path
    _env_file = Path(__file__).resolve().parents[1] / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
except Exception:
    pass

import requests
import websockets


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(
            f"[✗] 缺少环境变量 {name}。请复制 doubao.env.example 为 .env 并填入真实值,"
            f"或通过环境变量导出。切勿把凭据写进源码。"
        )
    return val


# ======================== 账号配置 ========================
# 从你抓包来的 cookie(失效后重新登录豆包网页,替换 .env 里的 DOUBAO_COOKIE)
COOKIE = _require("DOUBAO_COOKIE")

# 设备参数(固定,来自抓包)
DEVICE_ID   = _require("DOUBAO_DEVICE_ID")
WEB_ID      = os.environ.get("DOUBAO_WEB_ID", DEVICE_ID)
TEA_UUID    = os.environ.get("DOUBAO_TEA_UUID", WEB_ID)
WEB_TAB_ID  = _require("DOUBAO_WEB_TAB_ID")
API_APP_KEY = _require("DOUBAO_API_APP_KEY")
UID         = _require("DOUBAO_UID")

# 音色(桃桃女声,豆包默认)
SPEAKER = "zh_female_taozi_conversation_v4_wvae_bigtts"

# 输出目录
OUTPUT_DIR = "audio_out"


# ======================== 消息列表接口 ========================
def fetch_messages(limit=20, per_conv=10):
    """拉取最近的豆包对话,返回扁平化的回复列表(只取豆包回复)"""
    url = "https://www.doubao.com/im/chain/recent_conv"
    params = {
        "version_code": "20800", "language": "zh", "device_platform": "web",
        "doubao_device_platform": "web", "aid": "497858", "real_aid": "497858",
        "pkg_type": "release_version", "device_id": DEVICE_ID,
        "pc_version": "3.29.1", "doubao_pc_version": "3.29.1",
        "web_id": WEB_ID, "tea_uuid": TEA_UUID,
        "region": "CN", "sys_region": "CN", "samantha_web": "1",
        "web_platform": "browser", "use-olympus-account": "1",
        "web_tab_id": WEB_TAB_ID,
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "agw-js-conv": "str",
        "content-type": "application/json; encoding=utf-8",
        "origin": "https://www.doubao.com",
        "referer": "https://www.doubao.com/",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0"),
        "cookie": COOKIE,
    }
    data = {
        "cmd": 3200,
        "uplink_body": {"pull_recent_conv_chain_uplink_body": {
            "limit": limit, "message_count_per_conv": per_conv,
            "api_version": 1, "conv_version": 0, "direction": 3,
            "option": {
                "not_need_message": False, "need_complete_conversation": True,
                "need_coco_conversation": True, "need_coco_bot": True,
                "need_pc_pin_chain": True, "pc_pin_query_type": 0,
            },
        }},
        "sequence_id": str(uuid.uuid4()), "channel": 2, "version": "1",
    }
    r = requests.post(url, params=params, headers=headers, json=data, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("status_code") != 0:
        raise RuntimeError(f"接口返回错误: {d.get('status_desc')}")

    cells = d["downlink_body"]["pull_recent_conv_chain_downlink_body"]["cells"]

    # 扁平化:只收集「豆包回复」(user_type=2 是豆包)
    replies = []
    for cell in cells:
        conv = cell.get("conversation") or {}
        if isinstance(conv, str):
            conv = json.loads(conv)
        conv_id = conv.get("conversation_id", "")
        for m in conv.get("messages", []):
            # user_type=2 = 豆包回复;user_type=1 = 你的提问
            if str(m.get("user_type")) != "2":
                continue
            # tts_content 是朗读用的纯文本;brief 是摘要
            tts = (m.get("tts_content") or "").strip()
            brief = (m.get("brief") or "").strip()
            ext = m.get("ext") or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}
            reply_unique_key = ext.get("reply_unique_key", "")
            if not reply_unique_key:
                continue
            replies.append({
                "message_id": str(m.get("message_id", "")),
                "bot_reply_message_id": str(m.get("bot_reply_message_id", "")),  # = question_id
                "conversation_id": str(conv_id),
                "section_id": str(m.get("section_id", "")),
                "reply_unique_key": reply_unique_key,
                "tts_content": tts,
                "brief": brief,
                "create_time": int(m.get("create_time", 0) or 0),
            })
    # 按时间倒序
    replies.sort(key=lambda x: x["create_time"], reverse=True)
    return replies


def preview_text(text, n=80):
    """文本预览:取前 n 字,去换行"""
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:n] + ("…" if len(t) > n else "")


# ======================== protobuf 编解码 ========================
def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)

def _field(field_num, value_bytes):
    tag = (field_num << 3) | 2
    return bytes([tag]) + _varint(len(value_bytes)) + value_bytes

def build_message(api_key, namespace, command, payload_json, task_id=None):
    msg = b""
    msg += _field(2, api_key.encode())
    msg += _field(3, namespace.encode())
    msg += _field(5, command.encode())
    msg += _field(6, payload_json.encode())
    if task_id:
        msg += _field(8, task_id.encode())
    return msg

def parse_fields(data):
    fields = []
    i = 0
    while i < len(data):
        tag = data[i]; i += 1
        field_num = tag >> 3
        wire = tag & 7
        if wire == 2:
            length = 0; shift = 0
            while i < len(data):
                b = data[i]; i += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80): break
                shift += 7
            fields.append((field_num, data[i:i+length]))
            i += length
        elif wire == 0:
            while i < len(data):
                if not (data[i] & 0x80): i += 1; break
                i += 1
        else:
            break
    return fields


# ======================== 朗读 WS ========================
def make_payload(reply, speaker: str | None = None):
    common = {
        "business": 1,
        "conversation_id": reply["conversation_id"],
        "chat": {
            "bot_id": "",
            "conversation_id": reply["conversation_id"],
            "question_id": reply["bot_reply_message_id"],
            "message_id": reply["message_id"],
            "uid": UID,
            "new_conversation": False,
            "chat_next": "1",
            "enable_toast_reading": "true",
            "extra": {
                "chat_next": "1",
                "reply_unique_key": reply["reply_unique_key"],
                "query_local_message_id": str(uuid.uuid1()),
            },
            "reply_unique_key": reply["reply_unique_key"],
            "section_id": reply["section_id"],
            "local_message_id": str(uuid.uuid1()),
            "query_local_message_id": str(uuid.uuid1()),
        },
        "request_type": 4,
        "enable_text_reading": True,
        "interrupt_type": 0,
        "query_mode": 2,
        "tts": {
            "speaker": speaker or SPEAKER,
            "audio_config": {"bit_rate": 32000, "format": "ogg_opus", "sample_rate": 24000},
            "extra": {"chat_next": "1", "post_process": {"pitch": 0, "speech_rate": 1}},
        },
        "extra": {
            "enable_toast_reading": "true", "chat_next": "1", "uid": UID,
            "section_id": reply["section_id"],
            "reply_unique_key": reply["reply_unique_key"],
        },
    }
    return json.dumps(common, ensure_ascii=False)


async def read_reply(reply, output_path, verbose=True, speaker: str | None = None):
    """朗读一条回复,保存为 ogg。返回音频字节数。

    speaker: 音色 ID,默认用模块级 SPEAKER(桃桃)。多人物配音时按说话人传不同 ID。
    """
    task_id = str(uuid.uuid4())
    ws_url = (
        "wss://frontier-audio-web-ws.doubao.com/api/v2/sami/voicegenie"
        f"?api_app_key={API_APP_KEY}&namespace=VoiceGenie&version_code=20800"
        "&language=zh&device_platform=web&pkg_type=release_version&pc_version=3.29.1"
        "&region=CN&sys_region=CN&samantha_web=1&use-olympus-account=1"
        "&doubao_device_platform=web&aid=497858&real_aid=497858"
        f"&device_id={DEVICE_ID}&doubao_pc_version=3.29.1"
        f"&web_id={WEB_ID}&tea_uuid={TEA_UUID}&web_platform=browser&web_tab_id={WEB_TAB_ID}"
    )
    headers = {
        "Origin": "https://www.doubao.com",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cookie": COOKIE,
    }

    audio_chunks = []
    IDLE_TIMEOUT = 15

    async with websockets.connect(ws_url, additional_headers=headers) as ws:
        await ws.send(build_message(API_APP_KEY, "VoiceGenie", "StartTask", "{}"))
        await ws.send(build_message(API_APP_KEY, "VoiceGenie", "StartSession",
                                    make_payload(reply, speaker), task_id))
        await ws.send(build_message(API_APP_KEY, "VoiceGenie", "StartTTS",
                                    make_payload(reply, speaker), task_id))
        finished = False
        got_audio = False
        last_print = 0
        while not finished:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                break
            except websockets.ConnectionClosed:
                break
            if isinstance(msg, str):
                if got_audio and ("Finish" in msg or "End" in msg):
                    finished = True
                continue
            fields = parse_fields(msg)
            statuses = [v.decode('utf-8', 'replace') for fn, v in fields if fn == 4]
            for fn, v in fields:
                if fn == 8 and len(v) > 0:
                    audio_chunks.append(v)
                    got_audio = True
                    total = sum(len(c) for c in audio_chunks)
                    if verbose and (total < 2048 or time.time() - last_print > 2):
                        print(f"    接收中... {total} bytes ({round(total/1024,1)} KB)", end="\r", flush=True)
                        last_print = time.time()
                    break
            if got_audio:
                for st in statuses:
                    if "Finish" in st or "Ended" in st or "Complete" in st:
                        finished = True
                        break

    if audio_chunks:
        full = b"".join(audio_chunks)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(full)
        if verbose:
            print(f" " * 40, end="\r")
            print(f"    [✓] 保存: {output_path} ({round(len(full)/1024,1)} KB)")
        return len(full)
    if verbose:
        print(f"    [✗] 未收到音频(可能刚读过/被去重,稍等再试)")
    return 0


# ======================== CLI ========================
def cmd_list():
    print("正在拉取最近的豆包回复...")
    try:
        replies = fetch_messages()
    except Exception as e:
        print(f"\n[✗] 拉取失败:{e}")
        print("    最常见原因:COOKIE 失效或未填写。")
        print("    解决:重新登录豆包网页,按 README 第三章重新抓 cookie,填到脚本顶部 COOKIE 变量。")
        return []
    if not replies:
        print("没拉到任何回复。检查 cookie 是否失效。")
        return replies
    print(f"\n找到 {len(replies)} 条豆包回复(按时间倒序):\n")
    print(f"{'序号':<5} {'时间':<19} {'预览':<60}")
    print("-" * 85)
    for i, r in enumerate(replies):
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["create_time"]))
        prev = preview_text(r["brief"] or r["tts_content"], 55)
        print(f"{i+1:<5} {t:<19} {prev}")
    return replies


def cmd_read(idx, replies=None):
    if replies is None:
        replies = fetch_messages()
    if idx < 1 or idx > len(replies):
        print(f"序号超出范围(1~{len(replies)})")
        return
    r = replies[idx - 1]
    print(f"\n准备朗读第 {idx} 条:")
    print(f"  message_id: {r['message_id']}")
    print(f"  预览: {preview_text(r['brief'] or r['tts_content'], 70)}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_time = time.strftime("%Y%m%d_%H%M%S", time.localtime(r["create_time"]))
    out = os.path.join(OUTPUT_DIR, f"doubao_{safe_time}_{r['message_id']}.ogg")
    n = asyncio.run(read_reply(r, out))
    if n:
        print(f"\n[完成] {out}")
        print(f"       Windows 默认播放器:explorer \"{out}\"")
    return out


def cmd_read_all(max_n=5):
    replies = fetch_messages()
    print(f"将批量朗读最近 {min(max_n, len(replies))} 条回复\n")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for i in range(1, min(max_n, len(replies)) + 1):
        r = replies[i - 1]
        safe_time = time.strftime("%Y%m%d_%H%M%S", time.localtime(r["create_time"]))
        out = os.path.join(OUTPUT_DIR, f"doubao_{safe_time}_{r['message_id']}.ogg")
        if os.path.exists(out):
            print(f"[{i}] 已存在,跳过: {out}")
            continue
        print(f"[{i}] {preview_text(r['brief'], 50)}")
        asyncio.run(read_reply(r, out))
        if i < min(max_n, len(replies)):
            time.sleep(2)  # 避免被风控
    print("\n[全部完成]")


def interactive():
    while True:
        print("\n" + "=" * 50)
        print(" 豆包朗读工具")
        print("=" * 50)
        print("  list        列出最近的豆包回复")
        print("  read N      朗读第 N 条")
        print("  read-all    批量朗读最近 5 条")
        print("  quit        退出")
        cmd = input("\n请输入命令: ").strip().lower()
        if cmd in ("q", "quit", "exit"):
            break
        elif cmd == "list":
            cmd_list()
        elif cmd.startswith("read-all"):
            parts = cmd.split()
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
            cmd_read_all(n)
        elif cmd.startswith("read"):
            parts = cmd.split()
            if len(parts) < 2 or not parts[1].isdigit():
                print("用法: read N (N 是 list 里的序号)")
                continue
            replies = cmd_list()  # 先列出
            cmd_read(int(parts[1]), replies)
        else:
            print("未知命令")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        interactive()
    elif args[0] == "list":
        cmd_list()
    elif args[0] == "read-all":
        n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 5
        cmd_read_all(n)
    elif args[0] == "read":
        replies = cmd_list()
        if len(args) > 1 and args[1].isdigit():
            cmd_read(int(args[1]), replies)
    else:
        print(__doc__)
