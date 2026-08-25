from portal_audit.adapters.mcp.client import DisabledMcpClient


def test_mcp_is_disabled_by_default() -> None:
    assert DisabledMcpClient().enabled is False
