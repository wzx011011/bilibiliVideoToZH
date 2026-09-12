"""tibo-interview-pod 达到终态后,自动恢复其余全部任务。

tibo 独占队列跑完播客链路;结束后按各自状态恢复:
  canceled → resume(翻译/审查断点保留);dario 用 resume 从审查检查点继续。
"""
import json, time, urllib.request
SERVER = "http://192.168.100.78:8766"
OPENER = urllib.request.build_opener()
RESUME = ['naval-podcast','sam-theo-von','dianne-penn-anthropic','fei-fei-godmother',
          'lex-ai-2026','jensen-huang-nvidia','yann-lecun-ai','ian-silber-openai',
          'fei-fei-world-models','dario-anthropic-452']

def get_tasks():
    while True:
        try:
            with OPENER.open(SERVER+"/api/tasks", timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"查询失败(20s 后重试): {e}", flush=True); time.sleep(20)

def action(tid, act):
    while True:
        try:
            req = urllib.request.Request(SERVER+f"/api/tasks/{tid}/action",
                data=json.dumps({"action": act}).encode(),
                headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"  action {act} 失败(15s 后重试): {e}", flush=True); time.sleep(15)

while True:
    tasks = get_tasks()
    tibo = next((t for t in tasks if t["slug"] == "tibo-interview-pod"), None)
    if tibo and tibo["status"] in ("done", "failed", "canceled"):
        print(f"tibo 终态: {tibo['status']},恢复其余任务", flush=True)
        break
    time.sleep(120)
    cur = next((s['label'] for s in tibo['stages'] if s['status']=='running'), '-') if tibo else '?'
    print(f"  tibo={tibo['status'] if tibo else '?'} {tibo['progress'] if tibo else ''} {cur}", flush=True)

by_slug = {t["slug"]: t for t in get_tasks()}
for slug in RESUME:
    t = by_slug.get(slug)
    if not t:
        continue
    if t["status"] == "canceled":
        print(f"  {slug}: resume -> {action(t['id'], 'resume')}", flush=True)
    else:
        print(f"  {slug}: 状态 {t['status']},跳过", flush=True)
print("watcher: 恢复完成,退出", flush=True)
