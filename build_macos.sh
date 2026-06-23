#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

python3 -m pip install -r requirements.txt pyinstaller

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "NaichaMouse" \
  --icon "app_icon.ico" \
  --add-data "IMG_5791:IMG_5791" \
  --add-data "accessories:accessories" \
  --add-data "naicha_mouse_state_map.json:." \
  --add-data "naicha_mouse_dialogues.json:." \
  --add-data "naicha_mouse_gacha_pool.json:." \
  --add-data "naicha_mouse_accessories.json:." \
  main.py

mkdir -p release
cp -R "dist/NaichaMouse.app" "release/NaichaMouse.app"

echo ""
echo "打包完成：release/NaichaMouse.app"
