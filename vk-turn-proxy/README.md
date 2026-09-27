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

```bash
# бинарь/Dockerfile — из вашего образа vk-turn-proxy (build: . в compose)
cd /opt/vk-turn-proxy
docker compose up -d
ss -ulnp | grep 56000
```

UFW: разрешить `56000/udp`.
