#!/usr/bin/env bash
# Minimal UFW allows for routenode stack. Does NOT enable UFW if inactive.
set -euo pipefail

command -v ufw >/dev/null 2>&1 || { echo "ufw not installed, skip"; exit 0; }

SSH_PORT="${SSH_PORT:-22}"
# detect non-default ssh port from sshd if present
if [[ -r /etc/ssh/sshd_config ]]; then
  p="$(awk '/^Port /{print $2; exit}' /etc/ssh/sshd_config || true)"
  [[ -n "${p:-}" ]] && SSH_PORT="$p"
fi

echo "==> UFW allow SSH ${SSH_PORT}/tcp, AWG 47054/udp, vk-turn 56000/udp"
ufw allow "${SSH_PORT}/tcp" comment 'SSH' || true
ufw allow 47054/udp comment 'AmneziaWG' || true
ufw allow 56000/udp comment 'vk-turn-proxy VK Calls' || true

# Admin panels — comment out if you want them closed by default
if [[ "${UFW_OPEN_ADMIN:-0}" == "1" ]]; then
  ufw allow 61864/tcp comment 'Pi-hole admin' || true
  ufw allow 49818/tcp comment 'Grafana' || true
fi

ufw status verbose || true
echo "Note: ufw enable is NOT run automatically. Enable yourself after checking SSH."
