#!/usr/bin/env bash
# After Amnezia client created container amnezia-awg2: copy DNS/NAT tweaks and restart.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="${AWG_CONTAINER:-amnezia-awg2}"
START_SRC="${START_SRC:-/opt/amnezia/start.sh}"

[[ -f "$START_SRC" ]] || START_SRC="$REPO_DIR/amnezia/start.sh"
[[ -f "$START_SRC" ]] || { echo "ERROR: start.sh not found" >&2; exit 1; }

docker inspect "$CONTAINER" >/dev/null 2>&1 || {
  echo "ERROR: container '$CONTAINER' not running. Install AmneziaWG from the Amnezia client first." >&2
  exit 1
}

# Ensure shared DNS network
if ! docker inspect -f '{{json .NetworkSettings.Networks}}' "$CONTAINER" | grep -q amnezia-dns-net; then
  echo "==> connect $CONTAINER → amnezia-dns-net"
  docker network create --subnet=172.29.172.0/24 --gateway=172.29.172.1 amnezia-dns-net 2>/dev/null || true
  docker network connect amnezia-dns-net "$CONTAINER" || true
fi

mkdir -p /opt/amnezia
cp -a "$START_SRC" /opt/amnezia/start.sh
chmod +x /opt/amnezia/start.sh

echo "==> docker cp start.sh → $CONTAINER"
docker cp /opt/amnezia/start.sh "$CONTAINER:/opt/amnezia/start.sh"
docker restart "$CONTAINER"

# Host route for Pi-hole replies (if unit installed)
if systemctl list-unit-files awg-host-route.service >/dev/null 2>&1; then
  systemctl restart awg-host-route.service || true
fi

echo "==> verify DNS hijack rules"
docker exec "$CONTAINER" sh -c 'iptables -t nat -L PREROUTING -n 2>/dev/null | grep -E "53|dpt:53" || true'
echo "OK: tweaks applied on $CONTAINER"
