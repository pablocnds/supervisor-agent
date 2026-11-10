"""Offline, same-filesystem archival of both services before a clean start."""

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def credential_paths(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("key_file", "api_key_file") and isinstance(item, str):
                yield Path(item)
            elif key == "header_files" and isinstance(item, dict):
                yield from (Path(path) for path in item.values())
            else:
                yield from credential_paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from credential_paths(item)


def write_owned(path, content, uid, gid, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.chown(path, uid, gid)
    path.chmod(mode)


def archive_and_reset(
    supervisor, harness, archive, *, service_uid, service_gid, operator_uid, operator_gid, metadata=None
):
    roots = (Path(supervisor), Path(harness))
    archive = Path(archive)
    if archive.exists():
        raise ValueError("Archive already exists; inspect the previous attempt before resetting again")
    configs = {root: json.loads((root / "config.json").read_text()) for root in roots}
    if Path(configs[roots[0]]["state_root"]) != roots[0] or Path(configs[roots[1]]["data_root"]) != roots[1]:
        raise ValueError("Configuration does not name the state roots being archived")
    archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chown(archive.parent, operator_uid, operator_gid)
    archive.parent.chmod(0o700)
    if any(root.stat().st_dev != archive.parent.stat().st_dev for root in roots):
        raise ValueError("Archival requires a same-filesystem rename; no implicit large copy is allowed")
    credentials = {}
    for config in configs.values():
        for path in credential_paths(config):
            for root in roots:
                if path.is_relative_to(root):
                    if not stat.S_ISREG(path.lstat().st_mode):
                        raise ValueError("State credentials must be regular files")
                    credentials[path] = (path.read_bytes(), path.stat().st_mode & 0o660)
    operations = roots[0] / "notes/operations.md"
    operations_text = operations.read_bytes() if operations.is_file() else None
    # Check both databases before moving either tree. Services must already be stopped.
    database_info = {}
    for root in roots:
        path = root / "state.sqlite3"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError(f"Database integrity check failed: {root}")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("projects", "executions", "inbox", "publications")
                if table in tables
            }
        database_info[str(root)] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "counts": counts}
    archive.mkdir(mode=0o700)
    os.chown(archive, operator_uid, operator_gid)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "complete": False,
        "path_mapping": {str(root): str(archive / root.name) for root in roots},
        "databases": database_info,
        "metadata": metadata or {},
    }

    def save_manifest():
        write_owned(
            archive / "manifest.json",
            (json.dumps(manifest, indent=2) + "\n").encode(),
            operator_uid,
            operator_gid,
            0o600,
        )

    save_manifest()
    for root in roots:
        root.rename(archive / root.name)
    for root in roots:
        root.mkdir(mode=0o2770)
        os.chown(root, service_uid, service_gid)
        root.chmod(0o2770)
        config = configs[root]
        if root == roots[0]:
            config["hidden_paths"] = list(
                dict.fromkeys([*config.get("hidden_paths", []), str(archive.parent)])
            )
        write_owned(
            root / "config.json",
            (json.dumps(config, indent=2) + "\n").encode(),
            service_uid,
            service_gid,
            0o640,
        )
    for path, (content, mode) in credentials.items():
        write_owned(path, content, service_uid, service_gid, mode)
    if operations_text is not None:
        operations.parent.mkdir(exist_ok=True)
        os.chown(operations.parent, service_uid, service_gid)
        operations.parent.chmod(0o2770)
        write_owned(operations, operations_text, service_uid, service_gid, 0o660)
    manifest["complete"] = True
    save_manifest()
    return manifest
