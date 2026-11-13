from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from supervisor_agent.alerts import HandoffCache
from supervisor_agent.api import app
from supervisor_agent.store import now


@pytest.mark.asyncio
async def test_harness_failure_parks_once_and_requires_explicit_resume(runtime):
    status = runtime.harness.add(actor="harness")
    status["control"]["pause_request"]["reason"] = "Write-up grace exhausted"
    project = runtime.store.create_project("Study", "harness", backend_id="h1")
    runtime.store.set("enabled", True)
    runtime.store.set("next_project", project["id"])
    for _ in range(5):
        await runtime.dispatch()
    assert not runtime.harness.starts
    assert runtime.store.get("next_project") is None
    inbox = runtime.store.rows("SELECT * FROM inbox")
    assert len(inbox) == 1 and inbox[0]["immediate"]
    # Monitoring and even a mistaken re-selection must not duplicate the same incident.
    runtime.harness.feed["h1"] = [
        {
            "seq": 1,
            "at": now(),
            "kind": "project_paused",
            "data": {"actor": "harness", "request_id": "pause1", "reason": "Write-up grace exhausted"},
        }
    ]
    await runtime.monitor()
    runtime.store.set("next_project", project["id"])
    await runtime.dispatch()
    assert len(runtime.store.rows("SELECT * FROM inbox")) == 1
    job = runtime.store.create_execution("inbox", "Review")
    runtime.store.execution_state(job["id"], "running")
    runtime.agent = SimpleNamespace(id=job["id"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)),
        base_url="http://test",
        headers={"x-supervisor-execution": job["id"]},
    ) as client:
        response = await client.post("/v1/action", json={"operation": "project_resume", "id": project["id"]})
        assert response.status_code == 200
    await runtime.dispatch()
    assert len(runtime.harness.starts) == 1
    # The authorization cannot release a different, later pause.
    runtime.harness.projects["h1"]["control"]["pause_request"]["id"] = "new-pause"
    await runtime.dispatch()
    assert len(runtime.harness.starts) == 1


@pytest.mark.asyncio
async def test_duplicate_notes_do_not_hide_current_notebooks(runtime):
    for name in ["aaa", "improvements", "operations", "operations.md", "improvements.md"]:
        runtime.store.note_path(name).write_text(name + "\n" + "x" * 4000)
    job = runtime.store.create_execution("routine", "Review")
    packet = await runtime.start_context(job)
    assert [n["name"] for n in packet["environment_notes"][:2]] == ["operations.md", "improvements.md"]
    assert len(packet["environment_note_index"]) == 5
    assert sum(len(n["excerpt"]) for n in packet["environment_notes"]) <= 6000


def events(at):
    def event(seq, kind, **data):
        return {"seq": seq, "at": at, "kind": kind, "data": data}

    return [
        event(1, "model_request_started", request_id="cold", model="test"),
        event(
            2,
            "model_prompt_cache_warning",
            request_id="cold",
            role="iteration",
            reason="no_cached_prefix",
            cached_input_tokens=0,
            expected_prefix_tokens=40000,
        ),
        event(3, "model_request_started", request_id="warm"),
        event(
            4,
            "model_request_finished",
            request_id="warm",
            role="iteration",
            request_kind="agent",
            ok=True,
            cached_input_tokens=41000,
        ),
    ]


def test_handoff_warning_requires_our_marker_and_proven_warm_recovery(store):
    cache = HandoffCache(store, 1800)
    at = now()
    feed = events(at)
    assert cache.observe("h1", feed[1]) is False  # An uncorrelated cold request stays an alert.
    cache.begin("h1", at, "test")
    for event in feed:
        accounted = cache.observe("h1", event)
        if event["kind"] == "model_prompt_cache_warning":
            assert accounted
    assert not store.rows("SELECT * FROM inbox")
    assert any(e["kind"] == "cache_handoff_recovered" for e in store.events())
    assert cache.observe("h1", feed[1]) is True  # Cursor replay does not resurrect it.
    # A later mid-session warning is still investigated.
    later = {**feed[1], "seq": 5, "data": {**feed[1]["data"], "request_id": "later"}}
    assert cache.observe("h1", later) is False


@pytest.mark.parametrize("ending", ["cold", "failed", "stopped", "timeout"])
def test_unverified_handoff_miss_is_alerted_once(store, ending):
    cache = HandoffCache(store, 1800)
    at = now()
    feed = events(at)
    cache.begin("h1", at, "test")
    for event in feed[:3]:
        cache.observe("h1", event)
    if ending == "timeout":
        cache.expire("h1", datetime.fromisoformat(at) + timedelta(seconds=1801))
    elif ending == "stopped":
        cache.observe("h1", {"seq": 4, "at": at, "kind": "controller_stopped", "data": {}})
    else:
        event = feed[-1]
        event["data"]["cached_input_tokens"] = 0
        event["data"]["ok"] = ending != "failed"
        cache.observe("h1", event)
    cache.flush("h1")
    assert len(store.rows("SELECT * FROM inbox")) == 1


@pytest.mark.asyncio
async def test_quiet_routine_finishes_without_publishing_or_requiring_alert_resolution(runtime):
    message = runtime.store.alert("known", "Review recovered incident")
    job = runtime.store.create_execution("inbox", message["text"], inbox_id=message["id"])

    class QuietAgent:
        def __init__(self, owner, execution):
            self.id, self.elapsed = execution["id"], 1

        async def run(self):
            return "Healthy; no change."

    runtime.agent_factory = QuietAgent
    await runtime.run_execution(job)
    assert runtime.store.one("inbox", message["id"])["state"] == "handled"
    assert not runtime.store.rows("SELECT * FROM communications")


def test_cache_handoff_does_not_hide_a_miss_for_a_different_model(store):
    cache = HandoffCache(store, 300)
    at = now()
    cache.begin("h1", at, "other-profile")
    feed = events(at)
    cache.observe("h1", feed[0])
    assert cache.observe("h1", feed[1]) is False


def test_notebook_consolidation_is_archived_retryable_and_keeps_unknown_history(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "review_fix_deploy", Path(__file__).resolve().parents[1] / "deploy/prepare-review-fixes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    notes, archive = tmp_path / "notes", tmp_path / "private"
    notes.mkdir()
    (notes / "operations").write_text("old duplicate")
    (notes / "operations.md").write_text("old current")
    (notes / "extra.md").write_text("unique historical evidence")
    saved = {}

    def write(kind, item, name, text):
        if kind == "environment":
            (notes / name).write_text(text)
        else:
            saved[name] = text

    module.consolidate(notes, archive, write)
    module.consolidate(notes, archive, write)
    assert (archive / "extra.md").read_text() == "unique historical evidence"
    assert saved["review-2026-11-13-extra.md"] == "unique historical evidence"
    assert sorted(p.name for p in notes.iterdir()) == ["improvements.md", "operations.md"]
    assert all(p.stat().st_size < 2000 for p in notes.iterdir())
