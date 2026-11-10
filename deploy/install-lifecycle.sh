#!/bin/sh
set -eu
test "$(id -u)" -eq 0 || { printf '%s\n' 'Run with sudo from the host terminal.' >&2; exit 1; }
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TAILNET_IP=$(tailscale ip -4)
python3 - "$TAILNET_IP" <<'PY'
import ipaddress
import sys
assert ipaddress.ip_address(sys.argv[1]) in ipaddress.ip_network('100.64.0.0/10'), 'Expected a Tailscale IPv4 address'
PY
"$SOURCE_DIR/deploy/install.sh" "${1:-$SOURCE_DIR/config/example.json}"
MONITOR_UNIT=$(mktemp)
trap 'rm -f "$MONITOR_UNIT"' EXIT HUP INT TERM
sed "s/__TAILSCALE_IP__/$TAILNET_IP/g" "$SOURCE_DIR/deploy/supervisor-monitor.service.in" > "$MONITOR_UNIT"
install -o root -g root -m 0644 "$MONITOR_UNIT" /etc/systemd/system/supervisor-monitor.service
systemctl daemon-reload
systemctl enable --now supervisor-monitor.service
printf '\nMonitor: http://%s:8766/\n' "$TAILNET_IP"
printf '%s\n' 'First-install dispatch is disabled. The assistant can now seed the lifecycle test and enable it.'
