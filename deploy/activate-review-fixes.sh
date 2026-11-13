#!/bin/sh
# Restart already staged releases without enabling agents or clearing the operator hold.
set -eu
test "$(id -u)" -eq 0 || { echo 'Run with sudo to restart the system services.' >&2; exit 1; }
PLAN=/home/omega/.local/state/supervisor-agent-review-fixes/releases.json
SUPERVISOR_RELEASE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["supervisor"])' "$PLAN")
HARNESS_RELEASE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["harness"])' "$PLAN")
test "$(readlink -f /srv/supervisor/current)" = "$SUPERVISOR_RELEASE"
test "$(readlink -f /srv/irh/current)" = "$HARNESS_RELEASE"
"$SUPERVISOR_RELEASE/.venv/bin/supervisorctl" status | python3 -c '
import json,sys
s=json.load(sys.stdin)
assert not s["enabled"] and not s["active_execution"], "Dispatch must be stopped"
'
"$HARNESS_RELEASE/.venv/bin/irh" health | python3 -c '
import json,sys
assert not json.load(sys.stdin)["active_projects"], "Research must be paused"
'
systemctl stop supervisor-monitor.service supervisor-agent.service
systemctl restart irh-daemon.service
for attempt in $(seq 1 30); do
    if "$HARNESS_RELEASE/.venv/bin/irh" health >/dev/null 2>&1; then break; fi
    sleep 1
done
"$HARNESS_RELEASE/.venv/bin/irh" health >/dev/null
systemctl start supervisor-agent.service supervisor-monitor.service
for attempt in $(seq 1 30); do
    if "$SUPERVISOR_RELEASE/.venv/bin/supervisorctl" status >/dev/null 2>&1; then break; fi
    sleep 1
done
"$SUPERVISOR_RELEASE/.venv/bin/supervisorctl" status | python3 -c '
import json,sys
s=json.load(sys.stdin)
assert not s["enabled"] and not s["active_execution"]
assert not s["harness"]["health"]["active_projects"]
print("Updated services are ready. Dispatch remains disabled; research has not resumed.")
'
