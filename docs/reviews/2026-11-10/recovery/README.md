# Recovery artifacts

These files document and repair the paused EA-1 run reviewed on November 10.
They are maintenance artifacts, not additional tools exposed to the agents.

- `ea1_run_driver.py`: replacement foreground experiment driver, installed in
  the live workspace after preserving the original under `maintenance/`.
- `verify_ea1.py`: rebuilds and checks a separate snapshot, without resuming the
  research agent or modifying the original engine/binary.
- `verification-result.json`: exact build/input hashes and check results.
  Legacy validation passed; the independent lineage causality check failed.
- `summary-probe.json`: measured non-thinking summary request, with no raw reasoning.
- `apply_ea1_recovery.py`: checks that dispatch is disabled and EA-1 paused,
  installs the reviewed driver, appends corrective steering and notes, and sends
  one concise correction. Repeats use receipts and idempotency keys. Failed-task
  steering is completed after activating the new backend.

The old user communications and queued instructions are preserved. Corrections
explicitly supersede the incorrect interruption, timing, and validation claims.
Original experiment outputs remain in place; future driver replacements archive
old/incomplete cells before writing new ones. No claim of valid phylogeny/rank
measurements should be made from the existing lineage data.

The production services need a privileged restart after staging committed
releases. The exact release paths are recorded outside the agent's state in
`~omega/.local/state/supervisor-agent-recovery/releases.json`.
`sudo deploy/activate-recovery.sh` activates those releases, completes corrective
steering, and verifies that dispatch is still disabled. It never resumes research.
