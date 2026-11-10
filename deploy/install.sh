#!/bin/sh
set -eu
test "$(id -u)" -eq 0 || { printf '%s\n' 'Run this installer with sudo.' >&2; exit 1; }
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CONFIG=${1:-$SOURCE_DIR/config/example.json}
test -f "$CONFIG"
getent passwd rh-agent >/dev/null
getent group irh-worker >/dev/null
install -d -o omega -g irh-worker -m 2775 /srv/supervisor /srv/supervisor/releases
install -d -o rh-agent -g irh-worker -m 2770 /var/lib/supervisor-agent
runuser -u omega -- "$SOURCE_DIR/deploy/update.sh"
install -o rh-agent -g irh-worker -m 0640 "$CONFIG" /var/lib/supervisor-agent/config.json
install -o root -g root -m 0644 "$SOURCE_DIR/deploy/supervisor-agent.service" /etc/systemd/system/supervisor-agent.service
ln -sf /srv/supervisor/current/.venv/bin/supervisorctl /usr/local/bin/supervisorctl
systemctl daemon-reload
systemctl enable --now supervisor-agent.service
printf '%s\n' 'Backend installed. Dispatch starts disabled on first installation; inspect supervisorctl status.'
