"""Read-only adapter for the hosted Indiana Code MCP."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_MCP_URL = "https://mcp.openindianalaw.org/mcp"
ALLOWED_TOOLS = (
    "ic_search",
    "ic_resolve_citation",
    "ic_get_section",
    "ic_get_versions",
    "ic_browse",
    "ic_get_act",
    "ic_list_companion",
    "ic_search_companion",
    "ic_get_companion",
    "case_search",
    "case_get",
    "ic_cases_citing",
    "cases_construing",
    "cases_citing_case",
    "cases_cited_in",
    "cases_citing_court",
)

ToolCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class TraceStep:
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class LawGateway:
    """Allowlisted MCP calls with a visible trace."""

    call_tool: ToolCaller
    steps: list[TraceStep] = field(default_factory=list)

    async def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            raise ValueError(f"tool not allowlisted: {name}")
        result = await self.call_tool(name, arguments)
        self.steps.append(TraceStep(tool=name, arguments=arguments, result=result))
        return result

    async def resolve_and_fetch_section(
        self, citation: str, as_of: str | None = None
    ) -> dict[str, Any]:
        resolved = await self.invoke("ic_resolve_citation", {"text": citation})
        citations = resolved.get("citations") or []
        if not citations:
            return {"found": False, "resolved": resolved}
        section_id = citations[0].get("section_id")
        args: dict[str, Any] = {"section_id": section_id}
        if as_of:
            args["as_of"] = as_of
        section = await self.invoke("ic_get_section", args)
        return {"found": bool(section.get("found")), "resolved": resolved, "section": section}


def result_to_dict(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    texts = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            texts.append(text)
    if len(texts) == 1:
        try:
            parsed = json.loads(texts[0])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"text": "\n".join(texts)}


class LiveMcp:
    """One Streamable HTTP session for a research turn."""

    def __init__(self, url: str = DEFAULT_MCP_URL):
        self.url = url
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None
        self.tool_names: list[str] = []

    async def __aenter__(self) -> LiveMcp:
        stack = AsyncExitStack()
        read, write, _session_id = await stack.enter_async_context(streamablehttp_client(self.url))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        self._stack = stack
        self.session = session
        self.tool_names = [tool.name for tool in listed.tools]
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("MCP session is closed")
        result = await self.session.call_tool(name, arguments)
        return result_to_dict(result)


async def live_call(url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with LiveMcp(url) as mcp:
        return await mcp.call(name, arguments)


async def live_list_tools(url: str) -> list[str]:
    async with LiveMcp(url) as mcp:
        return mcp.tool_names
