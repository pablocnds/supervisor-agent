"""Preserve old notebooks, install concise current guidance, and keep dispatch stopped."""

import hashlib
import json
import shutil
from pathlib import Path

import httpx

from supervisor_agent.config import write_json

SOURCE = Path(__file__).resolve().parents[1]
ROOT = Path("/var/lib/supervisor-agent")
HARNESS = Path("/var/lib/iterative-research-harness")
PRIVATE = Path("/home/omega/.local/state/supervisor-agent-review-fixes")
LINE = "a5903a4ebe6146a4bcf9f9b4440f7330"


def call(socket, method, path, body=None):
    with httpx.Client(
        transport=httpx.HTTPTransport(uds=str(socket)), base_url="http://local", timeout=30
    ) as c:
        response = c.request(method, "/v1/" + path, json=body)
        response.raise_for_status()
        return response.json()


def consolidate(notes, archive, write_note):
    """Archive every original before replacing or removing any note; safe to retry."""
    archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = archive / "notes-manifest.json"
    if not manifest_path.exists():
        manifest = {}
        for path in sorted(notes.iterdir()):
            if not path.is_file() or path.is_symlink():
                raise ValueError("Unexpected notebook entry: " + str(path))
            shutil.copy2(path, archive / path.name)
            manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        write_json(manifest_path, manifest)
    manifest = json.loads(manifest_path.read_text())
    for name, digest in manifest.items():
        original = archive / name
        if hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            raise ValueError("Notebook archive changed: " + name)
        write_note("line", LINE, "review-2026-11-13-" + name, original.read_text())
    review = SOURCE / "docs/reviews/2026-11-13"
    for name in ("operations", "improvements"):
        write_note("environment", None, name + ".md", (review / f"current-{name}.md").read_text())
    for name, digest in manifest.items():
        if name not in ("operations.md", "improvements.md"):
            path = notes / name
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("Notebook changed during consolidation: " + name)
                path.unlink()


def main():
    status = call(ROOT / "daemon.sock", "GET", "status")
    health = call(HARNESS / "daemon.sock", "GET", "health")
    if status["enabled"] or status["active_execution"] or health["active_projects"]:
        raise SystemExit("Stop dispatch and safely pause research before preparing these changes.")
    config_path = HARNESS / "config.json"
    config = json.loads(config_path.read_text())
    if not {"exa", "manual"} <= {t["id"] for t in config["tools"]}:
        raise SystemExit("Expected configured exa/manual tool servers; inspect configuration first.")
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PRIVATE.chmod(0o700)
    receipt = PRIVATE / "guidance-applied.json"
    if receipt.exists():
        print("Review guidance already applied; dispatch remains stopped.")
        return
    archive = PRIVATE / "2026-11-13"

    def write_note(kind, item, name, text):
        call(
            ROOT / "daemon.sock",
            "POST",
            "action",
            {
                "operation": "note",
                "kind": kind,
                "id": item,
                "name": name,
                "text": text,
                "append": False,
            },
        )

    consolidate(ROOT / "notes", archive, write_note)
    backup_config = archive / "harness-config.json"
    if not backup_config.exists():
        shutil.copy2(config_path, backup_config)
    config["default_tools"] = ["exa", "manual"]
    write_json(config_path, config)
    config_path.chmod(0o640)
    # The saved prompt/history remains untouched. Guidance is appended when this task resumes.
    execution = "aa14c5a8b26d4f979510a345719b5fe1"
    text = (
        "Operator follow-up after reviewing the run: read the compact operations.md and improvements.md. "
        "Healthy routine checks are silent; relevant user messages are usually 50–120 words with a detail link. "
        "Known handled warnings do not need repeated investigations or an operator alert-resolve request. "
        "Finish supervision once a next-work decision is supported; delegate deeper analysis. "
        "Write-up exhaustion now parks for a decision; preserve drafts/data and do not resume exhausted grace. "
        "You created unregistered harness project 197e58fe-1ad7-4059-b7c2-18f9e97b888d just before the cutoff. "
        "It has never run, lacks external tools, and its brief incorrectly blames double quotes for xargs failure. "
        "Reconcile that side effect before starting work: do not duplicate or discard its staged evidence. "
        "Use a properly configured replacement if needed; new projects inherit exa/manual defaults. "
        "Both shell quote styles substitute {} with xargs -I{}; verify the actual command and concurrency. "
        "Freeze plans before fresh data and do not equate nonsignificance with equivalence. "
        "Check load-bearing estimators on known cases and submit a valid partial report before polishing. "
        "Detailed former notebooks are archived with the research line; consult them selectively."
    )
    call(
        ROOT / "daemon.sock",
        "POST",
        "action",
        {
            "operation": "steer",
            "execution_id": execution,
            "text": text,
        },
    )
    write_json(receipt, {"archive": str(archive), "execution_id": execution, "dispatch_enabled": False})
    print(
        "Archived notebooks, installed compact guidance and tool defaults, appended continuation steering. Dispatch remains stopped."
    )


if __name__ == "__main__":
    main()
