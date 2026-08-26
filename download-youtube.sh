#!/usr/bin/env bash
# AI 大佬 YouTube 采访批量下载（1080p，可重试 / 断点续传）
# 用法: bash download-youtube.sh
# 中断后重新运行同一命令即可，已下完的会跳过。

set -u
cd "$(dirname "$0")"

PY="work/.venv-ocr/Scripts/python.exe"
YT="$PY -m yt_dlp"
FFMPEG_DIR="work/video-tools"
FFMPEG="$(pwd)/work/video-tools/ffmpeg.exe"

# 1080p 优先：取高度≤1080 的最佳 mp4 视频 + 最佳音频，合并成 mp4
FORMAT="bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/best"
# 输出模板: youtube/<人物>/<视频标题> [<id>].mp4
OUT="youtube/%(uploader|channel)s — %(title).150B [%(id)s].%(ext)s"

# 人物目录 + 视频 ID（已验证可访问、标题/时长已确认）
# 用 bash 关联数组保证顺序清晰
TARGETS=(
  # Musk
  "elon-musk|JN3KPFbWCy8"   # Lex #400 War, AI, Aliens... 2:16
  "elon-musk|DxREm3s1scA"   # Lex #252 SpaceX, Mars, AI... 2:31
  # Fei-Fei Li
  "fei-fei-li|Ctjiatnd6Xk"  # Godmother of AI on jobs, robots 1:19
  "fei-fei-li|z1g1kkA1M-8"  # Asking Audacious Questions 1:10
  # Sam Altman
  "sam-altman|hmtuvNfytjM"  # Shows Me GPT 5 1:05
  "sam-altman|aYn8VKW6vXA"  # Theo Von #599 1:33
  # Dario Amodei (Anthropic)
  "dario-amodei|ugvHCXCOmm4"  # Lex #452 Claude, AGI 5:15
  "dario-amodei|n1E9IZfvGMA"  # end of the exponential 2:22
  # Demis Hassabis (DeepMind)
  "demis-hassabis|Gfr50f6ZBvo"  # Lex #299 Superintelligence 2:10
  "demis-hassabis|-HzgcbRXUK8"  # Lex #475 Simulating Reality 2:28
  # Yann LeCun (Meta)
  "yann-lecun|5t1vTLU7s40"     # Lex #416 Meta AI, Open Source 2:47
  # Geoffrey Hinton
  "geoffrey-hinton|UnELdZdyNaE" # LLMs in Medicine 0:36
)

URL_BASE="https://www.youtube.com/watch?v="
TOTAL=${#TARGETS[@]}
OK=0; FAIL=0; SKIP=0

echo "================================================"
echo "  AI 大佬 YouTube 采访下载  共 ${TOTAL} 个"
echo "  画质: 1080p (height<=1080)  格式: mp4"
echo "  目录: youtube/<人物>/"
echo "  代理: ${HTTP_PROXY:-未设置}"
echo "================================================"
echo ""

for entry in "${TARGETS[@]}"; do
  person="${entry%%|*}"
  vid="${entry##*|}"
  url="${URL_BASE}${vid}"
  dir="youtube/${person}"
  mkdir -p "$dir"

  # 取该视频 ID 对应的已存在成品文件
  # 必须精确匹配 "[<vid>].mp4" 结尾，排除 ".f<数字>.mp4" 中间分片
  existing=$(find "$dir" -maxdepth 1 -name "*[${vid}].mp4" ! -name "*.f*.mp4" 2>/dev/null | head -1 || true)
  if [[ -n "$existing" ]]; then
    # 简单完整性检查：文件 > 5MB 视为已完成
    size=$(stat -c%s "$existing" 2>/dev/null || echo 0)
    if (( size > 5242880 )); then
      echo "[$((OK+FAIL+SKIP+1))/${TOTAL}] SKIP  ${person}/${vid}  (已存在 $((size/1048576))MB)"
      SKIP=$((SKIP+1))
      continue
    fi
  fi

  echo "----------------------------------------------------------------"
  echo "[$((OK+FAIL+SKIP+1))/${TOTAL}] 下载 ${person}/${vid}"
  echo "  → ${url}"

  # 用自定义输出前缀，便于后续 fallback 合并时定位分片文件
  PREFIX="${dir}/%(title).150B [%(id)s]"

  # 先尝试官方 --no-part 模式（直接写最终文件名，绕过 .part rename 被杀软锁住的问题）
  # --restrict-filenames: 避免中文标点(全角：等)在 Windows 上导致 rename 失败
  if $YT -f "$FORMAT" \
        -o "${PREFIX}.%(ext)s" \
        --merge-output-format mp4 \
        --restrict-filenames \
        --ffmpeg-location "$FFMPEG_DIR" \
        --newline \
        --retries 10 \
        --fragment-retries 10 \
        --socket-timeout 30 \
        --no-part \
        --no-mtime \
        "$url"; then
    echo "  ✓ 完成: ${vid}"
    OK=$((OK+1))
    continue
  fi

  # ---- Fallback: yt-dlp 合并失败时手动救回分片 ----
  # 情况1: 视频分片留在 .mp4.part（yt-dlp rename 失败）
  # 情况2: .f###.mp4 / .f###.m4a 已存在但没合并
  # 策略: rename 所有 .part → 正式名，再用 ffmpeg -c copy 合并最大的视频+音频流
  echo "  ⚠ yt-dlp 流程失败，尝试 fallback 手动合并..."
  # rename 所有 .part 残留
  shopt -s nullglob
  for p in "$dir"/*["$vid"].*.part; do
    mv -f "$p" "${p%.part}" 2>/dev/null && echo "    rename: $(basename "$p") -> $(basename "${p%.part}")"
  done
  # 找该视频的视频流和音频流分片（模式: *[<vid>].f<数字>.mp4）
  vfrag=$(ls "$dir"/*"$vid"*.f*.mp4 2>/dev/null | grep -F "[${vid}].f" | head -1)
  afrag=$(ls "$dir"/*"$vid"*.f*.m4a 2>/dev/null | grep -F "[${vid}].f" | head -1)
  if [[ -n "$vfrag" && -n "$afrag" ]]; then
    finalmp4="${vfrag%.f*.mp4}.mp4"
    if "$FFMPEG" -i "$vfrag" -i "$afrag" -c copy -map 0:v:0 -map 1:a:0 "$finalmp4" -y >/dev/null 2>&1; then
      # 合并成功，删掉中间分片
      rm -f "$vfrag" "$afrag"
      echo "  ✓ fallback 合并成功: ${vid} -> $(basename "$finalmp4")"
      OK=$((OK+1))
    else
      echo "  ✗ fallback 合并也失败: ${vid}"
      FAIL=$((FAIL+1))
    fi
  else
    echo "  ✗ 找不到可合并的分片，跳过: ${vid}"
    FAIL=$((FAIL+1))
  fi
  shopt -u nullglob
done

echo ""
echo "================================================"
echo "  完成。成功 ${OK}  跳过(已存在) ${SKIP}  失败 ${FAIL}  / 共 ${TOTAL}"
echo "================================================"
[[ -d youtube ]] && echo "" && echo "各目录大小:" && du -sh youtube/*/ 2>/dev/null
