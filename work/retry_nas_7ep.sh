#!/bin/bash
# 七期归档重试(1101~1107):NAS 宕机 6 天,每 10 分钟探活,窗口 12 小时
SCP="/f/Program Files/Git/usr/bin/scp.exe"
K=/e/ai/bilibiliVideoToZH/kinetic_demo
D="/volume1/share/视频汉化项目/临时-试听/AI快讯"
declare -A EXPECT=( ["20261101"]="cdc053b6fac0751f1a3ba63de18760af" ["20261102"]="1909c0873b6be0fc03c55e7ac137c54c" ["20261103"]="f9625d8b7437d05e103ef3e5d1b975dc" ["20261104"]="952aef2c42defb44ccab9049905e33c8" ["20261105"]="ce3e99a90483c9e5e47b9893525b180a" ["20261106"]="fd3639ee75b86a73173e7c246da8b2f7" ["20261107"]="3f41a36dbe9a42fea3d256dd1cbc70fd" )
pending="20261101 20261102 20261103 20261104 20261105 20261106 20261107"
for i in $(seq 1 72); do
  echo "[$(date '+%F %T')] attempt $i, pending: $pending"
  ssh -o ConnectTimeout=10 -o BatchMode=yes nas "echo alive" >/dev/null 2>&1 || { sleep 600; continue; }
  next=""
  for d in $pending; do
    if "$SCP" -o ConnectTimeout=10 -o BatchMode=yes "$K/ai-news-${d:2:4}_video.mp4" "nas:$D/AI快讯-$d.mp4" >/dev/null 2>&1; then
      GOT=$(ssh -o ConnectTimeout=10 -o BatchMode=yes nas "md5sum '$D/AI快讯-$d.mp4'" 2>/dev/null | awk '{print $1}')
      if [ "$GOT" = "${EXPECT[$d]}" ]; then
        echo "[$(date '+%F %T')] $d archived ok (md5 match)"
      else
        echo "[$(date '+%F %T')] $d md5 MISMATCH: $GOT"; next="$next $d"
      fi
    else
      next="$next $d"
    fi
  done
  pending="$next"
  [ -z "${pending// }" ] && { echo "[$(date '+%F %T')] ALL ARCHIVED"; exit 0; }
  sleep 600
done
echo "[$(date '+%F %T')] GAVE UP, still pending:$pending"
exit 1
