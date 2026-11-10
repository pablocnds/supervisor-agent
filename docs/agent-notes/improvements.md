# Improvements and decisions awaiting follow-up

Keep this a short, free-form record with evidence and current disposition.

- **Implemented, awaiting longer-run observation:** safe non-thinking compaction,
  startup readiness, explicit alert resolution, observed project states, and
  synchronous shell guidance. See `docs/reasoning-and-recovery.md` in the Supervisor source.
- **Open research defect:** EA-1's fresh verification failed parent-before-child
  lineage causality despite the legacy validator reporting PASS. Its recovery
  note and `maintenance/verification-20261110T210056Z/verification.json` in the
  harness workspace contain evidence and hashes. Existing lineage/rank claims
  remain unsupported. Repair and validate in a focused research iteration before
  expanding the grid. No independent rediscovery is needed.
- **Awaiting user decision:** the two older FIORA projects remain paused outside
  the catalog. The user was already asked whether to register or retire them.
  Leave their holds intact; do not repeat the question on each routine check.
- **Still to observe:** real bounded-run completion, publication synthesis,
  completion-driven next-work selection, and delegate lifecycle over a long run.
  Automated tests do not establish scientific quality or unattended reliability.

Update resolved findings and link investigations or user communications. Report
new actionable defects when established; keep detailed investigation in linked
project notes rather than growing this file indefinitely.
