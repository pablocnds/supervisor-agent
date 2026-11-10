#!/bin/sh
# Activate already-built, committed releases. Research remains stopped.
set -eu
test "$(id -u)" -eq 0 || { echo 'Run this activation step with sudo.' >&2; exit 1; }
PLAN=/home/omega/.local/state/supervisor-agent-recovery/releases.json
test -f "$PLAN"
SUPERVISOR_RELEASE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["supervisor"])' "$PLAN")
HARNESS_RELEASE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["harness"])' "$PLAN")
case "$SUPERVISOR_RELEASE" in /srv/supervisor/releases/*) ;; *) exit 1 ;; esac
case "$HARNESS_RELEASE" in /srv/irh/releases/*) ;; *) exit 1 ;; esac
test "$(readlink -f /srv/supervisor/current)" = "$SUPERVISOR_RELEASE"
test "$(readlink -f /srv/irh/current)" = "$HARNESS_RELEASE"
"$SUPERVISOR_RELEASE/.venv/bin/supervisorctl" status | python3 -c '
import json,sys
s=json.load(sys.stdin)
assert not s["enabled"] and not s["active_execution"], "Stop dispatch and wait for the current execution first"
'
"$HARNESS_RELEASE/.venv/bin/irh" health | python3 -c '
import json,sys
assert not json.load(sys.stdin)["active_projects"], "Safely pause research before activation"
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
runuser -u omega -- "$SUPERVISOR_RELEASE/.venv/bin/python" \
  "$SUPERVISOR_RELEASE/docs/reviews/2026-11-10/recovery/apply_ea1_recovery.py"
CHECK_FAILURE=0
EFFICIENCY="$SUPERVISOR_RELEASE/docs/reviews/2026-11-10/efficiency"
if test -f "$EFFICIENCY/prepare_guidance.py"; then
  runuser -u omega -- "$SUPERVISOR_RELEASE/.venv/bin/python" "$EFFICIENCY/prepare_guidance.py"
  runuser -u omega -- "$SUPERVISOR_RELEASE/.venv/bin/python" "$EFFICIENCY/acknowledge_reviewed_alerts.py"
  CHECK_FAILURE=1
fi
"$SUPERVISOR_RELEASE/.venv/bin/supervisorctl" status | python3 -c '
import json,sys
s=json.load(sys.stdin)
assert not s["enabled"] and not s["active_execution"]
assert all(p["execution"]["state"] != "running" for p in s["projects"])
if sys.argv[1] == "1":
    assert not s["critical_failure"], "A new failure needs operator inspection"
print("Updated services are running. Supervisor dispatch is disabled; research remains paused.")
' "$CHECK_FAILURE"
echo "Supervisor release: $SUPERVISOR_RELEASE"
echo "Harness release: $HARNESS_RELEASE"
