"""Append the reviewed scope and efficiency corrections without starting agents."""

import json
from pathlib import Path

import httpx

CATALOG = "79a8cfe348d34b91a3e1a55a2db1a048"
HARNESS = "7eb9d6e9-4c34-400f-90f2-0af807be77b2"
FAILED = "474ccebb3e214c5497238cf9eb82e53e"

SCOPE = """EA-1: feature entrenchment in evolving programs. Preserve the original ideas,
earlier definitions, evidence and negative results. The broad measurement stack,
population grid, nestedness, speciation and extinction treatments are a backlog,
not prerequisites for the next useful result.

Current priority: the smallest coherent repair and validation of lineage, then
one validated observable and a small comparison. Fresh verification found invalid
parent-before-child lineage references despite legacy PASS results. Establish
correct founder/parent handling and meaningful checks; record any protocol change
explicitly. Prefer small edits and existing C/Python-stdlib facilities. NumPy/pip
and a usable GPU research stack were unavailable; do not repeat broad dependency
discovery without a changed need.

Measure foreground runtime on a small cell before scaling. The old 17-minute
estimate was incorrect. Use the durable per-cell driver and verified receipts;
preserve legacy/incomplete outputs and keep preliminary results labelled. Do not
expand the grid until the observable is trustworthy. A focused repair report or
negative finding is useful; do not claim the scientific instrument is validated
just because old gates pass. Archive self-contained publications when evidence
supports a useful synthesis, rather than publishing every routine iteration.
"""


def main():
    private = Path.home() / ".local/state/supervisor-agent-recovery"
    receipt_path = private / "efficiency-guidance.json"
    if receipt_path.exists():
        print("Efficiency guidance was already recorded; research remains paused.")
        return
    with (
        httpx.Client(
            transport=httpx.HTTPTransport(uds="/var/lib/supervisor-agent/daemon.sock"),
            base_url="http://supervisor",
            timeout=30,
        ) as supervisor,
        httpx.Client(
            transport=httpx.HTTPTransport(uds="/var/lib/iterative-research-harness/daemon.sock"),
            base_url="http://irh",
            timeout=30,
        ) as harness,
    ):

        def call(client, method, path, body=None):
            response = client.request(method, "/v1/" + path, json=body)
            response.raise_for_status()
            return response.json()

        state = call(supervisor, "GET", "status")
        status = call(harness, "GET", f"projects/{HARNESS}")
        if state["enabled"] or state["active_execution"] or status["control"]["state"] != "paused":
            raise RuntimeError("Stop dispatch and safely pause research first")
        project = call(supervisor, "GET", f"projects/{CATALOG}")
        archive = (
            Path("/var/lib/supervisor-agent/research/projects")
            / CATALOG
            / "instructions-before-efficiency-review.md"
        )
        if not archive.exists():
            call(
                supervisor,
                "POST",
                "action",
                {
                    "operation": "note",
                    "kind": "project",
                    "id": CATALOG,
                    "name": archive.name,
                    "append": False,
                    "text": project["instructions"],
                },
            )
        call(
            supervisor,
            "POST",
            "action",
            {"operation": "project_update", "id": CATALOG, "values": {"instructions": SCOPE}},
        )
        messages = []
        for target in ("upper", "iteration"):
            message = call(
                harness,
                "POST",
                f"projects/{HARNESS}/messages",
                {
                    "actor": "operator",
                    "target": target,
                    "text": "Scope clarification after the efficiency review. "
                    "This supersedes requirements to finish the entire original measurement stack immediately.\n\n"
                    + SCOPE,
                    "idempotency_key": f"nov10-efficiency-scope-{target}",
                },
            )
            messages.append(message["id"])
        call(
            supervisor,
            "POST",
            "action",
            {
                "operation": "steer",
                "execution_id": FAILED,
                "text": "Efficiency review: known failures, operational facts and unresolved decisions are recorded "
                "in /var/lib/supervisor-agent/notes after the updated backend starts. Consult them and recent "
                "communications before repeating work. The EA-1 scope is now one lineage repair and one trustworthy "
                "observable before grid expansion. Original instructions are archived in the project notes. "
                "The FIORA question is already awaiting a user decision; do not ask it again without a material change. "
                "Keep routine review brief once evidence supports a decision, report useful findings promptly, "
                "and delegate longer debugging. Preserve the current conversation prefix.",
            },
        )
        receipt_path.write_text(
            json.dumps({"harness_messages": messages, "dispatch_enabled": False}, indent=2) + "\n"
        )
        print("Scope and efficiency guidance recorded; no agents started.")


if __name__ == "__main__":
    main()
