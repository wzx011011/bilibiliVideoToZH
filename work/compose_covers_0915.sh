#!/bin/bash
# ep09-15 封面合成(本地标题绘制,不调 API)
set -u
PY="work/.venv-ocr/Scripts/python.exe"
compose() { # raw out kicker title subtitle
  [ -s "work/studio/covers/$1" ] || { echo "[missing] $1"; return; }
  "$PY" src/mzx_story/make_cover.py --compose --raw "work/studio/covers/$1" \
    --out "$2" --kicker "$3" --title "$4" --subtitle "$5" >/dev/null 2>&1 \
    && echo "[ok] $2" || echo "[FAIL] $2"
}
compose ming09-raw.png videos/cover-ming09.jpg "明朝故事 · 第 09 集" "正德皇帝" "—— 不想当皇帝的皇帝"
compose ming10-raw.png videos/cover-ming10.jpg "明朝故事 · 第 10 集" "大礼议" "—— 外藩少年掀翻满朝文武"
compose ming11-raw.png videos/cover-ming11.jpg "明朝故事 · 第 11 集" "严嵩与倭寇" "—— 铁肩担道义,辣手著文章"
compose ming12-raw.png videos/cover-ming12.jpg "明朝故事 · 第 12 集" "隆庆新政" "—— 闷皇帝干对的两件事"
compose ming13-raw.png videos/cover-ming13.jpg "明朝故事 · 第 13 集" "张居正" "—— 帝国最后的裱糊匠"
compose ming14-raw.png videos/cover-ming14.jpg "明朝故事 · 第 14 集" "万历亲政" "—— 皇帝跟大臣冷战十五年"
compose ming15-raw.png videos/cover-ming15.jpg "明朝故事 · 第 15 集" "万历三大征" "—— 跨过鸭绿江"
