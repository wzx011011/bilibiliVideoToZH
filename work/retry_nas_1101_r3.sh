#!/bin/bash
# 第二轮:NAS 归档 1101 带图版(首轮 60 次全败),每 5 分钟重试,窗口 4 小时
V=/e/ai/bilibiliVideoToZH/kinetic_demo/ai-news-1101_video.mp4
EXPECT=cdc053b6fac0751f1a3ba63de18760af
DST="nas:/volume1/share/视频汉化项目/临时-试听/AI快讯/AI快讯-20261101.mp4"
SCP="/f/Program Files/Git/usr/bin/scp.exe"
for i in $(seq 1 24); do
  echo "[$(date '+%F %T')] attempt $i"
  if ssh -o ConnectTimeout=10 -o BatchMode=yes nas "echo alive" >/dev/null 2>&1; then
    if "$SCP" -o ConnectTimeout=10 -o BatchMode=yes "$V" "$DST" >/dev/null 2>&1; then
      GOT=$(ssh -o ConnectTimeout=10 -o BatchMode=yes nas "md5sum '/volume1/share/视频汉化项目/临时-试听/AI快讯/AI快讯-20261101.mp4'" 2>/dev/null | awk '{print $1}')
      echo "[$(date '+%F %T')] remote md5: $GOT"
      if [ "$GOT" = "$EXPECT" ]; then echo "[$(date '+%F %T')] SUCCESS md5 match"; exit 0; fi
    fi
  fi
  sleep 1200
done
echo "[$(date '+%F %T')] GAVE UP after 48 attempts"
exit 1
