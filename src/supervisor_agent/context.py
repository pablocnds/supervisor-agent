"""Small observations for starting a task; full evidence stays in service APIs/files."""


def harness_brief(snapshot, tracked):
    projects = {}
    for item, status in snapshot.get("projects", {}).items():
        control = status["control"]
        value = {"name": status["name"], "phase": status["phase"], "state": control["state"]}
        if item in tracked or control["state"] in ("running", "waiting_to_pause"):
            run = control.get("run") or {}
            value["run"] = {k: run.get(k) for k in ("id", "state", "iterations_completed", "max_iterations")}
            pause = control.get("pause_request") or {}
            value["pause"] = {k: pause.get(k) for k in ("actor", "reason")}
            usage = status.get("model_usage", {})
            activity = usage.get("activity", {})
            latest = activity.get("latest_request") or {}
            data = latest.get("data", {})
            value["model"] = {
                "state": activity.get("state"),
                "last_request_at": latest.get("at"),
                **{
                    k: data.get(k)
                    for k in (
                        "ok",
                        "request_kind",
                        "elapsed_seconds",
                        "input_tokens",
                        "output_tokens",
                        "cached_input_tokens",
                        "effective_output_tokens_per_second",
                    )
                },
                "provider_timings": data.get("timings"),
                "totals": usage.get("totals", {}),
            }
            operation = control.get("current_operation") or {}
            value["operation"] = {k: operation.get(k) for k in ("kind", "started_at", "role", "tool")}
        projects[item] = value
    return {"health": snapshot.get("health", {}), "projects": projects}


def changes_since(previous, current):
    before = (previous or {}).get("harness", {}).get("projects", {})
    after = current["projects"]
    return {
        "previous_execution_id": (previous or {}).get("execution_id"),
        "previous_finished_at": (previous or {}).get("finished_at"),
        "changed_projects": [item for item in after if after[item] != before.get(item)],
        "unchanged_projects": [item for item in after if after[item] == before.get(item)],
        "removed_projects": [item for item in before if item not in after],
    }
