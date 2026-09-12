"""ep-23 达到终态后,自动恢复其余任务(canceled → resume)。"""
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
            print(f"  action 失败(15s 后重试): {e}", flush=True); time.sleep(15)
while True:
    tasks = get_tasks()
    t = next((x for x in tasks if x["slug"] == "ep-23"), None)
    if t and t["status"] in ("done", "failed", "canceled"):
        print(f"ep-23 终态: {t['status']},恢复其余任务", flush=True)
        break
    time.sleep(180)
by = {x["slug"]: x for x in get_tasks()}
for slug in RESUME:
    t = by.get(slug)
    if t and t["status"] == "canceled":
        print(f"  {slug}: resume -> {action(t['id'],'resume')}", flush=True)
print("watcher 完成", flush=True)
