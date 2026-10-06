#!/bin/bash
# Установка omarchy-yandex-music: пакеты, служба ymd, плагин панели.
set -euo pipefail
cd "$(dirname "$0")"

# python-hatchling первым: в PKGBUILD python-yandex-music-api-git его нет в makedepends
for pkg in mpv mpv-mpris qrencode python-hatchling python-yandex-music-api-git; do
  if ! pacman -Q "$pkg" &>/dev/null; then
    yay -S --needed --noconfirm "$pkg"
  fi
done

mkdir -p ~/.config/systemd/user ~/.config/omarchy/plugins
ln -sfn "$PWD/systemd/ymd.service" ~/.config/systemd/user/ymd.service
# Значок в группе индикаторов копирует хук patch_indicators (omarchy-dotfiles)
ln -sfn "$PWD/plugin" ~/.config/omarchy/plugins/predmaxim.yandex-music

systemctl --user daemon-reload
systemctl --user enable --now ymd.service
systemctl --user restart ymd.service
