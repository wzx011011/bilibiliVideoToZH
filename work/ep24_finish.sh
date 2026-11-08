#!/bin/bash
# ep24 收尾(2026-09-15 凌晨,ICU 日额度用尽后挂后台等重置):
# 1) 每 30 分钟重试一次 ep23 封面原图(额度恢复的第一个成功尝试直接就是产物)
# 2) ep24 broll 32 张(ICU,断点续跑)
# 3) ep24 封面原图+合成;ep23 封面合成
# 4) ep24 静态渲染(独占)
set -u
cd /e/ai/bilibiliVideoToZH
GEN="C:/Users/67376/.zcode/skills/icu-image/scripts/generate.py"
PY="work/.venv-ocr/Scripts/python.exe"

# 1) 等额度:直接拿 ep23 封面当探针
P23="Horizontal cover illustration, flat vector picture-book style on warm aged parchment paper: late Ming dynasty China, 1644. A solitary emperor figure in dark robes standing with bowed head on a small hill above the vast Forbidden City at cold rainy dawn, a single loyal old eunuch standing a few steps behind, the enormous palace sea below shrouded in mist and drifting smoke, distant rebel campfires, fallen red banners on the hillside, willow branches. Palette: vermilion red, imperial yellow, indigo blue, cream parchment. Clean bold shapes, subtle paper grain, dramatic cinematic composition with calm empty parchment space in the lower left for a title. Absolutely no text, no letters, no characters, no seals, no watermark."
ok=0
for i in $(seq 1 96); do
  echo "=== try ep23 cover ($i) $(date +%T) ==="
  if python "$GEN" --prompt "$P23" --out work/studio/covers/ming23-raw.png; then
    ok=1; break
  fi
  sleep 1800
done
[ "$ok" = 1 ] || { echo NO-QUOTA-AFTER-12H; exit 1; }

# 2) ep24 broll
"$PY" src/broll/generate.py --content src/mzx_story/ming-24-nanming.json --backend icu > work/broll-24.log 2>&1
echo "broll24 exit=$?"
tail -2 work/broll-24.log

# 3) ep24 封面 + ep23 封面合成
P24="Horizontal cover illustration, flat vector picture-book style on warm aged parchment paper: late Ming dynasty China, 1650s. A lone general in armor on a southern shore holding a tattered Ming war banner, loyalist junks with red sails departing toward distant islands over a golden sunset sea, fallen helmets and broken spears on the beach, dark storm clouds parting with last light. Palette: vermilion red, imperial yellow, indigo blue, cream parchment. Clean bold shapes, subtle paper grain, dramatic cinematic composition with calm empty parchment space in the lower left for a title. Absolutely no text, no letters, no characters, no seals, no watermark."
python "$GEN" --prompt "$P24" --out work/studio/covers/ming24-raw.png || exit 1
"$PY" src/mzx_story/make_cover.py --compose --raw work/studio/covers/ming23-raw.png --out videos/cover-ming23.jpg --kicker "明朝故事 · 第 23 集" --title "煤山" --subtitle "—— 1644:大明的最后一天" || exit 1
"$PY" src/mzx_story/make_cover.py --compose --raw work/studio/covers/ming24-raw.png --out videos/cover-ming24.jpg --kicker "明朝故事 · 第 24 集" --title "南明终章" --subtitle "—— 最后的抗争与大明落幕" || exit 1

# 4) ep24 渲染(独占)
"$PY" src/mzx_story/vector_render.py --render --content src/mzx_story/ming-24-nanming.json --out D:/mzx-ming24 > work/render-24.log 2>&1
echo "render24 exit=$?"
grep -E "verified|expected_duration" work/render-24.log | tail -2
echo EP24-CHAIN-DONE
