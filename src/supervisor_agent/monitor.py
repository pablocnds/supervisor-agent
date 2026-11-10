"""Temporary, read-only tailnet monitor. Never forwards administrative operations."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from importlib.resources import files

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route


def create_app(supervisor_socket, harness_socket):
    @asynccontextmanager
    async def lifespan(app):
        async with (
            httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(supervisor_socket)),
                base_url="http://supervisor",
                timeout=15,
            ) as supervisor,
            httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(harness_socket)), base_url="http://irh", timeout=15
            ) as harness,
        ):
            app.state.supervisor, app.state.harness = supervisor, harness
            yield

    async def index(request):
        return HTMLResponse(
            files("supervisor_agent").joinpath("monitor.html").read_text(),
            headers={"Cache-Control": "no-store"},
        )

    async def forward(request, client, path, params=None):
        try:
            upstream = await client.get(path, params=params)
            return Response(
                upstream.content,
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "application/json"),
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
        except httpx.HTTPError as error:
            return JSONResponse({"error": f"Upstream unavailable: {type(error).__name__}"}, 503)

    async def collection(request):
        name = request.path_params["name"]
        if name not in {
            "status",
            "events",
            "lines",
            "projects",
            "executions",
            "inbox",
            "communications",
            "publications",
            "notes",
        }:
            return JSONResponse({"error": "Unknown read-only collection"}, 404)
        params = {
            key: value
            for key, value in request.query_params.items()
            if key in {"after", "limit", "execution"}
        }
        return await forward(request, request.app.state.supervisor, "/v1/" + name, params)

    async def communication(request):
        return await forward(
            request,
            request.app.state.supervisor,
            f"/v1/communications/{request.path_params['item']}/markdown",
        )

    async def note(request):
        from urllib.parse import quote

        return await forward(
            request, request.app.state.supervisor, "/v1/notes/" + quote(request.path_params["name"], safe="")
        )

    async def harness_projects(request):
        return await forward(request, request.app.state.harness, "/v1/projects")

    async def harness_collection(request):
        name, item = request.path_params["name"], request.path_params["item"]
        if name not in {"events", "publications", "artifacts", "status"}:
            return JSONResponse({"error": "Unknown harness view"}, 404)
        suffix = "" if name == "status" else "/" + name
        params = {key: value for key, value in request.query_params.items() if key in {"after", "limit"}}
        return await forward(request, request.app.state.harness, f"/v1/projects/{item}{suffix}", params)

    async def paper(request):
        item, publication = request.path_params["item"], request.path_params["publication"]
        return await forward(
            request,
            request.app.state.harness,
            f"/v1/projects/{item}/publications/{publication}/files/paper.md",
        )

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/", index),
            Route("/data/communication/{item}", communication),
            Route("/data/note/{name}", note),
            Route("/data/{name}", collection),
            Route("/harness/projects", harness_projects),
            Route("/harness/{item}/publications/{publication}/paper", paper),
            Route("/harness/{item}/{name}", harness_collection),
        ],
    )


def main():
    parser = argparse.ArgumentParser(
        description="Temporary read-only monitor; bind only to loopback or your tailnet IP"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--socket", default="/var/lib/supervisor-agent/daemon.sock")
    parser.add_argument("--harness-socket", default="/var/lib/iterative-research-harness/daemon.sock")
    args = parser.parse_args()
    uvicorn.run(
        create_app(args.socket, args.harness_socket),
        host=args.host,
        port=args.port,
        access_log=False,
        log_level="info",
    )
