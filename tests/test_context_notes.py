import json

import httpx
import pytest

from supervisor_agent.api import app
from supervisor_agent.cli import parser, request_from
from supervisor_agent.context import changes_since, harness_brief
from supervisor_agent.shell import Shell


@pytest.mark.asyncio
async def test_environment_notes_are_durable_freeform_and_available_to_user(runtime, tmp_path):
    note = tmp_path / "finding.md"
    note.write_text("# Investigating latency\nEvidence and follow-up in my own format.")
    args = parser().parse_args(["note", "environment", "--file", str(note), "--name", "latency.md"])
    method, path, body = request_from(args)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)), base_url="http://test"
    ) as client:
        result = await client.request(method, "/v1/" + path, json=body)
        assert result.status_code == 200
        read = await client.get("/v1/notes/latency.md")
        assert read.text == note.read_text() + "\n"
        listing = (await client.get("/v1/notes")).json()
        assert any(r["name"] == "latency.md" and r["updated_at"] for r in listing)
        assert (await client.get("/v1/notes/missing.md")).status_code == 404
        result = await client.post(
            "/v1/action", json={**body, "append": False, "text": "Resolved; evidence retained."}
        )
        assert result.status_code == 200
        assert (await client.get("/v1/notes/latency.md")).text == "Resolved; evidence retained.\n"
    assert runtime.store.note_path("latency.md").read_text().startswith("Resolved")


@pytest.mark.asyncio
async def test_startup_packet_has_delta_known_findings_recent_replies_and_id_mapping(runtime):
    runtime.harness.add(phase="paused")
    runtime.harness.add("unregistered", phase="paused")
    runtime.harness.projects["unregistered"]["model_usage"] = {"sessions": ["large old history"] * 10000}
    project = runtime.store.create_project("Study", "harness", backend_id="h1")
    await runtime.monitor()
    before = runtime.brief_observation()
    runtime.store.set(
        "last_review",
        {"execution_id": "prior", "finished_at": "then", "result": "No changes", "harness": before},
    )
    runtime.store.communicate("Already asked whether to register the old projects.")
    message = runtime.store.enqueue("Unique original user notes")
    job = runtime.store.create_execution("inbox", message["text"], inbox_id=message["id"])
    packet = await runtime.start_context(job)
    encoded = json.dumps(packet)
    assert encoded.count("Unique original user notes") == 1
    assert "large old history" not in encoded
    assert packet["catalog"][0]["backend_id"] == "h1"
    assert packet["catalog"][0]["id"] == project["id"]
    assert packet["recent_communications"][0]["excerpt"].startswith("Already asked")
    assert packet["environment_notes"]
    assert packet["changes_since_last_review"]["changed_projects"] == []
    current = json.loads(json.dumps(before))
    current["projects"]["h1"]["phase"] = "complete"
    assert changes_since({"harness": before}, current)["changed_projects"] == ["h1"]
    assert harness_brief(runtime.snapshot, {"h1"}) == before


@pytest.mark.asyncio
async def test_filtered_shell_failure_is_not_hidden(runtime, tmp_path):
    shell = Shell(runtime.config, "pipeline", tmp_path / "workspace")
    result = await shell.run("printf 'bad option\\n' >&2; (exit 2) | cat", timeout=5)
    assert result["exit_code"] == 2
    # Regular shell sequencing remains available; no errexit is imposed.
    result = await shell.run("false; printf recovered", timeout=5)
    assert result["exit_code"] == 0 and result["output"] == "recovered"


@pytest.mark.asyncio
async def test_early_finding_and_communication_survive_later_execution_failure(runtime):
    store = runtime.store
    message = store.enqueue("Check a suspected regression")
    job = store.create_execution("inbox", message["text"], inbox_id=message["id"])

    class FailingInvestigation:
        def __init__(self, owner, execution):
            self.id, self.execution = execution["id"], execution
            self.elapsed = 1

        async def run(self):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app(runtime)),
                base_url="http://test",
                headers={"x-supervisor-execution": self.id},
            ) as client:
                for body in (
                    {
                        "operation": "note",
                        "kind": "environment",
                        "name": "new-finding.md",
                        "text": "Confirmed defect; evidence at /artifacts/example; investigation remains open.",
                    },
                    {
                        "operation": "communicate",
                        "markdown": "A confirmed defect needs attention; evidence is recorded.",
                    },
                ):
                    response = await client.post("/v1/action", json=body)
                    assert response.status_code == 200
            raise RuntimeError("Later model failure")

    runtime.agent_factory = FailingInvestigation
    await runtime.run_execution(job)
    assert store.one("executions", job["id"])["state"] == "failed"
    assert "Confirmed defect" in store.note_path("new-finding.md").read_text()
    reply = store.rows("SELECT * FROM communications")[0]
    assert reply["request_id"] == message["id"]
    assert reply["created_at"]
