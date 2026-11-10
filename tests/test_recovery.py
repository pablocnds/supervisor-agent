import copy
import json

import httpx
import pytest

from supervisor_agent.agent import Agent
from supervisor_agent.api import app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,finish", [(None, "length"), ("", "stop"), ("  ", "stop"), ("partial", "length")]
)
async def test_bad_compaction_preserves_history_and_diagnostics(runtime, content, finish):
    runtime.store.set("enabled", True)
    agent = Agent(runtime, runtime.store.create_execution("routine", "Review"))
    agent.model.extra = {"chat_template_kwargs": {"preserve_thinking": False}}
    agent.session = {
        "prompt": "identity",
        "tools": [],
        "messages": [{"role": "user", "content": f"fact {i}"} for i in range(20)],
        "previous_input": 95000,
        "cache_reset": None,
        "delivered": [2],
    }
    original = copy.deepcopy(agent.session)
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(
                200, json={"input_tokens": 1000 if payload.get("tool_choice") == "none" else 100000}
            )
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": finish,
                        "message": {"content": content, "reasoning_content": "reasoning"},
                    }
                ],
                "usage": {"completion_tokens": 4096},
            },
        )

    await agent.client.aclose()
    agent.client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="http://model")
    try:
        with pytest.raises(RuntimeError, match="history preserved"):
            await agent.compact()
        assert agent.session == original
        assert len(requests) == 1
        assert requests[0]["reasoning_effort"] == "none"
        assert requests[0]["chat_template_kwargs"]["enable_thinking"] is False
        assert requests[0]["chat_template_kwargs"]["preserve_thinking"] is False
        assert requests[0]["messages"][:-1] == [
            {"role": "system", "content": "identity"},
            *original["messages"],
        ]
        assert requests[0]["tools"] == original["tools"]
        backup = next((agent.directory / "compactions").glob("*.json"))
        assert json.loads(backup.read_text()) == original
        event = next(e for e in runtime.store.events() if e["kind"] == "compaction_finished")
        assert event["data"]["ok"] is False
        assert event["data"]["finish_reason"] == finish
        assert event["data"]["reasoning_characters"] == 9
    finally:
        await agent.client.aclose()


@pytest.mark.asyncio
async def test_startup_waits_only_for_transient_connections(runtime, monkeypatch):
    calls = 0

    async def health():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("socket starting")
        return {"ok": True}

    async def no_delay(_):
        pass

    monkeypatch.setattr(runtime.harness, "health", health)
    monkeypatch.setattr("supervisor_agent.runtime.asyncio.sleep", no_delay)
    await runtime.wait_for_harness()
    assert calls == 3
    assert not runtime.store.rows("SELECT * FROM inbox")
    runtime.config.startup_timeout_seconds = 0
    calls = 0
    with pytest.raises(httpx.ConnectError):
        await runtime.wait_for_harness()
    assert calls == 1


@pytest.mark.asyncio
async def test_startup_timeout_disables_dispatch(runtime, monkeypatch):
    runtime.config.startup_timeout_seconds = 0
    runtime.store.set("enabled", True)

    async def unavailable():
        raise httpx.ConnectError("harness unavailable")

    async def inspect_and_exit():
        assert not runtime.store.get("enabled")
        assert "Startup readiness failed" in runtime.store.get("critical_failure")
        runtime.stopping = True
        runtime.wake.set()

    monkeypatch.setattr(runtime.harness, "health", unavailable)
    monkeypatch.setattr(runtime, "step", inspect_and_exit)
    await runtime.run()
    assert len(runtime.store.rows("SELECT * FROM inbox WHERE kind='alert'")) == 1


@pytest.mark.asyncio
async def test_intervention_stops_dispatch_and_reconciles_state_without_clearing_holds(runtime):
    store = runtime.store
    runtime.harness.add(phase="paused")
    project = store.create_project("Study", "harness", backend_id="h1")
    store.update_project(project["id"], {"status": "running", "held": 1})
    store.set("enabled", True)
    runtime.harness.feed["h1"] = [
        {
            "seq": 1,
            "at": "9999",
            "kind": "operator_intervention_required",
            "data": {"source": "compaction"},
        }
    ]
    await runtime.step()
    assert not store.get("enabled")
    assert not runtime.harness.starts
    current = store.one("projects", project["id"])
    assert current["held"] == 1
    assert current["status"] == "paused"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)), base_url="http://test"
    ) as client:
        listed = (await client.get("/v1/projects")).json()[0]
        assert listed["execution"]["state"] == "paused"
        assert "compaction" in listed["execution"]["blocked_by"]


@pytest.mark.asyncio
async def test_resolving_alert_cancels_queued_investigation_but_does_not_enable(runtime):
    store = runtime.store
    alert = store.alert("startup", "connection refused", critical=True)
    job = store.create_execution("inbox", alert["text"], inbox_id=alert["id"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)), base_url="http://test"
    ) as client:
        result = await client.post(
            "/v1/action",
            json={
                "operation": "alert_resolve",
                "id": alert["id"],
                "resolution": "Readiness verified",
            },
        )
        assert result.status_code == 200
        assert result.json()["state"] == "resolved"
    assert store.one("executions", job["id"])["state"] == "cancelled"
    assert not store.get("enabled")
    assert store.get("critical_failure") is None
    runtime.queue_cycle(routine=True)
    assert len(store.rows("SELECT * FROM executions WHERE kind='inbox'")) == 1
    store.alert("startup", "new failure")
    assert len(store.rows("SELECT * FROM inbox")) == 2


def test_active_alert_investigation_cannot_be_resolved(runtime):
    alert = runtime.store.alert("cache", "cache miss")
    job = runtime.store.create_execution("inbox", "Inspect", inbox_id=alert["id"])
    runtime.store.execution_state(job["id"], "running")
    with pytest.raises(ValueError, match="active investigation"):
        runtime.store.resolve_alert(alert["id"], "Not resolved yet")


def test_resolving_old_alert_does_not_acknowledge_new_critical_failure(runtime):
    store = runtime.store
    old = store.alert("old", "Earlier failure", critical=True)
    current = store.alert("current", "Current failure", critical=True)
    store.resolve_alert(old["id"], "Earlier incident fixed")
    assert store.get("critical_failure") == "Current failure"
    store.set("critical_failure_alert_id", None)  # Legacy persisted state.
    store.resolve_alert(current["id"], "Current incident fixed")
    assert store.get("critical_failure") is None
    assert not store.get("enabled")


@pytest.mark.asyncio
async def test_failed_execution_can_receive_corrections_without_resuming(runtime):
    job = runtime.store.create_execution("routine", "Review")
    runtime.store.execution_state(job["id"], "failed", error="summary failed")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)), base_url="http://test"
    ) as client:
        result = await client.post(
            "/v1/action",
            json={
                "operation": "steer",
                "execution_id": job["id"],
                "text": "Corrected evidence is in the project note",
            },
        )
    assert result.status_code == 200
    assert runtime.store.one("executions", job["id"])["state"] == "failed"
    assert not runtime.store.get("enabled")
