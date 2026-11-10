# Backend validation — 2026-11-10

The backend has not been installed or enabled in production. All supervisor state created for live
smoke checks was temporary and removed afterward. No research project was started, resumed, or changed.

- The automated suite covers cooperative handoff, no concurrent supervisor executions, separate inbox
  and routine tasks, skipped calendar ticks, eight-hour configuration, operator holds, deferred operator
  resumes tied to a specific hold, delegate review boundaries, stopped dispatch, restart recovery,
  durable event receipts, alert grouping, Markdown communication metadata, shell containment, real
  Unix-socket CLI access from the sandbox, append-only steering, compaction boundaries, persisted
  reminders, frozen tool definitions, and critical model failure behavior.
- Lint and shell-script syntax checks pass.
- Native Exa MCP discovery succeeded for `web_search_exa` and `web_fetch_exa`; the smoke check did not
  perform a paid search/fetch request.
- The existing harness API was healthy and idle. Its configured pool profile was present. The initial
  input-token check timed out at 60 seconds; a follow-up with a 180-second allowance succeeded. This
  could reflect startup latency; it is not a throughput benchmark.
- A real model-loop test used the initial prompt and native communication tool, with shell execution
  blocked for that test. It published exactly one Markdown communication and concluded in two model
  requests. Reported cached tokens were 0 on the initial request and 1,308 on the continuation, with no
  cache alert. State and communication files were temporary.
- A packaged release was built using system Python 3.14, with development dependencies excluded.
  Its daemon started disabled, served the Unix API, persisted a deferred inbox message, and exited
  cleanly on SIGTERM with its socket removed. This test used the operator account explicitly in its
  temporary configuration; the production `rh-agent` systemd installation remains an operator step.

Start/resume coordination is exercised with a simulated harness in the automated suite, not by
launching research against the live archive. A real research lifecycle should be observed after the
operator installs the backend and supplies the first research task. Tune the short prompts and settings
listed in [tuning.md](tuning.md) from that evidence.
