"""
A client of an MCP server, which hands its tools to any agent: each with
the input its JSON schema describes, called on the server when the model calls
it. An error the server answers with is the tool's answer to the model.

A tool call is stored once it is done, with the agent's conversation: a crash
makes again only a call that had not finished, which the server then sees twice
(moving an issue twice is harmless; a comment may show twice).
"""

import contextlib
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import httpx2
import mcp_types
import restate
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from restate.agents import Tool, ToolCall


class McpClient:
    """A client of the MCP server at ``url``: its tools, asked for the first time they are needed, and its tool calls."""

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url = url
        self.headers = headers or {}
        self._listed: list[mcp_types.Tool] | None = None

    @contextlib.asynccontextmanager
    async def _session(self) -> AsyncGenerator[ClientSession]:
        """A session of its own for each request: simple, and it survives the server restarting."""
        async with (
            httpx2.AsyncClient(headers=self.headers, timeout=httpx2.Timeout(60, read=300)) as http,
            streamable_http_client(self.url, http_client=http) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    async def listed(self) -> list[mcp_types.Tool]:
        if self._listed is None:
            tools: list[mcp_types.Tool] = []
            async with self._session() as session:
                cursor: str | None = None
                while True:
                    page = await session.list_tools(params=mcp_types.PaginatedRequestParams(cursor=cursor))
                    tools += page.tools
                    if not (cursor := page.next_cursor):
                        break
            self._listed = tools
        return self._listed

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Call the tool ``name``; its answer as text, or a terminal error (for the model) if the server says it failed."""
        async with self._session() as session:
            result = await session.call_tool(name, arguments)
        text = "\n".join(
            part.text if isinstance(part, mcp_types.TextContent) else f"[{part.type}]" for part in result.content
        )
        if result.is_error:
            raise restate.TerminalError(text)
        return text

    async def tools(
        self, change: Callable[[mcp_types.Tool, dict[str, Any], ToolCall], dict[str, Any]] | None = None
    ) -> list[Tool]:
        """Its tools, for any agent; ``change`` may rewrite a call's arguments first (to sign a comment, say)."""

        def as_tool(listed: mcp_types.Tool) -> Tool:
            async def run(arguments: dict[str, Any], call: ToolCall) -> str:
                return await self.call(listed.name, change(listed, arguments, call) if change else arguments)

            return make_tool(listed.name, listed.description or listed.name, listed.input_schema, run)

        return [as_tool(listed) for listed in await self.listed()]


def make_tool(
    name: str, description: str, schema: dict[str, Any], run: Callable[[dict[str, Any], ToolCall], Awaitable[Any]]
) -> Tool:
    """A tool whose input is a JSON schema, as an MCP server gives it.

    ``restate.agents.tool`` takes a typed function, which an MCP tool is not; so this builds the ``Tool``
    itself, and leaves checking the arguments to the server, which answers an error the model can act on.
    """
    return Tool(
        name=name, description=description, input_schema=schema, _run=run, _validate=lambda arguments: arguments
    )
