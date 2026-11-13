# Run review — 13 November 2026

The Supervisor made useful research decisions and caught real analysis defects, but supervision and reporting became disproportionately expensive. Communication needs a stronger relevance threshold and a much smaller default size. There are also two harness defects to repair before continuing: exhausted write-up repeatedly auto-resumes, and a reasonable section heading prevents submission.

This is a review, with proposed changes below. No prompts, deployed services, live notebooks, research artifacts, or execution state were changed. Dispatch remains disabled. The interrupted final execution and recovery marker are consistent with the user's expected abrupt stop and are not treated as a new failure.

## Evidence and scope

Reviewed the ordinary request submitted on 10 November at 22:35 UTC, all 22 communications, Supervisor execution and inbox records, durable notebooks, 26,990 harness events, project snapshots, selected saved conversations and compaction snapshots, publication metadata, and relevant analysis/code artifacts. The final interrupted Supervisor execution created a follow-up project at 01:00 UTC on 13 November; it did not finish registering that project in the Supervisor catalog.

Sources match the relevant deployed revisions: Supervisor `1200da60daea`, harness `5728e8fc5f21`. Consistent database snapshots and extracted records are temporarily under `/tmp/supervisor-review-20261113-4495bjcr`. [metrics.json](metrics.json) preserves the compact counts, communication IDs, and event references. Scientific findings below verify specific code defects and reporting issues; this was not an independent replication of every experiment or statistical table.

## 1. Communications

| Observation | Measured result |
| --- | ---: |
| User communications | 22 |
| Total words | 12,599 |
| Average / range | 573 / 337–764 words |
| Communications from routine checks | 10, totaling 5,444 words |
| Explicit “no change” routine message | 462 words |

At 200 words per minute this is roughly an hour of reading. Every completed routine check published a message. These are deliberate calls to the communication mechanism; the backend does not automatically publish every execution's final answer.

The 12 November 17:25 message (`d49a4a1a…`) illustrates the problem: it starts with normal health, no changed projects, and nothing needed from the user, then repeats identifiers, memory/disk statistics, steering details, predictions, and an unchanged list of operator suggestions. It does contain a possible new timing issue, but that could have been recorded internally and included in one short, relevant improvement notification.

Many other messages contain genuinely useful discoveries. The wrong uncertainty calculation, invalid survival estimator, and write-up loop deserved attention. They needed a brief consequence and next action, with the derivation in a linked note. Healthy status, hashes, exact CLI calls, repeated cache diagnoses, and previously unanswered infrastructure suggestions crowded out those points.

**Suggested communication policy:**

- Remain silent after healthy, uneventful routine checks. Save an internal execution result; a routine trigger does not itself justify a notification.
- Notify for an answer to the user's request, a meaningful research outcome, a material correction, a blocker, or a decision the user needs to make. Routine steering and known, recovered incidents normally stay internal.
- Aim for approximately 50–120 words: outcome, practical consequence, next action or question, and a detail link when useful. This is a default, not a hard limit or required template. Supply longer explanations when requested.
- Do not repeat an unanswered suggestion unless its urgency, evidence, or requested decision changes. Gather related findings into one message when practical; interrupt promptly for a serious blocker.
- Keep routine RAM, disk, cache, version, and identifier inventories in observations and notes unless they explain a material problem.

Suggested replacement for the communication paragraph of the initial prompt:

> Keep durable operations and improvement notes compact and current; put detailed investigations with the relevant project. Consult recent communications before notifying the user. Be silent for healthy, uneventful routine checks and known incidents already handled. Communicate for a requested answer, meaningful result or correction, material blocker, or decision needing the user. Usually use one short paragraph or a few bullets, around 50–120 words, and link details. Do not repeat unchanged suggestions. Save internal findings without a notification when appropriate. When done, conclude normally; this does not require a user communication.

The routine task and `communicate` tool description should reinforce the same distinction in a sentence. No notification quota, Markdown schema, or automatic prose classifier is needed.

For example, the estimator discovery could have been:

> I found a bug in the isolation study's analysis, so its published reversal is unreliable. Correcting it leaves the question unresolved. I supplied a checked replacement and queued a confirmatory iteration using new seeds. No action needed from you. Details: [analysis and correction].

This describes the historical action at that time, not a newly resumed run. The uneventful routine message would simply be omitted.

## 2. Bugs and incorrect behavior

### Exhausted write-up repeatedly resumes without making progress

Two projects encountered the same loop:

| Harness project | First / last exhaustion pause, UTC | Exhaustion pauses |
| --- | --- | ---: |
| Extinction lever, `0b144f67…` | 11 Nov 22:06:26–23:59:58 | 1,349 |
| Isolation lever, `ee7e4e68…` | 12 Nov 22:41:20–13 Nov 00:00:00 | 932 |

There were **2,281 exhaustion pauses over approximately 3h 12m**. Most cycles made no model request. They still blocked progress and flooded event history.

In harness `controller.py::_writeup`, the remaining allowance is the configured grace minus charged write-up time. Both iterations retain about 0.006 seconds, which passes the positive-budget check but cannot fund a phase. Timeout pauses with `resume_phase="writeup"`. Supervisor `Runtime.dispatch` automatically resumes non-operator pauses without distinguishing this exhausted allowance from its own cooperative pause. Each service's local behavior recreates the other's failure indefinitely.

The Supervisor recognized the first loop, preserved data, and selected an analysis-rescue project. That was useful recovery. The source defect remained, and the next project hit it again.

**Fix first:** distinguish a cooperative pause that can be automatically released from a harness condition requiring a new decision. Exhausted write-up must park and notify once, rather than automatically restart. A minimum viable allowance avoids the millisecond phase; it does not alone solve repeated resume when allowance is fully exhausted. Choosing how to finalize an existing partial paper is a separate decision: do not silently present an unfinished draft as an accepted publication.

### Submission rejects a section that clearly identifies its methodology

Isolation iteration 3's `submit_results` failed at 22:38:48 with `paper.md needs a Methodology heading`. The paper contains:

```markdown
## 2. Methodology: what was done, and what was verified
```

`workspace.py::report_files` requires the section name to end the heading. An isolated reproduction using the actual harness function rejected that heading and accepted `## 2. Methodology`. The paper survived, but submission failed near the end of grace and the project entered the loop above.

**Fix:** accept ordinary heading subtitles while retaining the three substantive sections. Validate cheaply before spending the grace on prose polishing, and make a rejected submission's correction obvious. This is not evidence that the methodology section was absent.

### Research projects were created without the requested search access

The first three projects have `snapshot.enabled_tools: []`. The Supervisor eventually discovered the omission and created the isolation project with `['exa', 'manual']`. However, the follow-up created during the interrupted execution again has an empty list. Creation had already completed; registration in the catalog had not.

This is a setup omission, not a search-service outage. **Fix:** make the configured project-creation path/example include the intended external tools and verify the resulting snapshot. Check the unstarted follow-up before eventual continuation. Preserve frozen ongoing conversations rather than rewriting their earlier tool definitions.

### Some Supervisor instructions and lessons are wrong

- Steering message `989e59f2…` says to run the grid and pre-register immediately afterwards. Freeze the analysis plan before fresh results are available. The researcher's surviving paper states it actually froze its pre-registration before running, so the instruction alone does not establish post-hoc registration in this iteration.
- The same brief says failure to reach significance at the new sample size means the answer is “structure-insensitive.” A null result needs a stated resolution or uncertainty bound; lack of significance alone does not establish equivalence.
- The interrupted execution's new brief claims `xargs -I{} sh -c '{}'` works but `xargs -I{} sh -c "{}"` does not. Both quote forms pass the same replacement token; an isolated shell check confirmed both work. The failed earlier launch lacked the appropriate replacement behavior. Do not preserve the quoting claim as an operational lesson.
- A follow-on brief initially used the wrong instrument, forced-loss budget, and population size. The Supervisor caught and corrected these before research began, but only after sending a long “new project running” communication and then a second correction. Verify the anchor protocol before publishing the decision.

These findings argue for checking small, consequential claims and keeping limitations in summaries, rather than adding lengthy instructions for every future task.

## 3. Efficiency

### Routine supervision is taking research-sized amounts of time

The 22 completed Supervisor executions consumed **18h 16m** of active time. The interrupted execution adds roughly another hour. Ten completed routine checks consumed **8h 40m**; their median was approximately **50 minutes**, and eight exceeded the existing 30-minute guidance. Healthy routine checks were intended to be brief.

Tools accounted for only about **8m 34s** across recorded executions. The main cost is repeated model generation, deep artifact audits, writing analysis code, and long notes. No supervisor-delegate projects were created; substantial infrastructure and statistical investigation stayed inside routine/alert executions.

**Tune:** stop a routine once there is enough evidence to leave work running, steer it, park it, or select the next project. Turn longer audits into bounded projects, usually in the harness. Preserve the soft time guidance; a hard kill was explicitly rejected by the user.

### Repeated cache triage creates its own overhead

Cache warnings were repeatedly explained as cold requests after an execution handoff, yet generated separate investigations and communications. An execution handling the warning can itself cause another pause/handoff and another cold request. The note “do not give this a dedicated execution” cannot change the backend's queuing behavior by itself.

**Fix/tune:** record the known cause and distinguish an expected handoff loss from an unexpected miss. Keep the measured cost visible and retain alerts for genuine regressions. Do not blindly suppress every first request after resume: that could conceal a new failure. A repeated known event should not trigger another full line-wide cache study.

The Supervisor's cache-configuration proposals are candidates to benchmark, not verified fixes. A resident server does not prove there is only one cache slot. Do not apply suggested slot/RAM flags based solely on that explanation.

### Durable memory is becoming a repeated report archive

The five environment notes total roughly **26,600 words**. Four are divergent copies named `operations`, `operations.md`, `improvements`, and `improvements.md`.

Startup context takes the first 2,000 characters of each note, in filename order, within a 6,000-character total. The interrupted execution's preserved startup packet includes `improvements`, `improvements.md`, and `operations`; it omits `operations.md`. Recent lessons are near the ends of these files, outside their excerpts. The earlier GPU/capability discussion continues to dominate the start.

**Fix/tune:** consolidate without losing historical evidence. Keep one compact current operations note and one improvement backlog with resolved/superseded status, and move detailed chronological reports under projects. Make the startup packet deliberately prioritize these current notes while keeping other resources discoverable. Document that `--name` is a literal filename. A larger context allowance would preserve the duplication at additional cost.

### Write-up forces expensive complete-paper replacement

Isolation iteration 3 made **12 successful `write_paper` calls between 21:50 and 22:37**. Most replaced 14,500–18,800 characters. One wrote the literal `placeholder` before the next replacement restored the draft. Submission was attempted only at 22:38.

This is partly agent behavior and partly interface design: write-up removes `edit_file` and exposes only full replacement through `write_paper`. The guidance to make small edits cannot be followed through that interface.

**Fix/tune:** permit small edits to `paper.md` using the existing editing machinery; encourage a valid partial submission before cosmetic polishing. Preserve the previous usable draft through failed/interrupted edits. Changing tool definitions at write-up also causes a recorded cold prefill, so evaluate that transition separately from ordinary cache regressions.

### The actual grid launch did not match the throughput estimate

The Supervisor budgeted the confirmatory grid for parallel execution. The first launch failed with literal replacement commands; the next omitted `-P` and timed out after 1,000 seconds. The paper records 1,199 of 3,456 runs passing the completeness gate, with remaining jobs persisted. The grid was therefore recoverable, but the promised few-minute experiment did not materialize.

**Tune:** verify the actual bounded launch command on a small shard, including concurrency and elapsed time, then reuse it. Preserve receipts and resume completed work. Do not estimate a parallel grid from single-cell runtime while launching it serially.

Across the Supervisor there were 242 unsuccessful tool results in 1,646 calls, including expected probe failures. This is not 242 separate bugs. Clear repeated friction includes seven attempts to explicitly resolve operator-only alerts, missing paths, CLI argument mistakes, and schema assumptions. The compact operations note should retain demonstrated interface facts instead of repeatedly rediscovering them.

## 4. Research results and the Supervisor's suggestions

Useful behavior is visible: the original abstract ideas became a coherent entrenchment line; bottlenecks and isolation became follow-ons; negative/incomplete results were retained; three synthesis publications, including an addendum, were registered. Data rescue preserved work that otherwise remained stuck in write-up. The final interrupted execution also prepared another rescue rather than silently claiming completion.

The scientific checking found real defects:

- The bottleneck paper's `poisson_slope` used the intercept element of the inverse information matrix as the slope variance. The preserved source confirms the wrong `swxx/det` element. The Supervisor supplied a correction and requested revised uncertainty reporting.
- The isolation paper's RMST helper subtracts events twice from the risk set. Extracting its function and applying uncensored times `[1, 2, 10, 100]` returns **38.5**, whereas the correct uncensored mean is **28.25**. The Supervisor's decision to withdraw the affected headline was justified. This check does not independently certify all its replacement bootstrap calculations.

These are valuable interventions. They also show that attractive paper prose and a completed iteration are insufficient acceptance criteria. Require a small reproducible check for a load-bearing numerical claim, using a known case or independent implementation where appropriate. Prefer established routines when available. Keep this scientific validation in the research workflow; a universal hardcoded statistics gate in the harness is a broader and less general solution.

The improvement backlog should be ranked by observed cost:

1. Fix exhausted-write-up dispatch and submission validation.
2. Shorten and filter communications; reduce routine investigation and repeated alert triage.
3. Repair compact memory and reliable project/tool setup.
4. Improve write-up editing/submission and measured experiment launching.
5. Validate important estimators and follow-on protocols before reporting conclusions.
6. Benchmark cache retention changes if measured handoff cost still warrants them.

GPU enablement and additional memory controls were repeatedly proposed, but this run does not establish that either is the leading bottleneck. Much of its time went to inference, analysis, writing, and supervision around comparatively short simulations. Those proposals should remain deferred choices unless a concrete research task needs them. Prose hash scanning may be a useful advisory check, but it cannot validate scientific reproducibility by itself.

Finally, the agent repeatedly says a benign alert needs the user's click because explicit `alert-resolve` is operator-only. Completed executions already mark their inbox items `handled`; the historical rows confirm this. Distinguish automated handling from explicit operator resolution. Keep operator control over critical recovery without manufacturing a manual chore for each recovered warning.

## Before eventual continuation

Leave dispatch stopped while deciding and applying fixes. Reconcile the unregistered harness project `197e58fe-1ad7-4059-b7c2-18f9e97b888d`, its missing external tools, and its incorrect quoting lesson before resuming the interrupted execution or starting a replacement. It contains partial side effects from the expected cutoff, not evidence that it has run. Existing datasets and drafts remain available; a clean restart would discard useful progress and is not necessary for this review's findings.
