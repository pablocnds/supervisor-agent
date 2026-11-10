# Reasoning and recovery defaults

Reviewed against the installed stack on 10 November 2026.

## Model modes

The [Qwen3.8-Flash-Next model card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
documents per-request thinking controls. Its non-thinking example uses temperature
0.7, top-p 0.8 and presence penalty 1.5; the thinking example uses temperature
1.0, top-p 0.95 and no presence penalty. It recommends preserved thinking for
agent continuity and cache reuse.

The [llama.cpp server API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
accepts `reasoning_effort: "none"` and
`chat_template_kwargs: {"enable_thinking": false}`. The installed server code
confirms these override server defaults. A live pool summary returned a usable
154-token answer, no reasoning text, and `finish_reason: stop` in 7.6 seconds.
See the [probe](reviews/2026-11-10/recovery/summary-probe.json).

Independent settings under `model.compaction` default to 4,096 answer tokens,
temperature 0.7 and those non-thinking request overrides. Supervisor uses
`output_tokens`/`extra`; the harness uses `max_output_tokens`/`extra_body`, following
their existing names. Summary extras override ordinary extras. These are tunable
defaults for this Qwen/llama.cpp stack, not universal model rules.

Research, planning, supervision, and delegates retain the configured thinking
profile. There is insufficient local evidence to lower reasoning for decisions
about evidence, priorities, or failures. A future routine-only mode should be
measured and selected at execution creation. Existing prompts and ordinary
history stay intact; the threshold remains 96k. Reasoning absent from legacy
harness sessions is not reconstructed.

[Anthropic's context-engineering guidance](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)
supports carrying decisions and remaining work through compaction, with durable
notes outside the prompt. Here the recent tool-complete suffix is retained,
full histories are archived, and agents can inspect original artifacts through
the shell. Summary requests now reuse the original system prompt, tools and
conversation, appending the summary instruction as a user message and disabling
tool calls. This preserves the cached prefix on the installed stack; replacing
history after a validated summary remains an intentional cache reset. See the
[efficiency follow-up](reviews/2026-11-10/efficiency/implementation.md).

## Failure behavior

Full session snapshots precede summary requests under
`executions/ID/compactions/` (Supervisor) or
`controller/PROJECT/sessions/compactions/` (harness). Only nonempty answer text
with `finish_reason: stop` and no tool calls can replace history. Empty,
truncated, malformed, and failed responses preserve history without automatic
expensive retries. Events record snapshot paths, finish reasons, token usage,
and answer/reasoning lengths without dumping reasoning into alerts.

Harness summary failures emit `session_compaction_failed` and an intervention
event. The Supervisor disables dispatch for operator intervention instead of
automatically resuming the paused project. Ordinary output-limit events produce
coalesced noncritical alerts and an append-only reminder to use smaller edits.

Startup waits up to `startup_timeout_seconds` (default 30) for a temporarily
missing/refusing harness socket. Other errors, timeout exhaustion, and later
infrastructure failures require operator inspection.

```sh
supervisorctl alert-resolve ALERT_ID 'Readiness verified; incident resolved'
```

Resolution retains an event and a note in alert history. It cancels queued or
paused alert investigations, rejects resolution of a running investigation, and
does not enable dispatch. Recurrences create a new alert. `enable` stays separate.

Project responses expose `execution.state`, backend phase, pause reason and
`blocked_by` separately from project status, selection and holds. Monitoring
reconciles stale metadata without releasing holds or reviving ended projects.
The temporary monitor shows project and execution state separately.

## Paused experiment

The [recovery scripts](reviews/2026-11-10/recovery/) apply to the reviewed EA-1
artifact. Its foreground driver writes durable per-cell receipts and flushes
manifest rows as cells finish, including out-of-order completion. Resume requires
a successful receipt matching binary, config and summary hash. Old/incomplete
outputs are archived before replacement. A summary alone is insufficient: the
engine writes it before its final checks. No population-level checkpointing or
asynchronous service was introduced.

Fresh verification rebuilt a snapshot, regenerated self-test inputs and ran a
small foreground test, recording hashes and commands. Legacy checks passed,
but an independent lineage causality check failed. This does not certify the
scientific instrument. Original source, binary, data and reports are preserved;
research stays paused for review.
