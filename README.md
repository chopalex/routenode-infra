# routenode-infra

Конфиги, твики и скрипты VPN-шлюза (AmneziaWG + Pi-hole + мониторинг + vk-turn-proxy).

Секреты в репозиторий **не входят** — только `.env.example` / `secrets.env.example`.

## Архитектура

```
Клиент (прямой AWG) ──UDP──► :47054 ──► amnezia-awg2 (awg0, 10.8.1.0/24)
                                          │
                                          ├─ DNS :53 ──DNAT──► pihole 172.29.172.10
                                          └─ трафик ──MASQUERADE──► интернет

Клиент (через VK Calls) ──► vk-turn-proxy :56000/udp
                                 │
                                 └─ connect 127.0.0.1:47054 → amnezia-awg2
                              (host network; AWG в конфиге прокси — localhost)

Мониторинг: Prometheus → Grafana / Alertmanager (Telegram)
```

**vk-turn-proxy** — отдельный сервис входа через инфраструктуру звонков VK.  
На сервере слушает `:56000`, а к AmneziaWG ходит по `-connect 127.0.0.1:47054` (`network_mode: host`).

Сеть Docker: `amnezia-dns-net` (`172.29.172.0/24`):
| Контейнер        | IP            |
|------------------|---------------|
| amnezia-awg2     | 172.29.172.2* |
| pihole           | 172.29.172.10 |
| pihole-webproxy  | (dynamic)     |

\* IP AWG после `docker network connect` может отличаться; Pi-hole/route скрипты резолвят контейнер по имени, когда возможно.

## Быстрый подъём (новый сервер)

AmneziaWG ставится **с клиента Amnezia** (в репо её нет). Остальное — одной командой после clone.

```bash
# 0) Docker
sudo apt update && sudo apt install -y docker.io docker-compose-v2 curl
sudo systemctl enable --now docker

# 1) Clone
sudo git clone https://github.com/chopalex/routenode-infra.git /opt/routenode-infra
cd /opt/routenode-infra

# 2) Секреты (обязательно поправить пароли)
sudo mkdir -p /opt/pihole /opt/monitoring/exporters /opt/monitoring/alertmanager
sudo cp pihole/.env.example /opt/pihole/.env
sudo cp monitoring/.env.example /opt/monitoring/.env
sudo cp monitoring/exporters/.env.example /opt/monitoring/exporters/.env
sudo cp monitoring/alertmanager/secrets.env.example /opt/monitoring/alertmanager/secrets.env
sudo chmod 600 /opt/pihole/.env /opt/monitoring/.env \
  /opt/monitoring/exporters/.env /opt/monitoring/alertmanager/secrets.env
sudo nano /opt/pihole/.env /opt/monitoring/.env /opt/monitoring/exporters/.env
# exporters/.env — тот же пароль Pi-hole
# secrets.env — Telegram (можно позже)

# 3) Базовый стек: Pi-hole + monitoring + vk-turn + systemd + UFW rules
sudo PUBLIC_IP=$(curl -4 -fsS https://ifconfig.me) ./scripts/deploy.sh

# 4) Amnezia — с клиента (контейнер amnezia-awg2, UDP 47054)
#    затем твики DNS/NAT:
sudo ./scripts/apply-amnezia-tweaks.sh

# 5) UFW enable (после проверки SSH!)
sudo ufw enable
```

Опции `deploy.sh`:

| Env | Значение |
|-----|----------|
| `PUBLIC_IP` | публичный IP (для DNS socat units) |
| `SKIP_UFW=1` | не трогать UFW |
| `SKIP_VK_TURN=1` | не собирать vk-turn |
| `UFW_OPEN_ADMIN=1` | открыть Pi-hole/Grafana в UFW |

### Проверки

```bash
docker ps
docker exec amnezia-awg2 iptables -t nat -L PREROUTING -n | grep 53
curl -s http://127.0.0.1:9090/-/healthy
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/api/health
ss -ulnp | grep -E '47054|56000'
```

Grafana: `http://127.0.0.1:3000`  
Pi-hole admin: `http://127.0.0.1:61864/admin/`

### Имена клиентов в Pi-hole

Local DNS / `dns.hosts`:

```
10.8.1.1 dell
10.8.1.2 husk
```

### Блоклисты (опционально)

```bash
export PIHOLE_PASS='(пароль из /opt/pihole/.env)'
/opt/pihole/apply-max-blocklists.sh
```

## Обновление Pi-hole

```bash
cd /opt/pihole
docker compose pull
docker compose up -d
```

## Состав репозитория

| Путь | Назначение |
|------|------------|
| `scripts/deploy.sh` | подъём Pi-hole / monitoring / vk-turn / systemd |
| `scripts/apply-amnezia-tweaks.sh` | после установки Amnezia с клиента |
| `scripts/ufw-allow.sh` | минимальные UFW allow |
| `amnezia/start.sh` | iptables: DNS hijack, no-NAT к Pi-hole, MSS clamp |
| `pihole/` | compose, nginx proxy, route scripts, blocklists |
| `monitoring/` | Prometheus, Grafana, Alertmanager, exporter |
| `vk-turn-proxy/` | VK Calls → `127.0.0.1:47054` (бинарь качается при build) |
| `systemd/` | host route + DNS socat relay |
| `docs/tweaks.md` | changelog твиков |

## Чего здесь нет (намеренно)

- Ключи WireGuard / `clientsTable` Amnezia (ставит клиент)
- Compose/образ Amnezia (ставит клиент)
- Реальные `.env`, Telegram token, пароли панелей
- Объёмы БД Grafana/Prometheus
- Клиентский APK/конфиг для VK Calls (endpoint сервера — `:56000`)

## Замечания по безопасности

- Не коммитьте заполненные `.env` / `secrets.env`
- После `apply-secrets.sh` в `alertmanager.yml` попадает токен — права `640`
- Публичные порты админок — только через UFW allowlist (`UFW_OPEN_ADMIN=1` или вручную)
