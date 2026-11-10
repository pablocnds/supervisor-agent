import asyncio
import json
import socket
from types import SimpleNamespace

import pytest
import uvicorn

from supervisor_agent.api import app
from supervisor_agent.shell import Shell


@pytest.mark.asyncio
async def test_sandbox_cli_can_publish_over_read_only_unix_socket(runtime):
    config = runtime.config
    runtime.store.set("enabled", True)
    job = runtime.store.create_execution("routine", "Smoke test")
    runtime.agent = SimpleNamespace(id=job["id"], execution=job)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(config.socket))
    listener.listen(16)
    listener.setblocking(False)
    server = uvicorn.Server(uvicorn.Config(app(runtime), lifespan="off", log_level="error"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        shell = Shell(config, job["id"], config.state_root / "executions" / job["id"] / "workspace")
        result = await shell.run(
            "printf '# Result\nUseful findings.\n' > reply.md; supervisorctl communicate --file reply.md",
            timeout=10,
        )
        assert result["exit_code"] == 0, result
        metadata = json.loads(result["output"])
        assert metadata["execution_id"] == job["id"]
        assert metadata["created_at"]
        assert runtime.store.rows("SELECT * FROM communications")[0]["id"] == metadata["id"]
    finally:
        server.should_exit = True
        await serving
        listener.close()
        config.socket.unlink(missing_ok=True)
