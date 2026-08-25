"""Framework-independent MCP capability boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class McpToolDescriptor:
    """Machine-readable metadata for one allow-listed external MCP tool."""

    server_id: str
    tool_name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class McpToolResult:
    """Normalized result returned to the audit application."""

    content: Sequence[Mapping[str, Any]]
    is_error: bool = False


class McpCapabilityPort(Protocol):
    """Optional outbound port for consuming external MCP capabilities."""

    @property
    def enabled(self) -> bool: ...

    async def list_tools(self) -> Sequence[McpToolDescriptor]: ...

    async def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> McpToolResult: ...
