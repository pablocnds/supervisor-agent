from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def now():
    return datetime.now(UTC).isoformat()


def identifier():
    return uuid.uuid4().hex


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o770)
        for name in ("executions", "research", "communications", "observations"):
            (root / name).mkdir(exist_ok=True)
        self.db = sqlite3.connect(root / "state.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS receipts(key TEXT PRIMARY KEY,inbox_id TEXT NOT NULL);
        INSERT OR IGNORE INTO settings VALUES('enabled','false');
        CREATE TABLE IF NOT EXISTS lines(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,
          meta INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS projects(
          id TEXT PRIMARY KEY,line_id TEXT REFERENCES lines(id),name TEXT NOT NULL,
          backend TEXT NOT NULL,backend_id TEXT UNIQUE,instructions TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',
          held INTEGER NOT NULL DEFAULT 0,max_iterations INTEGER,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inbox(
          id TEXT PRIMARY KEY,origin TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,
          fingerprint TEXT,occurrences INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',immediate INTEGER NOT NULL DEFAULT 0,
          execution_id TEXT);
        CREATE TABLE IF NOT EXISTS executions(
          id TEXT PRIMARY KEY,kind TEXT NOT NULL,task TEXT NOT NULL,project_id TEXT REFERENCES projects(id),
          inbox_id TEXT UNIQUE REFERENCES inbox(id),state TEXT NOT NULL DEFAULT 'queued',
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL,elapsed REAL NOT NULL DEFAULT 0,
          delivered TEXT NOT NULL DEFAULT '[]',error TEXT);
        CREATE TABLE IF NOT EXISTS steering(
          id INTEGER PRIMARY KEY,execution_id TEXT NOT NULL REFERENCES executions(id),
          text TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS communications(
          id TEXT PRIMARY KEY,created_at TEXT NOT NULL,execution_id TEXT,project_id TEXT,
          request_id TEXT,path TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS publications(
          project_id TEXT NOT NULL REFERENCES projects(id),publication_id TEXT NOT NULL,reference TEXT NOT NULL,
          PRIMARY KEY(project_id,publication_id));
        CREATE TABLE IF NOT EXISTS events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,execution_id TEXT,kind TEXT NOT NULL,data TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS event_no_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT,'append-only'); END;
        CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON events
          BEGIN SELECT RAISE(ABORT,'append-only'); END;
        """)

    @contextmanager
    def transaction(self):
        with self.db:
            yield self.db

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, table, item):
        if table not in {"lines", "projects", "inbox", "executions", "communications"}:
            raise ValueError("Invalid collection")
        rows = self.rows(f"SELECT * FROM {table} WHERE id=?", (item,))
        if not rows:
            raise KeyError(f"Unknown {table}: {item}")
        return rows[0]

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def event(self, kind, data, execution_id=None):
        with self.db:
            self.db.execute(
                "INSERT INTO events(at,execution_id,kind,data) VALUES(?,?,?,?)",
                (now(), execution_id, kind, json.dumps(data)),
            )

    def events(self, after=0, limit=100, execution_id=None):
        result = self.rows(
            "SELECT * FROM events WHERE seq>? AND (? IS NULL OR execution_id=?) ORDER BY seq LIMIT ?",
            (after, execution_id, execution_id, min(max(limit, 1), 1000)),
        )
        for row in result:
            row["data"] = json.loads(row["data"])
        return result

    def enqueue(
        self, text, origin="operator", kind="message", immediate=False, fingerprint=None, source_key=None
    ):
        with self.db:
            if source_key:
                receipt = self.db.execute(
                    "SELECT inbox_id FROM receipts WHERE key=?", (source_key,)
                ).fetchone()
                if receipt:
                    return self.one("inbox", receipt[0])
            if fingerprint:
                existing = self.rows(
                    "SELECT * FROM inbox WHERE fingerprint=? AND state IN ('pending','assigned')",
                    (fingerprint,),
                )
                if existing:
                    item = existing[0]
                    self.db.execute(
                        "UPDATE inbox SET occurrences=occurrences+1,text=?,updated_at=? WHERE id=?",
                        (text, now(), item["id"]),
                    )
                    if source_key:
                        self.db.execute("INSERT INTO receipts VALUES(?,?)", (source_key, item["id"]))
                    return self.one("inbox", item["id"])
            item = identifier()
            self.db.execute(
                """INSERT INTO inbox
                (id,origin,kind,text,fingerprint,created_at,updated_at,immediate) VALUES(?,?,?,?,?,?,?,?)""",
                (item, origin, kind, text, fingerprint, now(), now(), immediate),
            )
            if source_key:
                self.db.execute("INSERT INTO receipts VALUES(?,?)", (source_key, item))
        self.event("inbox_received", {"id": item, "origin": origin, "kind": kind})
        return self.one("inbox", item)

    def alert(self, fingerprint, text, critical=False, source_key=None):
        value = self.enqueue(text, "system", "alert", fingerprint=fingerprint, source_key=source_key)
        self.event(
            "alert", {"id": value["id"], "fingerprint": fingerprint, "text": text, "critical": critical}
        )
        if critical:
            self.set("enabled", False)
            self.set("critical_failure", text)
        return value

    def create_execution(self, kind, task, project_id=None, inbox_id=None):
        item = identifier()
        with self.db:
            self.db.execute(
                """INSERT INTO executions
                (id,kind,task,project_id,inbox_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)""",
                (item, kind, task, project_id, inbox_id, now(), now()),
            )
            if inbox_id:
                self.db.execute(
                    "UPDATE inbox SET state='assigned',execution_id=? WHERE id=?", (item, inbox_id)
                )
        return self.one("executions", item)

    def execution_state(self, item, state, elapsed=None, error=None):
        with self.db:
            self.db.execute(
                "UPDATE executions SET state=?,updated_at=?,elapsed=COALESCE(?,elapsed),error=? WHERE id=?",
                (state, now(), elapsed, error, item),
            )
            if state == "completed":
                self.db.execute("UPDATE inbox SET state='handled' WHERE execution_id=?", (item,))
        self.event("execution_" + state, {"error": error}, item)

    def recover(self):
        active = self.rows("SELECT * FROM executions WHERE state='running'")
        for execution in active:
            self.execution_state(
                execution["id"], "paused", error="Daemon stopped; inspect outstanding tool effects"
            )
        if active or self.get("dispatch_in_flight"):
            self.alert(
                "unclean_restart",
                "Execution or dispatch was interrupted. Inspect state before enabling/resuming.",
                True,
            )

    def research_path(self, kind, item):
        self.one("lines" if kind == "line" else "projects", item)
        path = self.root / "research" / ("lines" if kind == "line" else "projects") / item
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_line(self, name, description="", meta=False):
        item = identifier()
        with self.db:
            self.db.execute("INSERT INTO lines VALUES(?,?,?,?)", (item, name, description, meta))
        self.research_path("line", item)
        return self.one("lines", item)

    def create_project(
        self, name, backend, instructions="", line_id=None, backend_id=None, priority=0, max_iterations=None
    ):
        if backend not in ("harness", "delegate"):
            raise ValueError("backend must be harness or delegate")
        if backend == "harness" and not backend_id:
            raise ValueError("harness projects require a harness project ID")
        if backend == "delegate" and not line_id:
            raise ValueError("delegates require a meta-research line")
        if max_iterations is not None and max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if line_id:
            line = self.one("lines", line_id)
            if backend == "delegate" and not line["meta"]:
                raise ValueError("supervisor-delegate is restricted to meta-research lines")
        item = identifier()
        with self.db:
            self.db.execute(
                """INSERT INTO projects
              (id,line_id,name,backend,backend_id,instructions,priority,max_iterations,created_at)
              VALUES(?,?,?,?,?,?,?,?,?)""",
                (item, line_id, name, backend, backend_id, instructions, priority, max_iterations, now()),
            )
        self.research_path("project", item)
        return self.one("projects", item)

    def update_project(self, item, values, actor="operator"):
        current = self.one("projects", item)
        allowed = {"line_id", "name", "instructions", "priority", "status", "held", "max_iterations"}
        if not values or set(values) - allowed:
            raise ValueError("Unsupported project fields")
        if "held" in values and (type(values["held"]) not in (int, bool) or values["held"] not in (0, 1)):
            raise ValueError("held must be boolean or 0/1")
        if "priority" in values and type(values["priority"]) is not int:
            raise ValueError("priority must be an integer")
        if values.get("max_iterations") is not None and type(values["max_iterations"]) is not int:
            raise ValueError("max_iterations must be an integer or null")
        for name in ("name", "instructions"):
            if name in values and not isinstance(values[name], str):
                raise ValueError(f"{name} must be text")
        if current["held"] and values.get("held") == 0 and actor != "operator":
            raise Conflict("Only an operator can release a user hold")
        if values.get("status", current["status"]) not in (
            "pending",
            "running",
            "paused",
            "complete",
            "ended",
        ):
            raise ValueError("Invalid project status")
        if values.get("max_iterations") is not None and values["max_iterations"] < 1:
            raise ValueError("max_iterations must be positive")
        if values.get("line_id"):
            line = self.one("lines", values["line_id"])
            if current["backend"] == "delegate" and not line["meta"]:
                raise ValueError("Delegates require a meta-research line")
        elif "line_id" in values and current["backend"] == "delegate":
            raise ValueError("Delegates require a meta-research line")
        with self.db:
            fields = ",".join(f"{key}=?" for key in values)
            self.db.execute(f"UPDATE projects SET {fields} WHERE id=?", (*values.values(), item))
        return self.one("projects", item)

    def communicate(self, markdown, execution_id=None, project_id=None, request_id=None):
        item = identifier()
        path = self.root / "communications" / f"{item}.md"
        path.write_text(markdown)
        with self.db:
            self.db.execute(
                "INSERT INTO communications VALUES(?,?,?,?,?,?)",
                (item, now(), execution_id, project_id, request_id, str(path)),
            )
        self.event("communication", {"id": item, "path": str(path)}, execution_id)
        return self.one("communications", item)
