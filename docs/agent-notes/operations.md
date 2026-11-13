# Operations notebook

Keep this a compact current reference; link project notes for history.

- Catalog IDs differ from harness backend IDs. Startup catalog maps both. Use
  catalog IDs for Supervisor notes/selection and backend IDs for irh.
- Events use integer cursors: `supervisorctl events --after N --limit N` and
  `irh events BACKEND_ID --after N --limit N`. Output is JSON; no --json flag.
- Update this literal filename with `supervisorctl note environment --file FILE
  --name operations.md --replace`; maintain improvements.md the same way.
- Shell calls are synchronous, children die with the call, /tmp is fresh each
  call, and shell internet is disabled. Keep files in the persistent workspace.
  Pipelines propagate failure; shell sequencing does not imply errexit.
- At the last capability check, C++ and Python stdlib worked; research NumPy,
  pip, and ROCm/CUDA did not. Vulkan inference does not imply GPU research support.
  Rediscover capabilities only when requirements or the environment change.
- Only one agent runs. Select next work; dispatch follows execution completion.
  Cooperative Supervisor pauses resume automatically; harness failure pauses
  require a decision. Preserve partial datasets and drafts.
- New projects inherit configured default tools. Check snapshot.enabled_tools
  includes exa/manual; --tool overrides and --no-tools opts out. Existing
  project snapshots stay frozen. There is no irh create --model option.
- Completed inbox executions are handled automatically. alert-resolve is
  operator-only; recovered warnings do not require repeated requests for it.
- Verify the cited instrument/protocol and the actual bounded parallel command.
  xargs -I{} replaces {} with either shell quote style; without -I it does not.
  Freeze confirmatory plans before fresh results; smoke-test key estimators.
