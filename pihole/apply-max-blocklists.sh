#!/bin/bash
set -euo pipefail
PIHOLE_API="${PIHOLE_API:-http://172.29.172.10/api}"
PIHOLE_PASS="${PIHOLE_PASS:?set PIHOLE_PASS in env or pihole/.env}"
SID=$(curl -sk -X POST "${PIHOLE_API}/auth" -H "Content-Type: application/json" -d "{\"password\":\"${PIHOLE_PASS}\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)[\"session\"][\"sid\"])")
api() { curl -sk "$@" -H "X-FTL-SID: ${SID}" -H "Content-Type: application/json"; }
LISTS=(
  "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts|StevenBlack unified"
  "https://big.oisd.nl/domainswild|OISD Full wildcard"
  "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/pro.txt|HaGezi Multi PRO"
  "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/popupads.txt|HaGezi Popup Ads"
  "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/tif.txt|HaGezi Threat Intelligence"
  "https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt|AdGuard DNS filter"
  "https://o0.pages.dev/Xtra/adblock.txt|1Hosts Xtra"
  "https://raw.githubusercontent.com/RPiList/specials/master/Blocklisten/malware|RPiList malware"
  "https://phishing.army/download/phishing_army_blocklist_extended.txt|Phishing Army extended"
  "https://raw.githubusercontent.com/Spam404/lists/master/main-blacklist.txt|Spam404"
)
existing=$(api "${PIHOLE_API}/lists" | python3 -c "import sys,json; print(chr(10).join(l[\"address\"] for l in json.load(sys.stdin).get(\"lists\",[])))")
for entry in "${LISTS[@]}"; do
  url="${entry%%|*}"; comment="${entry#*|}"
  if echo "$existing" | grep -Fxq "$url"; then echo "skip: $url"; continue; fi
  echo "add: $url"
  api -X POST "${PIHOLE_API}/lists" -d "{\"address\":\"${url}\",\"type\":\"block\",\"enabled\":true,\"comment\":\"${comment}\",\"groups\":[0]}"
done
docker exec pihole pihole-FTL --config dns.CNAMEdeepInspect true
docker exec pihole pihole-FTL --config dns.blockESNI true
docker exec pihole pihole-FTL --config dns.blocking.active true
docker exec pihole pihole-FTL --config dns.blocking.mode NULL
docker exec pihole pihole-FTL --config dns.blockTTL 2
docker exec pihole pihole-FTL --config dns.specialDomains.iCloudPrivateRelay true
docker exec pihole pihole-FTL --config dns.specialDomains.mozillaCanary true
docker exec pihole pihole-FTL --config dns.specialDomains.designatedResolver true
docker exec pihole pihole-FTL --config dns.cache.upstreamBlockedTTL 86400
echo "Updating gravity..."
docker exec pihole pihole -g
echo Done.
