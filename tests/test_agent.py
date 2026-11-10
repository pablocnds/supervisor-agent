import json

import httpx
import pytest

from supervisor_agent.agent import BUILTINS, Agent, Paused
from supervisor_agent.config import write_json


def streamed(message, usage=None, finish="stop"):
    chunks = [{"choices": [{"delta": message, "finish_reason": finish}]}]
    if usage:
        chunks.append({"choices": [], "usage": usage})
    return httpx.Response(
        200, content="".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
    )


async def attach(agent, handler):
    await agent.client.aclose()
    agent.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://model")


@pytest.mark.asyncio
async def test_append_only_continuations_and_free_form_communications(runtime):
    store = runtime.store
    store.set("enabled", True)
    inbox = store.enqueue("A task")
    job = store.create_execution("inbox", "A task", inbox_id=inbox["id"])
    agent = Agent(runtime, job)
    runtime.agent = agent
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        requests.append(payload)
        if len(requests) == 1:
            with store.db:
                store.db.execute(
                    "INSERT INTO steering(execution_id,text,created_at) VALUES(?,?,?)",
                    (job["id"], "Stop after this message", "now"),
                )
            return streamed(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call1",
                            "type": "function",
                            "function": {
                                "name": "communicate",
                                "arguments": json.dumps({"markdown": "An arbitrary **Markdown** reply."}),
                            },
                        }
                    ]
                },
                {"prompt_tokens": 100, "completion_tokens": 10},
                "tool_calls",
            )
        return streamed(
            {"content": "Done"},
            {"prompt_tokens": 150, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 100}},
        )

    await attach(agent, handler)
    assert await agent.run() == "Done"
    assert requests[0]["cache_prompt"] is True
    assert requests[1]["messages"][: len(requests[0]["messages"])] == requests[0]["messages"]
    assert requests[1]["messages"][-1]["content"] == "Steering: Stop after this message"
    communications = store.rows("SELECT * FROM communications")
    assert communications[0]["execution_id"] == job["id"]
    assert communications[0]["request_id"] == inbox["id"]
    assert communications[0]["created_at"]
    assert not store.rows("SELECT * FROM inbox WHERE kind='alert'")


@pytest.mark.asyncio
async def test_global_stop_saves_tool_result_and_skips_rest_of_batch(runtime, monkeypatch):
    store = runtime.store
    store.set("enabled", True)
    agent = Agent(runtime, store.create_execution("routine", "Review"))
    runtime.agent = agent
    calls = []

    async def shell(command, timeout=None):
        calls.append(command)
        store.set("enabled", False)
        return {"exit_code": 0, "output": "saved evidence"}

    monkeypatch.setattr(agent.shell, "run", shell)

    def handler(request):
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        return streamed(
            {
                "tool_calls": [
                    {
                        "index": i,
                        "id": f"call{i}",
                        "type": "function",
                        "function": {"name": "shell", "arguments": json.dumps({"command": command})},
                    }
                    for i, command in enumerate(["first", "second"])
                ]
            },
            {"prompt_tokens": 100},
            "tool_calls",
        )

    await attach(agent, handler)
    with pytest.raises(Paused, match="operator_stop"):
        await agent.run()
    saved = json.loads(agent.path.read_text())
    assert calls == ["first"]
    results = [m for m in saved["messages"] if m["role"] == "tool"]
    assert "saved evidence" in results[0]["content"]
    assert "Not executed" in results[1]["content"]


@pytest.mark.asyncio
async def test_cache_failure_alerts_and_missing_measurements_differ(runtime):
    runtime.store.set("enabled", True)
    agent = Agent(runtime, runtime.store.create_execution("routine", "Review"))
    agent.session = {
        "prompt": "identity",
        "messages": [],
        "tools": [],
        "previous_input": 100,
        "cache_reset": None,
    }
    await attach(
        agent,
        lambda request: streamed(
            {"content": "Done"},
            {"prompt_tokens": 150, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 0}},
        ),
    )
    await agent.complete()
    assert runtime.store.rows("SELECT origin FROM inbox WHERE kind='alert'")[0]["origin"] == "system"
    await agent.client.aclose()


@pytest.mark.asyncio
async def test_compaction_preserves_tool_batch_and_receipts(runtime):
    runtime.store.set("enabled", True)
    agent = Agent(runtime, runtime.store.create_execution("routine", "Review"))
    messages = [{"role": "user", "content": str(i)} for i in range(6)]
    messages += [
        {"role": "assistant", "tool_calls": [{"id": "c", "function": {"name": "shell", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c", "content": "result"},
        *[{"role": "user", "content": "Continue"} for _ in range(6)],
    ]
    agent.session = {
        "prompt": "identity",
        "messages": messages,
        "tools": [],
        "previous_input": 200,
        "cache_reset": None,
        "delivered": [7],
    }

    def handler(request):
        payload = json.loads(request.content)
        if request.url.path.endswith("input_tokens"):
            large = any(m.get("content") == "0" for m in payload["messages"])
            return httpx.Response(200, json={"input_tokens": 100000 if large else 100})
        assert payload["messages"][:-1] == [{"role": "system", "content": "identity"}, *messages]
        assert payload["tools"] == []
        assert payload["tool_choice"] == "none"
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "Findings and open work"}}]},
        )

    await attach(agent, handler)
    await agent.compact()
    assert agent.session["cache_reset"] == "compaction"
    assert agent.session["previous_input"] is None
    assert agent.session["delivered"] == [7]
    assert agent.session["messages"][1]["role"] == "assistant"
    assert agent.session["messages"][2]["tool_call_id"] == "c"
    await agent.client.aclose()


@pytest.mark.asyncio
async def test_resume_retains_prefix_and_marks_uncertain_tool_effects(runtime):
    job = runtime.store.create_execution("routine", "Review")
    path = runtime.store.root / "executions" / job["id"] / "session.json"
    write_json(
        path,
        {
            "prompt": "frozen identity",
            "model": runtime.config.model.model_dump(mode="json"),
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "pending",
                            "function": {"name": "shell", "arguments": '{"command":"side effect"}'},
                        }
                    ],
                }
            ],
            "tools": [],
            "previous_input": 100,
            "cache_reset": None,
            "delivered": [3],
        },
    )
    agent = Agent(runtime, job)
    agent.close_interrupted_calls()
    assert agent.session["prompt"] == "frozen identity"
    assert "outcome unknown" in agent.session["messages"][-1]["content"]
    assert agent.session["delivered"] == [3]
    await agent.client.aclose()


@pytest.mark.asyncio
async def test_overdue_reminder_survives_pause_without_duplicate_delivery(runtime):
    job = runtime.store.create_execution("routine", "Review")
    job["elapsed"] = 1900
    path = runtime.store.root / "executions" / job["id"] / "session.json"
    write_json(
        path,
        {
            "prompt": "identity",
            "model": runtime.config.model.model_dump(mode="json"),
            "messages": [],
            "tools": [],
            "delivered": [],
            "last_reminder": 0,
        },
    )
    agent = Agent(runtime, job)
    agent.deliver()
    assert len(agent.session["messages"]) == 1
    assert "31.7 minutes" in agent.session["messages"][0]["content"]
    await agent.client.aclose()
    resumed = Agent(runtime, job)
    resumed.deliver()
    assert len(resumed.session["messages"]) == 1
    await resumed.client.aclose()


@pytest.mark.asyncio
async def test_model_failure_stops_dispatch_and_records_operator_alert(runtime):
    runtime.store.set("enabled", True)
    job = runtime.store.create_execution("routine", "Review")

    class FailedModelAgent(Agent):
        async def run(self):
            await attach(self, lambda request: httpx.Response(503, json={"error": "unavailable"}))
            return await super().run()

    runtime.agent_factory = FailedModelAgent
    await runtime.run_execution(job)
    assert not runtime.store.get("enabled")
    assert runtime.store.one("executions", job["id"])["state"] == "failed"
    alert = runtime.store.rows("SELECT * FROM inbox WHERE kind='alert'")[0]
    assert alert["origin"] == "system"
    assert "Operator action required" in alert["text"]


@pytest.mark.asyncio
async def test_resume_keeps_frozen_tool_definitions_when_metadata_changes(runtime):
    runtime.store.set("enabled", True)
    job = runtime.store.create_execution("routine", "Review")
    tools = json.loads(json.dumps(BUILTINS))
    tools[0]["function"]["description"] = "Original shell description"
    path = runtime.store.root / "executions" / job["id"] / "session.json"
    write_json(
        path,
        {
            "prompt": "identity",
            "model": runtime.config.model.model_dump(mode="json"),
            "messages": [{"role": "user", "content": "Task"}],
            "tools": tools,
            "delivered": [],
            "previous_input": None,
            "cache_reset": "new_execution",
        },
    )
    agent = Agent(runtime, job)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        assert body["tools"] == tools
        requests.append(body)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        return streamed({"content": "Done"}, {"prompt_tokens": 100})

    await attach(agent, handler)
    assert await agent.run() == "Done"
    assert requests
    assert agent.session["tools"] == tools
    assert any(event["kind"] == "tool_metadata_changed" for event in runtime.store.events())
