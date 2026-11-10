#!/usr/bin/env python3
"""Install the reviewed driver and append corrections while dispatch is stopped."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import httpx

HARNESS_ID = "7eb9d6e9-4c34-400f-90f2-0af807be77b2"
CATALOG_ID = "79a8cfe348d34b91a3e1a55a2db1a048"
FAILED_EXECUTION = "474ccebb3e214c5497238cf9eb82e53e"
WORKSPACE = Path("/var/lib/iterative-research-harness/runtime") / HARNESS_ID / "iteration/workspace"
HERE = Path(__file__).resolve().parent


def main():
    private = Path.home() / ".local/state/supervisor-agent-recovery"
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt_file = private / "applied.json"
    receipt = json.loads(receipt_file.read_text()) if receipt_file.exists() else {}
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
        status = call(harness, "GET", f"projects/{HARNESS_ID}")
        if state["enabled"] or state["active_execution"] or status["control"]["state"] != "paused":
            raise RuntimeError("Stop dispatch and safely pause EA-1 before applying recovery")
        verification = json.loads((HERE / "verification-result.json").read_text())
        report_path = Path(verification["report"])
        if json.loads(report_path.read_text()) != {k: v for k, v in verification.items() if k != "report"}:
            raise RuntimeError("Verification artifact differs from the reviewed result")
        driver = WORKSPACE / "src/run_driver.py"
        replacement = (HERE / "ea1_run_driver.py").read_bytes()
        if driver.read_bytes() != replacement:
            backup = WORKSPACE / "maintenance/run_driver.before-recovery.py"
            if backup.exists():
                raise RuntimeError("Driver changed after recovery; inspect before replacing it again")
            shutil.copy2(driver, backup)
            staging = driver.with_suffix(".recovery.tmp")
            staging.write_bytes(replacement)
            staging.chmod(0o660)
            os.replace(staging, driver)
        correction = f"""Operator correction after the November 10 run review. This supersedes the
12:51 and 12:57 Supervisor steering (messages 76408ed18a71464ab2f1936014fb0bd2
and afca203cb2144cc1995607ef1ebc2d4f), the noon review, and the blanket validation
claim in the 08:09 user report.

The final grid stopped writing at 11:58:11 when its shell call ended, BEFORE the
12:00 pause request. The 12:14 acknowledgement waited for compaction, not an
active grid. Its recorded progress came from about 30 seconds, not 17 minutes;
withdraw the resulting multi-hour estimate and remeasure in the foreground.
Shell children do not survive a call, even with nohup/setsid/disown. /tmp is fresh
per call; use /workspace or /scratch for persistent files.

The old PASS report predated the last binary rebuild. Fresh verification is at:
{report_path}
It records source/binary/test-input hashes and exact commands. Build, regenerated
selftests, legacy gates, and a small foreground smoke run succeeded, but an
independent parent-before-child lineage check FAILED. Legacy G5c/G5d/G5g contain
vacuous assertions. The scientific instrument is NOT certified. Withdraw the
instruction to stop investigating correctness; fix and validate lineage before
claiming phylogeny/rank results. Older completed summaries are preliminary
evidence, not proof of successful exit or trustworthy lineage.

src/run_driver.py now persists per-cell receipts and manifest rows as cells
finish. Run it in the foreground, using --resume to skip only verified matching
receipts. Legacy/incomplete outputs are archived before replacement, never
deleted; preserve all prior evidence. Resume skips complete cells, not partially
evolved populations. Check measured runtimes and scope before another grid.
Use small coherent edits after output truncation, and retain limitations in
papers and user summaries. Do not resume research automatically from this note.
"""
        for target in ("iteration", "upper"):
            call(
                harness,
                "POST",
                f"projects/{HARNESS_ID}/messages",
                {
                    "actor": "operator",
                    "target": target,
                    "text": correction,
                    "idempotency_key": f"nov10-recovery-correction-{target}",
                },
            )

        def action(body):
            return call(supervisor, "POST", "action", body)

        action({"operation": "project_update", "id": CATALOG_ID, "values": {"status": "paused"}})
        if not receipt.get("notes"):
            for name in ("review-2026-11-10T0805Z", "review-2026-11-10T1230Z", "recovery-2026-11-10.md"):
                action(
                    {
                        "operation": "note",
                        "kind": "project",
                        "id": CATALOG_ID,
                        "name": name,
                        "text": "\n## Operator correction\n\n" + correction,
                    }
                )
            receipt["notes"] = True
        if not receipt.get("communication"):
            receipt["communication"] = action(
                {
                    "operation": "communicate",
                    "project_id": CATALOG_ID,
                    "markdown": "Correction to the earlier EA-1 reports: the grid ended with its shell call, "
                    "before the scheduled pause; the 17-minute runtime estimate was incorrect. Fresh checks "
                    "also found a lineage defect the old validation missed. Research remains paused. "
                    "Original evidence is preserved, and corrected guidance plus a durable foreground driver "
                    "are recorded in the project's recovery note.",
                }
            )["id"]
        receipt["driver_sha256"] = hashlib.sha256(driver.read_bytes()).hexdigest()
        receipt_file.write_text(json.dumps(receipt, indent=2) + "\n")
        # The new backend accepts steering for a failed execution without queuing it.
        if not receipt.get("failed_execution_steered"):
            response = supervisor.post(
                "/v1/action",
                json={"operation": "steer", "execution_id": FAILED_EXECUTION, "text": correction},
            )
            if response.status_code == 409:
                print(
                    "Harness/project corrections applied; failed-execution steering awaits backend activation."
                )
            else:
                response.raise_for_status()
                receipt["failed_execution_steered"] = True
                receipt_file.write_text(json.dumps(receipt, indent=2) + "\n")
                print("Recovery corrections applied; dispatch and research remain stopped.")


if __name__ == "__main__":
    main()
