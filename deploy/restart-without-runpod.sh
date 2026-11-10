#!/bin/sh
set -eu
test "$(id -u)" -eq 0 || { printf '%s\n' 'Run this operator setup command with sudo.' >&2; exit 1; }
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# This reset is only for the abandoned initial request, before a research catalog exists.
/srv/supervisor/current/.venv/bin/python - <<'PY'
import httpx
with httpx.Client(transport=httpx.HTTPTransport(uds='/var/lib/supervisor-agent/daemon.sock'),
                  base_url='http://supervisor',timeout=15) as client:
    status=client.get('/v1/status')
    status.raise_for_status()
    data=status.json()
    assert not data['enabled'] and not data['active_execution'], 'Stop dispatch and wait for safe pause first'
    assert not data['harness']['health']['active_projects'], 'Pause active research before resetting'
    for collection in ('lines','projects'):
        response=client.get('/v1/'+collection)
        response.raise_for_status()
        assert not response.json(), 'Catalog is not empty; do not reset established research'
PY

systemctl stop supervisor-monitor.service supervisor-agent.service
systemctl disable --now runpod-agent-tool.service
python3 - "$SOURCE_DIR" <<'PY'
import json
import os
import pwd
import grp
import shutil
from datetime import datetime, timezone
from pathlib import Path
source=Path(__import__('sys').argv[1])
state=Path('/var/lib/supervisor-agent')
config=json.loads((state/'config.json').read_text())
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
base=Path('/home/omega/.local/state/supervisor-agent-restarts')
base.mkdir(parents=True,exist_ok=True)
base.chmod(0o700)
operator=pwd.getpwnam('omega')
os.chown(base,operator.pw_uid,operator.pw_gid)
archive=base/stamp
archive.mkdir(mode=0o700)
os.chown(archive,operator.pw_uid,operator.pw_gid)
shutil.move(str(state),str(archive/'previous-state'))
receipt=source/'lifecycle-test/run.json'
if receipt.exists():
    shutil.move(str(receipt),str(archive/'previous-request.json'))
hidden=[str(base), str(source/'lifecycle-test'), '/home/omega/llms/runpod_agent_tool',
        '/srv/runpod-agent-tool', '/var/lib/runpod-agent-tool',
        '/home/omega/llms/iterative_research_harness/src/irh/runpod_mcp.py',
        '/home/omega/llms/iterative_research_harness/tests/test_runpod_mcp.py',
        '/home/omega/llms/iterative_research_harness/TODO.md']
config['hidden_paths']=list(dict.fromkeys([*config.get('hidden_paths',[]),*hidden]))
state.mkdir(mode=0o2770)
account=pwd.getpwnam('rh-agent')
group=grp.getgrnam('irh-worker').gr_gid
os.chown(state,account.pw_uid,group)
state.chmod(0o2770)
path=state/'config.json'
path.write_text(json.dumps(config,indent=2)+'\n')
os.chown(path,account.pw_uid,group)
path.chmod(0o640)
harness=Path('/var/lib/iterative-research-harness/config.json')
data=json.loads(harness.read_text())
data['tools']=[tool for tool in data.get('tools',[]) if tool['id']!='runpod']
harness.write_text(json.dumps(data,indent=2)+'\n')
unit=Path('/etc/systemd/system/irh-daemon.service')
unit.write_text(unit.read_text().replace('ReadWritePaths=-/var/lib/runpod-agent-tool\n',''))
print('Archived the initial supervisor state under',archive)
print('Available harness tools:',[tool['id'] for tool in data['tools']])
PY
systemctl daemon-reload
systemctl restart irh-daemon.service
systemctl start supervisor-agent.service supervisor-monitor.service
printf '%s\n' 'Fresh supervisor state is ready with dispatch disabled. The assistant can submit the ordinary research request.'
