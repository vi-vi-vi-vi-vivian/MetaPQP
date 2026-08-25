"""Future MCP server adapter boundary.

The concrete MCP SDK integration will expose only stable application use cases:
submit, status, cancel, and result. It remains unconfigured in the local MVP.
"""

EXPOSED_APPLICATION_TOOLS = (
    "submit_page_audit",
    "get_audit_status",
    "cancel_audit",
    "get_page_assessment",
)
