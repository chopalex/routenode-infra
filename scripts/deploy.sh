#!/usr/bin/env bash
# Greenfield deploy for routenode-infra (Pi-hole, monitoring, vk-turn-proxy, systemd).
# AmneziaWG: install from Amnezia client, then run scripts/apply-amnezia-tweaks.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_IP="${PUBLIC_IP:-}"
SKIP_UFW="${SKIP_UFW:-0}"
SKIP_VK_TURN="${SKIP_VK_TURN:-0}"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "need '$1'"; }

need_cmd docker
docker compose version >/dev/null 2>&1 || die "need docker compose plugin"

if [[ $EUID -ne 0 ]]; then
  die "run as root (sudo)"
fi

if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP="$(curl -4 -fsS --max-time 5 https://ifconfig.me 2>/dev/null || true)"
fi
[[ -n "$PUBLIC_IP" ]] || die "set PUBLIC_IP=x.x.x.x (auto-detect failed)"

info "repo: $REPO_DIR"
info "PUBLIC_IP=$PUBLIC_IP"

# --- layout ---
info "layout + secrets templates"
mkdir -p /opt/pihole/{etc-pihole,etc-dnsmasq.d,log/nginx} \
         /opt/monitoring/alertmanager \
         /opt/monitoring/exporters \
         /opt/amnezia \
         /opt/vk-turn-proxy

cp -a "$REPO_DIR/pihole/docker-compose.yml" \
      "$REPO_DIR/pihole/nginx.conf" \
      "$REPO_DIR/pihole/with-awg-route.sh" \
      "$REPO_DIR/pihole/awg-host-route.sh" \
      "$REPO_DIR/pihole/apply-max-blocklists.sh" \
      /opt/pihole/
chmod +x /opt/pihole/*.sh

# copy tree but keep existing secrets / volume dirs
tar -C "$REPO_DIR/monitoring" \
  --exclude='.env' \
  --exclude='alertmanager/secrets.env' \
  --exclude='exporters/.env' \
  --exclude='prometheus_data' \
  --exclude='grafana_data' \
  --exclude='alertmanager_data' \
  -cf - . | tar -C /opt/monitoring -xf -

cp -a "$REPO_DIR/amnezia/start.sh" /opt/amnezia/start.sh
chmod +x /opt/amnezia/start.sh

cp -a "$REPO_DIR/vk-turn-proxy/docker-compose.yml" \
      "$REPO_DIR/vk-turn-proxy/Dockerfile" \
      /opt/vk-turn-proxy/

# secrets: create from examples if missing
if [[ ! -f /opt/pihole/.env ]]; then
  cp "$REPO_DIR/pihole/.env.example" /opt/pihole/.env
  chmod 600 /opt/pihole/.env
  echo "WARN: edit /opt/pihole/.env (FTLCONF_webserver_api_password)" >&2
fi
if [[ ! -f /opt/monitoring/.env ]]; then
  cp "$REPO_DIR/monitoring/.env.example" /opt/monitoring/.env
  chmod 600 /opt/monitoring/.env
  echo "WARN: edit /opt/monitoring/.env (Grafana admin)" >&2
fi
if [[ ! -f /opt/monitoring/exporters/.env ]]; then
  cp "$REPO_DIR/monitoring/exporters/.env.example" /opt/monitoring/exporters/.env
  chmod 600 /opt/monitoring/exporters/.env
  echo "WARN: set Pi-hole password in /opt/monitoring/exporters/.env" >&2
fi
if [[ ! -f /opt/monitoring/alertmanager/secrets.env ]]; then
  cp "$REPO_DIR/monitoring/alertmanager/secrets.env.example" \
     /opt/monitoring/alertmanager/secrets.env
  chmod 600 /opt/monitoring/alertmanager/secrets.env
  echo "WARN: optional Telegram in /opt/monitoring/alertmanager/secrets.env" >&2
fi

# --- docker network ---
info "docker network amnezia-dns-net"
docker network inspect amnezia-dns-net >/dev/null 2>&1 || \
  docker network create \
    --subnet=172.29.172.0/24 \
    --gateway=172.29.172.1 \
    amnezia-dns-net

# --- services ---
info "pihole"
(cd /opt/pihole && docker compose up -d)

info "monitoring"
(cd /opt/monitoring && docker compose up -d --build)

if [[ "$SKIP_VK_TURN" != "1" ]]; then
  info "vk-turn-proxy (build downloads binary from GitHub releases)"
  (cd /opt/vk-turn-proxy && docker compose up -d --build)
fi

# Telegram placeholders → live yml if secrets filled
if grep -q 'TG_BOT_TOKEN_PLACEHOLDER' /opt/monitoring/alertmanager/alertmanager.yml 2>/dev/null; then
  if grep -qvE '^(#|$)|PLACEHOLDER' /opt/monitoring/alertmanager/secrets.env 2>/dev/null; then
    info "apply alertmanager secrets"
    (cd /opt/monitoring/alertmanager && ./apply-secrets.sh && docker restart alertmanager || true)
  fi
fi

# --- systemd ---
info "systemd units"
cp "$REPO_DIR/systemd/awg-host-route.service" /etc/systemd/system/
sed "s/PUBLIC_IP/${PUBLIC_IP}/g" "$REPO_DIR/systemd/pihole-dns-worker.service" \
  > /etc/systemd/system/pihole-dns-worker.service
sed "s/PUBLIC_IP/${PUBLIC_IP}/g" "$REPO_DIR/systemd/pihole-dns-worker-tcp.service" \
  > /etc/systemd/system/pihole-dns-worker-tcp.service
systemctl daemon-reload
systemctl enable --now awg-host-route.service || true
# DNS worker optional — enable only if you want public :53 on PUBLIC_IP
# systemctl enable --now pihole-dns-worker pihole-dns-worker-tcp

if [[ "$SKIP_UFW" != "1" ]] && command -v ufw >/dev/null 2>&1; then
  info "UFW rules (scripts/ufw-allow.sh)"
  "$REPO_DIR/scripts/ufw-allow.sh" || true
fi

cat <<EOF

Done (base stack).

Next — Amnezia from client:
  1) Install AmneziaWG container (name: amnezia-awg2, UDP :47054)
  2) Attach it to network: docker network connect --ip 172.29.172.2 amnezia-dns-net amnezia-awg2
     (IP may differ; start.sh / Pi-hole resolve by name when possible)
  3) $REPO_DIR/scripts/apply-amnezia-tweaks.sh

Checks:
  docker ps
  curl -s -o /dev/null -w 'grafana:%{http_code}\\n' http://127.0.0.1:3000/api/health
  curl -s http://127.0.0.1:9090/-/healthy
  ss -ulnp | grep -E '47054|56000' || true

Secrets still to fill if WARN above:
  /opt/pihole/.env
  /opt/monitoring/.env
  /opt/monitoring/exporters/.env
  /opt/monitoring/alertmanager/secrets.env
EOF
