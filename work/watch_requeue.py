"""等 tibo-interview-pod 被代理领取后,把其余失败任务按正确路径重新入队。

- 审查超时类(dario-anthropic-452):retry → 审查从检查点续跑
- 审查串位类(sam/fei-fei-godmother/demis/yann):retranslate → 作废译文重译重审
- 中途取消类(fei-fei-world-models):resume → 从断点继续
其余已取消任务(elon-war-ai / tibo-interview-nar / elon-mars-tesla)保持不动。
"""
import json
import time
import urllib.request

SERVER = "http://192.168.100.78:8766"
# 绕过 Clash 等系统代理:LAN 直连,容器重启窗口也不再吃 502
# 走系统代理(沙盒内 LAN 直连被拒):代理在容器重启窗口会回 502,
# 由无限重试兜底
OPENER = urllib.request.build_opener()


def get_tasks():
    while True:  # 永不因网络抖动崩溃:失败就等 20s 重试
        try:
            with OPENER.open(SERVER + "/api/tasks", timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"  get_tasks 失败(20s 后重试): {e}", flush=True)
            time.sleep(20)


def action(task_id, act):
    body = json.dumps({"action": act}).encode()
    while True:
        try:
            req = urllib.request.Request(
                SERVER + f"/api/tasks/{task_id}/action", data=body,
                headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"  action {act} 失败(15s 后重试): {e}", flush=True)
            time.sleep(15)


def main():
    print("watcher: 等待 tibo-interview-pod 被领取(translate 进入 running)...")
    while True:
        tasks = get_tasks()
        tibo = next((t for t in tasks if t["slug"] == "tibo-interview-pod"), None)
        if tibo and tibo["status"] == "running":
            tr = next(s for s in tibo["stages"] if s["key"] == "translate")
            if tr["status"] == "running":
                print("tibo 已领取并开始翻译,入队其余任务", flush=True)
                break
        time.sleep(60)
        print(f"  等待中... tibo={tibo['status'] if tibo else '?'}", flush=True)

    by_slug = {t["slug"]: t for t in get_tasks()}
    plan = [
        ("dario-anthropic-452", "retry"),
        ("sam-theo-von", "retranslate"),
        ("fei-fei-godmother", "retranslate"),
        ("demis-simulation", "retranslate"),
        ("yann-lecun-ai", "retranslate"),
        ("naval-podcast", "retranslate"),
        ("ian-silber-openai", "retranslate"),
        ("fei-fei-world-models", "resume"),
    ]
    for slug, act in plan:
        t = by_slug.get(slug)
        if not t:
            print(f"  {slug}: 不存在,跳过", flush=True)
            continue
        print(f"  {slug}: {act} -> {action(t['id'], act)}", flush=True)
    print("watcher: 全部入队完成,退出", flush=True)


if __name__ == "__main__":
    main()
