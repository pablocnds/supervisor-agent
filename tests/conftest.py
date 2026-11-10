from pathlib import Path

import pytest

from supervisor_agent.config import Settings
from supervisor_agent.runtime import Runtime
from supervisor_agent.store import Store


class FakeHarness:
    def __init__(self):
        self.active = []
        self.pauses = []
        self.starts = []
        self.start_actors = []
        self.projects = {}
        self.feed = {}

    async def health(self):
        return {"ok": True, "active_projects": self.active.copy()}

    async def pause(self, item, reason, actor="supervisor"):
        self.pauses.append((item, reason))
        return {"state": "waiting_to_pause"}

    async def status(self, item):
        return self.projects[item]

    async def start(self, item, resume, max_iterations, actor="supervisor"):
        self.starts.append((item, resume, max_iterations))
        self.start_actors.append(actor)
        self.active = [item]
        return {"run_id": "run"}

    async def call(self, method, path, data=None):
        if path == "projects":
            return [value["project"] for value in self.projects.values()]
        item = path.split("/")[1]
        after = int(path.split("after=")[1].split("&")[0])
        return [event for event in self.feed.get(item, []) if event["seq"] > after]

    async def close(self):
        pass

    def add(self, item="h1", phase="paused", actor="supervisor"):
        self.projects[item] = {
            "project": {"id": item, "name": "Study", "phase": phase},
            "control": {
                "state": "paused" if phase == "paused" else "idle",
                "pause_request": {"actor": actor, "id": "pause1"},
            },
            "model_usage": {},
        }
        return self.projects[item]


@pytest.fixture
def config(tmp_path):
    key = tmp_path / "model.key"
    key.write_text("test-key")
    key.chmod(0o600)
    return Settings(
        state_root=tmp_path / "state",
        socket=tmp_path / "daemon.sock",
        harness_socket=tmp_path / "harness.sock",
        prompt_file=Path(__file__).resolve().parents[1] / "INITIAL_PROMPT.md",
        model={"base_url": "http://model", "profile": "test", "key_file": key},
    )


@pytest.fixture
def store(config):
    value = Store(config.state_root)
    yield value
    value.db.close()


@pytest.fixture
def runtime(config, store):
    return Runtime(config, store, FakeHarness())
