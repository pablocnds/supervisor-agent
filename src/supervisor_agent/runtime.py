from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from zoneinfo import ZoneInfo

from .agent import Agent, Paused
from .config import write_json
from .harness import Harness
from .store import now


class Runtime:
    def __init__(self, config, store, harness=None, agent_factory=Agent):
        self.config, self.store = config, store
        self.harness = harness or Harness(config.harness_socket)
        self.agent_factory = agent_factory
        self.agent = None
        self.task = None
        self.stopping = False
        self.wake = asyncio.Event()
        self.phase = "idle"
        self.started_at = now()
        self.snapshot = {"health": {}, "projects": {}}

    def environment_map(self):
        c = self.config
        return (
            f"- State, research notes, communications, transcripts, observations: {c.state_root}\n"
            f"- Current workspace: {c.state_root}/executions/EXECUTION_ID/workspace\n"
            f"- Sources and project documentation: {c.source_root}\n"
            f"- Harness control: irh --socket {c.harness_socket}; docs: "
            f"{c.source_root}/iterative_research_harness/docs/supervision.md\n"
            f"- Harness artifacts: /var/lib/iterative-research-harness/projects\n"
            f"- Administration and catalog: supervisorctl --help (Unix socket {c.socket})\n"
            f"- Model inference/status from shell: curl --unix-socket {c.socket} "
            "http://supervisor/pool/v1/models (or POST /pool/v1/chat/completions). "
            "This fixed pool proxy does not permit service configuration changes.\n"
            "- Normal starts/resumes are coordinated here. Select next work with supervisorctl select; "
            "do not directly run/resume the harness from inside an agent execution. "
            "Use --actor supervisor for harness steering and pause calls.\n"
            "- The shell has read-only host files, a writable execution workspace, and no internet. "
            "Its private process namespace shows local children; host process observations are under observations/.\n"
            "- Shell calls are synchronous: children die when the call ends, even with nohup/setsid/disown. "
            "Each call has a fresh /tmp; use the execution workspace for files needed by later calls.\n"
            "- Research line/project directories accept free-form notes through supervisorctl note. "
            "Use its CLI/API for metadata and communications; do not edit live service databases."
        )

    async def start_context(self, execution):
        inbox = self.store.one("inbox", execution["inbox_id"]) if execution["inbox_id"] else None
        project = self.store.one("projects", execution["project_id"]) if execution["project_id"] else None
        return {
            "execution_id": execution["id"],
            "trigger": execution["kind"],
            "task": execution["task"],
            "created_at": execution["created_at"],
            "inbox": inbox,
            "project": project,
            "selected_project": self.store.get("next_project"),
            "harness": self.snapshot,
            "catalog": self.store.rows(
                "SELECT id,line_id,name,backend,priority,status,held FROM projects ORDER BY priority DESC LIMIT 50"
            ),
            "recent_alerts": self.store.rows(
                "SELECT id,text,occurrences,state,execution_id,updated_at FROM inbox "
                "WHERE kind='alert' ORDER BY updated_at DESC LIMIT ?",
                (self.config.recent_alert_limit,),
            ),
            "research_directory": str(self.store.research_path("project", project["id"]))
            if project
            else None,
        }

    def status(self):
        return {
            "version": "0.1.0",
            "enabled": self.store.get("enabled", False),
            "phase": self.phase,
            "active_execution": self.agent.id if self.agent else None,
            "activity": {
                "kind": self.agent.execution["kind"],
                "elapsed_seconds": self.agent.elapsed,
                "operation": {k: v for k, v in self.agent.operation.items() if k != "started"}
                if self.agent.operation
                else None,
                "last_progress": self.agent.last_progress,
            }
            if self.agent
            else None,
            "waiting_to_pause": self.phase == "waiting_to_pause"
            or bool(self.agent and self.pause_reason(self.agent)),
            "next_project": self.store.get("next_project"),
            "critical_failure": self.store.get("critical_failure"),
            "harness": self.snapshot,
            "schedule": {"hours": self.config.hours, "timezone": self.config.timezone},
            "projects": [self.project_view(p) for p in self.store.rows("SELECT * FROM projects")],
        }

    def project_view(self, project):
        observed = {"state": "unknown", "blocked_by": None}
        if project["backend"] == "harness":
            backend = self.snapshot.get("projects", {}).get(project["backend_id"])
            if backend:
                control = backend["control"]
                observed.update(
                    state="complete" if backend["phase"] == "complete" else control["state"],
                    backend_phase=backend["phase"],
                    pause_reason=(control.get("pause_request") or {}).get("reason"),
                )
        else:
            jobs = self.store.rows(
                "SELECT state,error FROM executions WHERE project_id=? AND kind='delegate' ORDER BY rowid DESC LIMIT 1",
                (project["id"],),
            )
            observed.update(
                state=jobs[0]["state"] if jobs else "idle", error=jobs[0]["error"] if jobs else None
            )
        if not self.store.get("enabled", False):
            observed["blocked_by"] = self.store.get("critical_failure") or "Supervisor dispatch is disabled"
        return {**project, "execution": observed}

    async def wait_for_harness(self):
        import httpx

        deadline = time.monotonic() + self.config.startup_timeout_seconds
        while True:
            try:
                health = await self.harness.health()
                if not health.get("ok"):
                    raise RuntimeError("Harness health is not ready")
                self.store.event("harness_ready", {})
                return
            except (httpx.ConnectError, httpx.ConnectTimeout, FileNotFoundError):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                await asyncio.sleep(min(1, remaining))

    def queue_cycle(self, routine=False):
        for message in self.store.rows(
            "SELECT * FROM inbox WHERE state='pending' AND (? OR immediate=1) ORDER BY created_at", (routine,)
        ):
            self.store.create_execution("inbox", message["text"], inbox_id=message["id"])
        if routine:
            self.store.create_execution(
                "routine",
                "Review current research progress, system health, priorities, and next work. "
                "Keep this check short when everything is progressing normally.",
            )

    def scheduled_tick(self, instant=None):
        instant = instant or datetime.now(UTC)
        local = instant.astimezone(ZoneInfo(self.config.timezone))
        if local.hour not in self.config.hours or local.minute != 0:
            return False
        key = local.replace(minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
        if self.store.get("last_tick") == key:
            return False
        self.store.set("last_tick", key)
        busy = (self.agent and self.agent.execution["kind"] != "delegate") or self.store.rows(
            "SELECT id FROM executions WHERE state='queued' AND kind!='delegate' LIMIT 1"
        )
        if busy:
            self.store.event("tick_skipped", {"at": key, "reason": "supervisor cycle still active"})
            return False
        if self.store.get("enabled"):
            self.queue_cycle(routine=True)
            self.store.event("tick", {"at": key})
            return True
        return False

    def next_tick(self, instant=None):
        instant = instant or datetime.now(UTC)
        zone = ZoneInfo(self.config.timezone)
        local = instant.astimezone(zone)
        candidates = [
            datetime.combine(local.date() + timedelta(days=offset), day_time(hour), zone).astimezone(UTC)
            for offset in (0, 1, 2)
            for hour in self.config.hours
        ]
        return min(candidate for candidate in candidates if candidate > instant)

    async def calendar_loop(self):
        while not self.stopping:
            self.scheduled_tick()
            self.wake.set()
            await asyncio.sleep(max(0.01, (self.next_tick() - datetime.now(UTC)).total_seconds()))

    def pause_reason(self, agent):
        if self.stopping:
            return "daemon_shutdown"
        if not self.store.get("enabled"):
            return "operator_stop"
        if agent.execution["kind"] == "delegate":
            project = self.store.one("projects", agent.execution["project_id"])
            if project["held"] or project["status"] in ("paused", "ended"):
                return "project_hold"
            if agent.elapsed - agent.segment_start >= self.config.delegate_seconds:
                return "delegate_time_limit"
            if self.store.rows("SELECT id FROM executions WHERE state='queued' AND kind!='delegate' LIMIT 1"):
                return "supervision"
        return None

    async def acquire(self):
        health = await self.harness.health()
        active = health["active_projects"]
        if not active:
            return True
        self.phase = "waiting_to_pause"
        for backend_id in active:
            await self.harness.pause(backend_id, "The Supervisor is waiting for exclusive execution")
            known = self.store.rows("SELECT * FROM projects WHERE backend_id=?", (backend_id,))
            if not known:
                status = await self.harness.status(backend_id)
                known = [
                    self.store.create_project(status["project"]["name"], "harness", backend_id=backend_id)
                ]
            if self.store.get("next_project") is None and not self.store.get("selection_explicit", False):
                self.store.set("next_project", known[0]["id"])
        return False

    async def run_execution(self, execution):
        self.store.execution_state(execution["id"], "running")
        self.phase = "running"
        try:
            self.agent = self.agent_factory(self, execution)
            result = await self.agent.run()
            self.store.event("execution_result", {"text": result}, execution["id"])
            self.store.execution_state(execution["id"], "completed", self.agent.elapsed)
            if execution["kind"] == "delegate":
                self.store.update_project(execution["project_id"], {"status": "complete"})
                self.store.enqueue(
                    f"Delegate project {execution['project_id']} completed. Review execution "
                    f"{execution['id']} and its evidence.\n{result[:4000]}",
                    "system",
                    "completion",
                    True,
                )
                if self.store.get("next_project") == execution["project_id"]:
                    self.store.set("next_project", None)
        except Paused as error:
            elapsed = self.agent.elapsed if self.agent else execution["elapsed"]
            self.store.execution_state(execution["id"], "paused", elapsed, str(error))
            if execution["kind"] == "delegate" and str(error) in ("supervision", "delegate_time_limit"):
                if str(error) == "delegate_time_limit":
                    self.store.enqueue(
                        f"Delegate project {execution['project_id']} reached its review interval. "
                        f"Review progress in execution {execution['id']}; decide whether to resume, steer, or switch work.",
                        "system",
                        "delegate_review",
                        True,
                    )
        except asyncio.CancelledError:
            self.store.execution_state(
                execution["id"], "paused", error="Execution interrupted; verify tool effects"
            )
            raise
        except Exception as error:
            self.store.execution_state(
                execution["id"],
                "failed",
                self.agent.elapsed if self.agent else None,
                f"{type(error).__name__}: {error}",
            )
            self.store.alert(
                "execution_failed:" + execution["id"],
                f"Execution {execution['id']} failed: {type(error).__name__}: {error}. Operator action required.",
                True,
            )
        finally:
            self.agent = None
            self.phase = "idle"

    async def dispatch(self):
        if not self.store.get("enabled"):
            return
        selection = self.store.get("next_project")
        if not selection:
            return
        project = self.store.one("projects", selection)
        if project["held"] or project["status"] in ("complete", "ended"):
            return
        if project["backend"] == "delegate":
            previous = self.store.rows(
                "SELECT * FROM executions WHERE project_id=? AND kind='delegate' ORDER BY rowid DESC LIMIT 1",
                (selection,),
            )
            if previous and previous[0]["state"] == "paused":
                self.store.execution_state(previous[0]["id"], "queued")
            elif not previous:
                self.store.create_execution("delegate", project["instructions"], project_id=selection)
            self.store.update_project(selection, {"status": "running"})
            return
        status = await self.harness.status(project["backend_id"])
        phase = status["project"]["phase"]
        if phase == "complete":
            self.store.update_project(selection, {"status": "complete"})
            return
        if status["control"]["state"] in ("running", "waiting_to_pause"):
            if status["control"]["state"] == "running":
                self.store.set("operator_resume", None)
            return
        pause = status["control"]["pause_request"]
        grant = self.store.get("operator_resume")
        operator_resume = grant == {"project": selection, "pause_id": pause["id"] if pause else None}
        if phase == "paused" and (not pause or pause["actor"] == "operator") and not operator_resume:
            self.store.update_project(selection, {"held": 1, "status": "paused"})
            self.store.enqueue(
                f"Project {selection} has an operator/legacy hold; it was not resumed.",
                "system",
                "hold",
                fingerprint="hold:" + selection,
            )
            return
        self.store.set("dispatch_in_flight", {"project": selection, "backend_id": project["backend_id"]})
        await self.harness.start(
            project["backend_id"],
            phase == "paused",
            None if phase == "paused" else project["max_iterations"],
            actor="operator" if operator_resume else "supervisor",
        )
        self.store.set("operator_resume", None)
        self.store.set("dispatch_in_flight", None)
        self.store.set("running_harness", project["backend_id"])
        self.store.update_project(selection, {"status": "running"})

    async def monitor(self):
        health = await self.harness.health()
        listings = await self.harness.call("GET", "projects")
        statuses = {}
        for project in listings:
            item = project["id"]
            status = await self.harness.status(item)
            # Keep startup packets small; full history/artifacts remain accessible via the CLI/files.
            statuses[item] = {
                "name": project["name"],
                "phase": status["project"]["phase"],
                "control": status["control"],
                "model_usage": status["model_usage"],
            }
            cursor_key = "harness_cursor:" + item
            cursor = self.store.get(cursor_key, 0)
            events = await self.harness.call("GET", f"projects/{item}/events?after={cursor}&limit=200")
            for event in events:
                # Event receipts prevent duplicates after a crash between enqueue and cursor checkpoint.
                receipt = "harness_event:" + str(event["seq"])
                if event["at"] >= self.store.get("monitor_since", self.started_at):
                    if event["kind"] in ("project_completed", "run_stopped"):
                        data = event["data"] if "data" in event else event.get("data_json", {})
                        if isinstance(data, str):
                            data = json.loads(data)
                        if event["kind"] == "project_completed" or data.get("state") == "completed":
                            self.store.enqueue(
                                f"Harness {event['kind']} for project {item}. "
                                f"Inspect its status, results, and publications. Event: {json.dumps(data)}",
                                "system",
                                "completion",
                                True,
                                fingerprint="completion:" + item,
                                source_key=receipt,
                            )
                    elif event["kind"] in (
                        "model_prompt_cache_warning",
                        "model_output_truncated",
                        "operator_intervention_required",
                    ):
                        self.store.alert(
                            f"harness:{item}:{event['kind']}",
                            f"Harness event {event['kind']} for project {item}: {json.dumps(event)}",
                            critical=event["kind"] == "operator_intervention_required",
                            source_key=receipt,
                        )
                cursor = event["seq"]
            self.store.set(cursor_key, cursor)
        self.snapshot = {"health": health, "projects": statuses}
        for project in self.store.rows("SELECT * FROM projects WHERE backend='harness'"):
            observed = statuses.get(project["backend_id"])
            if not observed or project["status"] in ("complete", "ended"):
                continue
            if observed["phase"] == "complete":
                self.store.update_project(project["id"], {"status": "complete"})
            elif (
                observed["control"]["state"] in ("running", "waiting_to_pause")
                and project["status"] != "running"
            ):
                self.store.update_project(project["id"], {"status": "running"})
            elif project["status"] == "running" and observed["control"]["state"] == "paused":
                self.store.update_project(project["id"], {"status": "paused"})
            elif (
                project["status"] == "running"
                and (observed["control"].get("run") or {}).get("state") == "completed"
            ):
                self.store.update_project(project["id"], {"status": "pending"})
        write_json(self.store.root / "observations" / "harness.json", self.snapshot)
        # Host process summaries are produced outside the private shell PID namespace.
        process = await asyncio.create_subprocess_exec(
            "ps",
            "-eo",
            "pid,ppid,user,stat,etimes,pcpu,pmem,comm",
            "--sort=-pcpu",
            stdout=asyncio.subprocess.PIPE,
        )
        output, _ = await process.communicate()
        write_json(
            self.store.root / "observations" / "host.json",
            {"at": now(), "processes": output.decode(errors="replace").splitlines()[:50]},
        )
        if self.agent:
            agent = self.agent
            with self.store.db:
                self.store.db.execute("UPDATE executions SET elapsed=? WHERE id=?", (agent.elapsed, agent.id))
            if (
                agent.operation
                and time.monotonic() - agent.operation["started"] >= self.config.request_warning_seconds
            ):
                key = "long_operation:" + agent.id + ":" + str(agent.operation["started"])
                self.store.alert(
                    key,
                    f"Execution {agent.id} has spent over "
                    f"{self.config.request_warning_seconds / 60:.0f} minutes in {agent.operation['kind']}; "
                    "inspect progress and model timing.",
                    source_key=key,
                )

    async def step(self):
        await self.monitor()
        self.scheduled_tick()
        if not self.store.get("enabled"):
            backend_id = self.store.get("running_harness")
            if backend_id and backend_id in self.snapshot["health"]["active_projects"]:
                self.phase = "waiting_to_pause"
                await self.harness.pause(backend_id, "The Supervisor was stopped")
            elif not self.agent:
                self.phase = "idle"
            return
        self.queue_cycle()
        if self.task and not self.task.done():
            return
        if self.task:
            self.task.result()
            self.task = None
        queued = self.store.rows(
            "SELECT * FROM executions WHERE state='queued' "
            "ORDER BY CASE WHEN kind='delegate' THEN 1 ELSE 0 END, rowid LIMIT 1"
        )
        if queued:
            if await self.acquire():
                self.task = asyncio.create_task(self.run_execution(queued[0]))
        else:
            await self.dispatch()

    async def run(self):
        self.store.recover()
        if not self.store.get("monitor_since"):
            self.store.set("monitor_since", self.started_at)
        calendar = asyncio.create_task(self.calendar_loop())
        try:
            try:
                await self.wait_for_harness()
            except Exception as error:
                self.store.alert(
                    "infrastructure_failure",
                    f"Startup readiness failed: {type(error).__name__}: {error}",
                    True,
                )
            while not self.stopping:
                try:
                    await self.step()
                except Exception as error:
                    self.store.alert(
                        "infrastructure_failure",
                        f"Infrastructure failure: {type(error).__name__}: {error}",
                        True,
                    )
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=self.config.poll_seconds)
                except TimeoutError:
                    pass
                self.wake.clear()
        finally:
            calendar.cancel()
            await asyncio.gather(calendar, return_exceptions=True)
            if self.task:
                await self.task
            backend_id = self.store.get("running_harness")
            if backend_id:
                health = await self.harness.health()
                if backend_id in health["active_projects"]:
                    await self.harness.pause(backend_id, "Supervisor daemon shutdown")
            await self.harness.close()
