# Efficiency and functionality follow-up

Production activation of the previous fixes was verified on 10 November 2026:
Supervisor, harness and monitor were active on the committed releases, dispatch
was disabled, all research was paused, and corrective steering was recorded.
This pass leaves that stopped state intact.

## Changes against the review

| Finding | Implemented response |
| --- | --- |
| E1 oversized code writes | Existing truncation events and small-edit reminders retained; research scope now emphasizes one observable and a small comparison. No blanket output-limit increase. |
| E2 extended routine checks | Startup shows the last completed review, changes since then, recent communications and known findings. Prompt tells the agent to finish when it has enough evidence and delegate longer investigations. The 30-minute guidance stays soft. |
| E3 expensive compaction | Both agents fork their existing cached conversation and append a summary request, retaining system prompt/tools and using non-thinking mode. Full histories and summary validation remain intact. |
| E4 rediscovery/tool errors | Seeded operations notebook records ID mapping, correct cursor/CLI syntax, capabilities, persistent paths and shell lifetime. Pipeline errors propagate; shell failure logging is accurate. Harness status avoids reparsing unchanged sessions. |
| E5 excessive experiment scope | Original EA-1 instructions are archived; current scope is lineage repair/validation followed by one defensible observable. The broad grid remains a backlog. Guidance is appended to existing conversations. |
| F1 lost improvement findings | Atomic, durable free-form environment notebooks hold observations, evidence, pending user decisions and follow-up. Prompt requests early recording/reporting of actionable defects. Notes remain available if a later model call fails. |
| F2 redundant communications | Recent replies and unanswered questions are included in startup context. Prompt favors useful, change-driven messages and quiet healthy checks. No mandatory template or hard one-message limit. |
| F3 unsupported source claims | Prompt distinguishes snippets from verified sources and requests a lightweight check of a central claim, or an explicit preliminary label. |
| F4 unexercised lifecycle | Integration coverage now connects completion notification, negative-publication linking, review, communication and bounded next-run selection without agent overlap. Existing delegate pause/review tests remain. Real scientific quality and unattended reliability still need a live run. |

The monitor adds a read-only operations/improvements pane. User communication
fetches also retry after transient failures instead of retaining an incomplete
render. No new model tools were added: agents still use shell, search and generic
communication, with CLI/API ownership of service state.

## Measurements and rationale

A [live cache probe](cached-compaction-probe.json) on the configured pool profile
reused **5,203 / 5,248** summary input tokens (99.1%), evaluated only 45 new tokens,
and completed in **4.42 seconds**, with `finish_reason: stop` and no reasoning
text. This small probe demonstrates prefix reuse, not a guarantee of timing at
96k context or after cache eviction.

A [second probe with retained reasoning in history](cached-compaction-reasoning-probe.json)
reused 5,292 / 5,337 input tokens (99.2%), again evaluating only the appended
45 tokens. Disabling thinking for the summary preserved the retained reasoning
prefix on the configured template.

The method follows [Anthropic's implementation notes](https://claude.com/blog/lessons-from-building-claude-code-prompt-caching-is-everything):
keep the same cached prompt/tools and append the compaction request. It was
checked locally because another server/template can render requests differently.
Normal thinking mode, retained reasoning and the 96k threshold are unchanged.

A [startup-packet comparison](startup-context-probe.json), using a consistent copy
of the paused production state and the actual model tokenizer, reduced variable
context from **4,358 to 2,878 tokens** (34%) while adding known findings and recent
communications. Packets vary with inbox/catalog size and later review history.
No claim of a measured end-to-end routine speedup is made yet.

## Operational handoff

`prepare_guidance.py` archives the old catalog instructions and appends scope
corrections through service APIs, with dispatch disabled and research paused.
It does not change scientific code or resume work. Existing sessions receive
steering; their initial prompts/history are not rewritten. Global notebooks are
seeded only if absent when the new backend starts.

After staging clean committed releases, the existing privileged activation script
can restart the services while preserving the stopped state. The newly found
lineage defect remains a research task. A fresh short Supervisor review should
reuse the durable evidence instead of repeating the failed long investigation.
