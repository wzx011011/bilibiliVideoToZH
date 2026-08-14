#!/usr/bin/env bash
# 批量重渲染 17 集字幕（每条字幕 ≤28 字，一行显示）
# 每集两步：subtitle（重生成 asr.srt，有缓存秒级）+ video（重新渲染 mp4）
# 用法: bash rerender-subtitles.sh
# 中断后重跑：已渲染好的（videos/episode-XX.mp4 时间戳新于 asr.srt）会跳过。

set -u
cd "$(dirname "$0")"

PY="work/.venv-ocr/Scripts/python.exe"
EPISODES=(02 03 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19)
TOTAL=${#EPISODES[@]}
OK=0; FAIL=0; SKIP=0
FAILED_LIST=()

echo "================================================"
echo "  字幕重渲染  共 ${TOTAL} 集（每条字幕 ≤28 字）"
echo "================================================"
echo ""

for ep in "${EPISODES[@]}"; do
  work_dir="work/ep-${ep}"
  asr_srt="${work_dir}/episode-${ep}-asr.srt"
  out_mp4="videos/episode-${ep}.mp4"

  # 跳过判断：本批次完成标记（subtitle+video 都成功后写入）
  if [[ -f "${work_dir}/.rerendered" ]]; then
    echo "[$((OK+FAIL+SKIP+1))/${TOTAL}] SKIP ep-${ep} (已渲染)"
    SKIP=$((SKIP+1))
    continue
  fi

  echo "----------------------------------------------------------------"
  echo "[$((OK+FAIL+SKIP+1))/${TOTAL}] ep-${ep}"
  t0=$(date +%s)

  # 步骤1: subtitle（重生成 asr.srt，有 .asr.json 缓存，秒级）
  echo "  [subtitle] 重生成字幕..."
  if ! "$PY" src/make_episode.py --episode "${ep#0}" --step subtitle \
        > "work/ep-${ep}-rerender.log" 2>&1; then
    echo "  ✗ subtitle 失败 (见 work/ep-${ep}-rerender.log)"
    FAIL=$((FAIL+1)); FAILED_LIST+=("$ep"); continue
  fi

  # 步骤2: video（重新渲染 mp4，2-4 分钟）
  echo "  [video] 重新渲染..."
  if ! "$PY" src/make_episode.py --episode "${ep#0}" --step video \
        >> "work/ep-${ep}-rerender.log" 2>&1; then
    echo "  ✗ video 失败 (见 work/ep-${ep}-rerender.log)"
    FAIL=$((FAIL+1)); FAILED_LIST+=("$ep"); continue
  fi

  t1=$(date +%s)
  dt=$(( t1 - t0 ))

  # 统计新字幕最长字符
  if command -v python >/dev/null 2>&1; then
    maxlen=$(python -c "
import re,sys
t=open(r'$asr_srt',encoding='utf-8').read()
mx=0
for b in re.split(r'\n\s*\n',t.strip()):
    ls=[l for l in b.splitlines() if l.strip()]
    if len(ls)>=3 and '-->' in ls[1]: mx=max(mx,len(' '.join(ls[2:])))
print(mx)" 2>/dev/null || echo "?")
  else
    maxlen="?"
  fi

  sz=$(ls -la "$out_mp4" 2>/dev/null | awk '{print int($5/1048576)}')
  echo "  ✓ ep-${ep} 完成 (${dt}s, ${sz}MB, 字幕最长${maxlen}字)"
  touch "${work_dir}/.rerendered"  # 标记本集已完成（供中断后重跑跳过）
  OK=$((OK+1))
done

echo ""
echo "================================================"
echo "  完成。成功 ${OK}  跳过 ${SKIP}  失败 ${FAIL}  / 共 ${TOTAL}"
if (( ${#FAILED_LIST[@]} > 0 )); then
  echo "  失败集: ${FAILED_LIST[*]}"
  echo "  查看各集日志: work/ep-XX-rerender.log"
fi
exit 0
echo "================================================"
