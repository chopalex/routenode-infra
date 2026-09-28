# vk-turn-proxy

Отдельный сервис входа через **сеть звонков VK** (VK Calls). Это не опциональная UDP-обёртка поверх AmneziaWG.

## Как связано с Amnezia

На сервере прокси работает в `network_mode: host` и в конфиге подключается к AWG как к localhost:

```
-listen  0.0.0.0:56000
-connect 127.0.0.1:47054   ← опубликованный порт amnezia-awg2 на хосте
```

Клиентский путь: устройство → инфраструктура VK Calls → этот хост `:56000` → `127.0.0.1:47054` (AmneziaWG).

Прямой AmneziaWG на `:47054` остаётся отдельным каналом; vk-turn — отдельный вход, стыкующийся с тем же AWG локально.

## Подъём

`Dockerfile` скачивает бинарь с GitHub Releases при `docker compose build` (бинарь в git не нужен).

```bash
cd /opt/vk-turn-proxy   # или из репо: vk-turn-proxy/
docker compose up -d --build
ss -ulnp | grep 56000
```

Версию бинаря можно переопределить:

```bash
docker compose build --build-arg VK_TURN_VERSION=v1.8.3
```

UFW: разрешить `56000/udp` (`scripts/ufw-allow.sh`).
