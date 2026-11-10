# Run review — 10 November 2026

Review of the ordinary research request started at 01:40 UTC, through the failure at 13:13 UTC. All times below are UTC. This review changes no service code, configuration, prompts, execution state, or research artifacts.

The immediate stop is a Supervisor compaction failure. The more serious finding is that the harness silently accepted the same kind of failure and discarded conversation history. Separately, background experiment launches repeatedly died at the end of their shell calls, and The Supervisor misdiagnosed this as a scheduling interruption. These issues should be addressed before continuing the run.

## Evidence and current state

- Supervisor execution records, events, saved sessions, communications, research notes, and source matching the deployed release were inspected. A consistent SQLite snapshot and extracted event/tool records were made under `/tmp/supervisor-review-20261110/` for this review; that directory is temporary, not a durable archive.
- All 1,292 harness events for project `7eb9d6e9-4c34-400f-90f2-0af807be77b2` were inspected, along with its surviving sessions, first iteration paper, current experiment sources, logs, validation reports, and result-file timestamps. Compaction has already removed parts of the original research conversations, so the surviving transcript is incomplete.
- Source files cited below were compared with `/srv/supervisor/current` and `/srv/irh/current`; the relevant agent/runtime/sandbox files match.
- The services remain up, but Supervisor dispatch is **disabled** with a recorded critical failure. The research project is safely paused; its files remain present. Nothing was restarted during this review.
- Two isolated reproductions were run using the deployed harness package, with temporary data and no model calls: an empty summary discarded earlier messages; a detached sandbox child did not survive shell completion.

## 1. Bugs and clearly incorrect behavior

### B1 — Critical: the harness silently discards history when compaction returns no answer

Both saved research sessions begin with the literal placeholder:

> Prior-session summary: No summary was returned.

In `src/irh/agent.py:410–417`, an empty `message.content` is replaced with that string, older messages are discarded, and the operation is recorded as successful compaction. There is no intervention alert for this failure. The two sessions are `controller/<project-id>/sessions/iteration-1.json` and `iteration-2.json` under the harness state root.

Three compaction requests consumed exactly 4,096 output tokens each:

| Completed | Input tokens | Wall time | Cache reuse |
| --- | ---: | ---: | ---: |
| 05:32:10 | 105,288 | 15m 14s | 0 |
| 10:10:53 | 100,912 | 15m 06s | 0 |
| 12:14:36 | 107,849 | 16m 24s | 0 |

The surviving sessions prove empty-summary acceptance in both iterations; they do not preserve enough response data to prove the content of every earlier compaction. The isolated reproduction reduced 20 messages to nine and incremented the successful compaction counter despite receiving `content=None`.

**Required change, harness:** validate a usable continuation summary before replacing history, preserve the original session on failure, and emit an actionable alert. Log truncation/finish information and whether reasoning versus answer text was returned. Add a regression check for an empty or truncated summary. Existing event records label these calls `ok: true`, which currently conceals the failure from the Supervisor.

### B2 — High: the Supervisor stops on its own empty compaction summary

Execution `474ccebb3e214c5497238cf9eb82e53e` reached its 96k context threshold at 12:59:56. Its compaction request processed **95,669 input tokens with no cache reuse**, spent **10m 35s on prefill**, generated exactly **4,096 output tokens**, and returned no usable answer text. At **13:13:44**, `Agent.compact()` raised `RuntimeError: Model returned an empty continuation summary`. `Runtime.run_execution()` then recorded a critical alert and disabled dispatch.

Unlike the harness, the Supervisor preserved its previous messages. Disabling after an unhandled critical error is consistent with the requested failure policy; the defect is the compaction path that predictably cannot produce a usable result with these settings.

The running model has reasoning enabled and a 4,096-token reasoning budget. Compaction independently caps the entire completion at 4,096 tokens. Exhausting that allowance on reasoning before reaching answer text is a strong explanation for all these failures, **not a fully proven response-level diagnosis**: the compaction events omit `finish_reason` and reasoning/answer lengths, and the raw responses were not retained.

**Required change, both agents:** make summarization settings compatible with the reasoning model and reserve space for an actual answer. Test a request-level non-thinking or bounded-reasoning summary mode against the installed model before choosing settings. Preserve history on failure, report truncation clearly, and use only bounded recovery. Increasing the limit alone would also increase cost. Supervisor compaction currently omits the normal `model.extra` settings, another source of inconsistent request behavior (`supervisor_agent/agent.py:307–344`).

### B3 — High: background research jobs repeatedly die at shell completion

The harness uses a fresh bubblewrap PID namespace for each shell command. Detached `nohup`/`setsid` jobs do not become persistent managed research jobs. This was reproduced: the shell returned successfully in 0.21 seconds, but its detached child never reached a file write scheduled two seconds later.

The researcher tried detached launches at **04:55, 05:06** (a survival probe), **11:02, 11:18, 11:23, 11:43, and 11:57**. Several commands also removed previous result directories before relaunching. The final command started at **11:57:41**, slept 30 seconds, and returned at **11:58:11**. Current result-file writes end at **11:58:11**, matching command completion. Its manifest was never written because the driver writes it only after the whole grid finishes.

**Required change, harness guidance and agent behavior:** explicitly communicate the existing shell lifetime: commands are synchronous, and their children cannot outlive the call. Run batches in the foreground and keep recoverable outputs between calls. This needs a short, concrete tool-environment clarification, not a new asynchronous framework. Experiment drivers should persist completed-cell metadata incrementally. Whole-cell `--resume` skips completed runs but does not checkpoint unfinished populations.

### B4 — High: the Supervisor confidently gave incorrect causal and timing guidance

At 12:51 and 12:57, The Supervisor queued steering saying the **12:14 supervisor pause killed the grid** and that the largest cells had achieved only 23–188 generations **in 17 minutes**, therefore requiring multi-hour execution. Its persisted noon review repeats this interpretation.

The final grid had already stopped at **11:58:11**, before the **12:00:00** pause request. The actual pause acknowledgement at 12:14:36 coincides with the harness's long compaction finishing. The grid's progress came from approximately **30 seconds**, not 17 minutes. The Supervisor treated time since launch as active experiment runtime without verifying that the process had survived. Its resulting speed estimate and scheduling advice are unsupported and substantially pessimistic.

**Required correction before resume:** retain the evidence but supersede the two queued steering messages and the incorrect note. Re-establish throughput using completed foreground runs and their measured runtimes. Fixing compaction alone and immediately resuming would deliver the erroneous pending instructions to the researcher.

### B5 — High: validation claims exceed the evidence

The 08:09 communication calls iteration 1 engineering “solid and validated.” The iteration paper explicitly says the **current source does not compile**, some final validation used **stale self-test dumps**, and several instrumentation defects invalidate the intended scientific measurements. The older pilot had working components, but the user-facing report omits a material distinction between that pilot and the current artifact.

The noon steering goes further: it declares the instrument correct, cites an `OVERALL: PASS` report, and says not to revisit instrumentation. However, `results/validation.txt` was last written at **11:16:31**, whereas the experiment binary was rebuilt at **11:55:50**, after further source changes. The PASS report does not establish validation of the final binary. This does not prove every final result is wrong; it invalidates the blanket certification.

**Required change in research practice:** tie validation to the actual binary/source and test-input hashes, rerun the relevant gates after changes, and distinguish verified observations from preliminary results. The Supervisor should carry the paper's limitations into its summary rather than strengthen its claims. Review the pending “do not re-litigate instrumentation” instructions before resuming.

### B6 — Medium: project metadata says “running” while execution is stopped

Catalog project `79a8cfe348d34b91a3e1a55a2db1a048` remains `status=running`, while harness control says paused and Supervisor dispatch is disabled. Dispatch marks the catalog running, but monitoring does not reconcile it with subsequent backend pauses/failure (`runtime.py:285–286, 288–331`).

**Required change, Supervisor:** expose/reconcile observed execution state separately from project disposition, selection, and user holds. The monitor should make “paused because supervision failed” visible. Do not infer that the research is running from a historical dispatch update.

### B7 — Medium: a startup readiness race creates a critical shutdown and stale investigation

The initial Supervisor poll hit `Connection refused` while the harness socket was still starting. The runtime's catch-all treats that first connection failure as critical (`runtime.py:391–402`). Two attempts within about four milliseconds were correctly coalesced into one inbox item with two occurrences; this is not evidence that the same exception was logged twice by one handler.

After operator recovery, that old inbox item remained pending and consumed a separate **9m 43s** investigation at 04:00, immediately followed by the ordinary check. The initial triage had already identified it as a startup transient.

**Required change:** add a narrow startup readiness gate in deployment/startup coordination. Preserve the requested stop-and-alert behavior for genuine ongoing infrastructure/model failures. Make operator acknowledgement and alert resolution clear enough that a known resolved incident need not be rediscovered later.

## 2. Efficiency and avoidable work

### E1 — Large, measured waste: oversized code-generation calls fail repeatedly

Four research `write_file` calls followed model responses that used the full **16,384-token** output limit. Their tool arguments were malformed and the writes failed. The preceding calls cost **9m 11s, 10m 56s, 11m 24s, and 11m 09s**, totaling **42m 40s**. They occurred at 03:14, 06:31, 08:37, and 08:52, primarily while producing/replacing the C engine. Successful caching did not save this generation time.

The harness logged 13 explicitly unsuccessful tool calls overall, including these four, path mistakes, editing failures, and rejected result submissions. Shell-level compilation failures can still appear as successful tool invocations, so 13 is not an exhaustive count of failed commands.

**Priority:** teach the researcher to edit small coherent sections and avoid retrying whole-file rewrites after truncation. Surface output-limit truncation as such; malformed-JSON sanitization alone does not solve it. A larger blanket output limit would risk longer failures.

### E2 — Most Supervisor cost is inference, especially an overextended noon check

| Execution | Actual agent time | Model calls | Tool calls |
| --- | ---: | ---: | ---: |
| Initial idea triage | 32m 05s | 28 | 48 |
| Old startup alert | 9m 43s | 21 | 30 |
| 04:00 routine | 7m 00s | 14 | 20 |
| 08:00 routine | 6m 35s | 21 | 27 |
| 12:00 routine, failed | 59m 07s | 37 + compaction | 60 |
| **Total** | **1h 54m 29s** | **121 + compaction** | **185** |

Times exclude waiting for research to reach its safe pause. All Supervisor tools combined consumed only **about 30 seconds**; ordinary model calls consumed **99m 56s**, with another **13m 48s** for failed compaction. Optimizing shell execution speed is not the main opportunity.

The noon check spent about **45 minutes before compaction** inspecting C code, raw per-run summaries, motif data, sessions, and historical records. It repeatedly checked artifacts while the researcher was paused. Some investigation was justified by real defects, but it became a research/debugging task performed directly in routine supervision, instead of handing off a focused investigation or recording and stopping after decisive evidence.

**Tuning:** keep the existing 30-minute guidance soft; do not add the hard cap the user rejected. Encourage a small health/progress delta check, a decision once evidence is sufficient, and delegation of longer investigation. The 04:00 and 08:00 routines show short executions are possible.

### E3 — Cache reuse is healthy; context growth and compaction are expensive

Ordinary Supervisor calls reused **4,075,101 of 4,229,616 input tokens: 96.35%**. The three harness compactions plus the Supervisor compaction consumed **about 60m 32s** and intentionally had no cache reuse. These are not ordinary cache failures. The noon Supervisor context retained about 151k characters of reasoning and 116k of tool results, increasing compaction pressure. It reached 97,917 input tokens on its last ordinary call.

**Priority:** make compaction reliable first, then reduce unnecessary new tool output and repetitive investigation. Consider a cheaper summary path that avoids serializing the entire history under a new prompt prefix. Any reasoning-retention change must be model/template-aware and tested for prefix reuse; do not remove or rewrite the middle of an ongoing cached conversation. Keep the agreed 96k threshold unless measurements justify changing it.

### E4 — Repeated environment discovery and avoidable interface errors

- Repeated `--help`, directory discovery, and schema inspection occur across fresh executions. Fresh tasks are intentional; rediscovering stable operational facts is avoidable with one concise maintained operations note linked from startup context.
- The 08:00 routine passed a timestamp to integer `events --after`; the noon check used unsupported `irh events --project`. Pipes often returned zero despite CLI errors, obscuring failure classification.
- The startup-alert execution confused the harness project ID with the catalog ID, then repeatedly attempted to reuse `/tmp/ops-note.md` across shell calls. Each call has a fresh `/tmp`, so the file had vanished. The persistent execution workspace is the right location.
- Initial triage probed unavailable NumPy/pip/GPU tooling and read unrelated paused-project material. Capability discovery is useful once, but should not recur in every research task.

**Tuning:** add only the demonstrated missing facts to the environment map: per-call `/tmp` and process lifetime, persistent workspace, identifier mapping, and location of a compact operations note. Preserve general shell access; no specialized directory-reading tools are needed.

### E5 — Initial experiment scope expanded before yielding a decisive result

The strongest idea was sensibly turned into one research line, but the brief demanded a new engine, lineage tracking, motif canonicalization, essentiality, irreversibility, nestedness/null testing, genome-size controls, population scaling, multiple arms, and seeds. Iteration 1 spent its four-hour active budget plus roughly 38 minutes of write-up producing an honest partial paper, with no trustworthy test of the main hypothesis. Iteration 2 was still repairing instruments before another large grid launch.

Validation effort was valuable; the avoidable issue is attempting so much new measurement machinery at once. Start with one valid observable and one small comparison, obtain an interpretable result, and expand. The choice of research direction is reasonable; the implementation scope needs tuning.

## 3. Functionality and communication gaps

### F1 — Important improvement findings were not reliably delivered or tracked

The Supervisor did suggest startup/readiness improvements in its 04:10 communication, so the problem is not a total absence of suggestions. It also correctly detected empty research summaries at noon and saved that finding in the project review. But it failed before publishing that review as a communication. The user therefore received the generic execution failure rather than the discovered harness defect and its consequences.

A small durable improvement note linked to the relevant communication/project, with follow-up state, would prevent rediscovery and lost findings. Critical observed defects should be reported when established rather than waiting for a long routine to finish. This can remain free-form Markdown; a rigid output schema or automatic meta-project for every issue is unnecessary. Use a meta-project when an investigation actually warrants sustained work.

### F2 — Some communication is repetitive; broad overcommunication is not established

Five user communications were published. One at **04:17:24** merely says the routine completed and points to the substantive communication sent **15 seconds earlier**. The same unresolved request about registering/retiring the old FIORA projects appears in four messages. The other messages are generally concise and useful, although their confidence needs the corrections in B4/B5.

Prefer one useful communication per outcome, suppress redundant completion notices, and keep unanswered low-priority questions in a persistent note until something changes. Healthy no-change routines can just record their check. This is prompt tuning, not a reason to restrict arbitrary Markdown or prohibit follow-ups.

### F3 — Source discovery was adequate for triage, weak for confident scientific prescriptions

The initial Supervisor used four Exa searches but no source-fetch calls before making fairly specific literature and mechanism claims in the project brief. The researcher later acquired references. Search snippets are reasonable for finding directions, but preliminary mechanisms should remain hypotheses until source evidence supports them. A lightweight source check for the central claim would be preferable to a broad literature review during supervision.

### F4 — The full lifecycle has not yet been demonstrated

The run produced a research line, a bounded two-iteration harness run, one archived partial iteration paper, safe pause/resume cycles, steering, and communications. It did not finish the second iteration or reach the bounded-run completion trigger. Publication synthesis, completion-driven prioritization, delegate projects, and a full day of unattended operation were not exercised. Their absence in this stopped run is not itself a proven implementation defect.

## Recommended order

1. Fix empty/truncated compaction handling in both agents and test real summary settings with the current profile. Preserve originals and useful diagnostics.
2. Clarify synchronous shell lifetime, stop detached batch launches, and persist experiment progress/manifest records incrementally.
3. Correct/supersede the queued false steering, validate the current research artifact, and remeasure throughput before any resume.
4. Reconcile project status and fix the startup readiness race.
5. Reduce large code-generation failures and routine-check scope; then tune compact operational context and concise, change-driven communications.
6. Resume the existing research only after these corrections and observe the remaining completion/publication lifecycle. No broad redesign or new guardrail framework is indicated by this run.

The original user notes were preserved, a coherent line was selected, older operator-held projects were left alone, ordinary caching worked well, and the partial paper honestly preserved negative findings. Those parts should be retained while correcting the failures above.
