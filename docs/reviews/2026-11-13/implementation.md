# Implementation of the 13 November review

The changes preserve the stopped run and its evidence. They do not restart
research, automatically accept partial drafts, change the model/profile or
context limit, install a GPU stack, or alter cache-server flags.

- Supervisor communication guidance: normally 50–120 words, silent healthy
  routines, no repeated unchanged suggestions or recovered-alert chores. Routine
  task/tool descriptions reinforce the same policy. This needs observation and
  tuning, not a hard notification limit.
- Supervisor scheduling: automatically release only its own cooperative harness
  pauses. Other pauses park selection and enqueue one decision item keyed to the
  pause ID. Explicit permitted resumes remain possible and are bound to that ID;
  operator/legacy holds cannot be released by agents.
- Harness write-up: less than one second is exhausted; ordinary resume is refused
  until allowance changes. Already accepted papers can still finalize without
  another model call. Drafts/data are preserved rather than implicitly accepted.
- Paper submission: accept ordinary heading subtitles. Write-up can use the
  existing edit_file tool, restricted to paper.md. Paper edits and replacements
  are atomic; write-up rejects invalid replacement papers before overwriting the
  current draft. General workspace writes are atomic too.
- Tool setup: configurable default_tools apply to omitted/null project tools;
  explicit lists and --no-tools override them. Defaults are resolved and frozen
  at project creation. The local config is prepared with exa/manual defaults.
- Cache observations: correlate our own same-profile handoff with its first
  request, then require a warm follow-up before recording recovery without an
  inbox investigation. Unverified, failed, stopped, timed-out, uncorrelated, and
  mid-session cases retain alerts. A pending observation expires after at most
  five minutes; raw warning/timing evidence remains available.
- Working memory: prioritize current named notes and index other resources;
  expose more of recent notifications. Archive every previous notebook privately
  and as research-line notes before installing two concise current references.
- Research guidance: verify the cited protocol and actual bounded parallel launch;
  freeze plans before results; check important estimators on known cases; retain
  uncertainty; submit an honest partial result before polishing. No specialized
  statistical tool or fixed experiment template was added.

`deploy/prepare-review-fixes.py` applies the reversible notebook/config migration
while dispatch is disabled and appends guidance for the interrupted Supervisor.
It does not rewrite that execution's frozen prompt or earlier conversation.
The partially created, unregistered follow-up project is explicitly identified
for reconciliation, including its empty tools and incorrect xargs quoting claim.
It is not started or silently replaced by this deployment.

The preparation archive and release receipt live under the operator-only
`~/.local/state/supervisor-agent-review-fixes/`. The archive preserves all five
original notebooks. Historical agent-readable copies are under research line
`a5903a4ebe6146a4bcf9f9b4440f7330`, named `review-2026-11-13-*`.

Build the committed harness with `deploy/update.sh --no-restart`, then build the
committed Supervisor with its `deploy/update.sh`. After preparation and recording
the exact release paths, `sudo deploy/activate-review-fixes.sh` restarts the
services in readiness order and verifies that dispatch is still disabled. It
preserves the expected manual-stop recovery marker for later operator review.
