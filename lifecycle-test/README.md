# Evolution ideas lifecycle test

The original notes are preserved in [ideas.md](ideas.md). The seed message asks The Supervisor to
triage and prioritize them, organize the useful ideas, and start a focused project if warranted.
It does not prescribe an experiment or require wasting time on a project that looks unpromising.

Install the backend and the temporary read-only Tailscale monitor from the host terminal:

```sh
sudo /home/omega/llms/supervisor-agent/deploy/install-lifecycle.sh
```

On first installation dispatch stays disabled. Once the services are healthy, submit the test once:

```sh
/srv/supervisor/current/.venv/bin/python /home/omega/llms/supervisor-agent/lifecycle-test/start.py
```

`start.py` records the inbox identifier in `run.json` before enabling dispatch. It refuses repeated
submission once that receipt exists, and uses a backend idempotency key to protect a retried submission.
An uncertain/failed activation should be inspected with `supervisorctl status` rather than blindly retried.

The monitor is at `http://100.97.90.14:8766/` on this machine's tailnet. It exposes only whitelisted
GET views; administrative operations and the pool inference proxy are not exposed over HTTP.
Supervisor output is streamed from its event log; researchers expose their harness progress/events.
No separate research agent transcript API is added. Markdown replies and publications are shown as text.

Both services run under `rh-agent` and persist under systemd independently of the coding session.
The normal 00/04/08/12/16/20 UTC checks remain enabled during the test. There is no automatic stop
at 24 hours; the user decides when to end the test. To request a progress-preserving stop:

```sh
supervisorctl stop
```

Wait until the supervisor and harness acknowledge their pauses before stopping services. To remove
the temporary monitor after the test, independently of research state:

```sh
sudo systemctl disable --now supervisor-monitor.service
```
