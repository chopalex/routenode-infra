#!/bin/bash
set -euo pipefail
AWG_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "amnezia-dns-net").IPAddress}}' amnezia-awg2)
ip route replace 10.8.1.0/24 via "$AWG_IP" dev amn0
echo "host route: 10.8.1.0/24 via $AWG_IP"
