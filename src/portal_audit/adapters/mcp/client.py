"""Disabled-by-default MCP client adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from portal_audit.application.ports.mcp import (
    McpCapabilityPort,
    McpToolDescriptor,
    McpToolResult,
)


class DisabledMcpClient(McpCapabilityPort):
    """Null adapter used when no MCP endpoint has been configured."""

    @property
    def enabled(self) -> bool:
        return False

    async def list_tools(self) -> Sequence[McpToolDescriptor]:
        return ()

    async def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> McpToolResult:
        del server_id, tool_name, arguments
        raise RuntimeError("MCP is disabled; configure an allow-listed MCP adapter first")
