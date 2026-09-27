#!/bin/bash
# Add return route to AmneziaWG peers so Pi-hole can answer DNS without NAT.
set -euo pipefail
AWG_IP=""
if getent hosts amnezia-awg2 >/dev/null 2>&1; then
  AWG_IP=$(getent hosts amnezia-awg2 | awk '{print $1; exit}')
fi
if [ -z "$AWG_IP" ]; then
  AWG_IP=172.29.172.2
fi
ip route replace 10.8.1.0/24 via "$AWG_IP" 2>/dev/null || true
echo "pihole: route 10.8.1.0/24 via $AWG_IP"
exec /usr/bin/start.sh
