# Твики (changelog инфраструктуры)

## DNS / Pi-hole ↔ AmneziaWG

1. **Прозрачный DNS hijack** — любой UDP/TCP :53 с `10.8.1.0/24` (кроме уже Pi-hole) → `172.29.172.10`  
   Клиент может оставить «Amnezia DNS» / `1.1.1.1` в приложении.
2. **Блок DoT :853** — меньше обхода Pi-hole.
3. **RETURN перед MASQUERADE** для `dst 172.29.172.0/24` — в Query Log видны `10.8.1.x`, не один NAT IP.
4. **Маршрут на Pi-hole** `10.8.1.0/24 via amnezia-awg2` (entrypoint `with-awg-route.sh`).
5. **Host route** `awg-host-route.service` — ответы через docker bridge.
6. **dns.hosts** — человекочитаемые имена пиров.

## Мониторинг

- Кастомный `service-exporter`: AWG peers + Pi-hole v6 API + docker stats + GeoIP.
- Pi-hole counters: history buckets / mono-accumulator (windowed summary API иначе ломает `rate()`).
- Дашборды: Home, System, AmneziaWG, Peer details, Peer history 7d, Pi-hole.
- Alertmanager → Telegram (critical / warning), SLO recording rules.

## Сеть

- TCP MSS 1280 на FORWARD awg0 (путь vk-turn + AWG, веб без MTU blackhole).
- socat UDP/TCP 53 на публичном IP → Pi-hole (опциональный внешний DNS).
EOF