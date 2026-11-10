import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_state(tmp_path):
    supervisor, harness = tmp_path / "supervisor", tmp_path / "harness"
    for root in (supervisor, harness):
        root.mkdir()
        with sqlite3.connect(root / "state.sqlite3") as db:
            db.execute("CREATE TABLE projects(name TEXT)")
            db.execute("INSERT INTO projects VALUES ('old evidence')")
    key = harness / "model.key"
    key.write_text("fixture model credential")
    key.chmod(0o640)
    exa = harness / "search.key"
    exa.write_text("fixture search credential")
    exa.chmod(0o600)
    (supervisor / "config.json").write_text(
        json.dumps({"state_root": str(supervisor), "model": {"key_file": str(key)}})
    )
    (harness / "config.json").write_text(
        json.dumps(
            {
                "data_root": str(harness),
                "model": {"api_key_file": str(key)},
                "tools": [{"transport": {"header_files": {"Authorization": str(exa)}}}],
            }
        )
    )
    (supervisor / "notes").mkdir()
    (supervisor / "notes/operations.md").write_text("General operational knowledge")
    (supervisor / "notes/improvements.md").write_text("Old project-specific context")
    (harness / "projects").mkdir()
    (harness / "projects/paper.md").write_text("Previous research evidence")
    return supervisor, harness


def archive_args():
    return {
        "service_uid": os.getuid(),
        "service_gid": os.getgid(),
        "operator_uid": os.getuid(),
        "operator_gid": os.getgid(),
    }


def test_clean_state_moves_intact_trees_and_keeps_only_fresh_inputs(tmp_path):
    module = load("clean_state", "deploy/clean_state.py")
    supervisor, harness = fixture_state(tmp_path)
    original_inode = (harness / "projects/paper.md").stat().st_ino
    archive = tmp_path / "private/comparison"
    manifest = module.archive_and_reset(supervisor, harness, archive, **archive_args())
    assert manifest["complete"]
    assert archive.stat().st_mode & 0o777 == 0o700
    assert archive.parent.stat().st_mode & 0o777 == 0o700
    assert (archive / "harness/projects/paper.md").stat().st_ino == original_inode
    assert (archive / "harness/projects/paper.md").read_text() == "Previous research evidence"
    assert (archive / "supervisor/notes/improvements.md").read_text() == "Old project-specific context"
    assert manifest["databases"][str(harness)]["counts"]["projects"] == 1
    assert not (harness / "state.sqlite3").exists()
    assert not (supervisor / "state.sqlite3").exists()
    assert not (supervisor / "notes/improvements.md").exists()
    assert (supervisor / "notes/operations.md").read_text() == "General operational knowledge"
    assert (harness / "model.key").read_text() == "fixture model credential"
    assert (harness / "search.key").stat().st_mode & 0o777 == 0o600
    assert str(archive.parent) in json.loads((supervisor / "config.json").read_text())["hidden_paths"]
    with pytest.raises(ValueError, match="already exists"):
        module.archive_and_reset(supervisor, harness, archive, **archive_args())


def test_corrupt_database_stops_archive_before_either_tree_moves(tmp_path):
    module = load("clean_state", "deploy/clean_state.py")
    supervisor, harness = fixture_state(tmp_path)
    (harness / "state.sqlite3").write_text("not a database")
    archive = tmp_path / "private/comparison"
    with pytest.raises(sqlite3.DatabaseError):
        module.archive_and_reset(supervisor, harness, archive, **archive_args())
    assert (supervisor / "state.sqlite3").exists()
    assert (harness / "projects/paper.md").exists()
    assert not archive.exists()


def test_request_is_submitted_verbatim_and_receipt_precedes_enable(tmp_path):
    module = load("start_request", "lifecycle-test/start.py")
    receipt_path = tmp_path / "run.json"
    task = "Original notes:\n> Try an idea.\n\n  preserve indentation\n"
    actions = []

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"critical_failure": None})
        body = json.loads(request.content)
        actions.append(body["operation"])
        if body["operation"] == "message":
            assert body["text"] == task and body["immediate"]
            return httpx.Response(200, json={"id": "new-inbox-id"})
        assert json.loads(receipt_path.read_text())["inbox_id"] == "new-inbox-id"
        return httpx.Response(200, json={"enabled": True})

    with httpx.Client(transport=httpx.MockTransport(handle), base_url="http://test") as client:
        module.submit(client, task, receipt_path, tmp_path / "request.md")
        with pytest.raises(SystemExit, match="already submitted"):
            module.submit(client, task, receipt_path, tmp_path / "request.md")
    assert actions == ["message", "enable"]
