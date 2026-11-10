# Operations notebook

Baseline observed on 2026-11-10; update facts when the environment changes.

- Supervisor catalog IDs and harness backend IDs differ. Startup `catalog` lists
  both. Use the catalog ID for project notes/priority/selection and backend_id for `irh`.
- `supervisorctl events --after INTEGER --limit N` and
  `irh events HARNESS_ID --after INTEGER --limit N` use integer sequence cursors,
  not timestamps. Harness events take a positional ID, not `--project`.
- `supervisorctl note environment --file FILE --name operations.md --replace`
  updates this notebook; project notes use `note project CATALOG_ID`.
- Shell calls have fresh `/tmp`, process namespaces, and no shell internet.
  Use the persistent execution workspace, run batches in the foreground, and
  retain per-cell receipts. Pipelines propagate failure; SIGPIPE from intentional
  output clipping may be expected. No `errexit` is imposed.
- The Supervisor Python environment and harness `/usr/bin/python3` differ.
  NumPy/pip and CUDA/ROCm were unavailable to research shells at the last check;
  C compilation and Python's standard library worked. Do not repeat broad
  dependency probes without a changed requirement. Model inference uses Vulkan;
  that does not establish a usable GPU research stack inside the sandbox.
- Research and supervision share exclusive execution. Choose next work with
  `supervisorctl select`; dispatch occurs after the current execution finishes.

Read the service docs only for interfaces you actually need. Record new durable
operational facts here so subsequent tasks can reuse them.
