from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx


def parser():
    p = argparse.ArgumentParser(
        description="Administer The Supervisor; all operations use its Unix-socket API."
    )
    p.add_argument(
        "--socket", default=os.environ.get("SUPERVISOR_SOCKET", "/var/lib/supervisor-agent/daemon.sock")
    )
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("status", "enable", "stop", "tick"):
        sub.add_parser(name)
    resolve = sub.add_parser("alert-resolve", help="Resolve an investigated alert without enabling dispatch")
    resolve.add_argument("id")
    resolve.add_argument("resolution")
    message = sub.add_parser(
        "message", help="Send unstructured notes; --now triggers handling, otherwise defer to next tick"
    )
    message.add_argument("text")
    message.add_argument("--now", action="store_true")
    steer = sub.add_parser("steer")
    steer.add_argument("execution_id")
    steer.add_argument("text")
    resume = sub.add_parser(
        "resume-execution", help="Queue a saved execution; enable dispatch separately if stopped"
    )
    resume.add_argument("execution_id")
    select = sub.add_parser(
        "select", help="Select next project after this execution; use 'idle' to select no work"
    )
    select.add_argument("project_id")
    events = sub.add_parser("events", help="Read a cursor-bounded live transcript/event feed")
    events.add_argument("--after", type=int, default=0)
    events.add_argument("--limit", type=int, default=100)
    events.add_argument("--execution")
    listing = sub.add_parser("list")
    listing.add_argument(
        "collection", choices=["lines", "projects", "inbox", "executions", "communications", "publications"]
    )
    listing.add_argument("--after", type=int, default=0)
    listing.add_argument("--limit", type=int, default=100)
    show = sub.add_parser("show")
    show.add_argument("collection", choices=["lines", "projects", "inbox", "executions", "communications"])
    show.add_argument("id")
    line = sub.add_parser("line-add")
    line.add_argument("name")
    line.add_argument("--description", default="")
    line.add_argument("--meta", action="store_true")
    project = sub.add_parser("project-add")
    project.add_argument("name")
    project.add_argument("--backend", choices=["harness", "delegate"], required=True)
    project.add_argument("--line", dest="line_id")
    project.add_argument("--harness-id", dest="backend_id")
    project.add_argument("--instructions-file", type=Path)
    project.add_argument("--priority", type=int, default=0)
    project.add_argument("--max-iterations", type=int)
    edit = sub.add_parser("update", help="Update a line/project's operational metadata")
    edit.add_argument("kind", choices=["line", "project"])
    edit.add_argument("id")
    edit.add_argument("values", help='JSON object, e.g. {"priority":10}')
    for name in ("project-pause", "project-resume", "project-end"):
        action = sub.add_parser(name)
        action.add_argument("id")
    note = sub.add_parser("note", help="Write free-form research Markdown through the controller")
    note.add_argument("kind", choices=["line", "project"])
    note.add_argument("id")
    note.add_argument("--file", type=Path, required=True)
    note.add_argument("--name", default="notes.md")
    note.add_argument("--replace", action="store_true")
    communication = sub.add_parser("communicate")
    communication.add_argument("--file", type=Path, required=True)
    link = sub.add_parser("publication-link")
    link.add_argument("project_id")
    link.add_argument("publication_id")
    link.add_argument("reference", help="Archive path or service API reference")
    return p


def request_from(args):
    command = args.command
    if command in ("status", "events", "list", "show"):
        path = (
            "status"
            if command == "status"
            else "events"
            if command == "events"
            else args.collection + ("/" + args.id if command == "show" else "")
        )
        params = {key: getattr(args, key) for key in ("after", "limit", "execution") if hasattr(args, key)}
        return "GET", path, params
    data = {
        k: str(v) if isinstance(v, Path) else v
        for k, v in vars(args).items()
        if k not in ("socket", "command") and v is not None
    }
    operation = command.replace("-", "_")
    if command in ("line-add", "project-add"):
        operation = command.removesuffix("-add") + "_create"
    if command == "project-add":
        data["instructions"] = args.instructions_file.read_text() if args.instructions_file else ""
        data.pop("instructions_file", None)
    if command == "message":
        data["immediate"] = data.pop("now")
    if command == "select" and args.project_id == "idle":
        data["project_id"] = None
    if command == "update":
        operation = args.kind + "_update"
        data = {"id": args.id, "values": json.loads(args.values)}
    if command in ("note", "communicate"):
        data.pop("file")
        data["markdown" if command == "communicate" else "text"] = args.file.read_text()
    if command == "note":
        data["append"] = not data.pop("replace")
    return "POST", "action", {"operation": operation, **data}


def main():
    args = parser().parse_args()
    try:
        method, path, data = request_from(args)
        execution_id = os.environ.get("SUPERVISOR_EXECUTION_ID")
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=args.socket),
            base_url="http://supervisor",
            timeout=30,
            headers={"x-supervisor-execution": execution_id} if execution_id else {},
        ) as client:
            response = client.request(
                method, "/v1/" + path, **({"params": data} if method == "GET" else {"json": data})
            )
            if response.is_error:
                raise RuntimeError(response.text)
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except (ValueError, OSError, httpx.HTTPError, RuntimeError) as error:
        raise SystemExit(f"supervisorctl: {error}") from error
