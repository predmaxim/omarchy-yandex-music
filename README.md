# omarchy-yandex-music

Яндекс Музыка без официального клиента: «Моя волна» с выбором настроения, волна по любому треку, «Мне нравится», поиск. Управление — медиаклавишами и из бара Omarchy.

## Установка

```bash
git clone https://github.com/predmaxim/omarchy-yandex-music ~/Projects/omarchy-yandex-music
~/Projects/omarchy-yandex-music/install.sh
```

`install.sh` ставит пакеты через `yay` (`mpv`, `mpv-mpris`, `qrencode`, `python-yandex-music-api-git`; если они уже есть — `sudo` не нужен), линкует `systemd/ymd.service` в `~/.config/systemd/user/` и плагин `plugin/` в `~/.config/omarchy/plugins/predmaxim.yandex-music`, включает и перезапускает `ymd`. Значок в центральной группе индикаторов копирует хук `patch_indicators` из `omarchy-dotfiles` (после него — `omarchy restart shell`).

## Вход

Откройте модалку (клик по значку или `omarchy-shell predmaxim.yandex-music toggle`): без токена там код устройства и QR со ссылкой. Подтвердите на телефоне — `ymd` сам опросит токен. Токен лежит в `~/.config/predmaxim.yandex-music/token` (права 0600, не в git). Протух — модалка снова предложит вход.

## Управление

| Что | Как |
|---|---|
| Открыть модалку | левый клик по значку, `omarchy-shell predmaxim.yandex-music toggle` |
| Пауза / плей | правый клик по значку, медиаклавиши, Space при пустом поле поиска |
| Следующий / предыдущий | медиаклавиши (`playerctl -p mpv next` / `previous`) — и в волне, и в «Мне нравится» |
| Лайк / дизлайк | Ctrl+L / Ctrl+D, кнопки в шапке |
| Включить трек | Enter на строке очереди или результата поиска |
| Волна по треку | → на строке, затем кнопка 󰐑 |
| Строки / шапка | ↑ / ↓ (↑ с первой строки — в шапку) |
| Вкладка «Моя волна» | обложка и плеер вместо списка; ← / → по кнопкам, ↑ — к «Волна / Мне нравится / настроение», Enter нажать; ▶ запускает волну, смена настроения во время волны перезапускает её |
| Очистить поле, закрыть | Esc |

Значок горит, пока играет или стоит на паузе; подсказка — «Исполнитель — трек».

## Устройство

```
плагин (QML) ── сокет $XDG_RUNTIME_DIR/ymd.sock ── ymd (Python) ── mpv --idle (IPC-сокет)
                                                        │               └ mpv-mpris → медиаклавиши, playerctl
                                                        └ Яндекс Музыка API
```

- `ymd` — пользовательская служба: держит очередь, получает ссылки на потоки, шлёт обратную связь волне (`radioStarted`, `trackStarted`, `skip`, `trackFinished`, лайки) и рассылает состояние подписчикам сокета (по JSON-объекту на строку).
- `mpv` — дочерний процесс `ymd`, играет и держит текущий и следующий трек; упал — `ymd` его перезапускает. `mpv-mpris` даёт MPRIS, поэтому медиаклавиши идут прямо в плеер.
- Плагин `predmaxim.yandex-music` (`plugin/`): значок и модалка по центру; разбор состояния — `Model.js`.

## Проверка

```bash
timeout 60 python -m pytest -q   # ymd: очередь, волна, сокет, mpv (заглушки API и mpv)
node plugin/test.js              # плагин: разбор состояния, переводы
journalctl --user -u ymd         # журнал службы
playerctl -p mpv status          # плеер виден по MPRIS
```
