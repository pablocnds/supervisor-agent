import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from supervisor_agent.agent import Paused
from supervisor_agent.api import app
from supervisor_agent.store import now


@pytest.mark.asyncio
async def test_check_waits_for_harness_acknowledgement(runtime):
    store = runtime.store
    runtime.harness.add(phase="executing")
    runtime.harness.active = ["h1"]
    store.set("enabled", True)
    store.enqueue("Inspect progress", immediate=True)
    await runtime.step()
    assert runtime.phase == "waiting_to_pause"
    assert runtime.task is None
    assert runtime.harness.pauses
    assert not runtime.harness.starts
    assert store.get("next_project")
    runtime.harness.active = []
    runtime.harness.projects["h1"]["project"]["phase"] = "paused"

    class FakeAgent:
        def __init__(self, owner, execution):
            self.id = execution["id"]
            self.elapsed = 1

        async def run(self):
            assert not runtime.harness.active
            return "Reviewed"

    runtime.agent_factory = FakeAgent
    await runtime.step()
    await runtime.task
    assert store.rows("SELECT state FROM executions")[0]["state"] == "completed"
    assert not runtime.harness.starts
    await runtime.step()
    assert runtime.harness.starts == [("h1", True, None)]


def test_each_inbox_item_and_routine_are_separate_and_ticks_skip(runtime):
    store = runtime.store
    store.set("enabled", True)
    store.enqueue("Idea one")
    store.enqueue("Idea two")
    store.alert("cache", "Cache failure")
    store.alert("cache", "Cache failure again")
    assert runtime.scheduled_tick(datetime(2026, 11, 10, 4, tzinfo=UTC))
    jobs = store.rows("SELECT * FROM executions ORDER BY rowid")
    assert [j["kind"] for j in jobs] == ["inbox", "inbox", "inbox", "routine"]
    assert store.rows("SELECT * FROM inbox WHERE kind='alert'")[0]["occurrences"] == 2
    assert not runtime.scheduled_tick(datetime(2026, 11, 10, 4, 0, 30, tzinfo=UTC))
    assert not runtime.scheduled_tick(datetime(2026, 11, 10, 8, tzinfo=UTC))
    assert len(store.rows("SELECT * FROM executions")) == 4
    assert store.events()[-1]["kind"] == "tick_skipped"
    runtime.config.hours = [0, 8, 16]
    assert not runtime.scheduled_tick(datetime(2026, 11, 11, 4, tzinfo=UTC))
    assert runtime.next_tick(datetime(2026, 11, 10, 1, tzinfo=UTC)) == datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_operator_and_legacy_holds_are_never_resumed(runtime):
    store = runtime.store
    runtime.harness.add(actor="operator")
    project = store.create_project("Study", "harness", backend_id="h1")
    store.set("enabled", True)
    store.set("next_project", project["id"])
    await runtime.dispatch()
    assert not runtime.harness.starts
    assert store.one("projects", project["id"])["held"]
    assert store.rows("SELECT * FROM inbox")[0]["kind"] == "hold"


@pytest.mark.asyncio
async def test_delegate_time_boundary_saves_then_requests_review(runtime):
    store = runtime.store
    line = store.create_line("Environment", meta=True)
    project = store.create_project("Inspect speed", "delegate", "Investigate", line["id"])
    store.set("enabled", True)
    store.set("next_project", project["id"])
    store.update_project(project["id"], {"status": "running"})
    execution = store.create_execution("delegate", "Investigate", project["id"])

    class TimedAgent:
        def __init__(self, owner, job):
            self.id = job["id"]
            self.execution = job
            self.elapsed = runtime.config.delegate_seconds + 1
            self.segment_start = 0

        async def run(self):
            reason = runtime.pause_reason(self)
            assert reason == "delegate_time_limit"
            raise Paused(reason)

    runtime.agent_factory = TimedAgent
    await runtime.run_execution(execution)
    saved = store.one("executions", execution["id"])
    assert saved["state"] == "paused"
    assert saved["elapsed"] == runtime.config.delegate_seconds + 1
    assert store.rows("SELECT * FROM inbox")[0]["immediate"]
    runtime.queue_cycle()
    assert store.rows("SELECT * FROM executions WHERE state='queued'")[0]["kind"] == "inbox"


@pytest.mark.asyncio
async def test_global_stop_prevents_dispatch_and_requests_safe_pause(runtime):
    store = runtime.store
    runtime.harness.add(phase="executing")
    runtime.harness.active = ["h1"]
    store.set("running_harness", "h1")
    store.set("enabled", False)
    await runtime.step()
    assert runtime.harness.pauses
    assert runtime.status()["waiting_to_pause"]
    assert not runtime.harness.starts


@pytest.mark.asyncio
async def test_completion_and_cache_events_are_consumed_once(runtime):
    store = runtime.store
    runtime.harness.add(phase="ready")
    runtime.harness.feed["h1"] = [
        {"seq": 1, "at": now(), "kind": "run_stopped", "data": {"state": "completed"}},
        {"seq": 2, "at": now(), "kind": "model_prompt_cache_warning", "data": {}},
        {"seq": 3, "at": now(), "kind": "model_prompt_cache_warning", "data": {}},
    ]
    await runtime.monitor()
    assert len(store.rows("SELECT * FROM inbox")) == 2
    assert store.rows("SELECT occurrences FROM inbox WHERE kind='alert'")[0]["occurrences"] == 2
    store.set("harness_cursor:h1", 0)  # Crash/retry before the cursor checkpoint.
    await runtime.monitor()
    assert len(store.rows("SELECT * FROM inbox")) == 2
    assert store.rows("SELECT occurrences FROM inbox WHERE kind='alert'")[0]["occurrences"] == 2


def test_unclean_recovery_stops_dispatch_without_replaying_tools(runtime):
    store = runtime.store
    job = store.create_execution("inbox", "Investigate")
    store.execution_state(job["id"], "running")
    store.set("enabled", True)
    store.recover()
    assert not store.get("enabled")
    assert store.one("executions", job["id"])["state"] == "paused"
    assert store.rows("SELECT * FROM inbox")[0]["origin"] == "system"


@pytest.mark.asyncio
async def test_operator_resume_is_deferred_and_bound_to_specific_hold(runtime):
    store = runtime.store
    runtime.harness.add(actor="operator")
    project = store.create_project("Study", "harness", backend_id="h1")
    store.update_project(project["id"], {"status": "paused", "held": 1})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)), base_url="http://test"
    ) as client:
        response = await client.post("/v1/action", json={"operation": "project_resume", "id": project["id"]})
        assert response.status_code == 200
    assert not runtime.harness.starts
    store.set("enabled", True)
    await runtime.dispatch()
    assert runtime.harness.starts == [("h1", True, None)]
    assert runtime.harness.start_actors == ["operator"]
    assert store.get("operator_resume") is None
    # A new operator hold cannot be released by a stale earlier resume request.
    runtime.harness.projects["h1"]["control"]["pause_request"]["id"] = "new-hold"
    store.set("operator_resume", {"project": project["id"], "pause_id": "pause1"})
    await runtime.dispatch()
    assert len(runtime.harness.starts) == 1


@pytest.mark.asyncio
async def test_no_overlap_between_inbox_items(runtime):
    runtime.store.set("enabled", True)
    runtime.store.enqueue("One", immediate=True)
    runtime.store.enqueue("Two", immediate=True)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class SlowAgent:
        def __init__(self, owner, execution):
            self.id, self.execution = execution["id"], execution
            self.elapsed, self.operation = 0, None

        async def run(self):
            calls.append(self.id)
            entered.set()
            await release.wait()
            return "Done"

    runtime.agent_factory = SlowAgent
    await runtime.step()
    await entered.wait()
    await runtime.step()
    assert len(calls) == 1
    release.set()
    await runtime.task
    await runtime.step()
    await runtime.task
    assert len(calls) == 2
