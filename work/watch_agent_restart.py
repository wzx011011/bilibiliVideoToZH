"""naval 审查阶段结束的瞬间重启 PC 代理,让新审计包装代码生效。"""
import json, time, subprocess, urllib.request
SERVER = "http://192.168.100.78:8766"
# 走系统代理(沙盒内 LAN 直连被拒):代理在容器重启窗口会回 502,
# 由无限重试兜底
OPENER = urllib.request.build_opener()
def get_tasks():
    while True:
        try:
            with OPENER.open(SERVER+"/api/tasks", timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"查询失败(20s 后重试): {e}", flush=True); time.sleep(20)
while True:
    tasks = get_tasks()
    naval = next((t for t in tasks if t["slug"]=="naval-podcast"), None)
    if naval is None:
        print("naval 任务不存在", flush=True); break
    au = next((s for s in naval["stages"] if s["key"]=="audit_translation"), None)
    print(f"naval={naval['status']} audit={au['status'] if au else '?'}", flush=True)
    if naval["status"] != "running" or (au and au["status"] != "running"):
        print("naval 审查阶段已结束,重启代理加载新代码", flush=True)
        subprocess.run(["taskkill","/IM","python.exe","/F"], capture_output=True)
        subprocess.run(["taskkill","/IM","Python311.exe","/F"], capture_output=True)
        break
    time.sleep(120)
print("watcher 退出", flush=True)
