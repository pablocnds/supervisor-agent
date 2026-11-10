# The Supervisor

A backend for directing local research through an independently running iterative research harness.
The daemon runs as `rh-agent`, owns its own SQLite state and Unix-socket API, and exposes
`supervisorctl` for unstructured messages, research organization, scheduling, and communications.
The permanent frontend remains deferred. A temporary read-only monitor for the lifecycle test is
documented in [lifecycle-test/README.md](lifecycle-test/README.md). Daily backups are deferred.

The implementation follows [REQUIREMENTS.md](REQUIREMENTS.md). Operational details and settings that
will likely need tuning are in [docs/operations.md](docs/operations.md) and [docs/tuning.md](docs/tuning.md).

```sh
uv sync
uv run pytest -q
uv run ruff check .
```

Review `config/example.json`, particularly the model endpoint/profile and credential paths, then install:

```sh
sudo ./deploy/install.sh /absolute/path/to/config.json
supervisorctl status
supervisorctl message 'Organize these research ideas: ...'
supervisorctl enable
supervisorctl tick
```

The installer starts the service; first-install dispatch is disabled until `enable`. Installation does
not start research. An enabled routine tick or immediate message allows the agent to manage research.
`tick` processes each pending inbox item in a separate execution, then runs a separate routine check.
Messages without `--now` wait for the next calendar tick; `message '...' --now` requests earlier handling.

Normal project starts/resumes go through The Supervisor. Use direct `irh run` only for maintenance while
The Supervisor is stopped. This is cooperative coordination, not a lock against independent external clients.

To stop automatic work and request a progress-preserving pause:

```sh
supervisorctl stop
supervisorctl status
```

The daemon and CLI remain available while dispatch is disabled. `waiting_to_pause` means an in-flight
model request or synchronous tool must finish. `enable` deliberately restores dispatch; paused supervisor
executions require `resume-execution ID` if you want to continue their context.

Updates do not modify running services autonomously:

```sh
supervisorctl stop
# Wait until status shows no active execution and the harness is no longer executing.
./deploy/update.sh
sudo systemctl restart supervisor-agent.service
```

The service remains stopped for dispatch after an update until explicitly enabled again.
