import asyncio

import httpx
from starlette.testclient import TestClient

from supervisor_agent.monitor import create_app


def test_monitor_only_forwards_whitelisted_gets():
    forwarded = []

    def upstream(request):
        forwarded.append((request.method, request.url.path, request.url.query))
        if request.url.path.endswith("paper.md"):
            return httpx.Response(200, text="# Findings", headers={"content-type": "text/plain"})
        return httpx.Response(200, json={"ok": True})

    app = create_app("/unused-supervisor.sock", "/unused-harness.sock")
    mock = httpx.AsyncClient(transport=httpx.MockTransport(upstream), base_url="http://backend")
    try:
        with TestClient(app) as client:
            app.state.supervisor = mock
            app.state.harness = mock
            page = client.get("/")
            assert page.status_code == 200
            assert "temporary read-only monitor" in page.text.lower()
            assert client.get("/data/notes").status_code == 200
            assert client.get("/data/note/improvements.md").status_code == 200
            assert client.get("/data/status").status_code == 200
            assert client.get("/data/events?after=7&limit=100&operation=enable").status_code == 200
            assert client.get("/harness/project/publications/pub/paper").text == "# Findings"
            assert client.post("/data/status", json={"operation": "enable"}).status_code == 405
            assert client.post("/v1/action", json={"operation": "enable"}).status_code == 404
            assert client.get("/data/action").status_code == 404
            assert client.get("/harness/project/run").status_code == 404
        assert all(method == "GET" for method, _, _ in forwarded)
        assert all(b"operation" not in query for _, _, query in forwarded)
        assert all(path != "/v1/action" for _, path, _ in forwarded)
    finally:
        asyncio.run(mock.aclose())
