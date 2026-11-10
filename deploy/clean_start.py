"""Archive the stopped ecosystem and submit a pinned ordinary research request."""

import argparse
import grp
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from clean_state import archive_and_reset, write_owned

SOURCE = Path(__file__).resolve().parents[1]
PRIVATE = Path("/home/omega/.local/state/supervisor-agent-clean-start")
SUPERVISOR = Path("/var/lib/supervisor-agent")
HARNESS = Path("/var/lib/iterative-research-harness")
RELEASES = {"supervisor": Path("/srv/supervisor/current"), "harness": Path("/srv/irh/current")}


def call(socket, method, path, body=None):
    with httpx.Client(
        transport=httpx.HTTPTransport(uds=str(socket)), base_url="http://service", timeout=15
    ) as client:
        response = client.request(method, "/v1/" + path, json=body)
        response.raise_for_status()
        return response.json()


def wait_ready(socket, path):
    deadline = time.monotonic() + 30
    while True:
        try:
            return call(socket, "GET", path)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def paused_projects():
    status = call(SUPERVISOR / "daemon.sock", "GET", "status")
    health = call(HARNESS / "daemon.sock", "GET", "health")
    if status["enabled"] or status["active_execution"] or health["active_projects"]:
        raise SystemExit("Stop dispatch and safely pause all research before resetting.")
    return call(HARNESS / "daemon.sock", "GET", "projects")


def prepare():
    if os.getuid() != pwd.getpwnam("omega").pw_uid:
        raise SystemExit("Prepare as omega; only activation needs sudo.")
    if subprocess.check_output(["git", "-C", str(SOURCE), "status", "--porcelain"]):
        raise SystemExit("Commit the clean-start changes before staging a release.")
    projects = paused_projects()
    previous = json.loads((SOURCE / "lifecycle-test/run.json").read_text())
    message = call(SUPERVISOR / "daemon.sock", "GET", "inbox/" + previous["inbox_id"])
    if message["origin"] != "operator" or message["kind"] != "message":
        raise RuntimeError("Saved receipt does not identify the original user request")
    task = message["text"]
    baseline = {
        name: {"path": str(link.resolve()), **json.loads((link / "release.json").read_text())}
        for name, link in RELEASES.items()
    }
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PRIVATE.chmod(0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = PRIVATE.parent / "supervisor-agent-comparisons" / stamp
    if archive.exists():
        raise RuntimeError("Comparison archive already exists")
    request = PRIVATE / "request.md"
    write_owned(request, task.encode(), os.getuid(), os.getgid(), 0o600)
    subprocess.run([str(SOURCE / "deploy/update.sh")], check=True)
    plan = {
        "archive": str(archive),
        "request_file": str(request),
        "request_sha256": hashlib.sha256(task.encode()).hexdigest(),
        "config_sha256": {
            str(root): hashlib.sha256((root / "config.json").read_bytes()).hexdigest()
            for root in (SUPERVISOR, HARNESS)
        },
        "project_ids": sorted(p["id"] for p in projects),
        "baseline": baseline,
        "releases": {name: str(link.resolve()) for name, link in RELEASES.items()},
    }
    write_owned(
        PRIVATE / "plan.json", (json.dumps(plan, indent=2) + "\n").encode(), os.getuid(), os.getgid(), 0o600
    )
    print(f"Prepared archive: {archive}")
    print(f"Pinned original request SHA-256: {plan['request_sha256']}")


def main():
    if os.geteuid() != 0:
        raise SystemExit(
            "Run deploy/clean-start.sh with sudo; it stops services and moves their state directories."
        )
    plan = json.loads((PRIVATE / "plan.json").read_text())
    archive = Path(plan["archive"])
    if archive.exists():
        raise SystemExit("This archive already exists. Inspect the prior attempt; the reset will not repeat.")
    for name, current in RELEASES.items():
        if str(current.resolve()) != plan["releases"][name]:
            raise SystemExit("Prepared releases changed; refresh the clean-start plan before proceeding.")
    task = Path(plan["request_file"]).read_text()
    if hashlib.sha256(task.encode()).hexdigest() != plan["request_sha256"]:
        raise SystemExit("Prepared request changed; refusing to reset with a different prompt.")
    for root in (SUPERVISOR, HARNESS):
        if (
            hashlib.sha256((root / "config.json").read_bytes()).hexdigest()
            != plan["config_sha256"][str(root)]
        ):
            raise SystemExit("Configuration changed since preparation; inspect before resetting.")
    projects = paused_projects()
    if sorted(p["id"] for p in projects) != plan["project_ids"]:
        raise SystemExit("Project set changed since preparation; inspect before archiving.")
    operator = pwd.getpwnam("omega")
    account = pwd.getpwnam("rh-agent")
    group = grp.getgrnam("irh-worker").gr_gid
    archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(root.stat().st_dev != archive.parent.stat().st_dev for root in (SUPERVISOR, HARNESS)):
        raise SystemExit(
            "State and archive are on different filesystems; no large implicit copy will be made."
        )
    subprocess.run(
        ["systemctl", "stop", "supervisor-monitor.service", "supervisor-agent.service", "irh-daemon.service"],
        check=True,
    )
    for service in ("supervisor-monitor.service", "supervisor-agent.service", "irh-daemon.service"):
        if subprocess.run(["systemctl", "is-active", "--quiet", service]).returncode == 0:
            raise RuntimeError(f"Service is still active: {service}")
    metadata = {
        "baseline": plan["baseline"],
        "request_sha256": plan["request_sha256"],
        "new_releases": plan["releases"],
        "old_projects": projects,
    }
    manifest = archive_and_reset(
        SUPERVISOR,
        HARNESS,
        archive,
        service_uid=account.pw_uid,
        service_gid=group,
        operator_uid=operator.pw_uid,
        operator_gid=operator.pw_gid,
        metadata=metadata,
    )
    write_owned(archive / "original-request.md", task.encode(), operator.pw_uid, operator.pw_gid, 0o600)
    receipt_file = SOURCE / "lifecycle-test/run.json"
    if receipt_file.exists():
        receipt_file.rename(archive / "previous-request.json")
    recovery = Path("/home/omega/.local/state/supervisor-agent-recovery")
    if recovery.exists():
        copied = archive / "operator-recovery"
        shutil.copytree(recovery, copied, symlinks=True)
        for path in [copied, *copied.rglob("*")]:
            os.chown(path, operator.pw_uid, operator.pw_gid, follow_symlinks=False)
    write_owned(
        archive / "README.md",
        (
            b"# Archived research ecosystem\n\nBoth service state trees were moved after a safe stop. "
            b"They include databases, transcripts, notes, papers, code, outputs and configuration. "
            b"Use manifest.json's path_mapping to translate original absolute paths. "
            b"Release identities and database hashes are recorded for comparison. "
            b"The archive is private to the operator and excluded from active discovery.\n"
        ),
        operator.pw_uid,
        operator.pw_gid,
        0o600,
    )
    print(f"Archived the older runs under {archive}", flush=True)
    subprocess.run(["systemctl", "start", "irh-daemon.service"], check=True)
    health = wait_ready(HARNESS / "daemon.sock", "health")
    if not health["ok"] or health["active_projects"]:
        raise RuntimeError("Fresh harness is not idle and healthy")
    subprocess.run(
        ["systemctl", "start", "supervisor-agent.service", "supervisor-monitor.service"], check=True
    )
    state = wait_ready(SUPERVISOR / "daemon.sock", "status")
    if state["enabled"] or state["critical_failure"]:
        raise RuntimeError("Fresh Supervisor is not stopped and healthy")
    for collection in ("projects", "lines", "inbox", "executions", "communications"):
        if call(SUPERVISOR / "daemon.sock", "GET", collection):
            raise RuntimeError(f"Fresh {collection} is not empty")
    if call(HARNESS / "daemon.sock", "GET", "projects"):
        raise RuntimeError("Fresh harness project list is not empty")
    improvements = (SUPERVISOR / "notes/improvements.md").read_text()
    if "FIORA" in improvements or "EA-1" in improvements:
        raise RuntimeError("Fresh improvement notebook still contains retired project context")
    subprocess.run(
        [
            "runuser",
            "-u",
            "omega",
            "--",
            plan["releases"]["supervisor"] + "/.venv/bin/python",
            str(SOURCE / "lifecycle-test/start.py"),
            "--request-file",
            plan["request_file"],
        ],
        check=True,
    )
    receipt = json.loads(receipt_file.read_text())
    delivered = call(SUPERVISOR / "daemon.sock", "GET", "inbox/" + receipt["inbox_id"])
    if delivered["text"] != task or delivered["origin"] != "operator":
        raise RuntimeError("Submitted message does not match the original operator request")
    manifest["new_run"] = receipt
    write_owned(
        archive / "manifest.json",
        (json.dumps(manifest, indent=2) + "\n").encode(),
        operator.pw_uid,
        operator.pw_gid,
        0o600,
    )
    print("Fresh research request submitted. The monitor remains at its existing address.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare", action="store_true", help="Pin request and stage the release without stopping services"
    )
    if parser.parse_args().prepare:
        prepare()
    else:
        main()
