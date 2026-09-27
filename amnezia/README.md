# AmneziaWG startup tweaks

`start.sh` is mounted/copied into the Amnezia AWG container and runs on every start.

Tweaks vs stock Amnezia:
- Transparent DNS hijack (UDP/TCP 53) → Pi-hole `172.29.172.10`
- Block DoT (853) to reduce DNS bypass
- No MASQUERADE toward `172.29.172.0/24` so Pi-hole sees real `10.8.1.x` clients
- FORWARD eth0→awg0 for Pi-hole replies
- TCP MSS clamp 1280 (vk-turn + AWG path)

Deploy: copy into the running container and ensure the container entrypoint uses it
(Amnezia typically keeps `/opt/amnezia/start.sh` inside the image/volume).

```bash
docker cp amnezia/start.sh amnezia-awg2:/opt/amnezia/start.sh
# or bind-mount in your AWG compose
```
