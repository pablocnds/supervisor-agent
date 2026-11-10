# Backend operation

## Research catalog and delegation

Research lines contain projects. A project points to a harness project or to a supervisor-delegate
investigation. Notes are ordinary Markdown under `research/lines/ID/` and `research/projects/ID/`.
The agent reads sources and evidence through the shell, and updates metadata through the CLI/API.

```sh
supervisorctl line-add 'Environment improvements' --meta
supervisorctl line-add 'Main research question'
irh create --name 'Baseline study' --goal 'Measure ...' --tool exa
supervisorctl project-add 'Baseline study' --backend harness --harness-id HARNESS_ID --line LINE_ID --max-iterations 1
supervisorctl project-add 'Investigate model speed' --backend delegate --line META_LINE_ID --instructions-file investigation.md
supervisorctl update project PROJECT_ID '{"priority":10}'
supervisorctl select PROJECT_ID
supervisorctl select idle
```

Selecting work records the next choice; it does not start an agent alongside the current execution.
At a check the coordinator requests cooperative pause and waits for the harness health API to report
no active controllers before starting The Supervisor. It retains the previous active project as the
default next selection unless an explicit selection replaces it. Priorities inform agent decisions;
there is no independent algorithm overruling its project choice.

The harness enforces `--max-iterations` on a new run, including reporting/review. Resuming retains the
existing run's allowance. Registering existing projects does not automatically resume user-held work.
The coordinator treats a legacy pause without attribution conservatively as a user hold.

```sh
supervisorctl project-pause PROJECT_ID
supervisorctl project-resume PROJECT_ID
supervisorctl project-end PROJECT_ID
supervisorctl steer EXECUTION_ID 'Conclude after the current measurement; preserve partial findings.'
```

An operator `project-resume` queues release of that specific harness pause when execution is available;
it does not start the harness immediately. Agent-originated operations cannot clear an operator hold.
Delegate projects use persistent sessions/workspaces. At their review interval they pause safely and
queue a supervisor review, which may select the same project to continue its context or choose other work.

## Messages, communications, and publications

```sh
supervisorctl message 'Investigate why inference became slower' --now
supervisorctl message 'Consider this research idea at the next scheduled check: ...'
supervisorctl list inbox
supervisorctl list executions
supervisorctl events --after 0 --limit 100 --execution EXECUTION_ID
supervisorctl communicate --file reply.md
supervisorctl note project PROJECT_ID --file findings.md --name findings.md
```

Each addressable inbox item has its own execution. Routine checks are separate. A calendar tick drains
the pending inbox and queues its check; a tick is skipped if the prior supervisor cycle is still queued
or executing. Immediate messages wait for a safe handoff as well. Automated alerts are marked `system`,
coalesced until their investigation is handled, and presented with recent alert/investigation history. Distinct events retain
their receipt identities across cursor retries. Recurrent alerts in later cycles can create new notifications.

The native `communicate` tool and CLI accept arbitrary Markdown. Creation time, an identifier, and
originating execution/request/project links are attached outside the body. The final model response
ends execution normally; it does not need a special finish tool or structured final output.

Publications remain immutable harness artifacts. Researchers can prepare synthesis text as research
work; The Supervisor can also prepare it and use the existing harness CLI to archive it. This backend
does not add another paper-generation workflow or require a paper for every supervisor check.

```sh
irh publication-create HARNESS_ID --title 'Findings' --paper synthesis.md --source HARNESS_ID:1 --actor supervisor
supervisorctl publication-link PROJECT_ID PUBLICATION_ID /var/lib/iterative-research-harness/projects/HARNESS_ID/syntheses/PUBLICATION_ID
supervisorctl list publications
```

## Runtime boundary and recovery

The controller runs as `rh-agent`. Shells have read-only host mounts, their own writable workspace and
temporary directory, a private process namespace, and no ordinary network. Source and service state
remain readable. Host process summaries and harness observations are under `observations/`.
Configured model/search credential files are hidden from shells. General read access does not bypass
host Unix permissions, and explicitly hidden paths stay hidden. GPU device access retains Unix permissions.

The CLI connects through a group-protected Unix socket. The controller reaches the configured inference
and Exa endpoints outside shell networking. A fixed pool proxy supports shell-based benchmarks:

```sh
curl --unix-socket /var/lib/supervisor-agent/daemon.sock http://supervisor/pool/v1/models
```

Only inference/counting/embedding and selected status paths are allowed through that proxy; service
configuration mutations are unavailable. Search/fetch use the native tools discovered from Exa MCP.
All these operations use configured destinations, not an arbitrary outbound proxy.

This is deliberately a trusted-agent environment, not isolation against a malicious process running as
the same Unix account. Socket attribution identifies agent requests but is not per-user authentication.
In particular, follow the cooperative rule: use direct `irh run` for maintenance with supervisor dispatch stopped.

The SQLite database is authoritative for inbox, catalog, execution state, selection, communications,
receipts, and event cursors. Sessions and papers remain readable files. A daemon lock prevents two
supervisors from owning the same state root. Unclean loss marks active executions paused, disables
dispatch, and records an operator alert. Interrupted tool calls are marked outcome-unknown, never replayed
automatically. Inspect actual service/filesystem state before resuming them.

```sh
supervisorctl status
supervisorctl show executions EXECUTION_ID
supervisorctl resume-execution EXECUTION_ID
supervisorctl enable
```

Critical model/infrastructure failures stop dispatch for the operator. There is no model fallback or
automatic service repair. `enable` acknowledges the failure after inspection; an execution that needs
continuation is queued explicitly. Raw event and collection endpoints support a future frontend:
`GET /v1/status`, `/v1/events?after=SEQ&limit=N&execution=ID`, `/v1/{collection}?after=ROWID&limit=N`,
`/v1/{collection}/{id}`, and `/v1/communications/{id}/markdown`. Writes use `POST /v1/action`;
`supervisorctl --help` and its implementation provide the corresponding operation fields.

Backups remain deferred. Before changing deployed code, stop dispatch and wait for a safe pause.

See [reasoning-and-recovery.md](reasoning-and-recovery.md) for summary settings,
startup readiness, alert resolution, observed project status, and experiment recovery.

Environment-wide notebooks live under `notes/`. They are ordinary Markdown with
no required fields or workflow. Startup seeds the operations/improvement notes
only when absent; agent and operator edits survive restarts and upgrades.

```sh
supervisorctl note environment --file findings.md --name improvements.md --replace
```

The shell can read these files directly. Frontend reads use `GET /v1/notes`
(names, paths, sizes and modification times) and `GET /v1/notes/NAME` (Markdown).
The temporary monitor exposes these through its read-only notebook pane.
Writes and replacements are atomic. Line/project notes retain their existing
syntax and archive locations.

Resolving the current critical alert clears its active failure marker while
keeping dispatch disabled. Resolving an older alert cannot acknowledge a newer
failure. Re-enabling work remains a separate operator action.

For an operator-authorized clean restart with the original research request:

```sh
deploy/clean-start.sh --prepare
sudo deploy/clean-start.sh
```

Preparation checks paused state, pins the exact previous operator message, and
stages a committed Supervisor release. Activation safely stops both controllers
and the monitor, verifies SQLite integrity, and moves the complete state trees to
`~omega/.local/state/supervisor-agent-comparisons/TIMESTAMP/`. A same-filesystem
rename preserves evidence without duplicating large datasets. The archive
records releases, database hashes and original path mappings for comparison;
it is inaccessible to the agent account. The same archive cannot be reused for
a second reset.

Fresh state retains configuration, referenced credentials and general operations
notes. Old research, transcripts, alerts and project-specific notes remain in
the archive. The script checks empty catalogs, starts the same monitor and
submits the pinned message as ordinary use. This is separate from the historic
`activate-recovery.sh`, which is tied to the archived project and alert IDs.
