"""Submit the evolution notes as an ordinary user request."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent


def default_task():
    return """Please organize and prioritize these research ideas. Some may be too abstract or not worth
pursuing. Identify the strongest ideas and start a useful, focused project if warranted; discard or
defer unpromising directions. Preserve the original notes and briefly explain your choices.

Original user notes:

""" + (ROOT / "ideas.md").read_text()


def submit(client, task, receipt_file, notes):
    if receipt_file.exists():
        raise SystemExit(f"Request already submitted; inspect {receipt_file} and supervisorctl status.")
    status = client.get("/v1/status")
    status.raise_for_status()
    if status.json()["critical_failure"]:
        raise SystemExit("Resolve the recorded critical failure before starting this request.")
    response = client.post(
        "/v1/action",
        json={
            "operation": "message",
            "text": task,
            "immediate": True,
            "idempotency_key": "research-ideas:" + hashlib.sha256(task.encode()).hexdigest(),
        },
    )
    response.raise_for_status()
    receipt = {
        "submitted_at": datetime.now(UTC).isoformat(),
        "inbox_id": response.json()["id"],
        "notes": str(notes),
        "activation_requested": True,
    }
    # Persist before enabling; never silently re-enable a subsequently failed run.
    with receipt_file.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    enabled = client.post("/v1/action", json={"operation": "enable"})
    enabled.raise_for_status()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", type=Path)
    parser.add_argument("--receipt-file", type=Path, default=ROOT / "run.json")
    args = parser.parse_args()
    task = args.request_file.read_text() if args.request_file else default_task()
    with httpx.Client(
        transport=httpx.HTTPTransport(uds="/var/lib/supervisor-agent/daemon.sock"),
        base_url="http://supervisor",
        timeout=30,
    ) as client:
        receipt = submit(client, task, args.receipt_file, args.request_file or ROOT / "ideas.md")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
