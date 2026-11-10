# Existing Services — Requirements for The Supervisor Integration

- **Scope and implementation order**
  - Update existing services independently before implementing The Supervisor against their interfaces.
  - Keep every service independently runnable and authoritative for its own state; expose integration through its supported CLI/API and durable events.
  - Reuse existing capabilities where sufficient rather than replacing service internals or adding purpose-specific artifact-reading tools.
  - Keep runtime instructions concise and general. Add guidance or restrictions only where observed behavior justifies them.
  - This document specifies prerequisites only; it does not authorize implementation, deployment, or changes to the running services at this stage.

- **Iterative research harness: external lifecycle control**
  - Retain independent project creation, start, pause, resume, status, and event access through the harness CLI/API.
  - Allow The Supervisor to operate those interfaces under the dedicated LLM Unix account, without directly modifying the harness database or private runtime files.
  - Support controlled project stopping/ending and externally directed bounded runs, including a single-iteration investigation that does not silently begin further experimental iterations.
  - Preserve the final reporting/review needed for a bounded run and clearly expose when its execution is finished or awaiting further instruction.
  - Record whether a pause/hold originated with the user, The Supervisor, a time boundary, or a failure, along with its reason.
  - Do not automatically override a user hold when handling an agent-originated resume request.
  - Expose a reliable distinction between a requested pause and an acknowledged quiescent state in which no research agent, model request, or experiment tool remains active.
  - Let The Supervisor coordinate scheduling externally; do not introduce a second global project scheduler inside the harness.

- **Iterative research harness: append-only steering**
  - Accept durable steering messages through the CLI/API for an existing project, including sender/origin and delivery state.
  - Deliver relevant steering to the responsible agent at a completed-turn boundary by appending to its conversation tail.
  - Leave the system prompt, previously sent messages, and existing tool definitions unchanged to preserve the cached conversation prefix.
  - Make pending steering available when the appropriate phase resumes, without losing it across service restarts or applying it repeatedly after successful delivery.
  - Record what steering was delivered and when; preserve original execution snapshots rather than rewriting them to disguise later guidance as initial instructions.
  - Do not change model/tool configuration or deployed code as a side effect of steering; those remain operator-controlled service changes.

- **Iterative research harness: safe pause, resume, and synchronous tools**
  - Preserve session history, workspaces, completed evidence, and checkpoint state during controlled pauses and resumes.
  - Define pause, stop, cancellation, and resume semantics clearly, including what happens to an executing tool or experiment.
  - Support safe yielding for supervisor checks without losing long-running experiment progress or replaying completed side effects unnecessarily.
  - Save completed tool results before yielding and retain valid model tool-call/result history for continuation.
  - Prefer a safe checkpoint or tool-completion boundary when abrupt interruption would discard progress; expose when a requested pause is still waiting for that boundary.
  - Report `waiting to pause` until safe pause is acknowledged. A supervisory trigger does not justify silently terminating a long synchronous call and losing its work.
  - Keep service daemons running after a coordinated pause; global supervisor-stop policy belongs to The Supervisor and must not require stopping independent services.
  - Coordinate the supported tool set with the user's planned removal of the existing asynchronous tool. The new supervisor integration should assume synchronous tools and should not introduce additional asynchronous-job management machinery.
  - Keep tool removal/replacement separate from this integration where its detailed scope has not yet been specified.

- **Iterative research harness: publications and evidence**
  - Retain lightweight iteration reports and experiment evidence while adding a distinct self-contained publication artifact.
  - Allow a publication to consolidate findings from multiple iterations instead of requiring every iteration to become a substantial standalone publication.
  - Include introduction, methods, results, and conclusions, with references to earlier papers where useful.
  - Preserve negative and inconclusive results and make them available for publication in the archive.
  - Preserve publication versions, stable references, and links to supporting iteration reports and selected evidence.
  - Expose publications and artifact references through supported interfaces so The Supervisor can associate them with projects and research lines.
  - Keep global research-line organization in The Supervisor; the harness need not duplicate that catalog.

- **Iterative research harness: timing, context, and monitoring**
  - Produce an agent-facing reminder every 30 minutes of running time, containing elapsed time, available progress, and concise guidance to avoid unnecessary work.
  - Append due reminders at a completed-turn opportunity after an in-flight model/tool operation returns; do not alter earlier conversation text.
  - Keep timing/status observable independently while an agent is blocked in a model request or synchronous tool.
  - Expose bounded progress/events and available request timing, token counts, context size, cached-token counts, and model-speed metrics for lightweight monitoring.
  - Distinguish queueing/loading, prompt processing, generation, tools, and waiting when the underlying measurements support it. Clearly identify aggregate effective throughput when phase-specific timing is unavailable.
  - Give researchers concise awareness of slow prompt prefill, increasing long-context costs, and the current model's marked generation slowdown around 128k context.
  - Avoid treating the maximum supported context size as a desired operating size; make context-management costs and expected cache resets observable.
  - Make the context-management threshold configurable and initially use 96k tokens (98,304) of complete model input, including system prompt and tools. Compact at a valid conversation boundary before an ordinary request would reach that threshold, leaving room for generation within the model's context window.
  - Retain durable findings and recent working context across compaction, and preserve valid tool-call/result ordering. Treat intentional compaction as an expected cache reset rather than an unexpected failure.

- **Iterative research harness: completion and alerts**
  - Expose durable, identifiable events for project completion, controlled pauses, execution failures, critical infrastructure failures, and unexpected cache-reuse failures.
  - Preserve enough event identity and position information for an external consumer to resume after restart without losing or repeatedly handling the same event.
  - Let a separate integration/monitor forward those events into The Supervisor's inbox; the harness must continue operating independently when that consumer is unavailable.
  - Include source service, affected project/session/request where available, event time, and useful diagnostic references in failure/cache events.
  - Distinguish expected cache resets, unexpectedly missing reuse, and unavailable usage measurements; avoid representing every new session or intentional context compaction as a cache failure.
  - Keep repeated-alert grouping and recent investigation history in The Supervisor rather than duplicating its inbox inside the harness.
  - On model unavailability or another critical infrastructure failure, preserve resumable state, log the incident, and expose it for operator intervention; autonomous repair or model fallback is not required.

- **llama-server-pool: model selection, cache behavior, and telemetry**
  - Continue providing configurable model profiles through its existing inference and control APIs.
  - Let The Supervisor initially use the same qwen-3.8-flash-next profile as the research harness; the current harness checkout names it `qwen38-flash-next-q4xl-mtp-agent-128k`.
  - Forward prompt-caching options and the timing/cache-usage information available from the deployed llama-server without stripping or rewriting relevant request history.
  - Enable supported caching and follow ordinary cache-friendly request construction. Observe existing cache metrics during normal continuations and session switching, and investigate unexpected failures when they occur.
  - Do not require a new cache-persistence system, cache reservation scheme, or cache-residency guarantee before implementing the integration.
  - Expose existing health/resource information and relevant model load/unload/failure information to the external monitor through supported APIs or logs.
  - Distinguish pool/model availability, prompt-processing speed, generation speed, and overall request duration where telemetry permits.
  - Do not add a global agent scheduler, autonomous model substitution, or software self-update mechanism to the pool for this integration.
  - Change pool code only if its existing transparent forwarding, telemetry, or cache configuration cannot meet these requirements; verify the deployed llama-server's capabilities before requiring new endpoints or flags.

- **Deployment, permissions, and independent backups**
  - Make current source and environment-project artifacts readable by the dedicated LLM account through operator-configured permissions/mounts, including source paths otherwise hidden by home-directory permissions or service sandboxing.
  - Keep deployed services, their deployment configuration, and source outside agent-writable areas; lifecycle control through supported APIs remains permitted.
  - Permit controlled service access needed for inference, designated search/fetch tools, and lifecycle APIs while restricting ordinary shell internet access.
  - Keep lightweight monitoring and trigger delivery independent from model execution and compatible with one active agent across services.
  - Configure predictable calendar-based supervisor triggers with no intentional randomized delay; provide configurable hours/timezone, initially 00:00/04:00/08:00/12:00/16:00/20:00 UTC.
  - Defer the independent daily backup job until later; it does not block external-service changes or initial supervisor implementation/testing. Eventually cover project/research-line state, the papers/publications archive, and the metadata needed to reconnect them after restore.
  - Prefer a backup service/account and destination inaccessible to agents. Coordinate snapshots of live state and referenced archive artifacts so backups are recoverable.

- **Boundary with new supervisor work**
  - The inbox, routine checks, alert deduplication/history, global execution coordination, research-line catalog, supervisor-delegate runtime, and user communication mechanism belong to The Supervisor backend.
  - `supervisorctl` is The Supervisor's administration interface. Do not add a supervisor-only manual finish/soft-stop-and-continue operation to the external services; ordinary execution completion and appended steering are sufficient.
  - The new supervisor-delegate runtime should use lifecycle semantics equivalent to the harness, including progress-preserving pauses and `waiting to pause`; do not implement a separate delegate runtime inside the harness.
  - No frontend work is required in existing services for this phase; retain backend events and state needed for later display.
  - The two requirements files specify coordinated behavior, not a requirement to implement the same feature independently in each service.
