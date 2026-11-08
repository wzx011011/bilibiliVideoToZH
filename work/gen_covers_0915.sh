#!/bin/bash
# 大明演义 ep09-15 封面原图批量生成(ICU gpt-image-2,系列羊皮纸风格)
set -u
GEN="C:/Users/67376/.zcode/skills/icu-image/scripts/generate.py"
OUT="work/studio/covers"
TAIL="Palette: vermilion red, imperial yellow, indigo blue, cream parchment. Clean bold shapes, subtle paper grain, dramatic cinematic composition with calm empty parchment space in the lower left for a title. Absolutely no text, no letters, no characters, no seals, no watermark."
STYLE="Horizontal cover illustration, flat vector picture-book style on warm aged parchment paper: late Ming dynasty China."

declare -A P
P[ming09-raw]="A carefree young Ming emperor in ornate casual armor riding a spirited horse with a leopard beside him, self-confident grin, leading a charge on a vast battlefield with red war banners (plain cloth, no writing), fallen helmets in foreground, autumn grassland."
P[ming10-raw]="A solemn teenage Ming emperor newly seated on a grand golden throne in a vast palace hall, rows of prostrating court officials in red and blue robes below the steps, tension in the air, tall red pillars, morning light through the doorway."
P[ming11-raw]="Ming soldiers with long spears and matchlock guns in famous mandarin-duck formation defending a coastal village against Japanese pirates in dark clothing, smoke and flames over thatched roofs, generals in armor commanding on a dune, East China sea horizon."
P[ming12-raw]="A bustling Ming dynasty seaport with merchant junks being loaded with silk and porcelain crates, foreign merchants counting silver ingots, city gate nearby; in the distance on hills, Mongolian horsemen herding trade horses toward a border market, warm afternoon light."
P[ming13-raw]="A stern middle-aged Ming grand secretary in crimson court robes standing tall over a huge desk piled with memorials and ledgers, holding a red brush, a large wall map of the empire behind him, candlelight, atmosphere of tireless reform."
P[ming14-raw]="A distant Ming emperor sulking behind a gilded desk piled high with unopened memorials in an empty silent palace hall, while below the steps rows of officials in official robes kneel holding petitions up, vast empty space between them, cold morning light."
P[ming15-raw]="A Ming expeditionary army in blue armor crossing a wide river on boats and pontoon bridges toward Korean peninsula, red war banners (plain cloth, no writing), warships with cannon smoke on the water, distant walled city of Pyongyang under bombardment at dusk."

for name in ming09-raw ming10-raw ming11-raw ming12-raw ming13-raw ming14-raw ming15-raw; do
  if [ -s "$OUT/$name.png" ]; then echo "[skip] $name"; continue; fi
  echo "=== $name ==="
  python "$GEN" --prompt "$STYLE ${P[$name]} $TAIL" --out "$OUT/$name.png" || echo "[FAIL] $name"
done
echo ALL-DONE
