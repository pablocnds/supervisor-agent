from contextlib import AsyncExitStack

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from .config import secret


class SearchTools:
    def __init__(self, config):
        self.config = config
        self.stack = AsyncExitStack()
        self.client = None

    async def __aenter__(self):
        try:
            if self.config:
                http = await self.stack.enter_async_context(
                    create_mcp_http_client(headers={"x-api-key": secret(self.config.key_file)})
                )
                self.client = await self.stack.enter_async_context(
                    Client(
                        streamable_http_client(self.config.url, http_client=http), read_timeout_seconds=300
                    )
                )
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def definitions(self):
        definitions = []
        if self.client:
            cursor = None
            while True:
                page = await self.client.list_tools(cursor=cursor)
                for tool in page.tools:
                    if tool.name in self.config.tools:
                        definitions.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": "search__" + tool.name,
                                    "description": tool.description or tool.name,
                                    "parameters": tool.input_schema,
                                },
                            }
                        )
                cursor = page.next_cursor
                if cursor is None:
                    break
            found = {d["function"]["name"].removeprefix("search__") for d in definitions}
            if found != set(self.config.tools):
                raise RuntimeError("Configured search tools were not all discovered")
        return sorted(definitions, key=lambda item: item["function"]["name"])

    async def call(self, name, arguments):
        result = await self.client.call_tool(name.removeprefix("search__"), arguments)
        return {
            "content": [block.model_dump(mode="json") for block in result.content],
            "structured": result.structured_content,
            "is_error": bool(result.is_error),
        }

    async def __aexit__(self, *args):
        await self.stack.aclose()
