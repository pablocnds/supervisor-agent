import httpx
import pytest

from supervisor_agent.api import app
from supervisor_agent.cli import parser, request_from
from supervisor_agent.shell import Shell


@pytest.mark.asyncio
async def test_catalog_messages_notes_communications_and_user_holds(runtime, tmp_path):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)), base_url="http://test"
    ) as client:

        async def action(operation, **values):
            response = await client.post("/v1/action", json={"operation": operation, **values})
            assert response.is_success, response.text
            return response.json()

        line = await action("line_create", name="Environment", meta=True)
        project = await action(
            "project_create",
            name="Investigate",
            backend="delegate",
            line_id=line["id"],
            instructions="Measure inference speed",
        )
        await action("select", project_id=project["id"])
        assert runtime.store.get("next_project") == project["id"]
        message = await action("message", text="Unstructured notes", immediate=True)
        assert message["origin"] == "operator"
        note = await action("note", kind="project", id=project["id"], text="# Findings", name="findings.md")
        assert "research/projects" in note["path"]
        bad_note = await client.post(
            "/v1/action",
            json={
                "operation": "note",
                "kind": "project",
                "id": project["id"],
                "name": "../outside",
                "text": "bad",
            },
        )
        assert bad_note.status_code == 400
        communication = await action(
            "communicate", markdown="A free-form **reply**.", request_id=message["id"]
        )
        markdown = await client.get(f"/v1/communications/{communication['id']}/markdown")
        assert markdown.text == "A free-form **reply**."
        assert communication["created_at"]
        await action("project_pause", id=project["id"])
        assert runtime.store.one("projects", project["id"])["held"]
        assert runtime.store.get("next_project") is None
        unknown = await client.post(
            "/v1/action", json={"operation": "project_create", "name": "bad", "backend": "delegate"}
        )
        assert unknown.status_code == 400


def test_cli_builds_small_explicit_requests(tmp_path):
    p = parser()
    method, path, data = request_from(p.parse_args(["message", "Notes", "--now"]))
    assert (method, path, data["operation"], data["immediate"]) == ("POST", "action", "message", True)
    assert request_from(p.parse_args(["select", "idle"]))[2]["project_id"] is None
    assert request_from(p.parse_args(["update", "project", "id", '{"priority":10}']))[2]["values"] == {
        "priority": 10
    }


@pytest.mark.asyncio
async def test_real_sandbox_read_only_host_writable_workspace_and_no_network(config, tmp_path):
    workspace = config.state_root / "executions" / "test" / "workspace"
    sandbox = Shell(config, "test", workspace)
    secret = config.state_root / "host-file"
    secret.write_text("readable artifact")
    command = (
        f"cat {secret}; ! touch {config.state_root}/outside; printf evidence > result; "
        f"test ! -s {config.model.key_file}; "
        "python3 -c 'import socket; socket.create_connection((\"1.1.1.1\",443),1)' 2>/dev/null; "
        "test $? -ne 0"
    )
    result = await sandbox.run(command, timeout=10)
    assert result["exit_code"] == 0, result
    assert "readable artifact" in result["output"]
    assert (workspace / "result").read_text() == "evidence"
    assert not (tmp_path / "outside").exists()


@pytest.mark.asyncio
async def test_pool_proxy_rejects_service_mutations(runtime):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)), base_url="http://test"
    ) as client:
        result = await client.post("/pool/control/models", json={"id": "forbidden"})
        assert result.status_code == 409


def test_meta_project_boundary_and_alert_receipt_deduplication(store):
    ordinary = store.create_line("Ordinary research")
    with pytest.raises(ValueError, match="meta-research"):
        store.create_project("Investigation", "delegate", line_id=ordinary["id"])
    first = store.alert("cache", "first", source_key="event1")
    investigation = store.create_execution("inbox", "Investigate", inbox_id=first["id"])
    repeated = store.alert("cache", "first", source_key="event1")
    assert repeated["id"] == first["id"]
    assert len(store.rows("SELECT * FROM inbox")) == 1
    store.execution_state(investigation["id"], "completed")
    second = store.alert("cache", "another occurrence", source_key="event2")
    assert second["id"] != first["id"]


@pytest.mark.asyncio
async def test_seed_message_retry_does_not_duplicate_lifecycle_request(runtime):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(runtime)), base_url="http://test"
    ) as client:
        payload = {
            "operation": "message",
            "text": "Original ideas",
            "immediate": True,
            "idempotency_key": "seed",
        }
        first = await client.post("/v1/action", json=payload)
        second = await client.post("/v1/action", json=payload)
        assert first.status_code == second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert len(runtime.store.rows("SELECT * FROM inbox")) == 1
