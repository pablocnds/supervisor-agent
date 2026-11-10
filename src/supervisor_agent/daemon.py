from __future__ import annotations

import argparse
import asyncio
import fcntl
import grp
import os
import pwd
import signal
import socket
import threading
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from .api import app
from .config import load
from .runtime import Runtime
from .store import Store


class ManagedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # Uvicorn re-raises captured signals on return. The controller must first
        # finish a safe pause, close SQLite, and remove its socket in our finally.
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        for sig in previous:
            signal.signal(sig, self.handle_exit)
        try:
            yield
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


async def serve(config_path):
    config = load(config_path)
    if pwd.getpwuid(os.getuid()).pw_name != config.runtime_user:
        raise RuntimeError(f"Run the daemon as {config.runtime_user}")
    os.umask(0o007)
    config.state_root.mkdir(parents=True, exist_ok=True, mode=0o770)
    with (config.state_root / "daemon.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store = Store(config.state_root)
        runtime = Runtime(config, store)
        config.socket.parent.mkdir(parents=True, exist_ok=True)
        config.socket.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(config.socket))
        os.chown(config.socket, -1, grp.getgrnam(config.operator_group).gr_gid)
        os.chmod(config.socket, 0o660)
        listener.listen(128)
        listener.setblocking(False)
        server = ManagedServer(uvicorn.Config(app(runtime), log_level="info", access_log=False))
        worker = asyncio.create_task(runtime.run())
        try:
            await server.serve(sockets=[listener])
        finally:
            runtime.stopping = True
            runtime.wake.set()
            await worker
            listener.close()
            config.socket.unlink(missing_ok=True)
            store.db.close()


def main():
    parser = argparse.ArgumentParser(description="The Supervisor backend daemon")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.config))
