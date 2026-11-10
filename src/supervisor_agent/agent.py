from __future__ import annotations

import json
import time

import httpx
from jsonschema import validate

from .config import Model, secret, write_json
from .search import SearchTools
from .shell import Shell


class Paused(Exception):
    pass


def tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


BUILTINS = [
    tool(
        "shell",
        "Run a synchronous shell command in the assigned workspace. No shell internet access.",
        {"command": {"type": "string"}, "timeout_seconds": {"type": "number", "exclusiveMinimum": 0}},
        ["command"],
    ),
    tool(
        "communicate",
        "Publish arbitrary Markdown to the user. Metadata is attached automatically.",
        {"markdown": {"type": "string"}},
        ["markdown"],
    ),
]


class Agent:
    def __init__(self, runtime, execution):
        self.runtime, self.store, self.config = runtime, runtime.store, runtime.config
        self.execution = execution
        self.id = execution["id"]
        self.directory = self.store.root / "executions" / self.id
        self.directory.mkdir(exist_ok=True)
        self.path = self.directory / "session.json"
        self.shell = Shell(self.config, self.id, self.directory / "workspace")
        self.started = time.monotonic()
        self.previous_elapsed = execution["elapsed"]
        self.segment_start = self.previous_elapsed
        self.operation = None
        self.last_progress = None
        self.session = json.loads(self.path.read_text()) if self.path.exists() else None
        self.last_reminder = self.session.get("last_reminder", 0) if self.session else 0
        self.model = Model.model_validate(self.session["model"]) if self.session else self.config.model
        self.client = httpx.AsyncClient(
            base_url=self.model.base_url.rstrip("/"),
            headers={"Authorization": "Bearer " + secret(self.model.key_file)},
            timeout=httpx.Timeout(self.model.request_timeout_seconds, connect=10),
        )

    @property
    def elapsed(self):
        return self.previous_elapsed + time.monotonic() - self.started

    def save(self):
        write_json(self.path, self.session)
        with self.store.db:
            self.store.db.execute("UPDATE executions SET elapsed=? WHERE id=?", (self.elapsed, self.id))

    def checkpoint(self):
        reason = self.runtime.pause_reason(self)
        if reason:
            self.save()
            raise Paused(reason)

    async def run(self):
        try:
            async with SearchTools(self.config.search) as search:
                definitions = BUILTINS + await search.definitions()
                if self.session is None:
                    prompt = (
                        self.config.prompt_file.read_text()
                        .replace("{{environment_map}}", self.runtime.environment_map())
                        .replace("{{compact_context}}", f"{self.model.compact_tokens:,}")
                    )
                    if self.execution["kind"] == "delegate":
                        path = self.config.delegate_prompt_file or self.config.prompt_file.with_name(
                            "DELEGATE_PROMPT.md"
                        )
                        prompt += "\n\n" + path.read_text()
                    self.session = {
                        "prompt": prompt,
                        "model": self.model.model_dump(mode="json"),
                        "tools": definitions,
                        "messages": [
                            {
                                "role": "user",
                                "content": json.dumps(
                                    await self.runtime.start_context(self.execution), ensure_ascii=False
                                ),
                            }
                        ],
                        "delivered": [],
                        "previous_input": None,
                        "cache_reset": "new_execution",
                        "compaction_prompt": (
                            self.config.compaction_prompt_file
                            or self.config.prompt_file.with_name("COMPACTION_PROMPT.md")
                        ).read_text(),
                    }
                    self.save()
                if self.session["tools"] != definitions:
                    self.store.event("tool_metadata_changed", {"using_frozen_definitions": True}, self.id)
                definitions = self.session["tools"]
                self.close_interrupted_calls()
                while True:
                    self.checkpoint()
                    self.deliver()
                    await self.compact()
                    self.checkpoint()
                    response = await self.complete()
                    message = response["choices"][0]["message"]
                    assistant = {
                        k: v
                        for k, v in message.items()
                        if k in ("role", "content", "tool_calls", "reasoning_content") and v is not None
                    }
                    assistant["role"] = "assistant"
                    bad_calls = {}
                    for call in assistant.get("tool_calls", []):
                        raw = call["function"]["arguments"]
                        try:
                            parsed = json.loads(raw)
                            if not isinstance(parsed, dict):
                                raise ValueError("Arguments must be an object")
                        except (ValueError, TypeError) as error:
                            bad_calls[call["id"]] = str(error)
                            # Normalize only this unsent message; never rewrite a cached prefix.
                            call["function"]["arguments"] = "{}"
                            self.store.event(
                                "invalid_tool_arguments", {"raw": raw, "call_id": call["id"]}, self.id
                            )
                    self.session["messages"].append(assistant)
                    self.save()
                    calls = assistant.get("tool_calls", [])
                    if not calls:
                        if response["choices"][0].get("finish_reason") == "length":
                            self.session["messages"].append(
                                {"role": "user", "content": "The response was truncated. Continue concisely."}
                            )
                            self.save()
                            continue
                        return assistant.get("content") or ""
                    for call in calls:
                        name = call["function"]["name"]
                        reason = self.runtime.pause_reason(self)
                        if reason:
                            result = {"error": "Not executed: waiting to pause. No side effects occurred."}
                        else:
                            arguments = json.loads(call["function"]["arguments"])
                            self.operation = {"kind": "tool", "name": name, "started": time.monotonic()}
                            self.store.event(
                                "tool_started",
                                {"call_id": call["id"], "name": name, "arguments": arguments},
                                self.id,
                            )
                            try:
                                if call["id"] in bad_calls:
                                    raise ValueError(bad_calls[call["id"]])
                                declared = next(
                                    d["function"] for d in definitions if d["function"]["name"] == name
                                )
                                validate(arguments, declared["parameters"])
                                if name == "shell":
                                    result = await self.shell.run(
                                        arguments["command"], arguments.get("timeout_seconds")
                                    )
                                elif name == "communicate":
                                    result = self.store.communicate(
                                        arguments["markdown"],
                                        self.id,
                                        self.execution["project_id"],
                                        self.execution["inbox_id"],
                                    )
                                else:
                                    result = await search.call(name, arguments)
                            except Exception as error:
                                result = {"is_error": True, "error": f"{type(error).__name__}: {error}"}
                                self.store.alert(
                                    f"tool:{name}:{type(error).__name__}",
                                    f"Tool {name} failed in execution {self.id}: {error}",
                                )
                            self.last_progress = name
                            self.store.event(
                                "tool_finished",
                                {
                                    "call_id": call["id"],
                                    "name": name,
                                    "elapsed_seconds": time.monotonic() - self.operation["started"],
                                    "result": result,
                                },
                                self.id,
                            )
                            self.operation = None
                        payload = json.dumps(result, ensure_ascii=False)
                        if len(payload.encode()) > self.config.shell_output_bytes:
                            path = self.directory / "workspace" / f"result-{call['id']}.json"
                            path.write_text(payload)
                            payload = json.dumps({"full_result": str(path), "preview": payload[:8000]})
                        self.session["messages"].append(
                            {"role": "tool", "tool_call_id": call["id"], "content": payload}
                        )
                        self.save()
                    self.checkpoint()
        finally:
            await self.client.aclose()

    def close_interrupted_calls(self):
        for i in range(len(self.session["messages"]) - 1, -1, -1):
            message = self.session["messages"][i]
            if message.get("tool_calls"):
                done = {
                    m.get("tool_call_id") for m in self.session["messages"][i + 1 :] if m["role"] == "tool"
                }
                for call in message["tool_calls"]:
                    if call["id"] not in done:
                        self.session["messages"].append(
                            {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": "Interrupted: outcome unknown. Inspect actual state before repeating this operation.",
                            }
                        )
                break
        self.save()

    def deliver(self):
        for message in self.store.rows("SELECT * FROM steering WHERE execution_id=? ORDER BY id", (self.id,)):
            if message["id"] not in self.session["delivered"]:
                self.session["messages"].append({"role": "user", "content": "Steering: " + message["text"]})
                self.session["delivered"].append(message["id"])
        threshold = int(self.elapsed // self.config.reminder_seconds)
        if threshold > self.last_reminder:
            self.session["messages"].append(
                {
                    "role": "user",
                    "content": f"Time reminder: {self.elapsed / 60:.1f} minutes running. Last completed tool: "
                    f"{self.last_progress or 'none'}. Spend time proportionately; delegate longer work.",
                }
            )
            self.last_reminder = threshold
            self.session["last_reminder"] = threshold
        self.save()

    def request(self):
        return {
            **self.model.extra,
            "model": self.model.profile,
            "messages": [{"role": "system", "content": self.session["prompt"]}, *self.session["messages"]],
            "tools": self.session["tools"],
            "tool_choice": "auto",
            "temperature": self.model.temperature,
            "max_tokens": self.model.output_tokens,
            "cache_prompt": True,
        }

    async def count(self, request):
        self.checkpoint()
        self.operation = {"kind": "token_count", "started": time.monotonic()}
        try:
            response = await self.client.post("/v1/chat/completions/input_tokens", json=request)
            response.raise_for_status()
            value = response.json()["input_tokens"]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("Invalid model input token count")
            self.store.event(
                "input_counted",
                {"input_tokens": value, "elapsed_seconds": time.monotonic() - self.operation["started"]},
                self.id,
            )
            return value
        finally:
            self.operation = None

    async def compact(self):
        for _ in range(3):
            if await self.count(self.request()) < self.model.compact_tokens:
                return
            messages = self.session["messages"]
            cut = max(1, len(messages) - min(8, max(1, len(messages) // 2)))
            while cut > 1 and messages[cut]["role"] == "tool":
                cut -= 1
            if len(messages) < 2:
                raise RuntimeError("Initial prompt/tool definitions exceed context threshold")
            request = {
                "model": self.model.profile,
                "messages": [
                    {
                        "role": "system",
                        "content": self.session.get("compaction_prompt")
                        or (
                            self.config.compaction_prompt_file
                            or self.config.prompt_file.with_name("COMPACTION_PROMPT.md")
                        ).read_text(),
                    },
                    {"role": "user", "content": json.dumps(messages[:cut], ensure_ascii=False)},
                ],
                "max_tokens": min(4096, self.model.output_tokens),
                "temperature": 0,
                "cache_prompt": True,
            }
            if await self.count(request) + request["max_tokens"] >= self.model.context_window:
                raise RuntimeError("History cannot fit in a compaction request")
            self.operation = {"kind": "compaction", "started": time.monotonic()}
            self.store.event("compaction_started", {}, self.id)
            try:
                response = await self.client.post("/v1/chat/completions", json=request)
                response.raise_for_status()
                self.store.event(
                    "compaction_finished",
                    {
                        "elapsed_seconds": time.monotonic() - self.operation["started"],
                        "usage": response.json().get("usage"),
                        "timings": response.json().get("timings"),
                    },
                    self.id,
                )
            finally:
                self.operation = None
            summary = response.json()["choices"][0]["message"]["content"]
            if not summary:
                raise RuntimeError("Model returned an empty continuation summary")
            self.session["messages"] = [
                {"role": "user", "content": "Prior-session summary:\n" + summary},
                *messages[cut:],
            ]
            self.session["previous_input"] = None
            self.session["cache_reset"] = "compaction"
            self.store.event("context_compacted", {}, self.id)
            self.save()
        raise RuntimeError("Context remains above compaction threshold")

    async def complete(self):
        try:
            return await self.stream_complete()
        except BaseException as error:
            self.store.event(
                "model_failed",
                {
                    "type": type(error).__name__,
                    "elapsed_seconds": time.monotonic() - self.operation["started"]
                    if self.operation
                    else None,
                },
                self.id,
            )
            raise
        finally:
            self.operation = None

    async def stream_complete(self):
        self.checkpoint()
        request = self.request()
        self.operation = {"kind": "model", "started": time.monotonic()}
        self.store.event("model_started", {"profile": self.model.profile}, self.id)
        message = {"role": "assistant", "content": ""}
        calls = {}
        usage, timings, finish_reason = {}, {}, None
        pending = {}
        flushed = time.monotonic()
        async with self.client.stream(
            "POST",
            "/v1/chat/completions",
            json={**request, "stream": True, "stream_options": {"include_usage": True}},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                data = json.loads(line[5:].strip())
                if data.get("usage"):
                    usage = data["usage"]
                if data.get("timings"):
                    timings = data["timings"]
                for choice in data.get("choices", []):
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta", {})
                    for field in ("content", "reasoning_content"):
                        if delta.get(field):
                            message[field] = message.get(field, "") + delta[field]
                            pending[field] = pending.get(field, "") + delta[field]
                    for part in delta.get("tool_calls", []):
                        target = calls.setdefault(
                            part["index"],
                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        if part.get("id"):
                            target["id"] = part["id"]
                        for field in ("name", "arguments"):
                            target["function"][field] += part.get("function", {}).get(field, "")
                if time.monotonic() - flushed >= 1 and pending:
                    self.store.event("model_delta", pending, self.id)
                    pending = {}
                    flushed = time.monotonic()
        if pending:
            self.store.event("model_delta", pending, self.id)
        if not finish_reason:
            raise RuntimeError("Model stream ended without a finish reason")
        if calls:
            message["tool_calls"] = [calls[index] for index in sorted(calls)]
        elapsed = time.monotonic() - self.operation["started"]
        self.operation = None
        previous = self.session["previous_input"]
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        reset = self.session.get("cache_reset")
        self.store.event(
            "model_finished",
            {
                "elapsed_seconds": elapsed,
                "usage": usage,
                "timings": timings,
                "cache_reset": reset,
                "effective_output_tokens_per_second": usage.get("completion_tokens", 0) / max(elapsed, 0.001),
            },
            self.id,
        )
        if previous and not reset:
            if cached is None:
                self.store.event("cache_measurement_unavailable", {}, self.id)
            elif cached < previous * self.model.cache_warning_ratio:
                self.store.alert(
                    "cache:" + self.model.profile,
                    f"Unexpected cache reuse in execution {self.id}: {cached} cached tokens; preceding input {previous}.",
                )
        self.session["previous_input"] = usage.get("prompt_tokens")
        self.session["cache_reset"] = None
        return {"choices": [{"message": message, "finish_reason": finish_reason}]}
