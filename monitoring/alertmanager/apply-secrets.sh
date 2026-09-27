#!/bin/bash
# Substitute TG_BOT_TOKEN / TG_CHAT_ID from secrets.env into alertmanager.yml.
# Keeps real credentials out of compose env and image layers.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/secrets.env"

if [[ -z "$TG_BOT_TOKEN" || "$TG_BOT_TOKEN" == "PLACEHOLDER" ]]; then
  echo "ERROR: fill $DIR/secrets.env with real TG_BOT_TOKEN / TG_CHAT_ID first" >&2
  exit 1
fi

sed -i \
  -e "s/TG_BOT_TOKEN_PLACEHOLDER/${TG_BOT_TOKEN}/g" \
  -e "s/chat_id: -1/chat_id: ${TG_CHAT_ID}/g" \
  "$DIR/alertmanager.yml"

chgrp 65534 "$DIR/alertmanager.yml" && chmod 640 "$DIR/alertmanager.yml"
echo "alertmanager.yml updated (token ***${TG_BOT_TOKEN: -4}, chat ${TG_CHAT_ID})"
