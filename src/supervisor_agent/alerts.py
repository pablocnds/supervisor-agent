"""Recognize a verified cache recovery after our own exclusive model handoff."""

from datetime import UTC, datetime


class HandoffCache:
    def __init__(self, store, timeout_seconds):
        self.store = store
        self.timeout = timeout_seconds

    def begin(self, project, at, model):
        # Dispatch must not replace an unresolved observation from an earlier run.
        self.flush(project)
        self.store.set("cache_handoff:" + project, {"after": at, "model": model})

    def alert(self, project, event):
        self.store.alert(
            f"harness:{project}:model_prompt_cache_warning",
            f"Harness event model_prompt_cache_warning for project {project}: {event}",
            source_key="harness_event:" + str(event["seq"]),
        )

    def flush(self, project):
        key = "cache_handoff:" + project
        state = self.store.get(key) or {}
        if state.get("pending"):
            self.alert(project, state["pending"])
        self.store.set(key, None)

    def expire(self, project, instant=None):
        state = self.store.get("cache_handoff:" + project) or {}
        if state.get("pending"):
            age = (instant or datetime.now(UTC)) - datetime.fromisoformat(state["pending"]["at"])
            if age.total_seconds() >= self.timeout:
                self.flush(project)

    def observe(self, project, event):
        """Return true only when a warning is already accounted for or being verified.

        We require our own dispatch marker, the first request of that handoff,
        and a subsequent warm request. A cold first request alone is not enough.
        Unverified observations become ordinary alerts on failure, stop or timeout.
        """
        receipt = "handoff_cache_event:" + str(event["seq"])
        if self.store.get(receipt):
            return True
        key = "cache_handoff:" + project
        state = self.store.get(key)
        if not state or event["at"] < state["after"]:
            return False
        kind, data = event["kind"], event.get("data", {})
        pending = state.get("pending")
        if kind == "model_request_started":
            if not state.get("first_request"):
                if data.get("model") != state["model"]:
                    self.flush(project)
                    return False
                state["first_request"] = data.get("request_id")
            elif not pending:
                self.flush(project)
                return False
        elif kind == "model_prompt_cache_warning":
            if (
                data.get("request_id") == state.get("first_request")
                and data.get("reason") == "no_cached_prefix"
                and data.get("cached_input_tokens") == 0
            ):
                state["pending"] = event
                self.store.set(key, state)
                self.store.event("cache_handoff_pending", {"project_id": project, "warning": event})
                self.store.set(receipt, True)
                return True
            self.flush(project)
            return False
        elif kind == "model_request_finished" and pending:
            if data.get("request_id") != pending["data"].get("request_id"):
                expected = pending["data"].get("expected_prefix_tokens")
                cached = data.get("cached_input_tokens")
                if (
                    data.get("ok")
                    and data.get("request_kind") == "agent"
                    and data.get("role") == pending["data"].get("role")
                    and isinstance(expected, int)
                    and expected > 0
                    and isinstance(cached, int)
                    and cached >= expected * 0.8
                ):
                    self.store.event(
                        "cache_handoff_recovered",
                        {
                            "project_id": project,
                            "warning": pending,
                            "recovery_request": data.get("request_id"),
                            "cached_input_tokens": cached,
                        },
                    )
                    self.store.set(key, None)
                else:
                    self.flush(project)
                return False
        elif kind in ("controller_stopped", "operator_intervention_required"):
            self.flush(project)
            return False
        self.store.set(key, state)
        return False
