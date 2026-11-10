"""Submit the evolution notes as an ordinary user request."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
RECEIPT = ROOT / "run.json"
if RECEIPT.exists():
    raise SystemExit(
        f"This test was already submitted; inspect {RECEIPT} and supervisorctl status instead of re-enabling it."
    )

task = """Please organize and prioritize these research ideas. Some may be too abstract or not worth
pursuing. Identify the strongest ideas and start a useful, focused project if warranted; discard or
defer unpromising directions. Preserve the original notes and briefly explain your choices.

Original user notes:

""" + (ROOT / "ideas.md").read_text()

with httpx.Client(
    transport=httpx.HTTPTransport(uds="/var/lib/supervisor-agent/daemon.sock"),
    base_url="http://supervisor",
    timeout=30,
) as client:
    status = client.get("/v1/status")
    status.raise_for_status()
    if status.json()["critical_failure"]:
        raise SystemExit("Resolve the recorded critical failure before starting this test.")
    response = client.post(
        "/v1/action",
        json={
            "operation": "message",
            "text": task,
            "immediate": True,
            "idempotency_key": "evolution-ideas-fresh-2026-11-10",
        },
    )
    response.raise_for_status()
    receipt = {
        "submitted_at": datetime.now(UTC).isoformat(),
        "inbox_id": response.json()["id"],
        "notes": str(ROOT / "ideas.md"),
        "activation_requested": True,
    }
    # Persist before enabling; if the response is lost, do not silently re-enable a later failed run.
    with RECEIPT.open("x") as stream:
        json.dump(receipt, stream, indent=2)
    enabled = client.post("/v1/action", json={"operation": "enable"})
    enabled.raise_for_status()
    print(json.dumps(receipt, indent=2))
