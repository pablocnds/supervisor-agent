from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path


class Shell:
    def __init__(self, config, execution_id, workspace):
        self.config, self.execution_id, self.workspace = config, execution_id, workspace
        workspace.mkdir(parents=True, exist_ok=True)

    def arguments(self, command):
        c = self.config
        # A private PID namespace prevents /proc/<host-pid>/root from bypassing the read-only mounts.
        args = [
            str(c.bwrap),
            "--die-with-parent",
            "--new-session",
            "--unshare-user-try",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-net",
            "--cap-drop",
            "ALL",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
        for device in ("/dev/dri", "/dev/kfd"):
            if Path(device).exists():
                args += ["--dev-bind", device, device]
        # State and the control socket also remain visible when testing under /tmp.
        args += ["--ro-bind", str(c.state_root), str(c.state_root)]
        if c.socket.exists():
            args += ["--ro-bind", str(c.socket), str(c.socket)]
        for path in c.hidden_paths:
            if path.exists():
                args += ["--tmpfs", str(path)] if path.is_dir() else ["--ro-bind", "/dev/null", str(path)]
        # Hide credentials even though the controller uses them for inference/search.
        for path in [c.model.key_file, *([c.search.key_file] if c.search else [])]:
            if path.exists():
                args += ["--ro-bind", "/dev/null", str(path)]
        args += [
            "--bind",
            str(self.workspace),
            str(self.workspace),
            "--clearenv",
            "--setenv",
            "PATH",
            str(Path(sys.executable).parent) + ":" + os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "--setenv",
            "HOME",
            str(self.workspace),
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--setenv",
            "SUPERVISOR_SOCKET",
            str(c.socket),
            "--setenv",
            "SUPERVISOR_EXECUTION_ID",
            self.execution_id,
            "--chdir",
            str(self.workspace),
            "--",
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-o",
            "pipefail",
            "-c",
            command,
        ]
        return args

    async def run(self, command, timeout=None):
        process = await asyncio.create_subprocess_exec(
            *self.arguments(command),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        output = bytearray()
        truncated = False

        async def read():
            nonlocal truncated
            while chunk := await process.stdout.read(8192):
                output.extend(chunk)
                overflow = len(output) - self.config.shell_output_bytes
                if overflow > 0:
                    del output[:overflow]
                    truncated = True

        reader = asyncio.create_task(read())
        try:
            await asyncio.wait_for(process.wait(), timeout)
            await reader
        finally:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            await reader
        return {
            "exit_code": process.returncode,
            "output": output.decode(errors="replace"),
            "truncated": truncated,
        }
