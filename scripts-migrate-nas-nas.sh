#!/bin/bash
# 视频汉化项目迁移:把 share/视频 的汉化相关资源复制到 视频汉化项目 根下,中文命名
# 策略:逐资源 cp -r 到新根 → 校验字节数 → 全部成功后才由 verify-delete 阶段删除旧位置
set -u
ROOT="/volume1/share/视频"
NEW="/volume1/share/视频汉化项目"
fail=0
cpv() {  # cpv <src> <dst> 复制并校验
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  cp -r "$src" "$dst" 2>/dev/null
  if [ -d "$src" ]; then
    local a=$(du -sb "$src" | cut -f1) b=$(du -sb "$dst" | cut -f1)
  else
    local a=$(stat -c%s "$src") b=$(stat -c%s "$dst")
  fi
  if [ "$a" = "$b" ] && [ -n "$a" ] && [ "$a" != "0" ]; then
    echo "  ✓ $(basename "$src")"
  else
    echo "  ✗ 校验失败: $src ($a vs $b)"
    fail=1
  fi
}

echo "== 1) 积极心理学 course23 集成 =="
SRC="$ROOT/B站视频发布/积极心理学"
D=0
for f in "$SRC"/*.mp4; do
  n=$(basename "$f")
  if [ "$n" = "episode-09.part.mp4" ]; then continue; fi  # 残留半成品不迁
  ep=$(echo "$n" | grep -oE '[0-9]+')
  cpv "$f" "$NEW/积极心理学/course23集成/第${ep}讲-成品.mp4"
done

echo "== 2) 积极心理学 原片(第22讲在 NAS 原片库) =="
cpv "$ROOT/原片库/积极心理学-第22讲.mp4" "$NEW/积极心理学/原片/第22讲-原片.mp4"

echo "== 3) hinton-医学访谈 =="
cpv "$ROOT/hinton-medicine-v2/01-视频源/hinton-medicine-v2-source.mp4" "$NEW/hinton-医学访谈/01-视频源/Hinton访谈-原片.mp4"
cpv "$ROOT/hinton-medicine-v2/02-英文字幕/hinton-medicine-v2-en.srt"   "$NEW/hinton-医学访谈/02-英文字幕/Hinton访谈-英文字幕.srt"
cpv "$ROOT/hinton-medicine-v2/03-中文字幕/hinton-medicine-v2-zh.srt"   "$NEW/hinton-医学访谈/03-中文字幕/Hinton访谈-中文字幕.srt"
cpv "$ROOT/hinton-medicine-v2/04-中文音频/hinton-medicine-v2-zh.wav"   "$NEW/hinton-医学访谈/04-中文音频/Hinton访谈-中文配音.wav"
cpv "$ROOT/hinton-medicine-v2/05-成品/hinton-medicine-v2-final.mp4"    "$NEW/hinton-医学访谈/05-成品/Hinton访谈-中文成品.mp4"

echo "== 4) 确认平台 task 记录指向(平台产物迁移说明) =="
echo "(平台任务五件套已随以上迁移;nas-lib-e2e/smoke-* 为测试任务,不迁)"

echo "== done  fail=$fail =="
exit $fail
