"""等第11集交付包生成完成后，停掉批量任务和 GPT-SoVITS 服务。

轮询 episode-11-delivery 是否出现，出现后：
  1. 停掉批量任务主进程（batch_episodes.py）
  2. 停掉 GPT-SoVITS 服务
  3. 报告完成
"""
import subprocess
import time
from pathlib import Path

BASE = Path("D:/work/wzx/outputs/harvard-positive-psychology")
DELIVERY = BASE / "episode-11-delivery" / "video"
LOG = BASE / "wait-ep11.log"
POLL = 60


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def find_batch_proc():
    """找 batch_episodes.py 的 python 进程 PID。"""
    r = subprocess.run(
        ["powershell", "-Command",
         "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*batch_episodes*'} | "
         "Select-Object ProcessId,CommandLine | Format-Table -HideTableHeaders"],
        capture_output=True, text=True)
    pids = []
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if line and line[0].isdigit():
            pids.append(int(line.split()[0]))
    return pids


def stop_pid(pid):
    subprocess.run(["powershell", "-Command",
                    f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
                   capture_output=True)


def main():
    log("监听第11集交付包...")
    while True:
        if DELIVERY.is_dir():
            log(f"✓ 第11集交付包已生成: {DELIVERY}")
            break
        time.sleep(POLL)

    time.sleep(5)  # 等批量脚本写完日志

    # 停批量任务
    pids = find_batch_proc()
    for pid in pids:
        stop_pid(pid)
        log(f"  停掉批量任务进程 {pid}")
    if not pids:
        log("  未找到批量任务进程（可能已退出）")

    # 停 GPT-SoVITS（找监听 9880 的进程）
    r = subprocess.run(
        ["powershell", "-Command",
         "Get-NetTCPConnection -LocalPort 9880 -State Listen -ErrorAction SilentlyContinue | "
         "Select-Object -ExpandProperty OwningProcess"],
        capture_output=True, text=True)
    gsv_pid = r.stdout.strip().splitlines()
    gsv_pid = [p.strip() for p in gsv_pid if p.strip().isdigit()]
    for pid in gsv_pid:
        stop_pid(int(pid))
        log(f"  停掉 GPT-SoVITS 服务 {pid}")
    if not gsv_pid:
        log("  未找到 GPT-SoVITS 服务")

    log("全部停止完成。第12-23集未生成，下次需重新启动 batch_episodes.py 续跑。")


if __name__ == "__main__":
    main()
