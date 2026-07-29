# -*- coding: utf-8 -*-
"""
豆包网页版"朗读"音频抓取器
原理:复刻 wss://frontier-audio-web-ws.doubao.com 的 chat_tts 协议
     客户端只发 message_id,服务端拉取该条豆包回复的文本并流式合成 ogg_opus 音频

依赖: pip install websockets

账号/设备参数从环境变量或同目录 .env 文件读取(见 doubao.env.example)。
不要把真实 cookie / 设备号写进源码或提交到仓库。
"""
import asyncio
import json
import os
import uuid

try:  # 可选: 读取同目录 .env(若有 python-dotenv 也可一并使用)
    from pathlib import Path
    _env_file = Path(__file__).resolve().parent / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
except Exception:
    pass

import websockets


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(
            f"[✗] 缺少环境变量 {name}。请复制 doubao.env.example 为 .env 并填入真实值,"
            f"或通过环境变量导出。切勿把凭据写进源码。"
        )
    return val


# ============== 账号/设备参数(从环境变量 / .env 读取) ==============
# COOKIE: 浏览器抓包得到的完整 cookie 串(sessionid、sid_tt、ttwid、passport_csrf_token 等)
COOKIE = _require("DOUBAO_COOKIE")
DEVICE_ID   = _require("DOUBAO_DEVICE_ID")
WEB_ID      = os.environ.get("DOUBAO_WEB_ID", DEVICE_ID)
TEA_UUID    = os.environ.get("DOUBAO_TEA_UUID", WEB_ID)
WEB_TAB_ID  = _require("DOUBAO_WEB_TAB_ID")
API_APP_KEY = _require("DOUBAO_API_APP_KEY")
UID         = _require("DOUBAO_UID")

# ============== 朗读目标(每次朗读改这里) ==============
# 这是"你要朗读的那条豆包回复"的标识
MESSAGE_ID       = _require("DOUBAO_MESSAGE_ID")       # 豆包回复的 message_id
CONVERSATION_ID  = _require("DOUBAO_CONVERSATION_ID")  # 会话 id (URL 里的 /chat/xxx)
QUESTION_ID      = _require("DOUBAO_QUESTION_ID")      # 你提问的 question_id
SECTION_ID       = _require("DOUBAO_SECTION_ID")
REPLY_UNIQUE_KEY = _require("DOUBAO_REPLY_UNIQUE_KEY")

# 音色(桃桃女声),可换成豆包里其它音色 id
SPEAKER = "zh_female_taozi_conversation_v4_wvae_bigtts"

OUTPUT_FILE = "doubao_audio.ogg"

# ============== WebSocket URL ==============
WS_URL = (
    "wss://frontier-audio-web-ws.doubao.com/api/v2/sami/voicegenie"
    f"?api_app_key={API_APP_KEY}"
    "&namespace=VoiceGenie&version_code=20800&language=zh"
    "&device_platform=web&pkg_type=release_version&pc_version=3.29.1"
    "&region=CN&sys_region=CN&samantha_web=1&use-olympus-account=1"
    "&doubao_device_platform=web&aid=497858&real_aid=497858"
    f"&device_id={DEVICE_ID}&doubao_pc_version=3.29.1"
    f"&web_id={WEB_ID}&tea_uuid={TEA_UUID}"
    "&web_platform=browser"
    f"&web_tab_id={WEB_TAB_ID}"
)

HEADERS = {
    "Origin": "https://www.doubao.com",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cookie": COOKIE,
}


# ============== protobuf 最小编码器 ==============
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
    tag = (field_num << 3) | 2  # wire type 2 = length-delimited
    return bytes([tag]) + _varint(len(value_bytes)) + value_bytes

def build_message(api_key, namespace, command, payload_json, task_id=None):
    """组装一条 VoiceGenie 协议消息(字节)"""
    msg = b""
    msg += _field(2, api_key.encode())        # api_app_key
    msg += _field(3, namespace.encode())      # namespace
    msg += _field(5, command.encode())        # command
    msg += _field(6, payload_json.encode())   # payload (JSON string)
    if task_id:
        msg += _field(8, task_id.encode())    # task_id
    return msg

# protobuf 字段解析(用于读服务端返回的二进制帧)
def parse_fields(data):
    fields = []
    i = 0
    while i < len(data):
        tag = data[i]; i += 1
        field_num = tag >> 3
        wire = tag & 7
        if wire == 2:  # length-delimited
            length = 0; shift = 0
            while i < len(data):
                b = data[i]; i += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80): break
                shift += 7
            fields.append((field_num, data[i:i+length]))
            i += length
        elif wire == 0:  # varint
            while i < len(data):
                if not (data[i] & 0x80): i += 1; break
                i += 1
        else:
            break
    return fields


def make_payload(command):
    """构造 StartSession / StartTTS 的 payload JSON(基于抓包)"""
    common = {
        "business": 1,
        "conversation_id": CONVERSATION_ID,
        "chat": {
            "bot_id": "",
            "conversation_id": CONVERSATION_ID,
            "question_id": QUESTION_ID,
            "message_id": MESSAGE_ID,
            "uid": UID,
            "new_conversation": False,
            "chat_next": "1",
            "enable_toast_reading": "true",
            "extra": {
                "chat_next": "1",
                "reply_unique_key": REPLY_UNIQUE_KEY,
                "query_local_message_id": str(uuid.uuid1()),
            },
            "reply_unique_key": REPLY_UNIQUE_KEY,
            "section_id": SECTION_ID,
            "local_message_id": str(uuid.uuid1()),
            "query_local_message_id": str(uuid.uuid1()),
        },
        "request_type": 4,
        "enable_text_reading": True,
        "interrupt_type": 0,
        "query_mode": 2,
        "tts": {
            "speaker": SPEAKER,
            "audio_config": {"bit_rate": 32000, "format": "ogg_opus", "sample_rate": 24000},
            "extra": {"chat_next": "1", "post_process": {"pitch": 0, "speech_rate": 1}},
        },
        "extra": {
            "enable_toast_reading": "true", "chat_next": "1", "uid": UID,
            "section_id": SECTION_ID, "reply_unique_key": REPLY_UNIQUE_KEY,
        },
    }
    return json.dumps(common, ensure_ascii=False)


async def main():
    task_id = str(uuid.uuid4())
    print(f"[i] task_id = {task_id}")
    print(f"[i] 朗读 message_id = {MESSAGE_ID}")
    print(f"[i] 音色 = {SPEAKER}")

    audio_chunks = []
    first_frame_logged = False
    IDLE_TIMEOUT = 15  # 连续 15 秒没收到任何数据就认为朗读结束
    got_audio = False  # 是否已收到至少一帧音频

    def save_audio():
        """把已收到的音频帧落盘"""
        if audio_chunks:
            full = b"".join(audio_chunks)
            with open(OUTPUT_FILE, "wb") as f:
                f.write(full)
            print(f"\n[💾] 已保存: {OUTPUT_FILE}  ({len(full)} bytes = {round(len(full)/1024,1)} KB)")
            return True
        return False

    async with websockets.connect(WS_URL, additional_headers=HEADERS) as ws:
        print("[✓] WebSocket 已连接")

        # 1) StartTask
        await ws.send(build_message(API_APP_KEY, "VoiceGenie", "StartTask", "{}"))
        # 2) StartSession
        await ws.send(build_message(API_APP_KEY, "VoiceGenie", "StartSession",
                                    make_payload("StartSession"), task_id))
        # 3) StartTTS(真正发起合成)
        await ws.send(build_message(API_APP_KEY, "VoiceGenie", "StartTTS",
                                    make_payload("StartTTS"), task_id))
        print("[→] 已发送 StartTask / StartSession / StartTTS,开始接收音频...\n")

        finished = False
        while not finished:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                print(f"\n[!] {IDLE_TIMEOUT} 秒无新数据,判定朗读结束")
                break
            except websockets.ConnectionClosed:
                print("\n[!] 连接关闭")
                break

            # 文本帧 = 控制消息
            if isinstance(msg, str):
                print(f"[控制] {msg[:160]}")
                if got_audio and ("Finish" in msg or "End" in msg):
                    finished = True
                continue

            # 二进制帧:解析 protobuf
            fields = parse_fields(msg)
            if not first_frame_logged:
                print("[调试] 首个二进制帧的字段:")
                for fn, v in fields:
                    preview = v.decode('utf-8', 'replace') if len(v) < 200 else f"<{len(v)} bytes>"
                    print(f"       field {fn}: {preview}")
                first_frame_logged = True

            # 收集所有 field4(状态/command)
            statuses = []
            for fn, v in fields:
                if fn == 4:
                    statuses.append(v.decode('utf-8', 'replace'))

            # 音频数据:field 8 整段都是 ogg 流数据
            for fn, v in fields:
                if fn == 8 and len(v) > 0:
                    audio_chunks.append(v)
                    got_audio = True
                    total = sum(len(c) for c in audio_chunks)
                    if total < 2048 or total % 50000 < len(v):  # 只在关键节点打印,减少刷屏
                        print(f"  [音频] +{len(v)}B (累计 {total} = {round(total/1024,1)} KB)")
                    break

            # 结束判定:只有在已经收到音频后,才认 ChatEnded/Finish 信号为结束
            if got_audio:
                for st in statuses:
                    if "Finish" in st or "Ended" in st or "Complete" in st:
                        print(f"\n[✓] 收到结束信号: {st}")
                        finished = True
                        break
            else:
                # 还没收到音频就来了状态包,只打印不退出
                for st in statuses:
                    if st != "TaskStarted":
                        print(f"  [状态] {st} (尚未收到音频,继续等待...)")

        save_audio()

    if audio_chunks:
        print(f"\n[✓✓] 完成!共 {len(audio_chunks)} 帧音频")
        print(f"    播放:直接用播放器打开 {OUTPUT_FILE}")
        print(f"    转 mp3:ffmpeg -i {OUTPUT_FILE} doubao_audio.mp3")
    else:
        print("\n[✗] 没收到音频帧。")
        print("    最可能原因:这条 message_id 刚刚被朗读过,服务端去重了。")
        print("    解决:① 换一条豆包回复(新的 message_id)再试;② 等 1~2 分钟再跑。")


if __name__ == "__main__":
    asyncio.run(main())
