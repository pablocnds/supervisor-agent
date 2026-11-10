from __future__ import annotations

import httpx


class Harness:
    def __init__(self, socket):
        self.client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(socket)), base_url="http://irh", timeout=15
        )

    async def call(self, method, path, data=None):
        response = await self.client.request(method, "/v1/" + path, json=data)
        response.raise_for_status()
        return response.json()

    async def health(self):
        return await self.call("GET", "health")

    async def status(self, item):
        return await self.call("GET", f"projects/{item}")

    async def pause(self, item, reason, actor="supervisor"):
        return await self.call("POST", f"projects/{item}/pause", {"actor": actor, "reason": reason})

    async def start(self, item, resume=False, max_iterations=None, actor="supervisor"):
        return await self.call(
            "POST",
            f"projects/{item}/run",
            {"actor": actor, "resume": resume, "max_iterations": max_iterations},
        )

    async def close(self):
        await self.client.aclose()
