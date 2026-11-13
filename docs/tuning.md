# Settings to tune from observed behavior

Start with these defaults and change them when evidence warrants it. There are no meta-project quotas,
routine-check hard caps, automatic fallback models, or special manual finish commands.

| Setting | Initial value | Effect |
| --- | --- | --- |
| `prompt_file` | `INITIAL_PROMPT.md` | Identity, remit, resource map, and general working instructions. This is the most important behavior-tuning surface. |
| `delegate_prompt_file` | `DELEGATE_PROMPT.md` | Short role addition for an investigation that needs broader access. |
| `compaction_prompt_file` | `COMPACTION_PROMPT.md` | What must survive a context summary. |
| `hours`, `timezone` | 00/04/08/12/16/20 UTC | Calendar trigger hours; use `[0,8,16]` for eight-hour checks. |
| `model.compact_tokens` | 98,304 | Complete input threshold, including prompts and tools. |
| `model.output_tokens` | 16,384 | Maximum generated tokens per model response. |
| `model.temperature` | 1.0 | Sampling temperature, matching the existing harness. |
| `model.profile` | `qwen38-flash-next-q4xl-mtp-agent-128k` | Pool profile for new executions. |
| `model.request_timeout_seconds` | 3,600 | Network/model request deadline; independent of the routine-check guidance. |
| `model.cache_warning_ratio` | 0.8 | Warn when an expected continuation reuses less than this fraction of the preceding input. Missing measurements are recorded separately. |
| `poll_seconds` | 5 | Lightweight harness observation and dispatch cadence. Increase if the harness catalog grows large. |
| `request_warning_seconds` | 1,800 | Alert on a long model/tool operation; observational, not cancellation. |
| `reminder_seconds` | 1,800 | Agent-facing elapsed/progress reminders at the next turn boundary. |
| `delegate_seconds` | 14,400 | Review interval per resumed delegate segment. Safe pause can occur later if a synchronous operation is still running. |
| `shell_output_bytes` | 24,000 | Shell output tail retained in the conversation. Redirect substantial output to a workspace file. |
| `recent_alert_limit` | 10 | Prior alerts included with task context, linked to investigation execution IDs. |

The initial prompt currently gives 30-minute routine checks as guidance and explains the observed
generation slowdown near 128k context. Those are behavioral context, not agent execution limits.
If researcher/delegate selection, publication synthesis, or stopping behavior needs adjustment,
tune the short role/task context before adding task-specific rules.

Identity, rendered locations, model settings, tool definitions, and compaction instructions are frozen
in each saved execution. Editing a prompt or model configuration affects new executions; resuming an
old one retains its prefix and model settings. Credential file contents remain external. Changing an
existing credential file takes effect when the client reopens it. Saved tool definitions remain unchanged
on resume even if newly discovered metadata differs; that drift is recorded. Unavailable configured tools
or incompatible calls are reported through the normal failure/alert paths rather than rewriting history.

Intentional compaction is an expected cache reset. Ordinary continuations append new messages; they
never insert current status, timestamps, steering, or reminders into earlier history. Cache persistence
across model unloads/session switches is not guaranteed; unexpected reuse failures become automated inbox alerts.

The summarization call itself now shares the parent's prompt/tools/history and
appends a checkpoint request. Only continuation after swapping in the validated
summary resets the context. On the installed model, a live probe reused 5,203 of
5,248 summary input tokens, with no reasoning output.

New task packets include changes since the last successful review, recent user
communications, compact model/progress observations and excerpts of durable
environment notebooks. Full sessions, alerts and artifacts remain readable.
The initial prompt nudges small experiment scope, early useful
findings, short routine reviews and change-driven communications. These are soft
behavioral choices: no 30-minute hard cap, communication schema, automatic
semantic deduplication or forced improvement workflow is imposed. Tune after
observing the next run rather than assuming the prompt changes guarantee behavior.

General settings are loaded when the daemon starts. Restart after changing configuration, using the
safe stop procedure. Prompt files are read for each new execution, but immutable release files should
be changed through an operator-built release. The backend records streaming output and provider timing
data; effective tokens per full request second are labeled separately from raw provider generation rates.

The 13 November review tunes ordinary user notifications to roughly 50–120 words
and makes healthy, uneventful routine checks silent. This is prompt guidance,
not a schema, hard length limit, or notification quota. Routine reviews should
usually take a few minutes; 30 minutes remains a soft target. Longer analysis
belongs in a prioritized project. Follow notification relevance and routine
duration on the next run; these are the first behaviors to tune further.

Startup prioritizes operations.md and improvements.md within the existing
6,000-character excerpt budget and lists all notebook paths separately. Keep the
current notes compact; put chronological investigations with their projects.
Recent communications now expose up to 1,000 characters each so their actual
outcomes and requests are less likely to be hidden behind an opening status list.

Only a cold first request correlated with our own same-profile dispatch can be
considered an expected cache handoff. A subsequent successful request must prove
warm reuse of at least 80% of the earlier prefix. The raw warning and measured
cost remain in event observations. Failed/stopped runs, poor recovery, or no
confirmation within five minutes (or the shorter configured operation-warning
interval) retain ordinary inbox alerts. Mid-session and uncorrelated misses
remain alerts. This deliberately avoids suppressing all first requests on resume.
