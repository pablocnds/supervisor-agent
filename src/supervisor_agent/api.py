from __future__ import annotations

import sqlite3
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from .config import secret, write_text
from .store import Conflict, now


def bounded_text(value, maximum=32000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Expected nonempty text up to {maximum} characters")
    return value


def actor(request, runtime):
    execution_id = request.headers.get("x-supervisor-execution")
    if execution_id:
        if not runtime.agent or runtime.agent.id != execution_id:
            raise Conflict("Execution is not active")
        return "supervisor", execution_id
    return "operator", None


def app(runtime):
    store = runtime.store

    async def status(request):
        return JSONResponse(runtime.status())

    async def events(request):
        return JSONResponse(
            store.events(
                int(request.query_params.get("after", 0)),
                int(request.query_params.get("limit", 100)),
                request.query_params.get("execution"),
            )
        )

    async def collection(request):
        table = request.path_params["collection"]
        if table not in ("lines", "projects", "inbox", "executions", "communications", "publications"):
            raise KeyError("Unknown collection")
        after = int(request.query_params.get("after", 0))
        limit = min(max(int(request.query_params.get("limit", 100)), 1), 1000)
        rows = store.rows(
            f"SELECT rowid AS cursor,* FROM {table} WHERE rowid>? ORDER BY rowid LIMIT ?", (after, limit)
        )
        return JSONResponse([runtime.project_view(row) for row in rows] if table == "projects" else rows)

    async def detail(request):
        table, item = request.path_params["collection"], request.path_params["id"]
        row = store.one(table, item)
        return JSONResponse(runtime.project_view(row) if table == "projects" else row)

    async def communication(request):
        value = store.one("communications", request.path_params["id"])
        return PlainTextResponse(Path(value["path"]).read_text(), media_type="text/markdown")

    async def notes(request):
        return JSONResponse(store.notes())

    async def note(request):
        path = store.note_path(request.path_params["name"])
        if not path.is_file():
            raise KeyError("Unknown note")
        return PlainTextResponse(path.read_text(), media_type="text/markdown")

    async def pool(request):
        import httpx
        from starlette.responses import StreamingResponse

        path = request.path_params["path"]
        allowed = (
            request.method == "GET"
            and path in ("health", "v1/health", "v1/models", "control/stats", "control/models")
        ) or (
            request.method == "POST"
            and path
            in ("v1/chat/completions", "v1/chat/completions/input_tokens", "v1/completions", "v1/embeddings")
        )
        if not allowed:
            raise Conflict("Pool proxy permits inference and selected status endpoints only")
        client = httpx.AsyncClient(timeout=runtime.config.model.request_timeout_seconds)
        try:
            upstream = await client.send(
                client.build_request(
                    request.method,
                    runtime.config.model.base_url.rstrip("/") + "/" + path,
                    content=await request.body(),
                    headers={
                        "Authorization": "Bearer " + secret(runtime.config.model.key_file),
                        "Content-Type": "application/json",
                    },
                ),
                stream=True,
            )
        except BaseException:
            await client.aclose()
            raise

        async def body():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            body(),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    async def action(request: Request):
        a = await request.json()
        who, execution_id = actor(request, runtime)
        operation = a["operation"]
        if operation == "enable":
            if who != "operator":
                raise Conflict("Only the operator can enable dispatch")
            store.set("enabled", True)
            store.set("critical_failure", None)
            store.set("critical_failure_alert_id", None)
            # Explicit enable acknowledges that interrupted dispatch has been inspected.
            store.set("dispatch_in_flight", None)
            result = runtime.status()
        elif operation == "stop":
            if who != "operator":
                raise Conflict("Only the operator can globally stop dispatch")
            store.set("enabled", False)
            result = runtime.status()
        elif operation == "alert_resolve":
            if who != "operator":
                raise Conflict("Only the operator can resolve an alert explicitly")
            result = store.resolve_alert(a["id"], bounded_text(a["resolution"]))
        elif operation == "tick":
            if who != "operator":
                raise Conflict("Routine triggers are operator operations")
            if runtime.agent and runtime.agent.execution["kind"] != "delegate":
                raise Conflict("A supervisor execution is already active")
            runtime.queue_cycle(routine=True)
            result = {"queued": True}
        elif operation == "message":
            key = bounded_text(a["idempotency_key"], 200) if a.get("idempotency_key") else None
            result = store.enqueue(
                bounded_text(a["text"]),
                who,
                immediate=bool(a.get("immediate")),
                source_key=f"message:{who}:{key}" if key else None,
            )
        elif operation == "steer":
            target = store.one("executions", a["execution_id"])
            if target["state"] not in ("running", "paused", "queued", "failed"):
                raise Conflict("Execution cannot receive steering in its current state")
            with store.db:
                store.db.execute(
                    "INSERT INTO steering(execution_id,text,created_at) VALUES(?,?,?)",
                    (target["id"], bounded_text(a["text"]), now()),
                )
            result = {"queued": True}
        elif operation == "resume_execution":
            if who != "operator":
                raise Conflict("Only the operator can resume an execution manually")
            target = store.one("executions", a["execution_id"])
            if target["state"] not in ("paused", "failed"):
                raise Conflict("Execution is not paused or failed")
            store.execution_state(target["id"], "queued")
            result = store.one("executions", target["id"])
        elif operation == "line_create":
            result = store.create_line(
                bounded_text(a["name"], 500), a.get("description", ""), bool(a.get("meta"))
            )
        elif operation == "line_update":
            store.one("lines", a["id"])
            values = a["values"]
            if not values or set(values) - {"name", "description"}:
                raise ValueError("Only name and description can be updated")
            with store.db:
                store.db.execute(
                    "UPDATE lines SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                    (*values.values(), a["id"]),
                )
            result = store.one("lines", a["id"])
        elif operation == "project_create":
            result = store.create_project(
                bounded_text(a["name"], 500),
                a["backend"],
                a.get("instructions", ""),
                a.get("line_id"),
                a.get("backend_id"),
                int(a.get("priority", 0)),
                a.get("max_iterations"),
            )
        elif operation == "project_update":
            result = store.update_project(a["id"], a["values"], who)
        elif operation in ("project_pause", "project_end", "project_resume"):
            project = store.one("projects", a["id"])
            if project["held"] and who != "operator" and operation == "project_resume":
                raise Conflict("Only the operator can release a user hold")
            if operation == "project_resume":
                if who == "operator" and project["backend"] == "harness":
                    status = await runtime.harness.status(project["backend_id"])
                    pause = status["control"]["pause_request"]
                    store.set(
                        "operator_resume",
                        {"project": project["id"], "pause_id": pause["id"] if pause else None},
                    )
                store.update_project(project["id"], {"status": "pending", "held": 0}, who)
                store.set("next_project", project["id"])
                store.set("selection_explicit", True)
            else:
                store.update_project(
                    project["id"],
                    {
                        "status": "ended" if operation == "project_end" else "paused",
                        "held": 1 if who == "operator" else project["held"],
                    },
                    who,
                )
                if store.get("next_project") == project["id"]:
                    store.set("next_project", None)
                    store.set("selection_explicit", True)
                if project["backend"] == "harness":
                    await runtime.harness.pause(
                        project["backend_id"], "Project paused/ended through The Supervisor", actor=who
                    )
            result = store.one("projects", project["id"])
        elif operation == "select":
            if a.get("project_id"):
                project = store.one("projects", a["project_id"])
                if project["held"] or project["status"] in ("complete", "ended"):
                    raise Conflict("Project is held or finished")
            store.set("next_project", a.get("project_id"))
            store.set("selection_explicit", True)
            result = {"next_project": a.get("project_id")}
        elif operation == "note":
            root = store.research_path(a["kind"], a.get("id"))
            name = a.get("name", "notes.md")
            if not name or Path(name).name != name or name in (".", ".."):
                raise ValueError("Note name must be a filename")
            if (root / name).is_symlink():
                raise ValueError("Notes cannot be symlinks")
            text = bounded_text(a["text"], 4 * 1024 * 1024)
            path = root / name
            previous = path.read_text() if a.get("append", True) and path.exists() else ""
            write_text(path, previous + text + "\n")
            result = {"path": str(root / name)}
        elif operation == "communicate":
            result = store.communicate(
                bounded_text(a["markdown"], 4 * 1024 * 1024),
                execution_id,
                runtime.agent.execution["project_id"] if execution_id else a.get("project_id"),
                runtime.agent.execution["inbox_id"] if execution_id else a.get("request_id"),
            )
        elif operation == "publication_link":
            project = store.one("projects", a["project_id"])
            with store.db:
                store.db.execute(
                    "INSERT OR REPLACE INTO publications VALUES(?,?,?)",
                    (
                        project["id"],
                        bounded_text(a["publication_id"], 200),
                        bounded_text(a["reference"], 4000),
                    ),
                )
            result = {"linked": True}
        else:
            raise ValueError("Unknown operation")
        store.event("control_action", {"operation": operation, "actor": who}, execution_id)
        runtime.wake.set()
        return JSONResponse(result)

    async def error(request, exc):
        code = 409 if isinstance(exc, Conflict) else 404 if isinstance(exc, KeyError) else 400
        return JSONResponse({"error": str(exc)}, code)

    return Starlette(
        routes=[
            Route("/pool/{path:path}", pool, methods=["GET", "POST"]),
            Route("/v1/status", status),
            Route("/v1/events", events),
            Route("/v1/action", action, methods=["POST"]),
            Route("/v1/communications/{id}/markdown", communication),
            Route("/v1/notes", notes),
            Route("/v1/notes/{name}", note),
            Route("/v1/{collection}/{id}", detail),
            Route("/v1/{collection}", collection),
        ],
        exception_handlers={ValueError: error, KeyError: error, sqlite3.IntegrityError: error},
    )
