# -*- coding: utf-8 -*-
"""断点续批驱动:循环补齐 job 中的缺失图,直到全部存在或超过轮次上限。

用法(务必用 start /min 独立窗口跑,避免随 ZCode 会话恢复被杀):
  python work/run_batch_detached.py work/sy_ep02_images.json
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
job = sys.argv[1]

for rnd in range(12):
    jobs = json.load(open(job, encoding="utf-8"))
    missing = [j for j in jobs if not os.path.exists(j["out"])]
    if not missing:
        print("ALL_DONE", flush=True)
        break
    # 按 preset 分组:turbo 先(热且稳),base 后
    missing.sort(key=lambda j: 0 if j.get("preset") != "qwen21" else 1)
    tmp = job + ".missing.json"
    json.dump(missing, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[driver] round {rnd}: missing {len(missing)}", flush=True)
    subprocess.run([sys.executable, os.path.join(ROOT, "work", "qwen_cast_gen.py"),
                    "--job", tmp], cwd=ROOT)
    time.sleep(15)
else:
    print("ROUNDS_EXHAUSTED", flush=True)
