# routenode-infra

Конфиги, твики и скрипты VPN-шлюза (AmneziaWG + Pi-hole + мониторинг).

Секреты в репозиторий **не входят** — только `.env.example` / `secrets.env.example`.

## Архитектура

```
Клиент AmneziaWG ──UDP──► :47054 ──► amnezia-awg2 (awg0, 10.8.1.0/24)
                              │
                              ├─ DNS :53 (любой upstream) ──DNAT──► pihole 172.29.172.10
                              └─ остальной трафик ──MASQUERADE──► интернет

vk-turn-proxy :56000/udp ──► 127.0.0.1:47054 (опциональная UDP-обёртка)

Мониторинг: Prometheus → Grafana / Alertmanager (Telegram)
```

Сеть Docker: `amnezia-dns-net` (`172.29.172.0/24`):
| Контейнер        | IP            |
|------------------|---------------|
| amnezia-awg2     | 172.29.172.2  |
| pihole           | 172.29.172.10 |
| pihole-webproxy  | (dynamic)     |

## Быстрый подъём (с нуля)

### 0. Требования

- Ubuntu 22.04/24.04, Docker + Compose plugin
- Публичный IP, открытые UDP: `47054` (AWG), опционально `56000` (vk-turn)
- TCP: админки только после осознанного открытия UFW

### 1. Клонировать и положить секреты

```bash
sudo mkdir -p /opt && sudo git clone <THIS_REPO_URL> /opt/routenode-infra
cd /opt/routenode-infra

# Pi-hole
cp pihole/.env.example /opt/pihole/.env
chmod 600 /opt/pihole/.env
# отредактировать FTLCONF_webserver_api_password

# Grafana
mkdir -p /opt/monitoring
cp monitoring/.env.example /opt/monitoring/.env
chmod 600 /opt/monitoring/.env

# Exporter → тот же пароль Pi-hole
cp monitoring/exporters/.env.example /opt/monitoring/exporters/.env
chmod 600 /opt/monitoring/exporters/.env

# Telegram (опционально)
cp monitoring/alertmanager/secrets.env.example /opt/monitoring/alertmanager/secrets.env
chmod 600 /opt/monitoring/alertmanager/secrets.env
```

### 2. Развернуть рабочие каталоги

```bash
# Pi-hole
sudo mkdir -p /opt/pihole/{etc-pihole,etc-dnsmasq.d,log/nginx}
sudo cp pihole/docker-compose.yml pihole/nginx.conf \
       pihole/with-awg-route.sh pihole/awg-host-route.sh \
       pihole/apply-max-blocklists.sh /opt/pihole/
sudo chmod +x /opt/pihole/*.sh

# Monitoring
sudo cp -a monitoring/. /opt/monitoring/
# вернуть секреты поверх примеров, если копировали целиком:
# sudo cp monitoring/.env.example /opt/monitoring/.env  # уже сделано выше

# Amnezia start tweaks (после создания контейнера amnezia-awg2)
sudo mkdir -p /opt/amnezia
sudo cp amnezia/start.sh /opt/amnezia/start.sh
sudo chmod +x /opt/amnezia/start.sh
```

### 3. Docker-сеть и сервисы

```bash
docker network create \
  --subnet=172.29.172.0/24 \
  --gateway=172.29.172.1 \
  amnezia-dns-net || true

# AmneziaWG — подними своим compose/клиентом Amnezia, контейнер: amnezia-awg2
# затем:
docker cp /opt/amnezia/start.sh amnezia-awg2:/opt/amnezia/start.sh
docker restart amnezia-awg2

cd /opt/pihole && docker compose up -d
cd /opt/monitoring && docker compose up -d

# Telegram secrets → alertmanager.yml
cd /opt/monitoring/alertmanager
# убедись что в alertmanager.yml стоят TG_BOT_TOKEN_PLACEHOLDER и chat_id: -1
./apply-secrets.sh && docker restart alertmanager
```

### 4. Маршруты и DNS relay

```bash
# Host → VPN peers (ответы Pi-hole без NAT)
sudo cp systemd/awg-host-route.service /etc/systemd/system/
# путь ExecStart должен указывать на /opt/pihole/awg-host-route.sh
sudo systemctl daemon-reload
sudo systemctl enable --now awg-host-route.service

# Опционально: публичный DNS :53 только на PUBLIC_IP → Pi-hole
sudo sed 's/PUBLIC_IP/ВАШ_ПУБЛИЧНЫЙ_IP/g' systemd/pihole-dns-worker.service \
  | sudo tee /etc/systemd/system/pihole-dns-worker.service
sudo sed 's/PUBLIC_IP/ВАШ_ПУБЛИЧНЫЙ_IP/g' systemd/pihole-dns-worker-tcp.service \
  | sudo tee /etc/systemd/system/pihole-dns-worker-tcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now pihole-dns-worker pihole-dns-worker-tcp
```

### 5. Имена клиентов в Pi-hole

В UI Pi-hole → Local DNS / `dns.hosts`, либо API:

```
10.8.1.1 dell
10.8.1.2 husk
...
```

После твиков `start.sh` Pi-hole видит реальные `10.8.1.x` (не один NAT-хост).

### 6. Блоклисты (опционально)

```bash
export PIHOLE_PASS='(пароль из /opt/pihole/.env)'
/opt/pihole/apply-max-blocklists.sh
```

### 7. Проверки

```bash
docker ps
docker exec pihole pihole -v
docker exec amnezia-awg2 iptables -t nat -L PREROUTING -n | grep 53
curl -s http://127.0.0.1:9090/-/healthy
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/api/health
```

Grafana (локально): `http://127.0.0.1:3000`  
Pi-hole admin: `http://127.0.0.1:61864/admin/` (или публичный порт из compose)

## Обновление Pi-hole

```bash
cd /opt/pihole
docker compose pull
docker compose up -d
# проверить маршрут 10.8.1.0/24 и DNS с VPN
```

Данные в volumes (`etc-pihole`) сохраняются.

## Состав репозитория

| Путь | Назначение |
|------|------------|
| `amnezia/start.sh` | iptables: DNS hijack, no-NAT к Pi-hole, MSS clamp |
| `pihole/` | compose, nginx proxy, route scripts, blocklists |
| `monitoring/` | Prometheus, Grafana dashboards, Alertmanager, exporter |
| `vk-turn-proxy/` | compose UDP-обёртки перед AWG |
| `systemd/` | host route + DNS socat relay |

## Чего здесь нет (намеренно)

- Ключи WireGuard / `clientsTable` Amnezia
- Реальные `.env`, Telegram token, пароли панелей
- Объёмы БД Grafana/Prometheus
- Полный образ Amnezia (поднимается клиентом Amnezia)

## Замечания по безопасности

- Не коммитьте заполненные `.env` / `secrets.env`
- После `apply-secrets.sh` в `alertmanager.yml` попадает токен — файл должен быть `640` и **в `.gitignore` уже есть исключения для секретов; сам yml с плейсхолдерами ок для git**
- Публичные порты админок открывайте только через UFW allowlist
EOF